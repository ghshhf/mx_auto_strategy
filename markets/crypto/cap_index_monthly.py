"""
cap_index_monthly.py — 当前34币池「全部买入 + 市值加权 + 每月再平衡」指数基准
=================================================================================
与 index_buyhold.py 的区别:
  - index_buyhold 的 cap 是【固定快照、不调仓】; rebal 是【周度等权】。
  - 本脚本是用户要的精确语义: 权重 = 市值快照比例, 且【每月(跨月首个周五)再平衡】回目标权重。
  - 成分币首根有价即纳入, 未上市币权重为 0, 上市后首个再平衡日进入(贴近真实指数。

数据: data/weekly_adjclose_crypto50_10y.csv (截到 2017-01-01, 与动量策略同窗口)
      mcap_snapshot.json (当前市值快照, 仅取池内34币)
输出: 倍数/CAGR/MDD/Sharpe + 可选 --nav 存 index_nav_cap_monthly.csv + 可选 --chart 出四线对比图
"""
import os
import sys
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crypto_adoption_v2 as ca2
import backtest_v2 as bt

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
SNAP = os.path.join(HERE, "mcap_snapshot.json")
OUT_PNG = "E:/xmanbian/reports_archive/crypto_backtest_10y_capindex_5line_2026-09-04.png"


def cap_monthly_nav(px, mc, symbols):
    """市值加权 + 每月再平衡的 NAV 序列(重基=1)。"""
    sub = px[symbols].astype(float)
    vals = sub.values
    dates = px.index
    n = len(px)
    out = [float("nan")] * n
    weights = np.zeros(len(symbols))
    last_month = None
    prev = None
    for i in range(n):
        if i == 0:
            caps = np.array([mc[s] for s in symbols], float)
            tr = ~np.isnan(vals[i]) & (vals[i] > 0) & (caps > 0)
            wc = caps[tr]
            wc = wc / wc.sum()
            weights = np.zeros(len(symbols))
            weights[tr] = wc
            last_month = dates[i].month
            out[i] = 1.0
            prev = vals[i].copy()
            continue
        row = vals[i]
        wk = np.ones(len(symbols))
        v = ~np.isnan(row) & ~np.isnan(prev) & (prev > 0)
        wk[v] = row[v] / prev[v]
        wk[~v] = 1.0  # 缺失周视为持平(权重仍在)
        nav = (out[i - 1] if np.isfinite(out[i - 1]) else 1.0) * np.sum(weights * wk)
        out[i] = nav
        prev = row.copy()
        if dates[i].month != last_month:  # 跨月首周五再平衡
            caps = np.array([mc[s] for s in symbols], float)
            tr = ~np.isnan(row) & (row > 0) & (caps > 0)
            if tr.sum() > 0:
                wc = caps[tr]
                wc = wc / wc.sum()
                weights = np.zeros(len(symbols))
                weights[tr] = wc
            last_month = dates[i].month
    return pd.Series(out, index=dates, name="cap_monthly")


def metrics(s):
    rets = s.pct_change().dropna()
    mult = float(s.iloc[-1])
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = mult ** (1 / yrs) - 1
    mdd = float((s / s.cummax() - 1).min())
    sharpe = float(rets.mean() / rets.std() * np.sqrt(52))
    return mult, cagr, mdd, sharpe, len(s)


