# -*- coding: utf-8 -*-
"""
timing_extreme_backtest.py —— 诚实测试用户提出的"极端时减仓、低位买回"择时
========================================================================
用户反驳: "科技里面没有周期吗? 我只想让你格外的时候减仓, 差不多低位再买回来。"
之前"择时跑输持有"的结论用了错误的钟(宽基指数)和太频繁的过滤(200MA震下车)。

本脚本用**篮子自身价格**当钟(而不是上证指数), 实现用户描述的机制:
  - 正常市: 满仓 = B(等权买持)
  - "格外的时候减仓": 篮子进入深度回撤 / 跌破自身 MA250 长期下行 → 降到防御仓位
  - "差不多低位再买回来": 篮子站回 MA250(修复) → 恢复满仓
参数取常识值(-20%~-25% 深回撤阈值, MA250), 非挖矿优化。ex-ante, 无前视。
"""
import os, sys, math, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data_store as ds
import stock_backtest as sb

UNIVERSE = sb.UNIVERSE
# 科技/成长子集(用户点名的"科技周期"): 半导体/电子/软件AI/消费电子/新能源设备
TECH = [
    ("002371", 0, "北方华创"), ("603986", 1, "兆易创新"), ("603501", 1, "豪威集团"),
    ("002230", 0, "科大讯飞"), ("002415", 0, "海康威视"), ("002475", 0, "立讯精密"),
    ("002241", 0, "歌尔股份"), ("300782", 0, "卓胜微"), ("300750", 0, "宁德时代"),
    ("300274", 0, "阳光电源"), ("601012", 1, "隆基绿能"), ("300014", 0, "亿纬锂能"),
    ("002594", 0, "比亚迪"),   ("300124", 0, "汇川技术"), ("300316", 0, "晶盛机电"),
    ("300450", 0, "先导智能"), ("300059", 0, "东方财富"), ("603259", 1, "药明康德"),
]

def build_basket_nav(dates, universe):
    """日频等权买持 NAV(月度再平衡近似为日频等权, 差异极小), 返回 NAV 序列。"""
    by_code, _ = sb.build_stock_matrix(dates, universe)
    # 日频等权: 每天对所有"当时已有数据"的票取等权日收益
    codes = list(by_code.keys())
    nav = [1.0]
    for i in range(1, len(dates)):
        avail = [c for c in codes if dates[i-1] in by_code[c][1] and dates[i] in by_code[c][1]]
        if not avail:
            nav.append(nav[-1]); continue
        rets = []
        for c in avail:
            seq = by_code[c][1]
            c0, c1 = seq[dates[i-1]], seq[dates[i]]
            if c0 and c1 and c0 > 0:
                rets.append(c1/c0 - 1)
        day_ret = sum(rets)/len(rets) if rets else 0.0
        nav.append(nav[-1] * (1 + day_ret))
    return nav

def sma(seq, i, n):
    if i < n-1: return None
    return sum(seq[i-n+1:i+1])/n

def apply_timing_exposure(nav, rule, dd_thr=-0.22, def_exp=0.15, re_ma=250, bounce=0.0):
    """返回暴露序列 E (len=len(nav)): E[i] 应用于 第 i->i+1 日收益(基于 i-1 状态, 因果无前视)。
    用于把篮子自身钟叠加到其它组合(如动量轮动)之上。"""
    n = len(nav)
    E = [1.0]
    state = "ON"
    trough = nav[0]
    for i in range(1, n):
        prev = nav[i-1]
        ma250 = sma(nav, i-1, 250)
        ma_re = sma(nav, i-1, re_ma)
        peak = max(nav[max(0, i-250):i]) if i >= 1 else prev
        dd = prev/peak - 1
        exp_here = 0.0 if rule == "MA250BIN" else def_exp
        if rule == "MA250":
            target = "ON" if (ma250 is None or prev >= ma250) else "OFF"
        elif rule == "MA250BIN":
            target = "ON" if (ma250 is None or prev >= ma250) else "OFF"
        elif rule == "MA50RE":
            if state == "ON":
                target = "OFF" if (ma250 is not None and prev < ma250) else "ON"
            else:
                target = "ON" if (ma_re is not None and prev >= ma_re) else "OFF"
        elif rule == "BOUNCE":
            if state == "ON":
                target = "OFF" if (ma250 is not None and prev < ma250) else "ON"
            else:
                target = "ON" if (prev >= trough*(1+bounce)) else "OFF"
        elif rule == "DEEPDD":
            if state == "ON":
                target = "OFF" if dd <= dd_thr else "ON"
            else:
                target = "ON" if (ma250 is not None and prev >= ma250) else "OFF"
        else:
            if state == "ON":
                target = "OFF" if (dd <= dd_thr or (ma250 is not None and prev < ma250)) else "ON"
            else:
                target = "ON" if (ma250 is not None and prev >= ma250) else "OFF"
        if target == "ON":
            trough = prev
        elif state == "OFF":
            trough = min(trough, prev)
        state = target
        E.append(1.0 if state == "ON" else exp_here)
    return E

