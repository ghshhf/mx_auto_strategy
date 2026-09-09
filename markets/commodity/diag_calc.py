# -*- coding: utf-8 -*-
"""诊断: 月线 vs 季度 再平衡 差异是否真实 (MU/FCX/CAT/BA).
同时给出向量化正确实现, 供后续引擎复用。
"""
import pandas as pd, numpy as np
np.seterr(all='ignore')

px = pd.read_csv("data/us_universe_weekly_adjclose.csv", index_col=0, parse_dates=True)
px = px.apply(pd.to_numeric, errors='coerce').resample("ME").last()
px = px[(px.index >= "2005-01-31") & (px.index <= "2025-12-31")]
cols = ["MU","FCX","CAT","BA"]
cols = [c for c in cols if c in px.columns]
print("找到列:", cols)
p = px[cols].dropna(how='any')
print(f"范围 {p.index[0].date()} ~ {p.index[-1].date()}  行数 {len(p)}")

g = p.iloc[-1] / p.iloc[0]
print("\n各资产总涨幅(倍):", {c: round(v,2) for c,v in zip(cols, g.values)})
print("等权持有总倍数:", round(g.mean(),2))

# ---- 月线 ----
r_m = p.pct_change().dropna(how='any')
yrs_m = len(r_m)/12.0
reb_m = float(np.prod(1.0 + r_m.mean(axis=1).values))
hld_m = float(g.mean())
print(f"\n[月线] 期数={len(r_m)} yrs={yrs_m:.2f}")
print(f"  持有CAGR   = {hld_m**(1/yrs_m)-1:>8.2%}")
print(f"  再平衡CAGR = {reb_m**(1/yrs_m)-1:>8.2%}")
print(f"  超额       = {(reb_m**(1/yrs_m)-hld_m**(1/yrs_m))*100:>+7.2f}pp")

# ---- 季度 ----
pq = p.resample("QE").last().dropna(how='any')
r_q = pq.pct_change().dropna(how='any')
yrs_q = len(r_q)/4.0
reb_q = float(np.prod(1.0 + r_q.mean(axis=1).values))
g_q = pq.iloc[-1]/pq.iloc[0]
hld_q = float(g_q.mean())
print(f"\n[季度] 期数={len(r_q)} yrs={yrs_q:.2f}")
print(f"  持有CAGR   = {hld_q**(1/yrs_q)-1:>8.2%}")
print(f"  再平衡CAGR = {reb_q**(1/yrs_q)-1:>8.2%}")
print(f"  超额       = {(reb_q**(1/yrs_q)-hld_q**(1/yrs_q))*100:>+7.2f}pp")

print("\n--- 交叉校验: 季度持有倍数 %.2f vs 月线持有倍数 %.2f ---" % (hld_q, hld_m))
print("--- 再平衡总倍数: 月 %.2f  季 %.2f ---" % (reb_m, reb_q))
