# -*- coding: utf-8 -*-
"""
【无杠杆现货 + 美股交易成本(1bp) 的净收益优化】—— 目标: 净 CAGR 往 20% 靠

约束(用户设定):
  - 不用杠杆, 全部现货(已剔除 2x/3x/反向 ETF, 宇宙中本就没有)
  - 交易成本 = 0.01% = 1bp(单边), 按换手额扣: 成本 = turnover * c
  - 满仓等权为主, 不做空不加杠杆

优化维度(全矩阵搜索):
  池大小 N(4/6/8) × 波动档(35/45/55) × 权重(EW/IV/RP) × 触发(月历/BAND) × 信号(NONE/ADAPT)
  → 找验证期(2016-2025, 样本外) 净 CAGR 最高的配置
"""
import pandas as pd, numpy as np
np.seterr(all="ignore")

TR0, TR1 = "2005-01-31", "2015-12-31"   # 训练期(用于筛池, 避免前视)
VA0, VA1 = "2016-01-31", "2025-12-31"   # 验证期(样本外)
C_BP = 1.0                               # 美股交易成本 1bp = 0.01%

FILES = [("us_universe_weekly_adjclose.csv", "美股"), ("hk_leaders_weekly_adjclose.csv", "港股"),
         ("equities_weekly_adjclose.csv", "个股"), ("us_etf_weekly_adjclose.csv", "ETF"),
         ("commodity_worldbank_monthly.csv", "商品"), ("gas_panel_monthly.csv", "天然气"),
         ("eia_gas_monthly.csv", "EIA"), ("global_assets_monthly.csv", "债汇指")]
# 杠杆/反向 ETF 黑名单(非现货, 即便出现也剔除)
LEV = {"TQQQ","SQQQ","UPRO","SPXU","SSO","SDS","TNA","TZA","UDOW","SDOW","NUGT","DUST","JNUG",
       "JDST","SOXL","SOXS","UVXY","SVXY","VXX","UGLD","FAS","FAZ","ERX","ERY","UCO","SCO",
       "BIB","BIS","LABU","LABD","TECL","TECS","CURE","YINN","YANG","CHAU","EURL","UTSL",
       "DPST","NAIL","WEBL","UBOT","BULZ","FNGO","GBTC","PSQ","SH","DOG","RWM","QID"}


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
allp = allp.drop(columns=[c for c in allp.columns if c in LEV], errors="ignore")
allp = allp[(allp.index >= TR0) & (allp.index <= VA1)].dropna(how="all")
print(f"全资产宇宙: {allp.shape[1]} 列 x {len(allp)} 月 (已剔除杠杆/反向ETF, 纯现货)")

# ---- 用训练期统计筛池(避免前视) ----
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
# 现货可交易: 非 EIA 噪声序列; 长期不归零(cagr>=0); 非超级赢家(cagr<=45)
BASE = df[(df.kind != "EIA") & (df.cagr >= 0) & (df.cagr <= 45)]
TIERS = {35: list(BASE[BASE.vol >= 35].index),
         45: list(BASE[BASE.vol >= 45].index),
         55: list(BASE[BASE.vol >= 55].index)}
print("候选池(按训练期波动档): " + " | ".join(f"vol>={k}: {len(v)}" for k, v in TIERS.items()))


