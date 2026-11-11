# -*- coding: utf-8 -*-
"""一次性: 按主人实际配置复算
① 四基金日定投（红利A股 510880 / 港股红利 3110.HK / 纳指 QQQ / 标普 SPY）近2年实际结果
② 长期定投复利倍数表（与选币无关，只与时间和收益率有关）
"""
import os
import sys
import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CRY = os.path.dirname(HERE)
DCA = os.path.join(HERE, "data", "history")


def load(sym):
    p = os.path.join(DCA, f"{sym}.csv")
    d = pd.read_csv(p)
    d["date"] = pd.to_datetime(d["date"])
    d = d.set_index("date").sort_index()
    col = "adjclose" if "adjclose" in d.columns and d["adjclose"].notna().sum() > len(d) * 0.8 else "close"
    s = pd.to_numeric(d[col], errors="coerce").dropna()
    return s


LEGS = [("510880.SS", "红利A股"), ("3110.HK", "港股红利"), ("QQQ", "纳指100"), ("SPY", "标普500")]

print("=== 数据体检 ===")
series = {}
for sym, name in LEGS:
    s = load(sym)
    series[sym] = s
    print(f"  {name:8s} {sym:11s} {s.index[0].date()} ~ {s.index[-1].date()}  {len(s)} 行  末值 {s.iloc[-1]:.2f}")

print("\n=== ① 日定投近2年（2024-10-28 ~ 最新） ===")
t0 = pd.Timestamp("2024-10-28")
rows = []
for sym, name in LEGS:
    s = series[sym]
    s = s[s.index >= t0]
    if len(s) < 100:
        print(f"  {name} 数据不足")
        continue
    units = (40.0 / s).sum()          # 每交易日投 40 元
    invested = 40.0 * len(s)
    value = units * s.iloc[-1]
    rows.append(dict(name=name, sym=sym, days=len(s), invested=invested, value=value,
                     ret=(value / invested - 1) * 100,
                     px_ret=(s.iloc[-1] / s.iloc[0] - 1) * 100))
    print(f"  {name:8s} 定投 {invested:8.0f} 元 -> {value:9.2f} 元  收益 {rows[-1]['ret']:+.2f}%   "
          f"（同期一次性买入 {rows[-1]['px_ret']:+.2f}%）")

df = pd.DataFrame(rows)
tot_inv, tot_val = df.invested.sum(), df.value.sum()
print(f"\n  四只合计：投入 {tot_inv:,.0f} 元 → 现值 {tot_val:,.2f} 元  "
      f"收益 {tot_val-tot_inv:+,.2f} 元（{(tot_val/tot_inv-1)*100:+.2f}%）")
print(f"  定投 vs 一次性买入 的差距：{(tot_val/tot_inv-1)*100 - (df.px_ret*tot_inv/4).sum()/tot_inv:+.2f}pp（说明摊平成本有没有帮上忙）")

print("\n=== ② 长期定投复利倍数（月投，与选什么无关） ===")
print("  投入/年化 →    6%      8%      10%")
for yrs in (10, 20, 30):
    n = yrs * 12
    out = [f"{yrs:2d}年"]
    for r in (0.06, 0.08, 0.10):
        rm = r / 12
        fv = ((1 + rm) ** n - 1) / rm        # 每元月投的未来值
        out.append(f"{fv/n:5.2f}x")
    print("  " + "  ".join(out) + "   （账户市值 ÷ 累计投入）")
print("\n  例：每月 1600 元 × 20 年 = 累计投入 38.4 万")
for r in (0.06, 0.08, 0.10):
    rm = r / 12
    fv = 1600 * ((1 + rm) ** 240 - 1) / rm
    print(f"     年化 {r*100:.0f}% → 期末 {fv:>12,.0f} 元   （兑现 {fv-384000:>10,.0f} 元）")
