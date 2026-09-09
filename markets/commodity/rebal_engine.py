# -*- coding: utf-8 -*-
"""干净再平衡引擎 v2 (修索引bug + 向量化 + 波动率分档).
用户定量假设: 高波动~20% / 中等波动~15% / 低波动~10% (再平衡CAGR年化)
本脚本: 随机搜索股票4元组, 按池内波动率分三档, 验证各档CAGR与超额。
"""
import pandas as pd, numpy as np
np.seterr(all='ignore')
W0, W1 = "2005-01-31", "2025-12-31"

def load_me(f):
    df = pd.read_csv(f, index_col=0, parse_dates=True).apply(pd.to_numeric, errors='coerce')
    return df.resample("ME").last()

us = load_me("data/us_universe_weekly_adjclose.csv")
allp = us[(us.index >= W0) & (us.index <= W1)].dropna(how='all')
print(f"美股宇宙(月线): {allp.shape[1]} 列 x {allp.shape[0]} 月  [{allp.index[0].date()} ~ {allp.index[-1].date()}]")

def clean(cols):
    good = []
    for c in cols:
        s = allp[c].dropna()
        if len(s) < 150: continue
        if (s <= 0).any(): continue
        r = s.pct_change().dropna()
        if (r.abs() > 0.9).any(): continue
        good.append(c)
    return good

sc = clean(allp.columns)
print(f"清洗后候选: {len(sc)}")

def bt(cols, freq='M'):
    px = allp[list(cols)]
    if freq == 'QE': px = px.resample('QE').last()
    px = px.dropna(how='any')
    if len(px) < 70: return None
    r = px.pct_change().dropna(how='any')
    n = len(r); per = 4.0 if freq == 'QE' else 12.0
    yrs = n / per
    if yrs < 8: return None
    reb = float(np.prod(1.0 + r.mean(axis=1).values))
    g = (px.iloc[-1] / px.iloc[0]).values
    if np.any(g <= 0): return None
    hld = float(g.mean())
    if not (np.isfinite(reb) and reb > 0 and np.isfinite(hld) and hld > 0): return None
    rc = reb ** (1/yrs) - 1; hc = hld ** (1/yrs) - 1
    vol = float(r.std().mean() * np.sqrt(12 if freq == 'M' else 4) * 100)
    return hc*100, rc*100, (rc-hc)*100, vol

# ---- 定向: 半导体 / 周期资源 ----
semis = [t for t in ["NVDA","AMD","MU","INTC","QCOM","AVGO","TXN","LRCX","AMAT","KLAC","ASX","UMC","TSM","MRVL","NXPI","SWKS","TER","WDC","STX","ENTG"] if t in sc]
cycl  = [t for t in ["FCX","X","AA","CLF","NEM","GOLD","MOS","CF","CAT","DE","BA","HON","LMT","RTX","EMR","DOW","DD","PPG","EQT","MRO","DVN","APA","OXY","HAL","SLB","BKR","VLO","PSX","MPC"] if t in sc]
print(f"\n半导体候选({len(semis)}): {semis}")
print(f"周期资源候选({len(cycl)}): {cycl}")

print("\n" + "="*90)
print("定向组合 (月线 / 季度)")
print("="*90)
dire = {}
if len(semis) >= 4: dire["纯半导体4"] = semis[:4]
if len(semis) >= 6: dire["半导体(去龙头)"] = semis[2:6]
if len(cycl) >= 4: dire["纯周期资源4"] = cycl[:4]
if len(semis) >= 2 and len(cycl) >= 2: dire["2半导体+2周期"] = semis[2:4] + cycl[:2]
if len(semis) >= 4: dire["半导体(尾部4)"] = semis[-4:]
for name, q in dire.items():
    m = bt(q, 'M'); qq = bt(q, 'QE')
    if m:  print(f"  {name:<16} 月 持有{m[0]:6.2f}% 再平衡{m[1]:6.2f}% 超额{m[2]:+6.2f}pp 波动{m[3]:5.1f}%  {','.join(q)}")
    if qq: print(f"  {'':<16} 季 持有{qq[0]:6.2f}% 再平衡{qq[1]:6.2f}% 超额{qq[2]:+6.2f}pp 波动{qq[3]:5.1f}%")

# ---- 随机搜索 + 波动率分档 ----
rng = np.random.default_rng(3)
res = []
for _ in range(8000):
    q = list(rng.choice(sc, 4, replace=False))
    m = bt(q, 'M')
    if m: res.append((m[1], m[0], m[2], m[3], tuple(q)))
res.sort(reverse=True)
cg = np.array([x[0] for x in res]); ex = np.array([x[2] for x in res]); vo = np.array([x[3] for x in res])
print("\n" + "="*90)
print(f"随机搜索 {len(res)} 组 (股票4元组, 2005-2025, 月线等权再平衡)")
print("="*90)
print(f"  再平衡CAGR: 中位 {np.median(cg):.2f}%   超额: 中位 {np.median(ex):+.2f}pp (正占比 {(ex>0).mean()*100:.1f}%)")

q33, q67 = np.percentile(vo, 33), np.percentile(vo, 67)
lo, md, hi = vo <= q33, (vo > q33) & (vo <= q67), vo > q67
print(f"\n  按池内波动率分档 (验证 高20% / 中15% / 低10%):")
print(f"  {'档位':<8}{'波动均值':>9}{'CAGR中位':>10}{'CAGR均值':>10}{'超额中位':>10}{'>=15%':>8}{'>=20%':>8}")
for nm, msk in [("低波动", lo), ("中波动", md), ("高波动", hi)]:
    print(f"  {nm:<8}{vo[msk].mean():>8.1f}%{np.median(cg[msk]):>9.2f}%{cg[msk].mean():>9.2f}%"
          f"{np.median(ex[msk]):>+9.2f}pp{(cg[msk]>=15).mean()*100:>7.1f}%{(cg[msk]>=20).mean()*100:>7.1f}%")

print(f"\n  Top10 按再平衡CAGR:")
for rc, hc, e, v, q in res[:10]:
    print(f"    {rc:6.2f}%  持有{hc:6.2f}%  超额{e:+6.2f}pp  波动{v:5.1f}%   {','.join(q)}")

pos = [x for x in res if x[2] > 0]
print(f"\n  超额>0 中 CAGR 最高 Top8 (再平衡真贡献):")
for rc, hc, e, v, q in pos[:8]:
    print(f"    {rc:6.2f}%  持有{hc:6.2f}%  超额{e:+6.2f}pp  波动{v:5.1f}%   {','.join(q)}")
