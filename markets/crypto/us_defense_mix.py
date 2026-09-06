"""
us_defense_mix.py — 加密进攻端 + 美股防御端 跨资产混合基准
=================================================================================
用户结构 (2026-09-07 口述):
  - 加密端 = 全部加密仓(进攻), 用 sleeve_mix 的 60/40 (防御市值加权/进攻等权) 作代表
  - 美股防御端 = 三大指数 ETF (SPY/QQQ/DIA) + 能源 (XLE/CVX) + 大消费防御 (XLP/KO/PG)
  - 结论背景: 加密内部大/小币配比压不下最深回撤(-80% 档, 崩盘系统性 β→1);
    真正能压回撤的是跨资产——美股与加密周收益相关 ~0 (+0.05), MDD -22%~-35%.

★ 核心结论 (2017-01~2026-09 实测):
  - 固定分仓(买了放着不调) 50/50: MDD 仍 -80.0% —— 加美股但不再平衡 = 没有防御,
    因为加密涨成大头后崩盘, 美股仓只是"没帮上忙也没拖后腿".
  - 季度再平衡 13周 50/50: MDD -53.6% / Sharpe 1.39 (纯加密 -80.2% / 1.22)
    加密涨上去减仓进美股, 跌下来美股是弹药 → 波动收割, 这才是"防御端放美股"的正确姿势.
  - 崩盘段: 2018熊 -79.7%→-50.9%, 2022熊 -80.2%→-53.6%, 2026回调 -62.2%→-28.8%
  - 代价: 牛市弹性减半 (2021 +477%→+273%, 2020 +250%→+107%), 因为涨的年份持续被再平衡抽走.

数据:
  - 加密: data/weekly_adjclose_crypto50_10y.csv + sleeve_mix.load_sleeves() (2017-01 起)
  - 美股: markets/us/data/weekly_adjclose_us_defense.csv (W-FRI, 2014-08 起, yfinance 复权)
输出: 加密/美股不同配比混合指标表 + 分年对比 + 可选 --chart 出图
用法: python us_defense_mix.py [--chart]   (仓库根: python markets/crypto/us_defense_mix.py)
"""
import os
import sys
import datetime

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cap_index_monthly as cim
import sleeve_mix as sm

_REPORTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "reports_archive")
if not os.path.isdir(_REPORTS):
    _REPORTS = os.path.join(HERE, "out")
OUT_PNG = os.path.join(_REPORTS, f"us_defense_mix_{datetime.date.today():%Y-%m-%d}.png")

# 美股防御端候选组合 (权重和=1)
DEF_COMBO = {
    "三大指数等权": {"SPY": 1/3, "QQQ": 1/3, "DIA": 1/3},
    "指数+能源": {"SPY": 0.50, "QQQ": 0.20, "XLE": 0.15, "CVX": 0.15},
    "指数+防御股": {"SPY": 0.40, "QQQ": 0.20, "XLP": 0.15, "KO": 0.10, "PG": 0.15},
    "全防御等权": {"SPY": 0.15, "QQQ": 0.10, "DIA": 0.10, "XLE": 0.10, "XLP": 0.10,
                 "XLV": 0.10, "XLU": 0.10, "KO": 0.10, "CVX": 0.05, "PG": 0.10},
}


def load_us_panel():
    """美股防御端周线, 对齐 sleeve 窗口 (2017-01 起)."""
    p = os.path.join(os.path.dirname(HERE), "us", "data", "weekly_adjclose_us_defense.csv")
    us = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
    return us


def build_def_nav(us, combo, start=None):
    """按权重合成防御端 NAV (等权月再平衡近似: 组合权重固定但随价格漂移, 用周收益加权)."""
    cols = [c for c in combo if c in us.columns and us[c].notna().sum() > 50]
    wsum = sum(combo[c] for c in cols)
    w = {c: combo[c] / wsum for c in cols}
    rets = us[cols].pct_change().fillna(0.0)
    port_ret = sum(w[c] * rets[c] for c in cols)
    nav = (1.0 + port_ret).cumprod()
    nav = nav / nav.iloc[0]
    if start is not None:
        nav = nav[nav.index >= start]
    return nav.rename("def_nav")


