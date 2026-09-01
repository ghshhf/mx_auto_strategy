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

DATA = os.path.join(BASE, "data")


def walk_forward(panel_path=None, train_years=3, test_years=1,
                 offense_mode="momentum", momentum_lookback=26, use_tech=False,
                 core_satellite=True, core_frac=0.5, death_cross=True,
                 trend_filter=False, costs=True, **run_kwargs):
    """滚动 walk-forward 验证.

    将面板数据按 [train_years 年训练 + test_years 年测试] 切片,
    在每个测试窗口内评估策略表现, 统计跨窗口稳定性。

    默认基线 = v6.18 诚实口径:
      trend_filter=False (v6.17 配对检验判定为有害, t=4.05 已移除)
      use_tech=False     (v6.18 判定手写相位表含前视偏差, 详见 backtest_engine
                          的 tech_mode 说明; 默认不启用任何相位加权)

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


# 候选变体: 用于检验 ablation.py 的单窗口结论是否跨窗口稳健 (防过拟合)
# BASE = v6.18 诚实基线 (无趋势过滤 / 无相位加权 / 无叠加层)
WF_VARIANTS = [
    ("BASE",                          {}),
    ("+趋势过滤",                     dict(trend_filter=True)),
    ("+相位static(含前视)",           dict(use_tech=True, tech_mode="static")),
    ("+相位data0.25",                 dict(use_tech=True, tech_mode="data",
                                           tech_strength=0.25)),
    ("+相位data1.0",                  dict(use_tech=True, tech_mode="data",
                                           tech_strength=1.0)),
    ("+量能0.9",                      dict(volume_confirm=True, volume_ratio=0.9)),
    ("无卫星",                        dict(core_satellite=False)),
    ("+宏观0.6",                      dict(macro_overlay=True, macro_tilt=0.6)),
    ("+估值0.4",                      dict(valuation_overlay=True, val_tilt=0.4)),
    ("+估值0.6",                      dict(valuation_overlay=True, val_tilt=0.6)),
    ("+估值0.6+宏观0.6",              dict(valuation_overlay=True, val_tilt=0.6,
                                           macro_overlay=True, macro_tilt=0.6)),
    ("+估值0.6+波动目标",             dict(valuation_overlay=True, val_tilt=0.6,
                                           vol_target=True, vol_ref=0.06)),
]


def variant_compare(panel_path, train_years, test_years):
    """跨窗口稳健性对比: 单窗口(全样本)最优 != walk-forward 最优。

    过拟合诊断的核心表: 若某变体全样本大幅领先但 walk-forward 均值/胜率不领先,
    则该变体的优势来自特定时间段, 不可外推。
    """
    print(f"\n{'='*94}")
    print(f"  变体跨窗口稳健性对比 (训练{train_years}y + 测试{test_years}y 滚动)")
    print(f"{'='*94}")
    print(f"{'变体':<26}{'窗口数':>7}{'净收益均值':>11}{'中位':>8}{'标准差':>8}"
          f"{'最差':>8}{'胜率%':>8}{'赢HS300%':>10}{'稳定性':>8}")
    print("-" * 94)
    rows = []
    per_window = {}   # name -> {mult:[...], mdd:[...]}, 供 paired_test 复用避免重跑
    for name, delta in WF_VARIANTS:
        r = walk_forward(panel_path=panel_path, train_years=train_years,
                         test_years=test_years, costs=True, **delta)
        ok = [w for w in r["windows"] if "multiple" in w]
        per_window[name] = {"mult": [w["multiple"] for w in ok],
                            "mdd": [w["mdd"] for w in ok]}
        s = r["summary"]
        if "error" in s:
            print(f"{name:<26}  ERROR: {s['error']}")
            continue
        stab = s["mult_mean"] / s["mult_std"] if s["mult_std"] > 0 else float("inf")
        print(f"{name:<26}{s['n_windows']:>7}{s['mult_mean']:>11.3f}{s['mult_median']:>8.3f}"
              f"{s['mult_std']:>8.3f}{s['mult_min']:>8.3f}{s['win_rate']:>8.1f}"
              f"{s['beat_hs300_rate']:>10.1f}{stab:>8.1f}")
        rows.append((name, s, stab))
    print("-" * 94)
    if rows:
        best_mean = max(rows, key=lambda r: r[1]["mult_mean"])
        best_stab = max(rows, key=lambda r: r[2])
        best_worst = max(rows, key=lambda r: r[1]["mult_min"])
        print(f"净收益均值最高: {best_mean[0]}  ({best_mean[1]['mult_mean']:.3f}x)")
        print(f"稳定性最高    : {best_stab[0]}  (均值/标准差 {best_stab[2]:.1f})")
        print(f"最差窗口最好  : {best_worst[0]}  ({best_worst[1]['mult_min']:.3f}x)")
    print("\n注: 若某变体全样本(ablation.py)大幅领先但此表不领先, 说明优势来自特定时段 = 过拟合信号。")
    return per_window


def _paired_stats(v, base):
    """返回 (均值差, 胜出数, t 统计量)。"""
    import statistics
    import math
    d = [a - b for a, b in zip(v, base)]
    md = statistics.mean(d)
    sd = statistics.stdev(d) if len(d) > 1 else 0.0
    t = md / (sd / math.sqrt(len(d))) if sd > 0 else 0.0
    return md, sum(1 for x in d if x > 0), t


def paired_test(per_variant):
    """配对显著性检验: 逐窗口比较各变体 vs BASE, 收益与回撤两个维度。

    少量窗口的均值差落在噪声内是常态, 因此必须做配对比较:
      - 逐窗口取差值 d_i = variant_i - base_i (消除窗口本身的市场波动)
      - 符号检验: 有多少窗口变体胜出 (非参数, 不假设正态)
      - 配对 t 统计量: mean(d) / (std(d)/sqrt(n))
    判定: |t| < 2 且胜出窗口数接近半数 => 差异不显著, 不应据此改默认值。

    ★ 同时检验 MDD: 某些特性(如估值分位层)本就是「以收益换回撤」,
      只看倍数会把有效的风控特性误判为无效。MDD 为负值, 差值为正 = 回撤更浅。
    """
    print(f"\n{'='*104}")
    print("  配对显著性检验 (逐窗口 variant - BASE)")
    print(f"{'='*104}")

    b = per_variant.get("BASE", {})
    base_m, base_d = b.get("mult", []), b.get("mdd", [])
    if not base_m:
        print("  [ERROR] BASE 无有效窗口")
        return

    n = len(base_m)
    print(f"  样本: {n} 个不重叠测试窗口\n")
    print(f"{'变体':<24}{'Δ倍数':>9}{'胜':>6}{'t':>7}{'判定':>22}"
          f"{'ΔMDD':>9}{'胜':>6}{'t':>7}{'回撤判定':>16}")
    print("-" * 104)
    for name, _ in WF_VARIANTS:
        if name == "BASE":
            continue
        cur = per_variant.get(name, {})
        v_m, v_d = cur.get("mult", []), cur.get("mdd", [])
        if len(v_m) != n:
            print(f"{name:<24}  窗口数不匹配, 跳过")
            continue
        md, wins, t = _paired_stats(v_m, base_m)
        if abs(t) >= 2.0:
            verdict = "显著改善 ✅" if t > 0 else "显著恶化 ❌"
        elif abs(t) >= 1.5:
            verdict = "弱证据"
        else:
            verdict = "噪声"
        mdd_md, mdd_w, mdd_t = _paired_stats(v_d, base_d)
        if abs(mdd_t) >= 2.0:
            v2 = "显著变浅 ✅" if mdd_t > 0 else "显著加深 ❌"
        elif abs(mdd_t) >= 1.5:
            v2 = "弱证据"
        else:
            v2 = "噪声"
        print(f"{name:<24}{md:>+9.4f}{f'{wins}/{n}':>6}{t:>7.2f}{verdict:>22}"
              f"{mdd_md:>+9.2f}{f'{mdd_w}/{n}':>6}{mdd_t:>7.2f}{v2:>16}")
    print("-" * 104)
    print("  判定门槛: |t|>=2 视为显著 (双侧约 95%); n 小, 结论保守。")
    print("  含义: 判定为『噪声』的特性不应改为默认值, 即便全样本回测更好看。")
    print("  ΔMDD > 0 表示回撤更浅(MDD 是负数, 变大即改善)。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Walk-forward 滚动窗口验证")
    ap.add_argument("--train", type=float, default=3, help="训练窗口年数 (默认3)")
    ap.add_argument("--test", type=float, default=1, help="测试窗口年数 (默认1)")
    ap.add_argument("--compare", action="store_true", help="对比含成本 vs 毛收益")
    ap.add_argument("--variants", action="store_true", help="对比候选变体的跨窗口稳健性")
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
    print("基线: momentum26 + 核心卫星(0.5) + 死叉 | 无趋势过滤 / 无相位加权 (v6.18)")

    if args.variants:
        pw = variant_compare(panel_path, args.train, args.test)
        paired_test(pw)
    elif args.compare:
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