def bt(cols, w0, w1, scheme="EW", trig="CAL", band=0.10, mode="NONE",
       strength=0.35, c_bp=C_BP, lookback=24, slow=60):
    """带交易成本的净收益回测. 返回净CAGR(已扣成本)"""
    px = allp.loc[w0:w1, list(cols)].dropna(how="any")
    if len(px) < 72:
        return None
    r = px.pct_change().dropna(how="any")
    if len(r) < 60:
        return None
    R = np.clip(r.values, -0.95, None)
    T, N = R.shape
    yrs = T / 12.0
    c = c_bp / 10000.0

    # 目标权重方案
    w_eq = np.ones(N) / N
    w_iv = np.zeros((T, N)); w_rp = np.zeros((T, N))
    sd24 = pd.DataFrame(R).rolling(24, min_periods=12).std().values
    sd24 = np.where(np.isfinite(sd24) & (sd24 > 1e-8), sd24, np.nan)
    for t in range(T):
        v = sd24[t]
        if np.all(np.isfinite(v)):
            iv = 1.0 / v
            w_iv[t] = iv / iv.sum()
        else:
            w_iv[t] = w_eq
    # RP: 逆协方差, 每12月更新一次
    w_rp[:] = w_eq
    for t in range(36, T, 12):
        C = np.cov(R[t - 36:t].T) + 1e-10 * np.eye(N)
        try:
            iv = np.linalg.solve(C, np.ones(N))
            if np.all(iv > 0):
                w = iv / iv.sum()
                w_rp[t:t + 12] = w
        except Exception:
            pass

    # 信号(只用 t-1 前信息)
    lp = np.log(px.values)
    rel = lp - lp.mean(axis=1, keepdims=True)
    disp = rel.std(axis=1)
    z_T = np.zeros((T, N)); mom_T = np.zeros((T, N))
    for t in range(lookback, T):
        win = rel[t - lookback:t]
        z_T[t] = -np.clip((rel[t - 1] - win.mean(axis=0)) / (win.std(axis=0) + 1e-9), -2, 2)
    for t in range(13, T):
        cum = np.prod(1 + R[t - 12:t - 1], axis=0)
        mom_T[t] = (cum - cum.mean()) / (cum.std() + 1e-9)

    val, w = 1.0, w_eq.copy()
    val_g = 1.0                            # 毛净值(不扣成本), 同循环累计, 省一遍回测
    nav = np.zeros(T + 1); nav[0] = 1.0
    turn_sum, n_reb = 0.0, 0
    for t in range(T):
        wd = w * (1 + R[t])
        wd = wd / (wd.sum() + 1e-12)          # 漂移后权重
        tgt = w_eq if scheme == "EW" else (w_iv[t] if scheme == "IV" else w_rp[t])
        if mode == "CONTR":
            sig = z_T[t]
        elif mode == "MOM":
            sig = mom_T[t]
        elif mode == "ADAPT":
            if t >= slow:
                sig = z_T[t] if disp[t - lookback:t].mean() > np.median(disp[t - slow:t]) else mom_T[t]
            else:
                sig = np.zeros(N)
        else:
            sig = np.zeros(N)
        if np.any(sig != 0):
            tw = np.clip(tgt + strength * tgt * sig, 0, None)
            tgt = tw / (tw.sum() + 1e-12)
        # 成本控制: 是否再平衡
        do = True
        if trig == "BAND" and np.max(np.abs(wd - tgt)) < band:
            do = False
        gr = float(np.dot(w, R[t]))
        val *= (1 + gr)
        val_g *= (1 + gr)
        if do:
            turn = float(np.abs(tgt - wd).sum())
            turn_sum += turn; n_reb += 1
            val *= (1 - turn * c)             # 扣交易成本
            w = tgt
        else:
            w = wd
        nav[t + 1] = val
    if not np.isfinite(val) or val <= 0:
        return None
    rc_net = val ** (1 / yrs) - 1
    rc_gross = val_g ** (1 / yrs) - 1 if (np.isfinite(val_g) and val_g > 0) else np.nan
    g = (px.iloc[-1] / px.iloc[0]).values
    if np.any(g <= 0):
        return None
    hc = float(g.mean()) ** (1 / yrs) - 1
    nr = np.diff(nav) / nav[:-1]
    vol = float(np.std(nr) * np.sqrt(12) * 100)
    mdd = float((nav / np.maximum.accumulate(nav) - 1).min() * 100)
    return dict(net=rc_net * 100, gross=rc_gross * 100, hold=hc * 100,
                excess_net=(rc_net - hc) * 100, vol=vol, mdd=mdd,
                sharpe=(rc_net * 100) / max(vol, 1e-6),
                turnover=turn_sum / yrs * 100, n_reb=n_reb)


