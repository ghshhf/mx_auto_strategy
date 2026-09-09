# -*- coding: utf-8 -*-
"""
【选池算法对比】—— 怎样从候选里挑出 N 个"跨行业龙头"最好?

策略:
  A RANDOM        随机(基线)
  B TOPVOL        按训练期波动取最高 N 个
  C GREEDY_CORR   最小相关贪心(每次加入与已选平均相关性最低的)
  D GREEDY_GAMMA  最大化 gamma* 贪心(直接优化再平衡收益的理论目标)
  E BALANCED      类别配额(美股/港股/商品/债汇 按比例)+ 组内贪心

用训练期(2005-2015)数据选池 -> 验证期(2016-2025)样本外检验, 无前视。
"""
import pandas as pd, numpy as np, sys
import core20 as E

rng = np.random.default_rng(777)


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


TIERS = {t: dedup(list(E.BASE[E.BASE.vol >= t].index), E.allp) for t in [30, 35, 40, 45]}
print("=== 候选池 ===")
for t, v in TIERS.items():
    print(f"  vol>={t}: {len(v)}")

# 训练期协方差(选池唯一依据)
def train_stats(cols):
    px = E.allp.loc[E.TR0:E.TR1, cols].dropna(how="any")
    r = px.pct_change().dropna(how="any")
    return r.cov().values * 12, list(px.columns)     # 年化协方差


def gamma_star(C, idxs):
    """等权 N 资产的 Fernholz gamma* = 0.5*(sum w_i var_i - var_p)"""
    n = len(idxs)
    if n < 2:
        return 0.0
    sub = C[np.ix_(idxs, idxs)]
    avg_var = np.mean(np.diag(sub))
    port_var = sub.sum() / (n * n)
    return 0.5 * (avg_var - port_var)


def sel_random(pool, N):
    return list(rng.choice(pool, N, replace=False))


def sel_topvol(pool, N):
    return list(pd.Series({c: E.BASE.loc[c, "vol"] for c in pool}).sort_values(ascending=False).index[:N])


def sel_greedy_corr(pool, N):
    C, cols = train_stats(pool)
    if len(cols) < N:
        return None
    idx = {c: i for i, c in enumerate(cols)}
    d = np.sqrt(np.diag(C)); d[d <= 0] = 1e-9
    R = C / np.outer(d, d)
    first = max(cols, key=lambda c: E.BASE.loc[c, "vol"])
    chosen = [first]
    for _ in range(N - 1):
        rest = [c for c in cols if c not in chosen]
        if not rest:
            break
        av = {c: float(np.mean([R[idx[c], idx[s]] for s in chosen])) for c in rest}
        chosen.append(min(av, key=av.get))
    return chosen


def sel_greedy_gamma(pool, N):
    """贪心: 每步加入使 gamma* 增量最大的候选"""
    C, cols = train_stats(pool)
    if len(cols) < N:
        return None
    idx = {c: i for i, c in enumerate(cols)}
    # 起点: 训练期波动最高
    first = max(cols, key=lambda c: E.BASE.loc[c, "vol"])
    chosen = [first]
    for _ in range(N - 1):
        rest = [c for c in cols if c not in chosen]
        if not rest:
            break
        best, bg = None, -1e18
        ci = [idx[c] for c in chosen]
        for c in rest:
            g = gamma_star(C, ci + [idx[c]])
            if g > bg:
                bg, best = g, c
        chosen.append(best)
    return chosen


def sel_balanced(pool, N):
    """类别配额: 按各候选类别规模加权分配名额, 组内用最小相关贪心"""
    kinds = pd.Series({c: E.BASE.loc[c, "kind"] for c in pool})
    quota = {}
    for k, cnt in kinds.value_counts().items():
        quota[k] = max(1, int(round(N * cnt / len(kinds))))
    # 修正总数
    while sum(quota.values()) > N:
        k = max(quota, key=quota.get); quota[k] -= 1
    while sum(quota.values()) < N:
        k = max([q for q in quota], key=lambda x: quota[x]); quota[k] += 1
    out = []
    for k, q in quota.items():
        sub = [c for c in pool if kinds[c] == k]
        if q >= len(sub):
            out += sub
        else:
            s = sel_greedy_corr(sub, q) if q >= 2 else [max(sub, key=lambda c: E.BASE.loc[c, "vol"])]
            out += (s or sub[:q])
    return out[:N]


