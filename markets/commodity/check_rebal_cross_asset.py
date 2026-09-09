# -*- coding: utf-8 -*-
"""跨资产 4 配对 (稳健版): '4个里不必须全是股票, 天然气/商品都可以'
修正点:
  1. 统一用月线 (股票月末重采样, 商品本就月线) -> 消除 ffill 假摔 -100% 周
  2. 严格过滤 非正价格 / |月收益|>0.9 -> 剔除破产/脏数据标的
  3. 用组合净值模拟算再平衡, 避免 (1+r)<=0 时 prod 溢出
窗口 2005~2025, 对比 纯股票 / 纯商品+气体 / 混编(股票+商品随机4)
"""
import pandas as pd, numpy as np
np.seterr(all='ignore')   # 抑制底层 umr_prod 噪声

WIN0, WIN1 = "2005-01-31", "2025-12-31"

def load(f):
    return pd.read_csv(f, index_col=0, parse_dates=True).apply(pd.to_numeric, errors='coerce')

# ---- 股票面板 (周线 -> 月末) ----
stock = pd.concat([load(f"data/{x}") for x in
    ["us_universe_weekly_adjclose.csv","hk_leaders_weekly_adjclose.csv",
     "equities_weekly_adjclose.csv","us_etf_weekly_adjclose.csv"]], axis=1)
stock = stock.loc[:, ~stock.columns.duplicated()]
stock = stock.resample("ME").last().dropna(how='all')

# ---- 商品/气体 (本就月线) ----
wb   = load("data/commodity_worldbank_monthly.csv")
gas  = load("data/gas_panel_monthly.csv")
eia  = load("data/eia_gas_monthly.csv")
comm = pd.concat([wb, gas, eia], axis=1).loc[:, ~wb.columns.append(gas.columns).append(eia.columns).duplicated(keep=False)]
# 上面去重写法过于复杂, 改用简单去重:
comm = pd.concat([wb, gas, eia], axis=1)
comm = comm.loc[:, ~comm.columns.duplicated()]

# ---- 对齐到共同月线索引 ----
allp = pd.concat([stock, comm], axis=1)
allp = allp.loc[:, ~allp.columns.duplicated()]
allp = allp[(allp.index >= WIN0) & (allp.index <= WIN1)]
allp = allp.apply(lambda s: s.interpolate(limit=3).ffill().bfill())
print(f"跨资产月线宇宙: {allp.shape[1]} 列 x {allp.shape[0]} 月 (2005~2025)")

stock_cols = [c for c in allp.columns if c in set(stock.columns)]
comm_cols  = [c for c in allp.columns if c not in set(stock_cols)]
print(f"  股票 {len(stock_cols)} / 商品+气体 {len(comm_cols)}")

# 预过滤: 任何标的价格曾<=0 或 任何单月 |收益|>0.9 -> 剔除(破产/脏数据)
def clean_cols(cols):
    good = []
    for c in cols:
        s = allp[c].dropna()
        if (s <= 0).any(): continue
        r = s.pct_change().dropna()
        if (r.abs() > 0.9).any(): continue
        good.append(c)
    return good

sc = clean_cols(stock_cols)
cc = clean_cols(comm_cols)
print(f"  清洗后: 股票 {len(sc)} / 商品+气体 {len(cc)}")

def excess(cols, monthly=True):
    """返回 再平衡CAGR - 持有CAGR (pp). 任意异常返回 None."""
    try:
        sub = allp[cols].dropna(how='any')
        if len(sub) < 120: return None
        r = sub.pct_change().dropna(how='any')
        if len(r) < 110: return None
        yrs = len(r) / 12.0
        # 再平衡: 每月重置等权, 净值模拟
        val = 1.0
        for _, row in r.iterrows():
            rr = np.clip(row.values, -0.95, None)
            if np.any(1+rr <= 0): return None
            val *= (1.0 + rr.mean())
        if not np.isfinite(val) or val <= 0: return None
        reb_c = val ** (1/yrs) - 1
        # 持有: 等权起步, 各标的 last/first
        g = (sub.iloc[-1] / sub.iloc[0]).values
        if np.any(g <= 0): return None
        hld_c = (g.mean()) ** (1/yrs) - 1
        if not (np.isfinite(reb_c) and np.isfinite(hld_c)): return None
        return (reb_c - hld_c) * 100
    except Exception:
        return None

rng = np.random.default_rng(11)
def pool_test(name, cols, n=60000):
    ex = []
    for _ in range(n):
        q = rng.choice(cols, 4, replace=False)
        e = excess(list(q))
        if e is not None: ex.append(e)
    ex = np.array(ex)
    med = float(np.median(ex)) if len(ex) else float('nan')
    win = float((ex > 0).mean()) if len(ex) else 0.0
    neg = float((ex < 0).mean()) if len(ex) else 0.0
    print(f"  {name:<24} (候选 {len(cols):>3}, 有效 {len(ex):>5}) 4配对: 超额中位 {med:>+7.2f}pp | 跑赢 {win:.1%} | 负占比 {neg:.1%}")
    return med, win

print("\n" + "=" * 72)
print("跨资产 4配对对比 (月线 2005~2025, 稳健清洗)")
pool_test("纯股票", sc)
pool_test("纯商品+气体", cc)
pool_test("混编(股票+商品随机4)", sc + cc)
