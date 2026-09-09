# -*- coding: utf-8 -*-
"""core20: 无杠杆现货 + 成本 的回测内核(供各优化脚本复用, 无主流程)"""
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
         ("a_leaders_weekly_adjclose.csv", "A股"), ("yahoo_global_weekly_adjclose.csv", "环球"),
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
       strength=0.35, c_bp=C_BP, lookback=24, slow=60, minm=72):
    """带交易成本的净收益回测. 返回净CAGR(已扣成本). minm=最短月数(滚动分段用小值)"""
    px = allp.loc[w0:w1, list(cols)].dropna(how="any")
    if len(px) < minm:
        return None
    r = px.pct_change().dropna(how="any")
    if len(r) < max(minm - 12, 24):
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


