# -*- coding: utf-8 -*-
"""
survivorship_check.py - 幸存者偏差 / 赢家集中度 敏感性检查 (v6.18 诚实基线)
================================================================================
移除候选池中历史涨幅最大的 TopN 只股票后重算回测,
评估"当前赢家"池对回测倍数的向上偏差量级。

用法:
  python3 survivorship_check.py                  # 移除 Top5 重算
  python3 survivorship_check.py --top 10         # 移除 Top10
  python3 survivorship_check.py --compare        # 对比 Top0/5/10/20

⚠️ 重要解释 (v6.18):
  本脚本测的是"赢家集中度敏感性", 是幸存者偏差的**上界代理**而非精确修正:
    1. 严格幸存者偏差 = 候选池只含"未退市幸存者", 而这些幸存者 disproportionally
       是赢家; 本脚本通过"移除最大涨幅者"近似这一效应。
    2. 精确修正需 point-in-time 含退市全样本池, akshare 经本代理无法干净获取
       (szse.cn 连接被拦, stock_zh_a_st_em 仅当前 ST 股), 故不做虚假精确值。
  结论判读: 若移除 TopN 后倍数大幅下降 -> 头条 18.185x 是被系统性高估的**上界**,
  真实值应更低; 本脚本给出偏差幅度的保守下界。

基线: v6.18 诚实配置 use_tech=False + trend_filter=False + 核心卫星 + 死叉 + 成本。
"""
import os
import sys
import json
import copy
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(BASE))
sys.path.insert(0, BASE)
from backtest_engine import run, load_panel, DEF16, OFF4, CORE_SUB, HS300, DC_INDICES


def compute_stock_returns(panel_path):
    """计算面板中每只股票的全周期涨幅, 返回 [(code, return_ratio), ...] 降序。"""
    dates, codes, series = load_panel(panel_path)
    returns = []
    for code in codes:
        vals = series[code]
        first = None
        last = None
        for v in vals:
            if v is not None and v > 0:
                if first is None:
                    first = v
                last = v
        if first and last and first > 0:
            returns.append((code, last / first - 1.0))
    returns.sort(key=lambda x: x[1], reverse=True)
    return returns


def run_with_excluded(exclude_codes, **run_kwargs):
    """临时修改 strategy_config.json 排除指定股票后跑回测。

    注意: panel_path 由 run_kwargs 透传, 不再作为独立位置参数,
    否则与调用方 run_kw 中的 panel_path 冲突 (multiple values)。
    """
    cfg_path = os.path.join(ROOT, "strategy_config.json")
    cfg = json.load(open(cfg_path, encoding="utf-8"))

    # 备份原始池
    orig_pool = copy.deepcopy(cfg.get("auto_select", {}).get("candidate_pool", []))

    # 过滤候选池
    pool = [p for p in orig_pool if p["code"] not in exclude_codes]
    cfg["auto_select"]["candidate_pool"] = pool

    # 写临时配置
    tmp_cfg = os.path.join(BASE, "_tmp_survivorship_config.json")
    with open(tmp_cfg, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    # 临时替换配置路径 (engine 读固定路径, 所以用文件替换)
    real_cfg = cfg_path
    backup_cfg = cfg_path + ".surv_backup"
    os.rename(real_cfg, backup_cfg)
    os.rename(tmp_cfg, real_cfg)

    try:
        s, _, _, _ = run(**run_kwargs)
    finally:
        # 恢复原始配置
        os.rename(real_cfg, tmp_cfg)
        os.rename(backup_cfg, real_cfg)
        os.remove(tmp_cfg)

    return s


def main():
    ap = argparse.ArgumentParser(description="幸存者偏差敏感性检查")
    ap.add_argument("--top", type=int, default=5, help="移除涨幅最大的N只 (默认5)")
    ap.add_argument("--compare", action="store_true", help="对比 Top0/5/10/20")
    ap.add_argument("--panel", type=str, default=None, help="面板路径")
    args = ap.parse_args()

    panel = args.panel or os.path.join(BASE, "data", "ashare_panel_close_em.csv")
    if not os.path.exists(panel):
        panel = os.path.join(BASE, "data", "ashare_panel_close.csv")
    if not os.path.exists(panel):
        print("[ERROR] 无可用面板数据, 请先运行 tencent_hfq_rebuild.py")
        sys.exit(1)

    # 计算所有股票涨幅排名
    returns = compute_stock_returns(panel)
    print(f"面板共 {len(returns)} 只股票")
    print(f"涨幅 Top10:")
    for code, ret in returns[:10]:
        print(f"  {code}: {ret + 1.0:.1f}x ({ret*100:+.0f}%)")

    run_kw = dict(
        offense_mode="momentum", momentum_lookback=26, use_tech=False,
        core_satellite=True, core_frac=0.5, death_cross=True,
        trend_filter=False, costs=True, panel_path=panel, use_core_sub=True,
    )

    if args.compare:
        print(f"\n{'='*70}")
        print(f"  幸存者偏差敏感性对比")
        print(f"{'='*70}")
        print(f"{'排除数':<10}{'倍数':>8}{'MDD%':>8}{'CAGR%':>8}{'变化':>10}")
        print("-" * 50)

        base_s = None
        for n in [0, 5, 10, 20]:
            if n == 0:
                s, _, _, _ = run(**run_kw)
            else:
                excl = set(c for c, _ in returns[:n])
                s = run_with_excluded(excl, **run_kw)
            if base_s is None:
                base_s = s["final_multiple"]
            delta = s["final_multiple"] - base_s
            pct = delta / base_s * 100 if base_s else 0.0
            print(f"Top{n:<7}{s['final_multiple']:>8.3f}{s['mdd']:>8.2f}{s['cagr']:>8.2f}"
                  f"{delta:>+8.3f} ({pct:+.1f}%)")
    else:
        excl = set(c for c, _ in returns[:args.top])
        print(f"\n移除 Top{args.top} 涨幅股: {sorted(excl)}")
        s_base, _, _, _ = run(**run_kw)
        s_excl = run_with_excluded(excl, **run_kw)
        print(f"\n{'':<20}{'倍数':>8}{'MDD%':>8}{'CAGR%':>8}")
        print(f"{'原始(全池)':<20}{s_base['final_multiple']:>8.3f}{s_base['mdd']:>8.2f}{s_base['cagr']:>8.2f}")
        print(f"{'排除Top'+str(args.top):<20}{s_excl['final_multiple']:>8.3f}{s_excl['mdd']:>8.2f}{s_excl['cagr']:>8.2f}")
        delta = s_excl['final_multiple'] - s_base['final_multiple']
        pct = delta / s_base['final_multiple'] * 100 if s_base['final_multiple'] else 0
        print(f"\n变化: {delta:+.3f}x ({pct:+.1f}%)")
        if abs(pct) > 20:
            print("⚠ 偏差显著: 移除Top涨幅后倍数变化>20% -> 头条 18.185x 是被系统性高估的上界, 真实值应明显更低")
        elif abs(pct) > 10:
            print("⚠ 偏差中等: 移除Top涨幅后倍数变化10-20% -> 头条倍数含可观幸存者/赢家集中度溢价")
        else:
            print("✓ 偏差有限: 移除Top涨幅后倍数变化<10% -> 收益来源较分散")
        print("注: 此为赢家集中度敏感性(幸存者偏差上界代理); 精确修正需含退市 point-in-time 池(akshare 经本代理不可得)。")


if __name__ == "__main__":
    main()
