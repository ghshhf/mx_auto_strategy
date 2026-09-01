# -*- coding: utf-8 -*-
"""
ablation.py - 特性消融对比 (v6.17)
=====================================
在同一面板/同一基准配置上, 逐个开关单一特性, 量化每个特性的净贡献。

设计原则:
  - 单变量对照: 每行只相对 BASE 改动一个开关, 避免多因素混淆。
  - 诚实呈现: 负贡献照实打印, 不做事后挑选。
  - 可扩展: 新特性只需往 VARIANTS 加一行。

用法:
  python ablation.py                 # 跑全部消融
  python ablation.py --only volume   # 只跑名字含 volume 的变体
  python ablation.py --panel <path>
"""
import os
import sys
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from backtest_engine import run  # noqa: E402


# 基准配置 = v6.18 诚实基线
#   trend_filter=False : v6.17 配对检验判定有害 (2y窗 t=4.05, 5/5 全胜) -> 已移除
#   use_tech=False     : v6.18 判定手写相位表 PHASE_HISTORY 含前视偏差 -> 不启用
BASE_CFG = dict(
    offense_mode="momentum", momentum_lookback=26, use_tech=False,
    core_satellite=True, core_frac=0.5, death_cross=True,
    trend_filter=False, costs=True, use_core_sub=True,
)

# (显示名, 相对 BASE 的增量改动)
VARIANTS = [
    ("BASE (动态26+卫星, 无相位)",     {}),
    ("+ 相位 static (★含前视)",        dict(use_tech=True, tech_mode="static")),
    ("+ 相位 static 强度0.5 (★含前视)", dict(use_tech=True, tech_mode="static",
                                            tech_strength=0.5)),
    ("+ 相位 data 强度0.25",           dict(use_tech=True, tech_mode="data",
                                            tech_strength=0.25)),
    ("+ 相位 data 强度1.0",            dict(use_tech=True, tech_mode="data",
                                            tech_strength=1.0)),
    ("+ 趋势过滤 (MA5>MA20)",          dict(trend_filter=True)),
    ("+ 量能确认 ratio=0.9 (宽松)",    dict(volume_confirm=True, volume_ratio=0.9)),
    ("+ 量能确认 ratio=1.1",           dict(volume_confirm=True, volume_ratio=1.1)),
    ("- 死叉防御",                     dict(death_cross=False)),
    ("- 核心卫星",                     dict(core_satellite=False)),
    ("+ 波动目标 vol_ref=0.06",        dict(vol_target=True, vol_ref=0.06)),
    ("+ 行业分散",                     dict(industry_diversify=True)),
    ("+ 宏观叠加 tilt=0.2",            dict(macro_overlay=True, macro_tilt=0.2)),
    ("+ 宏观叠加 tilt=0.6",            dict(macro_overlay=True, macro_tilt=0.6)),
    ("+ 估值分位 tilt=0.4",            dict(valuation_overlay=True, val_tilt=0.4)),
    ("+ 估值分位 tilt=0.6",            dict(valuation_overlay=True, val_tilt=0.6)),
    ("+ 估值分位 tilt=1.0",            dict(valuation_overlay=True, val_tilt=1.0)),
]


# 组合验证: 单变量最优不等于叠加最优, 必须实测
COMBOS = [
    ("BASE (无相位/无趋势)",                {}),
    ("+ 估值0.6",                           dict(valuation_overlay=True, val_tilt=0.6)),
    ("+ 估值0.6 + 宏观0.6",                 dict(valuation_overlay=True, val_tilt=0.6,
                                                 macro_overlay=True, macro_tilt=0.6)),
    ("+ 估值0.6 + 波动目标",                dict(valuation_overlay=True, val_tilt=0.6,
                                                 vol_target=True, vol_ref=0.06)),
    ("+ 估值0.6 + 宏观0.6 + 波动目标",      dict(valuation_overlay=True, val_tilt=0.6,
                                                 macro_overlay=True, macro_tilt=0.6,
                                                 vol_target=True, vol_ref=0.06)),
    ("+ 估值0.4 + 量能0.9",                 dict(valuation_overlay=True, val_tilt=0.4,
                                                 volume_confirm=True, volume_ratio=0.9)),
    ("+ 相位data0.25 + 估值0.6",            dict(use_tech=True, tech_mode="data",
                                                 tech_strength=0.25,
                                                 valuation_overlay=True, val_tilt=0.6)),
    ("无卫星 + 估值0.6",                    dict(core_satellite=False,
                                                 valuation_overlay=True, val_tilt=0.6)),
]


def main():
    ap = argparse.ArgumentParser(description="特性消融对比")
    ap.add_argument("--panel", type=str, default=None, help="面板路径")
    ap.add_argument("--only", type=str, default=None, help="只跑名字包含该子串的变体")
    ap.add_argument("--combo", action="store_true", help="跑组合叠加验证而非单变量消融")
    args = ap.parse_args()

    panel = args.panel or os.path.join(BASE_DIR, "data", "ashare_panel_close_em.csv")
    if not os.path.exists(panel):
        print(f"[ERROR] 面板不存在: {panel}\n  先运行 tencent_hfq_rebuild.py")
        sys.exit(1)

    variants = COMBOS if args.combo else VARIANTS
    if args.only:
        # BASE 永远保留, 否则无从对照
        variants = [variants[0]] + [v for v in variants[1:] if args.only in v[0]]

    print("=" * 88)
    title = "组合叠加验证 (多变量)" if args.combo else "特性消融对比 (单变量, 同面板同基准)"
    print(f"  {title}")
    print(f"  面板: {os.path.basename(panel)}")
    print("=" * 88)
    print(f"{'变体':<30}{'倍数':>9}{'MDD%':>9}{'CAGR%':>8}{'Δ倍数':>10}{'Δ%':>9}{'ΔMDD':>8}")
    print("-" * 88)

    base_mult = None
    base_mdd = None
    rows = []
    for name, delta in variants:
        kw = dict(BASE_CFG)
        kw.update(delta)
        kw["panel_path"] = panel
        try:
            s, _, _, _ = run(**kw)
        except Exception as e:  # 不让单个变体炸掉整张表
            print(f"{name:<30}{'ERROR':>9}  {type(e).__name__}: {e}")
            continue
        m = s["final_multiple"]
        mdd = s["mdd"]
        if base_mult is None:
            base_mult, base_mdd = m, mdd
            print(f"{name:<30}{m:>9.3f}{mdd:>9.2f}{s['cagr']:>8.2f}"
                  f"{'—':>10}{'—':>9}{'—':>8}")
        else:
            d = m - base_mult
            pct = d / base_mult * 100 if base_mult else 0.0
            dmdd = mdd - base_mdd
            print(f"{name:<30}{m:>9.3f}{mdd:>9.2f}{s['cagr']:>8.2f}"
                  f"{d:>+10.3f}{pct:>+8.1f}%{dmdd:>+8.2f}")
        rows.append((name, m, mdd, s["cagr"]))

    print("-" * 88)
    if len(rows) > 1:
        best = max(rows[1:], key=lambda r: r[1])
        safest = min(rows[1:], key=lambda r: abs(r[2]))
        print(f"最高倍数变体: {best[0]}  {best[1]:.3f}x")
        print(f"最小回撤变体: {safest[0]}  MDD {safest[2]:.2f}%")
    print("\n注: Δ 为相对 BASE 的差值; ΔMDD 为正代表回撤变浅(改善)。")
    print("    单变量对照, 不代表叠加后可加性。")


if __name__ == "__main__":
    main()
