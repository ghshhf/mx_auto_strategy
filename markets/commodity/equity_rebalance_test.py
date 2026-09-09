# -*- coding: utf-8 -*-
"""
全球个股池再平衡测试 —— 用户点名的 4 标的
腾讯控股 / 中国海洋石油 / 紫金矿业 (港股 hfq) + 超威半导体 (美股)
口径: 月度收益, 等权, 死拿(初始权重自然漂移) vs 再平衡(定期拉回等权)
"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(HERE, "data", "equities_weekly_adjclose.csv")

p = pd.read_csv(PANEL, index_col=0, parse_dates=True)
m = p.resample("ME").last()


def rebalance_test(tag, cols, rule="M"):
    sub = m[cols].dropna()
    r = (sub / sub.shift(1)).dropna()
    # ⚠️ r 是增长因子(本月/上月)。季度聚合直接连乘, 不要 (1+r) —— 那会变成 2+收益
    if rule == "Q":
        r = r.resample("QE").prod()
    n_per_year = 4 if rule == "Q" else 12
    years = len(r) / n_per_year

    w0 = np.full(len(cols), 1.0 / len(cols))

    # 死拿: 初始等权买入后不再交易
    # ⚠️ r 是增长因子(本月/上月), 不是收益率 —— 直接加权, 不要 +1
    growth = r.values @ w0
    bh = np.cumprod(growth)

    # 再平衡: 每期拉回等权
    wb = w0.copy()
    rb = [1.0]
    for i in range(len(r)):
        rr = r.values[i]
        rb.append(rb[-1] * float(np.dot(wb, rr)))
        wb = wb * rr
        wb = wb / wb.sum()
    rb = np.array(rb[1:])

    ex = (rb[-1] ** (1 / years) - bh[-1] ** (1 / years)) * 100
    dd_r = (rb / np.maximum.accumulate(rb) - 1).min()
    dd_b = (bh / np.maximum.accumulate(bh) - 1).min()
    print(f"{tag:24s} 再平衡 {rb[-1]:8.1f}x (CAGR {rb[-1]**(1/years)-1:+7.2%}) "
          f"| 死拿 {bh[-1]:8.1f}x (CAGR {bh[-1]**(1/years)-1:+7.2%}) "
          f"| 超额 {ex:+6.2f} pp/y | MDD 再平衡 {dd_r:6.1%} / 死拿 {dd_b:6.1%} "
          f"| {r.index[0].date()}~{r.index[-1].date()} ({years:.1f}y)")


ALL4 = ["700_HK_TENCENT", "883_HK_CNOOC", "2899_HK_ZIJIN", "AMD_US"]
NO_TENCENT = ["883_HK_CNOOC", "2899_HK_ZIJIN", "AMD_US"]

print("=== 用户点名标的池: 死拿 vs 再平衡 ===")
rebalance_test("4币全池 月度", ALL4)
rebalance_test("4币全池 季度", ALL4, "Q")
rebalance_test("3币去腾讯 月度", NO_TENCENT)
rebalance_test("3币去腾讯 季度", NO_TENCENT, "Q")
rebalance_test("2币紫金+AMD 月度", ["2899_HK_ZIJIN", "AMD_US"])
rebalance_test("2币中海油+AMD 月度", ["883_HK_CNOOC", "AMD_US"])

print("\n=== 单币死拿 ===")
years = None
for c in ALL4:
    s = m[c].dropna()
    s = s[s.index >= "2007-04-30"]
    y = len(s) / 12
    n = s.iloc[-1] / s.iloc[0]
    dd = (s / s.cummax() - 1).min()
    print(f"  {c:18s} {n:8.1f}x  CAGR {n**(1/y)-1:+7.2%}  MDD {dd:6.1%}  ({s.index[0].date()}~{s.index[-1].date()})")

print("\n=== 相关性 / 波动率 (共同窗口月度) ===")
r = (m[ALL4].dropna() / m[ALL4].dropna().shift(1)).dropna()
print("相关性:")
print(r.corr().round(2).to_string())
print("\n年化波动率:")
print((r.std() * np.sqrt(12) * 100).round(1).to_string())
