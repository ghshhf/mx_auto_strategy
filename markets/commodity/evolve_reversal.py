# -*- coding: utf-8 -*-
"""
【可迁移性解剖】—— 到底什么能从过去带到未来?
样本外发现: 训练期Top池 验证期18.11% < 随机18.47% < 训练期Bottom池 24.71%
本脚本拆解: 这个"反向"是 ①组合层面均值回归 还是 ②波动率差异 造成的?
分三组检验(训练期 2005-2015 → 验证期 2016-2025, 池内4资产随机600组):
  A 训练期 CAGR 分5档        → 检验均值回归(是否越差越好)
  B 训练期 γ*(离散度) 分5档   → 检验"波动率结构"是否可迁移(这是公式核心)
  C 训练期 池内波动率 分5档   → 检验波动率是否可迁移
  D 控制波动率后, A 是否仍成立 → 剔除波动率解释
"""
import pandas as pd, numpy as np
np.seterr(all="ignore")

TR0, TR1 = "2005-01-31", "2015-12-31"
VA0, VA1 = "2016-01-31", "2025-12-31"
FILES = [("us_universe_weekly_adjclose.csv", "美股"), ("hk_leaders_weekly_adjclose.csv", "港股"),
         ("equities_weekly_adjclose.csv", "个股"), ("us_etf_weekly_adjclose.csv", "ETF"),
         ("commodity_worldbank_monthly.csv", "商品"), ("gas_panel_monthly.csv", "天然气"),
         ("eia_gas_monthly.csv", "EIA"), ("global_assets_monthly.csv", "债汇指")]


def load_me(f):
    d = pd.read_csv(f, index_col=0, parse_dates=True).apply(pd.to_numeric, errors="coerce")
    d.columns = [c.lstrip("\ufeff") for c in d.columns]
    d = d[~d.index.duplicated(keep="last")]
    return d.resample("ME").last()


panels, kind = [], {}
for f, k in FILES:
    try:
        d = load_me(f"data/{f}")
        for c in d.columns:
            kind.setdefault(c, k)
        panels.append(d)
    except Exception:
        pass
allp = pd.concat(panels, axis=1).loc[:, ~pd.concat(panels, axis=1).columns.duplicated()]
allp = allp[(allp.index >= TR0) & (allp.index <= VA1)].dropna(how="all")

tr_px = allp.loc[TR0:TR1]
stat = {}
for c in allp.columns:
    s_tr = tr_px[c].dropna(); s = allp[c].dropna()
    if len(s_tr) < 100 or len(s) < 200 or (s <= 0).any():
        continue
    r = s_tr.pct_change().dropna()
    if (r.abs() > 0.9).any():
        continue
    yrs = (s_tr.index[-1] - s_tr.index[0]).days / 365.25
    cagr = (s_tr.iloc[-1] / s_tr.iloc[0]) ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(12)
    if np.isfinite(cagr) and np.isfinite(vol):
        stat[c] = (cagr * 100, vol * 100, kind.get(c, "?"))
df = pd.DataFrame(stat, index=["cagr", "vol", "kind"]).T
df[["cagr", "vol"]] = df[["cagr", "vol"]].astype(float)
POOL = list(df[(df.kind != "EIA") & (df.vol >= 30) & (df.cagr >= 0) & (df.cagr <= 45)].index)
print(f"候选池(训练期筛选): {len(POOL)} 个")


def bt(cols, w0, w1):
    px = allp.loc[w0:w1, list(cols)].dropna(how="any")
    if len(px) < 60:
        return None
    r = px.pct_change().dropna(how="any")
    if len(r) < 48:
        return None
    R = r.values; T, N = R.shape
    yrs = T / 12.0
    if yrs < 4:
        return None
    w = np.ones(N) / N
    val = 1.0
    nav = np.zeros(T + 1); nav[0] = 1.0
    for t in range(T):
        rr = np.clip(R[t], -0.95, None)
        val *= (1 + float(np.dot(w, rr)))
        nav[t + 1] = val
        wd = w * (1 + rr); w = wd / (wd.sum() + 1e-12)
        w = np.ones(N) / N                      # 月度等权再平衡
    if not np.isfinite(val) or val <= 0:
        return None
    rc = val ** (1 / yrs) - 1
    g = (px.iloc[-1] / px.iloc[0]).values
    if np.any(g <= 0):
        return None
    hc = float(g.mean()) ** (1 / yrs) - 1
    nr = np.diff(nav) / nav[:-1]
    vol = float(np.std(nr) * np.sqrt(12) * 100)
    mdd = float((nav / np.maximum.accumulate(nav) - 1).min() * 100)
    return dict(cagr=rc * 100, hold=hc * 100, excess=(rc - hc) * 100, vol=vol, mdd=mdd,
                sharpe=(rc * 100) / max(vol, 1e-6))


