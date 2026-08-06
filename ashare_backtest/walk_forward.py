# -*- coding: utf-8 -*-
"""
walk_forward.py - 滚动窗口 walk-forward 验证
=============================================
将回测窗口切分为多个子窗口, 检验策略在不同时间段的稳定性,
排除单一窗口过拟合。

用法:
  python3 walk_forward.py                    # 默认 3 年训练 + 1 年测试, 滚动
  python3 walk_forward.py --train 5 --test 2 # 5 年训练 + 2 年测试
  python3 walk_forward.py --compare          # 对比 costs=True vs costs=False

依赖 backtest_engine.run() 的 eval_lo/eval_hi 切片评估能力。
"""
import os
import sys
import json
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from backtest_engine import run, load_panel, DEF16, OFF4, CORE_SUB, HS300, DC_INDICES


def walk_forward(panel_path=None, train_years=3, test_years=1,
                 offense_mode="momentum", momentum_lookback=26, use_tech=True,
                 core_satellite=True, core_frac=0.5, death_cross=True,
                 trend_filter=True, costs=True, **run_kwargs):
    """滚动 walk-forward 验证.

    将面板数据按 [train_years 年训练 + test_years 年测试] 切片,
    在每个测试窗口内评估策略表现, 统计跨窗口稳定性。

    返回: dict 包含 per_window 结果列表 + 统计汇总。
    """
    dates, codes, series = load_panel(panel_path)
    n = len(dates)
    weeks_per_year = 52
    train_w = int(train_years * weeks_per_year)
    test_w = int(test_years * weeks_per_year)
    step_w = test_w  # 滚动步长 = 测试窗口长度

    # 确定回测有效起点 (所有核心标的都有数据的最早周)
    needed = DEF16 + [CORE_SUB.get(c, c) for c in OFF4] + [HS300] + DC_INDICES
    from backtest_engine import extract
    aligned, start = extract(dates, series, needed)

    windows = []
    i = start
    while i + train_w + test_w <= n:
        lo = i + train_w  # 测试窗口起点
        hi = min(i + train_w + test_w, n)
        if hi - lo < 10:  # 太短跳过
            break

        kw = dict(
            offense_mode=offense_mode, momentum_lookback=momentum_lookback,
            use_tech=use_tech, core_satellite=core_satellite, core_frac=core_frac,
            death_cross=death_cross, trend_filter=trend_filter,
            costs=costs, panel_path=panel_path, use_core_sub=True,
            eval_lo=lo, eval_hi=hi,
            **run_kwargs
        )
        try:
            s, _, _, _ = run(**kw)
            windows.append({
                "test_start": s["start"], "test_end": s["end"],
                "weeks": s["weeks"], "multiple": s["final_multiple"],
                "mdd": s["mdd"], "cagr": s["cagr"],
                "hs300": s["hs300_multiple"], "excess": s["excess_vs_hs300"],
                "cost_deducted": s["total_cost_deducted"],
            })
        except Exception as e:
            windows.append({"test_start": dates[lo], "test_end": dates[hi-1],
                             "error": str(e)})
        i += step_w

    # 统计汇总
    valid = [w for w in windows if "multiple" in w]
    if not valid:
        return {"windows": windows, "summary": {"error": "no valid windows"}}

    mults = [w["multiple"] for w in valid]
    mdds = [w["mdd"] for w in valid]
    cagrs = [w["cagr"] for w in valid]
    excess = [w["excess"] for w in valid]

    import statistics
    summary = {
        "n_windows": len(valid),
        "train_years": train_years,
        "test_years": test_years,
        "mult_mean": round(statistics.mean(mults), 3),
        "mult_median": round(statistics.median(mults), 3),
        "mult_std": round(statistics.stdev(mults), 3) if len(mults) > 1 else 0,
        "mult_min": round(min(mults), 3),
        "mult_max": round(max(mults), 3),
        "mdd_mean": round(statistics.mean(mdds), 2),
        "mdd_worst": round(min(mdds), 2),
        "cagr_mean": round(statistics.mean(cagrs), 2),
        "excess_mean": round(statistics.mean(excess), 2),
        "win_rate": round(sum(1 for m in mults if m > 1.0) / len(mults) * 100, 1),
        "beat_hs300_rate": round(sum(1 for m, w in zip(mults, valid) if m > w["hs300"]) / len(mults) * 100, 1),
    }
    return {"windows": windows, "summary": summary}


