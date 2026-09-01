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
"""第二轮: 时间刻减仓为主干, 精调 (a)是否叠加门控做空 (b)crash激进项 (c)ph起点 (d)缩放深度"""
import crypto_options_bt as m

px10 = m.pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()
px = m.pd.read_csv('data/weekly_adjclose_crypto50.csv', index_col=0, parse_dates=True).sort_index()

BASE = dict(halving_cycle_enabled=True, pre_halving_start_month=31.0)
NOSHORT = dict(short_proactive_ma=0, short_cycle_gate=False)

CFGS = {
    'B  减仓0.5/0.5 无做空':            {**BASE, 'halving_crash_risk_scale':0.5,'halving_bear_bottom_risk_scale':0.5, **NOSHORT},
    'D  减仓0.5/0.5 +门控做空':          {**BASE, 'halving_crash_risk_scale':0.5,'halving_bear_bottom_risk_scale':0.5},
    'D2 减仓0.5/0.5 +门控做空(crashAdj关)':{**BASE, 'halving_crash_risk_scale':0.5,'halving_bear_bottom_risk_scale':0.5,'_adj_off':True},
    'F  减仓0.3/0.3 无做空':            {**BASE, 'halving_crash_risk_scale':0.3,'halving_bear_bottom_risk_scale':0.3, **NOSHORT},
    'G  减仓0.3/0.3 +门控做空':          {**BASE, 'halving_crash_risk_scale':0.3,'halving_bear_bottom_risk_scale':0.3},
    'G2 减仓0.3/0.3 +门控做空(crashAdj关)':{**BASE, 'halving_crash_risk_scale':0.3,'halving_bear_bottom_risk_scale':0.3,'_adj_off':True},
    'H  减仓0.3(暴跌)/0.5(筑底) +做空':   {**BASE, 'halving_crash_risk_scale':0.3,'halving_bear_bottom_risk_scale':0.5},
    'I  只暴跌期减仓0.3, 筑底满仓 +做空':  {**BASE, 'halving_crash_risk_scale':0.3,'halving_bear_bottom_risk_scale':1.0},
    'J  减仓0.5/0.5 ph36(保守起点) +做空': {'halving_cycle_enabled':True,'pre_halving_start_month':36.0,'halving_crash_risk_scale':0.5,'halving_bear_bottom_risk_scale':0.5},
}
WINDOWS = [('10y', px10, None), ('主面板9y', px, None), ('5y', px, '2021-08-13'), ('3y', px, '2023-08-11')]

res = {}
for wname, panel, start in WINDOWS:
    p = panel if start is None else panel.loc[start:]
    print("=" * 88)
    print(f"窗口 {wname}: {len(p)}周 {p.index[0].date()}~{p.index[-1].date()}")
    print(f"  {'配置':<40} {'倍数':>11} {'CAGR':>8} {'MDD':>8} {'Sharpe':>7}")
    for name, over in CFGS.items():
        c = dict(m.DEFAULT_CFG); c.update(over)
        m.HALVING_PHASE_ADJUST['crash'] = (1.0,1.0,0) if c.pop('_adj_off', False) else (1.0,2.0,-10)
        r = m.run_bt(p, c, label=name)
        res[(wname,name)] = r
        print(f"  {name:<40} {r['multiple']:>10.1f}x {r['cagr']*100:>7.1f}% {r['mdd']*100:>7.1f}% {r.get('sharpe',0):>7.2f}")
    m.HALVING_PHASE_ADJUST['crash'] = (1.0,2.0,-10)
    print()

# 当前相位 & 未来时间表
print("=" * 88)
print("减半相位时间表 (ph_start=31) —— 实盘意义")
print("=" * 88)
import datetime as dt
for d in ['2024-04-20','2025-04-20','2025-10-20','2026-08-11','2026-11-20','2027-04-20','2028-01-01']:
    date = m.pd.Timestamp(d)
    ph, ms, mn = m.halving_cycle_phase(date, pre_halving_start_month=31.0)
    scale = {'euphoria':1.0,'crash':0.5,'bear_bottom':0.5}.get(ph, 1.0)
    print(f"  {d}  post-halving {ms:>5.1f}月  相位={ph:<13} 风险仓位={scale:.0%}")
