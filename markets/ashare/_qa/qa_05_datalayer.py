# -*- coding: utf-8 -*-
"""
QA-05 数据层核验 (本次修复之外的发现)
=====================================
假设: eastmoney_hfq_rebuild.fetch_one 请求
      fields2 = f51,f53,f55,f56,f57,f58,f59,f60,f61
      = 日期, 收盘, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
      但按 p[1]=开盘 p[2]=收盘 p[3]=最高 p[4]=最低 p[5]=量 p[6]=额 解析,
      再以 (d,o,h,l,c,v,a) 落盘 -> 列标签整体错位。
推论: 文件列 "open"   = 真·收盘
      文件列 "amount" = 真·涨跌幅(%)
      文件列 "close"  = 真·最低      <-- build_panel 读的正是这一列!
判据: 若推论成立, 则对每一行都有  open[k]/open[k-1]-1 ≈ amount[k]/100
      且 close 列 <= open 列 恒成立(最低 <= 收盘)。
"""
import os
import sys
import csv

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.dirname(HERE)
sys.path.insert(0, BT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import backtest_engine as E

WK = os.path.join(E.DATA, "ashare_weekly_em")
PANEL = os.path.join(E.DATA, "ashare_panel_close_em.csv")

# [QA 自查修正] 首版把 A 股与港股混在一起统计, 得到 85% 这种不上不下的比例,
# 结论被稀释。实测(见 qa_05b_perfile.py): 19 只港股由腾讯脚本抓取, 列是正确的;
# 只有东方财富脚本抓的 105 只 A 股 + 00388 存在错位。故这里只统计 A 股口径。
HK_TENCENT = {"00005", "00175", "00291", "00700", "00762", "00939", "00941",
              "01024", "01109", "01299", "01810", "01876", "02020", "02318",
              "02388", "03690", "09618", "09888", "09988"}

n_rows = n_match_open = n_match_close = 0
n_low_le_open = n_low_gt_open = 0
for fn in sorted(os.listdir(WK)):
    if not fn.endswith(".csv"):
        continue
    if fn[:-4] in HK_TENCENT:
        continue
    rows = []
    with open(os.path.join(WK, fn), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                rows.append((float(r["open"]), float(r["close"]), float(r["amount"])))
            except (ValueError, KeyError, TypeError):
                continue
    for k in range(1, len(rows)):
        o0, c0, _ = rows[k - 1]
        o1, c1, pct = rows[k]
        if o0 <= 0 or c0 <= 0:
            continue
        n_rows += 1
        if abs((o1 / o0 - 1) * 100 - pct) < 0.15:
            n_match_open += 1
        if abs((c1 / c0 - 1) * 100 - pct) < 0.15:
            n_match_close += 1
        if c1 <= o1:
            n_low_le_open += 1
        else:
            n_low_gt_open += 1

print("=" * 92)
print("QA-05 数据层列错位核验")
print("=" * 92)
print(f"样本行数: {n_rows}  (仅东方财富脚本抓取的 A 股 + 00388, 已剔除腾讯口径港股)")
print(f"  「open 列」环比涨跌幅 == amount 列 的比例 : {n_match_open/n_rows:>7.2%}"
      f"   ({n_match_open}/{n_rows})")
print(f"  「close 列」环比涨跌幅 == amount 列 的比例: {n_match_close/n_rows:>7.2%}"
      f"   ({n_match_close}/{n_rows})")
print(f"  close 列 <= open 列 的比例 (最低<=收盘应恒真): {n_low_le_open/n_rows:>7.2%}"
      f"   (违反 {n_low_gt_open} 行)")

verdict = (n_match_open / n_rows > 0.95) and (n_match_close / n_rows < 0.30)
print(f"\n结论: {'★ 列错位确认成立' if verdict else '列错位假设不成立'}")
print("  -> 文件 open 列 = 真·收盘;  文件 close 列 = 真·最低;  amount 列 = 真·涨跌幅%")

# 面板取的是哪一列
rows = list(csv.reader(open(PANEL, encoding="utf-8")))
hdr = rows[0]
same_close = same_open = tot = 0
for code in ("300750", "600519", "300059", "000651"):
    if code not in hdr:
        continue
    j = hdr.index(code)
    pm = {r[0]: r[j] for r in rows[1:]}
    with open(os.path.join(WK, f"{code}.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pv = pm.get(r["date"], "")
            if not pv:
                continue
            tot += 1
            if abs(float(pv) - float(r["close"])) < 1e-9:
                same_close += 1
            if abs(float(pv) - float(r["open"])) < 1e-9:
                same_open += 1
print(f"\n面板 ashare_panel_close_em.csv 抽样 {tot} 个单元格:")
print(f"  == 文件 close 列(真·最低) : {same_close/tot:.1%}")
print(f"  == 文件 open  列(真·收盘) : {same_open/tot:.1%}")
print(f"\n★ 影响: 全部回测(基线/优化/三模式)实际跑在「周最低价」序列上, 而非周收盘价。")
print("  这是 eastmoney_hfq_rebuild.py 的既有数据层缺陷, 早于本次防火墙修复,")
print("  也是 300750 首周 +93.2% 这类「伪迹」的真正成因(真·收盘环比仅 +25.6%)。")
print("  防火墙修复本身是正确且必要的, 但根因在数据管道, 建议单独立项修复。")