def print_report(result, label=""):
    """打印 walk-forward 报告。"""
    s = result["summary"]
    if "error" in s:
        print(f"  [{label}] ERROR: {s['error']}")
        return

    print(f"\n{'='*80}")
    print(f"  Walk-Forward 验证报告 {label}")
    print(f"  训练 {s['train_years']}y + 测试 {s['test_years']}y | {s['n_windows']} 个测试窗口")
    print(f"{'='*80}")
    print(f"{'测试期':<25}{'倍数':>8}{'MDD%':>8}{'CAGR%':>8}{'HS300x':>9}{'超额x':>8}{'成本':>10}")
    print("-" * 80)
    for w in result["windows"]:
        if "multiple" in w:
            print(f"{w['test_start']}~{w['test_end']:<15}{w['multiple']:>8}{w['mdd']:>8}"
                  f"{w['cagr']:>8}{w['hs300']:>9}{w['excess']:>8}{w['cost_deducted']:>10}")
        else:
            print(f"{w['test_start']}~{w['test_end']:<15}  ERROR: {w.get('error','')}")
    print("-" * 80)
    print(f"{'均值':<25}{s['mult_mean']:>8}{s['mdd_mean']:>8}{s['cagr_mean']:>8}"
          f"{'':>9}{s['excess_mean']:>8}")
    print(f"{'中位数':<25}{s['mult_median']:>8}")
    print(f"{'标准差':<25}{s['mult_std']:>8}")
    print(f"{'最差窗口':<25}{s['mult_min']:>8}{s['mdd_worst']:>8}")
    print(f"{'最佳窗口':<25}{s['mult_max']:>8}")
    print(f"\n  胜率(>1.0x): {s['win_rate']}% | 跑赢HS300: {s['beat_hs300_rate']}%")
    print(f"  稳定性: 均值/标准差 = {s['mult_mean']/s['mult_std']:.1f}" if s['mult_std'] > 0 else "  稳定性: N/A (单窗口)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Walk-forward 滚动窗口验证")
    ap.add_argument("--train", type=float, default=3, help="训练窗口年数 (默认3)")
    ap.add_argument("--test", type=float, default=1, help="测试窗口年数 (默认1)")
    ap.add_argument("--compare", action="store_true", help="对比含成本 vs 毛收益")
    args = ap.parse_args()

    panel = os.path.join(DATA, "ashare_panel_close_em.csv")
    panel_path = panel if os.path.exists(panel) else None
    if not panel_path:
        print("[WARN] 未找到 ashare_panel_close_em.csv, 尝试默认面板")
        panel_path = os.path.join(DATA, "ashare_panel_close.csv")
        if not os.path.exists(panel_path):
            print("[ERROR] 无可用面板数据, 请先运行 tencent_hfq_rebuild.py")
            sys.exit(1)

    print(f"面板: {panel_path}")
    print(f"模式: momentum + 核心卫星(0.5) + 趋势过滤 + 死叉")

    if args.compare:
        print("\n--- 含交易成本 ---")
        r1 = walk_forward(panel_path=panel_path, train_years=args.train,
                          test_years=args.test, costs=True)
        print_report(r1, "(含成本)")

        print("\n--- 毛收益 (无成本) ---")
        r2 = walk_forward(panel_path=panel_path, train_years=args.train,
                          test_years=args.test, costs=False)
        print_report(r2, "(毛收益)")

        if "mult_mean" in r1["summary"] and "mult_mean" in r2["summary"]:
            drag = r2["summary"]["mult_mean"] - r1["summary"]["mult_mean"]
            print(f"\n  成本拖累: 毛收益 {r2['summary']['mult_mean']}x → 净收益 {r1['summary']['mult_mean']}x (差 {drag:.2f}x)")
    else:
        r = walk_forward(panel_path=panel_path, train_years=args.train,
                         test_years=args.test, costs=True)
        print_report(r, "")
