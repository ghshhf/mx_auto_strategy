"""对比: 原 MA 触发 vs 周期门控(高位滞涨确认 + 1年LEAPS) vs 两者组合。
纯本地读面板, 零下载。仅用于诊断, 不改任何默认。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from crypto_options_bt import run_bt

MAIN = 'data/weekly_adjclose_crypto50.csv'
px = pd.read_csv(MAIN, index_col=0, parse_dates=True).sort_index()

CONFIGS = {
    'A. MA触发(原)':        {'short_cycle_gate': False, 'halving_cycle_enabled': False, 'short_proactive_ma': 20},
    'B. 周期门控(仅gate)':  {'short_cycle_gate': True,  'halving_cycle_enabled': False},
    'C. 周期门控+减半风控':  {'short_cycle_gate': True,  'halving_cycle_enabled': True},
}

WINDOWS = [('10y', '2016-08-11'), ('5y', '2021-08-11'), ('3y', '2023-08-11')]

print(f"{'配置':<20}{'窗口':<5}{'倍数':>9}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}{'空头贡献%':>11}")
print('-' * 73)
for name, cfg in CONFIGS.items():
    for wlabel, start in WINDOWS:
        r = run_bt(px, cfg_dict=cfg, label=name, start=start, return_recs=True)
        recs = r.get('recs', [])
        s_sum = sum(getattr(x, 'short_pnl', 0) for x in recs)
        short_pct = s_sum / r['nav'].iloc[-1] * 100 if len(r['nav']) else 0
        print(f"{name:<20}{wlabel:<5}{r['multiple']:>8.2f}x{r['cagr']*100:>8.1f}%"
              f"{r['mdd']*100:>8.1f}%{r['sharpe']:>9.2f}{short_pct:>10.1f}%")
    print()
