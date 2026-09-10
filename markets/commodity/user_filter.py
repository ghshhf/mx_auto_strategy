# -*- coding: utf-8 -*-
"""用户口径筛选: 高波动 + 长期收益好 + 不是超级赢家 (排除EIA偶发跳变噪声 & TSLA级碾压).
对比: 污染池(含EIA噪声) vs 用户口径池。
"""
import pandas as pd, numpy as np
np.seterr(all='ignore')
W0, W1 = "2005-01-31", "2025-12-31"
FILES = [("us_universe_weekly_adjclose.csv","美股"),("hk_leaders_weekly_adjclose.csv","港股"),
         ("equities_weekly_adjclose.csv","个股"),("us_etf_weekly_adjclose.csv","ETF"),
         ("commodity_worldbank_monthly.csv","商品"),("gas_panel_monthly.csv","天然气"),
         ("eia_gas_monthly.csv","EIA"),("global_assets_monthly.csv","债汇指")]

def load_me(f):
    d = pd.read_csv(f, index_col=0, parse_dates=True).apply(pd.to_numeric, errors='coerce')
    d.columns = [c.lstrip('\ufeff') for c in d.columns]
    return d.resample("ME").last()

panels, kind = [], {}
for f, k in FILES:
    try:
        d = load_me(f"data/{f}")
        for c in d.columns: kind.setdefault(c, k)
        panels.append(d)
    except Exception: pass
allp = pd.concat(panels, axis=1).loc[:, ~pd.concat(panels, axis=1).columns.duplicated()]
allp = allp[(allp.index >= W0) & (allp.index <= W1)].dropna(how='all')

stat = {}
for c in allp.columns:
    s = allp[c].dropna()
    if len(s) < 150: continue
    if (s <= 0).any(): continue
    r = s.pct_change().dropna()
    if (r.abs() > 0.9).any(): continue
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1]/s.iloc[0])**(1/yrs) - 1
    vol = r.std()*np.sqrt(12)
    if np.isfinite(cagr) and np.isfinite(vol):
        stat[c] = (cagr*100, vol*100, kind.get(c,"?"))
df = pd.DataFrame(stat, index=["cagr","vol","kind"]).T
df[["cagr","vol"]] = df[["cagr","vol"]].astype(float)

# ---- 用户口径: 持续高波动 + 长期收益好 + 非超级赢家 ----
# 排除EIA噪声(偶发跳变, 长期收益≈0) + 排除TSLA/NFLX级碾压赢家
clean_hi = df[(df.kind != "EIA") & (df.vol >= 45) & (df.cagr >= 8) & (df.cagr <= 28)]
print("【用户口径池】高波动(vol≥45) + 长期收益好(8%≤CAGR≤28%) + 非超级赢家 + 排除EIA噪声")
print(f"  → {len(clean_hi)} 个标的")
print(clean_hi.sort_values("cagr", ascending=False).round(2).to_string())

def bt(cols, freq='M'):
    px = allp[list(cols)]
    if freq=='QE': px = px.resample('QE').last()
    px = px.dropna(how='any')
    if len(px) < 70: return None
    r = px.pct_change().dropna(how='any')
    yrs = len(r)/(4.0 if freq=='QE' else 12.0)
    if yrs < 8: return None
    reb = float(np.prod(1.0 + r.mean(axis=1).values))
    g = (px.iloc[-1]/px.iloc[0]).values
    if np.any(g <= 0): return None
    hld = float(g.mean())
    if not (np.isfinite(reb) and reb > 0 and hld > 0): return None
    rc = reb**(1/yrs)-1; hc = hld**(1/yrs)-1
    return hc*100, rc*100, (rc-hc)*100

def run(pool, name, n=6000, freq='M', top=6):
    pool = [c for c in pool if c in allp.columns]
    if len(pool) < 4:
        print(f"  {name:<30} 池太小({len(pool)})"); return
    rng = np.random.default_rng(13)
    res = []
    for _ in range(n):
        q = list(rng.choice(pool, 4, replace=False))
        m = bt(q, freq)
        if m: res.append((m[1], m[0], m[2], tuple(q)))
    if not res:
        print(f"  {name:<30} 无有效样本"); return
    res.sort(reverse=True)
    cg = np.array([x[0] for x in res]); ex = np.array([x[2] for x in res])
    print(f"  {name:<30} 池{len(pool):>3}  CAGR中位 {np.median(cg):>6.2f}%  超额中位 {np.median(ex):>+6.2f}pp  "
          f"≥20% {(cg>=20).mean()*100:>5.1f}%  ≥25% {(cg>=25).mean()*100:>5.1f}%")
    for rc, hc, e, q in res[:top]:
        print(f"       {rc:6.2f}%  持有{hc:6.2f}%  超额{e:+6.2f}pp   {','.join(q)}")

print("\n" + "="*100)
print("对比: 污染池 vs 用户口径池 (月线等权再平衡)")
print("="*100)
run(list(df[df.vol >= 45].index), "污染池 vol≥45(含EIA噪声)")
run(list(clean_hi.index), "用户口径池")

print("\n" + "="*100)
print("用户口径池: 季度再平衡")
print("="*100)
run(list(clean_hi.index), "用户口径池", freq='QE', top=6)

# 更严: 极高波动 vol≥50
strict = df[(df.kind != "EIA") & (df.vol >= 50) & (df.cagr >= 10) & (df.cagr <= 25)]
print(f"\n【更严口径】vol≥50 & 10%≤CAGR≤25% → {len(strict)} 个: {list(strict.index)}")
if len(strict) >= 4:
    run(list(strict.index), "更严池(月)", n=4000)
    run(list(strict.index), "更严池(季)", n=4000, freq='QE')
