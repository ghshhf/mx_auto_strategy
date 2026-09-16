# -*- coding: utf-8 -*-
"""读 yearly_result.json，输出 P2 全表 + P1 分段汇总。"""
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
j = json.load(open(os.path.join(ROOT, "out", "yearly_result.json"), encoding="utf-8"))

p1, p2 = j["p1"], j["p2"]
print(f"P2 隐含股息 {p2['dv']:.2%}  窗口数 {p2['n']}  范围 {p2['windows'][0]} … {p2['windows'][-1]}")
print(f"  {'第N年':>4s} {'年龄':>4s} {'P25':>8s} {'中位':>8s} {'P75':>8s} {'最差':>8s} {'最好':>8s}")
for k in sorted(p2["stats"], key=lambda x: int(x)):
    s = p2["stats"][k]
    age = 21 + int(k)
    print(f"  {int(k):>4d} {age:>4d} {s['p25']:>7.2f}× {s['med']:>7.2f}× "
          f"{s['p75']:>7.2f}× {s['mn']:>7.2f}× {s['mx']:>7.2f}×")

rows = p1["rows"]
print("\nP1 五年分段:")
print(f"  {'年龄区间':>10s} {'期末市值':>12s} {'期末累计投入':>12s} {'该段盈亏':>12s} "
      f"{'该段投入':>10s} {'盈亏/投入':>9s} {'期末倍数':>8s}")
for i in range(0, len(rows), 5):
    seg = rows[i:i + 5]
    a, b = seg[0], seg[-1]
    inv_seg = sum(x["inv_year"] for x in seg)
    pnl_seg = b["value"] - (rows[i - 1]["value"] if i > 0 else 0.0) - inv_seg
    print(f"  {a['age']:>4d}-{b['age']:<4d} {b['value']:>12,.0f} {b['cum_inv']:>12,.0f} "
          f"{pnl_seg:>12,.0f} {inv_seg:>10,.0f} "
          f"{(pnl_seg/inv_seg if inv_seg else 0):>8.2f}× {b['ratio']:>7.2f}×")

print("\nP1 关键节点（前 12 年逐年）:")
for r in rows[:12]:
    print(f"  {r['age']} 岁（第{r['k']}年）市值 {r['value']:>10,.0f}  "
          f"累计投入 {r['cum_inv']:>9,.0f}  当年盈亏 {r['pnl']:>+10,.0f}  "
          f"倍数 {r['ratio']:>6.2f}×  当年 {r['ret']:>+7.1%}")
print("\n里程碑:")
for k, v in p1["milestones"].items():
    print(f"  {k:16s} 第{v[0]-1987}年（{v[1]} 岁）  {v[0]}年")
