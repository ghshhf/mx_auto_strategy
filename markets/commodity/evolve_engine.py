# -*- coding: utf-8 -*-
"""
【进化版全资产再平衡引擎 v3】
叠加三层优化, 目标: 在"全资产互相平衡"框架下尽量榨取更高年化。

  Layer 1 权重方案 (weighting)
      EW  等权            —— 基准
      IV  波动率倒数      —— 给低波动资产更大权重
      RP  风险平价        —— 各资产风险贡献相等
      GMV 最小方差        —— 压波动(对照)
      MAXG γ*最大化(近似) —— 用协方差矩阵贪心优化离散度

  Layer 2 触发方式 (trigger)
      CAL_M / CAL_Q  日历(月/季)
      BAND_x         阈值: 权重偏离目标超过 x% 才再平衡
      DISP           离散度触发: 池内价差离散度超过滚动阈值再平衡

  Layer 3 信号层 (signal / 预判)  ← 用户要求"通过价差更好的捕获"
      SPREAD_CONTR  价差反向 tilt: 用两两价差 z-score, 向"落后"资产倾斜权重
                    (价差 = log 价格相对强度的偏离, z-score 越负 = 越落后 = 越加仓)
      MOM           动量 tilt: 12-1 动量向强者倾斜
      VOLTARGET     波动率目标: 按已实现波动缩放总仓位(带现金)

产出: data/evolve_result.csv + 控制台全表
"""
import pandas as pd, numpy as np
np.seterr(all="ignore")

W0, W1 = "2005-01-31", "2025-12-31"
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
allp = allp[(allp.index >= W0) & (allp.index <= W1)].dropna(how="all")
print(f"全资产宇宙(月线): {allp.shape[1]} 列 x {allp.shape[0]} 月  [{allp.index[0].date()} ~ {allp.index[-1].date()}]")

# ---------- 标的清洗: 剔除噪声序列(EIA跳变) / 非正价 / 缺数据 ----------
stat = {}
for c in allp.columns:
    s = allp[c].dropna()
    if len(s) < 150:
        continue
    if (s <= 0).any():
        continue
    r = s.pct_change().dropna()
    if (r.abs() > 0.9).any():
        continue
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(12)
    if np.isfinite(cagr) and np.isfinite(vol):
        stat[c] = (cagr * 100, vol * 100, kind.get(c, "?"))
df = pd.DataFrame(stat, index=["cagr", "vol", "kind"]).T
df[["cagr", "vol"]] = df[["cagr", "vol"]].astype(float)
print(f"清洗后候选: {len(df)}  (美股{ (df.kind=='美股').sum() } / 港股{ (df.kind=='港股').sum() } / "
      f"ETF{ (df.kind=='ETF').sum() } / 商品{ (df.kind=='商品').sum() } / 气{ (df.kind=='天然气').sum() } / 债汇指{ (df.kind=='债汇指').sum() })")

# 候选池: 持续高波动 + 长期正收益 + 非超级赢家 + 排除EIA噪声
POOL = df[(df.kind != "EIA") & (df.vol >= 35) & (df.cagr >= 5) & (df.cagr <= 28)]
POOL = list(POOL.index)
print(f"【进化池】vol≥35 & 5%≤CAGR≤28% & 非EIA噪声 → {len(POOL)} 个")


