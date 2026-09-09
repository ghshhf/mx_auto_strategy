# -*- coding: utf-8 -*-
"""40年长窗口压力测试: 只用≥40年历史的龙头, 前20年筛池, 后段真实样本外.
   复刻 core20.bt 内核, 但运行在自定义长面板上(非 2005+ 对齐宇宙)."""
import pandas as pd, numpy as np
np.seterr(all="ignore")

C_BP = 1.0  # 美股交易成本 1bp

def load_long(f):
    d = pd.read_csv(f, index_col=0, parse_dates=True).apply(pd.to_numeric, errors="coerce")
    d.columns = [c.lstrip("\ufeff") for c in d.columns]
    d = d[~d.index.duplicated(keep="last")]
    return d.resample("ME").last()

# 只取长历史面板(美股 1969+ / 全球 1973+)
panels = [load_long("data/us_universe_weekly_adjclose.csv"),
          load_long("data/yahoo_global_weekly_adjclose.csv")]
PX = pd.concat(panels, axis=1)
PX = PX.loc[:, ~PX.columns.duplicated()]

# 只保留 ≥40 年历史的列
keep = []
for c in PX.columns:
    s = PX[c].dropna()
    if len(s) < 10:
        continue
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    if yrs >= 40:
        keep.append(c)
PX = PX[keep].sort_index()
print(f"≥40年历史龙头: {PX.shape[1]} 只 | 区间 {PX.index[0]:%Y-%m} -> {PX.index[-1]:%Y-%m} "
      f"跨 {(PX.index[-1]-PX.index[0]).days/365.25:.0f} 年")

# 切训练/测试(前20年筛池, 后段真实样本外)
TR0, TR1 = "1973-01-31", "1993-12-31"   # 训练 21y
VA0 = "1994-01-31"                       # 测试起点(样本外)
VA1 = PX.index[-1].strftime("%Y-%m-%d")

# 训练期波动: 每只资产用自己的非空序列(不要求全面板对齐)
tr_win = PX.loc[TR0:TR1]
vol = {}
for c in PX.columns:
    s = tr_win[c].dropna()
    r = s.pct_change().dropna()
    if len(r) < 60:
        continue
    if (r.abs() > 0.9).any():
        continue
    vol[c] = r.std() * np.sqrt(12) * 100
cand = [c for c, v in vol.items() if v >= 45]
print(f"训练期 vol>=45 候选: {len(cand)} 只 (全候选 {len(vol)})")

# 最小相关贪心选池(相关矩阵用候选集对齐面板)
tr_px = tr_win[cand].dropna(how="any")
tr_ret = tr_px.pct_change().dropna()
corr = tr_ret.corr().fillna(0).values
idx = {c: i for i, c in enumerate(cand)}
def greedy(N, topk=3, rnd=None):
    order = sorted(cand, key=lambda c: -vol[c])
    sel = []
    pool = list(order)
    while len(sel) < N and pool:
        if rnd is not None:
            top = pool[:max(topk, min(len(pool), 8))]
            pick = rnd.choice(top)
        else:
            top = pool[:max(topk, len(pool))]
            # 选与已选平均相关最低的
            best, bestc = None, None
            for c in top:
                if not sel:
                    best, bestc = -1, c; break
                ci = idx[c]; ac = np.mean([corr[ci][idx[o]] for o in sel])
                if best is None or ac < best:
                    best, bestc = ac, c
            pick = bestc
        sel.append(pick); pool.remove(pick)
    return sel

