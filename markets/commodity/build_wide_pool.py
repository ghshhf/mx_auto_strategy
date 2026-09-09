# -*- coding: utf-8 -*-
"""
【固化模板】跨行业龙头宽池构建器
用法:
  python build_wide_pool.py --vt 45 --N 50 --topk 3 --seed 2026
  python build_wide_pool.py --vt 40 --N 20 --topk 1 --seed 2026

产出:
  - 选定池的 全期/训练/验证 净CAGR(已扣 1bp 成本, 无杠杆现货)
  - 随机化贪心 x40 稳健性 (>=20% 占比)
  - 池内成分明细 CSV
  - 池清单 JSON (data/wide_pool_<vt>_<N>.json) 供再验证/再平衡实盘对接
"""
import argparse, json
import numpy as np, pandas as pd
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vt", type=int, default=45, help="波动档 (训练期年化波动%下限)")
    ap.add_argument("--N", type=int, default=50, help="池大小")
    ap.add_argument("--topk", type=int, default=3, help="贪心随机候选数(1=纯贪心)")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--rob", type=int, default=40, help="随机化稳健性次数")
    a = ap.parse_args()
    global rng; rng = np.random.default_rng(a.seed)

    pool = dedup(list(E.BASE[E.BASE.vol >= a.vt].index), E.allp)
    print(f"vol>={a.vt} 去重候选: {len(pool)} (全宇宙 BASE={len(E.BASE)})")
    sel = greedy(pool, a.N, topk=a.topk, rnd=rng)
    if sel is None:
        raise SystemExit("候选不足 N")
    ma = run(sel, E.TR0, E.VA1); mt = run(sel, E.TR0, E.TR1); mv = run(sel, E.VA0, E.VA1)
    print(f"\n=== 选定宽池 (vol>={a.vt}, N={a.N}, topk={a.topk}) ===")
    print(f"全期  2005-2025: 净 {ma['net']:.2f}% | 死拿 {ma['hold']:.2f}% | 超额 {ma['excess_net']:+.2f}pp | 波动 {ma['vol']:.1f}% | 回撤 {ma['mdd']:.1f}% | 夏普 {ma['sharpe']:.2f}")
    print(f"训练  2005-2015: 净 {mt['net']:.2f}%")
    print(f"验证  2016-2025: 净 {mv['net']:.2f}% | 死拿 {mv['hold']:.2f}% | 超额 {mv['excess_net']:+.2f}pp | 波动 {mv['vol']:.1f}% | 回撤 {mv['mdd']:.1f}% | 夏普 {mv['sharpe']:.2f}")

    rows = [(c, E.BASE.loc[c, "kind"], round(E.BASE.loc[c, "vol"], 1), round(E.BASE.loc[c, "cagr"], 1)) for c in sel]
    df = pd.DataFrame(rows, columns=["标的", "类别", "波动%", "训练期CAGR%"])
    print(f"\n=== 池内 {len(sel)} 个标的 ===")
    print(df.to_string(index=False))
    print("\n类别分布:", df["类别"].value_counts().to_dict())
    R, cols = train_stats(sel); iu = np.triu_indices(len(sel), 1)
    print(f"池内平均相关性: {R[iu].mean():.3f}")

    print(f"\n=== 随机化贪心 x{a.rob} (topk={a.topk}) 稳健性 ===")
    vs, vval = [], []
    for _ in range(a.rob):
        s = greedy(pool, a.N, topk=a.topk, rnd=rng)
        if s is None: continue
        m = run(s, E.TR0, E.VA1); mv2 = run(s, E.VA0, E.VA1)
        if m and mv2: vs.append(m); vval.append(mv2)
    vn = np.array([v["net"] for v in vs]); vsh = np.array([v["sharpe"] for v in vs])
    vv = np.array([v["net"] for v in vval]); vmd = np.array([v["mdd"] for v in vs])
    print(f"全期净CAGR  中位 {np.median(vn):.2f}% | 区间 [{vn.min():.2f}, {vn.max():.2f}]")
    print(f"验证期净CAGR 中位 {np.median(vv):.2f}% | 区间 [{vv.min():.2f}, {vv.max():.2f}]")
    print(f"夏普中位 {np.median(vsh):.2f} | 回撤中位 {np.median(vmd):.1f}%")
    print(f">=20% 占比 {(vn>=20).mean()*100:.1f}% | >=25% 占比 {(vn>=25).mean()*100:.1f}%")

    # 持久化
    out = {
        "vt": a.vt, "N": a.N, "topk": a.topk, "seed": a.seed,
        "pool": sel,
        "metrics": {
            "full_net": round(ma["net"], 2), "full_hold": round(ma["hold"], 2),
            "full_excess": round(ma["excess_net"], 2), "full_vol": round(ma["vol"], 1),
            "full_mdd": round(ma["mdd"], 1), "full_sharpe": round(ma["sharpe"], 2),
            "train_net": round(mt["net"], 2), "validate_net": round(mv["net"], 2),
            "validate_hold": round(mv["hold"], 2), "validate_excess": round(mv["excess_net"], 2),
            "validate_sharpe": round(mv["sharpe"], 2),
            "avg_corr": round(float(R[iu].mean()), 3),
        },
        "robustness": {
            "n": len(vs), "full_median": round(float(np.median(vn)), 2),
            "validate_median": round(float(np.median(vv)), 2),
            "pct_ge20": round(float((vn >= 20).mean() * 100), 1),
            "pct_ge25": round(float((vn >= 25).mean() * 100), 1),
        },
    }
    jp = f"data/wide_pool_{a.vt}_{a.N}.json"
    with open(jp, "w") as f: json.dump(out, f, ensure_ascii=False, indent=2)
    df.to_csv(f"data/wide_pool_{a.vt}_{a.N}_composition.csv", index=False, encoding="utf-8-sig")
    print(f"\n已存 {jp} 与 data/wide_pool_{a.vt}_{a.N}_composition.csv")


if __name__ == "__main__":
    main()
