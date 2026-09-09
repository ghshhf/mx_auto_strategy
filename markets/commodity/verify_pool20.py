# -*- coding: utf-8 -*-
"""
【验证 vol>=40 / N=20 最小相关贪心池 的 28.58% 是否稳健】

1) 输出池子构成(看是否真跨行业, 还是集中在单一板块)
2) 子期检验: 21年切成 7 段 3 年期, 看每段是否都正
3) 随机化贪心: 每步从"最不相关 top-k"里随机选 -> 生成 M 个变体池
   (检验是"贪心策略本身"稳健, 还是单次贪心碰巧)
4) 对照: 该池 vs 随机池 vs 全池 的逐年表现
"""
import pandas as pd, numpy as np, sys
import core20 as E

rng = np.random.default_rng(31337)


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


POOL = dedup(list(E.BASE[E.BASE.vol >= 40].index), E.allp)
print(f"vol>=40 候选池: {len(POOL)} 个")


def greedy(pool, N, topk=1, rnd=None):
    """topk=1 即确定性贪心; topk>1 为随机化贪心(每步从最不相关 topk 中随机选)"""
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


# ---------- 1) 确定性贪心池构成 ----------
N = 20
sel = greedy(POOL, N)
print(f"\n{'='*100}")
print(f"### 1) 最小相关贪心 N={N} 池构成")
print(f"{'='*100}")
info = []
for c in sel:
    info.append((c, E.BASE.loc[c, "vol"], E.BASE.loc[c, "cagr"], E.BASE.loc[c, "kind"]))
for c, v, g, k in info:
    print(f"  {c:<14} 波动 {v:>6.1f}%  训练期CAGR {g:>7.2f}%  [{k}]")
print(f"\n  类别分布: {pd.Series([x[3] for x in info]).value_counts().to_dict()}")
print(f"  池内平均波动: {np.mean([x[1] for x in info]):.1f}%")

# 池内平均相关性
R, cols = train_stats(sel)
iu = np.triu_indices(len(sel), 1)
print(f"  池内两两相关性均值(训练期): {R[iu].mean():.3f}")

m_all = E.bt(sel, E.TR0, E.VA1, scheme="EW", trig="CAL", mode="ADAPT", strength=0.40, lookback=12, slow=36)
print(f"\n  全期21年: 净CAGR {m_all['net']:.2f}% | 死拿 {m_all['hold']:.2f}% | 超额 {m_all['excess_net']:+.2f}pp"
      f" | 波动 {m_all['vol']:.1f}% | 回撤 {m_all['mdd']:.1f}% | 夏普 {m_all['sharpe']:.2f}")

# ---------- 2) 子期检验 ----------
# NOTE: bt() 内部要求 len(px)>=72 月, 故子期窗口不能短于 6 年 -> 改用 7 年 3 段
print(f"\n{'='*100}")
print("### 2) 子期检验 (21年切成3段, 每段7年; bt下限72月故不能用3年段)")
print(f"{'='*100}")
print(f"{'子期':<16}{'净CAGR':>10}{'死拿':>10}{'超额pp':>10}{'回撤%':>10}")
pos = 0
segs = [("2005-2011", "2005-01-31", "2011-12-31"),
        ("2012-2018", "2012-01-31", "2018-12-31"),
        ("2019-2025", "2019-01-31", "2025-12-31")]
for sname, a, b in segs:
    m = E.bt(sel, a, b, scheme="EW", trig="CAL", mode="ADAPT", strength=0.40, lookback=12, slow=36)
    if m is None:
        print(f"{sname:<16}  数据不足")
        continue
    flag = "OK" if m["excess_net"] > 0 else "负"
    if m["excess_net"] > 0:
        pos += 1
    print(f"{sname:<16}{m['net']:>10.2f}{m['hold']:>10.2f}{m['excess_net']:>+10.2f}"
          f"{m['mdd']:>10.1f}  {flag}")
print(f"\n  超额为正的子期: {pos}/{len(segs)}")

# 2b) 逐年收益(用全期净值切年, 绕开 bt 的 72 月下限)
print(f"\n{'='*100}")
print("### 2b) 逐年收益 (池 vs 等权死拿基准)")
print(f"{'='*100}")
px = E.allp.loc[E.TR0:E.VA1, sel].dropna(how="any")
r = px.pct_change().dropna(how="any")
years = sorted(set(r.index.year))
print(f"{'年份':<8}{'再平衡%':>11}{'死拿%':>11}{'差pp':>10}")
w = np.ones(len(sel)) / len(sel)
nav_r, nav_h = {r.index[0].year: 1.0}, {r.index[0].year: 1.0}
vr, vh = 1.0, 1.0
wh = np.ones(len(sel)) / len(sel)
for dt, row in r.iterrows():
    y = dt.year
    vr *= (1 + float(np.dot(w, row.values)))
    vh *= (1 + float(np.dot(wh, row.values)))
    wh = wh * (1 + row.values); wh = wh / wh.sum()
    w = np.ones(len(sel)) / len(sel)
    nav_r[y], nav_h[y] = vr, vh
