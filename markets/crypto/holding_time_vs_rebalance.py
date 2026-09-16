# -*- coding: utf-8 -*-
"""持有时间 vs 再平衡 —— 直接回答本轮三条质疑（口径纠错 + 重算）

质疑①: "你说 FIL / DOT / AVAX / AAVE 未来会亏，依据是什么？项目不更新了？背后势力不动了？"
   → 段1 口径对照。我原话其实是【单币死拿价格口径的历史滚动频率】（回顾统计，不是预测）。
     换成【再平衡筹码口径】，要点的 4 个币结论全部反转。

质疑②: "要看平均账户（都买），不是挑个别看"
   → 段2 滚动窗口：单币 池化 vs 等权全池死拿 vs 等权全池再平衡（同一批起点）。

质疑③: "买入还不是不动，再平衡还能拿点筹码"
   → 段2/段3 筹码口径：组合筹码分布、单币筹码倍数、不掉队比例。

附: BNB 本轮熊市近腰斩 —— 强币回撤 ↔ "强币更易掉队"的机制连接。

口径(不可混用):
  价格口径 nav  → 赚几倍 / 亏不亏美元
  筹码口径 units → 囤了多少币 / 掉队没有(死拿该组合 = 1.000)
数据: data/weekly_adjclose_crypto50_10y.csv (27 币, 625 周, 2014-09-19 ~ 2026-09-04)
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
MAIN_START = "2020-10-09"        # 主口径: 19 币 / 5.94y
LONG9 = ["BTC", "ETH", "BNB", "LTC", "OKB", "ADA", "XRP", "XLM", "TRX"]   # 8年+ 长历史组
FOCUS = ["FIL", "DOT", "AVAX", "AAVE", "BNB"]        # 用户点名 + BNB
HORIZONS_Y = [1, 2, 3, 5, 8]

geo = lambda x: math.exp(x) - 1.0


def load_panel():
    px = pd.read_csv(PANEL, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


# ============================ 段 0: 牛熊回撤 ============================
def drawdown_now(px, cycle_start="2024-01-01", label="本轮(2024起)"):
    """各币从周期内最高价到面板末的跌幅。"""
    rows = []
    for c in px.columns:
        s = px[c].dropna()
        w = s.loc[cycle_start:]
        if len(w) < 20:
            continue
        hi = float(w.max())
        now = float(s.iloc[-1])
        tot_hi = float(s.max())
        rows.append(dict(coin=c, n_weeks=len(s),
                         cyc_hi=hi, cyc_hi_date=w.idxmax().date(),
                         now=now, from_hi=now / hi - 1.0,
                         from_ath=now / tot_hi - 1.0,
                         ath=tot_hi, ath_date=s.idxmax().date()))
    return pd.DataFrame(rows).sort_values("from_hi")


# ============================ 段 1: 口径对照 ============================
def caliber_compare(px):
    """同一窗口(主口径 5.94y): 单币死拿价格 vs 再平衡筹码。"""
    ex = pd.read_csv(os.path.join(OUTDIR, "all_pairs_exhaustive.csv"))
    cv = pd.read_csv(os.path.join(OUTDIR, "all_pairs_coin_view.csv"))
    main = ex[ex.layer == f"{MAIN_START}/19币"].copy()
    main["_a"] = main.pair.str.split("+").str[0]
    main["_b"] = main.pair.str.split("+").str[1]
    solo = {}
    for c in px.columns:
        s = px[c].loc[MAIN_START:].dropna()
        if len(s) < 2:
            continue
        yrs = (s.index[-1] - s.index[0]).days / 365.25
        solo[c] = dict(mult=float(s.iloc[-1] / s.iloc[0]), yrs=yrs,
                       cagr=(s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1)
    rows = []
    for c in solo:
        sub = main[(main._a == c) | (main._b == c)]
        if not len(sub):
            continue
        own = np.array([math.log(r["ua"] if r["_a"] == c else r["ub"]) / r["yrs"]
                        for _, r in sub.iterrows()])
        comb = sub.rcm.values
        k = float((own > 0).mean())
        rows.append(dict(
            coin=c, yrs=solo[c]["yrs"], solo_mult=solo[c]["mult"], solo_cagr=solo[c]["cagr"],
            n_pair=len(sub), own_med=geo(float(np.median(own))),
            own_lo=geo(float(own.min())), own_hi=geo(float(own.max())),
            keep=k, comb_med=geo(float(np.median(comb)))))
    return pd.DataFrame(rows), main, cv


# ============================ 段 2: 滚动窗口 ============================
def roll_windows(px, coins, L, cost_bp=COST_BP, stride=1):
    """固定长度 L 年、逐周滑动的窗口；返回单币池化 + 组合死拿 + 组合再平衡分布。"""
    pxv = px[coins].dropna(how="any")
    idx = pxv.index
    pr = pxv.values.astype(float)
    n = len(idx)
    h = int(round(L * 52))
    if n <= h + 4:
        return None
    solo_r, hold_navs, chip_g, navs, holds, yrs_l = [], [], [], [], [], []
    for i in range(0, n - h, stride):
        j = i + h
        solo_r.append(pr[j] / pr[i] - 1.0)
        hold_navs.append(float(np.mean(pr[j] / pr[i])))
        r = bap.sim(pxv, coins, start=idx[i], end=idx[j], cost_bp=cost_bp)
        if r is None:
            continue
        us = [r["units_mult"][c] for c in coins]
        chip_g.append(math.exp(float(np.mean([math.log(u) for u in us]))))
        navs.append(r["nav"])
        holds.append(r["hold_nav"])
        yrs_l.append(r["yrs"])
    if not navs:
        return None
    S = np.array(solo_r)                             # (起点, 币)
    hold_navs = np.array(hold_navs)
    navs, holds = np.array(navs), np.array(holds)
    chip_g = np.array(chip_g)
    pool = S.ravel()
    return dict(L=L, yrs=float(np.median(yrs_l)), n_start=len(navs), n_coin=len(coins),
                solo_pool_loss=float((pool < 0).mean()),
                solo_pool_med=float(np.median(pool)),
                solo_start_loss_med=float(np.median((S < 0).mean(axis=1))),
                hold_loss=float((hold_navs < 1).mean()),
                hold_med=float(np.median(hold_navs)),
                hold_p5=float(np.percentile(hold_navs, 5)),
                hold_p95=float(np.percentile(hold_navs, 95)),
                nav_loss=float((navs < 1).mean()),
                nav_med=float(np.median(navs)),
                chip_med=float(np.median(chip_g)),
                chip_lo=float(chip_g.min()), chip_hi=float(chip_g.max()),
                chip_under1=float((chip_g < 1).mean()),
                chip_p5=float(np.percentile(chip_g, 5)),
                beat=float((navs > holds).mean()),
                excess_med=float(np.median(navs / holds - 1.0)))


# ============================ 段 3: 逐币"再平衡改写" ============================
def coin_rewrite(cv):
    rows = []
    for _, r in cv.iterrows():
        yrs = r.yrs if r.yrs == r.yrs else 5.94
        rows.append(dict(coin=r.coin, solo_cagr=r.solo_cagr,
                         solo_mult=r.solo_mult,
                         own_med=r.own_med, keep=r.keep))
    return pd.DataFrame(rows)


def fmt_pct(v, d=1):
    return "—" if v is None or v != v else f"{v * 100:+.{d}f}%"


def main():
    px = load_panel()
    print("=" * 126)
    print(f"面板 {os.path.basename(PANEL)}  {px.shape[1]} 币  "
          f"{px.index[0].date()} ~ {px.index[-1].date()}  ({px.shape[0]} 周)")
    print("（面板日期标签比承载价格早约 9 天，对所有币一致，不影响收益/筹码序列）")
    print("=" * 126)

    dd = drawdown_now(px)
    print("\n【段0】各币 2024 年起最高价 → 面板末 的跌幅（含用户提的 BNB）")
    print(f"  {'币':7s}{'2024起高点':>13s}{'高点日':>12s}{'现值':>12s}{'距周期高':>10s}"
          f"{'距历史最高':>11s}{'历史最高日':>12s}")
    show = dd[dd.coin.isin(FOCUS + ["BTC", "ETH", "SOL", "UNI", "ZEC", "LINK", "LTC"])]
    for _, r in show.iterrows():
        print(f"  {r.coin:7s}{r.cyc_hi:>13,.2f}{str(r.cyc_hi_date):>12s}{r.now:>12,.2f}"
              f"{r.from_hi * 100:>9.1f}%{r.from_ath * 100:>10.1f}%{str(r.ath_date):>12s}")
    print(f"\n  全池 {len(dd)} 币: 距周期高点 中位 {dd.from_hi.median() * 100:.1f}%  "
          f"| 距历史最高 中位 {dd.from_ath.median() * 100:.1f}%  "
          f"| 已跌破 -50% 的 {int((dd.from_hi < -0.5).sum())}/{len(dd)} 币")

    cv_all, main, _ = caliber_compare(px)
    print("\n" + "=" * 126)
    print(f"【段1】口径对照 — 同一窗口（主口径 {MAIN_START} 起, {cv_all.yrs.median():.2f}y, 19 币）")
    print("=" * 126)
    print("  ① 我上轮用的口径 = 单币死拿【价格】；② 你的口径 = 配对再平衡【筹码】")
    print(f"\n  {'币':7s}{'死拿倍数':>11s}{'死拿CAGR':>10s}{'配对数':>7s}"
          f"{'本币筹码年化中位':>16s}{'筹码区间(最差~最好)':>24s}{'不掉队比例':>11s}{'组合筹码年化中位':>16s}")
    focus_order = [c for c in FOCUS if c in set(cv_all.coin)]
    order = cv_all.set_index("coin").loc[focus_order].reset_index()
    rest = cv_all[~cv_all.coin.isin(FOCUS)].sort_values("solo_cagr", ascending=False)
    for _, r in pd.concat([order, rest]).iterrows():
        tag = " ←你点名的" if r.coin in FOCUS else ""
        print(f"  {r.coin:7s}{r.solo_mult:>11.4f}{r.solo_cagr * 100:>9.2f}%{int(r.n_pair):>7d}"
              f"{r.own_med * 100:>15.2f}%"
              f"{('  ' + format(r.own_lo * 100, '+7.2f') + '% ~ ' + format(r.own_hi * 100, '+7.2f') + '%'):>24s}"
              f"{r.keep * 100:>10.1f}%{r.comb_med * 100:>15.2f}%{tag}")

    print("\n" + "=" * 126)
    print(f"【段2】滚动窗口：同一批起点，三种口径（长历史 {len(LONG9)} 币，逐周滑动，月再平衡扣 10bp）")
    print("=" * 126)
    print("  口径A 单币死拿(价格)  口径B 全池等权死拿  口径C 全池等权再平衡")
    rows = []
    for L in HORIZONS_Y:
        r = roll_windows(px, LONG9, L)
        if r is None:
            print(f"\n  {L} 年: 数据不足")
            continue
        rows.append(r)
        print(f"\n  持有 {L} 年（窗口 {r['yrs']:.2f}y，起点 {r['n_start']} 个，币 {r['n_coin']} 个）")
        print(f"    A 单币死拿  : 池化亏损率 {r['solo_pool_loss'] * 100:5.1f}%  "
              f"池化收益中位 {fmt_pct(r['solo_pool_med'])}  "
              f"| 单起点内亏损币占比中位 {r['solo_start_loss_med'] * 100:.1f}%")
        print(f"    B 全池死拿  : 亏钱概率 {r['hold_loss'] * 100:5.1f}%  收益中位 {r['hold_med']:6.3f}x  "
              f"(P5~P95 {r['hold_p5']:.2f}~{r['hold_p95']:.2f}x)")
        print(f"    C 全池再平衡: 净值亏钱概率 {r['nav_loss'] * 100:5.1f}%  净值中位 {r['nav_med']:6.3f}x  "
              f"| 筹码中位 {r['chip_med']:6.3f}x (P5 {r['chip_p5']:.3f}x)  "
              f"筹码<1 概率 {r['chip_under1'] * 100:5.1f}%  "
              f"跑赢死拿概率 {r['beat'] * 100:5.1f}%  超额中位 {fmt_pct(r['excess_med'])}")

    print("\n" + "-" * 126)
    print("【段2b】「熬满全程」实测：长历史组共同起点 → 面板末（不换起点，一次持有到底）")
    print("-" * 126)
    pxv = px[LONG9].dropna(how="any")
    w0, w1 = pxv.index[0], pxv.index[-1]
    yrs = (w1 - w0).days / 365.25
    rb = bap.sim(pxv, LONG9, start=w0, end=w1, cost_bp=COST_BP)
    pr = pxv.values.astype(float)
    sm = pr[-1] / pr[0]
    hold_mult = float(np.mean(sm))
    chip = {c: rb["units_mult"][c] for c in LONG9}
    chip_g = math.exp(float(np.mean([math.log(v) for v in chip.values()])))
    print(f"  窗口 {w0.date()} ~ {w1.date()}  ({yrs:.2f}y, {len(pxv)} 周, {len(LONG9)} 币)")
    print("  单币死拿: " + "  ".join(f"{c} {m:7.2f}x" for c, m in zip(LONG9, sm)))
    print(f"            中位 {np.median(sm):.2f}x | 最差 {sm.min():.2f}x ({LONG9[int(np.argmin(sm))]})"
          f" | 最好 {sm.max():.2f}x ({LONG9[int(np.argmax(sm))]})"
          f" | 亏钱的 {int((sm < 1).sum())}/{len(LONG9)} 币")
    print(f"  全池死拿    {hold_mult:8.3f}x  (CAGR {hold_mult ** (1 / yrs) - 1:+.2%}/年)")
    print(f"  全池再平衡  {rb['nav']:8.3f}x  (CAGR {rb['cagr']:+.2%}/年)"
          f"  对死拿超额 {(rb['nav'] / rb['hold_nav'] - 1):+.2%}")
    print(f"  单币筹码(死拿=1.000): " + "  ".join(f"{c} {chip[c]:6.3f}x" for c in LONG9))
    print(f"            组合筹码 {chip_g:.3f}x  | 单币筹码 <1 的 "
          f"{int(sum(1 for v in chip.values() if v < 1))}/{len(LONG9)} 币  "
          f"（即再平衡下几乎没人掉队，尽管单币价格 {int((sm < 1).sum())} 个是亏的）")

    print("\n" + "=" * 126)
    print("【段3】把『未来会亏』换成可检验的三个问题")
    print("=" * 126)
    f = cv_all.set_index("coin")
    for c in FOCUS:
        if c not in f.index:
            continue
        r = f.loc[c]
        print(f"\n  {c}: 单币死拿到今天 {r.solo_mult:.4f}x（CAGR {r.solo_cagr * 100:+.2f}%/年）")
        print(f"        → 作为 {int(r.n_pair)} 组配对的一腿，本币筹码年化中位 {r.own_med * 100:+.2f}%/年，"
              f"不掉队 {r.keep * 100:.1f}%（区间 {r.own_lo * 100:+.2f}% ~ {r.own_hi * 100:+.2f}%）")
        print(f"        → 该币参与的组合，组合筹码年化中位 {r.comb_med * 100:+.2f}%/年"
              f"（主口径全 171 组中位 +11.48%/年）")

    print("\n" + "=" * 126)
    print("【段4】分位画像：『再平衡能不能救弱币』的反面与边界")
    print("=" * 126)
    print("  ① 段1 的不掉队比例与单币死拿强度几乎单调反向：")
    srt = cv_all.sort_values("solo_cagr", ascending=False)
    for _, r in srt.iterrows():
        print(f"     {r.coin:6s} 死拿 {r.solo_cagr * 100:+7.2f}%/年 → 不掉队 {r.keep * 100:5.1f}%")
    print(f"  ② Spearman(单币死拿CAGR, 不掉队比例) = "
          f"{cv_all.solo_cagr.corr(cv_all.keep, method='spearman'):+.3f}")

    os.makedirs(OUTDIR, exist_ok=True)
    pd.DataFrame(rows).to_csv(os.path.join(OUTDIR, "holdtime_roll_caliber.csv"),
                              index=False, float_format="%.6f")
    cv_all.to_csv(os.path.join(OUTDIR, "holdtime_caliber_compare.csv"),
                  index=False, float_format="%.6f")
    dd.to_csv(os.path.join(OUTDIR, "holdtime_drawdown.csv"), index=False, float_format="%.6f")
    print(f"\n[落盘] out/holdtime_roll_caliber.csv / holdtime_caliber_compare.csv / holdtime_drawdown.csv")


if __name__ == "__main__":
    main()
