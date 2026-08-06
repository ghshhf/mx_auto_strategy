# -*- coding: utf-8 -*-
"""Run 10-year backtest with corrected Tencent panel data."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_engine import run

panel = os.path.join(os.path.dirname(__file__), "data", "ashare_panel_close_em.csv")
print("=== 10-Year Backtest (Tencent hfq panel) ===\n")

configs = [
    ("基线(固定OFF4)", dict(offense_mode="fixed", death_cross=True, panel_path=panel, use_core_sub=True)),
    ("动态26+核心卫星(0.5)", dict(offense_mode="momentum", momentum_lookback=26, use_tech=True,
        core_satellite=True, core_frac=0.5, death_cross=True, panel_path=panel, use_core_sub=True, trend_filter=True)),
]

print(f"{'配置':<30}{'倍数':>8}{'MDD%':>8}{'CAGR%':>8}{'HS300x':>9}{'超额x':>8}")
print("-" * 75)
for name, kw in configs:
    s, _, _, _ = run(**kw)
    print(f"{name:<30}{s['final_multiple']:>8}{s['mdd']:>8}{s['cagr']:>8}"
          f"{s['hs300_multiple']:>9}{s['excess_vs_hs300']:>8}")
print(f"\n窗口: {s['start']} ~ {s['end']} ({s['weeks']}周)")
