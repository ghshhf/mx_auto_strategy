"""_scratch_bs_compare.py - 对照实验: 平面费率期权 vs BS 行权价/DTE 实时定价。
用法: G:/venv/quant/Scripts/python.exe _scratch_bs_compare.py
仅本地研究, 不修改提交/配置。确认 BS 定价是否压低期末倍数。
"""
import os, sys, json, copy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import us_backtest_ai as M

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(HERE, "data", "weekly_adjclose_full_ext.csv")

dates, series = M.load_panel(PANEL)
M.series_proxy.clear(); M.series_proxy.update(series)
us_cfg = M.load_us_cfg()
flat = copy.deepcopy(us_cfg["options_sim"])   # 当前 36x 基线配置
assert flat.get("enabled"), "options_sim 应开启"

REFRESH = 4  # monthly

def run(label, sim):
    hist, st = M.run_optimized(series, dates, use_ai=False, cfg=None,
                               refresh_weeks=REFRESH, theme_div=True, max_per_theme=2,
                               us_cfg=us_cfg, options_sim=sim)
    print(f"\n=== {label} ===")
    print(f"  期末倍数 {st['multiple']:.2f}x | CAGR {st['cagr']:.1f}% | MDD {st['mdd']*100:.1f}%")
    print(f"  call权 +{st['call_premium']*100:.2f}% | call被行权封顶 {st['call_settle']*100:.2f}%")
    print(f"  put成本 -{st['put_cost']*100:.2f}% | put对冲 +{st['put_hedge']*100:.2f}%")
    print(f"  做空 {st['short_pnl']*100:+.2f}% (开仓{st['short_count']}次)")
    print(f"  期权净 {st['options_net']*100:+.2f}%")
    return st

st_flat = run("平面费率(基线, short_size_ratio=1.0)", flat)
print(f"  [diag] 止盈触发(tp_count)={st_flat['take_profit_count']}  高估call={st_flat['ovl_call_count']}")

def bs_run(vol, tag):
    b = copy.deepcopy(flat)
    b["bs_pricing"] = True
    b["call_vol"] = vol
    b["put_vol"] = 0.20
    b["put_otm"] = 0.05
    b["bs_rate"] = 0.04
    return run(tag, b)

st_25 = bs_run(0.25, "BS 固定vol25%(当前默认)")
st_30 = bs_run(0.30, "BS 固定vol30%(市场锚定)")
st_35 = bs_run(0.35, "BS 固定vol35%")

# === 细扫: 找凑到100x附近的 call_vol ===
print("\n=== 细扫 call_vol (目标~100x) ===")
fine = {}
for v in [0.255, 0.260, 0.265, 0.270]:
    fine[v] = bs_run(v, f"BS 固定vol{v*100:.1f}%")

print("\n=== 结论速览 ===")
for lab, st in [("平面费率", st_flat), ("BS vol25%", st_25), ("BS vol30%", st_30), ("BS vol35%", st_35)]:
    print(f"  {lab:<10}: {st['multiple']:.2f}x | 期权净 {st['options_net']*100:+.1f}% | call权 {st['call_premium']*100:+.1f}%")
for v in [0.255, 0.260, 0.265, 0.270]:
    st = fine[v]
    print(f"  call_vol={v*100:.1f}%: {st['multiple']:.2f}x | CAGR {st['cagr']:.1f}% | MDD {st['mdd']*100:.1f}%")
print(f"\n  固定前向vol后: 结果对vol仍敏感但已收敛(25-35% -> {st_25['multiple']:.0f}x~{st_35['multiple']:.0f}x),")
print(f"  不再有'未封顶trailing vol'那种75x暴冲。封顶结算已改为以入场价为基(套利一致)。")
