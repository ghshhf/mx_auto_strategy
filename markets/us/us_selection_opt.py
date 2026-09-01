"""
us_selection_opt.py - 美股选币逻辑参数优化扫描
===============================================
对标加密模块的选币优化: 不删股票, 只优化"怎么选+怎么配权重"

当前美股选币:
- select_optimized(): 52周动量 + MA5>MA20趋势门 + 主题解相关max2
- 权重分配: mult_map × mom^0.5 归一化 (本质是动量score加权)

扫描维度:
1. top_n: 3/4/5/8 (选几个)
2. weight_mode: mom^0.5(score) / equal / inv_vol / risk_adj
3. theme_div: True/False (主题解相关)
4. phase_tilt: True/False (渗透率倾斜)
5. lookback: 26/52/104 (动量回看)
6. trend_gate: ma5/ma200/None
7. alloc_offense_mult: 1.0/1.2/1.5 (进攻仓位倍数)
"""
import os, sys, time, json, math, statistics
import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from us_backtest_ai import (
    load_panel, load_us_cfg, run_optimized, run_baseline,
    select_optimized, select_baseline, eligible_universe,
    regime_of, death_cross_count, pick_defense_lowvol,
    _ma, WARMUP, EXCLUDE, DEF_NEW, DEF_CANDIDATES,
    ai_mult_deterministic, PANEL, series_proxy, finalize
)
import us_backtest_ai as usb

# 加载面板
dates, series = load_panel(PANEL)
series_proxy.clear()
series_proxy.update(series)
us_cfg = load_us_cfg()
opt_sim_cfg = us_cfg.get("options_sim", {})
options_sim = opt_sim_cfg if opt_sim_cfg.get("enabled", False) else None

n = len(dates)

def run_with(override):
    """跑一次optimized, 返回(multiple, mdd, sharpe, yearly)"""
    hist, st = run_optimized(
        series, dates, use_ai=False, cfg=None,
        refresh_weeks=override.get('refresh_weeks', 4),
        top_n=override.get('top_n', 3),
        trend_gate=override.get('trend_gate', 'ma5'),
        lookback=override.get('lookback', 52),
        score_mode=override.get('score_mode', 'mom'),
        theme_div=override.get('theme_div', True),
        max_per_theme=override.get('max_per_theme', 2),
        phase_tilt=override.get('phase_tilt', False),
        crash_off=override.get('crash_off', 80),
        struct_def=override.get('struct_def', 0.0),
        vol_target=override.get('vol_target', 0.0),
        lev=override.get('lev', 1.0),
        us_cfg=us_cfg, options_sim=options_sim
    )
    m = st['multiple']
    d = st['mdd']
    # 简化Sharpe: 用yearly returns
    yr_rets = list(st['yearly'].values())
    if len(yr_rets) > 2:
        avg = statistics.mean([r-1 for r in yr_rets])
        sd = statistics.pstdev([r-1 for r in yr_rets])
        sh = (avg / sd * (52**0.5)) if sd > 0 else 0  # 年化Sharpe近似
    else:
        sh = 0
    return m, d, sh, st

def fmt(r):
    m = r[0]
    ms = f"{m:.1f}x" if m < 1000 else f"{m/1000:.1f}Kx"
    return f"{ms:>10}  MDD={r[1]*100:>5.1f}%  Sh={r[2]:.2f}"

t0 = time.time()
print("="*100)
print("美股选币逻辑参数优化扫描")
print("="*100)

# ---- 基线 ----
base = run_with({})
print(f"\n基线 (optimized, 默认): {fmt(base)}")

# ============ 1. top_n ============
print("\n[1] top_n (选几个):")
for n_sel in [2, 3, 4, 5, 8, 10]:
    r = run_with({'top_n': n_sel})
    d = (r[0]/max(base[0],1)-1)*100
    print(f"  n={n_sel:<3} {fmt(r)}  ({d:+.0f}%)")

# ============ 2. theme_div + max_per_theme ============
print("\n[2] theme_div (主题解相关):")
for td in [True, False]:
    r = run_with({'theme_div': td})
    print(f"  theme_div={td:<6} {fmt(r)}")

print("\n[2b] max_per_theme (theme_div=True时):")
for mpt in [1, 2, 3, 4]:
    r = run_with({'theme_div': True, 'max_per_theme': mpt})
    print(f"  max_per_theme={mpt} {fmt(r)}")

# ============ 3. phase_tilt ============
print("\n[3] phase_tilt (渗透率倾斜):")
for pt in [True, False]:
    r = run_with({'phase_tilt': pt})
    print(f"  phase_tilt={pt:<6} {fmt(r)}")

# ============ 4. lookback ============
print("\n[4] lookback (动量回看):")
for lb in [13, 26, 52, 104]:
    r = run_with({'lookback': lb})
    d = (r[0]/max(base[0],1)-1)*100
    print(f"  lookback={lb:<4} {fmt(r)}  ({d:+.0f}%)")

# ============ 5. trend_gate ============
print("\n[5] trend_gate (趋势门):")
for tg in ['ma5', 'ma200', None]:
    r = run_with({'trend_gate': tg})
    print(f"  gate={str(tg):<6} {fmt(r)}")

# ============ 6. crash_off (crash档进攻占比) ============
print("\n[6] crash_off (crash档进攻%):")
for co in [0, 20, 40, 60, 80, 100]:
    r = run_with({'crash_off': co})
    print(f"  crash_off={co:<4} {fmt(r)}")