def main():
    px = pd.read_csv(PANEL, index_col=0, parse_dates=True).sort_index()
    px = px[px.index >= pd.Timestamp("2017-01-01")]
    raw = {d["sym"]: (d.get("mcap") or 0) for d in json.load(open(SNAP))}
    symbols = [c for c in ca2.ALL_COINS if c in px.columns]  # 仅池内34币
    mc = {s: raw.get(s, 0) for s in symbols}
    print(f"面板窗口: {px.index[0].date()} ~ {px.index[-1].date()} ({(px.index[-1]-px.index[0]).days/365.25:.1f}y)")
    print(f"市值加权成分币数: {len(symbols)} (池内 ALL_COINS={len(ca2.ALL_COINS)})")
    print("=" * 78)

    # ---- 主力: 市值加权 + 月平衡 ----
    cap_nav = cap_monthly_nav(px, mc, symbols)
    m, c, d, sh, w = metrics(cap_nav)
    print(f"\n### [主力] 市值加权 + 每月再平衡 (全{len(symbols)}币)\n"
          f"    倍数={m:.1f}x  CAGR={c*100:.1f}%  MDD={d*100:.1f}%  Sharpe={sh:.2f}  周数={w}")

    # 期初权重分布
    caps0 = np.array([mc[s] for s in symbols], float)
    tr0 = ~np.isnan(px[symbols].iloc[0].values) & (px[symbols].iloc[0].values > 0) & (caps0 > 0)
    wc0 = caps0[tr0]
    wc0 = wc0 / wc0.sum()
    trad_sym = [symbols[j] for j in range(len(symbols)) if tr0[j]]
    top = sorted(zip(trad_sym, wc0), key=lambda x: -x[1])[:8]
    print("    期初权重(Top8, 市值占比):")
    for s_, w_ in top:
        print(f"      {s_:>6}: {w_*100:5.1f}%")
    btc_eth = sum(w_ for s_, w_ in zip(trad_sym, wc0) if s_ in ("BTC", "ETH"))
    print(f"    BTC+ETH 合计占比: {btc_eth*100:.1f}%")

    # ---- 参考变体 ----
    # 市值加权 不调仓
    nav_nr = cap_monthly_nav_static(px, mc, symbols)
    m2, c2, d2, sh2, _ = metrics(nav_nr)
    print(f"\n### [参考] 市值加权 不调仓\n    倍数={m2:.1f}x  CAGR={c2*100:.1f}%  MDD={d2*100:.1f}%  Sharpe={sh2:.2f}")
    # 等权 月平衡
    nav_ew = equal_monthly_nav(px, symbols)
    m3, c3, d3, sh3, _ = metrics(nav_ew)
    print(f"\n### [参考] 等权 每月再平衡\n    倍数={m3:.1f}x  CAGR={c3*100:.1f}%  MDD={d3*100:.1f}%  Sharpe={sh3:.2f}")

    # ---- 与动量策略同窗口对比 ----
    cfg = {"mode": "self", "thr": -0.15, "floor": 0.40}
    base = bt.run_backtest(px, cost_bps=0.001, label="Offense Top3 (base)",
                           crash_guard=None, vol_target=None, offense_n=3)
    guard = bt.run_backtest(px, cost_bps=0.001, label="Defense +Crash+VolT",
                            crash_guard=cfg, vol_target=0.60, offense_n=3)
    btc = px["BTC"].dropna()
    btc_nav = btc / btc.iloc[0]
    bm, bc, bd, bsh = (float(btc_nav.iloc[-1]), 0.0,
                       float((btc_nav / btc_nav.cummax() - 1).min()),
                       float(btc_nav.pct_change().dropna().mean() /
                             btc_nav.pct_change().dropna().std() * np.sqrt(52)))
    print("\n" + "=" * 78)
    print("同窗口(2017-01~2026-08) 四策略对比:")
    print(f"  进攻Top3基础       : {base['multiple']:.1f}x  CAGR {base['cagr']*100:.1f}%  MDD {base['mdd']*100:.1f}%  Sharpe {base['sharpe']:.2f}")
    print(f"  防御+Crash+VolT     : {guard['multiple']:.1f}x  CAGR {guard['cagr']*100:.1f}%  MDD {guard['mdd']*100:.1f}%  Sharpe {guard['sharpe']:.2f}")
    print(f"  BTC买入持有         : {bm:.1f}x   CAGR  -    MDD {bd*100:.1f}%  Sharpe {bsh:.2f}")
    print(f"  市值加权+月平衡     : {m:.1f}x  CAGR {c*100:.1f}%  MDD {d*100:.1f}%  Sharpe {sh:.2f}")

    if "--nav" in sys.argv:
        cap_nav.to_csv(os.path.join(HERE, "index_nav_cap_monthly.csv"), header=True)
        print("\n输出 index_nav_cap_monthly.csv")
    if "--chart" in sys.argv:
        make_chart(base, guard, btc_nav, bm, bd, bsh, cap_nav, m, c, d, sh,
                   nav_ew, m3, c3, d3, sh3)
        print(f"\n输出对比图: {OUT_PNG}")


def cap_monthly_nav_static(px, mc, symbols):
    """市值加权 不调仓(权重随价格漂移, 期初定权重)。"""
    sub = px[symbols].astype(float)
    caps = np.array([mc[s] for s in symbols], float)
    tr = ~np.isnan(sub.iloc[0].values) & (sub.iloc[0].values > 0) & (caps > 0)
    wc = caps[tr]
    wc = wc / wc.sum()
    w = np.zeros(len(symbols))
    w[tr] = wc
    p0 = sub.iloc[0].values
    out = []
    for i in range(len(px)):
        pend = sub.iloc[i].values
        nav = sum(w[j] * (pend[j] / p0[j]) for j in range(len(symbols))
                  if np.isfinite(pend[j]) and np.isfinite(p0[j]) and p0[j] > 0)
        out.append(nav if nav > 0 else float("nan"))
    return pd.Series(out, index=px.index, name="cap_static")


