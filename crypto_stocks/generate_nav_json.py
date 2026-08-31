"""generate_nav_json.py - 生成旧基线/新优化净值序列(三窗口)供可视化使用。
输出: nav_curves.json  {window: {dates:[], old:[], new:[]}}
"""
import os, sys, json
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

OLD_BASE = {
    'take_profit_pct': 2.0, 'call_strike_otm': 1.5, 'short_proactive_ma': 20,
    'alt_rs_ma': 22, 'ovl_mom26': 1.5, 'short_cycle_exit_ma': 40,
    'put_bigcap_crash': 0.12, 'put_bigcap_payout_ratio': 0.3,
    'put_cost_weekly_bps': 30, 'halving_derisk_offense_first': False,
    'halving_crash_risk_scale': 0.0, 'put_single_crash': 0.3,
    'ovl_premium_mult': 2.0, 'short_proactive_cooldown': 13,
}
NEW_PARAMS = {
    'take_profit_pct': 1.5, 'call_strike_otm': 1.7, 'short_proactive_ma': 15,
    'alt_rs_ma': 26, 'ovl_mom26': 1.0, 'short_cycle_exit_ma': 30,
    'put_bigcap_crash': 0.08, 'put_bigcap_payout_ratio': 0.5,
    'put_cost_weekly_bps': 80, 'halving_derisk_offense_first': True,
    'halving_crash_risk_scale': 0.3, 'put_single_crash': 0.2,
    'ovl_premium_mult': 3.0, 'short_proactive_cooldown': 10,
}

def cfg_for(overrides):
    cfg = dict(C.DEFAULT_CFG)
    for k, v in OLD_BASE.items():
        cfg[k] = v
    for k, v in overrides.items():
        cfg[k] = v
    return cfg

out = {}
for name, pnl, st in WINDOWS:
    px = pnl[pnl.index >= pd.Timestamp(st)]
    rows = {'dates': [d.strftime('%Y-%m-%d') for d in px.index]}
    for tag, ov in [('old', {}), ('new', NEW_PARAMS)]:
        C._ALT_RS_CACHE.clear()
        r = run_bt(px, cfg_for(ov))
        nav = [round(float(x), 6) for x in r['nav']]
        rows[tag] = nav
        print(f"{name} {tag}: multiple={r['multiple']:.2f} mdd={r['mdd']*100:.1f}% sharpe={r['sharpe']:.2f} weeks={len(nav)}")
    out[name] = rows

path = os.path.join(HERE, 'reports', 'nav_curves.json')
with open(path, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False)
print(f"已保存: {path}")