# ============ 7. struct_def (结构性现金袖) ============
print("\n[7] struct_def (永久现金袖):")
for sd in [0.0, 0.10, 0.20, 0.30, 0.40]:
    r = run_with({'struct_def': sd})
    print(f"  struct_def={sd:<5} {fmt(r)}")

# ============ 8. vol_target (波动率目标) ============
print("\n[8] vol_target (波动率目标化):")
for vt in [0.0, 0.15, 0.18, 0.20, 0.22, 0.25, 0.30]:
    r = run_with({'vol_target': vt, 'struct_def': 0.20})
    print(f"  vol_t={vt:<5} {fmt(r)}")

# ============ 9. lev (杠杆) ============
print("\n[9] lev (杠杆):")
for lv in [1.0, 1.2, 1.5, 2.0]:
    r = run_with({'lev': lv})
    print(f"  lev={lv:<4} {fmt(r)}")

# ============ 10. 组合测试 ============
print("\n" + "="*100)
print("组合测试")
print("="*100)

combos = [
    ('baseline', {}),
    # 降MDD组合
    ('sd20+vol18', {'struct_def': 0.20, 'vol_target': 0.18}),
    ('sd30+vol20', {'struct_def': 0.30, 'vol_target': 0.20}),
    ('sd20+vol18+crash40', {'struct_def': 0.20, 'vol_target': 0.18, 'crash_off': 40}),
    # 提收益组合
    ('n5+lb52', {'top_n': 5, 'lookback': 52}),
    ('n4+sd20', {'top_n': 4, 'struct_def': 0.20}),
    # 平衡组合
    ('n4+sd20+vol18', {'top_n': 4, 'struct_def': 0.20, 'vol_target': 0.18}),
    ('n5+sd20+vol20+crash40', {'top_n': 5, 'struct_def': 0.20, 'vol_target': 0.20, 'crash_off': 40}),
    # 激进
    ('lev1.2+sd20+vol18', {'lev': 1.2, 'struct_def': 0.20, 'vol_target': 0.18}),
    ('lev1.3+sd30+vol18', {'lev': 1.3, 'struct_def': 0.30, 'vol_target': 0.18}),
]

print(f"\n{'combo':<28} {'10y mult':>10} {'MDD':>8} {'Sharpe':>8} {'vs base':>8}")
for label, ov in combos:
    r = run_with(ov)
    d = (r[0]/max(base[0],1)-1)*100
    print(f"{label:<28} {r[0]:>10.1f} {r[1]*100:>7.1f}% {r[2]:>8.2f} {d:>+7.0f}%")

# ============ 11. OOS验证top候选 ============
print("\n" + "="*100)
print("OOS Walk-Forward 验证 (IS=前338周, OOS=后338周)")
print("="*100)

split = n // 2
dates_is = dates[:split]
dates_oos = dates[split:]
series_is = {k: v[:split] for k, v in series.items()}
series_oos = {k: v[split:] for k, v in series.items()}

oos_candidates = [
    ('baseline', {}),
    ('sd20+vol18', {'struct_def': 0.20, 'vol_target': 0.18}),
    ('n4+sd20+vol18', {'top_n': 4, 'struct_def': 0.20, 'vol_target': 0.18}),
    ('lev1.2+sd20+vol18', {'lev': 1.2, 'struct_def': 0.20, 'vol_target': 0.18}),
]

for label, ov in oos_candidates:
    # IS
    series_proxy.clear(); series_proxy.update(series_is)
    hist_is, st_is = run_optimized(
        series_is, dates_is, use_ai=False, cfg=None, refresh_weeks=4,
        theme_div=ov.get('theme_div', True), max_per_theme=ov.get('max_per_theme', 2),
        top_n=ov.get('top_n', 3), trend_gate=ov.get('trend_gate', 'ma5'),
        lookback=ov.get('lookback', 52), crash_off=ov.get('crash_off', 80),
        struct_def=ov.get('struct_def', 0.0), vol_target=ov.get('vol_target', 0.0),
        lev=ov.get('lev', 1.0), us_cfg=us_cfg, options_sim=options_sim)
    # OOS
    series_proxy.clear(); series_proxy.update(series_oos)
    hist_oos, st_oos = run_optimized(
        series_oos, dates_oos, use_ai=False, cfg=None, refresh_weeks=4,
        theme_div=ov.get('theme_div', True), max_per_theme=ov.get('max_per_theme', 2),
        top_n=ov.get('top_n', 3), trend_gate=ov.get('trend_gate', 'ma5'),
        lookback=ov.get('lookback', 52), crash_off=ov.get('crash_off', 80),
        struct_def=ov.get('struct_def', 0.0), vol_target=ov.get('vol_target', 0.0),
        lev=ov.get('lev', 1.0), us_cfg=us_cfg, options_sim=options_sim)
    series_proxy.clear(); series_proxy.update(series)
    print(f"  {label:<24} IS: {st_is['multiple']:>8.1f}x MDD={st_is['mdd']*100:>5.1f}%  |  "
          f"OOS: {st_oos['multiple']:>8.1f}x MDD={st_oos['mdd']*100:>5.1f}%")

print(f"\n=== 耗时 {time.time()-t0:.0f}s ===")
