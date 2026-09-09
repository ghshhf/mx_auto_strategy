# -*- coding: utf-8 -*-
"""
【终版: 宽池 N=50 跨行业龙头】—— 用扩充后的候选池重跑

关键假设(待验证): 之前 N 增大收益下降, 是因为候选池太浅(vol>=40 只有48个),
N=50 等于"全取", 被迫纳入高相关标的。若候选池扩到 150+, N=50 应保持高收益。

输出:
  PART1 扩充后候选池规模
  PART2 N 扫描(10/20/30/50/80) × 波动档, 最小相关贪心
  PART3 最优 N=50 配置: 三窗口 + 随机化贪心稳健性 + 逐年
  PART4 与 N=20 的最终对照
"""
import pandas as pd, numpy as np, sys
import core20 as E

rng = np.random.default_rng(555)
print(f"全资产宇宙: {E.allp.shape[1]} 列")


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


# ---------- PART1 ----------
TIERS = {t: dedup(list(E.BASE[E.BASE.vol >= t].index), E.allp) for t in [35, 40, 45, 50]}
print(f"\n{'='*100}")
print("### PART1 扩充后候选池规模")
print(f"{'='*100}")
for t, v in TIERS.items():
    print(f"  vol>={t}: {len(v)} 个")
    if len(v) <= 60:
        print(f"    {list(v)}")

# ---------- PART2 ----------
print(f"\n{'='*100}")
print("### PART2 N 扫描 × 波动档 (最小相关贪心) [验证期=样本外]")
print(f"{'='*100}")
NS = [10, 20, 30, 50, 80]
rows = []
for vt in [35, 40, 45]:
    pool = TIERS[vt]
    if len(pool) < 10:
        continue
    print(f"\n-- vol>={vt} (候选 {len(pool)}) --")
    print(f"{'N':>5}{'全期%':>9}{'训练期%':>10}{'验证期%':>10}{'死拿%':>9}{'超额pp':>9}"
          f"{'波动%':>8}{'回撤%':>9}{'夏普':>7}")
    for N in NS:
        if N > len(pool):
            continue
        sel = greedy(pool, N)
        if sel is None:
            continue
        ma = run(sel, E.TR0, E.VA1)
        mt = run(sel, E.TR0, E.TR1)
        mv = run(sel, E.VA0, E.VA1)
        if not ma:
            continue
        print(f"{N:>5}{ma['net']:>9.2f}{(mt['net'] if mt else np.nan):>10.2f}"
              f"{(mv['net'] if mv else np.nan):>10.2f}{ma['hold']:>9.2f}"
              f"{ma['excess_net']:>+9.2f}{ma['vol']:>8.1f}{ma['mdd']:>9.1f}{ma['sharpe']:>7.2f}")
        rows.append(dict(波动档=vt, N=N, 全期=ma["net"], 训练期=(mt["net"] if mt else np.nan),
                         验证期=(mv["net"] if mv else np.nan), 死拿=ma["hold"],
                         超额=ma["excess_net"], 波动=ma["vol"], 回撤=ma["mdd"],
                         夏普=ma["sharpe"], 标的=",".join(sel)))
        sys.stdout.flush()

pd.DataFrame(rows).to_csv("data/final_wide_scan.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/final_wide_scan.csv")

# ---------- PART3 ----------
print(f"\n{'='*100}")
print("### PART3 最优宽池(N=50 或最大可用): 稳健性检验")
print(f"{'='*100}")
best = max(rows, key=lambda r: r["夏普"])
vt, N = best["波动档"], best["N"]
pool = TIERS[vt]
sel = greedy(pool, N)
print(f"选取: vol>={vt}, N={N} (全期 {best['全期']:.2f}%, 夏普 {best['夏普']:.2f})")
print(f"池内构成: {sel}")
kinds = [E.BASE.loc[c, "kind"] for c in sel if c in E.BASE.index]
print(f"类别分布: {pd.Series(kinds).value_counts().to_dict()}")
R, cols = train_stats(sel)
iu = np.triu_indices(len(sel), 1)
print(f"池内平均相关性: {R[iu].mean():.3f} | 池内平均波动: "
      f"{np.mean([E.BASE.loc[c,'vol'] for c in sel]):.1f}%")

print(f"\n-- 随机化贪心 x40 (topk=3) --")
vs = []
for _ in range(40):
    s = greedy(pool, N, topk=3, rnd=rng)
    if s is None:
        continue
    m = run(s, E.TR0, E.VA1)
    if m:
        vs.append(m)
if vs:
    vn = np.array([v["net"] for v in vs]); vsh = np.array([v["sharpe"] for v in vs])
    ve = np.array([v["excess_net"] for v in vs]); vmd = np.array([v["mdd"] for v in vs])
    print(f"  净CAGR 中位 {np.median(vn):.2f}% | 区间 [{vn.min():.2f}, {vn.max():.2f}]")
    print(f"  超额中位 {np.median(ve):+.2f}pp | 为正占比 {(ve>0).mean()*100:.1f}%")
    print(f"  夏普中位 {np.median(vsh):.2f} | 回撤中位 {np.median(vmd):.1f}%")
    print(f"  >=20% 占比 {(vn>=20).mean()*100:.1f}% | >=25% 占比 {(vn>=25).mean()*100:.1f}%")

print(f"\n-- 逐年收益 --")
px = E.allp.loc[E.TR0:E.VA1, sel].dropna(how="any")
r = px.pct_change().dropna(how="any")
years = sorted(set(r.index.year))
w = np.ones(len(sel)) / len(sel); wh = w.copy()
vr, vh = 1.0, 1.0
nav_r, nav_h = {}, {}
for dt, row in r.iterrows():
    vr *= (1 + float(np.dot(w, row.values)))
    vh *= (1 + float(np.dot(wh, row.values)))
    wh = wh * (1 + row.values); wh = wh / wh.sum()
    w = np.ones(len(sel)) / len(sel)
    nav_r[dt.year], nav_h[dt.year] = vr, vh
pr, ph, win = 1.0, 1.0, 0
tot = 0
print(f"{'年份':<8}{'再平衡%':>11}{'死拿%':>11}{'差pp':>10}")
for y in years:
    if y == years[0]:
        continue
    rr = (nav_r[y] / pr - 1) * 100; hh = (nav_h[y] / ph - 1) * 100
    print(f"{y:<8}{rr:>11.2f}{hh:>11.2f}{rr-hh:>+10.2f}")
    if rr > hh:
        win += 1
    tot += 1
    pr, ph = nav_r[y], nav_h[y]
print(f"\n  跑赢年份: {win}/{tot} ({win/tot*100:.1f}%)")

# ---------- PART4 ----------
print(f"\n{'='*100}")
print("### PART4 N=20 vs N=50(或最大) 最终对照")
print(f"{'='*100}")
print(f"{'波动档':>7}{'N':>6}{'全期%':>9}{'验证期%':>10}{'超额pp':>9}{'波动%':>8}{'回撤%':>9}{'夏普':>7}")
for r in sorted(rows, key=lambda x: (x["波动档"], x["N"])):
    if r["N"] in (20, 30, 50, 80):
        print(f"{int(r['波动档']):>7}{int(r['N']):>6}{r['全期']:>9.2f}{r['验证期']:>10.2f}"
              f"{r['超额']:>+9.2f}{r['波动']:>8.1f}{r['回撤']:>9.1f}{r['夏普']:>7.2f}")
