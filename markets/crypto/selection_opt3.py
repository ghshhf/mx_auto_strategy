"""
selection_opt3.py - 第三轮: inv_vol+mult 细扫 + 最终验证
"""
import os, sys, time
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
print("=" * 80)
print("第三轮: inv_vol 细扫 + 最终确认")
print("=" * 80)

base = eval_cfg({})
print(f"\n基线: {fmt(base['10y'])}  {fmt(base['5y'])}  {fmt(base['3y'])}")

# ---- 1. inv_vol mult 细扫 (1.05~1.25) ----
print("\n[1] inv_vol × mult 细扫:")
for mult in [1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3]:
    r = eval_cfg({'offense_weight_mode': 'inv_vol', 'alloc_offense_mult': mult})
    m10 = r['10y'][0]
    ms10 = f"{m10/1000:.1f}Kx" if m10 >= 1000 else f"{m10:.1f}x"
    print(f"  mult={mult:<5} {ms10:>10} MDD={r['10y'][1]*100:>5.1f}% Sh={r['10y'][2]:.2f}  "
          f"5y={r['5y'][0]:.1f}x Sh={r['5y'][2]:.2f}  3y={r['3y'][0]:.1f}x Sh={r['3y'][2]:.2f}")

# ---- 2. 最终候选 OOS 4窗口验证 ----
print("\n[2] 最终候选 4窗口OOS验证:")
# 4窗口: 2016-2019, 2019-2022, 2022-2025, 2024-2026
OOS_WINDOWS = [
    ('2016-2019', '2016-08-11', '2019-08-09'),
    ('2019-2022', '2019-08-16', '2022-08-12'),
    ('2022-2025', '2022-08-19', '2025-08-08'),
    ('2024-2026', '2024-08-16', '2026-08-07'),
]

finalists = [
    ('baseline', {}),
    ('inv_vol+1.2', {'offense_weight_mode': 'inv_vol', 'alloc_offense_mult': 1.2}),
    ('inv_vol+1.15', {'offense_weight_mode': 'inv_vol', 'alloc_offense_mult': 1.15}),
    ('inv_vol+1.1', {'offense_weight_mode': 'inv_vol', 'alloc_offense_mult': 1.1}),
]

for label, ov in finalists:
    cfg = dict(C.DEFAULT_CFG)
    cfg.update(ov)
    print(f"\n  {label}:")
    for wname, st, en in OOS_WINDOWS:
        C._ALT_RS_CACHE.clear()
        px = TENY[(TENY.index >= pd.Timestamp(st)) & (TENY.index <= pd.Timestamp(en))]
        if len(px) < 60:
            print(f"    {wname}: 数据不足")
            continue
        try:
            r = run_bt(px, cfg)
            m = r['multiple']
            ms = f"{m/1000:.1f}Kx" if m >= 1000 else f"{m:.1f}x"
            print(f"    {wname}: {ms:>10} MDD={r['mdd']*100:>5.1f}% Sh={r['sharpe']:.2f}")
        except Exception as e:
            print(f"    {wname}: ERROR {e}")

# ---- 3. 与之前参数优化叠加测试 ----
print("\n[3] inv_vol+1.2 叠加之前14参数优化:")
# 之前参数优化是在 score 模式下做的; inv_vol 下需要重新验证关键参数
for param, val in [
    ('put_bigcap_crash', 0.08),
    ('put_bigcap_payout_ratio', 0.5),
    ('short_cycle_exit_ma', 30),
    ('alt_rs_ma', 26),
    ('ovl_mom26', 1.0),
    ('take_profit_pct', 1.5),
]:
    # 旧值 vs 新值, 在 inv_vol+1.2 基础上
    old_vals = {'put_bigcap_crash': 0.12, 'put_bigcap_payout_ratio': 0.3,
                'short_cycle_exit_ma': 40, 'alt_rs_ma': 22,
                'ovl_mom26': 1.5, 'take_profit_pct': 2.0}
    base_iv = {'offense_weight_mode': 'inv_vol', 'alloc_offense_mult': 1.2}
    r_new = eval_cfg({**base_iv, param: val})
    r_old = eval_cfg({**base_iv, param: old_vals[param]})
    d = (r_new['10y'][0]/max(r_old['10y'][0],1)-1)*100
    print(f"  {param}: {old_vals[param]}→{val}  "
          f"old={fmt(r_old['10y'])}  new={fmt(r_new['10y'])}  ({d:+.0f}%)")

# ---- 4. 最终对比 ----
print("\n[4] 最终对比 (旧基线 → 14参数优化 → +选币优化):")
r0 = eval_cfg({})
r1 = eval_cfg({'offense_weight_mode': 'inv_vol', 'alloc_offense_mult': 1.2})
print(f"  旧基线:        {fmt(r0['10y'])}")
print(f"  +选币优化:     {fmt(r1['10y'])}")
print(f"  收益提升: {(r1['10y'][0]/r0['10y'][0]-1)*100:+.0f}%")
print(f"  Sharpe提升: {r1['10y'][2]-r0['10y'][2]:+.2f}")
print(f"  MDD变化: {(r1['10y'][1]-r0['10y'][1])*100:+.1f}pp")

print(f"\n=== 耗时 {time.time()-t0:.0f}s ===")
