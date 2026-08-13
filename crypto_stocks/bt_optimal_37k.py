# -*- coding: utf-8 -*-
"""跑 README 的"最优 37000x 版本"：BTC 减半周期 + 下行完全离场(cr=bb=0.0) + alt_rs_gate。
精确对齐 README §1.2 二次修订档：pre_halving_start_month=31.0（引擎默认已 30.0，这里显式置 31）。
当前 50 币池。10y/5y/3y 三窗口 + BTC 买入持有基准。
"""
import os
import sys
import json

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crypto_options_bt as m  # noqa: E402

MAIN = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50.csv')
TENY = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50_10y.csv')


def load(path):
    return pd.read_csv(path, index_col=0, parse_dates=True).sort_index()


# 精确对齐 README 37000x 档
OPTIMAL = dict(m.DEFAULT_CFG,
               halving_cycle_enabled=True,
               halving_euphoria_risk_scale=1.0,
               halving_crash_risk_scale=0.0,
               halving_bear_bottom_risk_scale=0.0,
               pre_halving_start_month=31.0,
               alt_rs_gate=True)

WINDOWS = [
    ('10y', TENY, '2016-08-11'),
    ('5y',  MAIN, '2021-08-11'),
    ('3y',  MAIN, '2023-08-11'),
]


def main():
    rows = []
    print("== 最优 37000x 版本 (cr=bb=0.0 + alt_rs_gate, pre_halving_start_month=31) | 当前 50 币池 ==")
    print(f"{'窗口':<5}{'倍数':>10}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}{'BTC持有':>10}   起止")
    print('-' * 70)
    for wlabel, fpath, start in WINDOWS:
        px = load(fpath)
        px_s = px[px.index >= pd.Timestamp(start)]
        rng = f"{px_s.index[0].date()}~{px_s.index[-1].date()}"
        btc = px_s['BTC'].dropna()
        btc_bh = float(btc.iloc[-1] / btc.iloc[0]) if len(btc) >= 2 else None
        r = m.run_bt(px, OPTIMAL, label=f'{wlabel}/optimal37k', start=start)
        print(f"{wlabel:<5}{r['multiple']:>9.1f}x"
              f"{r['cagr']*100:>8.1f}%{r['mdd']*100:>8.1f}%"
              f"{r['sharpe']:>9.2f}"
              f"{('' if btc_bh is None else f'{btc_bh*100:>8.0f}%')}   {rng}")
        rows.append({'window': wlabel, 'multiple': round(r['multiple'], 3),
                     'cagr': round(r['cagr'], 4), 'mdd': round(r['mdd'], 4),
                     'sharpe': round(r['sharpe'], 3),
                     'btc_buyhold': round(btc_bh, 3) if btc_bh is not None else None,
                     'start': start, 'data_range': rng, 'n_weeks': int(len(px_s))})
    out = {'generated': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
           'config': 'halving_ON + cr=bb=0.0 + alt_rs_gate + pre_halving_start_month=31.0',
           'pool': 'current 50 coins', 'windows': rows}
    with open(os.path.join(HERE, 'bt_optimal_37k_results.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('\n[done] -> bt_optimal_37k_results.json')


if __name__ == '__main__':
    main()
