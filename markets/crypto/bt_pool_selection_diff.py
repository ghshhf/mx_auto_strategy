# -*- coding: utf-8 -*-
"""受控实验: 旧面板(60币, 1ace9eb时代) vs 新面板(50币) × 旧逻辑 vs 新逻辑。
逐周记录持仓 → 验证用户论点"两次选的币一模一样, 倍数却少1万倍"。
分解: A)旧面板+旧逻辑 B)新面板+旧逻辑 C)新面板+新逻辑(现状) D)旧面板+新逻辑
  A vs B = 死币(旧面板里的已删币)在 alt-RS 时机篮子里的影响(选币宇宙相同, 纯篮子效应)
  B vs C = 逻辑漂移(分阶段选币/fixed norm/php/ma)
"""
import os
import sys
import json

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crypto_options_bt as m  # noqa: E402

NEW_MAIN = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50.csv')
NEW_TENY = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50_10y.csv')
OLD_MAIN = os.path.join(HERE, '_old_panel_main.csv')
OLD_TENY = os.path.join(HERE, '_old_panel_10y.csv')


def load(path):
    return pd.read_csv(path, index_col=0, parse_dates=True).sort_index()


# 旧逻辑(近似 1ace9eb: php=31, ma=20, 均匀Top3, avail动态分母, 无相位期权过滤)
OLD_LOGIC = dict(m.DEFAULT_CFG,
                 halving_cycle_enabled=True, halving_euphoria_risk_scale=1.0,
                 halving_crash_risk_scale=0.0, halving_bear_bottom_risk_scale=0.0,
                 pre_halving_start_month=31.0,
                 alt_rs_gate=True, alt_rs_ma=20, alt_rs_scale=0.0, alt_rs_to_defense=True,
                 alt_rs_recovery=False,
                 offense_phase_selection=False, option_filter_phases=(),
                 theme_weight_norm='avail', alt_rs_universe='all')
# 新逻辑(现状默认: php=30, ma=22, 分阶段选币, fixed, 相位期权过滤)
NEW_LOGIC = dict(m.DEFAULT_CFG, alt_rs_universe='all')


def offense_set(held):
    if not held:
        return set()
    return {c for c, v in held.items() if v and v > 0 and c not in ('BTC', 'ETH', 'STABLE')}


def run(label, px, cfg):
    r = m.run_bt(px, cfg, label=label, start='2016-08-11',
                 return_recs=True, record_holdings=True)
    return r


def main():
    old = load(OLD_TENY)
    new = load(NEW_TENY)
    print("=" * 84)
    print("旧面板(60币) vs 新面板(50币) · 10y 窗口 · 逐周选币对比")
    print("=" * 84)

    # 旧面板里有哪些币在旧ca2进攻宇宙但不在当前ca2(即"已删且曾被选中")
    import crypto_adoption_v2 as ca2
    old_cols = set(old.columns)
    del_selectable_old = sorted(old_cols & (set(old.columns) - set(new.columns)))
    print(f"\n旧面板独有列(已删币, 当前不可选, 只进时机篮子): {del_selectable_old}")

    runs = {
        'A_旧面板+旧逻辑': run('A', old, OLD_LOGIC),
        'B_新面板+旧逻辑': run('B', new, OLD_LOGIC),
        'C_新面板+新逻辑': run('C', new, NEW_LOGIC),
        'D_旧面板+新逻辑': run('D', old, NEW_LOGIC),
    }
    print(f"\n{'运行':<14}{'倍数':>11}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}")
    print('-' * 56)
    for k, r in runs.items():
        print(f"{k:<14}{r['multiple']:>10.1f}x{r['cagr']*100:>8.1f}%"
              f"{r['mdd']*100:>8.1f}%{r['sharpe']:>9.2f}")

    def overlap(r1, r2):
        recs1 = [x for x in r1['recs'] if x.held]
        recs2 = [x for x in r2['recs'] if x.held]
        n = min(len(recs1), len(recs2))
        same = 0
        tot = 0
        for i in range(n):
            s1 = offense_set(recs1[i].held)
            s2 = offense_set(recs2[i].held)
            if not s1 and not s2:
                same += 1; tot += 1; continue
            if s1 or s2:
                tot += 1
                if s1 == s2:
                    same += 1
        return same, tot, (same / tot if tot else float('nan'))

    print("\n--- 逐周进攻选币一致性(offense_set 完全相等周数 / 有持仓周数) ---")
    for a, b in [('A_旧面板+旧逻辑', 'B_新面板+旧逻辑'),
                 ('B_新面板+旧逻辑', 'C_新面板+新逻辑'),
                 ('C_新面板+新逻辑', 'D_旧面板+新逻辑')]:
        same, tot, pct = overlap(runs[a], runs[b])
        print(f"  {a} vs {b}: {same}/{tot} 周完全一致 = {pct*100:.1f}%")

    # NAV 路径相关性
    print("\n--- NAV 周路径相关性(同期) ---")
    for a, b in [('A_旧面板+旧逻辑', 'B_新面板+旧逻辑'),
                 ('B_新面板+旧逻辑', 'C_新面板+新逻辑')]:
        n1 = runs[a]['nav']; n2 = runs[b]['nav']
        idx = n1.index.intersection(n2.index)
        corr = np.corrcoef(n1.loc[idx].values, n2.loc[idx].values)[0, 1]
        print(f"  {a} vs {b}: corr={corr:.4f}")

    out = {
        'generated': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
        'old_panel_cols': sorted(old.columns),
        'new_panel_cols': sorted(new.columns),
        'deleted_in_old_panel': del_selectable_old,
        'results': {k: {'multiple': round(v['multiple'], 3), 'cagr': round(v['cagr'], 4),
                        'mdd': round(v['mdd'], 4), 'sharpe': round(v['sharpe'], 3)}
                    for k, v in runs.items()},
    }
    with open(os.path.join(HERE, 'bt_pool_selection_diff.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('\n[done] -> bt_pool_selection_diff.json')


if __name__ == '__main__':
    main()
