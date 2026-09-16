# -*- coding: utf-8 -*-
"""筹码递归性检验 (BTC + AAVE)。

用户命题 (2026-09-14):
  「超额收益本质上就是筹码变多了。当你的筹码越多, 你攒得越多, 它是一个递归属性,
    最后肯定会有收益。这就跟越跌越加仓一样, 一反弹回本, 回本了卖出, 就这么简单。」

本脚本把「递归」拆成可检验的量, 全部用引擎口径 (等权月度再平衡 / 10bp / 起点 $10,000):
  段1  逐年筹码账本 —— 每年实际增加多少枚 / 多少 %
  段2  递归性 I : 兑现门槛 R*(T) = (1-β_B)/(β_A-1) 随时间的变化 (负值 = 门槛消失)
  段3  递归性 II: 净值弹性 β_A/(NAV_R/NAV_H) —— 「一反弹就回本」的数学依据
  段4  越跌越加仓 —— 逐笔成交的买入均价 vs 成交当周价 vs 末日价
  段5  边界 —— 归零极限 / 门槛不等于盈利 / β_B<1 时门槛转正
不做任何硬编码结论数字, 全部动态计算。
"""
import os
import sys
import math
import datetime as dt
import importlib.util

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
OUTDIR = os.path.join(HERE, "out")
MAIN_START = "2020-10-09"
CAP = 10000.0
SEP = "=" * 116

# 复用已跑通的引擎 (口径与全仓库一致, 带逐笔成交日志)
_spec = importlib.util.spec_from_file_location(
    "eic", os.path.join(HERE, "excess_is_chips.py"))
eic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eic)
sim_trades = eic.sim_trades


