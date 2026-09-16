# -*- coding: utf-8 -*-
"""经典币对再平衡总览 — 回答用户:"跑几个经典的交易对, 看整体筹码增加多少、收益多少"

两列核心(用户指定):
  ① 筹码年化 %  = 组合几何筹码倍数的几何年化   <- 主口径(纯币量, 不含价格)
  ② 收益 CAGR % = 再平衡净值年化               <- 次口径(净值含价格, 受起点价影响, 仅作参考)

铁律: 再平衡目的 = 筹码不掉队(>=1.0), 非收益最大化。
      筹码只依赖"路径", 面板末格重写不改变已实现路径 -> 筹码值抗面板更新;
      净值/超额是绝对量, 会被终点价整体平移。

数据: data/weekly_adjclose_crypto50_10y.csv
"""
import os
import math
import importlib.util

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("bap", os.path.join(HERE, "crypto_btc_ada_pair.py"))
bap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bap)

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
OUTDIR = os.path.join(HERE, "out")
COST_BP = 10.0

PAIRS = [
    ("BTC", "ETH"), ("BTC", "ADA"), ("ETH", "ADA"), ("ETH", "LINK"),
    ("BTC", "SOL"), ("ETH", "SOL"), ("SOL", "ADA"), ("SOL", "LINK"),
    ("ETH", "DOT"), ("SOL", "DOT"), ("UNI", "AAVE"),
]
BASKET = ["BTC", "ETH", "RAY", "DOT", "ZEC", "POL"]

geo = lambda x: math.exp(x) - 1


