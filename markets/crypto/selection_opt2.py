"""
selection_opt2.py - 第二轮: 风险调整后最优组合搜索
=====================================================
基于第一轮发现:
- alloc_offense_mult 是杠杆 (Sharpe不变), 需配合降MDD的模式
- equal/inv_vol 有真alpha (Sharpe提高+MDD降低)
- option_filter_phases=('accumulation',) 有+67%但MDD恶化
- n=2 集中选币收益高但MDD高

策略: 用 equal/inv_vol 的降MDD优势, 配合适度杠杆
"""
import os, sys, time, json
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crypto_options_bt as C
from crypto_options_bt import run_bt

TENY = pd.read_csv(f'{HERE}/data/weekly_adjclose_crypto50_10y.csv',
                   index_col=0, parse_dates=True).sort_index()
MAIN = pd.read_csv(f'{HERE}/data/weekly_adjclose_crypto50.csv',
                  index_col=0, parse_dates=True).sort_index()

WINDOWS = [('10y', TENY, '2016-08-11'), ('5y', MAIN, '2021-08-11'), ('3y', MAIN, '2023-08-11')]

def eval_cfg(override):
    cfg = dict(C.DEFAULT_CFG)
    cfg.update(override)
    out = {}
    for name, pnl, st in WINDOWS:
        C._ALT_RS_CACHE.clear()
        px = pnl[pnl.index >= pd.Timestamp(st)]
        try:
            r = run_bt(px, cfg)
            out[name] = (r['multiple'], r['mdd'], r['sharpe'])
        except:
            out[name] = (0, 0, 0)
    return out

def fmt(r):
    m = r[0]
    ms = f"{m/1000:.1f}Kx" if m >= 1000 else f"{m:.1f}x"
    return f"{ms:>10}  MDD={r[1]*100:>5.1f}%  Sh={r[2]:.2f}"

t0 = time.time()
print("=" * 100)
print("第二轮: 风险调整后最优组合搜索")
print("=" * 100)

# ---- 基线 ----
base = eval_cfg({})
print(f"\n基线: {fmt(base['10y'])}  {fmt(base['5y'])}  {fmt(base['3y'])}")

# ============ 1. weight_mode × alloc_offense_mult 交互 ============
print("\n" + "=" * 100)
print("[1] weight_mode × alloc_offense_mult 交互网格")
print("=" * 100)
print(f"{'mode':<10} {'mult':<6} {'10y':>30} {'5y':>30} {'3y':>30}")
for mode in ['score', 'equal', 'inv_vol']:
    for mult in [1.0, 1.1, 1.2, 1.3, 1.5]:
        r = eval_cfg({'offense_weight_mode': mode, 'alloc_offense_mult': mult})
        m10 = r['10y'][0]
        ms10 = f"{m10/1000:.1f}Kx" if m10 >= 1000 else f"{m10:.1f}x"
        m5 = r['5y'][0]
        ms5 = f"{m5:.1f}x"
        m3 = r['3y'][0]
        ms3 = f"{m3:.1f}x"
        print(f"{mode:<10} {mult:<6.1f} {ms10:>10} MDD={r['10y'][1]*100:>5.1f}% Sh={r['10y'][2]:.2f}  "
              f"{ms5:>7} MDD={r['5y'][1]*100:>5.1f}%  {ms3:>5} MDD={r['3y'][1]*100:>5.1f}%")

# ============ 2. option_filter_phases × weight_mode ============
print("\n" + "=" * 100)
print("[2] option_filter_phases × weight_mode 交互")
print("=" * 100)
for label, phases in [
    ('accum+pre', ('accumulation', 'pre_halving')),  # 当前
    ('accum only', ('accumulation',)),
    ('none', ()),
]:
    for mode in ['score', 'equal', 'inv_vol']:
        r = eval_cfg({'option_filter_phases': phases, 'offense_weight_mode': mode})
        m10 = r['10y'][0]
        ms10 = f"{m10/1000:.1f}Kx" if m10 >= 1000 else f"{m10:.1f}x"
        print(f"  {label:<12} {mode:<10} {ms10:>10} MDD={r['10y'][1]*100:>5.1f}% Sh={r['10y'][2]:.2f}  "
              f"5y={r['5y'][0]:.1f}x  3y={r['3y'][0]:.1f}x")

# ============ 3. 最优候选组合 ============
print("\n" + "=" * 100)
print("[3] 候选组合对比 (追求Sharpe最优)")
print("=" * 100)

