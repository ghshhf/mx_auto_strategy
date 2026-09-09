# -*- coding: utf-8 -*-
"""
【50 个跨行业宽池】—— 回答用户: "8个股票怎么能叫组合? 各行各业龙头凑起来50个"

PART1 全池极限: 把整个波动档的候选全部买下(不挑), 看 N 拉满能到多少
PART2 分散选股: 用"最小相关贪心"(每次加入与已选池平均相关性最低的标的)
               构建真正的跨行业 50 池, 对比随机 50 池
PART3 三窗口验证: 训练期 / 验证期(样本外) / 全期
"""
import pandas as pd, numpy as np, sys
import core20 as E

rng = np.random.default_rng(4242)


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


TIERS = {}
for t in [30, 35, 40, 45]:
    TIERS[t] = dedup(list(E.BASE[E.BASE.vol >= t].index), E.allp)

print("=== 去重后候选池规模 ===")
for t, v in TIERS.items():
    print(f"  vol>={t}: {len(v)} 个")

WINDOWS = [("训练期05-15", E.TR0, E.TR1), ("验证期16-25", E.VA0, E.VA1), ("全期21年", E.TR0, E.VA1)]
rows = []

# ============================================================
# PART1: 全池买下(不挑, 该波动档全部纳入)
# ============================================================
print(f"\n{'='*104}")
print("### PART1 全池买下 —— 该波动档候选全部纳入(等权月历+自适应)")
print(f"{'='*104}")
print(f"{'波动档':>8}{'N':>5}{'窗口':<12}{'净CAGR':>9}{'死拿':>9}{'超额pp':>9}{'波动%':>8}{'回撤%':>9}{'夏普':>7}")
for vt in [30, 35, 40, 45]:
    pool = TIERS[vt]
    if len(pool) < 4:
        continue
    for wname, w0, w1 in WINDOWS:
        m = E.bt(pool, w0, w1, scheme="EW", trig="CAL", mode="ADAPT",
                 strength=0.40, lookback=12, slow=36)
        if m is None:
            print(f"{vt:>8}{len(pool):>5}{wname:<12}  数据不足")
            continue
        rows.append(dict(类型="全池", 波动档=vt, N=len(pool), 窗口=wname,
                         净CAGR=m["net"], 死拿=m["hold"], 超额pp=m["excess_net"],
                         波动=m["vol"], 回撤=m["mdd"], 夏普=m["sharpe"]))
        print(f"{vt:>8}{len(pool):>5}{wname:<12}{m['net']:>9.2f}{m['hold']:>9.2f}"
              f"{m['excess_net']:>+9.2f}{m['vol']:>8.1f}{m['mdd']:>9.1f}{m['sharpe']:>7.2f}")
    sys.stdout.flush()

# ============================================================
# PART2: 最小相关贪心 —— 构建真正的跨行业分散池
# ============================================================
print(f"\n{'='*104}")
print("### PART2 最小相关贪心选池 vs 随机池 (用训练期相关性, 避免前视)")
print(f"{'='*104}")


def corr_matrix(cols, w0, w1):
    px = E.allp.loc[w0:w1, cols].dropna(how="any")
    r = px.pct_change().dropna(how="any")
    return r.corr().values, list(px.columns)


def greedy_decorr(pool, N, w0, w1):
    """每次加入与已选集合平均相关性最低的标的(用训练期数据)"""
    C, cols = corr_matrix(pool, w0, w1)
    if len(cols) < N:
        return None
    idx = {c: i for i, c in enumerate(cols)}
    # 起点: 训练期波动最高的
    vols = {c: E.BASE.loc[c, "vol"] for c in cols if c in E.BASE.index}
    first = max(vols, key=vols.get)
    sel = [first]
    for _ in range(N - 1):
        rest = [c for c in cols if c not in sel]
        if not rest:
            break
        best, bestc = None, 1e9
        for c in rest:
            av = float(np.mean([C[idx[c], idx[s]] for s in sel]))
            if av < bestc:
                bestc, best = av, c
        sel.append(best)
    return sel


for vt in [30, 35]:
    pool = TIERS[vt]
    for N in [20, 30, 50]:
        if N > len(pool):
            continue
        for tag, sel in [("贪心分散", greedy_decorr(pool, N, E.TR0, E.TR1)),
                         ("随机", list(rng.choice(pool, N, replace=False)))]:
            if sel is None:
                continue
            for wname, w0, w1 in WINDOWS:
                m = E.bt(sel, w0, w1, scheme="EW", trig="CAL", mode="ADAPT",
                         strength=0.40, lookback=12, slow=36)
                if m is None:
                    continue
                rows.append(dict(类型=tag, 波动档=vt, N=N, 窗口=wname,
                                 净CAGR=m["net"], 死拿=m["hold"], 超额pp=m["excess_net"],
                                 波动=m["vol"], 回撤=m["mdd"], 夏普=m["sharpe"]))
                if wname == "全期21年":
                    print(f"  vol>={vt} N={N:>3} {tag:<8} | 全期 {m['net']:>6.2f}% | 死拿 {m['hold']:>6.2f}% "
                          f"| 超额 {m['excess_net']:>+6.2f}pp | 波动 {m['vol']:>5.1f}% | "
                          f"回撤 {m['mdd']:>6.1f}% | 夏普 {m['sharpe']:>5.2f}")
        sys.stdout.flush()

# ============================================================
# PART3: 50 池的完整三窗口 + 各种模式对照
# ============================================================
print(f"\n{'='*104}")
print("### PART3 N=50 跨行业池: 三窗口 × 模式对照 (验证期=样本外)")
print(f"{'='*104}")
pool = TIERS[35] if len(TIERS[35]) >= 50 else TIERS[30]
N = min(50, len(pool))
sel50 = greedy_decorr(pool, N, E.TR0, E.TR1)
print(f"50 池构成(vol>={35 if len(TIERS[35])>=50 else 30}, N={N}):")
print("  " + ", ".join(sel50))
kinds = [E.BASE.loc[c, "kind"] for c in sel50 if c in E.BASE.index]
print(f"  类别分布: {pd.Series(kinds).value_counts().to_dict()}")
print()
print(f"{'模式':<16}{'窗口':<12}{'净CAGR':>9}{'死拿':>9}{'超额pp':>9}{'波动%':>8}{'回撤%':>9}{'夏普':>7}")
for mode in ["NONE", "CONTR", "MOM", "ADAPT"]:
    for wname, w0, w1 in WINDOWS:
        m = E.bt(sel50, w0, w1, scheme="EW", trig="CAL", mode=mode,
                 strength=0.40, lookback=12, slow=36)
        if m is None:
            continue
        rows.append(dict(类型=f"50池-{mode}", 波动档=35, N=N, 窗口=wname,
                         净CAGR=m["net"], 死拿=m["hold"], 超额pp=m["excess_net"],
                         波动=m["vol"], 回撤=m["mdd"], 夏普=m["sharpe"]))
        print(f"{mode:<16}{wname:<12}{m['net']:>9.2f}{m['hold']:>9.2f}{m['excess_net']:>+9.2f}"
              f"{m['vol']:>8.1f}{m['mdd']:>9.1f}{m['sharpe']:>7.2f}")
    sys.stdout.flush()

out = pd.DataFrame(rows)
out.to_csv("data/wide50_result.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/wide50_result.csv")
