# -*- coding: utf-8 -*-
"""
【20% 目标: 全期确认 + 自适应参数扫描】
  Part A: 全期 2005-2025(21年, 两轮牛熊) 验证 —— 避免单期偶然
  Part B: 自适应开关参数扫描 (strength / lookback / slow) 找最优
  Part C: 最终推荐配置 + 与"死拿持有"对照
约束: 无杠杆现货, 美股成本 1bp, 池子只用训练期波动率筛选(无收益前视)
"""
import pandas as pd, numpy as np, itertools
np.seterr(all="ignore")
import core20 as E

allp, TIERS, df, bt = E.allp, E.TIERS, E.df, E.bt
TR0, TR1 = E.TR0, E.TR1
VA0, VA1 = E.VA0, E.VA1
FU0, FU1 = "2005-01-31", "2025-12-31"

u55 = [c for c in TIERS[55] if c in df.index]
u45 = [c for c in TIERS[45] if c in df.index]

print("=" * 118)
print("【PART A】全期 2005-2025 (21年 / 两轮牛熊) 确认 —— 无杠杆现货, 成本1bp")
print("=" * 118)
print(f"  {'结构':<34}{'净CAGR':>9}{'P25':>9}{'最差':>9}{'死拿CAGR':>10}{'超额':>9}{'波动':>8}{'回撤':>8}{'夏普':>7}{'≥20%':>8}")
rows = []

# A1: vol>=55, N=6 全枚举(28组)
res = []
for combo in itertools.combinations(sorted(u55), 6):
    m = bt(list(combo), FU0, FU1, scheme="EW", trig="CAL", mode="NONE")
    if m:
        res.append((combo, m))
if res:
    n = np.array([m["net"] for _, m in res])
    h = np.array([m["hold"] for _, m in res])
    print(f"  {'N=6 / vol≥55 全枚举(28组)':<34}{np.median(n):>8.2f}%{np.percentile(n,25):>8.2f}%"
          f"{n.min():>8.2f}%{np.median(h):>9.2f}%{np.median(n-h):>+8.2f}pp"
          f"{np.median([m['vol'] for _,m in res]):>7.1f}%{np.median([m['mdd'] for _,m in res]):>7.1f}%"
          f"{np.median([m['sharpe'] for _,m in res]):>7.2f}{np.mean(n>=20)*100:>7.1f}%")
    rows.append(dict(结构="N=6/vol≥55全枚举", 期间="全期21年", 净CAGR=np.median(n),
                     P25=np.percentile(n, 25), 最差=n.min(), 死拿=np.median(h),
                     超额=np.median(n - h), 波动=np.median([m["vol"] for _, m in res]),
                     回撤=np.median([m["mdd"] for _, m in res]),
                     夏普=np.median([m["sharpe"] for _, m in res]), 过20占比=np.mean(n >= 20) * 100))

# A2: vol>=45, N=12 采样
rng = np.random.default_rng(2024)
pools, seen, guard = [], set(), 0
while len(pools) < 300 and guard < 6000:
    guard += 1
    q = tuple(sorted(rng.choice(u45, 12, replace=False)))
    if q in seen:
        continue
    seen.add(q); pools.append(q)
for lbl, mode in [("N=12 / vol≥45 等权月历", "NONE"), ("N=12 / vol≥45 等权月历+自适应", "ADAPT")]:
    rs = [bt(list(q), FU0, FU1, scheme="EW", trig="CAL", mode=mode) for q in pools]
    rs = [x for x in rs if x]
    n = np.array([x["net"] for x in rs]); h = np.array([x["hold"] for x in rs])
    print(f"  {lbl:<34}{np.median(n):>8.2f}%{np.percentile(n,25):>8.2f}%"
          f"{n.min():>8.2f}%{np.median(h):>9.2f}%{np.median(n-h):>+8.2f}pp"
          f"{np.median([x['vol'] for x in rs]):>7.1f}%{np.median([x['mdd'] for x in rs]):>7.1f}%"
          f"{np.median([x['sharpe'] for x in rs]):>7.2f}{np.mean(n>=20)*100:>7.1f}%")
    rows.append(dict(结构=lbl, 期间="全期21年", 净CAGR=np.median(n), P25=np.percentile(n, 25),
                     最差=n.min(), 死拿=np.median(h), 超额=np.median(n - h),
                     波动=np.median([x["vol"] for x in rs]), 回撤=np.median([x["mdd"] for x in rs]),
                     夏普=np.median([x["sharpe"] for x in rs]), 过20占比=np.mean(n >= 20) * 100))

