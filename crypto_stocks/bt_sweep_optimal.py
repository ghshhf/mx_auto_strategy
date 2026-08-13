# -*- coding: utf-8 -*-
"""在【当前 50 币池】上重做 README 37000x 版本的参数寻优，看能否把倍数推回原始量级。
基线 = 37k 版本：halving_ON + cr=bb=0.0 + alt_rs_gate + pre_halving_start_month=31.0
分阶段扫描：
  A) pre_halving_start_month 网格（主杠杆，README 二次修订就是调它）
  B) 在 A  winner 上扫 alt_rs_ma（README 标称 22 最优）
  C) 在 (A,B) winner 上扫 cr=bb 下行清仓比例（README 标称 0.0 最优）
  D) 全局 winner 跑 10y/5y/3y 全窗口 + BTC 买入持有基准
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


def base_cfg(**ov):
    d = dict(m.DEFAULT_CFG,
             halving_cycle_enabled=True,
             halving_euphoria_risk_scale=1.0,
             halving_crash_risk_scale=0.0,
             halving_bear_bottom_risk_scale=0.0,
             alt_rs_gate=True)
    d.update(ov)
    return d


def run10y(cfg):
    px = load(TENY)
    r = m.run_bt(px, cfg, label='sweep', start='2016-08-11')
    return r


def run_all(cfg):
    rows = []
    windows = [('10y', TENY, '2016-08-11'),
               ('5y', MAIN, '2021-08-11'),
               ('3y', MAIN, '2023-08-11')]
    for wl, fp, st in windows:
        px = load(fp)
        r = m.run_bt(px, cfg, label=f'{wl}', start=st)
        btc = px[px.index >= pd.Timestamp(st)]['BTC'].dropna()
        btc_bh = float(btc.iloc[-1] / btc.iloc[0]) if len(btc) >= 2 else None
        rng = f"{px[px.index >= pd.Timestamp(st)].index[0].date()}~{px[px.index >= pd.Timestamp(st)].index[-1].date()}"
        rows.append({'window': wl, 'multiple': round(r['multiple'], 3),
                     'cagr': round(r['cagr'], 4), 'mdd': round(r['mdd'], 4),
                     'sharpe': round(r['sharpe'], 3),
                     'btc_buyhold': round(btc_bh, 3) if btc_bh is not None else None,
                     'range': rng})
    return rows


def main():
    print("="*78)
    print("当前 50 币池 | 37k 版本参数重寻优")
    print("="*78)

    # ---- A) pre_halving_start_month ----
    grid_php = [22, 24, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 38, 40, 42]
    print(f"\n[A] pre_halving_start_month 扫描 ({len(grid_php)} 点, 10y)")
    print(f"{'php':>5}{'倍数':>11}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}")
    a_res = []
    for php in grid_php:
        r = run10y(base_cfg(pre_halving_start_month=float(php)))
        a_res.append((php, r))
        print(f"{php:>5}{r['multiple']:>10.1f}x{r['cagr']*100:>8.1f}%{r['mdd']*100:>8.1f}%{r['sharpe']:>9.2f}")
    a_res.sort(key=lambda x: x[1]['multiple'], reverse=True)
    php_star = a_res[0][0]
    print(f"\n  -> A winner: php={php_star}  (10y {a_res[0][1]['multiple']:.1f}x)")
    top3_php = [x[0] for x in a_res[:3]]

    # ---- B) alt_rs_ma @ php_star ----
    grid_ma = [20, 21, 22, 23, 24]
    print(f"\n[B] alt_rs_ma 扫描 @ php={php_star} ({len(grid_ma)} 点, 10y)")
    print(f"{'ma':>4}{'倍数':>11}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}")
    b_res = []
    for ma in grid_ma:
        r = run10y(base_cfg(pre_halving_start_month=float(php_star), alt_rs_ma=ma))
        b_res.append((ma, r))
        print(f"{ma:>4}{r['multiple']:>10.1f}x{r['cagr']*100:>8.1f}%{r['mdd']*100:>8.1f}%{r['sharpe']:>9.2f}")
    b_res.sort(key=lambda x: x[1]['multiple'], reverse=True)
    ma_star = b_res[0][0]
    print(f"\n  -> B winner: alt_rs_ma={ma_star}  (10y {b_res[0][1]['multiple']:.1f}x)")

    # ---- C) cr=bb @ (php_star, ma_star) ----
    grid_cb = [0.0, 0.05, 0.1, 0.15]
    print(f"\n[C] 下行清仓比例 cr=bb 扫描 @ php={php_star}, ma={ma_star}")
    print(f"{'crb':>5}{'倍数':>11}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}")
    c_res = []
    for cb in grid_cb:
        r = run10y(base_cfg(pre_halving_start_month=float(php_star),
                            alt_rs_ma=ma_star,
                            halving_crash_risk_scale=cb,
                            halving_bear_bottom_risk_scale=cb))
        c_res.append((cb, r))
        print(f"{cb:>5}{r['multiple']:>10.1f}x{r['cagr']*100:>8.1f}%{r['mdd']*100:>8.1f}%{r['sharpe']:>9.2f}")
    c_res.sort(key=lambda x: x[1]['multiple'], reverse=True)
    cb_star = c_res[0][0]
    print(f"\n  -> C winner: cr=bb={cb_star}  (10y {c_res[0][1]['multiple']:.1f}x)")

    # ---- D) 全局 winner 全窗口 ----
    win_cfg = base_cfg(pre_halving_start_month=float(php_star),
                       alt_rs_ma=ma_star,
                       halving_crash_risk_scale=cb_star,
                       halving_bear_bottom_risk_scale=cb_star)
    print(f"\n[D] 全局 winner 配置全窗口:")
    print(f"    pre_halving_start_month={php_star}, alt_rs_ma={ma_star}, cr=bb={cb_star}")
    full = run_all(win_cfg)
    print(f"\n{'窗口':<5}{'倍数':>11}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}{'BTC持有':>10}   起止")
    for row in full:
        print(f"{row['window']:<5}{row['multiple']:>10.1f}x{row['cagr']*100:>8.1f}%"
              f"{row['mdd']*100:>8.1f}%{row['sharpe']:>9.2f}"
              f"{('' if row['btc_buyhold'] is None else f'{row['btc_buyhold']*100:>8.0f}%')}   {row['range']}")

    # 对照：原始 37k 文档档(php=31) 在当前池
    base_now = run_all(base_cfg(pre_halving_start_month=31.0))

    out = {
        'generated': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
        'pool': 'current 50 coins',
        'A_pre_halving_start_month': [{'php': p, 'multiple': round(r['multiple'], 3),
                                        'cagr': round(r['cagr'], 4), 'mdd': round(r['mdd'], 4),
                                        'sharpe': round(r['sharpe'], 3)} for p, r in a_res],
        'B_alt_rs_ma': [{'ma': a, 'multiple': round(r['multiple'], 3),
                         'mdd': round(r['mdd'], 4), 'sharpe': round(r['sharpe'], 3)} for a, r in b_res],
        'C_crbb': [{'crbb': c, 'multiple': round(r['multiple'], 3),
                    'mdd': round(r['mdd'], 4), 'sharpe': round(r['sharpe'], 3)} for c, r in c_res],
        'winner': {'pre_halving_start_month': php_star, 'alt_rs_ma': ma_star, 'crbb': cb_star,
                   'full_windows': full},
        'baseline_37k_on_current_pool': {'pre_halving_start_month': 31.0, 'full_windows': base_now},
    }
    with open(os.path.join(HERE, 'bt_sweep_optimal_results.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('\n[done] -> bt_sweep_optimal_results.json')


if __name__ == '__main__':
    main()
