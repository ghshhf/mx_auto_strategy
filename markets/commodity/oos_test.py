# -*- coding: utf-8 -*-
"""样本外测试 (Out-of-Sample): 揭示前视偏差。
问题: 用全窗口CAGR筛"优质池"得25.97% 是用未来数据选股, 实盘不可得。
做法: 训练期 2005-2015 筛池 → 样本外 2016-2025 回测, 看真实可得年化。
"""
import pandas as pd, numpy as np
np.seterr(all='ignore')
TR0, TR1 = "2005-01-31", "2015-12-31"   # 训练/选股期
TE0, TE1 = "2016-01-31", "2025-12-31"   # 样本外验证期

def load_me(f):
    d = pd.read_csv(f, index_col=0, parse_dates=True).apply(pd.to_numeric, errors='coerce')
    return d.resample("ME").last()

panels = [load_me(f"data/{f}") for f in
          ["us_universe_weekly_adjclose.csv", "hk_leaders_weekly_adjclose.csv",
           "equities_weekly_adjclose.csv"]]
allp = pd.concat(panels, axis=1)
allp = allp.loc[:, ~allp.columns.duplicated()]
print(f"宇宙: {allp.shape[1]} 列 x {allp.shape[0]} 月")

train = allp[(allp.index >= TR0) & (allp.index <= TR1)].dropna(how='all')
test  = allp[(allp.index >= TE0) & (allp.index <= TE1)].dropna(how='all')
print(f"训练期 {train.index[0].date()}~{train.index[-1].date()} ({len(train)}月) | "
      f"样本外 {test.index[0].date()}~{test.index[-1].date()} ({len(test)}月)")

# ---- 只用训练期数据算指标(模拟"当时能看到的") ----
stat = {}
for c in allp.columns:
    s = train[c].dropna()
    if len(s) < 100: continue
    if (s <= 0).any(): continue
    r = s.pct_change().dropna()
    if (r.abs() > 0.9).any(): continue
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1/yrs) - 1
    vol = r.std() * np.sqrt(12)
    if np.isfinite(cagr) and np.isfinite(vol):
        stat[c] = (cagr*100, vol*100)
df = pd.DataFrame(stat, index=["cagr", "vol"]).T
print(f"训练期可评估标的: {len(df)}  (单股CAGR中位 {df.cagr.median():.2f}%, 波动中位 {df.vol.median():.1f}%)")

def bt(cols, px):
    p = px[list(cols)].dropna(how='any')
    if len(p) < 60: return None
    r = p.pct_change().dropna(how='any')
    yrs = len(r)/12.0
    if yrs < 5: return None
    reb = float(np.prod(1.0 + r.mean(axis=1).values))
    g = (p.iloc[-1] / p.iloc[0]).values
    if np.any(g <= 0): return None
    hld = float(g.mean())
    if not (np.isfinite(reb) and reb > 0 and hld > 0): return None
    rc = reb ** (1/yrs) - 1; hc = hld ** (1/yrs) - 1
    return hc*100, rc*100, (rc-hc)*100

def run(pool, name, n=6000, px=None):
    px = test if px is None else px
    pool = [c for c in pool if c in px.columns]
    if len(pool) < 4:
        print(f"  {name:<30} 池太小({len(pool)})"); return
    rng = np.random.default_rng(11)
    res = []
    for _ in range(n):
        q = list(rng.choice(pool, 4, replace=False))
        m = bt(q, px)
        if m: res.append((m[1], m[0], m[2]))
    if not res:
        print(f"  {name:<30} 无有效样本"); return
    cg = np.array([x[0] for x in res]); ex = np.array([x[2] for x in res])
    print(f"  {name:<30} 池{len(pool):>4}  CAGR中位 {np.median(cg):>6.2f}%  超额中位 {np.median(ex):>+6.2f}pp  "
          f"≥15% {(cg>=15).mean()*100:>5.1f}%  ≥20% {(cg>=20).mean()*100:>5.1f}%")

pools = {
    "全池(不选股)": list(df.index),
    "训练期CAGR≥8%": list(df[df.cagr >= 8].index),
    "训练期CAGR≥12%": list(df[df.cagr >= 12].index),
    "训练期≥12%&vol≥30": list(df[(df.cagr >= 12) & (df.vol >= 30)].index),
    "训练期≥12%&vol≥40": list(df[(df.cagr >= 12) & (df.vol >= 40)].index),
    "训练期vol≥40(不限收益)": list(df[df.vol >= 40].index),
}
print("\n" + "="*104)
print("【样本外验证】2016-2025 (池子用 2005-2015 数据筛选, 无前视偏差)")
print("="*104)
for nm, p in pools.items():
    run(p, nm)

print("\n" + "="*104)
print("【对照】同期 2016-2025 但用全窗口(含未来)筛选 = 前视偏差版")
print("="*104)
stat2 = {}
for c in allp.columns:
    s = allp[c].dropna()
    if len(s) < 150: continue
    if (s <= 0).any(): continue
    r = s.pct_change().dropna()
    if (r.abs() > 0.9).any(): continue
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    stat2[c] = (((s.iloc[-1]/s.iloc[0])**(1/yrs)-1)*100, r.std()*np.sqrt(12)*100)
d2 = pd.DataFrame(stat2, index=["cagr","vol"]).T
pools2 = {
    "全窗口CAGR≥12%&vol≥40": list(d2[(d2.cagr >= 12) & (d2.vol >= 40)].index),
    "全窗口CAGR≥12%": list(d2[d2.cagr >= 12].index),
}
for nm, p in pools2.items():
    run(p, nm)
