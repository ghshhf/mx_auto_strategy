# -*- coding: utf-8 -*-
"""全资产分析 (用户真正框架: 全资产互相平衡, 不是单一市场).
宇宙 = 美股+港股+个股+ETF+商品(WB)+天然气+EIA+全球资产(债/汇/股指), 统一月线。
按单资产波动率分档 (不用过去收益筛选), 随机4元组回测长期年化。
"""
import pandas as pd, numpy as np
np.seterr(all='ignore')
W0, W1 = "2005-01-31", "2025-12-31"

FILES = [
    ("us_universe_weekly_adjclose.csv", "美股"),
    ("hk_leaders_weekly_adjclose.csv", "港股"),
    ("equities_weekly_adjclose.csv", "个股"),
    ("us_etf_weekly_adjclose.csv", "ETF"),
    ("commodity_worldbank_monthly.csv", "商品"),
    ("gas_panel_monthly.csv", "天然气"),
    ("eia_gas_monthly.csv", "EIA"),
    ("global_assets_monthly.csv", "债汇指"),
]

def load_me(f):
    d = pd.read_csv(f, index_col=0, parse_dates=True).apply(pd.to_numeric, errors='coerce')
    d.columns = [c.lstrip('\ufeff') for c in d.columns]
    return d.resample("ME").last()      # 关键: 统一月末, 避免索引并集混乱

panels, kind = [], {}
for f, k in FILES:
    try:
        d = load_me(f"data/{f}")
        for c in d.columns:
            kind.setdefault(c, k)
        panels.append(d)
        print(f"  {k:<6} {f:<40} {d.shape[1]:>4} 列")
    except Exception as e:
        print(f"  SKIP {f}: {e}")

allp = pd.concat(panels, axis=1)
allp = allp.loc[:, ~allp.columns.duplicated()]
allp = allp[(allp.index >= W0) & (allp.index <= W1)].dropna(how='all')
print(f"\n全资产宇宙: {allp.shape[1]} 列 x {allp.shape[0]} 月  [{allp.index[0].date()} ~ {allp.index[-1].date()}]")

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
        stat[c] = (cagr*100, vol*100, kind.get(c, "?"))
df = pd.DataFrame(stat, index=["cagr", "vol", "kind"]).T
df[["cagr", "vol"]] = df[["cagr", "vol"]].astype(float)
print(f"合格标的 {len(df)} 个 | 单资产CAGR中位 {df.cagr.median():.2f}% | 波动中位 {df.vol.median():.1f}%")
print("\n各类别波动概况:")
print(df.groupby("kind").agg(数量=("vol", "size"), 波动中位=("vol", "median"),
                            CAGR中位=("cagr", "median")).round(2).to_string())

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

def run(pool, name, n=6000, freq='M', top=0):
    pool = [c for c in pool if c in allp.columns]
    if len(pool) < 4:
        print(f"  {name:<28} 池太小({len(pool)})"); return
    rng = np.random.default_rng(9)
    res = []
    for _ in range(n):
        q = list(rng.choice(pool, 4, replace=False))
        m = bt(q, freq)
        if m: res.append((m[1], m[0], m[2], tuple(q)))
    if not res:
        print(f"  {name:<28} 无有效样本"); return
    res.sort(reverse=True)
    cg = np.array([x[0] for x in res]); ex = np.array([x[2] for x in res])
    print(f"  {name:<28} 池{len(pool):>4}  CAGR中位 {np.median(cg):>6.2f}%  超额中位 {np.median(ex):>+6.2f}pp  "
          f"≥15% {(cg>=15).mean()*100:>5.1f}%  ≥20% {(cg>=20).mean()*100:>5.1f}%")
    for rc, hc, e, q in res[:top]:
        print(f"       {rc:6.2f}%  持有{hc:6.2f}%  超额{e:+6.2f}pp   {','.join(q)}")

print("\n" + "="*104)
print("全资产: 按单资产波动率分档 (月线等权再平衡, 2005-2025)")
print("="*104)
run(list(df.index), "全资产池")
run(list(df[df.vol >= 30].index), "波动≥30%")
run(list(df[df.vol >= 40].index), "波动≥40%", top=6)
run(list(df[df.vol >= 50].index), "波动≥50%(极高)", top=6)

print("\n" + "="*104)
print("全资产: 季度再平衡 (对照)")
print("="*104)
run(list(df.index), "全资产池", freq='QE')
run(list(df[df.vol >= 40].index), "波动≥40%", freq='QE')
run(list(df[df.vol >= 50].index), "波动≥50%(极高)", freq='QE')

print("\n--- 波动≥50% 的标的池(用户口径: 高波动好标的) ---")
hi = df[df.vol >= 50].sort_values("cagr", ascending=False)
print(hi.round(2).to_string())