STRATS = [("A 随机", sel_random), ("B 波动最高", sel_topvol),
          ("C 最小相关贪心", sel_greedy_corr), ("D 最大γ*贪心", sel_greedy_gamma),
          ("E 类别均衡", sel_balanced)]

WINDOWS = [("训练期05-15", E.TR0, E.TR1), ("验证期16-25", E.VA0, E.VA1), ("全期21年", E.TR0, E.VA1)]
rows = []

for vt in [30, 35, 40]:
    pool = TIERS[vt]
    print(f"\n{'='*108}")
    print(f"### 波动档 vol>={vt}  (候选 {len(pool)})   [验证期=样本外]")
    print(f"{'='*108}")
    for N in [20, 30, 50]:
        if N > len(pool):
            continue
        print(f"\n-- N={N} --")
        print(f"{'策略':<16}{'训练期%':>9}{'验证期%':>9}{'全期%':>9}{'死拿%':>8}{'超额pp':>9}"
              f"{'波动%':>7}{'回撤%':>9}{'夏普':>7}")
        for sname, fn in STRATS:
            try:
                sel = fn(pool, N)
            except Exception as e:
                print(f"{sname:<16}  选池失败 {type(e).__name__}")
                continue
            if sel is None or len(sel) < N:
                continue
            res = {}
            for wname, w0, w1 in WINDOWS:
                m = E.bt(sel, w0, w1, scheme="EW", trig="CAL", mode="ADAPT",
                         strength=0.40, lookback=12, slow=36)
                res[wname] = m
                if m:
                    rows.append(dict(波动档=vt, N=N, 策略=sname, 窗口=wname,
                                     净CAGR=m["net"], 死拿=m["hold"], 超额pp=m["excess_net"],
                                     波动=m["vol"], 回撤=m["mdd"], 夏普=m["sharpe"]))
            a, b, c = res.get("训练期05-15"), res.get("验证期16-25"), res.get("全期21年")
            if not (a and b and c):
                print(f"{sname:<16}  数据不足")
                continue
            print(f"{sname:<16}{a['net']:>9.2f}{b['net']:>9.2f}{c['net']:>9.2f}{c['hold']:>8.2f}"
                  f"{c['excess_net']:>+9.2f}{c['vol']:>7.1f}{c['mdd']:>9.1f}{c['sharpe']:>7.2f}")
        sys.stdout.flush()

out = pd.DataFrame(rows)
out.to_csv("data/pool_select_result.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/pool_select_result.csv")

# 汇总: 全期最优
print(f"\n{'='*108}")
print("### 汇总: 全期21年 各配置 TOP12 (按夏普降序)")
print(f"{'='*108}")
p = out[out.窗口 == "全期21年"].sort_values("夏普", ascending=False)
print(f"{'波动档':>7}{'N':>5}{'策略':<18}{'全期%':>9}{'验证期%':>10}{'超额pp':>9}{'波动%':>7}{'回撤%':>9}{'夏普':>7}")
for _, r in p.head(12).iterrows():
    v = out[(out.波动档 == r['波动档']) & (out.N == r['N']) & (out.策略 == r['策略']) &
            (out.窗口 == "验证期16-25")]
    vv = v["净CAGR"].iloc[0] if len(v) else np.nan
    print(f"{int(r['波动档']):>7}{int(r['N']):>5}{r['策略']:<18}{r['净CAGR']:>9.2f}{vv:>10.2f}"
          f"{r['超额pp']:>+9.2f}{r['波动']:>7.1f}{r['回撤']:>9.1f}{r['夏普']:>7.2f}")
