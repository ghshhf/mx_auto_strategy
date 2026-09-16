# -*- coding: utf-8 -*-
"""生成 1988-2026 账户曲线的 SVG 坐标（对数纵轴）。"""
import json, math, os

ROOT = os.path.dirname(os.path.abspath(__file__))
j = json.load(open(os.path.join(ROOT, "out", "real_window_result.json"), encoding="utf-8"))

ys = j["B_four_510880"]["year_snap"]
yrs = [int(y) for y in sorted(ys)]
eq = [ys[str(y)]["e"] / 1e4 for y in yrs]
ci = [ys[str(y)]["c"] / 1e4 for y in yrs]
# 补 2026 年中（终值）
yrs.append(2026)
eq.append(j["B_four_510880"]["final"] / 1e4)
ci.append(j["B_four_510880"]["invested"] / 1e4)

X0, X1 = 58.0, 638.0
Y0, Y1 = 52.0, 356.0
LO, HI = 0.7, 1200.0
lg = lambda v: (math.log10(max(v, LO)) - math.log10(LO)) / (math.log10(HI) - math.log10(LO))
xp = lambda i: X0 + i * (X1 - X0) / (len(yrs) - 1)
yp = lambda v: Y1 - lg(v) * (Y1 - Y0)


def path(vals):
    return "M" + " L".join(f"{xp(i):.1f},{yp(v):.1f}" for i, v in enumerate(vals))


print("VIEWBOX_H", 430)
print("EQ_PATH", path(eq))
print("CI_PATH", path(ci))
print("AREA", path(eq) + f" L{xp(len(eq)-1):.1f},{Y1:.1f} L{X0:.1f},{Y1:.1f} Z")
for v in (1, 10, 100, 1000):
    print(f"GRID_{v}W y={yp(v):.1f}  label={v}万")
print("YOUNG_1000W_y", f"{yp(1000):.1f}")
print()
print("--- 关键点 ---")
for y, tag in [(1999, "1999泡沫顶"), (2002, "2002谷底"), (2008, "2008"), (2013, "破百万"),
               (2021, "2021顶"), (2022, "2022谷"), (2026, "2026终值")]:
    i = yrs.index(y)
    print(f"{y} {tag:10s} x={xp(i):.1f} y={yp(eq[i]):.1f}  市值{eq[i]:.1f}万 投入{ci[i]:.1f}万")
print()
print("--- 年末点（画散点用）---")
for i, y in enumerate(yrs):
    print(f"{y} ({xp(i):.1f},{yp(eq[i]):.1f})")
print()
print("X 轴刻度:")
for y in (1990, 2000, 2010, 2020, 2026):
    i = yrs.index(y)
    print(f"  {y} x={xp(i):.1f}")