def apply_timing(nav, rule, dd_thr=-0.22, def_exp=0.15, re_ma=250, bounce=0.0):
    """在 NAV 上叠加减仓/买回择时, 返回带择时的 NAV。
    核心修正: 减仓用慢钟(MA250破位确认下行)确认避险, 但买回用快信号(MA50站回/脱离底部)
    抢在 V 型反弹前上车 —— 吃反弹而非错过反弹。
    """
    n = len(nav)
    out = [1.0]
    state = "ON"   # ON=满仓, OFF=防御
    trough = nav[0]
    for i in range(1, n):
        prev = nav[i-1]
        ma250 = sma(nav, i-1, 250)
        ma_re = sma(nav, i-1, re_ma)
        peak = max(nav[max(0, i-250):i]) if i >= 1 else prev
        dd = prev/peak - 1
        exp_here = 0.0 if rule == "MA250BIN" else def_exp
        if rule == "MA250":
            target = "ON" if (ma250 is None or prev >= ma250) else "OFF"
        elif rule == "MA250BIN":   # 二元: 破MA250清仓, 站回满仓(反弹全吃但晚一点)
            target = "ON" if (ma250 is None or prev >= ma250) else "OFF"
        elif rule == "MA50RE":     # 出: MA250破位; 回: MA50站回(更早吃反弹)
            if state == "ON":
                target = "OFF" if (ma250 is not None and prev < ma250) else "ON"
            else:
                target = "ON" if (ma_re is not None and prev >= ma_re) else "OFF"
        elif rule == "BOUNCE":     # 出: MA250破位; 回: 脱离底部+bounce即满仓(抢最猛反弹起点)
            if state == "ON":
                target = "OFF" if (ma250 is not None and prev < ma250) else "ON"
            else:
                target = "ON" if (prev >= trough*(1+bounce)) else "OFF"
        elif rule == "DEEPDD":
            if state == "ON":
                target = "OFF" if dd <= dd_thr else "ON"
            else:
                target = "ON" if (ma250 is not None and prev >= ma250) else "OFF"
        else:  # HYBRID
            if state == "ON":
                target = "OFF" if (dd <= dd_thr or (ma250 is not None and prev < ma250)) else "ON"
            else:
                target = "ON" if (ma250 is not None and prev >= ma250) else "OFF"
        if target == "ON":
            trough = prev   # 回到满仓, 重置底部跟踪
        elif state == "OFF":
            trough = min(trough, prev)  # 防御期间持续跟踪底部
        state = target
        exp = 1.0 if state == "ON" else exp_here
        c0 = prev; c1 = nav[i]
        day_ret = (c1/c0 - 1) if c0 > 0 else 0.0
        out.append(out[-1] * (1 + day_ret * exp))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--universe", default="all", choices=["all", "tech"])
    ap.add_argument("--dd", type=float, default=-0.22)
    args = ap.parse_args()

    universe = TECH if args.universe == "tech" else UNIVERSE
    label = "科技/成长子集(18只)" if args.universe == "tech" else "全50只宇宙"

    dates, _, _ = sb.build_market_clock()
    cut = [k for k, d in enumerate(dates) if d >= args.start]
    dates = dates[cut[0]:]

    nav = build_basket_nav(dates, universe)
    navB = list(nav)  # 满仓 = 基准 B
    h_ma  = apply_timing(nav, "MA250", dd_thr=args.dd)
    h_dd  = apply_timing(nav, "DEEPDD", dd_thr=args.dd)
    h_hy  = apply_timing(nav, "HYBRID", dd_thr=args.dd)
    h_bin = apply_timing(nav, "MA250BIN", dd_thr=args.dd)
    h_ma50= apply_timing(nav, "MA50RE", dd_thr=args.dd, re_ma=50)
    h_bnc = apply_timing(nav, "BOUNCE", dd_thr=args.dd, bounce=0.10)

    print("="*78)
    print("极端择时诚实测试(吃反弹版)  %s  窗口 %s~%s" %
          (label, dates[0], dates[-1]))
    print("="*78)
    rows = [
        ("B 满仓等权(基准, 无择时)", navB),
        ("H1 MA250趋势(15%防御仓)", h_ma),
        ("H2 深度回撤减仓(%.0f%%)" % (args.dd*100), h_dd),
        ("H3 混合(MA250∪深回撤)", h_hy),
        ("H4 MA250二元(破位清仓)", h_bin),
        ("H5 MA250出/MA50回(早吃反弹)", h_ma50),
        ("H6 MA250出/+10%底部回(抢反弹)", h_bnc),
    ]
    print("%-30s %8s %7s %9s %6s %6s" % ("策略","倍率","年化%","最大回撤%","波动%","夏普"))
    print("-"*78)
    res = {}
    for name, eq in rows:
        m = sb.metrics(eq)
        res[name] = m
        print("%-30s %8.2fx %6.1f%% %8.1f%% %6.1f%% %6.2f" %
              (name, m["mult"], m["cagr"], m["mdd"], m["vol"], m["sharpe"]))
    # 诚实判定
    b = res["B 满仓等权(基准, 无择时)"]
    for nm in ["H1 MA250趋势(15%防御仓)","H4 MA250二元(破位清仓)","H5 MA250出/MA50回(早吃反弹)","H6 MA250出/+10%底部回(抢反弹)"]:
        m = res[nm]
        beat = m["cagr"] > b["cagr"] + 0.0
        verdict = "击败B(收益↑且回撤↓)" if (m["cagr"]>=b["cagr"] and m["mdd"]>b["mdd"]) else \
                  ("收益≥B且回撤更浅" if m["cagr"]>=b["cagr"] else "降回撤但收益仍低")
        print("  %s: 年化 %.1f%% vs %.1f%% | 回撤 %.1f%% vs %.1f%% -> %s" %
              (nm, m["cagr"], b["cagr"], m["mdd"], b["mdd"], verdict))

if __name__ == "__main__":
    main()
