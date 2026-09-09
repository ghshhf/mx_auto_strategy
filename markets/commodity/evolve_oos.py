# -*- coding: utf-8 -*-
"""
【样本外验证 OOS】—— 回答两个关键问题:
  Q1 用历史"挑出来的最优池", 未来还行吗?  (= 选池能力是否可迁移)
  Q2 "价差反向 / 动量 信号" 在未来还有效吗? (= 预判信号是否可迁移)
设计:
  训练期 2005-01 ~ 2015-12 (11年)  → 选池 / 选参数
  验证期 2016-01 ~ 2025-12 (10年)  → 打分
对照:
  A 训练期Top池   B 训练期Bottom池   C 随机池(基准)
  信号: NONE / SPREAD_CONTR_DYN / MOM  三段各测
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

# 候选池: 用【训练期】数据筛选(不得偷看验证期)
tr_px = allp.loc[TR0:TR1]
stat = {}
for c in allp.columns:
    s = allp[c].dropna()
    s_tr = tr_px[c].dropna()
    if len(s_tr) < 100 or len(s) < 200:
        continue
    if (s <= 0).any():
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
# 只用训练期可见信息筛池: 高波动 + 训练期收益为正 + 非EIA噪声
POOL = list(df[(df.kind != "EIA") & (df.vol >= 35) & (df.cagr >= 3) & (df.cagr <= 40)].index)
print(f"训练期(2005-2015)筛选 → 候选池 {len(POOL)} 个 (vol≥35, 训练期CAGR 3~40%, 非EIA)")


def bt(cols, w0, w1, signal="NONE", strength=0.3, trigger="CAL_M", band=0.10, lookback=24):
    px = allp.loc[w0:w1, list(cols)].dropna(how="any")
    if len(px) < 60:
        return None
    r = px.pct_change().dropna(how="any")
    if len(r) < 48:
        return None
    R = r.values
    T, N = R.shape
    yrs = T / 12.0
    if yrs < 4:
        return None
    w_t = np.ones(N) / N

    # 信号 (只用截至 t-1 的信息, 无前视)
    sig_T = np.zeros((T, N))
    if signal in ("SPREAD_CONTR_DYN", "MOM"):
        lp = np.log(px.values)
        rel = lp - lp.mean(axis=1, keepdims=True)
        for t in range(T):
            if t < lookback:
                continue
            if signal == "SPREAD_CONTR_DYN":
                win = rel[t - lookback: t]
                z = (rel[t - 1] - win.mean(axis=0)) / (win.std(axis=0) + 1e-9)
                sig_T[t] = -np.clip(z, -2, 2)
            else:  # MOM 12-1
                a, b = max(0, t - 12), max(0, t - 1)
                cum = np.prod(1 + R[a:b], axis=0) if b > a else np.ones(N)
                sig_T[t] = (cum - cum.mean()) / (cum.std() + 1e-9)

    val, wact = 1.0, w_t.copy()
    nav = np.zeros(T + 1); nav[0] = 1.0
    for t in range(T):
        rr = np.clip(R[t], -0.95, None)
        if signal == "NONE":
            ww = w_t
        else:
            ww = np.clip(w_t + strength * w_t * sig_T[t], 0, None)
            ww = ww / (ww.sum() + 1e-12)
        val *= (1 + float(np.dot(wact, rr)))
        nav[t + 1] = val
        wd = wact * (1 + rr); wd = wd / (wd.sum() + 1e-12)
        if trigger == "CAL_M":
            do = True
        elif trigger == "CAL_Q":
            do = ((t + 1) % 3 == 0)
        else:
            do = np.abs(wd - ww).max() > band
        wact = ww if do else wd
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


# ---------- 训练期: 用 γ* 预筛 + 精确回测 选出 Top / Bottom ----------
rng = np.random.default_rng(21)
cand = POOL
tr = allp.loc[TR0:TR1, cand]
Rtr = tr.pct_change()
Ctr = np.nan_to_num(Rtr.corr().values)
sdtr = np.nan_to_num(Rtr.std().values * np.sqrt(12))
m = len(cand)
S = 20000
idx = rng.integers(0, m, size=(S, 4))
idx = np.array([row for row in idx if len(set(row)) == 4])
print(f"训练期采样组合: {len(idx)} 组")

sub_c = Ctr[idx[:, :, None], idx[:, None, :]]
sub_sd = sdtr[idx]
avg_var = (sub_sd ** 2).mean(axis=1)
cov = sub_c * (sub_sd[:, :, None] * sub_sd[:, None, :])
port_var = cov.sum(axis=(1, 2)) / 16
gamma = 0.5 * (avg_var - port_var) * 100
order = np.argsort(-gamma)

scored = []
for i in order[:1500]:
    cols = [cand[j] for j in idx[i]]
    mm = bt(cols, TR0, TR1)
    if mm:
        scored.append((mm["cagr"], gamma[i], tuple(cols)))
scored.sort(key=lambda x: -x[0])
print(f"训练期有效组合: {len(scored)}")

TOPN = 30
top_pools = [s[2] for s in scored[:TOPN]]
bot_pools = [s[2] for s in scored[-TOPN:]]
rand_pools = [tuple(list(rng.choice(cand, 4, replace=False))) for _ in range(60)]

print("\n" + "=" * 104)
print("【Q1】选池能力可迁移性: 训练期(05-15)挑出的池, 在验证期(16-25)表现如何?")
print("=" * 104)
print(f"{'池组':<22}{'训练CAGR':>10}{'验证CAGR':>10}{'验证持有':>10}{'验证超额':>10}{'验证波动':>10}{'验证夏普':>10}")
rows = []
for nm, pl in [("训练期Top30池", top_pools), ("随机池(基准)", rand_pools), ("训练期Bottom30池", bot_pools)]:
    tr_c, va_c, va_h, va_e, va_v, va_s = [], [], [], [], [], []
    for q in pl:
        a = bt(list(q), TR0, TR1); b = bt(list(q), VA0, VA1)
        if a and b:
            tr_c.append(a["cagr"]); va_c.append(b["cagr"]); va_h.append(b["hold"])
            va_e.append(b["excess"]); va_v.append(b["vol"]); va_s.append(b["sharpe"])
    if tr_c:
        print(f"{nm:<22}{np.median(tr_c):>9.2f}%{np.median(va_c):>9.2f}%{np.median(va_h):>9.2f}%"
              f"{np.median(va_e):>+9.2f}pp{np.median(va_v):>9.2f}%{np.median(va_s):>10.2f}")
        rows.append(dict(池组=nm, 训练CAGR=np.median(tr_c), 验证CAGR=np.median(va_c),
                         验证持有=np.median(va_h), 验证超额=np.median(va_e),
                         验证波动=np.median(va_v), 验证夏普=np.median(va_s)))

print("\n" + "=" * 104)
print("【Q2】信号层可迁移性: 在【验证期】上, 价差反向 / 动量 是否仍增超额? (池=随机60组)")
print("=" * 104)
print(f"{'信号':<26}{'CAGR中位':>10}{'超额中位':>10}{'波动中位':>10}{'夏普中位':>10}{'胜率(>NONE)':>13}")
sig_rows = []
base_res = {}
for q in rand_pools:
    m0 = bt(list(q), VA0, VA1, signal="NONE")
    if m0:
        base_res[q] = m0
for sg, st in [("NONE", 0.0), ("SPREAD_CONTR_DYN", 0.15), ("SPREAD_CONTR_DYN", 0.30),
               ("SPREAD_CONTR_DYN", 0.50), ("MOM", 0.30), ("MOM", 0.50)]:
    cg, ex, vo, sh, win, cnt = [], [], [], [], 0, 0
    for q in rand_pools:
        if q not in base_res:
            continue
        mm = bt(list(q), VA0, VA1, signal=sg, strength=st)
        if not mm:
            continue
        cnt += 1
        cg.append(mm["cagr"]); ex.append(mm["excess"]); vo.append(mm["vol"]); sh.append(mm["sharpe"])
        if mm["cagr"] > base_res[q]["cagr"]:
            win += 1
    if cnt:
        tag = f"{sg}@{st}" if sg != "NONE" else "NONE(基准)"
        print(f"{tag:<26}{np.median(cg):>9.2f}%{np.median(ex):>+9.2f}pp{np.median(vo):>9.2f}%"
              f"{np.median(sh):>10.2f}{win/cnt*100:>12.1f}%")
        sig_rows.append(dict(信号=tag, CAGR=np.median(cg), 超额=np.median(ex), 波动=np.median(vo),
                             夏普=np.median(sh), 胜率=win / cnt * 100))

print("\n" + "=" * 104)
print("【Q3】触发方式可迁移性: BAND(阈值) vs 日历, 验证期表现 + 再平衡次数")
print("=" * 104)
for trig in ["CAL_M", "CAL_Q", "BAND_10", "BAND_20", "BAND_30"]:
    cg, ex = [], []
    for q in rand_pools:
        mm = bt(list(q), VA0, VA1, trigger=trig)
        if mm:
            cg.append(mm["cagr"]); ex.append(mm["excess"])
    if cg:
        print(f"  {trig:<10} CAGR中位 {np.median(cg):>6.2f}%  超额中位 {np.median(ex):>+6.2f}pp")

pd.DataFrame(rows).to_csv("data/evolve_oos_pools.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(sig_rows).to_csv("data/evolve_oos_signal.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/evolve_oos_pools.csv / data/evolve_oos_signal.csv")
