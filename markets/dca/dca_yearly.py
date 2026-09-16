# -*- coding: utf-8 -*-
"""低保账户「逐年 / 按年龄」明细。

目的：把 38.7 年真实窗口的每一年，映射到「22 岁 → 62 岁」，
      看每个年龄阶段账户能做出多少收益。

两套路径：
  · P1 = 1988 起点真实路径（4 腿 40 元/日，红利腿接力）—— 实际发生过的那一条，偏乐观
  · P2 = 标普500（全收益构造）60 个 40 年窗口的同龄中位路径 —— 代表性路径，用于校准
"""
import os
import sys
import json
import datetime as dt

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import real_window as rw          # noqa: E402

ROOT, HIST, OUT = rw.ROOT, rw.HIST, rw.OUT
AGE0 = 22                          # 起投年龄
BIRTH_YEAR = 2004
Y0 = 2026                          # 现实起点年


# ------------------------------------------------------------------ 工具
def div_factor():
    """用 SP500TR 与 GSPC 的重叠期，反推隐含年化股息率。"""
    d1, p1 = rw.load_hist("IDX_GSPC")
    d2, p2 = rw.load_hist("IDX_SP500TR")
    i0 = int(np.searchsorted(d1, d2[0]))
    i1 = int(np.searchsorted(d1, d2[-1]))
    d1s, p1s = d1[i0:i1 + 1], p1[i0:i1 + 1]
    yr = (d1s[-1] - d1s[0]).days / 365.25
    g_sp = (p1s[-1] / p1s[0]) ** (1 / yr) - 1
    g_tr = (p2[-1] / p2[0]) ** (1 / yr) - 1
    return (1 + g_tr) / (1 + g_sp) - 1


def by_year(dates, eq, ci):
    """按自然年取最后一个交易日 → 逐年明细。年龄按「第 k 年」映射，不按自然年。"""
    last = {}
    for i, d in enumerate(dates):
        last[d.year] = i
    rows, prev, k = [], None, 0
    for y in sorted(last):
        i = last[y]
        k += 1
        inv = float(ci[i] - (ci[prev] if prev is not None else 0.0))
        eq_prev = float(eq[prev]) if prev is not None else 0.0
        base = eq_prev + inv
        pnl = float(eq[i]) - eq_prev - inv
        rows.append(dict(
            k=k, year=y, age=AGE0 + k - 1,
            value=float(eq[i]), cum_inv=float(ci[i]), inv_year=inv,
            pnl=pnl, ratio=float(eq[i] / ci[i]) if ci[i] else 1.0,
            ret=pnl / base if base > 0 else 0.0,
            pnl_over_inv=pnl / inv if inv > 0 else 0.0))
        prev = i
    return rows


def milestones(rows):
    out = {}
    for r in rows:
        if "回本(>1.0×)" not in out and r["ratio"] > 1.0:
            out["回本(>1.0×)"] = (r["year"], r["age"])
        if "一年赚超一年投入" not in out and r["pnl"] > r["inv_year"]:
            out["一年赚超一年投入"] = (r["year"], r["age"])
        for tag, thr in (("10万", 1e5), ("50万", 5e5), ("100万", 1e6),
                         ("300万", 3e6), ("500万", 5e6), ("1000万", 1e7)):
            if tag not in out and r["value"] >= thr:
                out[tag] = (r["year"], r["age"])
    return out


