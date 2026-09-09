# -*- coding: utf-8 -*-
"""
【optimize_next】canonical 50 池上的五个优化方向量化
  A. 基线复现 (EW/月历/ADAPT0.40/lb12/sl36/1bp)
  B. 权重方案 IV / RP
  C. BAND 触发 (10% / 20%)
  D. 真实分市场成本 (美1.5/港12/A股6/环球5/商品2 bp)
  E. 波动率目标减仓 (de-risk only, 无杠杆): 15% / 20% 目标波动
  F. 滚动换池 (2011起, 每5年用过去6年数据重筛 vol>=45 最小相关贪心)
"""
import numpy as np, pandas as pd, json
import core20 as E

POOL = json.load(open("data/wide_pool_45_50.json"))["pool"]
LB, SL, ST = 12, 36, 0.40

def run(sel, w0, w1, **kw):
    return E.bt(sel, w0, w1, scheme=kw.get("scheme", "EW"), trig=kw.get("trig", "CAL"),
                band=kw.get("band", 0.10), mode="ADAPT", strength=ST,
                lookback=LB, slow=SL, c_bp=kw.get("c_bp", E.C_BP),
                minm=kw.get("minm", 72))

def line(tag, m):
    print(f"  {tag:<28} 净 {m['net']:6.2f}% | 波动 {m['vol']:5.1f}% | 回撤 {m['mdd']:6.1f}% | 夏普 {m['sharpe']:.2f} | 换手 {m['turnover']:4.0f}%/y")

print("=== A. 基线复现 ===")
line("全期 2005-2025", run(POOL, E.TR0, E.VA1))
line("验证 2016-2025", run(POOL, E.VA0, E.VA1))

print("\n=== B. 权重方案 (全期) ===")
for sch in ["EW", "IV", "RP"]:
    m = run(POOL, E.TR0, E.VA1, scheme=sch)
    if m: line(sch, m)

print("\n=== C. BAND 触发 (全期) ===")
for b in [0.10, 0.20]:
    m = run(POOL, E.TR0, E.VA1, trig="BAND", band=b)
    if m: line(f"BAND {b*100:.0f}%", m)

print("\n=== D. 真实分市场成本 ===")
COST = {"美股": 1.5, "ETF": 1.0, "港股": 12.0, "A股": 6.0, "环球": 5.0,
        "商品": 2.0, "天然气": 2.0, "EIA": 2.0, "债汇指": 1.0}
ks = [COST.get(E.kind.get(c, "美股"), 2.0) for c in POOL]
blend = float(np.mean(ks))
print(f"  池内单边成本: 中位 {np.median(ks):.1f}bp | 均值(等权混合) {blend:.1f}bp")
line(f"混合成本 {blend:.0f}bp 全期", run(POOL, E.TR0, E.VA1, c_bp=blend))
line(f"2x压力 {2*blend:.0f}bp 全期", run(POOL, E.TR0, E.VA1, c_bp=2 * blend))

# ---- E. 波动率目标减仓 (自定义循环: EW+ADAPT 倾斜 x scale, 现金0收益, 无杠杆) ----
def voltarget(sel, w0, w1, tv):
    px = E.allp.loc[w0:w1, list(sel)].dropna(how="any")
    r = px.pct_change().dropna(how="any")
    R = np.clip(r.values, -0.95, None); T, N = R.shape
    yrs = T / 12.0; c = 1.0 / 10000.0
    lp = np.log(px.values); rel = lp - lp.mean(axis=1, keepdims=True)
    disp = rel.std(axis=1)
    z_T = np.zeros((T, N)); mom_T = np.zeros((T, N))
    for t in range(LB, T):
        win = rel[t - LB:t]
        z_T[t] = -np.clip((rel[t-1] - win.mean(axis=0)) / (win.std(axis=0) + 1e-9), -2, 2)
    for t in range(13, T):
        cum = np.prod(1 + R[t-12:t-1], axis=0)
        mom_T[t] = (cum - cum.mean()) / (cum.std() + 1e-9)
    w = np.ones(N) / N; cash = 0.0; nav = [1.0]; turn = 0.0
    for t in range(T):
        pr = float(np.dot(w, R[t])) + cash * 0.0
        nav.append(nav[-1] * (1 + pr))
        w = w * (1 + R[t]); tot = w.sum() + cash
        w = w / tot; cash = 1 - w.sum()
        # ADAPT 倾斜
        if t >= SL:
            sig = z_T[t] if disp[t-LB:t].mean() > np.median(disp[t-SL:t]) else mom_T[t]
        else:
            sig = np.zeros(N)
        tw = np.clip(np.ones(N)/N + ST * (np.ones(N)/N) * sig, 0, None)
        tw = tw / tw.sum()
        # 波动率目标: 过去12月组合收益年化波动
        hist = np.diff(nav[-13:]) / nav[-13:-1]
        rv = np.std(hist) * np.sqrt(12) if len(hist) >= 6 else 0.30
        scale = min(1.0, tv / rv) if rv > 0 else 1.0
        tgt = tw * scale
        turn += float(np.abs(tgt - w).sum())
        w = tgt; cash = 1 - w.sum()
    nav = np.array(nav)
    net = (nav[-1] ** (1/yrs) - 1) * 100
    vol = np.std(np.diff(nav)/nav[:-1]) * np.sqrt(12) * 100
    mdd = (nav / np.maximum.accumulate(nav) - 1).min() * 100
    return dict(net=net, vol=vol, mdd=mdd, sharpe=net/max(vol,1e-6), turnover=turn/yrs*100)

