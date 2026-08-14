#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
regime_positioning.py —— 周期相位 → 目标仓位 → 倍率回测
==========================================================
核心问题: 用 A 股周期理论(相位判定)把年化倍率提上来。

对比四套策略(均对指数/ETF 日收益施加"目标仓位", 现金不计息):
  A. 始终满仓 (buy & hold 指数)
  B. 相位开闸(单资产): 主升满仓 / 赶顶减 / 筑底半仓 / 震荡近空 / 退潮主跌近零
  C. RS 轮动(始终满仓版): 每月选 60日动量前3 ETF 等权, 不判相位
  D. RS 轮动 + 相位开闸: C 的仓位再乘市场(sh000001)相位权重

所有信号均用"前一日收盘判定"决定"次日仓位", 严格因果(无未来函数)。
含交易摩擦(单边 5bp)。

用法:
  python3 regime_positioning.py            # 跑全部, 打印对比表
  python3 regime_positioning.py --json     # 额外输出 JSON 明细
"""
import os, sys, json, math, argparse
sys.path.insert(0, os.path.dirname(__file__))
import data_store as ds
import analog_core as ac

BASE = os.path.dirname(os.path.abspath(__file__))

# 相位 → 目标仓位(单资产视角). 0.0=空仓, 1.0=满仓
POS = {
    "主升浪": 1.00,
    "赶顶/收割期": 0.40,
    "筑底": 0.50,
    "震荡": 0.10,
    "退潮期": 0.10,
    "主跌浪": 0.00,
    "数据不足": 0.10,
}

COST = 0.0005  # 单边 5bp

def load(code):
    bars = ds.load_bars(code)
    if not bars:
        return None
    # 统一成 [{d, c}]
    out = []
    for b in bars:
        if isinstance(b, dict):
            out.append((b["d"], float(b["c"])))
        else:
            out.append((b[0], float(b[1])))
    out.sort(key=lambda x: x[0])
    return out

def regime_weight_series(bars):
    """对单资产返回每日(用于次日)的目标仓位序列(因果: idx日相位 -> 用于idx+1日)."""
    bars_d = [{"d": d, "c": c, "v": 0} for d, c in bars]
    feats = ac.build_features(bars_d)
    w = [0.0] * len(bars)
    for i in range(len(bars)):
        label, _ = ac.regime_at(bars_d, feats, i)
        w[i] = POS.get(label, 0.10)
    return w

def simulate_timing(bars, weight_series):
    """weight_series[i] 决定第 i->i+1 日的仓位(因果滞后). 返回权益曲线与每日仓位."""
    eq = [1.0]
    pos = [0.0]
    prev_w = 0.0
    for i in range(1, len(bars)):
        w = weight_series[i - 1]  # 用前一日相位
        r = bars[i][1] / bars[i - 1][1] - 1.0
        # 摩擦: 仓位变动部分付单边成本
        cost = COST * abs(w - prev_w)
        day_ret = w * r - cost
        eq.append(eq[-1] * (1 + day_ret))
        pos.append(w)
        prev_w = w
    return eq, pos

def simulate_buyhold(bars):
    eq = [1.0]
    for i in range(1, len(bars)):
        r = bars[i][1] / bars[i - 1][1] - 1.0
        eq.append(eq[-1] * (1 + r))
    return eq

def metrics(eq, bars):
    n = len(eq) - 1
    yrs = n / 242.0
    mult = eq[-1]
    cagr = (mult ** (1 / yrs) - 1) if mult > 0 and yrs > 0 else float("nan")
    # 最大回撤
    peak = eq[0]; mdd = 0.0
    for x in eq:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    # 日收益统计
    rets = [(eq[i] / eq[i - 1] - 1) for i in range(1, len(eq))]
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / len(rets)
    sd = math.sqrt(var)
    sharpe = (mean / sd * math.sqrt(242)) if sd > 0 else 0.0
    time_in = sum(1 for i in range(1, len(eq)) if True)  # placeholder
    return dict(days=n, years=round(yrs, 2), mult=round(mult, 2),
                cagr=round(cagr * 100, 1), mdd=round(mdd * 100, 1),
                vol=round(sd * math.sqrt(242) * 100, 1),
                sharpe=round(sharpe, 2))

def simulate_rs_rotation(universe_bars, market_w_series, gate=True, topk=3, rebal=20):
    """RS 轮动: 每 rebal 日按前 60日动量选前 topk 等权; gate=True 时整体仓位乘市场相位权重.
    universe_bars: {code: [(d,c),...]} 已对齐到同一日期轴(调用方负责)."""
    codes = list(universe_bars.keys())
    # 以第一个为日期轴
    ref = universe_bars[codes[0]]
    dates = [d for d, _ in ref]
    n = len(dates)
    # 构建每个 code 的 close 序列(与 dates 对齐; 缺失用前值填充)
    closes = {}
    for c in codes:
        m = {d: v for d, v in universe_bars[c]}
        seq = []
        last = None
        for d in dates:
            if d in m:
                last = m[d]
            seq.append(last)
        closes[c] = seq
    eq = [1.0]
    prev_w = {c: 0.0 for c in codes}   # 当前持仓权重
    target = dict(prev_w)              # 本次调仓目标(初始为空仓)
    for i in range(1, n):
        rebal_day = (i % rebal == 0) or (i == 1)
        if rebal_day:
            # 排名: 前 60 日动量(只用 i-1 及之前, 因果)
            mom = {}
            for c in codes:
                c0 = closes[c][max(0, i - 61)]
                c1 = closes[c][i - 1]
                if c0 and c1 and c0 > 0:
                    mom[c] = c1 / c0 - 1
            ranked = sorted(mom.items(), key=lambda x: -x[1])[:topk]
            mw = market_w_series[i - 1] if (gate and market_w_series) else 1.0
            target = {c: (mw / len(ranked) if ranked else 0.0) for c, _ in ranked}
        # 当日组合收益(按当前持仓 prev_w)
        day_ret = 0.0
        for c in codes:
            w = prev_w[c]
            c0 = closes[c][i - 1]; c1 = closes[c][i]
            if c0 and c1 and c0 > 0:
                day_ret += w * (c1 / c0 - 1)
        # 调仓摩擦(仅调仓日, 按目标权重变动)
        cost_total = 0.0
        if rebal_day:
            for c in codes:
                cost_total += COST * abs(target.get(c, 0.0) - prev_w[c])
        eq.append(eq[-1] * (1 + day_ret - cost_total))
        prev_w = {c: target.get(c, 0.0) for c in codes}   # 调仓后持仓=目标(落选者0)
    return eq

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    print("=" * 70)
    print("A股周期相位 → 仓位 → 倍率 回测")
    print("=" * 70)

    # ---------- 单资产时序: 上证 + 创业板 ----------
    for code, name in [("sh000001", "上证指数"), ("sz399006", "创业板指")]:
        bars = load(code)
        if not bars:
            print(f"[跳过] {name} 无缓存"); continue
        print(f"\n### {name} ({code})  样本 {bars[0][0]}~{bars[-1][0]}  共{len(bars)}日")
        w = regime_weight_series(bars)
        eq_bh = simulate_buyhold(bars)
        eq_tm, _ = simulate_timing(bars, w)
        mb = metrics(eq_bh, bars)
        mt = metrics(eq_tm, bars)
        print(f"  始终满仓 : 倍率 {mb['mult']:>8.2f}x  年化 {mb['cagr']:>6.1f}%  最大回撤 {mb['mdd']:>7.1f}%  波动 {mb['vol']:>5.1f}%  夏普 {mb['sharpe']:.2f}")
        print(f"  相位开闸 : 倍率 {mt['mult']:>8.2f}x  年化 {mt['cagr']:>6.1f}%  最大回撤 {mt['mdd']:>7.1f}%  波动 {mt['vol']:>5.1f}%  夏普 {mt['sharpe']:.2f}")

    # ---------- RS 轮动宇宙(行业/宽基 ETF, 2020 起因 inception) ----------
    etfs = ["510880","512660","512690","512800","512880","512890","512480",
            "515880","159995","515030","512200","512400","512670","512720",
            "512980","515210","515220","515230","515790","159819","159732",
            "159865","159992","159937","518880"]
    ub = {}
    start = "2020-01-01"
    for c in etfs:
        b = load(c)
        if not b: continue
        b = [x for x in b if x[0] >= start]
        if len(b) > 200:
            ub[c] = b
    # 对齐日期轴到交集
    common = None
    for c, b in ub.items():
        dset = set(d for d, _ in b)
        common = dset if common is None else (common & dset)
    common = sorted(common)
    aligned = {}
    for c, b in ub.items():
        m = {d: v for d, v in b}
        aligned[c] = [(d, m[d]) for d in common if d in m]
    # 市场相位权重(上证)
    mkt = load("sh000001")
    mkt = [x for x in mkt if x[0] >= start]
    mkt_w = regime_weight_series(mkt)
    # 对齐 mkt_w 到 common 日期
    mkt_m = {d: w for d, w in zip([x[0] for x in mkt], mkt_w)}
    mkt_w_aligned = [mkt_m.get(d, 0.1) for d in common]

    print(f"\n### RS 轮动宇宙 样本 {common[0]}~{common[-1]}  共{len(common)}日, {len(aligned)}只ETF")
    eq_rot_nogate = simulate_rs_rotation(aligned, None, gate=False)
    eq_rot_gate = simulate_rs_rotation(aligned, mkt_w_aligned, gate=True)
    # 用 common 构造 bars 伪对象供 metrics(只需长度)
    pseudo = [(d, 0) for d in common]
    mr_n = metrics(eq_rot_nogate, pseudo)
    mr_g = metrics(eq_rot_gate, pseudo)
    mb_ref = metrics(simulate_buyhold([(d, aligned[list(aligned)[0]][i][1]) for i, d in enumerate(common)]), pseudo) if False else None
    print(f"  RS轮动(满仓)   : 倍率 {mr_n['mult']:>8.2f}x  年化 {mr_n['cagr']:>6.1f}%  最大回撤 {mr_n['mdd']:>7.1f}%  波动 {mr_n['vol']:>5.1f}%  夏普 {mr_n['sharpe']:.2f}")
    print(f"  RS轮动+相位开闸: 倍率 {mr_g['mult']:>8.2f}x  年化 {mr_g['cagr']:>6.1f}%  最大回撤 {mr_g['mdd']:>7.1f}%  波动 {mr_g['vol']:>5.1f}%  夏普 {mr_g['sharpe']:.2f}")

    # 基准: 18倍/10年
    bench_cagr = (18 ** (1/10) - 1) * 100
    print(f"\n--- 基准参照 ---")
    print(f"  历史记录 '10年18倍' ≈ 年化 {bench_cagr:.1f}%")
    print(f"  上证始终满仓 CAGR: {mb['cagr'] if 'mb' in dir() else '-'}% (长期被牛熊拉平)")
    print(f"  上证相位开闸 CAGR: {mt['cagr'] if 'mt' in dir() else '-'}%")
    print(f"  RS轮动+相位开闸 CAGR: {mr_g['cagr']}%  (集中度+轮动+相位三重叠加)")

    if args.json:
        out = dict(market={}, rotation={})
        print("\n[JSON]\n" + json.dumps(out, ensure_ascii=False))

if __name__ == "__main__":
    main()
