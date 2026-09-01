# -*- coding: utf-8 -*-

# --- [relocated 2026-08-31] 目录重构引导: 等效于在 markets/crypto/ 根目录下运行 ---
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
"""加 LTC 后的回测: V6 默认档(php=30) 10y/5y/3y + 最优档(php=30,ma=21) 10y。
对照加 LTC 前: 默认档 21664x/8.2x/2.6x (50币); 最优档 22821x (50币, php=30,ma=21)。
"""
import os
import sys
import json

import pandas as pd

HERE = _CS_ROOT  # [relocated] 原指向脚本目录, 迁移后指向 crypto_stocks 根
sys.path.insert(0, HERE)
import crypto_options_bt as m  # noqa: E402

MAIN = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50.csv')
TENY = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50_10y.csv')


def load(path):
    return pd.read_csv(path, index_col=0, parse_dates=True).sort_index()


DEFAULT = dict(m.DEFAULT_CFG)
OPTIMAL = dict(m.DEFAULT_CFG, pre_halving_start_month=30.0, alt_rs_ma=21)

WINDOWS = [('10y', TENY, '2016-08-11'),
           ('5y', MAIN, '2021-08-11'),
           ('3y', MAIN, '2023-08-11')]


def main():
    px_main = load(MAIN)
    print(f"[池] 面板列数={len(px_main.columns)}, 含LTC={'LTC' in px_main.columns}, "
          f"LTC首有效={px_main['LTC'].first_valid_index().date()}, "
          f"末值={px_main['LTC'].iloc[-1]:.2f}")

    out = {'generated': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
           'pool': 'current 51 coins (50+LTC)', 'rows': []}
    print(f"\n{'配置':<22}{'窗口':<5}{'倍数':>10}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}")
    print('-' * 66)
    for cfg, cname in [(DEFAULT, '默认档(php=30)'), (OPTIMAL, '最优档(php=30,ma=21)')]:
        for wl, fp, st in WINDOWS:
            if cname.startswith('最优') and wl != '10y':
                continue
            px = load(fp)
            r = m.run_bt(px, cfg, label=f'{cname}/{wl}', start=st)
            print(f"{cname:<22}{wl:<5}{r['multiple']:>9.1f}x{r['cagr']*100:>8.1f}%"
                  f"{r['mdd']*100:>8.1f}%{r['sharpe']:>9.2f}")
            out['rows'].append({'cfg': cname, 'window': wl, 'multiple': round(r['multiple'], 3),
                                'cagr': round(r['cagr'], 4), 'mdd': round(r['mdd'], 4),
                                'sharpe': round(r['sharpe'], 3)})
    with open(os.path.join(HERE, 'reports', 'bt_after_LTC.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('\n[done] -> bt_after_LTC.json')


if __name__ == '__main__':
    main()