prev_r = prev_h = 1.0
for y in years:
    if y == years[0]:
        continue
    rr = (nav_r[y] / prev_r - 1) * 100
    hh = (nav_h[y] / prev_h - 1) * 100
    print(f"{y:<8}{rr:>11.2f}{hh:>11.2f}{rr-hh:>+10.2f}")
    prev_r, prev_h = nav_r[y], nav_h[y]

# ---------- 3) 随机化贪心稳健性 ----------
print(f"\n{'='*100}")
print("### 3) 随机化贪心稳健性 (每步从最不相关 top-3 中随机选, 生成 40 个变体池)")
print(f"{'='*100}")
variants = []
for i in range(40):
    s = greedy(POOL, N, topk=3, rnd=rng)
    if s is None:
        continue
    m = E.bt(s, E.TR0, E.VA1, scheme="EW", trig="CAL", mode="ADAPT", strength=0.40, lookback=12, slow=36)
    if m:
        variants.append(m)
if variants:
    vn = np.array([v["net"] for v in variants])
    vv = np.array([v["vol"] for v in variants])
    vs = np.array([v["sharpe"] for v in variants])
    ve = np.array([v["excess_net"] for v in variants])
    print(f"  变体数 {len(vn)}")
    print(f"  净CAGR: 中位 {np.median(vn):.2f}% | 均值 {vn.mean():.2f}% | "
          f"区间 [{vn.min():.2f}, {vn.max():.2f}]")
    print(f"  超额pp: 中位 {np.median(ve):+.2f} | 为正占比 {(ve>0).mean()*100:.1f}%")
    print(f"  波动:   中位 {np.median(vv):.1f}% | 夏普中位 {np.median(vs):.2f}")
    print(f"  >=20% 占比: {(vn>=20).mean()*100:.1f}% | >=25% 占比: {(vn>=25).mean()*100:.1f}%")

# 对照组: 纯随机池 40 个
rnds = []
for i in range(40):
    s = list(rng.choice(POOL, N, replace=False))
    m = E.bt(s, E.TR0, E.VA1, scheme="EW", trig="CAL", mode="ADAPT", strength=0.40, lookback=12, slow=36)
    if m:
        rnds.append(m["net"])
if rnds:
    rnds = np.array(rnds)
    print(f"\n  [对照] 纯随机 N=20 池 x40: 中位 {np.median(rnds):.2f}% | "
          f"区间 [{rnds.min():.2f}, {rnds.max():.2f}] | >=20%占比 {(rnds>=20).mean()*100:.1f}%")

# ---------- 4) N 扫描(贪心, 扩大候选后再看) ----------
print(f"\n{'='*100}")
print("### 4) 最小相关贪心: N 扫描 (当前候选池规模下的天花板)")
print(f"{'='*100}")
print(f"{'N':>5}{'全期%':>9}{'验证期%':>10}{'死拿%':>9}{'超额pp':>9}{'波动%':>8}{'回撤%':>9}{'夏普':>7}")
rows = []
for N2 in [10, 15, 20, 25, 30, 40, min(48, len(POOL))]:
    if N2 > len(POOL):
        continue
    s = greedy(POOL, N2)
    if s is None:
        continue
    ma = E.bt(s, E.TR0, E.VA1, scheme="EW", trig="CAL", mode="ADAPT", strength=0.40, lookback=12, slow=36)
    mv = E.bt(s, E.VA0, E.VA1, scheme="EW", trig="CAL", mode="ADAPT", strength=0.40, lookback=12, slow=36)
    if not ma:
        continue
    print(f"{N2:>5}{ma['net']:>9.2f}{(mv['net'] if mv else np.nan):>10.2f}{ma['hold']:>9.2f}"
          f"{ma['excess_net']:>+9.2f}{ma['vol']:>8.1f}{ma['mdd']:>9.1f}{ma['sharpe']:>7.2f}")
    rows.append(dict(N=N2, 全期=ma["net"], 验证期=(mv["net"] if mv else np.nan),
                     死拿=ma["hold"], 超额=ma["excess_net"], 波动=ma["vol"],
                     回撤=ma["mdd"], 夏普=ma["sharpe"], 标的=",".join(s)))
pd.DataFrame(rows).to_csv("data/verify_pool20.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/verify_pool20.csv")
