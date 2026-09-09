# -*- coding: utf-8 -*-
"""验证用户机制: 再平衡收益来自"波动率差/离散度"(dispersion), 非单资产波动率。
做法: 对候选池全枚举4元组, 计算
  - 平均单资产波动  mean(vol_i)
  - 离散度 gamma* = 0.5*(mean(var_i) - var_p)   [组合方差用样本协方差]
  - 池内平均相关性
  - 实际再平衡超额 (回测)
然后按 gamma* 分档, 看离散度能否解释/预测超额。
"""
import pandas as pd, numpy as np, itertools
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
    if np.isfinite(cagr) and np.isfinite(vol): stat[c] = (cagr*100, vol*100, kind.get(c,"?"))
df = pd.DataFrame(stat, index=["cagr","vol","kind"]).T
df[["cagr","vol"]] = df[["cagr","vol"]].astype(float)

# 候选池: 可交易 + 高波动 + 剔除超级赢家 (排除EIA数据噪声)
pool = list(df[(df.kind != "EIA") & (df.vol >= 45) & (df.cagr >= 5) & (df.cagr <= 20)].index)
print(f"候选池 {len(pool)} 个 (可交易, vol≥45, 5%≤CAGR≤20%, 剔除超级赢家与EIA噪声)")
print(f"  {pool}")

rows = []
for combo in itertools.combinations(pool, 4):
    px = allp[list(combo)].dropna(how='any')
    if len(px) < 120: continue
    r = px.pct_change().dropna(how='any')
    if len(r) < 110: continue
    yrs = len(r)/12.0
    # 实际回测
    reb = float(np.prod(1.0 + r.mean(axis=1).values))
    g = (px.iloc[-1]/px.iloc[0]).values
    if np.any(g <= 0): continue
    hld = float(g.mean())
    if not (np.isfinite(reb) and reb > 0 and hld > 0): continue
    rc = reb**(1/yrs)-1; hc = hld**(1/yrs)-1
    excess = (rc-hc)*100
    # 离散度 gamma*
    cov = r.cov().values * 12                       # 年化协方差
    var_i = np.diag(cov)                            # 各资产年化方差
    w = np.ones(4)/4
    var_p = float(w @ cov @ w)                      # 组合年化方差
    gamma = 0.5*(var_i.mean() - var_p)*100          # 离散度收益(年化%)
    # 相关性 & 平均波动
    corr = r.corr().values
    avg_corr = corr[np.triu_indices(4,1)].mean()
    avg_vol = np.sqrt(var_i).mean()*100
    rows.append(dict(combo=",".join(combo), excess=excess, gamma=gamma,
                     avg_vol=avg_vol, avg_corr=avg_corr, rebal=rc*100, hold=hc*100))

res = pd.DataFrame(rows)
print(f"\n有效组合 {len(res)} 个")
print(f"  实际超额: 中位 {res.excess.median():.2f}pp  均值 {res.excess.mean():.2f}pp")
print(f"  离散度γ*: 中位 {res.gamma.median():.2f}%  均值 {res.gamma.mean():.2f}%")

print(f"\n--- 谁更能解释超额? (相关系数) ---")
print(f"  离散度 γ*   vs 实际超额 : r = {res.gamma.corr(res.excess):.3f}")
print(f"  平均波动率   vs 实际超额 : r = {res.avg_vol.corr(res.excess):.3f}")
print(f"  平均相关性   vs 实际超额 : r = {res.avg_corr.corr(res.excess):.3f}")

print(f"\n--- 按离散度 γ* 分档 → 实际能挣多少 ---")
res['tier'] = pd.qcut(res.gamma, 4, labels=["Q1低离散","Q2","Q3","Q4高离散"])
print(res.groupby('tier').agg(
    组合数=("excess","size"), γstar均值=("gamma","mean"), 平均波动=("avg_vol","mean"),
    平均相关=("avg_corr","mean"), 实际超额均值=("excess","mean"),
    再平衡CAGR=("rebal","mean"), 持有CAGR=("hold","mean")).round(2).to_string())

print(f"\n--- 离散度最高 Top8 组合 (用户逻辑: 波动率差最大) ---")
print(res.nlargest(8, "gamma")[["combo","gamma","avg_corr","excess","rebal","hold"]].round(2).to_string(index=False))
print(f"\n--- 实际超额最高 Top8 组合 ---")
print(res.nlargest(8, "excess")[["combo","gamma","avg_corr","excess","rebal","hold"]].round(2).to_string(index=False))
res.to_csv("data/dispersion_result.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/dispersion_result.csv")
