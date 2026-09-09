# -*- coding: utf-8 -*-
"""全资产平衡 = 跨资产类的各种组合 (用户根本逻辑).
对照:
  A) 纯股票 / 纯商品+气体 / 混编(随机4)
  B) 用户结构: 2股票 + 1商品 + 1油(或债券/汇率/气体替补)
口径: 月线 2005~2025, 稳健清洗(剔除<=0价格 / |月收益|>0.9), 组合净值模拟.
核心: 取"平均数"(中位数/胜率), 不 cherry-pick 极端赢家(PLUG).
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
comm = pd.concat([wb, gas, eia], axis=1)
comm = comm.loc[:, ~comm.columns.duplicated()]
ga = load("data/global_assets_monthly.csv"); ga.columns = [c.lstrip('\ufeff') for c in ga.columns]
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
# 细分商品类
comm_candidates = [c for c in allp.columns if c not in stock_cols_all]
metals = clean([c for c in comm_candidates if c in ("CU","AL","XAU","XAG","ZN","NI","PB","SN","FE_ORE","COAL_AUS","COAL_ZAF")])
oil    = clean([c for c in comm_candidates if c in ("OIL_BRENT","OIL_WTI","OIL_DUBAI","OIL_AVG")])
gas_c  = clean([c for c in comm_candidates if c in ("NG_US","NG_EU","LNG_JP","NG_INDEX")])
bond   = clean([c for c in allp.columns if c in ("TLT","IEF","BND","SHY","TIP")])
fx     = clean([c for c in allp.columns if c in ("DEXUSEU","DEXJPUS","DEXCHUS","DEXUSUK","DTWEXBGS")])
print(f"清洗后: 股票 {len(sc)} / 金属 {len(metals)} / 油 {len(oil)} / 气 {len(gas_c)} / 债 {len(bond)} / 汇 {len(fx)}")

def metrics(cols):
    try:
        sub=allp[cols].dropna(how='any')
        if len(sub)<120: return None
        r=sub.pct_change().dropna(how='any')
        if len(r)<110: return None
        yrs=len(r)/12.0
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
    except Exception:
        return None

rng=np.random.default_rng(11)
def test(name, pool_fn, n=15000):
    ex=[]; hc=[]; rc=[]
    for _ in range(n):
        q=pool_fn()
        if q is None: continue
        m=metrics(list(q))
        if m is not None:
            hc.append(m[0]); rc.append(m[1]); ex.append(m[2])
    ex=np.array(ex); hc=np.array(hc); rc=np.array(rc)
    if len(ex)==0:
        print(f"  {name:<30} 无有效样本"); return None
    print(f"  {name:<30} 有效 {len(ex):>5} | 持有中位 {np.median(hc):>6.2f}% | 再平衡中位 {np.median(rc):>6.2f}% | 超额中位 {np.median(ex):>+7.2f}pp | 跑赢 {(ex>0).mean():.1%} | 负占 {(ex<0).mean():.1%}")
    return dict(name=name, n=len(ex), hold_med=float(np.median(hc)), reb_med=float(np.median(rc)),
                excess_med=float(np.median(ex)), win=float((ex>0).mean()), neg=float((ex<0).mean()))

rows=[]
print("\n"+"="*78); print("A) 三组对照 (随机4, 取平均数)"); print("="*78)
rows.append(test("纯股票", lambda: rng.choice(sc,4,replace=False)))
rows.append(test("纯商品+气体", lambda: rng.choice(clean(comm_candidates),4,replace=False)))
rows.append(test("混编(股+商品随机4)", lambda: rng.choice(sc+clean(comm_candidates),4,replace=False)))

print("\n"+"="*78); print("B) 用户结构: 2股票 + 1商品 + 1油/替补"); print("="*78)
rows.append(test("2股+1金属+1油", lambda: tuple(rng.choice(sc,2,replace=False))+(rng.choice(metals),rng.choice(oil))))
rows.append(test("2股+1金属+1气", lambda: tuple(rng.choice(sc,2,replace=False))+(rng.choice(metals),rng.choice(gas_c))))
rows.append(test("2股+1金属+1债", lambda: tuple(rng.choice(sc,2,replace=False))+(rng.choice(metals),rng.choice(bond))))
rows.append(test("2股+1金属+1汇", lambda: tuple(rng.choice(sc,2,replace=False))+(rng.choice(metals),rng.choice(fx))))
rows.append(test("2股+1油+1气", lambda: tuple(rng.choice(sc,2,replace=False))+(rng.choice(oil),rng.choice(gas_c))))
rows.append(test("1股+1金属+1油+1气", lambda: (rng.choice(sc),rng.choice(metals),rng.choice(oil),rng.choice(gas_c))))

rows=[r for r in rows if r]
pd.DataFrame(rows).to_csv("data/rebal_combo_result.csv", index=False)
print("\n已存 data/rebal_combo_result.csv")
