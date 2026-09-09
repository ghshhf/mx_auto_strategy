# -*- coding: utf-8 -*-
"""
固化验证: ~50 跨行业龙头宽池 (vol>=45, N=50, 最小相关贪心)
目标: 确认样本外(2016-2025)净 CAGR 稳定 >=20%, 且非单一贪心巧合。
"""
import numpy as np, pandas as pd, sys
import core20 as E

rng = np.random.default_rng(2026)


def dedup(cols, px):
    keep = []
    for c in cols:
        dup = False
        for k in keep:
            a, b = px[c], px[k]
            m = a.notna() & b.notna()
            if m.sum() > 60:
                aa, bb = a[m].values, b[m].values
                if np.std(aa) > 0 and np.std(bb) > 0 and np.corrcoef(aa, bb)[0, 1] > 0.999:
                    dup = True
                    break
        if not dup:
            keep.append(c)
    return keep


def train_stats(cols):
    px = E.allp.loc[E.TR0:E.TR1, cols].dropna(how="any")
    r = px.pct_change().dropna(how="any")
    return r.corr().values, list(px.columns)


def greedy(pool, N, topk=1, rnd=None):
    R, cols = train_stats(pool)
    if len(cols) < N:
        return None
    idx = {c: i for i, c in enumerate(cols)}
    first = max(cols, key=lambda c: E.BASE.loc[c, "vol"])
    chosen = [first]
    for _ in range(N - 1):
        rest = [c for c in cols if c not in chosen]
        if not rest:
            break
        av = np.array([np.mean([R[idx[c], idx[s]] for s in chosen]) for c in rest])
        if topk <= 1:
            pick = rest[int(np.argmin(av))]
        else:
            cand = np.argsort(av)[:min(topk, len(rest))]
            pick = rest[int(rnd.choice(cand))]
        chosen.append(pick)
    return chosen


def run(sel, w0, w1, mode="ADAPT", strength=0.40):
    return E.bt(sel, w0, w1, scheme="EW", trig="CAL", mode=mode,
                strength=strength, lookback=12, slow=36)


VT = 45
N = 50
pool = dedup(list(E.BASE[E.BASE.vol >= VT].index), E.allp)
print(f"vol>={VT} 去重候选: {len(pool)} (全宇宙 BASE={len(E.BASE)})")

sel = greedy(pool, N)
print(f"\n=== 选定宽池 (vol>={VT}, N={N}) 全期净CAGR 验证 ===")
ma = run(sel, E.TR0, E.VA1)
mt = run(sel, E.TR0, E.TR1)
mv = run(sel, E.VA0, E.VA1)
print(f"全期  2005-2025: 净 {ma['net']:.2f}% | 死拿 {ma['hold']:.2f}% | 超额 {ma['excess_net']:+.2f}pp | 波动 {ma['vol']:.1f}% | 回撤 {ma['mdd']:.1f}% | 夏普 {ma['sharpe']:.2f} | 换手/年 {ma['turnover']:.0f}%")
print(f"训练  2005-2015: 净 {mt['net']:.2f}%")
print(f"验证  2016-2025: 净 {mv['net']:.2f}% | 死拿 {mv['hold']:.2f}% | 超额 {mv['excess_net']:+.2f}pp | 波动 {mv['vol']:.1f}% | 回撤 {mv['mdd']:.1f}% | 夏普 {mv['sharpe']:.2f}")

# 成分明细
print(f"\n=== 池内 {len(sel)} 个标的 ===")
rows = []
for c in sel:
    b = E.BASE.loc[c]
    rows.append((c, b["kind"], round(b["vol"], 1), round(b["cagr"], 1)))
df = pd.DataFrame(rows, columns=["标的", "类别", "波动%", "训练期CAGR%"])
print(df.to_string(index=False))
print("\n类别分布:", df["类别"].value_counts().to_dict())

R, cols = train_stats(sel)
iu = np.triu_indices(len(sel), 1)
print(f"池内平均相关性: {R[iu].mean():.3f}")

# 随机化贪心 x40 稳健性 (每个池同时算全期 + 验证期)
print(f"\n=== 随机化贪心 x40 (topk=3) 稳健性 ===")
vs, vval = [], []
for _ in range(40):
    s = greedy(pool, N, topk=3, rnd=rng)
    if s is None:
        continue
    m = run(s, E.TR0, E.VA1)
    mv = run(s, E.VA0, E.VA1)
    if m and mv:
        vs.append(m); vval.append(mv)
vn = np.array([v["net"] for v in vs]); vsh = np.array([v["sharpe"] for v in vs])
ve = np.array([v["excess_net"] for v in vs]); vmd = np.array([v["mdd"] for v in vs])
vv = np.array([v["net"] for v in vval])
print(f"全期净CAGR  中位 {np.median(vn):.2f}% | 区间 [{vn.min():.2f}, {vn.max():.2f}]")
print(f"验证期净CAGR 中位 {np.median(vv):.2f}% | 区间 [{vv.min():.2f}, {vv.max():.2f}]")
print(f"超额(全期)中位 {np.median(ve):+.2f}pp | 为正占比 {(ve>0).mean()*100:.1f}%")
print(f"夏普中位 {np.median(vsh):.2f} | 回撤中位 {np.median(vmd):.1f}%")
print(f">=20% 占比 {(vn>=20).mean()*100:.1f}% | >=25% 占比 {(vn>=25).mean()*100:.1f}%")

# 逐年 (验证期)
print(f"\n=== 验证期逐年 (2016-2025) ===")
px = E.allp.loc[E.VA0:E.VA1, sel].dropna(how="any")
r = px.pct_change().dropna(how="any")
years = sorted(set(r.index.year))
w = np.ones(len(sel)) / len(sel); wh = w.copy()
vr, vh = 1.0, 1.0; nav_r, nav_h = {}, {}
for dt, row in r.iterrows():
    vr *= (1 + float(np.dot(w, row.values)))
    vh *= (1 + float(np.dot(wh, row.values)))
    wh = wh * (1 + row.values); wh = wh / wh.sum()
    w = np.ones(len(sel)) / len(sel)
    nav_r[dt.year], nav_h[dt.year] = vr, vh
pr, ph, win, tot = 1.0, 1.0, 0, 0
print(f"{'年份':<8}{'再平衡%':>11}{'死拿%':>11}{'差pp':>10}")
for y in years:
    if y == years[0]:
        continue
    rr = (nav_r[y] / pr - 1) * 100; hh = (nav_h[y] / ph - 1) * 100
    print(f"{y:<8}{rr:>11.2f}{hh:>11.2f}{rr-hh:>+10.2f}")
    if rr > hh: win += 1
    tot += 1; pr, ph = nav_r[y], nav_h[y]
print(f"\n跑赢年份: {win}/{tot} ({win/tot*100:.1f}%)")

df.to_csv("data/wide50_pool_composition.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/wide50_pool_composition.csv")
