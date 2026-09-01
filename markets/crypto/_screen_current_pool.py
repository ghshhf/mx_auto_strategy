# -*- coding: utf-8 -*-
"""对当前 v3 面板(40币)重算三轮减半周期参与度，按档分组输出可扫读筛选视图。"""
import os, sys, json
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
V3 = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50_v3.csv')

# 防御核(README V2 设计): BTC/ETH/OKB；其余为进攻。(SKY 已于 2026-08-31 移除)
DEFENSIVE = {'BTC', 'ETH', 'OKB'}

CYCLES = [('C1_2017', '2016-08-11', '2020-05-11'),
          ('C2_2021', '2020-05-11', '2024-04-19'),
          ('C3_2024', '2024-04-19', '2026-08-07')]

def main():
    px = pd.read_csv(V3, index_col=0, parse_dates=True).sort_index()
    cols = [c for c in px.columns if c != 'date']
    rows = []
    for c in cols:
        ser = px[c].dropna()
        if len(ser) < 5:
            continue
        rec = {'coin': c, 'def': '防御' if c in DEFENSIVE else '进攻'}
        part3 = part10 = 0; gains = []
        for name, s, e in CYCLES:
            w = ser[(ser.index >= pd.Timestamp(s)) & (ser.index <= pd.Timestamp(e))]
            if len(w) < 3:
                rec[name] = None; continue
            start = float(w.iloc[0]); peak = float(w.max())
            g = peak / start if start > 0 else np.nan
            rec[name] = round(g, 2) if not np.isnan(g) else None
            gains.append(g)
            if not np.isnan(g) and g >= 3.0: part3 += 1
            if not np.isnan(g) and g >= 10.0: part10 += 1
        rec['ge3x'] = part3; rec['ge10x'] = part10; rec['nobs'] = len(gains)
        rows.append(rec)
    df = pd.DataFrame(rows)
    obs = df[df['nobs'] > 0].copy()
    never = obs[obs['ge3x'] == 0].sort_values('coin')
    once = obs[obs['ge3x'] == 1].sort_values('coin')
    twice = obs[obs['ge3x'] == 2].sort_values('coin')
    thrice = obs[obs['ge3x'] == 3].sort_values('coin')

    print("="*100)
    print(f"当前 v3 面板({len(cols)}币) · 三轮减半周期'涨过没'体检  (窗口 {px.index[0].date()}~{px.index[-1].date()})")
    print("  阈值: 窗口 peak/start >=3x=涨过; >=10x=疯涨过。C1=2017/C2=2021/C3=2024")
    print("="*100)
    def line(r):
        d = '防' if r['def']=='防御' else '攻'
        c1 = r['C1_2017']; c2 = r['C2_2021']; c3 = r['C3_2024']
        def f(x): return f"{x:.2f}x" if isinstance(x,(int,float)) else "—"
        return f"  {r['coin']:<6}[{d}] {f(c1):>8} {f(c2):>8} {f(c3):>8}  涨{int(r['ge3x'])}/{int(r['nobs'])}轮"
    print(f"\n【三轮都涨过 真·周期选手 — {len(thrice)}】")
    for _,r in thrice.iterrows(): print(line(r))
    print(f"\n【涨过 2 轮 — {len(twice)}】")
    for _,r in twice.iterrows(): print(line(r))
    print(f"\n【只涨过 1 轮 — {len(once)}】")
    for _,r in once.iterrows(): print(line(r))
    print(f"\n【从没涨过(0轮<3x) — {len(never)}】  ← 其中观测>=2轮=结构性弱币,太新(1轮)留观")
    for _,r in never.iterrows():
        note = " [太新留观]" if r['nobs']<=1 else " [弱币]"
        print(line(r)+note)
    print(f"\n总计: {len(obs)}币有观测 | 涨过>=1轮 {len(obs)-len(never)} | 从没涨过 {len(never)}")
    out = {'generated':'2026-08-17','panel':'v3(40)','never':never['coin'].tolist(),
           'once':once['coin'].tolist(),'twice':twice['coin'].tolist(),
           'thrice':thrice['coin'].tolist(),'detail':obs.to_dict(orient='records')}
    with open(os.path.join(HERE,'_screen_current_pool.json'),'w',encoding='utf-8') as f:
        json.dump(out,f,ensure_ascii=False,indent=2)
    print("[done] -> _screen_current_pool.json")

if __name__ == '__main__':
    main()
