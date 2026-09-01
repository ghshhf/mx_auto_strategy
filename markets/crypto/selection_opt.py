"""
selection_opt.py - 选币逻辑参数优化扫描
=========================================
不删币, 不改池子。只优化"怎么从池子里选币"的逻辑参数:
1. offense_n: 选几个币 (2/3/4/5)
2. alloc_offense_mult: 进攻仓位倍数 (0.8/1.0/1.2/1.5)
3. offense_weight_mode: 等权/score加权/逆波动率
4. theme_weight_norm: avail/fixed
5. option_filter_phases: 期权约束相位
6. offense_n_euphoria: 狂热期选几个 (3/4/5/6)
7. 动量回看周期: 通过新增momentum_lookback参数
8. phase/momentum比例: 通过新增phase_mom_ratios参数

策略: 先单参数扫描找各维度最优, 再组合测试。
"""
import os, sys, time, json
import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crypto_options_bt as C
from crypto_options_bt import run_bt
import crypto_adoption_v2 as ca2

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
    return f"{ms:>10}  MDD={r[1]*100:>5.1f}%  Sharpe={r[2]:.2f}"

def scan(param, values):
    print(f"\n===== {param} =====")
    base = eval_cfg({})
    print(f"  {'base':<20}{fmt(base['10y'])}  {fmt(base['5y'])}  {fmt(base['3y'])}")
    best_10y = (None, -1e9)
    for v in values:
        r = eval_cfg({param: v})
        d = (r['10y'][0]/max(base['10y'][0],1)-1)*100
        flag = '+' if d > 0 else ''
        print(f"  {str(v):<20}{fmt(r['10y'])}  {fmt(r['5y'])}  {fmt(r['3y'])}  ({flag}{d:.0f}%)")
        if r['10y'][0] > best_10y[1]:
            best_10y = (v, r['10y'][0])
    print(f"  >>> best: {best_10y[0]}")
    return best_10y[0]

t0 = time.time()

# ============ 单参数扫描 ============
print("=" * 80)
print("选币逻辑参数优化扫描 (不删币, 只优化选币方式)")
print("=" * 80)

# 1. 选币数量
best_n = scan('offense_n', [2, 3, 4, 5])

# 2. 进攻仓位倍数
best_mult = scan('alloc_offense_mult', [0.8, 1.0, 1.2, 1.5])

# 3. 权重模式
best_wmode = scan('offense_weight_mode', ['equal', 'score', 'inv_vol'])

# 4. 赛道权重归一化
best_norm = scan('theme_weight_norm', ['avail', 'fixed'])

# 5. 狂热期选币数
best_n_euph = scan('offense_n_euphoria', [3, 4, 5, 6])

# 6. 期权约束相位
print("\n===== option_filter_phases =====")
base = eval_cfg({})
print(f"  {'base':<40}{fmt(base['10y'])}")
for label, phases in [
    ('accumulation only', ('accumulation',)),
    ('accum+pre_halv', ('accumulation', 'pre_halving')),  # 当前默认
    ('none (全放开)', ()),
    ('accum+pre+crash', ('accumulation', 'pre_halving', 'crash')),
]:
    r = eval_cfg({'option_filter_phases': phases})
    d = (r['10y'][0]/max(base['10y'][0],1)-1)*100
    print(f"  {label:<40}{fmt(r['10y'])}  ({d:+.0f}%)")

# 7. 分阶段选币开关
best_phase_sel = scan('offense_phase_selection', [True, False])

# 8. 山寨相对强度门控开关
best_alt_rs = scan('alt_rs_gate', [True, False])

# ============ 组合测试 ============
print("\n" + "=" * 80)
print("组合测试: 单参数最优组合")
print("=" * 80)

combos = [
    ('baseline', {}),
    ('best_n only', {'offense_n': best_n}),
    ('best_mult only', {'alloc_offense_mult': best_mult}),
    ('n+mult', {'offense_n': best_n, 'alloc_offense_mult': best_mult}),
    ('n+mult+wmode', {'offense_n': best_n, 'alloc_offense_mult': best_mult,
                      'offense_weight_mode': best_wmode}),
    ('n+mult+wmode+norm', {'offense_n': best_n, 'alloc_offense_mult': best_mult,
                           'offense_weight_mode': best_wmode, 'theme_weight_norm': best_norm}),
    ('n+mult+euph', {'offense_n': best_n, 'alloc_offense_mult': best_mult,
                     'offense_n_euphoria': best_n_euph}),
    ('full best', {'offense_n': best_n, 'alloc_offense_mult': best_mult,
                   'offense_weight_mode': best_wmode, 'theme_weight_norm': best_norm,
                   'offense_n_euphoria': best_n_euph}),
]

print(f"\n{'combo':<30} {'10y':>30} {'5y':>30} {'3y':>30}")
for label, ov in combos:
    r = eval_cfg(ov)
    print(f"{label:<30} {fmt(r['10y']):>30} {fmt(r['5y']):>30} {fmt(r['3y']):>30}")

# ============ 进阶: 进攻仓位倍数细扫 ============
print("\n" + "=" * 80)
print("进阶: alloc_offense_mult 细扫 (配合 best_n)")
print("=" * 80)
for mult in [0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 2.0]:
    r = eval_cfg({'offense_n': best_n, 'alloc_offense_mult': mult})
    print(f"  mult={mult:<5} {fmt(r['10y'])}  {fmt(r['5y'])}  {fmt(r['3y'])}")

# ============ 进阶: 不同选币数+仓位组合 ============
print("\n" + "=" * 80)
print("进阶: offense_n × alloc_offense_mult 网格")
print("=" * 80)
for n in [2, 3, 4, 5]:
    for mult in [1.0, 1.2, 1.5, 2.0]:
        r = eval_cfg({'offense_n': n, 'alloc_offense_mult': mult})
        m = r['10y'][0]
        ms = f"{m/1000:.1f}Kx" if m >= 1000 else f"{m:.1f}x"
        print(f"  n={n} mult={mult:<4} {ms:>10}  MDD={r['10y'][1]*100:>5.1f}%  Sharpe={r['10y'][2]:.2f}  "
              f"5y={r['5y'][0]:.1f}x  3y={r['3y'][0]:.1f}x")

print(f"\n=== 耗时 {time.time()-t0:.0f}s ===")