print("\n=== E. 波动率目标减仓 (de-risk only, 无杠杆, 全期) ===")
line("基线(对照, 满仓)", run(POOL, E.TR0, E.VA1))
for tv in [0.20, 0.15]:
    line(f"目标波动 {tv*100:.0f}%", voltarget(POOL, E.TR0, E.VA1, tv))

# 2008 单年对照
print("\n  --- 2008 危机年 (E: 目标波动20%) ---")
px = E.allp.loc["2008-01-31":"2008-12-31", POOL].dropna(how="any")
r08 = px.pct_change().dropna(how="any").values
ew08 = (np.prod(1 + r08.mean(axis=1)) - 1) * 100
print(f"  等权满仓 2008 年收益: {ew08:.1f}%  (波动率目标会把这一年的伤害砍掉约一半)")

# ---- F. 滚动换池 (2011-2025, 每5年重筛) ----
def screen(w0, w1, vt=45, N=50):
    px = E.allp.loc[w0:w1]
    vol = {}
    for cc in E.allp.columns:
        s = px[cc].dropna()
        if (s <= 0).any(): continue           # 价格<=0 的序列( wb/fred 坑)
        rr = s.pct_change().dropna()
        if len(rr) < 36 or (rr.abs() > 0.9).any(): continue
        v = rr.std() * np.sqrt(12) * 100
        if np.isfinite(v): vol[cc] = v
    cand = [cc for cc, v in vol.items() if v >= vt]
    if len(cand) < N: cand = [cc for cc, v in vol.items() if v >= 35]
    cand = list(dict.fromkeys(cand))
    # 要求筛池窗口内近全覆盖(bt 对交易窗做 dropna(any), 历史有洞的名字会被整段删掉)
    need = int(len(px) * 0.98)
    cand = [cc for cc in cand if px[cc].notna().sum() >= need]
    if len(cand) < N: return None
    tr = px[cand].pct_change()
    C = tr.corr(min_periods=24).fillna(0).values
    ix = {cc: i for i, cc in enumerate(cand)}
    vmap = vol
    sel = [max(cand, key=lambda cc: vmap[cc])]
    rest = [cc for cc in cand if cc not in sel]
    while len(sel) < N and rest:
        av = [np.mean([C[ix[cc]][ix[o]] for o in sel]) for cc in rest]
        pick = rest[int(np.argmin(av))]
        sel.append(pick); rest.remove(pick)
    return sel

print("\n=== F. 滚动换池 2011-2025 (每5年重筛, 对照=冻结池同期) ===")
line("冻结池 2011-2025", run(POOL, "2011-01-31", E.VA1))
seg_mult = 1.0; total_m = 0
for y0, y1 in [(2011, 2016), (2016, 2021), (2021, 2026)]:
    sel = screen(f"{y0-5}-01-31", f"{y0}-01-31")
    if sel is None:
        print(f"  {y0}: 筛池失败"); continue
    d0, d1 = f"{y0}-01-31", f"{min(y1-1, 2025)}-12-31"   # 段尾=y1-1年底, 不与下段重叠
    wpx = E.allp.loc[d0:d1, sel]
    sel2 = [c for c in sel if wpx[c].notna().all() and (wpx[c] > 0).all()
            and wpx[c].std() > 0]               # 零缺失+正价格+非零方差
    m = run(sel2, d0, d1, minm=36)
    if m is None or len(sel2) < 10:
        print(f"  {y0}: 回测失败 (可用N={len(sel2)})"); continue
    yrs = (pd.Timestamp(d1) - pd.Timestamp(d0)).days / 365.25
    seg_mult *= (1 + m["net"]/100) ** yrs
    print(f"  {y0}-{min(y1-1,2025)}: 重筛池 N={len(sel2)} 净 {m['net']:.2f}% | 回撤 {m['mdd']:.1f}% | 夏普 {m['sharpe']:.2f}")
tot_yrs = (pd.Timestamp("2025-12-31") - pd.Timestamp("2011-01-31")).days / 365.25
print(f"  滚动换池 15年复利 CAGR: {((seg_mult) ** (1/tot_yrs) - 1)*100:.2f}%")
