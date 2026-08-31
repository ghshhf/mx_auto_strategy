# -*- coding: utf-8 -*-

# --- [relocated 2026-08-31] 目录重构引导: 等效于在 crypto_stocks/ 根目录下运行 ---
import os as _os, sys as _sys
_SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))
_d = _SCRIPT_DIR
while _os.path.basename(_d) != 'crypto_stocks' and _d != _os.path.dirname(_d):
    _d = _os.path.dirname(_d)
_CS_ROOT = _d if _os.path.basename(_d) == 'crypto_stocks' else _SCRIPT_DIR
if _CS_ROOT != _SCRIPT_DIR:
    if _CS_ROOT not in _sys.path:
        _sys.path.insert(0, _CS_ROOT)
    _os.chdir(_CS_ROOT)
# --- [relocated] 引导结束 ---
"""关键复查: 纯时间刻减仓(0.3/0.3, 无做空) vs 当前新默认(含门控做空)
10y面板显示无做空更优(28674x vs 24494x), 需多窗口+walk-forward 裁决。
"""
import numpy as np, pandas as pd
import crypto_options_bt as m

px10 = pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()
px9  = pd.read_csv('data/weekly_adjclose_crypto50.csv',      index_col=0, parse_dates=True).sort_index()

def cfg_pure():
    """纯时间刻减仓, 关掉一切做空"""
    c = dict(m.DEFAULT_CFG)
    c['halving_cycle_enabled'] = True
    c['halving_crash_risk_scale'] = 0.3
    c['halving_bear_bottom_risk_scale'] = 0.3
    c['pre_halving_start_month'] = 31.0
    c['short_proactive_ma'] = 0
    c['short_cycle_gate'] = False
    return c

def cfg_cur():
    return dict(m.DEFAULT_CFG)

WINDOWS = [
    ('10y', px10, None),
    ('9y主面板', px9, None),
    ('5y', px9, '2021-08-13'),
    ('3y', px9, '2023-08-11'),
    ('2y', px9, '2024-08-09'),
]

print('=' * 76)
print('多窗口: 纯减仓(无做空) vs 当前默认(含门控做空)')
print('=' * 76)
print(f"{'窗口':<10}{'纯减仓倍数':>13}{'MDD':>8}{'Shp':>6}   |{'默认倍数':>12}{'MDD':>8}{'Shp':>6}   胜者")
for name, p, start in WINDOWS:
    pp = p.loc[start:] if start else p
    a = m.run_bt(pp, cfg_pure(), label=name)
    b = m.run_bt(pp, cfg_cur(),  label=name)
    win = '纯减仓' if a['multiple'] > b['multiple'] else '含做空'
    print(f"{name:<10}{a['multiple']:>12,.2f}x{a['mdd']*100:>7.1f}%{a.get('sharpe',0):>6.2f}   |"
          f"{b['multiple']:>11,.2f}x{b['mdd']*100:>7.1f}%{b.get('sharpe',0):>6.2f}   {win}")

# walk-forward 配对 t 检验 (项目铁律: 倍数+MDD 双维度 |t|>=2)
print()
print('=' * 76)
print('Walk-forward 配对 t 检验 (104周窗 / 26周步进, 10y面板)')
print('=' * 76)
W, S = 104, 26
idx = px10.index
mults_a, mults_b, mdds_a, mdds_b = [], [], [], []
for s in range(0, len(idx) - W, S):
    sub = px10.iloc[s:s + W]
    if len(sub) < W:
        break
    ra = m.run_bt(sub, cfg_pure(), label='a')
    rb = m.run_bt(sub, cfg_cur(),  label='b')
    mults_a.append(np.log(max(ra['multiple'], 1e-9)))
    mults_b.append(np.log(max(rb['multiple'], 1e-9)))
    mdds_a.append(ra['mdd']); mdds_b.append(rb['mdd'])

def paired_t(x, y):
    d = np.array(x) - np.array(y)
    if d.std(ddof=1) == 0:
        return 0.0, 0
    t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))
    return t, int((d > 0).sum())

n = len(mults_a)
t_mu, w_mu = paired_t(mults_a, mults_b)
t_md, w_md = paired_t(mdds_a, mdds_b)   # mdd为负, a-b>0 表示 a 回撤更浅
print(f'窗口数 n={n}')
print(f'  log倍数  纯减仓 - 含做空 : t = {t_mu:+.2f}   纯减仓胜 {w_mu}/{n}')
print(f'  MDD      纯减仓 - 含做空 : t = {t_md:+.2f}   纯减仓胜 {w_md}/{n}  (正=纯减仓回撤更浅)')
print()
verdict = ('做空是净损害, 应关闭' if t_mu >= 2 else
           '做空是净增益, 应保留' if t_mu <= -2 else
           '无显著差异 -> 按奥卡姆剃刀选更简单的(纯减仓)')
print(f'裁决: {verdict}')
