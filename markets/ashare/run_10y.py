# -*- coding: utf-8 -*-
"""
run_10y.py - 10 年回测主入口 (腾讯后复权面板)

v6.17 配置变更说明:
  移除了 trend_filter (MA5>MA20)。依据: walk_forward.py --variants 的配对检验
    - 全样本      : 关闭后 19.980x -> 21.500x (+7.6%)
    - 3y训/1y测   : t=1.95, 8/11 窗口胜出
    - 3y训/2y测   : t=4.05, 5/5 窗口全胜 (显著)
  三个独立尺度同向, 判定为真实改进而非单窗口过拟合。
  原 v6.13 认为趋势过滤有效, 是在旧的错误口径面板(周最低价)上得出的结论。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_engine import run

panel = os.path.join(os.path.dirname(__file__), "data", "ashare_panel_close_em.csv")
print("=== 10-Year Backtest (Tencent hfq panel, v6.17) ===\n")

_common = dict(death_cross=True, panel_path=panel, use_core_sub=True, costs=True)
_dyn = dict(offense_mode="momentum", momentum_lookback=26, use_tech=True,
            core_satellite=True, core_frac=0.5, **_common)

configs = [
    ("基线(固定OFF4)", dict(offense_mode="fixed", **_common)),
    ("v6.16 旧推荐(带趋势过滤)", dict(trend_filter=True, **_dyn)),
    ("v6.17 推荐(去趋势过滤)", dict(_dyn)),
    ("v6.17 + 宏观叠加0.6 [可选]", dict(macro_overlay=True, macro_tilt=0.6, **_dyn)),
]

print(f"{'配置':<32}{'倍数':>9}{'MDD%':>9}{'CAGR%':>8}{'HS300x':>9}{'超额x':>8}")
print("-" * 78)
for name, kw in configs:
    s, _, _, _ = run(**kw)
    print(f"{name:<32}{s['final_multiple']:>9.3f}{s['mdd']:>9.2f}{s['cagr']:>8.2f}"
          f"{s['hs300_multiple']:>9.2f}{s['excess_vs_hs300']:>8.2f}")
print(f"\n窗口: {s['start']} ~ {s['end']} ({s['weeks']}周)")
print("\n注: 宏观叠加标 [可选] 是因为它未通过配对显著性检验 (t≈1.2-1.9, 未达 2.0),")
print("    全样本与方向证据为正但强度不足, 故默认关闭。详见 walk_forward.py --variants。")
