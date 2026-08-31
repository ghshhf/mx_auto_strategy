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
"""复现 17000x 的时间刻减仓机制, 并与当前默认(反应式MA做空)对比。
核心假设: 17000x 的 alpha 来自 halving_*_risk_scale(见顶/暴跌期砍半仓),
而非 HALVING_PHASE_ADJUST 的 crash 做空x2/MA收紧。
"""
import crypto_options_bt as m

px10 = m.pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()
px = m.pd.read_csv('data/weekly_adjclose_crypto50.csv', index_col=0, parse_dates=True).sort_index()
print(f"[10y面板] {len(px10)}周 {px10.index[0].date()}~{px10.index[-1].date()}")
print(f"[主面板 ] {len(px)}周 {px.index[0].date()}~{px.index[-1].date()}\n")

CFGS = {
    'A 当前默认(halving关, MA20做空+周期门控)': dict(),
    'B 17000x原参(halving开0.5/0.5/ph31, 关我的做空)': dict(
        halving_cycle_enabled=True, halving_crash_risk_scale=0.5,
        halving_bear_bottom_risk_scale=0.5, pre_halving_start_month=31.0,
        short_proactive_ma=0, short_cycle_gate=False),
    'C 纯减仓(只risk_scale, 不要crash做空x2/MA收紧)': dict(
        halving_cycle_enabled=True, halving_crash_risk_scale=0.5,
        halving_bear_bottom_risk_scale=0.5, pre_halving_start_month=31.0,
        short_proactive_ma=0, short_cycle_gate=False,
        halving_phase_adjust_off=True),
    'D 减仓 + 我的周期门控做空(叠加)': dict(
        halving_cycle_enabled=True, halving_crash_risk_scale=0.5,
        halving_bear_bottom_risk_scale=0.5, pre_halving_start_month=31.0),
    'E 减仓 + 见顶期也砍半(eu0.5)': dict(
        halving_cycle_enabled=True, halving_euphoria_risk_scale=0.5,
        halving_crash_risk_scale=0.5, halving_bear_bottom_risk_scale=0.5,
        pre_halving_start_month=31.0, short_proactive_ma=0, short_cycle_gate=False),
    'F 激进减仓 cr0.3/bb0.3 (README称全局最优16476x)': dict(
        halving_cycle_enabled=True, halving_crash_risk_scale=0.3,
        halving_bear_bottom_risk_scale=0.3, pre_halving_start_month=31.0,
        short_proactive_ma=0, short_cycle_gate=False),
}

WINDOWS = [('10y', px10, None), ('全主面板', px, None),
           ('5y', px, '2021-08-11'), ('3y', px, '2023-08-11')]

for wname, panel, start in WINDOWS:
    p = panel if start is None else panel.loc[start:]
    print("=" * 92)
    print(f"窗口 {wname}: {len(p)}周 {p.index[0].date()}~{p.index[-1].date()}")
    print("=" * 92)
    print(f"  {'配置':<48} {'倍数':>11} {'CAGR':>8} {'MDD':>8} {'Sharpe':>7}")
    for name, over in CFGS.items():
        c = dict(m.DEFAULT_CFG)
        c.update(over)
        if c.pop('halving_phase_adjust_off', False):
            m.HALVING_PHASE_ADJUST['crash'] = (1.00, 1.00, 0)
        else:
            m.HALVING_PHASE_ADJUST['crash'] = (1.00, 2.00, -10)
        try:
            r = m.run_bt(p, c, label=name)
            print(f"  {name:<48} {r['multiple']:>10.1f}x {r['cagr']*100:>7.1f}% "
                  f"{r['mdd']*100:>7.1f}% {r.get('sharpe',0):>7.2f}")
        except Exception as e:
            print(f"  {name:<48} ERROR {e}")
    m.HALVING_PHASE_ADJUST['crash'] = (1.00, 2.00, -10)
    # BTC 基准
    if 'BTC' in p.columns:
        s = p['BTC'].dropna()
        print(f"  {'[基准] BTC 买入持有':<48} {s.iloc[-1]/s.iloc[0]:>10.1f}x")
    print()
