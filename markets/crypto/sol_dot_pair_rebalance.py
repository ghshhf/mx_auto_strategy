# -*- coding: utf-8 -*-
"""SOL + DOT 双币配对再平衡 — 回答用户:"再来一个 sol 和 dot"(承接 UNI+AAVE 同口径)

口径铁律(全项目一致, 不可混用):
  ① 筹码口径 units_mult  -> 回答"囤了多少币"(死拿=1.000)  ← 对外结论只用这个
  ② 美元口径 nav         -> 内部诊断(会被起点价/数据源污染, 不进结论)
  再平衡目的 = 筹码不掉队(>=1.0), 非收益最大化。

输出六块:
  A 主结果(0/10/30bp + 死拿 + 筹码轨迹)
  B 分段
  C 频率 + 起点平移(相位)敏感性
  D 配对准入检验
  E 年化筹码增速分解(纯筹码恒等式, 不引入净值)
  F 可持续性(滚动分布 / sigma-rho 敏感性 / 归零临界)

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
PAIR = ("SOL", "DOT")
A, B = PAIR

geo = lambda x: math.exp(x) - 1
cls = lambda v: "pos" if v >= 0 else "neg"


def load_panel():
    px = pd.read_csv(PANEL, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


def main():
    px = load_panel()
    a, b = PAIR
    rows = []

    for c in PAIR:
        fd = px[c].first_valid_index()
        print(f"  {c:5s} 面板首日 {fd.date()}  末日 {px[c].last_valid_index().date()}  "
              f"NaN {int(px[c].isna().sum())} 周")

    win0 = max(px[c].first_valid_index() for c in PAIR)
    end = px.index[-1]
    T = (end - win0).days / 365.25
    print(f"\n{a}+{b} 自然公共窗口: {win0.date()} ~ {end.date()}  ({T:.2f}y)")
    print(f"面板末日: {end.date()}  (注: 标签较承载价格早约 9 天, 见 memory)")

    # ================= A =================
    print(f"\n{'=' * 96}\n### A. {a} + {b} 双币配对 (等权月度再平衡 vs 死拿)\n{'=' * 96}")
    base = bap.sim(px, list(PAIR), start=win0, cost_bp=0.0)
    st, en = base["start"], base["end"]
    print(f"  窗口 {st.date()} ~ {en.date()}  ({base['yrs']:.2f}y)")
    print("  [美元口径 — 赚几倍]")
    bap.line(f"{a}+{b} 等权月再平衡 (0bp)", base)
    r10 = bap.sim(px, list(PAIR), start=win0, cost_bp=10.0)
    r30 = bap.sim(px, list(PAIR), start=win0, cost_bp=30.0)
    for cbp, r in ((10.0, r10), (30.0, r30)):
        bap.line(f"{a}+{b} 等权月再平衡 ({cbp:.0f}bp)", r)
    h = bap.buyhold(px, list(PAIR), st, en)
    bap.line(f"{a}+{b} 等权死拿", h)
    sa = bap.solo(px, a, st, en)
    sb = bap.solo(px, b, st, en)
    bap.line(f"{a} 独家死拿", sa)
    bap.line(f"{b} 独家死拿", sb)
    print(f"  年化换手 {base['turnover_ann'] * 100:.1f}% / 年   调仓 {base['turnover_events']} 次")

    print(f"  [筹码口径 — 囤了多少币, 死拿该组合 = 1.000]  <<< 对外结论只用这个")
    bap.chip_line(f"{a}+{b} 等权月再平衡 (0bp)", base)
    bap.chip_line(f"{a}+{b} 等权月再平衡 (10bp)", r10)
    bap.chip_line(f"{a}+{b} 等权月再平衡 (30bp)", r30)
    print(f"  [内部诊断·超额(不作结论)] {(base['nav'] / base['hold_nav'] - 1) * 100:+.2f}%")
    print(f"  [起点价] {a} {base['px_first'][a]:.4f} -> {base['px_last'][a]:.4f}   "
          f"{b} {base['px_first'][b]:.4f} -> {base['px_last'][b]:.4f}")

    for tag, r in [("0bp", base), ("10bp", r10), ("30bp", r30)]:
        rows.append(dict(tag=f"{a}+{b} {tag}", window="全窗口", yrs=r["yrs"], nav=r["nav"],
                         cagr=r["cagr"] * 100, mdd=r["mdd"] * 100,
                         hold_nav=r["hold_nav"], units_a=r["units_mult"][a],
                         units_b=r["units_mult"][b], turnover=r["turnover_ann"] * 100))

    us = base["units_ser"]
    print(f"\n  [筹码轨迹 — 每 6 个月抽样]")
    print(f"  {'日期':>12s}{a:>12s}{b:>12s}")
    for dt in us.index[::26]:
        print(f"  {str(dt.date()):>12s}{us.loc[dt, a]:>11.4f}x{us.loc[dt, b]:>11.4f}x")
    print(f"  {str(us.index[-1].date()):>12s}{us.iloc[-1][a]:>11.4f}x{us.iloc[-1][b]:>11.4f}x  <== 期末")

    # ================= B =================
    windows = [
        ("上轮牛熊尾段", (None, "2022-11-11")),
        ("复苏段 2022-11~2024-04", ("2022-11-11", "2024-04-19")),
        ("本轮 2024-04~今", ("2024-04-19", None)),
        ("近3年", (str((end - pd.Timedelta(days=1095)).date()), None)),
        ("近2年", (str((end - pd.Timedelta(days=730)).date()), None)),
        ("近1年", (str((end - pd.Timedelta(days=365)).date()), None)),
    ]
    print(f"\n{'=' * 96}\n### B. {a} + {b} 分段 (公共窗口对齐)\n{'=' * 96}")
    for wtag, (s0, s1) in windows:
        bb = bap.sim(px, list(PAIR), start=s0, end=s1, cost_bp=COST_BP)
        if bb is None:
            print(f"  {wtag}: 数据不足")
            continue
        hh = bap.buyhold(px, list(PAIR), bb["start"], bb["end"])
        ra = bb["units_mult"][a]
        rb = bb["units_mult"][b]
        rc = math.sqrt(ra * rb)
        print(f"\n-- {wtag}  {bb['start'].date()} ~ {bb['end'].date()} ({bb['yrs']:.2f}y)")
        print(f"   筹码 {a} {ra:.4f}x / {b} {rb:.4f}x   [组合 {rc:.4f}x]   "
              f"换手 {bb['turnover_ann'] * 100:.0f}%/年")
        print(f"   (内部) 净值 {bb['nav']:.3f}x CAGR {bb['cagr'] * 100:+.2f}% "
              f"死拿 {hh['nav']:.3f}x")
        rows.append(dict(tag=f"{a}+{b} 10bp", window=wtag, yrs=bb["yrs"], nav=bb["nav"],
                         cagr=bb["cagr"] * 100, mdd=bb["mdd"] * 100, hold_nav=hh["nav"],
                         units_a=ra, units_b=rb, turnover=bb["turnover_ann"] * 100))

    # ================= C =================
    print(f"\n{'=' * 96}\n### C. 调仓频率 + 起点平移(相位)敏感性 — 长窗口必须看相位\n{'=' * 96}")
    for freq, lab in ((1, "每周"), (2, "双周"), (4, "月度"), (8, "双月"), (13, "季度")):
        r0 = bap.sim(px, list(PAIR), rebal_weeks=freq, start=win0, cost_bp=0.0)
        if r0 is None:
            continue
        ua, ub = r0["units_mult"][a], r0["units_mult"][b]
        print(f"  {lab:4s} 筹码 {a} {ua:.4f}x / {b} {ub:.4f}x  [组合 {math.sqrt(ua * ub):.4f}x]  "
              f"换手 {r0['turnover_ann'] * 100:.0f}%/年")
    # 起点平移(真正的相位): 截面整体平移 k 周
    print(f"\n  [起点平移敏感性 — 月度, k=0..3 周偏移]")
    sub_all = px[[a, b]].dropna()
    for k in range(4):
        pxk = sub_all.iloc[k:]
        rk = bap.sim(pxk, list(PAIR), rebal_weeks=4, cost_bp=0.0)
        if rk is None:
            continue
        ua, ub = rk["units_mult"][a], rk["units_mult"][b]
        print(f"    平移 {k} 周: 筹码 {a} {ua:.4f}x / {b} {ub:.4f}x  [组合 {math.sqrt(ua * ub):.4f}x]  "
              f"窗口 {rk['yrs']:.2f}y")

    # ================= D =================
    print(f"\n{'=' * 96}\n### D. {a}/{b} 配对准入检验\n{'=' * 96}")
    sub = px.loc[win0:, list(PAIR)].dropna()
    rr = sub.pct_change().dropna()
    rho_all = float(rr[a].corr(rr[b]))
    vol_a = float(rr[a].std() * np.sqrt(52))
    vol_b = float(rr[b].std() * np.sqrt(52))
    print(f"  周收益相关 {rho_all:.3f}  (准入要求 <0.3 才算低相关)")
    print(f"  年化波动 {a} {vol_a * 100:.1f}%  {b} {vol_b * 100:.1f}%  (准入要求 >20%)")
    print(f"  全窗口漂移 {a} CAGR {sa['cagr'] * 100:+.2f}%  {b} {sb['cagr'] * 100:+.2f}%  "
          f"漂移差 {(sa['cagr'] - sb['cagr']) * 100:+.1f}pp")
    print(f"  MDD {a} {sa['mdd'] * 100:+.1f}%  {b} {sb['mdd'] * 100:+.1f}%")

    # ================= E =================
    print(f"\n{'=' * 96}\n### E. 年化筹码增速分解 (纯筹码恒等式, 不引入净值)\n{'=' * 96}")
    y0 = r10["yrs"]
    ua10, ub10 = r10["units_mult"][a], r10["units_mult"][b]
    rca, rcb = math.log(ua10) / y0, math.log(ub10) / y0
    rcm = (rca + rcb) / 2
    qa, qb = math.log(sa["nav"] / 1.0), math.log(sb["nav"] / 1.0)   # 价格倍数对数
    print(f"  筹码倍数(10bp): {a} {ua10:.4f}x -> 年化 {geo(rca) * 100:+.2f}%   "
          f"{b} {ub10:.4f}x -> 年化 {geo(rcb) * 100:+.2f}%")
    print(f"  组合(几何) {math.sqrt(ua10 * ub10):.4f}x -> 年化 {geo(rcm) * 100:+.2f}%   "
          f"<<< 可重复的机器产出")
    print(f"  恒等式校验: {a} log = 组合 {rcm:.6f} + 搬运 {(qb - qa) / (2 * y0):.6f} "
          f"= {rcm + (qb - qa) / (2 * y0):.6f} (实 {rca:.6f})")
    print(f"              {b} log = 组合 {rcm:.6f} + 搬运 {(qa - qb) / (2 * y0):.6f} "
          f"= {rcm + (qa - qb) / (2 * y0):.6f} (实 {rcb:.6f})")
    print(f"  价格倍数: {a} {sa['nav']:.3f}x / {b} {sb['nav']:.3f}x -> "
          f"{'搬 DOT 的涨幅给 SOL' if sa['nav'] < sb['nav'] else '搬 SOL 的涨幅给 DOT'}")
    print(f"  组合翻倍 {math.log(2) / rcm:.1f} 年 / 十倍 {math.log(10) / rcm:.1f} 年")

    # ================= F =================
    print(f"\n{'=' * 96}\n### F. 可持续性 (收割项 = 0.25*(1-rho)*sigma^2)\n{'=' * 96}")
    lrx = np.log(px[[a, b]]).diff()
    sig_r = (lrx.rolling(52).std() * np.sqrt(52)).dropna()
    rho_r = lrx[a].rolling(52).corr(lrx[b]).dropna()
    cmn = sig_r.index.intersection(rho_r.index)
    sig_avg = (sig_r.loc[cmn, a] + sig_r.loc[cmn, b]) / 2
    rho_r = rho_r.loc[cmn]
    sig_med, sig_now = float(sig_avg.median()), float(sig_avg.iloc[-1])
    rho_med, rho_now = float(rho_r.median()), float(rho_r.iloc[-1])
    print(f"  实测滚动1年: sigma 中位 {sig_med * 100:.1f}% / 最近 {sig_now * 100:.1f}%   "
          f"rho 中位 {rho_med:.3f} / 最近 {rho_now:.3f}")
    print(f"  按最近读数收割项 ≈ {0.25 * (1 - rho_now) * sig_now ** 2 * 100:+.2f}%/年")
    k_ = vol_a / vol_b
    rho_star = ((k_ ** 2) + 1) / (2 * k_)
    print(f"  归零临界 rho* = (k^2+1)/(2k), k={a}/{b} 波动比 = {k_:.4f} -> rho* = {rho_star:.4f}"
          f"{'  > 1  =>  数学上不可达' if rho_star > 1 else '  <=1 => 可达'}")

    # 滚动 2 年分布
    idx2 = px[[a, b]].dropna().index
    W2 = 104
    rc_list, ra_list, rb_list = [], [], []
    for i in range(0, len(idx2) - W2, 2):
        r = bap.sim(px, list(PAIR), start=idx2[i], end=idx2[i + W2], cost_bp=COST_BP)
        if r is None:
            continue
        ra = math.log(r["units_mult"][a]) / r["yrs"]
        rb = math.log(r["units_mult"][b]) / r["yrs"]
        rc_list.append((ra + rb) / 2)
        ra_list.append(ra)
        rb_list.append(rb)
    s = pd.Series(rc_list)
    q = s.quantile([0, .25, .5, .75, 1])
    print(f"\n  滚动 2 年窗口 ({len(rc_list)} 个起点):")
    print(f"    组合筹码年化 最差 {geo(q.iloc[0]) * 100:+.2f}%  25% {geo(q.iloc[1]) * 100:+.2f}%  "
          f"中位 {geo(q.iloc[2]) * 100:+.2f}%  75% {geo(q.iloc[3]) * 100:+.2f}%  "
          f"最好 {geo(q.iloc[4]) * 100:+.2f}%")
    print(f"    组合为负比例 {float(np.mean([x < 0 for x in rc_list])) * 100:.1f}%   "
          f"{a} 为负 {float(np.mean([x < 0 for x in ra_list])) * 100:.1f}%   "
          f"{b} 为负 {float(np.mean([x < 0 for x in rb_list])) * 100:.1f}%")

    # sigma/rho 敏感性(对数口径)
    print(f"\n  sigma 敏感性 (按 rho={rho_med:.2f}, 对数口径):")
    for sg in (1.10, 0.90, sig_med, 0.60, 0.40, 0.30, 0.20):
        h = 0.25 * (1 - rho_med) * sg * sg
        hl = math.log(2) / h if h > 1e-9 else float("inf")
        print(f"    sigma {sg * 100:6.1f}%  ->  组合筹码年化 {geo(h) * 100:+.2f}%/年   "
              f"翻倍 {hl:5.1f} 年")
    print(f"\n  rho 敏感性 (按 sigma={sig_med:.2f}):")
    for rh in (0.0, 0.30, rho_med, 0.60, 0.80, 0.90, 0.95):
        h = 0.25 * (1 - rh) * sig_med * sig_med
        print(f"    rho {rh:.2f}  ->  组合筹码年化 {geo(h) * 100:+.2f}%/年   "
              f"相对 rho=0 保留 {((1 - rh) / 1.0) * 100:.0f}%")

    # 落盘
    os.makedirs(OUTDIR, exist_ok=True)
    pd.DataFrame(rows).to_csv(os.path.join(OUTDIR, "sol_dot_pair_rebalance.csv"),
                             index=False, encoding="utf-8-sig")
    print(f"\n[落盘] out/sol_dot_pair_rebalance.csv  ({len(rows)} 行)")


if __name__ == "__main__":
    main()
