# -*- coding: utf-8 -*-
"""选币逻辑消融: 进攻仓位比例(alloc_offense_mult) × 选币数(offense_n) × 权重模式(weight_mode)。
池子: 当前 45 币. 10y 主窗口寻优 → Top 组合验证 5y/3y. 基线=mult1.0/n3/equal.
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

BASE = dict(m.DEFAULT_CFG, halving_cycle_enabled=True,
            halving_euphoria_risk_scale=1.0, halving_crash_risk_scale=0.0,
            halving_bear_bottom_risk_scale=0.0, alt_rs_gate=True,
            pre_halving_start_month=30.0)


def load(p):
    return pd.read_csv(p, index_col=0, parse_dates=True).sort_index()


def run(px, cfg, st):
    return m.run_bt(px, cfg, label='alloc', start=st)


def main():
    px10 = load(TENY)
    # 基线确认(应与上轮 8235.6x 一致)
    base = run(px10, dict(BASE), '2016-08-11')
    print(f"基线(默认): {base['multiple']:.1f}x MDD={base['mdd']*100:.1f}% Sharpe={base['sharpe']:.2f}")

    rows = []
    for om in [1.0, 1.2, 1.4, 1.6]:
        for n in [3, 4]:
            for wm in ['equal', 'score']:
                cfg = dict(BASE, alloc_offense_mult=om, offense_n=n, offense_weight_mode=wm)
                r = run(px10, cfg, '2016-08-11')
                rows.append({'om': om, 'n': n, 'wm': wm,
                             'multiple': r['multiple'], 'mdd': r['mdd'],
                             'sharpe': r['sharpe'], 'cagr': r['cagr']})
                print(f"om={om:<4} n={n} {wm:<5} -> {r['multiple']:>8.0f}x  MDD={r['mdd']*100:>5.1f}%  Sharpe={r['sharpe']:.2f}")

    rows.sort(key=lambda x: x['multiple'], reverse=True)
    print(f"\n=== 10y Top5 按倍数 ===")
    for r in rows[:5]:
        print(f"  om={r['om']} n={r['n']} {r['wm']:<5} {r['multiple']:>8.0f}x MDD={r['mdd']*100:.1f}% Sharpe={r['sharpe']:.2f}")
    # 兼顾回撤: 按 (倍数, -mdd) 综合
    rows2 = sorted(rows, key=lambda x: (x['multiple'] * (1 + x['mdd'] * 0.5)), reverse=True)
    print("=== 10y Top5 按 倍数×(1-0.5|MDD|) 综合 ===")
    for r in rows2[:5]:
        print(f"  om={r['om']} n={r['n']} {r['wm']:<5} {r['multiple']:>8.0f}x MDD={r['mdd']*100:.1f}% Sharpe={r['sharpe']:.2f}")

    # Top2 组合验证 5y/3y
    print("\n=== Top2 全窗口验证 ===")
    picks = [rows[0], rows[1]]
    out = {'generated': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
           'pool': '45 coins', 'base_10y': round(base['multiple'], 3),
           'grid': rows, 'picks_5y3y': []}
    for pk in picks:
        cfg = dict(BASE, alloc_offense_mult=pk['om'], offense_n=pk['n'], offense_weight_mode=pk['wm'])
        for wl, fp, st in [('5y', MAIN, '2021-08-11'), ('3y', MAIN, '2023-08-11')]:
            r = run(load(fp), cfg, st)
            print(f"  om={pk['om']} n={pk['n']} {pk['wm']:<5} {wl}: {r['multiple']:.2f}x MDD={r['mdd']*100:.1f}% Sharpe={r['sharpe']:.2f}")
            out['picks_5y3y'].append({'om': pk['om'], 'n': pk['n'], 'wm': pk['wm'],
                                      'window': wl, 'multiple': round(r['multiple'], 3),
                                      'mdd': round(r['mdd'], 4), 'sharpe': round(r['sharpe'], 3)})
    with open(os.path.join(HERE, 'bt_alloc_opt_results.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('\n[done] -> bt_alloc_opt_results.json')


if __name__ == '__main__':
    main()
