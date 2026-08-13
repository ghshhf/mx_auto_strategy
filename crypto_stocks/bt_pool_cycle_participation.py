# -*- coding: utf-8 -*-
"""当前 50 币池 · 三轮减半周期"历史是否涨过"体检。
对每个币，在 C1(2016-08~2020-05)/C2(2020-05~2024-04)/C3(2024-04~2026-08)
三个窗口算 peak/start 涨幅，标记 >=3x(真涨过) / >=10x(疯涨过)。
输出每币参与的周期数 + 从没涨过的死重大名单。
"""
import os
import sys
import json

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
TENY = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50_10y.csv')

ADDED = {'XLM': 'L1公链(本轮加)', 'INJ': 'Injective(本轮加)', 'JOE': 'TraderJoe(本轮加)'}
# 本轮删掉的(对照用)
DELETED = {'STRK': 'StarkNet', 'SEI': 'Sei', 'BEAM': 'Beam(隐私)', 'PAS': 'PAS(模块化)'}


def load(path):
    return pd.read_csv(path, index_col=0, parse_dates=True).sort_index()


CYCLES = [('C1_2017', '2016-08-11', '2020-05-11'),
          ('C2_2021', '2020-05-11', '2024-04-19'),
          ('C3_2024', '2024-04-19', '2026-08-07')]


def main():
    px = load(TENY)
    cols = [c for c in px.columns if c not in ('STABLE',)]
    rows = []
    for c in cols:
        ser = px[c].dropna()
        if len(ser) < 5:
            continue
        rec = {'coin': c, 'added': ADDED.get(c, ''), 'deleted': DELETED.get(c, '')}
        part3 = part10 = 0
        gains = []
        for name, s, e in CYCLES:
            w = ser[(ser.index >= pd.Timestamp(s)) & (ser.index <= pd.Timestamp(e))]
            if len(w) < 3:
                rec[name] = None
                continue
            start = float(w.iloc[0])
            peak = float(w.max())
            g = peak / start if start > 0 else np.nan
            rec[name] = round(g, 2) if not np.isnan(g) else None
            gains.append(g)
            if not np.isnan(g) and g >= 3.0:
                part3 += 1
            if not np.isnan(g) and g >= 10.0:
                part10 += 1
        rec['cycles_ge3x'] = part3
        rec['cycles_ge10x'] = part10
        rec['n_cycles_obs'] = len(gains)
        rows.append(rec)

    df = pd.DataFrame(rows)
    # 有观测周期数的币
    df_obs = df[df['n_cycles_obs'] > 0].copy()
    never = df_obs[df_obs['cycles_ge3x'] == 0].sort_values('coin')
    once = df_obs[df_obs['cycles_ge3x'] == 1].sort_values('coin')
    twice = df_obs[df_obs['cycles_ge3x'] == 2].sort_values('coin')
    thrice = df_obs[df_obs['cycles_ge3x'] == 3].sort_values('coin')

    print("="*92)
    print(f"当前 50 币池 · 三轮减半周期'涨过没'体检  (数据 {px.index[0].date()}~{px.index[-1].date()})")
    print("  阈值: 窗口 peak/start >=3x = 算'涨过'; >=10x = 算'疯涨过'")
    print("="*92)
    print(f"\n【从没涨过 (0/观测周期 都 <3x) — 共 {len(never)} 币】")
    print(", ".join(never['coin'].tolist()) or "(无)")
    print(f"\n【只涨过 1 轮 — {len(once)} 币】")
    print(", ".join(once['coin'].tolist()) or "(无)")
    print(f"\n【涨过 2 轮 — {len(twice)} 币】")
    print(", ".join(twice['coin'].tolist()) or "(无)")
    print(f"\n【三轮都涨过 (真·周期选手) — {len(thrice)} 币】")
    print(", ".join(thrice['coin'].tolist()) or "(无)")

    # 本轮加的币表现
    print("\n--- 本轮加进来的币 ---")
    for c in ADDED:
        r = df[df['coin'] == c]
        if len(r):
            r = r.iloc[0]
            print(f"  {c}: C1={r['C1_2017']} C2={r['C2_2021']} C3={r['C3_2024']}  "
                  f"涨过{int(r['cycles_ge3x'])}/{int(r['n_cycles_obs'])}轮")

    # 本轮删的币(对照)
    print("\n--- 本轮删掉的币(历史对照) ---")
    for c in DELETED:
        r = df[df['coin'] == c]
        if len(r):
            r = r.iloc[0]
            print(f"  {c}: C1={r['C1_2017']} C2={r['C2_2021']} C3={r['C3_2024']}  "
                  f"涨过{int(r['cycles_ge3x'])}/{int(r['n_cycles_obs'])}轮")

    print("\n--- 每币明细 (coin / C1 / C2 / C3 / 涨过轮数) ---")
    show = df_obs.sort_values(['cycles_ge3x', 'coin'], ascending=[True, True])
    for _, r in show.iterrows():
        tag = ' +加' if r['added'] else (' -删' if r['deleted'] else '')
        print(f"  {r['coin']:<7} {str(r['C1_2017']):>7} {str(r['C2_2021']):>7} "
              f"{str(r['C3_2024']):>7}  涨过{int(r['cycles_ge3x'])}/{int(r['n_cycles_obs'])}{tag}")

    out = {'generated': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
           'pool': 'current 50 coins', 'threshold_ge3x': 3.0, 'threshold_ge10x': 10.0,
           'never_pumped': never['coin'].tolist(),
           'pumped_1': once['coin'].tolist(),
           'pumped_2': twice['coin'].tolist(),
           'pumped_3': thrice['coin'].tolist(),
           'detail': df_obs.to_dict(orient='records')}
    with open(os.path.join(HERE, 'bt_pool_cycle_participation.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n[done] 从没涨过 {len(never)}/{len(df_obs)} 币 | -> bt_pool_cycle_participation.json")


if __name__ == '__main__':
    main()