def equal_monthly_nav(px, symbols):
    sub = px[symbols].astype(float)
    vals = sub.values
    dates = px.index
    n = len(px)
    out = [float("nan")] * n
    weights = np.zeros(len(symbols))
    last_month = None
    prev = None
    for i in range(n):
        if i == 0:
            tr = ~np.isnan(vals[i]) & (vals[i] > 0)
            k = tr.sum()
            weights = np.zeros(len(symbols))
            weights[tr] = 1.0 / k
            last_month = dates[i].month
            out[i] = 1.0
            prev = vals[i].copy()
            continue
        row = vals[i]
        wk = np.ones(len(symbols))
        v = ~np.isnan(row) & ~np.isnan(prev) & (prev > 0)
        wk[v] = row[v] / prev[v]
        wk[~v] = 1.0
        out[i] = (out[i - 1] if np.isfinite(out[i - 1]) else 1.0) * np.sum(weights * wk)
        prev = row.copy()
        if dates[i].month != last_month:
            tr = ~np.isnan(row) & (row > 0)
            k = tr.sum()
            if k > 0:
                weights = np.zeros(len(symbols))
                weights[tr] = 1.0 / k
            last_month = dates[i].month
    return pd.Series(out, index=dates, name="equal_monthly")


def make_chart(base, guard, btc_nav, bm, bd, bsh, cap_nav, m, c, d, sh,
               ew_nav, ewm, ewc, ewd, ewsh):
    plt.rcParams.update({"axes.facecolor": "#fff", "figure.facecolor": "#fff",
                         "savefig.facecolor": "#fff", "axes.edgecolor": "#888",
                         "axes.labelcolor": "#222", "text.color": "#222",
                         "xtick.color": "#444", "ytick.color": "#444", "grid.color": "#e2e2e2"})
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8.4), sharex=True,
                                   gridspec_kw={"height_ratios": [2.4, 1], "hspace": 0.08})

    ax1.plot(base["nav"].index, base["nav"].values, color="#d12b2b", lw=1.4,
             label=f"Offense Top3 (base)  {base['multiple']:.0f}x / MDD {base['mdd']*100:.0f}%")
    ax1.plot(guard["nav"].index, guard["nav"].values, color="#1f6fb4", lw=1.4,
             label=f"Defense +Crash+VolT  {guard['multiple']:.0f}x / MDD {guard['mdd']*100:.0f}%")
    ax1.plot(btc_nav.index, btc_nav.values, color="#555", lw=1.2, ls="--",
             label=f"BTC buy&hold  {bm:.0f}x / MDD {bd*100:.0f}%")
    ax1.plot(cap_nav.index, cap_nav.values, color="#2e7d32", lw=1.6,
             label=f"Cap-Weight +Monthly Rebal  {m:.0f}x / MDD {d*100:.0f}%")
    ax1.plot(ew_nav.index, ew_nav.values, color="#e65100", lw=1.6,
             label=f"Equal-Weight +Monthly Rebal  {ewm:.0f}x / MDD {ewd*100:.0f}%")

    ax1.set_yscale("log")
    ax1.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:,.0f}x"))
    ax1.set_title("Crypto Strategy 10Y Backtest - Equity Curve (2017-01 ~ 2026-08, 34-coin pool, log)",
                  fontsize=12.5, fontweight="bold")
    ax1.grid(True, which="both", alpha=0.35)
    ax1.legend(loc="upper left", fontsize=8.2, framealpha=0.9)

    def dd(nav):
        return nav / nav.cummax() - 1.0

    for nav, col in [(base["nav"], "#d12b2b"), (guard["nav"], "#1f6fb4"),
                     (btc_nav, "#555"), (cap_nav, "#2e7d32"), (ew_nav, "#e65100")]:
        ax2.fill_between(nav.index, dd(nav).values * 100, 0, color=col, alpha=0.16)
        ax2.plot(nav.index, dd(nav).values * 100, color=col, lw=0.8)
    ax2.set_ylabel("Drawdown %", fontsize=10)
    ax2.set_ylim(-90, 2)
    ax2.grid(True, alpha=0.35)
    ax2.set_xlabel("Weekly close", fontsize=10)

    tbl = (f"Metrics       Mult     CAGR    MDD     Sharpe\n"
           f"Offense base   {base['multiple']:7.1f}x {base['cagr']*100:5.1f}% {base['mdd']*100:6.1f}%  {base['sharpe']:.2f}\n"
           f"Defense        {guard['multiple']:7.1f}x {guard['cagr']*100:5.1f}% {guard['mdd']*100:6.1f}%  {guard['sharpe']:.2f}\n"
           f"CapW+Monthly   {m:7.1f}x {c*100:5.1f}% {d*100:6.1f}%  {sh:.2f}\n"
           f"EqualW+Monthly {ewm:7.1f}x {ewc*100:5.1f}% {ewd*100:6.1f}%  {ewsh:.2f}\n"
           f"BTC hold       {bm:7.1f}x    -    {bd*100:6.1f}%  {bsh:.2f}")
    ax1.text(0.985, 0.04, tbl, transform=ax1.transAxes, fontsize=8.2,
             family="DejaVu Sans", ha="right", va="bottom", linespacing=1.5,
             bbox=dict(boxstyle="round", fc="#f6f6f6", ec="#ccc"))
    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=130)
    print("chart saved")


if __name__ == "__main__":
    main()