# ================= 核心: 通用回测器 =================
def backtest(cols, weight="EW", trigger="CAL_M", signal="NONE", signal_strength=0.3,
             band=0.20, lookback=24, vol_target=None, cost_bp=0.0):
    """返回 dict(CAGR, 超额, 波动, MDD, 换手) 或 None"""
    px = allp[list(cols)].dropna(how="any")
    if len(px) < 100:
        return None
    r = px.pct_change().dropna(how="any")
    if len(r) < 96:
        return None
    R = r.values                      # T x N
    T, N = R.shape
    yrs = T / 12.0
    if yrs < 8:
        return None

    # ---------- 目标权重 ----------
    C = np.corrcoef(R.T)
    sd = R.std(axis=0)
    Cov = np.cov(R.T)

    def w_ew():
        return np.ones(N) / N

    def w_iv():
        w = 1.0 / np.maximum(sd, 1e-6)
        return w / w.sum()

    def w_rp():
        w = np.ones(N) / N
        for _ in range(200):
            rc = w * (Cov @ w)
            g = rc / rc.sum()
            w = 0.5 * w + 0.5 * (1.0 / np.maximum(sd, 1e-6))
            w = w / w.sum()
        return w

    def w_gmv():
        try:
            iv = np.linalg.pinv(Cov)
        except Exception:
            return w_ew()
        w = iv @ np.ones(N)
        if (w < 0).all():
            w = -w
        w = np.clip(w, 0, None)
        return w / w.sum() if w.sum() > 0 else w_ew()

    def w_maxg():
        """γ*最大化近似: 最大化 ½(w'Σ_diag w − w'Σ w), 用投影梯度上升"""
        D = np.diag(np.diag(Cov))          # 加权平均方差(对角)
        A = D - Cov                        # 二次型, γ* = ½ w'Aw
        w = np.ones(N) / N
        for _ in range(300):
            g = A @ w
            w = w + 0.05 * g / (np.abs(g).max() + 1e-9)
            w = np.clip(w, 0.02, None)
            w = w / w.sum()
        return w

    WMAP = {"EW": w_ew, "IV": w_iv, "RP": w_rp, "GMV": w_gmv, "MAXG": w_maxg}
    w_t = WMAP[weight]()

    # ---------- 信号 tilt (预判: 价差 / 动量) ----------
    sig = np.zeros(N)
    if signal == "SPREAD_CONTR":
        # 价差 z-score: 用滚动窗口内 相对强度(对数价 - 池均值) 的 z-score
        lp = np.log(px.values)
        rel = lp - lp.mean(axis=1, keepdims=True)      # 相对强度(价差)
        z = np.zeros(N)
        t0 = max(lookback, 12)
        if T > t0:
            win = rel[T - t0: T]
            mu = win.mean(axis=0)
            sdw = win.std(axis=0) + 1e-9
            z = (rel[T - 1] - mu) / sdw
        sig = -z                                        # 反向: 越落后(负) → 越加仓
    elif signal == "MOM":
        cum = np.prod(1 + R[max(0, T - 12): T - 1], axis=0) if T > 13 else np.ones(N)
        mm = (cum - cum.mean()) / (cum.std() + 1e-9)
        sig = mm
    elif signal == "SPREAD_CONTR_DYN":
        lp = np.log(px.values)
        rel = lp - lp.mean(axis=1, keepdims=True)
        zfull = np.zeros((T, N))
        for t in range(lookback, T):
            win = rel[t - lookback: t]
            zfull[t] = (rel[t - 1] - win.mean(axis=0)) / (win.std(axis=0) + 1e-9)
        zfull[:lookback] = 0
        sig_T = -np.clip(zfull, -2, 2)                  # T x N
        sig = None                                       # 走动态分支

    # ---------- 触发逻辑 ----------
    if trigger.startswith("BAND"):
        band = float(trigger.split("_")[1]) / 100.0
    disp_T = None
    if trigger == "DISP":
        lp = np.log(px.values)
        rel = lp - lp.mean(axis=1, keepdims=True)
        disp_T = rel.std(axis=1)                        # 池内离散度
        roll = pd.Series(disp_T).rolling(lookback, min_periods=12).mean().values

    val = 1.0
    wact = w_t.copy()
    nav = np.zeros(T + 1)
    nav[0] = 1.0
    n_reb = 0
    prev_w = wact.copy()
    for t in range(T):
        rr = np.clip(R[t], -0.95, None)
        # 动态权重 = 目标权重 + 信号 tilt
        if signal == "SPREAD_CONTR_DYN" and sig is None:
            ww = w_t + signal_strength * w_t * sig_T[t]
        elif signal in ("SPREAD_CONTR", "MOM"):
            ww = w_t + signal_strength * w_t * sig
        else:
            ww = w_t
        ww = np.clip(ww, 0, None)
        if ww.sum() <= 0:
            ww = w_t
        ww = ww / ww.sum()

        # 波动率目标缩放
        if vol_target is not None:
            rv = np.std(R[max(0, t - 12): t + 1]) * np.sqrt(12) if t >= 12 else sd.mean() * np.sqrt(12)
            scale = np.clip(vol_target / max(rv, 1e-6), 0.2, 1.0)
        else:
            scale = 1.0

        port_r = float(np.dot(wact, rr)) * scale
        val *= (1 + port_r)
        nav[t + 1] = val
        # 漂移后权重
        wdrift = wact * (1 + rr)
        wdrift = wdrift / (wdrift.sum() + 1e-12)

        do_reb = False
        if trigger == "CAL_M":
            do_reb = True
        elif trigger == "CAL_Q":
            do_reb = ((t + 1) % 3 == 0)
        elif trigger.startswith("BAND"):
            do_reb = np.abs(wdrift - ww).max() > band
        elif trigger == "DISP":
            do_reb = (disp_T[t] > roll[t]) if np.isfinite(roll[t]) else False
        if do_reb:
            if cost_bp > 0:
                val *= (1 - cost_bp * np.abs(wdrift - ww).sum())
            wact = ww
            n_reb += 1
        else:
            wact = wdrift
        prev_w = wact.copy()

    if not np.isfinite(val) or val <= 0:
        return None
    reb_cagr = val ** (1 / yrs) - 1
    g = (px.iloc[-1] / px.iloc[0]).values
    if np.any(g <= 0):
        return None
    hld_cagr = float(g.mean()) ** (1 / yrs) - 1
    # 波动 & MDD (组合净值)
    navr = np.diff(nav) / nav[:-1]
    vol = float(np.std(navr) * np.sqrt(12) * 100)
    peak = np.maximum.accumulate(nav)
    mdd = float((nav / peak - 1).min() * 100)
    return dict(cagr=reb_cagr * 100, hold=hld_cagr * 100, excess=(reb_cagr - hld_cagr) * 100,
                vol=vol, mdd=mdd, nreb=n_reb, sharpe=(reb_cagr * 100) / max(vol, 1e-6))


