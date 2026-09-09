# -*- coding: utf-8 -*-
"""
【池子宽度扫描】—— 回答用户: "8个股票怎么能叫组合? 要50个, 各行各业龙头"

测 N = 4,6,8,12,16,20,25,30,40,50 在两档波动池(vol>=30 / vol>=35)上的表现,
三个窗口(训练期05-15 / 验证期16-25 / 全期21年), 模式 EW + ADAPT。

理论预期: gamma* = 0.5*sigma^2*(N-1)/N*(1-rho)
  N=4 ->0.750 | N=12->0.917 | N=50->0.980 (相对N=4, N=50 增加 30.7%)
"""
import pandas as pd, numpy as np, itertools, sys
import core20 as E

rng = np.random.default_rng(2027)

# ---- 去重: 2899_HK vs 2899_HK_ZIJIN 等同一标的的不同命名 ----
def dedup(cols, px):
    """同序列(相关系数>0.999)只保留一个"""
    keep = []
    for c in cols:
        dup = False
        for k in keep:
            a, b = px[c], px[k]
            m = a.notna() & b.notna()
            if m.sum() > 60:
                aa, bb = a[m].values, b[m].values
                if np.std(aa) > 0 and np.std(bb) > 0:
                    if np.corrcoef(aa, bb)[0, 1] > 0.999:
                        dup = True
                        break
        if not dup:
            keep.append(c)
    return keep

TIERS = {}
for t in [30, 35]:
    lst = list(E.BASE[E.BASE.vol >= t].index)
    TIERS[t] = dedup(lst, E.allp)

print("=== 去重后候选池 ===")
for t, v in TIERS.items():
    print(f"  vol>={t}: {len(v)} 个")

WINDOWS = [("训练期05-15", E.TR0, E.TR1), ("验证期16-25", E.VA0, E.VA1), ("全期21年", E.TR0, E.VA1)]
NS = [4, 6, 8, 12, 16, 20, 25, 30, 40, 50]
N_SAMPLE = 60

rows = []
for vt in [30, 35]:
    pool = TIERS[vt]
    print(f"\n{'='*100}")
    print(f"### 波动档 vol>={vt}  (候选 {len(pool)} 个)")
    print(f"{'='*100}")
    for N in NS:
        if N > len(pool):
            print(f"  N={N}: 候选不足({len(pool)}), 跳过")
            continue
        # 采样 N 元组
        combos = []
        seen = set()
        guard = 0
        while len(combos) < N_SAMPLE and guard < N_SAMPLE * 400:
            guard += 1
            q = tuple(sorted(rng.choice(pool, N, replace=False)))
            if q in seen:
                continue
            seen.add(q)
            combos.append(q)
        for wname, w0, w1 in WINDOWS:
            nets, exs, hcs, vols, mdds, shps = [], [], [], [], [], []
            for cols in combos:
                m = E.bt(list(cols), w0, w1, scheme="EW", trig="CAL",
                        mode="ADAPT", strength=0.40, lookback=12, slow=36)
                if m is None:
                    continue
                nets.append(m["net"]); exs.append(m["excess_net"]); hcs.append(m["hold"])
                vols.append(m["vol"]); mdds.append(m["mdd"]); shps.append(m["sharpe"])
            if len(nets) < 5:
                continue
            nets = np.array(nets); exs = np.array(exs)
            rows.append(dict(波动档=vt, N=N, 窗口=wname, 有效池=len(nets),
                             净CAGR中位=float(np.median(nets)), 死拿中位=float(np.median(hcs)),
                             超额中位=float(np.median(exs)),
                             净CAGR均值=float(nets.mean()),
                             P10=float(np.percentile(nets, 10)), P90=float(np.percentile(nets, 90)),
                             最差=float(nets.min()), 最好=float(nets.max()),
                             波动=float(np.median(vols)), 回撤=float(np.median(mdds)),
                             夏普=float(np.median(shps)),
                             ge20=float((nets >= 20).mean() * 100)))
            if wname == "全期21年":
                r = rows[-1]
                print(f"  N={N:>3} | 全期净CAGR中位 {r['净CAGR中位']:>6.2f}% | 死拿 {r['死拿中位']:>6.2f}% "
                      f"| 超额 {r['超额中位']:>+6.2f}pp | 波动 {r['波动']:>5.1f}% | 回撤 {r['回撤']:>6.1f}% "
                      f"| 夏普 {r['夏普']:>5.2f} | ≥20% {r['ge20']:>5.1f}% | 区间[{r['最差']:.1f},{r['最好']:.1f}]")
        sys.stdout.flush()

out = pd.DataFrame(rows)
out.to_csv("data/wide_pool_scan.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/wide_pool_scan.csv")

# ---- 汇总: 全期下 N 的影响 ----
print(f"\n{'='*100}")
print("### 汇总: 全期21年, 池子宽度 N 的影响 (验证期=样本外)")
print(f"{'='*100}")
p = out[out.窗口 == "全期21年"]
for vt in [30, 35]:
    q = p[p.波动档 == vt]
    if len(q) == 0:
        continue
    print(f"\n-- vol>={vt} --")
    print(f"{'N':>4}{'净CAGR':>9}{'死拿':>9}{'超额pp':>9}{'波动%':>8}{'回撤%':>9}{'夏普':>7}{'≥20%':>8}")
    for _, r in q.iterrows():
        print(f"{int(r['N']):>4}{r['净CAGR中位']:>9.2f}{r['死拿中位']:>9.2f}{r['超额中位']:>+9.2f}"
              f"{r['波动']:>8.1f}{r['回撤']:>9.1f}{r['夏普']:>7.2f}{r['ge20']:>7.1f}%")
