# -*- coding: utf-8 -*-
"""BTC 减半周期回测 (比特币周期为例)。

直接演示引擎内建的 `halving_cycle_enabled` 时间刻减仓层:
  - halving_OFF = 基线 (关掉 BTC 减半日历减仓)
  - halving_ON  = 开启 BTC 减半周期减仓 (accumulation 满仓 / crash+bear_bottom 缩仓)

在 10y / 5y / 3y 三个窗口上对比, 并给出同期 BTC 买入持有基准 + 各减半相位周数分布。
只读本地面板, 不下载。
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import crypto_options_bt as m  # noqa: E402

MAIN = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50.csv')
TENY = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50_10y.csv')


def load(path):
    return pd.read_csv(path, index_col=0, parse_dates=True).sort_index()


WINDOWS = [
    ('10y', TENY, '2016-08-11'),
    ('5y',  MAIN, '2021-08-11'),
    ('3y',  MAIN, '2023-08-11'),
]


def fmt(r):
    return (f"{r['multiple']:>9.1f}x  CAGR {r['cagr']*100:>6.1f}%  "
            f"MDD {r['mdd']*100:>6.1f}%  Sharpe {r['sharpe']:>5.2f}")


def main():
    rows = []
    print(f"{'窗口':<5}{'模式':<12}{'倍数':>10}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}{'BTC持有':>10}   起止")
    print('-' * 82)
    for wlabel, fpath, start in WINDOWS:
        px = load(fpath)
        px_s = px[px.index >= pd.Timestamp(start)]
        rng = f"{px_s.index[0].date()}~{px_s.index[-1].date()}"
        btc = px_s['BTC'].dropna()
        btc_bh = float(btc.iloc[-1] / btc.iloc[0]) if len(btc) >= 2 else None
        for tag, halv in [('halving_OFF', False), ('halving_ON', True)]:
            cfg = dict(m.DEFAULT_CFG, halving_cycle_enabled=halv)
            r = m.run_bt(px, cfg, label=f'{wlabel}/{tag}', start=start)
            print(f"{wlabel:<5}{tag:<12}{r['multiple']:>9.2f}x"
                  f"{r['cagr']*100:>8.1f}%{r['mdd']*100:>8.1f}%"
                  f"{r['sharpe']:>9.2f}"
                  f"{('' if btc_bh is None else f'{btc_bh*100:>8.0f}%')}   {rng}")
            rows.append({
                'window': wlabel, 'mode': tag, 'halving_cycle_enabled': halv,
                'multiple': round(r['multiple'], 3), 'cagr': round(r['cagr'], 4),
                'mdd': round(r['mdd'], 4), 'sharpe': round(r['sharpe'], 3),
                'btc_buyhold': (round(btc_bh, 3) if btc_bh is not None else None),
                'start': start, 'data_range': rng, 'n_weeks': int(len(px_s)),
            })
        print()

    # 减半相位周数分布 (主面板, 用默认 pre_halving_start_month)
    print('减半相位周数分布 (主面板 2017-08-11~, 默认 pre_halving_start_month=36):')
    ph = [m.halving_cycle_phase(d, pre_halving_start_month=36.0)[0] for d in px_s.index]
    from collections import Counter
    cnt = Counter(ph)
    tot = sum(cnt.values())
    for k in ['accumulation', 'euphoria', 'crash', 'bear_bottom', 'pre_halving', 'pre_data']:
        if cnt.get(k):
            print(f"  {k:<14}: {cnt[k]:>4} 周 ({cnt[k]/tot*100:>4.1f}%)")
    print(f"  {'合计':<14}: {tot:>4} 周")

    # 写出结果
    out = {'generated': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
           'note': 'halving_OFF=关BTC减半日历减仓(基线); halving_ON=开(比特币周期时间刻减仓)',
           'windows': rows}
    with open(os.path.join(HERE, 'bt_halving_cycle_results.json'), 'w', encoding='utf-8') as f:
        import json
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('\n[done] -> bt_halving_cycle_results.json')


if __name__ == '__main__':
    main()
