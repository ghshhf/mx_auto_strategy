# -*- coding: utf-8 -*-
"""校验：共同窗口下各腿交易日数、以及价格口径/全收益口径的差异"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from dca_backtest import load

START = "2020-07-03"
import datetime as dt
s = dt.date(*[int(x) for x in START.split("-")])

print("=== 共同窗口 2020-07-03 之后的交易日数 ===")
for sym in ["IDX_SP500TR", "IDX_NDX", "IDX_HSI", "515100.SS", "3110.HK",
            "IDX_GSPC", "510880.SS", "IDX_IXIC", "IDX_DJI", "VYM", "DVY"]:
    try:
        d, p = load(sym)
        i0 = int(np.searchsorted([x.toordinal() for x in d], s.toordinal()))
        n = len(d) - i0
        print(f"  {sym:12s} 全序列 {len(d):6d} 条  窗口内 {n:5d} 条  "
              f"{d[i0]} -> {d[-1]}  首值 {p[i0]:.2f} 末值 {p[-1]:.2f}")
    except Exception as e:
        print(f"  {sym:12s} ERR {e}")

print()
print("=== 价格口径 vs 全收益口径（重叠期 1988-2026）===")
for sym in ["IDX_GSPC", "IDX_SP500TR"]:
    d, p = load(sym)
    yr = (d[-1] - d[0]).days / 365.25
    print(f"  {sym:12s} {d[0]} -> {d[-1]}  {yr:.1f}y  {len(d)} 条  "
          f"倍数 {p[-1]/p[0]:.2f}×  年化 {(p[-1]/p[0])**(1/yr)-1:.2%}")

print()
print("=== 全收益/价格 的比值（衡量股息再投累积贡献）===")
d1, p1 = load("IDX_GSPC")
d2, p2 = load("IDX_SP500TR")
o1 = {x.toordinal(): v for x, v in zip(d1, p1)}
o2 = {x.toordinal(): v for x, v in zip(d2, p2)}
common = sorted(set(o1) & set(o2))
r0 = o1[common[0]] / o2[common[0]]
for k in [0, len(common)//4, len(common)//2, 3*len(common)//4, len(common)-1]:
    t = common[k]
    print(f"  {dt.date.fromordinal(t)}  比值 {(o1[t]/o2[t])/r0:.4f}")