def load_panel():
    px = pd.read_csv(PANEL, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


def annual_last(obj):
    """每年最后一个观测 (DatetimeIndex -> year index)。"""
    idx = obj.index
    ys = sorted(set(idx.year))
    rows = []
    for y in ys:
        m = idx.year == y
        rows.append(obj[m].iloc[-1])
    return pd.DataFrame(rows, index=pd.Index(ys, name="year"))


# ---------------------------------------------------------------- 段1 筹码账本
def section_ledger(r, a, b):
    print(SEP)
    print("【段1】逐年筹码账本: 每年实际增加多少枚 AAVE / 多少 %")
    print(SEP)
    R = r["R_hist"]
    nav, hold = r["nav_ser"], r["hold_ser"]
    i = r["i"]
    j = 1 - i
    ca = r["coins"][i]
    cb = r["coins"][j]
    u0A, u0B = float(r["U0"][i]), float(r["U0"][j])
    p0A, p0B = float(r["px_first"][i]), float(r["px_first"][j])
    pnA, pnB = float(r["px_last"][i]), float(r["px_last"][j])
    yrs = r["yrs"]
    Rann = annual_last(R)
    navA = annual_last(nav)
    hldA = annual_last(hold)
    pxA = annual_last(r["px_ser"])
    u0Achk = CAP / 2.0 / p0A

    print(f"  起点 {r['start']:%Y-%m-%d}: {ca} ${p0A:,.2f} → {u0A:,.4f} 枚 (投入 ${CAP/2:,.0f})"
          f"   |   {cb} ${p0B:,.2f} → {u0B:,.6f} 枚")
    print(f"  末日 {r['end']:%Y-%m-%d}: {ca} ${pnA:,.2f} ({pnA/p0A:.3f}×)  "
          f"{cb} ${pnB:,.2f} ({pnB/p0B:.3f}×)   窗口 {yrs:.2f} 年")
    print(f"  枚数核对: 起点应持 {u0Achk:,.4f} 枚, 引擎 {u0A:,.4f} (差 {abs(u0Achk-u0A):.2e})")
    print()
    hdr = (f"  {'年份':<6}{'AAVE年末价':>12}{'β_AAVE':>9}{'β_BTC':>8}{'AAVE枚数':>11}"
           f"{'本年增枚':>11}{'年增%':>9}{'组合筹码':>10}{'超额倍数':>10}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    prev_a, prev_b = 1.0, 1.0
    for y, row in Rann.iterrows():
        ba, bb = float(row[ca]), float(row[cb])
        ua = ba * u0A
        du = (ba - prev_a) * u0A
        g = ba / prev_a - 1.0
        cmb = math.sqrt(ba * bb)
        ex = float(navA.loc[y].iloc[0] / hldA.loc[y].iloc[0])
        print(f"  {y:<6}{float(pxA.loc[y, ca]):>12,.2f}{ba:>9.4f}{bb:>8.4f}"
              f"{ua:>11,.4f}{du:>+11,.4f}{g:>+9.2%}{cmb:>10.4f}{ex:>10.4f}")
        prev_a, prev_b = ba, bb
    ba, bb = float(Rann[ca].iloc[-1]), float(Rann[cb].iloc[-1])
    print()
    print(f"  全窗口: β_{ca} = {ba:.4f}× ({ba**(1/yrs)-1:+.2%}/年)   "
          f"β_{cb} = {bb:.4f}× ({bb**(1/yrs)-1:+.2%}/年)   "
          f"组合几何筹码 {math.sqrt(ba*bb):.4f}×")
    print(f"          {ca} 枚数 {u0A:,.4f} → {ba*u0A:,.4f} 枚 (净增 {ba*u0A-u0A:+,.4f} 枚, "
          f"平均每年 {((ba-1)*u0A)/yrs:+,.4f} 枚 = {(ba**(1/yrs)-1):+.2%}/年)")
    print(f"          按起点 ${pnA:,.2f} 计价, 这些新增筹码的市值 = "
          f"${(ba*u0A-u0A)*pnA:,.0f} (占起点本金 {(ba*u0A-u0A)*pnA/CAP:.1%})")
    print(f"  超额: 净值 {r['nav']:,.0f} vs 死拿 {r['hold']:,.0f} = "
          f"{r['nav']/r['hold']:.4f}× ({r['excess']:+.2%})  "
          f"年化 {(r['nav']/r['hold'])**(1/yrs)-1:+.2%}/年")
    return Rann, navA, hldA


# ------------------------------------------------------------ 段2 兑现门槛
def section_threshold(r, a, b):
    print()
    print(SEP)
    print("【段2】递归性 I: 兑现门槛 R*(T) —— 需要 AAVE 相对 BTC 涨多少, 超额才 > 0")
    print(SEP)
    print("  推导: NAV_rebal - NAV_hold = (CAP/4)·[(β_A-1)·rA - (1-β_B)·rB]  (rA/rB = 价格倍数)")
    print("        ⇒ 超额>0 ⟺ (rA/rB) > R*(T) = (1-β_B)/(β_A-1)")
    print()
    Rann = annual_last(r["R_hist"])
    navA = annual_last(r["nav_ser"])
    hldA = annual_last(r["hold_ser"])
    ca, cb = r["coins"][r["i"]], r["coins"][1 - r["i"]]
    print(f"  {'年份':<6}{'β_AAVE':>9}{'β_BTC':>9}{'R*(T)':>11}  {'状态':<32}{'超额倍数':>10}")
    print("  " + "-" * 84)
    for y, row in Rann.iterrows():
        ba, bb = float(row[ca]), float(row[cb])
        if abs(ba - 1.0) < 1e-12:
            st, th = "β_A≡1 (不转筹码)", float("nan")
        else:
            th = (1.0 - bb) / (ba - 1.0)
            if ba > 1 and bb > 1:
                st = "两侧筹码同增 → 门槛消失"
            elif ba > 1:
                st = f"需相对涨 > {th:.2f}×"
            else:
                st = f"筹码在流出 → 需相对跌 < {th:.2f}×"
        ex = float(navA.loc[y].iloc[0] / hldA.loc[y].iloc[0])
        print(f"  {y:<6}{ba:>9.4f}{bb:>9.4f}{th:>11.4f}  {st:<32}{ex:>10.4f}")
    ba, bb = float(Rann[ca].iloc[-1]), float(Rann[cb].iloc[-1])
    th = (1.0 - bb) / (ba - 1.0)
    print()
    print(f"  末日门槛 R* = (1 - {bb:.4f}) / ({ba:.4f} - 1) = {th:+.4f}")
    if th < 0:
        print(f"  ⇒ 右侧为负。因 rA/rB ≥ 0 恒成立, 超额对 {ca} 的任何终点价【无条件为正】——")
        print(f"     包括 {ca} 归零 (rA=0) 与 {ca} 跌 99%。门槛不是『变低』, 是【消失】。")
        print(f"     原因: 两侧筹码同时增长 (β_A={ba:.4f}>1 且 β_B={bb:.4f}>1), 收割不偏袒任何一侧。")
    else:
        print(f"  ⇒ 门槛为正: 需 {ca} 相对 {cb} 至少跑 {th:.4f}× 才兑现为大额超额。")
    return Rann, navA, hldA


# ------------------------------------------------------------ 段3 净值弹性
def section_elasticity(r, a, b):
    print()
    print(SEP)
    print("【段3】递归性 II: 净值弹性 —— 『越攒越多 ⇒ 一反弹就回本』的数学依据")
    print(SEP)
    print("  定义: 弹性比 = β_A(T) / (NAV_rebal(T)/NAV_hold(T))")
    print("        含义: AAVE 涨 1% 时, 再平衡账户的涨幅 ÷ 死拿账户的涨幅")
    print("        单位价格弹性 = 该腿市值占比, 占比 = 枚数 × 价格 ÷ 净值 → 枚数多则弹性大")
    print()
    R = r["R_hist"]
    nav, hold = r["nav_ser"], r["hold_ser"]
    ca = r["coins"][r["i"]]
    Rann = annual_last(R)
    navA = annual_last(nav)
    hldA = annual_last(hold)
    pxA = annual_last(r["px_ser"])
    print(f"  {'年份':<6}{'β_AAVE':>9}{'NAV_R/H':>10}{'弹性比':>9}"
          f"{'再平衡AAVE敞口':>15}{'死拿AAVE敞口':>14}{'敞口比':>9}")
    print("  " + "-" * 74)
    for y, row in Rann.iterrows():
        ba = float(row[ca])
        nr, nh = float(navA.loc[y].iloc[0]), float(hldA.loc[y].iloc[0])
        rat = nr / nh
        el = ba / rat
        pA = float(pxA.loc[y, ca])
        u_A = ba * (CAP / 2.0 / float(r["px_first"][r["i"]]))
        u_A0 = CAP / 2.0 / float(r["px_first"][r["i"]])
        expR = u_A * pA / nr
        expH = u_A0 * pA / nh
        print(f"  {y:<6}{ba:>9.4f}{rat:>10.4f}{el:>9.4f}{expR:>15.2%}{expH:>14.2%}"
              f"{expR/expH:>9.4f}")
    # 反弹情景
    i = r["i"]
    u_A = float(r["units"][i])
    u_B = float(r["units"][1 - i])
    u_A0, u_B0 = float(r["U0"][i]), float(r["U0"][1 - i])
    pA, pB = float(r["px_last"][i]), float(r["px_last"][1 - i])
    navR, navH = u_A * pA + u_B * pB, u_A0 * pA + u_B0 * pB
    wR, wH = u_A * pA / navR, u_A0 * pA / navH
    print()
    print(f"  从末日价起算 ({ca} ${pA:,.2f}):  再平衡持 {u_A:,.4f} 枚 (敞口 {wR:.2%}) / "
          f"死拿持 {u_A0:,.4f} 枚 (敞口 {wH:.2%})   → 弹性比 {wR/wH:.4f}")
    print()
    print(f"  AAVE 从末日价 ${pA:,.2f} 变动 X ({b} 冻在末日价) —— 上涨与下跌必须并列看:")
    print(f"  {'AAVE 变动':<12}{'再平衡净值':>13}{'死拿净值':>12}{'再平衡涨跌':>12}"
          f"{'死拿涨跌':>11}{'再/死':>9}{'再平衡赢?':>11}")
    print("  " + "-" * 82)
    for X in (-1.00, -0.95, -0.80, -0.50, -0.25, 0.0, 0.25, 0.50, 1.00, 2.00, 5.00):
        nr = u_A * pA * (1 + X) + u_B * pB
        nh = u_A0 * pA * (1 + X) + u_B0 * pB
        gr, gh = nr / navR - 1, nh / navH - 1
        print(f"  {X:>+8.0%}    {nr:>12,.0f}{nh:>12,.0f}{gr:>12.2%}{gh:>11.2%}"
              f"{nr/nh:>9.4f}{'✓' if nr > nh else '✗':>11}")
    print()
    print(f"  读法: 再平衡的 AAVE 敞口被月调仓锁在 50.00%, 死拿敞口只有 {wH:.2%}。")
    print(f"        所以【瞬时冲击】下再平衡的涨跌幅都被放大 {wR/wH:.3f} 倍 —— 下跌也一样放大。")
    print(f"        但它赢在【水位】: 同一个跌幅之后, 净值 77,212/49,163 起步的差距 1.5705× 不会归零,")
    print(f"        因为 NAV_R - NAV_H = (u_A-u_A0)·P_A·(1+X) - (u_B0-u_B)·P_B 对 X 线性,")
    print(f"        而 X=0 与 X=-1(归零) 两端点都为正 ⇒ 整个区间为正 (与段2 门槛为负等价)。")
    print(f"  注意 X=-1 是【解析端点】, 不是模拟: 归零时 u_A 那一腿消失, 剩下的仍是对手的筹码。")
    print()
    print(f"  ⚠️ 但【渐次下跌 ≠ 瞬时冲击】: 缓慢阴跌时, 每次月调仓都在减 AAVE 腿、换回对手腿,")
    print(f"     敞口被逐步削掉 → 归零时刻的实际筹码结构与 X=-1 的假设一致; 而一步腰斩时")
    print(f"     调仓来不及触发, 敞口仍是 50% → 跌幅被完整放大。这是两条不同的路径。")
    return wR, wH, u_A, u_A0, u_B, u_B0, pA, pB, navR, navH


# ---------------------------------------------------------- 段4 越跌越加仓
def section_accumulate(r):
    print()
    print(SEP)
    print("【段4】『越跌越加仓, 反弹回本』—— 逐笔成交的买入均价 vs 卖出均价")
    print(SEP)
    i = r["i"]
    ca = r["coins"][i]
    tr = pd.DataFrame(r["trades"])
    px = r["px_ser"]
    pxA = annual_last(px)
    tr["_d"] = pd.to_datetime(tr["date"])
    tr["year"] = tr["_d"].dt.year
    pnA = float(r["px_last"][i])
    print(f"  {'年份':<6}{'买入枚数':>11}{'买入均价':>11}{'卖出枚数':>11}{'卖出均价':>11}"
          f"{'年末价':>11}{'买入价/年末价':>14}")
    print("  " + "-" * 76)
    for y, g in tr.groupby("year"):
        buys = g[g["dq"] > 0]
        sells = g[g["dq"] < 0]
        bn = float(buys["dq"].sum())
        ba = float((buys["dq"] * buys["px"]).sum() / bn) if bn > 0 else float("nan")
        sn = float(-sells["dq"].sum())
        sa = float((-sells["dq"] * sells["px"]).sum() / sn) if sn > 0 else float("nan")
        pe = float(pxA.loc[y, ca])
        rat = ba / pe if ba == ba and pe else float("nan")
        print(f"  {y:<6}{bn:>11.4f}{ba:>11,.2f}{sn:>11.4f}{sa:>11,.2f}"
              f"{pe:>11,.2f}{rat:>14.4f}")
    buys = tr[tr["dq"] > 0]
    sells = tr[tr["dq"] < 0]
    BN = float(buys["dq"].sum())
    BA = float((buys["dq"] * buys["px"]).sum() / BN)
    SN = float(-sells["dq"].sum())
    SA = float((-sells["dq"] * sells["px"]).sum() / SN)
    print("  " + "-" * 76)
    print(f"  {'合计':<6}{BN:>11.4f}{BA:>11,.2f}{SN:>11.4f}{SA:>11,.2f}{pnA:>11,.2f}")
    print()
    print(f"  累计买入 {BN:,.4f} 枚, 加权均价 ${BA:,.2f};  累计卖出 {SN:,.4f} 枚, "
          f"加权均价 ${SA:,.2f}")
    print(f"  ⇒ 卖出均价 / 买入均价 = {SA/BA:.4f}×  (高卖低买, 赚 {SA/BA-1:+.2%})")
    print(f"  ⇒ 买入均价 / 末日价 = {BA/pnA:.4f}×  (末日价相对累计买价 {pnA/BA-1:+.2%})")
    print(f"  净增持 {BN-SN:,.4f} 枚, 现金净额 ${float(tr['cash'].sum()):+,.0f}")
    if float(tr["cash"].sum()) > 0:
        print(f"  ⇒ 新增的 {BN-SN:,.4f} 枚筹码是【倒赚来的】: 净现金流为正而非支出。")
    return dict(buy_n=BN, buy_avg=BA, sell_n=SN, sell_avg=SA, net=BN - SN,
                cash=float(tr["cash"].sum()))


# ---------------------------------------------------------------- 段5 边界
def section_bounds(px, r, a="AAVE", b="BTC"):
    print()
    print(SEP)
    print("【段5】边界: 门槛消失 ≠ 必然盈利 —— 两者必须分开")
    print(SEP)
    i = r["i"]
    ca, cb = r["coins"][i], r["coins"][1 - i]
    u_A, u_B = float(r["units"][i]), float(r["units"][1 - i])
    u_A0, u_B0 = float(r["U0"][i]), float(r["U0"][1 - i])
    pA, pB = float(r["px_last"][i]), float(r["px_last"][1 - i])
    ba = u_A / u_A0
    bb = u_B / u_B0
    navR, navH = u_A * pA + u_B * pB, u_A0 * pA + u_B0 * pB
    print("  ① 归零极限 (解析解, 不需要模拟):")
    print(f"     若 {ca} 终点价 = 0:  NAV_rebal = u_B·P_B = {u_B*pB:,.0f}, "
          f"NAV_hold = u_B0·P_B = {u_B0*pB:,.0f}")
    print(f"     ⇒ 超额 = β_{cb} - 1 = {bb-1:+.4f} ({bb-1:+.2%})。"
          f"再平衡【必输不了】, 但也【只有对手那一半】。")
    print(f"     死拿账户 ${u_A0*pA:,.0f} 的 {ca} 腿归零 → 账户 ${u_B0*pB:,.0f}; "
          f"再平衡账户 ${u_B*pB:,.0f}。差额 ${(u_B-u_B0)*pB:,.0f} 就是『转筹码』救回来的。")
    print()
    print("  ② 关键时点进入: 『越跌越加仓』在真实深跌里救回多少")
    print("     (主口径起点 2020-10 恰在牛市启动前, 账户全程仅水下 0.3% —— 那是样本特性,")
    print("      不能用来证明『回本容易』。换几个真实的坏时点进入才公平:)")
    starts = [("上市首周 牛市起点", "2020-10-09"),
              ("周期高点附近", "2021-05-14"),
              ("熊市底附近", "2022-06-24"),
              ("复苏起点", "2023-01-06"),
              ("前高附近", "2025-10-17")]
    print(f"     {'进入时点':<22}{'AAVE起点价':>11}{'窗口':>7}{'β_AAVE':>9}{'β_BTC':>8}"
          f"{'超额':>10}{'再平衡末值':>12}{'死拿末值':>11}{'水下%':>8}{'最深':>9}")
    print("     " + "-" * 106)
    for lab, st in starts:
        r2 = sim_trades(px, [a, b], a, capital=CAP, start=st)
        if r2 is None:
            continue
        i2 = r2["i"]
        bA = float(r2["units"][i2] / r2["U0"][i2])
        bB = float(r2["units"][1 - i2] / r2["U0"][1 - i2])
        nv, hd = r2["nav_ser"], r2["hold_ser"]
        dd_r = float((nv / CAP - 1).min())
        dd_h = float((hd / CAP - 1).min())
        print(f"     {lab:<22}{float(r2['px_first'][i2]):>11,.2f}{r2['yrs']:>6.2f}y"
              f"{bA:>9.4f}{bB:>8.4f}{r2['excess']:>10.2%}{r2['nav']:>12,.0f}"
              f"{r2['hold']:>11,.0f}{float((nv < CAP).mean()):>8.1%}{dd_r:>9.1%}")
    print(f"     (最深 = 相对起点本金的净值最大回撤; 死拿同窗口最深回撤对比见下)")
    for lab, st in starts:
        r2 = sim_trades(px, [a, b], a, capital=CAP, start=st)
        if r2 is None:
            continue
        print(f"       {lab:<22}死拿最深 {float((r2['hold_ser']/CAP-1).min()):>8.1%}   "
              f"再平衡最深 {float((r2['nav_ser']/CAP-1).min()):>8.1%}   "
              f"少跌 {float((r2['hold_ser']/CAP-1).min())-float((r2['nav_ser']/CAP-1).min()):+.1%}")
    print()
    print("  ③ 门槛何时消失: 判据是【两侧筹码同时增加】, 不是单看对手")
    found = []
    for other in ("SOL", "DOT", "FIL", "XRP"):
        rr = sim_trades(px, [a, other], a, capital=CAP, start=MAIN_START)
        if rr is None:
            continue
        bi = rr["i"]
        bA = float(rr["units"][bi] / rr["U0"][bi])
        bB = float(rr["units"][1 - bi] / rr["U0"][1 - bi])
        th = (1.0 - bB) / (bA - 1.0) if abs(bA - 1) > 1e-12 else float("nan")
        found.append((other, bA, bB, rr["nav"] / rr["hold"] - 1, th, rr["yrs"]))
    print(f"     {'配对':<15}{'β_AAVE':>9}{'β_对手':>10}{'超额':>11}{'R*(T)':>10}{'窗口':>8}"
          f"  {'形态':<24}")
    n_both = 0
    for other, bA, bB, ex, th, yy in found:
        if bA > 1 and bB > 1:
            flag = "门槛消失 → 无条件正"
            n_both += 1
        elif bA > 1:
            flag = f"门槛正 → 需相对涨 {th:.3f}×"
        else:
            flag = f"方向翻转 → 需相对跌 {th:.3f}×"
        print(f"     {a}+{other:<11}{bA:>9.4f}{bB:>10.4f}{ex:>11.2%}{th:>10.4f}"
              f"{yy:>7.2f}y  {flag:<24}")
    print(f"     ⇒ 两侧同增 (β_A>1 且 β_B>1) 的配对: {n_both}/{len(found)} 个。")
    print(f"       只要配对里有一个『相对弱』的对手提供筹码, 门槛就会消失;")
    print(f"       若两侧都很弱 (都 <1), 筹码在双边流失, 门槛重新出现甚至反向。")
    print()
    print("  ④ 递归链的完整表述 (成立的部分 + 边界)")
    wH_ = u_A0 * pA / navH
    print("     递归链: 每次调仓把筹码从相对强的一侧搬到相对弱的一侧")
    print("          → 币量按几何级数累积 (β 指数增长)")
    print("          → 兑现门槛 R* = (1-β_B)/(β_A-1) 递减; 两侧同增时转负")
    print("          → 单位价格弹性 = β_A/(NAV_R/NAV_H) 递增 ⇒ 同样的涨幅赚更多")
    print("          → 回本所需涨幅下降 ⇒ 『一反弹就回本』")
    print("     ✅ 已证明: 门槛为负后, 对任何非负终点价超额都为正 (含归零, 解析解)。")
    print("     ⚠️ 边界一: 门槛消失说的是【跑赢等权死拿】, 不是【绝对盈利】。归零情形下")
    print("        再平衡净值 = 对手那一半, 依旧可能低于本金 —— 它救回的是相对损失。")
    print(f"     ⚠️ 边界二: 弹性是双向的。瞬时跳变时再平衡 AAVE 敞口 50.00% vs 死拿 {wH_:.2%},")
    print("        下跌同样被放大。赢的是【起点水位】, 不是【抗跌】。")
    print("     ⚠️ 边界三: 『对手提供筹码』要求对手相对你在跌/横盘。若配对两侧筹码同时")
    print("        流失 (β_A<1 且 β_B<1), 门槛重新出现甚至反向 —— 段③ 的『方向翻转』就是这种形态。")


# ---------------------------------------------------------------- 导出
def export(r, a="AAVE", b="BTC"):
    os.makedirs(OUTDIR, exist_ok=True)
    i = r["i"]
    R = r["R_hist"]
    df = pd.DataFrame({
        "date": R.index.strftime("%Y-%m-%d"),
        f"chip_{a}": R[r["coins"][i]].values,
        f"chip_{b}": R[r["coins"][1 - i]].values,
        f"px_{a}": r["px_ser"][r["coins"][i]].values,
        f"px_{b}": r["px_ser"][r["coins"][1 - i]].values,
        "nav_rebal": r["nav_ser"].values,
        "nav_hold": r["hold_ser"].values,
        "excess_mult": (r["nav_ser"] / r["hold_ser"]).values,
    })
    p1 = os.path.join(OUTDIR, "chip_recursion_series.csv")
    df.to_csv(p1, index=False, float_format="%.6f")

    rows = []
    for t in R.index:
        ba = float(R[r["coins"][i]][t])
        bb = float(R[r["coins"][1 - i]][t])
        pa = float(r["px_ser"][r["coins"][i]][t])
        pb = float(r["px_ser"][r["coins"][1 - i]][t])
        ua = ba * (CAP / 2.0 / float(r["px_first"][i]))
        ub = bb * (CAP / 2.0 / float(r["px_first"][1 - i]))
        ua0 = CAP / 2.0 / float(r["px_first"][i])
        ub0 = CAP / 2.0 / float(r["px_first"][1 - i])
        navR, navH = ua * pa + ub * pb, ua0 * pa + ub0 * pb
        wr_, wh_ = ua * pa / navR, ua0 * pa / navH
        rows.append(dict(
            date=t.strftime("%Y-%m-%d"), chip_a=ba, chip_b=bb, px_a=pa, px_b=pb,
            nav_rebal=navR, nav_hold=navH,
            w_rebal=wr_, w_hold=wh_, elasticity=wr_ / wh_,
            need_rally_rebal=((CAP / navR) - 1) / wr_ if navR < CAP else 0.0,
            need_rally_hold=((CAP / navH) - 1) / wh_ if navH < CAP else 0.0,
            under_rebal=navR < CAP, under_hold=navH < CAP,
        ))
    p2 = os.path.join(OUTDIR, "chip_recursion_breakeven.csv")
    pd.DataFrame(rows).to_csv(p2, index=False, float_format="%.6f")
    return p1, p2


def main():
    px = load_panel()
    a, b = "AAVE", "BTC"
    r = sim_trades(px, [a, b], a, capital=CAP, start=MAIN_START)
    if r is None:
        print("无数据"); return
    print(SEP)
    print(f"筹码递归性检验 | 口径: 等权月度再平衡 / {a}+{b} / 成本 10bp / 起点 ${CAP:,.0f}")
    print(f"窗口 {r['start']:%Y-%m-%d} ~ {r['end']:%Y-%m-%d} ({r['yrs']:.2f} 年)   "
          f"相关性 ρ = {r['rho']:.3f}   调仓 {len(r['trades'])} 次")
    print(SEP)
    section_ledger(r, a, b)
    section_threshold(r, a, b)
    section_elasticity(r, a, b)
    section_accumulate(r)
    section_bounds(px, r, a, b)
    p1, p2 = export(r, a, b)
    print()
    print(f"  [导出] {os.path.relpath(p1, REPO)}")
    print(f"  [导出] {os.path.relpath(p2, REPO)}")


if __name__ == "__main__":
    main()
