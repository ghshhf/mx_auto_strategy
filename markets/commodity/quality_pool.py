# -*- coding: utf-8 -*-
"""为什么波动率提高但年化没动?
假设: 随机池混入大量"高波动但长期不涨"的垃圾股, 稀释了平均。
验证: 按 长期CAGR + 波动率 筛优质池, 再随机4元组搜索, 看年化是否跳到15-20%。
"""
import pandas as pd, numpy as np
np.seterr(all='ignore')
W0, W1 = "2005-01-31", "2025-12-31"

def load_me(f):
    d = pd.read_csv(f, index_col=0, parse_dates=True).apply(pd.to_numeric, errors='coerce')
    return d.resample("ME").last()      # 统一月末, 避免索引并集混乱

# 股票宇宙 = 美股 + 港股 + 个股面板 (补上之前漏掉的港股)
panels = [load_me(f"data/{f}") for f in
          ["us_universe_weekly_adjclose.csv", "hk_leaders_weekly_adjclose.csv",
           "equities_weekly_adjclose.csv"]]
allp = pd.concat(panels, axis=1)
allp = allp.loc[:, ~allp.columns.duplicated()]
allp = allp[(allp.index >= W0) & (allp.index <= W1)].dropna(how='all')
print(f"宇宙(美股+港股+个股): {allp.shape[1]} 列 x {allp.shape[0]} 月")

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
print(f"全样本 {len(df)} 只: 单股CAGR中位 {df.cagr.median():.2f}%   单股波动中位 {df.vol.median():.1f}%")

def bt(cols):
    px = allp[list(cols)].dropna(how='any')
    if len(px) < 70: return None
    r = px.pct_change().dropna(how='any')
    yrs = len(r)/12.0
    if yrs < 8: return None
    reb = float(np.prod(1.0 + r.mean(axis=1).values))
    g = (px.iloc[-1] / px.iloc[0]).values
    if np.any(g <= 0): return None
    hld = float(g.mean())
    if not (np.isfinite(reb) and reb > 0 and hld > 0): return None
    rc = reb ** (1/yrs) - 1; hc = hld ** (1/yrs) - 1
    return hc*100, rc*100, (rc-hc)*100

def search(pool, name, n=6000):
    if len(pool) < 4:
        print(f"  {name:<28} 池太小({len(pool)}), 跳过"); return
    rng = np.random.default_rng(5)
    res = []
    for _ in range(n):
        q = list(rng.choice(pool, 4, replace=False))
        m = bt(q)
        if m: res.append((m[1], m[0], m[2]))
    if not res:
        print(f"  {name:<28} 无有效样本"); return
    cg = np.array([x[0] for x in res]); ex = np.array([x[2] for x in res])
    print(f"  {name:<28} 池{len(pool):>4}只  CAGR中位 {np.median(cg):>6.2f}%  均值 {cg.mean():>6.2f}%  "
          f"超额中位 {np.median(ex):>+6.2f}pp  ≥15% {(cg>=15).mean()*100:>5.1f}%  ≥20% {(cg>=20).mean()*100:>5.1f}%")

pools = {
    "全池(随机基准)": list(df.index),
    "正收益 CAGR≥8%": list(df[df.cagr >= 8].index),
    "优质 CAGR≥12%": list(df[df.cagr >= 12].index),
    "优质+高波动 ≥12%&vol≥30": list(df[(df.cagr >= 12) & (df.vol >= 30)].index),
    "优质+超高波 ≥12%&vol≥40": list(df[(df.cagr >= 12) & (df.vol >= 40)].index),
    "仅超高波 vol≥40(不限收益)": list(df[df.vol >= 40].index),
}
print("\n" + "="*104)
print("池子质量 → 年化 (随机4元组, 月线等权再平衡, 2005-2025)")
print("="*104)
for nm, p in pools.items():
    search(p, nm)

print("\n--- 参考: 各池单股平均波动 ---")
for nm, p in pools.items():
    if len(p) >= 4:
        sub = df.loc[[x for x in p if x in df.index]]
        print(f"  {nm:<28} 单股CAGR中位 {sub.cagr.median():>6.2f}%  单股波动中位 {sub.vol.median():>5.1f}%")
