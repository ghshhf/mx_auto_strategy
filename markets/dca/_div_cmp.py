# -*- coding: utf-8 -*-
"""美股红利候选腿的表现对比：全历史年化 + 共同窗口 + 股息占比。"""
import csv, os, datetime as dt
import numpy as np

HIST = r"E:\xmanbian\mx_auto_strategy_repo\markets\dca\data\history"


def load(sym):
    with open(os.path.join(HIST, sym + ".csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    d = np.array([dt.date.fromisoformat(r["date"]) for r in rows])
    p = np.array([float(r["adjclose"] or r["close"]) for r in rows])
    g = np.array([float(r["close"]) for r in rows])
    return d, p, g


CAND = ["DVY", "VYM", "SCHD", "NOBL", "SPY", "IDX_SP500TR", "IDX_NDX", "IDX_HSI"]
print("各腿全历史（adjclose 含分红再投）")
print(f"{'sym':10s} {'起':11s} {'止':11s} {'年数':>5s} {'倍数':>7s} {'年化':>7s} "
      f"{'波动':>6s} {'最深跌':>7s} {'价格指数年化':>12s}")
info = {}
for s in CAND:
    try:
        d, p, g = load(s)
    except FileNotFoundError:
        print(f"{s:10s} 缺文件")
        continue
    yr = (d[-1] - d[0]).days / 365.25
    r = np.diff(np.log(p))
    gyr = (g[-1] / g[0]) ** (1 / yr) - 1
    cum = np.maximum.accumulate(p)
    dd = (p / cum - 1).min()
    info[s] = (d, p)
    print(f"{s:10s} {d[0]} {d[-1]} {yr:5.1f} {p[-1]/p[0]:6.2f}x "
          f"{(p[-1]/p[0])**(1/yr)-1:6.2%} {r.std()*np.sqrt(252):6.1%} "
          f"{dd:7.1%} {gyr:12.2%}")

# 共同窗口：四只美股红利齐全
common = dt.date(2013, 10, 10)
print(f"\n共同窗口（{common} 起，四只齐全）")
print(f"{'sym':10s} {'年化':>8s} {'波动':>7s} {'最深跌':>8s}")
for s in ["DVY", "VYM", "SCHD", "NOBL"]:
    if s not in info:
        continue
    d, p = info[s]
    i0 = int(np.searchsorted(d, common))
    d2, p2 = d[i0:], p[i0:]
    yr = (d2[-1] - d2[0]).days / 365.25
    r = np.diff(np.log(p2))
    cum = np.maximum.accumulate(p2)
    print(f"{s:10s} {(p2[-1]/p2[0])**(1/yr)-1:8.2%} {r.std()*np.sqrt(252):7.1%} "
          f"{(p2/cum-1).min():8.1%}")

# DVY vs 标普500全收益：同窗口相关性与超额
print("\nDVY 全历史 vs 标普500全收益（同窗口）")
d1, p1 = info["DVY"]
d2, p2 = info["IDX_SP500TR"]
s1 = dict(zip(d1.tolist(), p1.tolist()))
s2 = dict(zip(d2.tolist(), p2.tolist()))
ks = sorted(set(s1) & set(s2))
a = np.array([s1[k] for k in ks])
b = np.array([s2[k] for k in ks])
yr = (ks[-1] - ks[0]).days / 365.25
print(f"  窗口 {ks[0]} → {ks[-1]}  ({yr:.1f}y, {len(ks)} 天)")
print(f"  DVY        年化 {(a[-1]/a[0])**(1/yr)-1:7.2%}")
print(f"  标普500全收益 年化 {(b[-1]/b[0])**(1/yr)-1:7.2%}")
# 周频相关
wk = {}
for k, x, y in zip(ks, a, b):
    wk.setdefault(k.isocalendar()[:2], []).append((x, y))
wa, wb = [], []
for kk in sorted(wk):
    wa.append(wk[kk][-1][0])
    wb.append(wk[kk][-1][1])
wa, wb = np.array(wa), np.array(wb)
ra, rb = np.diff(np.log(wa)), np.diff(np.log(wb))
print(f"  周频相关 {np.corrcoef(ra, rb)[0,1]:.3f}   年化波动 DVY {ra.std()*np.sqrt(52):.1%} "
      f"vs 标普 {rb.std()*np.sqrt(52):.1%}")