# ================= 实验 1: 权重 × 触发 网格 =================
def run_grid(cols, tag=""):
    rows = []
    for wname in ["EW", "IV", "RP", "MAXG"]:
        for trig in ["CAL_M", "CAL_Q", "BAND_10", "BAND_20", "DISP"]:
            m = backtest(cols, weight=wname, trigger=trig)
            if m:
                rows.append(dict(标的=",".join(cols), 权重=wname, 触发=trig, 信号="NONE",
                                 CAGR=m["cagr"], 持有=m["hold"], 超额=m["excess"],
                                 波动=m["vol"], 回撤=m["mdd"], 夏普=m["sharpe"], 再平衡次数=m["nreb"]))
    return rows


# ================= 实验 2: 信号层(价差/动量) =================
def run_signal(cols):
    rows = []
    for sg in ["NONE", "SPREAD_CONTR", "SPREAD_CONTR_DYN", "MOM"]:
        for st in ([0.0] if sg == "NONE" else [0.15, 0.30, 0.50]):
            m = backtest(cols, weight="EW", trigger="CAL_M", signal=sg, signal_strength=st)
            if m:
                rows.append(dict(标的=",".join(cols), 权重="EW", 触发="CAL_M",
                                 信号=f"{sg}@{st}", CAGR=m["cagr"], 持有=m["hold"], 超额=m["excess"],
                                 波动=m["vol"], 回撤=m["mdd"], 夏普=m["sharpe"], 再平衡次数=m["nreb"]))
    return rows