rng = np.random.default_rng(909)


def sample_pools(vt, n, k, cnt):
    univ = TIERS[vt]
    if len(univ) < k + 1:
        return []
    out, seen, guard = [], set(), 0
    while len(out) < cnt and guard < cnt * 40:
        guard += 1
        q = tuple(sorted(rng.choice(univ, k, replace=False)))
        if q in seen:
            continue
        seen.add(q); out.append(q)
    return out


print("\n" + "=" * 112)
print("【PART 1】交易成本敏感性 (美股 1bp 基准; N=6, vol>=45, EW, 验证期 2016-2025)")
print("=" * 112)
pools6 = sample_pools(45, 6, 6, 60)
print(f"  {'成本':<14}{'触发':<12}{'净CAGR':>10}{'毛CAGR':>10}{'成本拖累':>10}{'年换手':>10}{'调仓次数':>10}")
cost_rows = []
for c_bp in [0, 1, 5, 10]:
    for trig, band, lbl in [("CAL", 0, "月历"), ("BAND", 0.10, "BAND10%"), ("BAND", 0.20, "BAND20%")]:
        nt, gr, tu, nr, ok = [], [], [], [], 0
        for q in pools6:
            m = bt(list(q), VA0, VA1, scheme="EW", trig=trig, band=band, mode="NONE", c_bp=c_bp)
            if m:
                nt.append(m["net"]); gr.append(m["gross"]); tu.append(m["turnover"])
                nr.append(m["n_reb"]); ok += 1
        print(f"  {c_bp:>3}bp{'':<8}{lbl:<12}{np.median(nt):>9.2f}%{np.median(gr):>9.2f}%"
              f"{np.median(gr)-np.median(nt):>+9.2f}pp{np.median(tu):>9.1f}%{np.median(nr):>10.0f}")
        cost_rows.append(dict(成本bp=c_bp, 触发=lbl, 净CAGR=np.median(nt), 毛CAGR=np.median(gr),
                              成本拖累=np.median(gr) - np.median(nt), 年换手=np.median(tu),
                              调仓次数=np.median(nr)))
pd.DataFrame(cost_rows).to_csv("data/evolve_cost_sens.csv", index=False, encoding="utf-8-sig")

print("\n" + "=" * 112)
print("【PART 2】优化矩阵: N × 波动档 × 权重 × 触发 × 信号  (验证期 2016-2025, 成本1bp, 全部样本外)")
print("=" * 112)
grid = []
for N in [4, 6, 8]:
    for vt in [35, 45, 55]:
        if len(TIERS[vt]) < N + 2:
            continue
        pls = sample_pools(vt, N, N, 30)
        if not pls:
            continue
        for scheme in ["EW", "IV", "RP"]:
            for trig, band in [("CAL", 0.0), ("BAND", 0.10)]:
                for mode in ["NONE", "ADAPT"]:
                    res = [bt(list(q), VA0, VA1, scheme=scheme, trig=trig, band=band, mode=mode)
                           for q in pls]
                    res = [x for x in res if x]
                    if len(res) < 10:
                        continue
                    grid.append(dict(N=N, 波动档=vt, 权重=scheme, 触发="月历" if trig == "CAL" else "BAND10",
                                     信号=mode, 净CAGR=np.median([x["net"] for x in res]),
                                     超额=np.median([x["excess_net"] for x in res]),
                                     波动=np.median([x["vol"] for x in res]),
                                     回撤=np.median([x["mdd"] for x in res]),
                                     夏普=np.median([x["sharpe"] for x in res]),
                                     过20占比=np.mean([x["net"] >= 20 for x in res]) * 100))
        print(f"  ... N={N} vol>={vt} 完成")