def load_panel():
    px = pd.read_csv(PANEL, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


def one_pair(px, a, b, start=None):
    st = start if start is not None else max(px[a].first_valid_index(), px[b].first_valid_index())
    r = bap.sim(px, [a, b], start=st, cost_bp=COST_BP)
    if r is None:
        return None
    h = bap.buyhold(px, [a, b], r["start"], r["end"])
    sa = bap.solo(px, a, r["start"], r["end"])
    sb = bap.solo(px, b, r["start"], r["end"])
    ua, ub = r["units_mult"][a], r["units_mult"][b]
    ucb = math.sqrt(ua * ub)
    rca, rcb = math.log(ua) / r["yrs"], math.log(ub) / r["yrs"]
    win = px[[a, b]].loc[r["start"]:r["end"]].dropna()
    rho = float(np.log(win).diff().dropna()[a].corr(np.log(win).diff().dropna()[b]))
    return dict(pair=f"{a}+{b}", yrs=r["yrs"], ua=ua, ub=ub, ucb=ucb,
                rcm=(rca + rcb) / 2, rca=rca, rcb=rcb, prem=r["cagr"] - (sa["cagr"] + sb["cagr"]) / 2,
                nav=r["nav"], hold=h["nav"], cagr=r["cagr"], cagr_h=h["cagr"],
                solo_a=sa["nav"], solo_b=sb["nav"], cagr_a=sa["cagr"], cagr_b=sb["cagr"],
                drift=sa["cagr"] - sb["cagr"], rho=rho, turn=r["turnover_ann"])


def main():
    px = load_panel()
    print(f"面板: {os.path.basename(PANEL)}  末日标签 {px.index[-1].date()}  "
          f"(末格=未完结周实时价, 下次同步会重写)")
    a, b = PAIRS[0]
    print(f"注: 面板日期标签比承载价格早约 9 天(既有发现), 对所有币一致 -> 不影响筹码与收益序列\n")

    recs = [x for x in (one_pair(px, a, b) for a, b in PAIRS) if x]

    hdr = (f"{'配对':9s} {'年数':>5s} {'筹码A':>8s} {'筹码B':>8s} {'组合':>7s} "
           f"{'筹码年化':>8s} {'再平衡净值':>10s} {'死拿净值':>9s} {'CAGR':>7s} "
           f"{'死拿CAGR':>8s} {'漂移差':>7s} {'相关':>5s}")
    print("=" * len(hdr))
    print("A. 经典币对(月度等权, 扣 10bp; 死拿=1.000)")
    print("=" * len(hdr))
    print(hdr)
    print("-" * len(hdr))
    for r in recs:
        mark = " *" if "DOT" in r["pair"] else ""
        print(f"{r['pair']:9s} {r['yrs']:5.2f} {r['ua']:8.4f} {r['ub']:8.4f} {r['ucb']:7.4f} "
              f"{geo(r['rcm']) * 100:+7.2f}% {r['nav']:10.3f} {r['hold']:9.3f} "
              f"{r['cagr'] * 100:+6.2f}% {r['cagr_h'] * 100:+7.2f}% "
              f"{r['drift'] * 100:+6.1f}pp {r['rho']:5.3f}{mark}")
    print("-" * len(hdr))
    print("  (* = 含 DOT, 本次面板修复触及该列)")

    n = len(recs)
    avg_rcm = sum(r["rcm"] for r in recs) / n
    med_rcm = float(np.median([r["rcm"] for r in recs]))
    avg_cagr = sum(r["cagr"] for r in recs) / n
    avg_ch = sum(r["cagr_h"] for r in recs) / n
    avg_prem = sum(r["prem"] for r in recs) / n
    med_cagr = float(np.median([r["cagr"] for r in recs]))
    med_ch = float(np.median([r["cagr_h"] for r in recs]))
    med_diff = float(np.median([r["cagr"] - r["cagr_h"] for r in recs]))
    med_rcm_a = float(np.median([r["rca"] for r in recs]))
    med_rcm_b = float(np.median([r["rcb"] for r in recs]))
    pos = sum(1 for r in recs if r["rcm"] > 0)
    pos_a = sum(1 for r in recs if r["rca"] > 0)
    pos_b = sum(1 for r in recs if r["rcb"] > 0)
    print(f"\n  汇总({n} 组, 各窗口不同, 仅供粗看):")
    print(f"    筹码年化   平均 {geo(avg_rcm) * 100:+.2f}%/年   中位 {geo(med_rcm) * 100:+.2f}%/年   "
          f"区间 {geo(min(r['rcm'] for r in recs)) * 100:+.2f}% ~ {geo(max(r['rcm'] for r in recs)) * 100:+.2f}%")
    print(f"    CAGR       平均 {avg_cagr * 100:+.2f}%/年   中位 {med_cagr * 100:+.2f}%/年")
    print(f"    死拿 CAGR  平均 {avg_ch * 100:+.2f}%/年   中位 {med_ch * 100:+.2f}%/年")
    print(f"    CAGR 差    平均 {(avg_cagr - avg_ch) * 100:+.2f}pp     中位 {med_diff * 100:+.2f}pp")
    print(f"  组合筹码为正: {pos}/{n} 组   单币 A 侧(老币)为正 {pos_a}/{n}   单币 B 侧(弱币)为正 {pos_b}/{n}")
    print(f"  CAGR 高于同窗死拿: {sum(1 for r in recs if r['cagr'] > r['cagr_h'])}/{n} 组")

    # ---------- C. 同窗口对照(消除窗口长度混杂) ----------
    COMMON = max(px[c].first_valid_index() for pair in PAIRS for c in pair)
    recs2 = [x for x in (one_pair(px, a, b, COMMON) for a, b in PAIRS) if x]
    if recs2:
        print("\n" + "=" * len(hdr))
        print(f"C. 同窗口对照(全部从 {COMMON.date()} 起, 消除窗口长度混杂; 月度等权, 扣 10bp)")
        print("=" * len(hdr))
        print(hdr)
        print("-" * len(hdr))
        for r in recs2:
            mark = " *" if "DOT" in r["pair"] else ""
            print(f"{r['pair']:9s} {r['yrs']:5.2f} {r['ua']:8.4f} {r['ub']:8.4f} {r['ucb']:7.4f} "
                  f"{geo(r['rcm']) * 100:+7.2f}% {r['nav']:10.3f} {r['hold']:9.3f} "
                  f"{r['cagr'] * 100:+6.2f}% {r['cagr_h'] * 100:+7.2f}% "
                  f"{r['drift'] * 100:+6.1f}pp {r['rho']:5.3f}{mark}")
        print("-" * len(hdr))
        m = len(recs2)
        a2 = sum(r["rcm"] for r in recs2) / m
        a2c = sum(r["cagr"] for r in recs2) / m
        a2h = sum(r["cagr_h"] for r in recs2) / m
        a2e = sum(r["nav"] / r["hold"] - 1 for r in recs2) / m
        print(f"  同窗口汇总({m} 组, 同一 {recs2[0]['yrs']:.2f}y):")
        print(f"    筹码年化  平均 {geo(a2) * 100:+.2f}%/年  中位 {geo(float(np.median([r['rcm'] for r in recs2]))) * 100:+.2f}%/年  "
              f"区间 {geo(min(r['rcm'] for r in recs2)) * 100:+.2f}% ~ {geo(max(r['rcm'] for r in recs2)) * 100:+.2f}%")
        print(f"    CAGR      平均 {a2c * 100:+.2f}%/年  中位 {float(np.median([r['cagr'] for r in recs2])) * 100:+.2f}%/年")
        print(f"    死拿 CAGR 平均 {a2h * 100:+.2f}%/年  中位 {float(np.median([r['cagr_h'] for r in recs2])) * 100:+.2f}%/年")
        print(f"    CAGR 差   平均 {(a2c - a2h) * 100:+.2f}pp     中位 {float(np.median([r['cagr'] - r['cagr_h'] for r in recs2])) * 100:+.2f}pp")
        print(f"    组合筹码为正 {sum(1 for r in recs2 if r['rcm'] > 0)}/{m}   CAGR 跑赢死拿 {sum(1 for r in recs2 if r['cagr'] > r['cagr_h'])}/{m}   "
              f"平均净值超额 {a2e * 100:+.2f}% [内部参考, 不进对外结论]")

    # ---------- B. 用户持仓多币篮子 ----------
    print("\n" + "=" * 90)
    print("B. 多币篮子(用户实际持仓 6 币, 月度等权, 扣 10bp)")
    print("=" * 90)
    st = max(px[c].first_valid_index() for c in BASKET)
    for c in BASKET:
        print(f"  {c:5s} 首日 {px[c].first_valid_index().date()}  末日 {px[c].last_valid_index().date()}")
    rb = bap.sim(px, BASKET, start=st, cost_bp=COST_BP)
    if rb is None:
        print("  [多币 sim 失败]")
    else:
        hb = bap.buyhold(px, BASKET, rb["start"], rb["end"])
        us = [rb["units_mult"][c] for c in BASKET]
        ucb = math.exp(sum(math.log(u) for u in us) / len(us))
        print(f"\n  窗口 {rb['start'].date()} ~ {rb['end'].date()}  ({rb['yrs']:.2f}y)")
        print(f"  {'币':6s} {'筹码倍数':>9s} {'筹码年化':>9s} {'独家死拿倍数':>12s} {'独家死拿CAGR':>12s}")
        for c, u in zip(BASKET, us):
            s = bap.solo(px, c, rb["start"], rb["end"])
            print(f"  {c:6s} {u:9.4f} {geo(math.log(u) / rb['yrs']) * 100:+8.2f}% "
                  f"{s['nav']:12.4f} {s['cagr'] * 100:+11.2f}%")
        print(f"\n  组合几何筹码 {ucb:.4f}x  ->  {geo(math.log(ucb) / rb['yrs']) * 100:+.2f}%/年")
        print(f"  再平衡净值 {rb['nav']:.3f}x (CAGR {rb['cagr'] * 100:+.2f}%)  vs  "
              f"等权死拿 {hb['nav']:.3f}x (CAGR {hb['cagr'] * 100:+.2f}%)  "
              f"-> 净值口径超额 {(rb['nav'] / hb['nav'] - 1) * 100:+.2f}% [内部参考]")
        print(f"  换手 {rb['turnover_ann'] * 100:.0f}%/年")

    df = pd.DataFrame(recs)
    os.makedirs(OUTDIR, exist_ok=True)
    p = os.path.join(OUTDIR, "classic_pairs_overview.csv")
    df.to_csv(p, index=False, float_format="%.6f")
    print(f"\n明细 -> {p}")


if __name__ == "__main__":
    main()
