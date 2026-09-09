# -*- coding: utf-8 -*-
"""
【自适应信号开关 ADAPTIVE REGIME SWITCH】—— 本轮"进化"的核心产物

发现(样本外): 高γ*池(离散强/均值回归) → 价差反向 +1.21pp, 动量 -1.02pp
             低γ*池(离散弱/趋势强)   → 价差反向 -1.32pp, 动量 +1.09pp
→ 完全对称! 说明: 该用"买落后"还是"买强势", 取决于池子当前处于哪种状态。

本脚本实现:
  每月用【滚动 24 月池内离散度 vs 滚动 60 月中位数】判断 regime:
     离散度高于自身常态 → 均值回归态 → 启用【价差反向】tilt
     离散度低于自身常态 → 趋势态     → 启用【动量】tilt
  全部只用 t-1 及以前信息, 无前视。

对照: NONE / 固定反向 / 固定动量 / 自适应开关   (验证期 2016-2025)
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
allp = pd.concat(panels, axis=1)
allp = allp.loc[:, ~allp.columns.duplicated()]
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
POOL = list(df[(df.kind != "EIA") & (df.vol >= 35) & (df.cagr >= 0) & (df.cagr <= 45)].index)
print(f"候选池(训练期2005-15筛选): {len(POOL)} 个")


def bt(cols, w0, w1, mode="NONE", strength=0.35, lookback=24, slow=60):
    """mode: NONE / CONTR / MOM / ADAPT"""
    px = allp.loc[w0:w1, list(cols)].dropna(how="any")
    if len(px) < 72:
        return None
    r = px.pct_change().dropna(how="any")
    if len(r) < 60:
        return None
    R = r.values; T, N = R.shape
    yrs = T / 12.0
    if yrs < 4:
        return None
    w_t = np.ones(N) / N

    lp = np.log(px.values)
    rel = lp - lp.mean(axis=1, keepdims=True)        # 相对强度(价差)
    disp = rel.std(axis=1)                            # 池内离散度序列
    # 价差 z-score (滚动)
    z_T = np.zeros((T, N))
    for t in range(lookback, T):
        win = rel[t - lookback: t]
        z_T[t] = -np.clip((rel[t - 1] - win.mean(axis=0)) / (win.std(axis=0) + 1e-9), -2, 2)
    # 动量 z-score
    mom_T = np.zeros((T, N))
    for t in range(13, T):
        cum = np.prod(1 + R[t - 12: t - 1], axis=0)
        mom_T[t] = (cum - cum.mean()) / (cum.std() + 1e-9)

    val, w = 1.0, w_t.copy()
    nav = np.zeros(T + 1); nav[0] = 1.0
    n_contr = n_mom = 0
    for t in range(T):
        rr = np.clip(R[t], -0.95, None)
        sig = np.zeros(N)
        if mode == "CONTR":
            sig = z_T[t]
        elif mode == "MOM":
            sig = mom_T[t]
        elif mode == "ADAPT":
            # regime 判定: 滚动24月离散度 vs 滚动60月中位数 (只用 t 之前)
            if t >= slow:
                d_fast = disp[t - lookback: t].mean()
                d_slow = np.median(disp[t - slow: t])
                if d_fast > d_slow:
                    sig = z_T[t]; n_contr += 1
                else:
                    sig = mom_T[t]; n_mom += 1
        ww = np.clip(w_t + strength * w_t * sig, 0, None)
        ww = ww / (ww.sum() + 1e-12)
        val *= (1 + float(np.dot(w, rr))); nav[t + 1] = val
        w = ww                                        # 月度再平衡到(带tilt的)目标权重
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
                sharpe=(rc * 100) / max(vol, 1e-6), n_contr=n_contr, n_mom=n_mom)


rng = np.random.default_rng(202)
pools, seen = [], set()
while len(pools) < 150:
    q = tuple(sorted(rng.choice(POOL, 4, replace=False)))
    if q in seen:
        continue
    seen.add(q); pools.append(q)
print(f"随机测试池: {len(pools)} 组")

print("\n" + "=" * 100)
print("【自适应开关验证】验证期 2016-2025 (10年, 样本外)")
print("=" * 100)
print(f"  {'模式':<26}{'CAGR中位':>10}{'超额中位':>10}{'波动中位':>10}{'回撤中位':>10}{'夏普中位':>10}{'胜率':>9}")
base = {}
for q in pools:
    m0 = bt(list(q), VA0, VA1, mode="NONE")
    if m0:
        base[q] = m0
bmed = np.median([v["cagr"] for v in base.values()])
out = []
for mode, st in [("NONE(基准)", 0.0), ("固定 价差反向@0.35", 0.35), ("固定 动量@0.35", 0.35),
                 ("自适应开关@0.25", 0.25), ("自适应开关@0.35", 0.35), ("自适应开关@0.50", 0.50)]:
    mm = "NONE" if mode.startswith("NONE") else ("CONTR" if "反向" in mode else ("MOM" if "动量" in mode else "ADAPT"))
    cg, ex, vo, md, sh, win, cnt = [], [], [], [], [], 0, 0
    for q in pools:
        if q not in base:
            continue
        r_ = bt(list(q), VA0, VA1, mode=mm, strength=st)
        if r_:
            cnt += 1
            cg.append(r_["cagr"]); ex.append(r_["excess"]); vo.append(r_["vol"])
            md.append(r_["mdd"]); sh.append(r_["sharpe"])
            if r_["cagr"] > base[q]["cagr"]:
                win += 1
    print(f"  {mode:<26}{np.median(cg):>9.2f}%{np.median(ex):>+9.2f}pp{np.median(vo):>9.2f}%"
          f"{np.median(md):>9.1f}%{np.median(sh):>10.2f}{win/cnt*100:>8.1f}%")
    out.append(dict(模式=mode, CAGR=np.median(cg), 超额=np.median(ex), 波动=np.median(vo),
                    回撤=np.median(md), 夏普=np.median(sh), 胜率=win / cnt * 100))

print("\n" + "=" * 100)
print("【同样测训练期 2005-2015 做对照】(看是否样本内虚高)")
print("=" * 100)
print(f"  {'模式':<26}{'CAGR中位':>10}{'超额中位':>10}")
for mode, st in [("NONE(基准)", 0.0), ("固定 价差反向@0.35", 0.35), ("自适应开关@0.35", 0.35)]:
    mm = "NONE" if mode.startswith("NONE") else ("CONTR" if "反向" in mode else "ADAPT")
    cg, ex = [], []
    for q in pools:
        r_ = bt(list(q), TR0, TR1, mode=mm, strength=st)
        if r_:
            cg.append(r_["cagr"]); ex.append(r_["excess"])
    print(f"  {mode:<26}{np.median(cg):>9.2f}%{np.median(ex):>+9.2f}pp")

pd.DataFrame(out).to_csv("data/evolve_adaptive.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/evolve_adaptive.csv")
