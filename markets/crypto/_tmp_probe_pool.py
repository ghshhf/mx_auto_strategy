# -*- coding: utf-8 -*-
"""探针: 面板列、各池共同窗口、n 币 sim 耗时。"""
import os, sys, time
import pandas as pd, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from excess_is_chips import sim_trades, load_panel, PANEL

px = load_panel()
print("面板", PANEL.rsplit(os.sep, 1)[-1], px.shape, px.index[0].date(), px.index[-1].date())
print("列:", list(px.columns))
print()
print("各列窗口:")
for c in px.columns:
    s = px[c].dropna()
    print(f"  {c:<7}{len(s):>5}周  {s.index[0].date()} ~ {s.index[-1].date()}")

sub = px.dropna(how="any")
print("\n全池 dropna(any):", sub.shape, sub.index[0].date(), "~", sub.index[-1].date())
main = [c for c in px.columns if len(px[c].dropna()) >= 300 and px[c].dropna().index[0] <= pd.Timestamp("2020-10-09")]
print("主口径池 n=%d:" % len(main), main)
sub2 = px[main].dropna(how="any")
print("主池 dropna(any):", sub2.shape, sub2.index[0].date(), "~", sub2.index[-1].date())
print("\n全池 dropna(any) 每列窗口:")
for c in sub.columns:
    print(f"  {c:<7}{sub[c].notna().sum():>5}周  {sub[c].first_valid_index().date()}")

for n in (2, 5, 19, 27):
    cols = list(px.columns[:n])
    t0 = time.time()
    r = sim_trades(px, cols, cols[0], start="2020-10-09")
    dt = time.time() - t0
    print(f"\nn={n:<3} 耗时 {dt*1000:.0f}ms  " + (f"超额 {r['nav']/r['hold']-1:+.2%} 筹码区间 {r['R'].min():.4f}~{r['R'].max():.4f}" if r else "None"))