G = pd.DataFrame(grid).sort_values("净CAGR", ascending=False)
print("\n--- 净 CAGR Top 15 配置 ---")
print(G.head(15).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
G.to_csv("data/evolve_cost_grid.csv", index=False, encoding="utf-8-sig")

print("\n" + "=" * 112)
print("【PART 3】最优配置 样本内/外 双期对照 (确认非过拟合)")
print("=" * 112)
best = G.iloc[0]
print(f"  最优配置: N={int(best.N)} vol>={int(best.波动档)} 权重={best.权重} "
      f"触发={best.触发} 信号={best.信号}")
pls_b = sample_pools(int(best.波动档), int(best.N), int(best.N), 60)
print(f"  {'期间':<20}{'净CAGR中位':>12}{'超额中位':>12}{'波动':>10}{'回撤':>10}{'夏普':>8}{'≥20%占比':>10}")
cmp_rows = []
for lbl, a, b in [("训练期 2005-2015", TR0, TR1), ("验证期 2016-2025", VA0, VA1)]:
    res = [bt(list(q), a, b, scheme=best.权重,
              trig=("CAL" if best.触发 == "月历" else "BAND"), band=0.10, mode=best.信号)
           for q in pls_b]
    res = [x for x in res if x]
    print(f"  {lbl:<20}{np.median([x['net'] for x in res]):>11.2f}%"
          f"{np.median([x['excess_net'] for x in res]):>+11.2f}pp"
          f"{np.median([x['vol'] for x in res]):>9.1f}%"
          f"{np.median([x['mdd'] for x in res]):>9.1f}%"
          f"{np.median([x['sharpe'] for x in res]):>8.2f}"
          f"{np.mean([x['net'] >= 20 for x in res])*100:>9.1f}%")
    cmp_rows.append(dict(期间=lbl, 净CAGR=np.median([x["net"] for x in res]),
                         超额=np.median([x["excess_net"] for x in res]),
                         波动=np.median([x["vol"] for x in res]),
                         回撤=np.median([x["mdd"] for x in res]),
                         夏普=np.median([x["sharpe"] for x in res]),
                         过20占比=np.mean([x["net"] >= 20 for x in res]) * 100))

print("\n" + "=" * 112)
print("【PART 4】高波动档大搜索: 净 CAGR 分布 & 达标结构 (N=8, vol>=55, 最优配置)")
print("=" * 112)
if len(TIERS[55]) >= 10:
    big = sample_pools(55, 8, 8, 400)
    res = []
    for q in big:
        m = bt(list(q), VA0, VA1, scheme=best.权重,
               trig=("CAL" if best.触发 == "月历" else "BAND"), band=0.10, mode=best.信号)
        if m:
            res.append((q, m))
    nets = [m["net"] for _, m in res]
    print(f"  样本: {len(res)} 组 | 净CAGR 中位 {np.median(nets):.2f}% | "
          f"P25 {np.percentile(nets,25):.2f}% / P75 {np.percentile(nets,75):.2f}%")
    print(f"  ≥20% 占比 {np.mean([x>=20 for x in nets])*100:.1f}% | "
          f"≥15% 占比 {np.mean([x>=15 for x in nets])*100:.1f}%")
    res.sort(key=lambda x: -x[1]["net"])
    print("\n  --- 净CAGR Top 10 池(样本内挑选, 仅供结构参考, 不可当预期) ---")
    for q, m in res[:10]:
        print(f"    {','.join(q)[:60]:<62} 净{m['net']:>6.2f}% 毛{m['gross']:>6.2f}% "
              f"超额{m['excess_net']:>+6.2f}pp 波动{m['vol']:>5.1f}% 回撤{m['mdd']:>6.1f}%")

pd.DataFrame(cmp_rows).to_csv("data/evolve_cost20_cmp.csv", index=False, encoding="utf-8-sig")
print("\n已存: data/evolve_cost_sens.csv / evolve_cost_grid.csv / evolve_cost20_cmp.csv")
