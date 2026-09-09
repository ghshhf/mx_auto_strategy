# -*- coding: utf-8 -*-
"""
【收官检验】
  1) strength 是否"越界越优" (0.35/0.5/0.7/1.0) —— 若越大越好说明是变相押注, 不可用
  2) 三个子期(训练/验证/全期)是否都为正 —— 结构性 vs 偶然
  3) tilt 后权重集中度 —— 检查是否变相单押
"""
import pandas as pd, numpy as np, itertools
np.seterr(all="ignore")
import core20 as E

allp, TIERS, df, bt = E.allp, E.TIERS, E.df, E.bt
TR0, TR1, VA0, VA1 = E.TR0, E.TR1, E.VA0, E.VA1
FU0, FU1 = "2005-01-31", "2025-12-31"
u45 = [c for c in TIERS[45] if c in df.index]
u55 = [c for c in TIERS[55] if c in df.index]

rng = np.random.default_rng(777)
pools, seen, guard = [], set(), 0
while len(pools) < 250 and guard < 5000:
    guard += 1
    q = tuple(sorted(rng.choice(u45, 12, replace=False)))
    if q in seen:
        continue
    seen.add(q); pools.append(q)

print("=" * 116)
print("【1】strength 越界检验 (N=12/vol≥45, lb=12/slow=36, 全期 2005-2025)")
print("=" * 116)
print(f"  {'strength':<12}{'全期净':>10}{'训练期':>10}{'验证期':>10}{'波动':>8}{'回撤':>8}{'夏普':>7}{'tilt后最大权重':>14}")
base = {}
for q in pools:
    m = bt(list(q), FU0, FU1, scheme="EW", trig="CAL", mode="NONE")
    if m:
        base[q] = m
bmed = np.median([v["net"] for v in base.values()])
for st in [0.0, 0.35, 0.5, 0.7, 1.0]:
    fu, tr, va, vo, md = [], [], [], [], []
    for q in pools:
        a = bt(list(q), FU0, FU1, scheme="EW", trig="CAL", mode="ADAPT", strength=st, lookback=12, slow=36)
        b = bt(list(q), TR0, TR1, scheme="EW", trig="CAL", mode="ADAPT", strength=st, lookback=12, slow=36)
        c = bt(list(q), VA0, VA1, scheme="EW", trig="CAL", mode="ADAPT", strength=st, lookback=12, slow=36)
        if a and b and c:
            fu.append(a["net"]); tr.append(b["net"]); va.append(c["net"])
            vo.append(a["vol"]); md.append(a["mdd"])
    # tilt 后权重集中度: N=12 等权 1/12=8.33%, strength=st 时最大权重 ≈ (1+st*2)/N 归一化上限
    wmax = (1 + st * 2) / ((1 + st * 2) + 11) * 100
    print(f"  {st:<12.2f}{np.median(fu):>9.2f}%{np.median(tr):>9.2f}%{np.median(va):>9.2f}%"
          f"{np.median(vo):>7.1f}%{np.median(md):>7.1f}%{np.median(fu)/np.median(vo):>7.2f}{wmax:>13.1f}%")
print(f"  (基准 strength=0 全期中位 = {bmed:.2f}%; N=12等权基准权重 = 8.3%)")

print("\n" + "=" * 116)
print("【2】三子期一致性 (N=12/vol≥45 + N=6/vol≥55, strength=0.5/lb=12/slow=36)")
print("=" * 116)
print(f"  {'结构':<30}{'期间':<18}{'净CAGR':>10}{'死拿':>10}{'超额':>10}{'夏普':>7}{'≥20%':>8}")
rows = []
for lbl, pls in [("N=12/vol≥45(采样250)", pools),
                 ("N=6/vol≥55(全枚举)", [c for c in itertools.combinations(sorted(u55), 6)])]:
    for plbl, a, b in [("训练期 2005-2015", TR0, TR1), ("验证期 2016-2025", VA0, VA1),
                       ("全期 2005-2025", FU0, FU1)]:
        rs, hs = [], []
        for q in pls:
            m = bt(list(q), a, b, scheme="EW", trig="CAL", mode="ADAPT", strength=0.5, lookback=12, slow=36)
            if m:
                rs.append(m); hs.append(m["hold"])
        if len(rs) < 5:
            continue
        n = np.array([x["net"] for x in rs])
        print(f"  {lbl:<30}{plbl:<18}{np.median(n):>9.2f}%{np.median(hs):>9.2f}%"
              f"{np.median(n)-np.median(hs):>+9.2f}pp{np.median(n)/np.median([x['vol'] for x in rs]):>7.2f}"
              f"{np.mean(n>=20)*100:>7.1f}%")
        rows.append(dict(结构=lbl, 期间=plbl, 净CAGR=np.median(n), 死拿=np.median(hs),
                         超额=np.median(n) - np.median(hs),
                         波动=np.median([x["vol"] for x in rs]),
                         回撤=np.median([x["mdd"] for x in rs]),
                         夏普=np.median(n) / np.median([x["vol"] for x in rs]),
                         过20占比=np.mean(n >= 20) * 100))
pd.DataFrame(rows).to_csv("data/evolve_final_check.csv", index=False, encoding="utf-8-sig")
print("\n已存 data/evolve_final_check.csv")