def gamma_of(cols, w0, w1):
    px = allp.loc[w0:w1, list(cols)].dropna(how="any")
    if len(px) < 48:
        return None
    r = px.pct_change().dropna(how="any")
    if len(r) < 36:
        return None
    C = np.nan_to_num(np.corrcoef(r.values.T))
    sd = np.nan_to_num(r.std().values * np.sqrt(12))
    N = len(cols)
    avg_var = (sd ** 2).mean()
    k = np.outer(sd, sd) * C
    port_var = k.sum() / (N * N)
    return 0.5 * (avg_var - port_var) * 100, sd.mean() * 100


# ---------- 生成随机组合, 记录训练期特征 + 验证期表现 ----------
rng = np.random.default_rng(77)
recs = []
seen = set()
while len(recs) < 700:
    q = tuple(sorted(rng.choice(POOL, 4, replace=False)))
    if q in seen:
        continue
    seen.add(q)
    a = bt(list(q), TR0, TR1)
    b = bt(list(q), VA0, VA1)
    if not (a and b):
        continue
    g_tr = gamma_of(list(q), TR0, TR1)
    g_va = gamma_of(list(q), VA0, VA1)
    if not (g_tr and g_va):
        continue
    recs.append(dict(q=",".join(q), tr_cagr=a["cagr"], tr_vol=a["vol"], tr_g=g_tr[0], tr_pvol=g_tr[1],
                     va_cagr=b["cagr"], va_hold=b["hold"], va_ex=b["excess"], va_vol=b["vol"],
                     va_g=g_va[0], va_pvol=g_va[1], va_sharpe=b["sharpe"], va_mdd=b["mdd"]))
D = pd.DataFrame(recs)
print(f"有效组合: {len(D)} 组")


def tier(name, key, n=5, ctrl=None):
    print(f"\n--- {name} ---")
    if ctrl is not None:
        # 控制变量: 在 ctrl 的中位附近子样本内分档
        lo, hi = D[ctrl].quantile(0.35), D[ctrl].quantile(0.65)
        sub = D[(D[ctrl] >= lo) & (D[ctrl] <= hi)].copy()
        print(f"  (控制 {ctrl} 在 {lo:.2f}~{hi:.2f} 区间, 子样本 {len(sub)} 组)")
    else:
        sub = D.copy()
    try:
        sub["tier"] = pd.qcut(sub[key], n, labels=[f"Q{i+1}" for i in range(n)], duplicates="drop")
    except Exception:
        return
    print(f"  {'档':<5}{'训练值':>10}{'验证CAGR':>10}{'验证持有':>10}{'验证超额':>10}{'验证夏普':>10}{'组数':>6}")
    for t, g in sub.groupby("tier", observed=True):
        print(f"  {str(t):<5}{g[key].median():>9.2f}{g['va_cagr'].median():>9.2f}%"
              f"{g['va_hold'].median():>9.2f}%{g['va_ex'].median():>+9.2f}pp"
              f"{g['va_sharpe'].median():>10.2f}{len(g):>6}")


print("\n" + "=" * 100)
print("【A】训练期 CAGR 分5档 → 验证期表现  (检验: 组合层面均值回归? 越差越好?)")
print("=" * 100)
tier("A. 训练期CAGR 分档", "tr_cagr")

print("\n" + "=" * 100)
print("【B】训练期 γ*(离散度) 分5档 → 验证期表现  (检验: 波动率结构可迁移? 这是公式核心)")
print("=" * 100)
tier("B. 训练期γ* 分档", "tr_g")

print("\n" + "=" * 100)
print("【C】训练期 池内波动率 分5档 → 验证期表现  (检验: 波动率可迁移?)")
print("=" * 100)
tier("C. 训练期池内波动 分档", "tr_pvol")

print("\n" + "=" * 100)
print("【D】控制池内波动率后, 训练期CAGR 分档是否仍反向? (剔除波动率解释)")
print("=" * 100)
tier("D. 控制波动后 训练期CAGR 分档", "tr_cagr", ctrl="tr_pvol")

# ---------- 相关性总表 ----------
print("\n" + "=" * 100)
print("【E】相关系数矩阵: 什么训练期特征 能预测 验证期超额?")
print("=" * 100)
cols_tr = ["tr_cagr", "tr_vol", "tr_g", "tr_pvol"]
print(f"  {'训练期特征':<16}{'vs 验证期超额':>16}{'vs 验证期CAGR':>16}{'vs 验证期夏普':>16}")
for c in cols_tr:
    print(f"  {c:<16}{D[c].corr(D['va_ex']):>16.3f}{D[c].corr(D['va_cagr']):>16.3f}"
          f"{D[c].corr(D['va_sharpe']):>16.3f}")
print(f"\n  验证期 γ* vs 验证期超额: {D['va_g'].corr(D['va_ex']):.3f}  ← 同期解释力(已知)")
print(f"  训练期 γ* vs 验证期 γ* : {D['tr_g'].corr(D['va_g']):.3f}  ← γ* 自身的持续性")
print(f"  训练期池波动 vs 验证期池波动: {D['tr_pvol'].corr(D['va_pvol']):.3f}  ← 波动率持续性")
print(f"  训练期CAGR vs 验证期CAGR: {D['tr_cagr'].corr(D['va_cagr']):.3f}  ← 收益持续性")

D.to_csv("data/evolve_reversal.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/evolve_reversal.csv")
