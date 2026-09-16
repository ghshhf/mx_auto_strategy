# -*- coding: utf-8 -*-
"""排查 510880 的 -99.3% 浮亏：看前复权序列有没有断点"""
import csv, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(HERE, "data", "history", "510880.SS.csv")
rows = list(csv.DictReader(open(p, encoding="utf-8")))
print(f"总行数 {len(rows)}  {rows[0]['date']} -> {rows[-1]['date']}")
a = np.array([float(r["adjclose"]) for r in rows])
d = [r["date"] for r in rows]
print("前10:", [(d[i], round(a[i], 4)) for i in range(10)])
print("后5 :", [(d[-5+i], round(a[-5+i], 4)) for i in range(5)])
print(f"min {a.min():.4f} @ {d[int(np.argmin(a))]}   max {a.max():.4f} @ {d[int(np.argmax(a))]}")
# 找最大单日跌幅
ret = a[1:] / a[:-1] - 1
worst = np.argsort(ret)[:6]
print("\n最大单日跌幅:")
for i in sorted(worst):
    print(f"  {d[i+1]}  {a[i]:.4f} -> {a[i+1]:.4f}  {ret[i]:.2%}")
# 找序列中的量级跳变（相邻比值离 1 很远）
jump = np.abs(np.log(a[1:] / a[:-1]))
jj = np.argsort(jump)[-6:]
print("\n最大单日涨幅:")
for i in sorted(jj):
    print(f"  {d[i+1]}  {a[i]:.4f} -> {a[i+1]:.4f}  {ret[i]:+.2%}")
# 分年首末
print("\n分年首末:")
import itertools
for y, grp in itertools.groupby(range(len(d)), key=lambda i: d[i][:4]):
    idx = list(grp)
    print(f"  {y}  {a[idx[0]]:.4f} -> {a[idx[-1]]:.4f}  n={len(idx)}")