# ------------------------------------------------------------------ P2
def century_path(amt=10.0, n_years=40):
    """标普500 全收益构造：每个起点年跑一个 40 年窗口，取各「第 k 年」倍数的分布。"""
    dv = div_factor()
    d, p = rw.make_tr("IDX_GSPC", dv)
    first = {}
    for i, x in enumerate(d):
        first.setdefault(x.year, i)
    ys = sorted(first)
    per = {}                                  # k -> [ratio...]
    cfgs = []
    for y0 in ys:
        i0 = first[y0]
        target = d[i0] + dt.timedelta(days=int(round(n_years * 365.25)))
        if target > d[-1]:
            break
        i1 = int(np.searchsorted(d, target))
        px = p[i0:i1 + 1]
        dd = d[i0:i1 + 1]
        eq, ci = rw.dca(px, amt)
        cfgs.append(f"{y0}-{dd[-1].year}")
        last = {}
        for i, x in enumerate(dd):
            last[x.year] = i
        k = 0
        prev = None
        for yy in sorted(last):
            i = last[yy]
            k += 1
            if k > n_years:
                break
            per.setdefault(k, []).append(float(eq[i] / ci[i]))
            prev = i
    stats = {}
    for k in sorted(per):
        a = np.array(per[k])
        stats[k] = dict(n=len(a), p25=float(np.percentile(a, 25)),
                        med=float(np.median(a)),
                        p75=float(np.percentile(a, 75)),
                        mn=float(a.min()), mx=float(a.max()))
    return dict(dv=dv, windows=cfgs, n=len(cfgs), stats=stats)


def main():
    cd, cv = rw.load_cpi()

    # ---- P1 组合（4 腿 40 元/日，红利腿接力）
    A_SSE = dt.date(2007, 1, 18)
    legs = [("IDX_SP500TR", 0.0, dt.date(1988, 1, 4), 10.0),
            ("IDX_NDX", 0.007, dt.date(1988, 1, 4), 10.0),
            ("IDX_HSI", 0.035, dt.date(1988, 1, 4), 10.0),
            ("IDX_HSI", 0.035, dt.date(1988, 1, 4), 10.0, A_SSE),
            ("510880.SS", 0.0, A_SSE, 10.0)]
    alld, eq, ci, ends = rw.build(legs)
    rows = by_year(alld, eq, ci)
    ms = milestones(rows)

    print("=" * 96)
    print("P1 · 1988 起点真实路径（4 腿 40 元/日，红利腿接力）—— 按年龄")
    print("=" * 96)
    print(f"  {'第N年':>4s} {'年份':>5s} {'年龄':>4s} {'年末市值':>12s} {'累计投入':>10s} "
          f"{'当年投入':>9s} {'当年盈亏':>12s} {'盈亏/投入':>9s} {'账户倍数':>8s} {'当年收益率':>9s}")
    for r in rows:
        print(f"  {r['k']:>4d} {r['year']:>5d} {r['age']:>4d} "
              f"{r['value']:>12,.0f} {r['cum_inv']:>10,.0f} {r['inv_year']:>9,.0f} "
              f"{r['pnl']:>12,.0f} {r['pnl_over_inv']:>8.2f}× "
              f"{r['ratio']:>7.2f}× {r['ret']:>8.1%}")
    print("\n  里程碑:")
    for k, (y, a) in ms.items():
        print(f"    {k:16s} {y} 年（{a} 岁）")

    # ---- P2 标普 60 个 40 年窗口
    cp = century_path()
    print("\n" + "=" * 96)
    print(f"P2 · 标普500 全收益构造（隐含股息 {cp['dv']:.2%}/年）"
          f"—— {cp['n']} 个 40 年窗口，各「第 k 年」倍数")
    print("=" * 96)
    print(f"  {'第N年':>4s} {'年龄':>4s} {'P25':>7s} {'中位':>7s} {'P75':>7s} "
          f"{'最差':>7s} {'最好':>7s}")
    for k in sorted(cp["stats"]):
        s = cp["stats"][k]
        print(f"  {k:>4d} {AGE0+k:>4d} {s['p25']:>6.2f}× {s['med']:>6.2f}× "
              f"{s['p75']:>6.2f}× {s['mn']:>6.2f}× {s['mx']:>6.2f}×")

    res = dict(p1=dict(rows=rows, milestones={k: list(v) for k, v in ms.items()},
                       legs=[[l[0], l[1], str(l[2]), l[3], str(l[4]) if len(l) > 4 else None]
                             for l in legs]),
               p2=cp)
    with open(os.path.join(OUT, "yearly_result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=float)
    print(f"\n结果: {os.path.join(OUT, 'yearly_result.json')}")


if __name__ == "__main__":
    main()
