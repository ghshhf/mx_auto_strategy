"""bt_leg_decompose.py - 策略腿拆解：同一最优参数下，逐腿开关，看 10y 倍率构成。
回答：期权(covered call)是不是真参与？做空/put 保险各贡献多少？
输出 bt_leg_decompose_report.txt
"""
import os, sys, json
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crypto_options_bt as C
from crypto_options_bt import run_bt

TENY = pd.read_csv(f'{HERE}/data/weekly_adjclose_crypto50_10y.csv',
                   index_col=0, parse_dates=True).sort_index()
px = TENY[TENY.index >= pd.Timestamp('2016-08-11')]

NEW_PARAMS = {
    'take_profit_pct': 1.5, 'call_strike_otm': 1.7, 'short_proactive_ma': 15,
    'alt_rs_ma': 26, 'ovl_mom26': 1.0, 'short_cycle_exit_ma': 30,
    'put_bigcap_crash': 0.08, 'put_bigcap_payout_ratio': 0.5,
    'put_cost_weekly_bps': 80, 'halving_derisk_offense_first': True,
    'halving_crash_risk_scale': 0.3, 'put_single_crash': 0.2,
    'ovl_premium_mult': 3.0, 'short_proactive_cooldown': 10,
}

def mk_cfg(extra=None):
    cfg = dict(C.DEFAULT_CFG)
    for k, v in NEW_PARAMS.items():
        cfg[k] = v
    if extra:
        cfg.update(extra)
    return cfg

def fmt(v):
    return f'{v:,.0f}x' if v >= 1000 else f'{v:.1f}x'

VARIANT = [
    ('全开（完整策略）', {}),
    ('关 covered call（enabled_call+ovl=False）', {'enabled_call': False, 'enabled_ovl': False}),
    ('关做空（enabled_short=False）', {'enabled_short': False}),
    ('关 put 保险（enabled_put=False）', {'enabled_put': False}),
    ('关期权+做空+put（只剩现货轮动）', {'enabled_call': False, 'enabled_ovl': False,
                                      'enabled_short': False, 'enabled_put': False}),
]

lines = []
lines.append('=' * 78)
lines.append('策略腿拆解 · 当前面板(50币) + 最优参数(NEW_PARAMS) · 10y窗口(2016-08起)')
lines.append('=' * 78)
base_mult = None
for name, ov in VARIANT:
    C._ALT_RS_CACHE.clear()
    r = run_bt(px, mk_cfg(ov), label=name)
    mult = r['multiple']
    if base_mult is None:
        base_mult = mult
    delta = f"{(mult/base_mult-1)*100:+.0f}%" if base_mult else ''
    ev = r['events']
    line = (f"{name}\n"
            f"  10y倍率 {fmt(mult):>14s}  vs全开 {delta:>6s}   CAGR {r['cagr']*100:+.1f}%  "
            f"MDD {r['mdd']*100:.1f}%  Sharpe {r['sharpe']:.2f}\n"
            f"  事件: 止盈call {ev['tp_calls']}次 高估call {ev['ovl_calls']}次 "
            f"call周收 {ev['avg_call_income_pw']:.2f}%  put周收 {ev['avg_put_income_pw']:.2f}% "
            f"空头周收 {ev['avg_short_pnl_pw']:.2f}%")
    lines.append(line)
    print(line)

# 纯 buy&hold 基准：全池等权周再平衡
rets = px.pct_change().fillna(0.0)
eq = rets.mean(axis=1)  # 等权组合周收益
nav_eq = (1 + eq).cumprod().dropna()
m_eq = float(nav_eq.iloc[-1]) if len(nav_eq) else float('nan')
lines.append(f'纯buy&hold基准(50币等权周再平衡): {fmt(m_eq)}')
lines.append(f'纯BTC基准: {fmt(float(px["BTC"].iloc[-1]/px["BTC"].iloc[0]))}x')
lines.append('')
lines.append('注: 倍率差距即各"腿"在完整策略中的贡献; 贡献非加性, 腿间有交互。')
print('\n'.join(lines[-3:]))

report = f'{HERE}/bt_leg_decompose_report.txt'
with open(report, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
print(f'已保存: {report}')