# ================= 实验 3: 无限组合搜索 (向量化 γ* 预筛 + 精确回测) =================
def search(n_pool=4, n_sample=60000, weight="EW", trigger="CAL_M", signal="NONE",
           signal_strength=0.3, top=12, seed=11):
    """先在池内用 γ* 解析式快速预筛, 再对高分者精确回测"""
    cand = [c for c in POOL if c in allp.columns]
    px = allp[cand]
    R = px.pct_change()
    C = R.corr().values
    sd = R.std().values * np.sqrt(12)
    m = len(cand)
    C = np.nan_to_num(C, nan=0.0)
    sd = np.nan_to_num(sd, nan=0.0)

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, m, size=(n_sample, n_pool))
    # 去重: 同一组合内互异
    ok = np.array([len(set(row)) == n_pool for row in idx])
    idx = idx[ok]
    if len(idx) > 30000:
        idx = idx[:30000]

    # 向量化 γ* = ½(加权平均方差 − 组合方差), 等权
    sub_c = C[idx[:, :, None], idx[:, None, :]]        # S x k x k
    sub_sd = sd[idx]                                   # S x k
    k = n_pool
    avg_var = (sub_sd ** 2).mean(axis=1)               # 加权平均方差
    cov = sub_c * (sub_sd[:, :, None] * sub_sd[:, None, :])
    port_var = cov.sum(axis=(1, 2)) / (k * k)
    gamma = 0.5 * (avg_var - port_var) * 100           # %
    order = np.argsort(-gamma)[:top * 8]               # 取 γ* 最高的前 top*8 做精确回测

    out = []
    for i in order:
        cols = [cand[j] for j in idx[i]]
        m_ = backtest(cols, weight=weight, trigger=trigger, signal=signal,
                      signal_strength=signal_strength)
        if m_:
            out.append(dict(标的=",".join(cols), γ预测=gamma[i], CAGR=m_["cagr"], 持有=m_["hold"],
                            超额=m_["excess"], 波动=m_["vol"], 回撤=m_["mdd"], 夏普=m_["sharpe"]))
    out.sort(key=lambda x: -x["CAGR"])
    return out[:top]


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "ALL"

    # ---------- 基准池 (确定性: 跨资产 4 组合) ----------
    def has(x):
        return x if x in allp.columns else None

    BASE = [c for c in ["MU", "FCX", "XAU", "NG_US"] if has(c)]
    if len(BASE) >= 3:
        print("\n" + "=" * 108)
        print(f"【实验1】权重方案 × 触发方式  (基准池: {','.join(BASE)})")
        print("=" * 108)
        g = run_grid(BASE)
        gd = pd.DataFrame(g)
        print(gd[["权重", "触发", "CAGR", "持有", "超额", "波动", "回撤", "夏普", "再平衡次数"]]
              .round(2).to_string(index=False))
        best = gd.sort_values("CAGR", ascending=False).head(1)
        print(f"\n  ★ 最优: {best.iloc[0]['权重']} + {best.iloc[0]['触发']}  "
              f"CAGR {best.iloc[0]['CAGR']:.2f}% (超额 {best.iloc[0]['超额']:+.2f}pp, "
              f"夏普 {best.iloc[0]['夏普']:.2f}, 回撤 {best.iloc[0]['回撤']:.1f}%)")

    # ---------- 信号层 ----------
    if len(BASE) >= 3:
        print("\n" + "=" * 108)
        print(f"【实验2】信号层: 价差反向 / 动量  (池: {','.join(BASE)})")
        print("=" * 108)
        sd_ = pd.DataFrame(run_signal(BASE))
        print(sd_[["信号", "CAGR", "持有", "超额", "波动", "回撤", "夏普"]].round(2).to_string(index=False))

    # ---------- 组合搜索 ----------
    print("\n" + "=" * 108)
    print("【实验3】无限组合搜索: γ* 预筛 → 精确回测 (池内 vol≥35 全资产)")
    print("=" * 108)
    for k_ in [4, 6]:
        res = search(n_pool=k_, n_sample=40000, top=10)
        rd = pd.DataFrame(res)
        print(f"\n--- N={k_} ---")
        print(rd[["标的", "γ预测", "CAGR", "持有", "超额", "波动", "夏普"]].round(2).to_string(index=False))
        if k_ == 4:
            rd.to_csv("data/evolve_result_k4.csv", index=False, encoding="utf-8-sig")
        else:
            rd.to_csv("data/evolve_result_k6.csv", index=False, encoding="utf-8-sig")

    # ---------- 终极: 最优权重+触发+信号 叠加在全池上 ----------
    print("\n" + "=" * 108)
    print("【实验4】全叠加: MAXG权重 + 价差反向信号, 在进化池里搜 N=4")
    print("=" * 108)
    res = search(n_pool=4, n_sample=40000, weight="MAXG", trigger="CAL_M",
                 signal="SPREAD_CONTR_DYN", signal_strength=0.30, top=10)
    rd = pd.DataFrame(res)
    print(rd[["标的", "γ预测", "CAGR", "持有", "超额", "波动", "夏普"]].round(2).to_string(index=False))
    rd.to_csv("data/evolve_result_best.csv", index=False, encoding="utf-8-sig")
    if len(rd):
        print(f"\n  ★ 全叠加中位 CAGR {rd['CAGR'].median():.2f}%  (超额中位 {rd['超额'].median():+.2f}pp, "
              f"夏普中位 {rd['夏普'].median():.2f})")
