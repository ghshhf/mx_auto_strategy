# -*- coding: utf-8 -*-
"""
跨资产 / 全球 ETF 池再平衡系统性测试

数据: us_etf_weekly_adjclose.csv (Twelve Data 美股 ETF 宇宙 56 标的)
      equities_weekly_adjclose.csv (腾讯行情 港股3 + AMD)
口径: 周 -> 月末; 等权; 死拿(初始权重自然漂移) vs 再平衡(月度拉回等权)
判定: 超额 = 再平衡 CAGR - 死拿 CAGR
"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ETF = os.path.join(HERE, "data", "us_etf_weekly_adjclose.csv")
EQ = os.path.join(HERE, "data", "equities_weekly_adjclose.csv")

etf = pd.read_csv(ETF, index_col=0, parse_dates=True)
eq = pd.read_csv(EQ, index_col=0, parse_dates=True)
allp = pd.concat([etf, eq], axis=1).sort_index()
allp = allp[~allp.index.duplicated()]
m = allp.resample("ME").last()


def run(tag, cols, rule="M"):
    cols = [c for c in cols if c in m.columns]
    sub = m[cols].dropna()
    if len(sub) < 36:
        print(f"  {tag:26s} 数据不足")
        return None
    r = (sub / sub.shift(1)).dropna()          # 增长因子
    if rule == "Q":
        r = r.resample("QE").prod()
    npy = 4 if rule == "Q" else 12
    years = len(r) / npy
    w0 = np.full(len(cols), 1.0 / len(cols))

    bh = np.cumprod(r.values @ w0)             # 死拿
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
    vol = r.std().mean() * np.sqrt(npy) * 100
    # 池内收益离散度: 长期倍数 max/min —— 越小越适合再平衡
    mult = sub.iloc[-1] / sub.iloc[0]
    spread = mult.max() / mult.min()
    print(f"  {tag:26s} 再平衡 {rb[-1]:6.2f}x  死拿 {bh[-1]:6.2f}x  超额 {ex:+6.2f} pp/y  "
          f"MDD {dd_r:5.1%}/{dd_b:5.1%}  倍差 {spread:6.1f}x  ({years:.1f}y, {r.index[0].date()}起)")
    return ex


print("=" * 130)
print("【A】用户点名的 5 标的 (含日股 ETF 腿)")
print("=" * 130)
run("腾讯+中海油+紫金+AMD", ["700_HK_TENCENT", "883_HK_CNOOC", "2899_HK_ZIJIN", "AMD"])
run("+EWJ 日股腿", ["700_HK_TENCENT", "883_HK_CNOOC", "2899_HK_ZIJIN", "AMD", "EWJ"])
run("港股3+日股ETF", ["700_HK_TENCENT", "883_HK_CNOOC", "2899_HK_ZIJIN", "EWJ"])

print("\n" + "=" * 130)
print("【B】国家 ETF 池 (各市场长期收益应较接近 -> 预期正超额)")
print("=" * 130)
run("日港德英", ["EWJ", "EWH", "EWG", "EWU"])
run("日港德英巴印", ["EWJ", "EWH", "EWG", "EWU", "EWZ", "INDA"])
run("发达+新兴", ["EFA", "EEM", "EWJ", "EWG"])
run("中国系", ["FXI", "MCHI", "KWEB", "EWH"])

print("\n" + "=" * 130)
print("【C】商品 ETF 池 (量级接近 -> 预期正超额)")
print("=" * 130)
run("金+银+铂+钯", ["GLD", "SLV", "PPLT", "PALL"])
run("金+油+气+农+金属", ["GLD", "USO", "UNG", "DBA", "DBB"])
run("能源(油气)", ["USO", "UNG", "XLE"])
run("农产品", ["DBA", "CORN", "WEAT", "SOYB"])

print("\n" + "=" * 130)
print("【D】债券 / 股债")
print("=" * 130)
run("债券梯度", ["TLT", "IEF", "LQD", "HYG", "TIP"])
run("股债 60/40", ["SPY", "TLT"])
run("股债商", ["SPY", "TLT", "DBC", "GLD"])

print("\n" + "=" * 130)
print("【E】行业 ETF 池")
print("=" * 130)
run("9大行业", ["XLF", "XLE", "XLK", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB"])
run("防御4行业", ["XLV", "XLP", "XLU", "XLK"])
run("周期4行业", ["XLE", "XLF", "XLI", "XLB"])

print("\n" + "=" * 130)
print("【F】全球多资产混合")
print("=" * 130)
run("股+债+金+商品+新兴", ["SPY", "TLT", "GLD", "DBC", "EEM"])
run("股+债+金+商品+新兴+日", ["SPY", "TLT", "GLD", "DBC", "EEM", "EWJ"])
run("全类别12资产", ["SPY", "QQQ", "IWM", "EFA", "EEM", "EWJ", "TLT", "LQD", "GLD", "DBC", "VNQ", "HYG"])
run("全类别12资产 季度", ["SPY", "QQQ", "IWM", "EFA", "EEM", "EWJ", "TLT", "LQD", "GLD", "DBC", "VNQ", "HYG"], "Q")

print("\n" + "=" * 130)
print("【G】频率敏感性")
print("=" * 130)
for rule in ["M", "Q"]:
    run(f"金+银+铂+钯 {rule}", ["GLD", "SLV", "PPLT", "PALL"], rule)
    run(f"日港德英 {rule}", ["EWJ", "EWH", "EWG", "EWU"], rule)
    run(f"债券梯度 {rule}", ["TLT", "IEF", "LQD", "HYG", "TIP"], rule)
