# -*- coding: utf-8 -*-
"""港股专属分析 (用户: 中国人投资以港股为主, 别拿美股逻辑套; 也别用过去收益筛未来).
做法: 只用港股龙头池(hk_leaders + equities), 按"高波动"筛(不用过去CAGR筛), 回测长期年化。
"""
import pandas as pd, numpy as np
np.seterr(all='ignore')
W0, W1 = "2005-01-31", "2025-12-31"

def load_me(f):
    d = pd.read_csv(f, index_col=0, parse_dates=True).apply(pd.to_numeric, errors='coerce')
    return d.resample("ME").last()

hk = load_me("data/hk_leaders_weekly_adjclose.csv")
eq = load_me("data/equities_weekly_adjclose.csv")
both = pd.concat([hk, eq], axis=1)
allp = both.loc[:, ~both.columns.duplicated()]
allp = allp[(allp.index >= W0) & (allp.index <= W1)].dropna(how='all')
print(f"港股宇宙: {allp.shape[1]} 列 x {allp.shape[0]} 月  [{allp.index[0].date()} ~ {allp.index[-1].date()}]")

stat = {}
for c in allp.columns:
    s = allp[c].dropna()
    if len(s) < 150: continue
    if (s <= 0).any(): continue
    r = s.pct_change().dropna()
    if (r.abs() > 0.9).any(): continue
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1/yrs) - 1
    vol = r.std() * np.sqrt(12)
    if np.isfinite(cagr) and np.isfinite(vol):
        stat[c] = (cagr*100, vol*100)
df = pd.DataFrame(stat, index=["cagr", "vol"]).T
print(f"合格港股 {len(df)} 只 | 单股CAGR中位 {df.cagr.median():.2f}% | 单股波动中位 {df.vol.median():.1f}%")

def bt(cols, freq='M'):
    px = allp[list(cols)]
    if freq == 'QE': px = px.resample('QE').last()
    px = px.dropna(how='any')
    if len(px) < 70: return None
    r = px.pct_change().dropna(how='any')
    yrs = len(r) / (4.0 if freq == 'QE' else 12.0)
    if yrs < 8: return None
    reb = float(np.prod(1.0 + r.mean(axis=1).values))
    g = (px.iloc[-1] / px.iloc[0]).values
    if np.any(g <= 0): return None
    hld = float(g.mean())
    if not (np.isfinite(reb) and reb > 0 and hld > 0): return None
    rc = reb ** (1/yrs) - 1; hc = hld ** (1/yrs) - 1
    return hc*100, rc*100, (rc-hc)*100

def run(pool, name, n=6000, freq='M', show_top=0):
    pool = [c for c in pool if c in allp.columns]
    if len(pool) < 4:
        print(f"  {name:<26} 池太小({len(pool)})"); return None
    rng = np.random.default_rng(7)
    res = []
    for _ in range(n):
        q = list(rng.choice(pool, 4, replace=False))
        m = bt(q, freq)
        if m: res.append((m[1], m[0], m[2], tuple(q)))
    if not res:
        print(f"  {name:<26} 无有效样本"); return None
    res.sort(reverse=True)
    cg = np.array([x[0] for x in res]); ex = np.array([x[2] for x in res])
    print(f"  {name:<26} 池{len(pool):>3}只  CAGR中位 {np.median(cg):>6.2f}%  超额中位 {np.median(ex):>+6.2f}pp  "
          f"≥20% {(cg>=20).mean()*100:>5.1f}%  ≥30% {(cg>=30).mean()*100:>5.1f}%")
    for rc, hc, e, q in res[:show_top]:
        print(f"      → {rc:6.2f}%  持有{hc:6.2f}%  超额{e:+6.2f}pp   {','.join(q)}")
    return res

print("\n" + "="*100)
print("港股: 按波动率分档 (不用过去收益筛, 月线等权再平衡, 2005-2025)")
print("="*100)
run(list(df.index), "全港股池")
run(list(df[df.vol >= 30].index), "高波动 vol≥30")
run(list(df[df.vol >= 40].index), "超高波动 vol≥40", show_top=5)
run(list(df[(df.vol >= 30) & (df.cagr >= 10)].index), "高波动+长期收益好(对照)")

print("\n" + "="*100)
print("港股: 季度再平衡 (对照月线)")
print("="*100)
run(list(df.index), "全港股池", freq='QE')
run(list(df[df.vol >= 40].index), "超高波动 vol≥40", freq='QE')

# 定向: 港股科技/半导体/新经济龙头
tech = [t for t in ["0700_HK","0981_HK","1810_HK","3690_HK","1211_HK","2382_HK",
                    "0992_HK","0762_HK","0388_HK","0268_HK","1024_HK","9618_HK"] if t in df.index]
print(f"\n港股科技/半导体龙头候选({len(tech)}): {tech}")
if len(tech) >= 4:
    m = bt(tech[:4], 'M'); q = bt(tech[:4], 'QE')
    if m: print(f"  定向科技4(月): 持有{m[0]:6.2f}% 再平衡{m[1]:6.2f}% 超额{m[2]:+6.2f}pp  {tech[:4]}")
    if q: print(f"  定向科技4(季): 持有{q[0]:6.2f}% 再平衡{q[1]:6.2f}% 超额{q[2]:+6.2f}pp")
if len(tech) >= 6:
    m = bt(tech[:6], 'M')
    if m: print(f"  定向科技6(月): 持有{m[0]:6.2f}% 再平衡{m[1]:6.2f}% 超额{m[2]:+6.2f}pp  {tech[:6]}")

print("\n--- 港股波动前10 (可复核是否龙头) ---")
print(df.sort_values("vol", ascending=False).head(10).round(2).to_string())