candidates = [
    ('baseline', {}),
    # 用 inv_vol 降MDD + 适度杠杆
    ('inv_vol+1.2', {'offense_weight_mode': 'inv_vol', 'alloc_offense_mult': 1.2}),
    ('inv_vol+1.3', {'offense_weight_mode': 'inv_vol', 'alloc_offense_mult': 1.3}),
    ('inv_vol+1.5', {'offense_weight_mode': 'inv_vol', 'alloc_offense_mult': 1.5}),
    # 用 equal 降MDD + 适度杠杆
    ('equal+1.2', {'offense_weight_mode': 'equal', 'alloc_offense_mult': 1.2}),
    ('equal+1.3', {'offense_weight_mode': 'equal', 'alloc_offense_mult': 1.3}),
    ('equal+1.5', {'offense_weight_mode': 'equal', 'alloc_offense_mult': 1.5}),
    # inv_vol + accum only filter + 适度杠杆
    ('ivol+acc+1.2', {'offense_weight_mode': 'inv_vol', 'option_filter_phases': ('accumulation',),
                      'alloc_offense_mult': 1.2}),
    ('ivol+acc+1.3', {'offense_weight_mode': 'inv_vol', 'option_filter_phases': ('accumulation',),
                      'alloc_offense_mult': 1.3}),
    # equal + accum only + 适度杠杆
    ('eq+acc+1.2', {'offense_weight_mode': 'equal', 'option_filter_phases': ('accumulation',),
                    'alloc_offense_mult': 1.2}),
    ('eq+acc+1.3', {'offense_weight_mode': 'equal', 'option_filter_phases': ('accumulation',),
                    'alloc_offense_mult': 1.3}),
    # n=2 + inv_vol (集中+风险平衡)
    ('n2+ivol+1.0', {'offense_n': 2, 'offense_weight_mode': 'inv_vol'}),
    ('n2+ivol+1.2', {'offense_n': 2, 'offense_weight_mode': 'inv_vol', 'alloc_offense_mult': 1.2}),
    # n=2 + equal
    ('n2+eq+1.0', {'offense_n': 2, 'offense_weight_mode': 'equal'}),
    ('n2+eq+1.2', {'offense_n': 2, 'offense_weight_mode': 'equal', 'alloc_offense_mult': 1.2}),
]

print(f"\n{'combo':<18} {'10y mult':>12} {'10y MDD':>8} {'10y Sh':>7} {'5y mult':>10} {'5y MDD':>8} {'5y Sh':>7} {'3y mult':>8} {'3y MDD':>8} {'3y Sh':>7}")
for label, ov in candidates:
    r = eval_cfg(ov)
    m10 = r['10y'][0]; ms10 = f"{m10/1000:.1f}Kx" if m10 >= 1000 else f"{m10:.1f}x"
    m5 = r['5y'][0]; ms5 = f"{m5:.1f}x"
    m3 = r['3y'][0]; ms3 = f"{m3:.1f}x"
    print(f"{label:<18} {ms10:>12} {r['10y'][1]*100:>7.1f}% {r['10y'][2]:>7.2f}  "
          f"{ms5:>10} {r['5y'][1]*100:>7.1f}% {r['5y'][2]:>7.2f}  "
          f"{ms3:>8} {r['3y'][1]*100:>7.1f}% {r['3y'][2]:>7.2f}")

# ============ 4. OOS walk-forward 验证 top候选 ============
print("\n" + "=" * 100)
print("[4] OOS Walk-Forward 验证 (IS=前260周, OOS=后260周)")
print("=" * 100)

# 10y数据从2016-08-11开始, ~520周; IS=前260, OOS=后260
px_10y = TENY[TENY.index >= pd.Timestamp('2016-08-11')]
split = len(px_10y) // 2
px_is = px_10y.iloc[:split]
px_oos = px_10y.iloc[split:]

oos_candidates = [
    ('baseline', {}),
    ('inv_vol+1.2', {'offense_weight_mode': 'inv_vol', 'alloc_offense_mult': 1.2}),
    ('inv_vol+1.3', {'offense_weight_mode': 'inv_vol', 'alloc_offense_mult': 1.3}),
    ('equal+1.2', {'offense_weight_mode': 'equal', 'alloc_offense_mult': 1.2}),
    ('equal+1.3', {'offense_weight_mode': 'equal', 'alloc_offense_mult': 1.3}),
    ('ivol+acc+1.2', {'offense_weight_mode': 'inv_vol', 'option_filter_phases': ('accumulation',),
                      'alloc_offense_mult': 1.2}),
    ('eq+acc+1.3', {'offense_weight_mode': 'equal', 'option_filter_phases': ('accumulation',),
                    'alloc_offense_mult': 1.3}),
    ('n2+ivol+1.2', {'offense_n': 2, 'offense_weight_mode': 'inv_vol', 'alloc_offense_mult': 1.2}),
    ('n2+eq+1.2', {'offense_n': 2, 'offense_weight_mode': 'equal', 'alloc_offense_mult': 1.2}),
]

print(f"\n{'combo':<18} {'IS mult':>12} {'IS MDD':>8} {'IS Sh':>7} {'OOS mult':>12} {'OOS MDD':>8} {'OOS Sh':>7}")
for label, ov in oos_candidates:
    cfg = dict(C.DEFAULT_CFG)
    cfg.update(ov)
    C._ALT_RS_CACHE.clear()
    try:
        r_is = run_bt(px_is, cfg)
        is_m, is_d, is_s = r_is['multiple'], r_is['mdd'], r_is['sharpe']
    except:
        is_m, is_d, is_s = 0, 0, 0
    C._ALT_RS_CACHE.clear()
    try:
        r_oos = run_bt(px_oos, cfg)
        oos_m, oos_d, oos_s = r_oos['multiple'], r_oos['mdd'], r_oos['sharpe']
    except:
        oos_m, oos_d, oos_s = 0, 0, 0
    is_ms = f"{is_m/1000:.1f}Kx" if is_m >= 1000 else f"{is_m:.1f}x"
    oos_ms = f"{oos_m:.1f}x" if oos_m < 1000 else f"{oos_m/1000:.1f}Kx"
    print(f"{label:<18} {is_ms:>12} {is_d*100:>7.1f}% {is_s:>7.2f}  {oos_ms:>12} {oos_d*100:>7.1f}% {oos_s:>7.2f}")

print(f"\n=== 耗时 {time.time()-t0:.0f}s ===")