# ---- 复刻 bt 内核(对自定义 px 运行) ----
def bt(px, w0, w1, scheme="EW", trig="CAL", band=0.10, mode="ADAPT",
       strength=0.40, c_bp=C_BP, lookback=24, slow=60):
    px = px.loc[w0:w1].dropna(how="any")
    if len(px) < 72:
        return None
    r = px.pct_change().dropna(how="any")
    if len(r) < 60:
        return None
    R = np.clip(r.values, -0.95, None)
    T, N = R.shape
    yrs = T / 12.0
    c = c_bp / 10000.0
    w_eq = np.ones(N) / N
    w_iv = np.zeros((T, N))
    sd24 = pd.DataFrame(R).rolling(24, min_periods=12).std().values
    sd24 = np.where(np.isfinite(sd24) & (sd24 > 1e-8), sd24, np.nan)
    for t in range(T):
        v = sd24[t]
        if np.all(np.isfinite(v)):
            iv = 1.0 / v; w_iv[t] = iv / iv.sum()
        else:
            w_iv[t] = w_eq
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
    nav = np.zeros(T + 1); nav[0] = 1.0
    turn_sum, n_reb = 0.0, 0
    for t in range(T):
        wd = w * (1 + R[t]); wd = wd / (wd.sum() + 1e-12)
        tgt = w_eq if scheme == "EW" else (w_iv[t] if scheme == "IV" else w_eq)
        if mode == "ADAPT":
            sig = z_T[t] if (t >= slow and disp[t - lookback:t].mean() > np.median(disp[t - slow:t])) else mom_T[t] if t >= 13 else np.zeros(N)
        else:
            sig = np.zeros(N)
        if np.any(sig != 0):
            tw = np.clip(tgt + strength * tgt * sig, 0, None)
            tgt = tw / (tw.sum() + 1e-12)
        do = True
        if trig == "BAND" and np.max(np.abs(wd - tgt)) < band:
            do = False
        gr = float(np.dot(w, R[t])); val *= (1 + gr)
        if do:
            turn = float(np.abs(tgt - wd).sum()); turn_sum += turn; n_reb += 1
            val *= (1 - turn * c); w = tgt
        else:
            w = wd
        nav[t + 1] = val
    if not np.isfinite(val) or val <= 0:
        return None
    rc = val ** (1 / yrs) - 1
    g = (px.iloc[-1] / px.iloc[0]).values
    if np.any(g <= 0):
        return None
    hc = float(g.mean()) ** (1 / yrs) - 1
    nr = np.diff(nav) / nav[:-1]
    v_ = float(np.std(nr) * np.sqrt(12) * 100)
    mdd = float((nav / np.maximum.accumulate(nav) - 1).min() * 100)
    return dict(net=rc*100, hold=hc*100, excess=(rc-hc)*100, vol=v_,
                mdd=mdd, sharpe=rc*100/max(v_,1e-6),
                turnover=turn_sum/yrs*100, n_reb=n_reb, mult=val)

N = min(50, len(cand))
pool = greedy(N)
print(f"\n=== 选定池 N={len(pool)} (vol>=45 最小相关贪心) ===")
for c in pool:
    print(f"  {c:<12} 训练期vol={vol[c]:.0f}%")
# 成分来源
def src(c):
    return "美股" if c in PX.columns and load_long.__name__ else "?"
from collections import Counter
print("池内平均训练期波动: %.1f%%" % np.mean([vol[c] for c in pool]))

# 全期(含训练段) 与 纯样本外 两段
print("\n=== 全期回测 %s -> %s ===" % (PX.index[0].strftime("%Y-%m"), VA1))
m = bt(PX[pool], PX.index[0].strftime("%Y-%m-%d"), VA1)
print(f"  再平衡净CAGR: {m['net']:.2f}% | 死拿等权: {m['hold']:.2f}% | 超额: {m['excess']:+.2f}pp")
print(f"  夏普: {m['sharpe']:.2f} | 波动: {m['vol']:.1f}% | 回撤: {m['mdd']:.1f}% | 终值倍数: {m['mult']:.1f}x | 年化换手: {m['turnover']:.0f}%")

print(f"\n=== 纯样本外(真实没见过) {VA0} -> {VA1} ===")
m2 = bt(PX[pool], VA0, VA1)
print(f"  再平衡净CAGR: {m2['net']:.2f}% | 死拿等权: {m2['hold']:.2f}% | 超额: {m2['excess']:+.2f}pp")
print(f"  夏普: {m2['sharpe']:.2f} | 终值倍数: {m2['mult']:.1f}x | 回撤: {m2['mdd']:.1f}%")

# 稳健性: 随机化贪心 x20
print("\n=== 随机化贪心 x20 稳健性 (纯样本外) ===")
rng = np.random.default_rng(40)
nets = []
for _ in range(20):
    s = greedy(N, topk=4, rnd=rng)
    mm = bt(PX[s], VA0, VA1)
    if mm:
        nets.append(mm['net'])
nets = np.array(nets)
print(f"  样本外净CAGR 中位 {np.median(nets):.2f}% | 区间 [{nets.min():.2f}, {nets.max():.2f}]")
print(f"  >=20% 占比: {(nets>=20).mean()*100:.0f}% | >=18% 占比: {(nets>=18).mean()*100:.0f}%")
