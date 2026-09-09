# -*- coding: utf-8 -*-
"""
【高波动池构成体检 + 全枚举 + 大池搜索】—— 确认 24.8% 不是单一板块垄断

问题: 上一步 N=6/vol>=55 得净CAGR 24.81%(验证期)。但该档标的可能只有 ~9 个,
      组合数 C(9,6)=84 极少, 需确认:
      ① 这些标的分散在几个行业? 还是全是加密股/氢能一类?
      ② 全枚举(而非采样)后分布如何? 最差组合多少?
      ③ 扩大到 N=8/12 时是否仍达标?
"""
import pandas as pd, numpy as np, itertools
np.seterr(all="ignore")
import core20 as E   # 纯内核模块(无主流程)

allp, TIERS, df, bt = E.allp, E.TIERS, E.df, E.bt
TR0, TR1, VA0, VA1 = E.TR0, E.TR1, E.VA0, E.VA1

print("\n" + "#" * 112)
print("# 高波动池构成体检")
print("#" * 112)
for vt in [45, 55]:
    names = TIERS[vt]
    sub = df.loc[[c for c in names if c in df.index]].sort_values("vol", ascending=False)
    print(f"\n=== 训练期 vol>={vt} 的标的: {len(names)} 个 ===")
    print(f"  {'标的':<12}{'训练期CAGR':>11}{'训练期波动':>11}  类别")
    for c in sub.index:
        print(f"  {c:<12}{sub.loc[c,'cagr']:>10.2f}%{sub.loc[c,'vol']:>10.2f}%  {sub.loc[c,'kind']}")

# ---------- 全枚举: N=6, vol>=55 ----------
print("\n" + "#" * 112)
print("# 【全枚举】N=6, vol>=55 —— 所有可能组合, 非采样 (验证期 2016-2025, 成本1bp)")
print("#" * 112)
u55 = [c for c in TIERS[55] if c in df.index]
res = []
for combo in itertools.combinations(sorted(u55), 6):
    m = bt(list(combo), VA0, VA1, scheme="IV", trig="BAND", band=0.10, mode="NONE")
    if m:
        res.append((combo, m))
if res:
    nets = np.array([m["net"] for _, m in res])
    print(f"  组合总数(全枚举): {len(res)}")
    print(f"  净CAGR: 中位 {np.median(nets):.2f}% | 最差 {nets.min():.2f}% | 最好 {nets.max():.2f}%")
    print(f"  ≥20% 占比 {np.mean(nets>=20)*100:.1f}% | ≥15% 占比 {np.mean(nets>=15)*100:.1f}%")
    print(f"  波动中位 {np.median([m['vol'] for _,m in res]):.1f}% | "
          f"回撤中位 {np.median([m['mdd'] for _,m in res]):.1f}% | "
          f"夏普中位 {np.median([m['sharpe'] for _,m in res]):.2f}")
    res.sort(key=lambda x: -x[1]["net"])
    print("\n  --- 最差 5 组(看下行风险) ---")
    for q, m in res[-5:]:
        print(f"    {','.join(q)[:58]:<60} 净{m['net']:>6.2f}% 波动{m['vol']:>5.1f}% 回撤{m['mdd']:>6.1f}%")
    print("\n  --- 最好 5 组 ---")
    for q, m in res[:5]:
        print(f"    {','.join(q)[:58]:<60} 净{m['net']:>6.2f}% 波动{m['vol']:>5.1f}% 回撤{m['mdd']:>6.1f}%")

# ---------- 大池搜索: N=8/12, vol>=45 ----------
print("\n" + "#" * 112)
print("# 【大池搜索】N=8 / N=12, vol>=45, 采样400组 (验证期, 成本1bp)")
print("#" * 112)
rng = np.random.default_rng(4242)
u45 = [c for c in TIERS[45] if c in df.index]
print(f"  可用标的: {len(u45)} 个")
rows = []
for N in [8, 12]:
    if len(u45) < N + 2:
        continue
    for scheme, trig, band, mode, lbl in [
            ("EW", "CAL", 0.0, "NONE", "等权+月历"),
            ("EW", "CAL", 0.0, "ADAPT", "等权+月历+自适应"),
            ("IV", "BAND", 0.10, "NONE", "反波动+BAND10"),
            ("IV", "BAND", 0.10, "ADAPT", "反波动+BAND10+自适应")]:
        out, seen, guard = [], set(), 0
        while len(out) < 400 and guard < 8000:
            guard += 1
            q = tuple(sorted(rng.choice(u45, N, replace=False)))
            if q in seen:
                continue
            seen.add(q); out.append(q)
        rs = [bt(list(q), VA0, VA1, scheme=scheme, trig=trig, band=band, mode=mode) for q in out]
        rs = [x for x in rs if x]
        if len(rs) < 30:
            continue
        n = np.array([x["net"] for x in rs])
        rows.append(dict(N=N, 配置=lbl, 净CAGR=np.median(n), P25=np.percentile(n, 25),
                         最差=n.min(), 波动=np.median([x["vol"] for x in rs]),
                         回撤=np.median([x["mdd"] for x in rs]),
                         夏普=np.median([x["sharpe"] for x in rs]),
                         过20占比=np.mean(n >= 20) * 100))
        print(f"  N={N:<3}{lbl:<22} 净CAGR中位 {np.median(n):>6.2f}% | P25 {np.percentile(n,25):>6.2f}% | "
              f"最差 {n.min():>6.2f}% | 波动 {np.median([x['vol'] for x in rs]):>5.1f}% | "
              f"回撤 {np.median([x['mdd'] for x in rs]):>6.1f}% | 夏普 {np.median([x['sharpe'] for x in rs]):>5.2f} | "
              f"≥20% {np.mean(n>=20)*100:>5.1f}%")
pd.DataFrame(rows).to_csv("data/evolve_hivol_pool.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/evolve_hivol_pool.csv")
