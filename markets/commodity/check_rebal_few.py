# -*- coding: utf-8 -*-
"""定点测几条跨资产组合 (用户: 几条测一下, 别搞1.5万次随机采样).
直接算每条确定性组合的 持有/再平衡/超额, 秒出。
口径: 月线 2005-01~2025-12, 稳健清洗。
"""
import pandas as pd, numpy as np
np.seterr(all='ignore')
WIN0, WIN1 = "2005-01-31", "2025-12-31"

def load(f):
    return pd.read_csv(f, index_col=0, parse_dates=True).apply(pd.to_numeric, errors='coerce')

stock = pd.concat([load(f"data/{x}") for x in
    ["us_universe_weekly_adjclose.csv","hk_leaders_weekly_adjclose.csv",
     "equities_weekly_adjclose.csv","us_etf_weekly_adjclose.csv"]], axis=1)
stock = stock.loc[:, ~stock.columns.duplicated()].resample("ME").last().dropna(how='all')
wb  = load("data/commodity_worldbank_monthly.csv")
gas = load("data/gas_panel_monthly.csv")
eia = load("data/eia_gas_monthly.csv")
comm = pd.concat([wb, gas, eia], axis=1); comm = comm.loc[:, ~comm.columns.duplicated()]
ga = load("data/global_assets_monthly.csv"); ga.columns=[c.lstrip('\ufeff') for c in ga.columns]
allp = pd.concat([stock, comm, ga], axis=1).loc[:, ~pd.concat([stock,comm,ga],axis=1).columns.duplicated()]
allp = allp[(allp.index >= WIN0) & (allp.index <= WIN1)]
allp = allp.apply(lambda s: s.interpolate(limit=3).ffill().bfill())
print(f"跨资产月线宇宙: {allp.shape[1]} 列 x {allp.shape[0]} 月")

stock_cols_all = set(stock.columns)
def clean(cols):
    good=[]
    for c in cols:
        if c not in allp: continue
        s=allp[c].dropna()
        if (s<=0).any(): continue
        r=s.pct_change().dropna()
        if (r.abs()>0.9).any(): continue
        good.append(c)
    return good

sc = clean([c for c in allp.columns if c in stock_cols_all])
comm_candidates = [c for c in allp.columns if c not in stock_cols_all]
metals = clean([c for c in comm_candidates if c in ("CU","AL","XAU","XAG","ZN","NI","PB","SN","FE_ORE","COAL_AUS","COAL_ZAF")])
oil    = clean([c for c in comm_candidates if c in ("OIL_BRENT","OIL_WTI","OIL_DUBAI","OIL_AVG")])
gas_c  = clean([c for c in comm_candidates if c in ("NG_US","NG_EU","LNG_JP","NG_INDEX")])
bond   = clean([c for c in allp.columns if c in ("TLT","IEF","BND","SHY","TIP")])
fx     = clean([c for c in allp.columns if c in ("DEXUSEU","DEXJPUS","DEXCHUS","DEXUSUK","DTWEXBGS")])
print(f"clean: 股票 {len(sc)} / 金属 {metals} / 油 {oil} / 气 {gas_c} / 债 {bond} / 汇 {fx}")

def metrics(cols, freq='M'):
    if any(c not in allp.columns for c in cols):
        return None
    px=allp[list(cols)]
    if freq=='QE': px=px.resample('QE').last()
    sub=px.dropna(how='any')
    minobs = 120 if freq=='M' else 40
    if len(sub)<minobs: return None
    r=sub.pct_change().dropna(how='any')
    minr = 110 if freq=='M' else 35
    if len(r)<minr: return None
    yrs=len(r)/(12.0 if freq=='M' else 4.0)
    val=1.0
    for _,row in r.iterrows():
        rr=np.clip(row.values,-0.95,None)
        if np.any(1+rr<=0): return None
        val*=(1.0+rr.mean())
    if not np.isfinite(val) or val<=0: return None
    reb_c=val**(1/yrs)-1
    g=(sub.iloc[-1]/sub.iloc[0]).values
    if np.any(g<=0): return None
    hld_c=(g.mean())**(1/yrs)-1
    if not(np.isfinite(reb_c) and np.isfinite(hld_c)): return None
    return hld_c*100, reb_c*100, (reb_c-hld_c)*100

# 确定性标的: 高波动周期股(MU美光/FCX自由港) + 黄金/铜(真分散金属, 剔除煤炭) + 油/气 + 债/汇
pools = {
 "纯股票周期(MU/FCX/CAT/BA)": ["MU","FCX","CAT","BA"],
 "2股+1金属+1油(MU/FCX+XAU+OIL_BRENT)": ["MU","FCX","XAU","OIL_BRENT"],
 "2股+1金属+1气(MU/FCX+XAU+NG_US)": ["MU","FCX","XAU","NG_US"],
 "2股+1金属+1债(MU/FCX+XAU+TLT)": ["MU","FCX","XAU","TLT"],
 "2股+1金属+1汇(MU/FCX+XAU+DEXUSEU)": ["MU","FCX","XAU","DEXUSEU"],
 "2股+1油+1气(MU/FCX+OIL_BRENT+NG_US)": ["MU","FCX","OIL_BRENT","NG_US"],
 "1股+1金属+1油+1气(MU+XAU+OIL_BRENT+NG_US)": ["MU","XAU","OIL_BRENT","NG_US"],
 "纯商品(黄金+铜+油+气)": ["XAU","CU","OIL_BRENT","NG_US"],
}
print(f"\n{'组合':<18}{'标的':<40}{'持有%':>7} | {'月再平衡%':>9}{'月超额':>8} | {'季再平衡%':>9}{'季超额':>8}")
print("-"*100)
rows=[]
for name,cols in pools.items():
    m=metrics(cols,'M'); q=metrics(cols,'QE'); tag=",".join(cols)
    h = (m[0] if m else (q[0] if q else float('nan')))
    ms = f"{m[1]:.2f}%/{m[2]:+.2f}" if m else "  -  /  -  "
    qs = f"{q[1]:.2f}%/{q[2]:+.2f}" if q else "  -  /  -  "
    print(f"{name:<18}{tag:<40}{h:>6.1f}% | {ms:>18} | {qs:>18}")
    if m or q:
        rows.append(dict(组合=name, 标的=tag, 持有=h,
                         月再平衡=(m[1] if m else None), 月超额=(m[2] if m else None),
                         季再平衡=(q[1] if q else None), 季超额=(q[2] if q else None)))
pd.DataFrame(rows).to_csv("data/rebal_few_result.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/rebal_few_result.csv")