def mix_crypto_us(crypto_nav, def_nav, w_crypto, rebal_weeks=None):
    """加密/美股 两仓混合. rebal_weeks=None => 固定分仓(池间不再平衡);
    rebal_weeks=N => 每 N 周拉回目标权重 (真再平衡)."""
    a = crypto_nav.reindex(def_nav.index.union(crypto_nav.index)).ffill().fillna(1.0)
    b = def_nav.reindex(a.index).ffill().fillna(1.0)
    ra, rb = a.pct_change().fillna(0.0), b.pct_change().fillna(0.0)
    idx = a.index
    nav = np.ones(len(idx))
    w = np.array([w_crypto, 1 - w_crypto])
    for t in range(1, len(idx)):
        r = np.array([ra.iloc[t], rb.iloc[t]])
        nav[t] = nav[t-1] * (1 + float(w @ r))
        if rebal_weeks and t % rebal_weeks == 0:
            w = np.array([w_crypto, 1 - w_crypto])   # 拉回目标
        else:
            w = w * (1 + r) / (1 + float(w @ r))     # 漂移
    return pd.Series(nav, index=idx).rename("mix")


def fmt_row(lbl, nav):
    m, c, d, sh, w = cim.metrics(nav)
    print(f"  {lbl:<34} {m:9.1f}x  CAGR {c*100:6.1f}%  MDD {d*100:6.1f}%  Sharpe {sh:.2f}")
    return m, c, d, sh


def main():
    px, def_nav, off_nav = sm.load_sleeves()
    crypto60 = sm.mix(0.6, def_nav, off_nav)     # 加密端: 60/40 sleeve = 640.9x
    us = load_us_panel()
    start = px.index[0]

    print(f"窗口: {start.date()} -> {px.index[-1].date()} "
          f"({(px.index[-1]-start).days/365.25:.1f}y), 加密端=60/40 sleeve\n")
    print("=" * 96)
    fmt_row("纯加密 100% (60/40 sleeve)", crypto60)

    # 防御端三档对比 (50/50 混合, 固定分仓)
    print("\n--- 防御端组合选择 (加密50% / 美股50%, 固定分仓) ---")
    for name, combo in DEF_COMBO.items():
        dn = build_def_nav(us, combo, start=start)
        mxd = mix_crypto_us(crypto60, dn, 0.5)
        print(f"  防御端={name}:")
        fmt_row("    纯防御端(单看)", dn)
        fmt_row("    50加密/50防御 混合", mxd)

    # 主表: 用「三大指数+防御股」作防御端 (用户点名 SPY/QQQ + XLP/KO/CVX), 固定分仓 vs 季调
    main_combo = {"SPY": 0.35, "QQQ": 0.25, "DIA": 0.10, "XLE": 0.10, "XLP": 0.10, "KO": 0.10}
    dn = build_def_nav(us, main_combo, start=start)
    print("\n--- 主防御端 = SPY 35 + QQQ 25 + DIA 10 + XLE 10 + XLP 10 + KO 10 ---")
    fmt_row("纯防御端(单看)", dn)

    print("\n=== 配比梯度 (加密/美股, 固定分仓) ===")
    for wc in (1.0, 0.8, 0.7, 0.6, 0.5, 0.4):
        fmt_row(f"加密{int(wc*100):02d}% / 美股{int((1-wc)*100):02d}%", mix_crypto_us(crypto60, dn, wc))
    print("\n=== 配比梯度 (加密/美股, 季度再平衡=13周) ===")
    for wc in (1.0, 0.8, 0.7, 0.6, 0.5, 0.4):
        fmt_row(f"加密{int(wc*100):02d}% / 美股{int((1-wc)*100):02d}% (季调)",
                mix_crypto_us(crypto60, dn, wc, rebal_weeks=13))

    # 逐年对比 (60/40 加密 vs 50/50 跨资产)
    print("\n=== 逐年收益对比 ===")
    pure = crypto60
    mix5 = mix_crypto_us(crypto60, dn, 0.5)
    yc = pure.resample("YE").last().pct_change()
    ym = mix5.resample("YE").last().pct_change()
    print(f"  {'年份':<6}{'纯加密60/40':>14}{'50加密/50美股':>16}")
    for yr in yc.index:
        if yr.year < 2017: continue
        print(f"  {yr.year:<6}{yc.get(yr, np.nan)*100:>13.1f}%{ym.get(yr, np.nan)*100:>15.1f}%")

    # 最差年份回撤对比: 用季调版(真防御) 而非固定分仓(无防御)
    mix5_q = mix_crypto_us(crypto60, dn, 0.5, rebal_weeks=13)
    print("\n=== 主要熊市段最深回撤 (纯加密 vs 季调50/50) ===")
    for nav, tag in [(pure, "纯加密"), (mix5_q, "季调50/50")]:
        dd_all = nav / nav.cummax() - 1.0
        for lbl, lo, hi in [("2018 加密熊", "2018-01-01", "2019-03-01"),
                            ("2022 加密熊", "2021-11-01", "2023-03-01"),
                            ("2026 回调", "2025-12-01", "2026-09-04")]:
            seg = dd_all[(dd_all.index >= lo) & (dd_all.index <= hi)]
            if len(seg) and tag == "纯加密":
                print(f"  {lbl:<12} {tag} {seg.min()*100:6.1f}%", end="")
            elif len(seg):
                print(f"   {tag} {seg.min()*100:6.1f}%")
        if tag == "纯加密":
            print()

    if "--chart" in sys.argv:
        _chart(px, crypto60, dn)


