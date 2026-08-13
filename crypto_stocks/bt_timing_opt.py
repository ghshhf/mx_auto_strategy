# -*- coding: utf-8 -*-
"""时机信号篮子优化 A/B：原版全面板(all) vs 持仓驱动(held)。
验证用户论点: 死重/占位币(从没涨过)的噪声拉偏减仓时机, 且池子增删随机移动信号
(STRK删→−16.2%)。held = 时机只按上周实际持仓的进攻币算 → 死币从不被选入,
删/加它不再动信号。默认行为不变(all)。
"""
import os
import sys
import json

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crypto_options_bt as m  # noqa: E402

MAIN = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50.csv')
TENY = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50_10y.csv')


def load(path):
    return pd.read_csv(path, index_col=0, parse_dates=True).sort_index()


BASE = dict(m.DEFAULT_CFG, halving_cycle_enabled=True,
            halving_euphoria_risk_scale=1.0, halving_crash_risk_scale=0.0,
            halving_bear_bottom_risk_scale=0.0, alt_rs_gate=True,
            pre_halving_start_month=30.0)   # 当前池最优档

WINDOWS = [('10y', TENY, '2016-08-11'),
           ('5y', MAIN, '2021-08-11'),
           ('3y', MAIN, '2023-08-11')]


def main():
    print("=" * 80)
    print("时机信号篮子优化 A/B | 当前 50 币池 | 档: halving_ON+cr=bb=0+php=30")
    print("='all' 原版全面板 vs 'held' 按上周实际持仓算时机")
    print("=" * 80)

    print(f"\n{'模式':<8}{'窗口':<5}{'倍数':>10}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}")
    print('-' * 55)
    out = {'generated': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
           'pool': 'current 50 coins', 'ab': []}
    for mode in ('all', 'held'):
        cfg = dict(BASE, alt_rs_universe=mode, alt_rs_verbose=(mode == 'held'))
        for wl, fp, st in WINDOWS:
            px = load(fp)
            r = m.run_bt(px, cfg, label=f'{mode}/{wl}', start=st)
            print(f"{mode:<8}{wl:<5}{r['multiple']:>9.1f}x{r['cagr']*100:>8.1f}%"
                  f"{r['mdd']*100:>8.1f}%{r['sharpe']:>9.2f}")
            out['ab'].append({'mode': mode, 'window': wl,
                              'multiple': round(r['multiple'], 3), 'cagr': round(r['cagr'], 4),
                              'mdd': round(r['mdd'], 4), 'sharpe': round(r['sharpe'], 3)})
        print()

    a10 = [x for x in out['ab'] if x['window'] == '10y' and x['mode'] == 'all']
    b10 = [x for x in out['ab'] if x['window'] == '10y' and x['mode'] == 'held']
    if a10 and b10:
        d = (b10[0]['multiple'] / a10[0]['multiple'] - 1) * 100
        print(f"10y: all={a10[0]['multiple']:.0f}x -> held={b10[0]['multiple']:.0f}x "
              f"({'+' if d >= 0 else ''}{d:.1f}%)")
    with open(os.path.join(HERE, 'bt_timing_opt_results.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('\n[done] -> bt_timing_opt_results.json')


if __name__ == '__main__':
    main()
