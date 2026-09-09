# -*- coding: utf-8 -*-
"""
【信号生效条件】—— 价差反向/动量信号 在什么池上才有效?
假设: 等权再平衡本身就是"买落后卖超前"; 额外加价差tilt = 加倍。
      加倍只在【均值回归强(高γ* / 低相关)的池】上赚, 在【趋势池】上加倍亏损。
检验: 验证期(2016-2025), 池按【训练期γ*】分 Q1(低离散) / Q5(高离散),
      各测 NONE / SPREAD_CONTR_DYN / MOM, 看信号增量。
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
    return 0.5 * ((sd ** 2).mean() - (np.outer(sd, sd) * C).sum() / (N * N)) * 100


def bt(cols, w0, w1, signal="NONE", strength=0.3, lookback=24):
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
    w_t = np.ones(N) / N
    sig_T = np.zeros((T, N))
    if signal != "NONE":
        lp = np.log(px.values)
        rel = lp - lp.mean(axis=1, keepdims=True)
        for t in range(lookback, T):
            if signal == "SPREAD_CONTR_DYN":
                win = rel[t - lookback: t]
                sig_T[t] = -np.clip((rel[t - 1] - win.mean(axis=0)) / (win.std(axis=0) + 1e-9), -2, 2)
            else:
                a, b = max(0, t - 12), max(0, t - 1)
                cum = np.prod(1 + R[a:b], axis=0) if b > a else np.ones(N)
                sig_T[t] = (cum - cum.mean()) / (cum.std() + 1e-9)
    val, w = 1.0, w_t.copy()
    nav = np.zeros(T + 1); nav[0] = 1.0
    for t in range(T):
        rr = np.clip(R[t], -0.95, None)
        ww = w_t if signal == "NONE" else np.clip(w_t + strength * w_t * sig_T[t], 0, None)
        ww = ww / (ww.sum() + 1e-12)
        val *= (1 + float(np.dot(w, rr))); nav[t + 1] = val
        wd = w * (1 + rr); wd = wd / (wd.sum() + 1e-12)
        w = ww                                   # 月度等权再平衡 + 信号tilt
    if not np.isfinite(val) or val <= 0:
        return None
    rc = val ** (1 / yrs) - 1
    g = (px.iloc[-1] / px.iloc[0]).values
    if np.any(g <= 0):
        return None
    hc = float(g.mean()) ** (1 / yrs) - 1
    nr = np.diff(nav) / nav[:-1]
    vol = float(np.std(nr) * np.sqrt(12) * 100)
    return dict(cagr=rc * 100, hold=hc * 100, excess=(rc - hc) * 100, vol=vol,
                sharpe=(rc * 100) / max(vol, 1e-6))


# ---------- 生成池, 按训练期 γ* 排序, 取 Q1(低) / Q5(高) 各 70 组 ----------
rng = np.random.default_rng(101)
recs = []
seen = set()
while len(recs) < 500:
    q = tuple(sorted(rng.choice(POOL, 4, replace=False)))
    if q in seen:
        continue
    seen.add(q)
    g_tr = gamma_of(list(q), TR0, TR1)
    if g_tr is None:
        continue
    recs.append((g_tr, q))
recs.sort()
low_g = [q for g, q in recs[:80]]
high_g = [q for g, q in recs[-80:]]
print(f"候选池 {len(POOL)} | 低γ*组(Q1) {len(low_g)} 组, 高γ*组(Q5) {len(high_g)} 组  "
      f"[γ*: {recs[0][0]:.2f} ~ {recs[-1][0]:.2f}]")

print("\n" + "=" * 96)
print("【信号生效条件】验证期 2016-2025, 信号在高γ*(离散)池 vs 低γ*池 上的增量")
print("=" * 96)
out = []
for gname, pl in [("高γ*池 Q5(离散强)", high_g), ("低γ*池 Q1(离散弱)", low_g)]:
    print(f"\n--- {gname} ---")
    print(f"  {'信号':<26}{'CAGR中位':>10}{'超额中位':>10}{'波动中位':>10}{'夏普中位':>10}{'相对NONE':>11}")
    base = {}
    for q in pl:
        m0 = bt(list(q), VA0, VA1, signal="NONE")
        if m0:
            base[q] = m0
    bmed = np.median([v["cagr"] for v in base.values()])
    for sg, st in [("NONE(基准)", 0.0), ("SPREAD_CONTR_DYN@0.2", 0.2), ("SPREAD_CONTR_DYN@0.35", 0.35),
                   ("MOM@0.35", 0.35)]:
        cg, ex, vo, sh = [], [], [], []
        for q in pl:
            if q not in base:
                continue
            mm = bt(list(q), VA0, VA1, signal=sg.replace("@0.2", "").replace("@0.35", "")
                    if sg != "NONE(基准)" else "NONE", strength=st)
            if mm:
                cg.append(mm["cagr"]); ex.append(mm["excess"]); vo.append(mm["vol"]); sh.append(mm["sharpe"])
        if cg:
            delta = np.median(cg) - bmed
            print(f"  {sg:<26}{np.median(cg):>9.2f}%{np.median(ex):>+9.2f}pp{np.median(vo):>9.2f}%"
                  f"{np.median(sh):>10.2f}{delta:>+10.2f}pp")
            out.append(dict(池组=gname, 信号=sg, CAGR=np.median(cg), 超额=np.median(ex),
                            波动=np.median(vo), 夏普=np.median(sh), 相对基准=delta))
pd.DataFrame(out).to_csv("data/evolve_signal_cond.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/evolve_signal_cond.csv")