def _chart(px, crypto60, dn):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    mix5 = mix_crypto_us(crypto60, dn, 0.5, rebal_weeks=13)
    mix7 = mix_crypto_us(crypto60, dn, 0.7, rebal_weeks=13)
    plt.rcParams.update({"axes.facecolor": "#fff", "figure.facecolor": "#fff",
                         "savefig.facecolor": "#fff", "axes.edgecolor": "#888",
                         "axes.labelcolor": "#222", "text.color": "#222",
                         "xtick.color": "#444", "ytick.color": "#444", "grid.color": "#e2e2e2"})
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 8.4), sharex=True,
                                 gridspec_kw={"height_ratios": [2.4, 1], "hspace": 0.08})

    def line(ax, nav, col, lw, ls, lbl):
        m, c, d, sh, _ = cim.metrics(nav)
        ax.plot(nav.index, nav.values, color=col, lw=lw, ls=ls,
                label=f"{lbl}  {m:.0f}x | CAGR {c*100:.0f}% | MDD {d*100:.0f}% | Sh {sh:.2f}")

    line(a1, crypto60, "#c62828", 1.4, "-", "Crypto 100% (60/40 sleeve)")
    line(a1, mix7, "#e65100", 1.5, "-", "70% crypto / 30% US (quarterly reb)")
    line(a1, mix5, "#2e7d32", 2.2, "-", "50% crypto / 50% US (quarterly reb)  <-- plan")
    line(a1, dn, "#1565c0", 1.4, "-", "US defense sleeve (SPY/QQQ/DIA/XLE/XLP/KO)")
    a1.set_yscale("log")
    a1.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:,.0f}x"))
    a1.set_title(f"Crypto Offense + US Defense Mix - Equity Curve "
                 f"({px.index[0]:%Y-%m} ~ {px.index[-1]:%Y-%m}, log)",
                 fontsize=12.5, fontweight="bold")
    a1.grid(True, which="both", alpha=0.35)
    a1.legend(loc="upper left", fontsize=8.0, framealpha=0.9)

    def dd(nav):
        return nav / nav.cummax() - 1.0

    for nav, col, ls in [(crypto60, "#c62828", "-"), (mix7, "#e65100", "-"),
                         (mix5, "#2e7d32", "-"), (dn, "#1565c0", "-")]:
        a2.fill_between(nav.index, dd(nav).values * 100, 0, color=col, alpha=0.10)
        a2.plot(nav.index, dd(nav).values * 100, color=col, lw=0.9, ls=ls)
    a2.set_ylabel("Drawdown %", fontsize=10)
    a2.set_ylim(-90, 2)
    a2.grid(True, alpha=0.35)
    a2.set_xlabel("Weekly close", fontsize=10)
    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=130)
    print(f"\n输出对比图: {OUT_PNG}")


if __name__ == "__main__":
    main()