print("\n" + "=" * 118)
print("【PART B】自适应开关参数扫描 (N=12 / vol≥45, 验证期 + 全期)")
print("=" * 118)
print(f"  {'参数(strength/lookback/slow)':<34}{'验证期净':>10}{'vs基准':>10}{'全期净':>10}{'vs基准':>10}{'胜率':>8}")
base_va, base_fu = {}, {}
for q in pools:
    m = bt(list(q), VA0, VA1, scheme="EW", trig="CAL", mode="NONE")
    if m:
        base_va[q] = m["net"]
    m2 = bt(list(q), FU0, FU1, scheme="EW", trig="CAL", mode="NONE")
    if m2:
        base_fu[q] = m2["net"]
scan = []
for st in [0.20, 0.35, 0.50]:
    for lb, sl in [(12, 36), (24, 60), (36, 84)]:
        va, fu, win, cnt = [], [], 0, 0
        for q in pools:
            m = bt(list(q), VA0, VA1, scheme="EW", trig="CAL", mode="ADAPT",
                   strength=st, lookback=lb, slow=sl)
            m2 = bt(list(q), FU0, FU1, scheme="EW", trig="CAL", mode="ADAPT",
                    strength=st, lookback=lb, slow=sl)
            if m and m2 and q in base_va and q in base_fu:
                va.append(m["net"]); fu.append(m2["net"]); cnt += 1
                if m["net"] > base_va[q]:
                    win += 1
        if cnt < 20:
            continue
        tag = f"strength={st} / lb={lb} / slow={sl}"
        print(f"  {tag:<34}{np.median(va):>9.2f}%{np.median(va)-np.median(list(base_va.values())):>+9.2f}pp"
              f"{np.median(fu):>9.2f}%{np.median(fu)-np.median(list(base_fu.values())):>+9.2f}pp"
              f"{win/cnt*100:>7.1f}%")
        scan.append(dict(strength=st, lookback=lb, slow=sl, 验证期净=np.median(va),
                         验证期增量=np.median(va) - np.median(list(base_va.values())),
                         全期净=np.median(fu),
                         全期增量=np.median(fu) - np.median(list(base_fu.values())),
                         胜率=win / cnt * 100))
pd.DataFrame(scan).to_csv("data/evolve_adapt_scan.csv", index=False, encoding="utf-8-sig")

print("\n" + "=" * 118)
print("【PART C】最终推荐 (无杠杆现货 / 成本1bp / 全期21年)")
print("=" * 118)
best = pd.DataFrame(rows).sort_values("夏普", ascending=False).iloc[0]
print(f"  推荐结构: {best['结构']}")
print(f"  全期净CAGR {best['净CAGR']:.2f}% | 死拿 {best['死拿']:.2f}% | 再平衡超额 {best['超额']:+.2f}pp")
print(f"  波动 {best['波动']:.1f}% | 最大回撤 {best['回撤']:.1f}% | 夏普 {best['夏普']:.2f}")
print(f"  ≥20% 占比 {best['过20占比']:.1f}% | 最差组合 {best['最差']:.2f}%")
pd.DataFrame(rows).to_csv("data/evolve_final20.csv", index=False, encoding="utf-8-sig")
print("\n已存: data/evolve_final20.csv / data/evolve_adapt_scan.csv")
