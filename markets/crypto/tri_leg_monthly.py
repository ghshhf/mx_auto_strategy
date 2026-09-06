"""
tri_leg_monthly.py — 用户最终结构: 60%防御(≈30%美股指数 + ≈30%BTC/ETH大市值) + 40%加密进攻, 全程月度再平衡
========================================================================================================
语义 (2026-09-07 用户口述校准, 在 us_defense_mix "跨资产再平衡才生效" 基础上的定型):
  - 整体仍是 ~60% 防御 / ~40% 进攻 双池框架;
  - 防御的 60% 内部切成两半(各约整体 30%):
      30% 美股指数 = 三大指数 ETF (SPY/QQQ/DIA), 可缩成两个 (SPY/QQQ)
      30% 加密大市值 = BTC + ETH (市值比例 ~84/16, 即旧"市值加权防御"的压舱核心)
  - 进攻 40% = 加密小币等权 (池内 32 币去掉 BTC/ETH 后的 30 币, 每月等权再平衡)
  - 三层之间 + 层内全部【月度】再平衡 (用户: "都以一个月为标准")

关键对比 (2017-01~2026-09; 进攻小币端 2017-11-03 首只上市, 此前资金 100% 在防御端=BTC/ETH+美股):
  - 纯加密 sleeve 60/40 (旧结构, def=全池市值加权/off=全池等权): 640.9x / MDD -80.2%
  - 本结构 A (30美股三指数+30BTC/ETH市值+40小币等权, 月度再平衡): 395.8x / CAGR 85.7%
    / MDD -65.7% / Sharpe 1.27 —— 回撤较纯加密收窄 14.5pt, 牛市弹性让渡约一半
    (2021: +477%→+253%), 换熊市/回调年份明显减损 (2018 -72%→-46%, 2025 -33%→-13%)

数据: crypto/data/weekly_adjclose_crypto50_10y.csv + us/data/weekly_adjclose_us_defense.csv
用法: python tri_leg_monthly.py [--chart]
"""
import os
import sys
import datetime

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cap_index_monthly as cim
import crypto_adoption_v2 as ca2
import sleeve_mix as sm
import us_defense_mix as udm

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
SNAP = os.path.join(HERE, "mcap_snapshot.json")
_US_CSV = os.path.join(os.path.dirname(HERE), "us", "data", "weekly_adjclose_us_defense.csv")

_REPORTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "reports_archive")
if not os.path.isdir(_REPORTS):
    _REPORTS = os.path.join(HERE, "out")
OUT_PNG = os.path.join(_REPORTS, f"tri_leg_monthly_{datetime.date.today():%Y-%m-%d}.png")

# 目标权重(占总仓): 美股30 / 加密大市值30 / 加密进攻40
W_US, W_BIG, W_OFF = 0.30, 0.30, 0.40
US_THREE = ["SPY", "QQQ", "DIA"]
US_TWO = ["SPY", "QQQ"]
BIG_SYMS = ["BTC", "ETH"]


def json_load(p):
    import json
    return json.load(open(p, encoding="utf-8"))


def load_aligned():
    """返回 (px, us, first_off): px=加密面板(2017起), us=对齐加密日期的美股复权价.
    用户校正 (2026-09-07): 小币进攻端是 2017-11 才上市, 但这不代表回测从那时才开始——
    无进攻标的阶段资金默认全在防御端 (BTC/ETH + 美股指数) 运作, 组合满仓不空转.
    first_off = 池内首只非BTC/ETH币上市周 (2017-11-03 BNB), 此前三腿目标权重退化为
    防御端两腿归一 (美股 / BTC+ETH 按防御内比例各半), 之后恢复 30/30/40."""
    px = pd.read_csv(PANEL, index_col=0, parse_dates=True).sort_index()
    px = px[px.index >= pd.Timestamp("2017-01-01")]
    us = udm.load_us_panel()
    us = us.reindex(px.index).ffill()          # 对齐加密面板日期
    off_syms = [c for c in ca2.ALL_COINS if c not in ("BTC", "ETH") and c in px.columns]
    first_off = px[off_syms].notna().any(axis=1).idxmax()   # 首只小币上市周
    return px, us, first_off


def big_nav(px, mc, mode="cap"):
    """加密大市值腿: cap=按市值(BTC~84%/ETH~16%), equal=各半. 月度再平衡."""
    if mode == "cap":
        return cim.cap_monthly_nav(px[BIG_SYMS].astype(float), mc, BIG_SYMS)
    return cim.equal_monthly_nav(px[BIG_SYMS].astype(float), BIG_SYMS)


def us_nav(us, syms):
    return cim.equal_monthly_nav(us[syms].astype(float), syms)


def off_nav(px, first_off):
    """加密小币进攻腿: 池内非BTC/ETH币等权月平衡. 面板截到首只小币上市周
    (此腿净值=1从那周起; 更早无标的, 混合层会把进攻权重清零)."""
    syms = [c for c in ca2.ALL_COINS if c not in ("BTC", "ETH") and c in px.columns]
    sub = px[syms].astype(float)
    sub = sub[sub.index >= first_off]
    return cim.equal_monthly_nav(sub, syms)


def mix_monthly(legs, w_before, w_after, first_off):
    """三层组合月度再平衡. 目标权重按日期切换:
    t < first_off 用 w_before(进攻无标的→防御两腿归一, 如 [0.5,0.5,0]),
    t >= first_off 用 w_after(如 [0.3,0.3,0.4]). 基准 index=legs[0](覆盖全窗口),
    其余腿(如晚上市的进攻腿)早段 fill 1.0 且权重为 0, 不影响净值."""
    base = legs[0].index
    vals = {}
    for i, s in enumerate(legs):
        v = s.reindex(base).ffill()
        vals[i] = v.fillna(1.0).values
    M = np.column_stack([vals[i] for i in range(len(legs))])
    rets = np.zeros_like(M)
    rets[1:] = np.diff(M, axis=0) / M[:-1]  # (n, 3) 周收益
    wb = np.array(w_before, float); wb = wb / wb.sum()
    wa = np.array(w_after, float); wa = wa / wa.sum()
    cur = wb.copy()
    out = np.ones(len(base))
    last_m = base[0].month
    active = False
    for t in range(len(base)):
        if t == 0:
            continue
        if base[t] >= first_off and not active:
            cur = wa.copy()                    # 进攻上市: 一次性切目标
            active = True
        elif base[t].month != last_m:          # 月度再平衡
            cur = (wa if active else wb).copy()
            last_m = base[t].month
        r = rets[t]
        out[t] = out[t - 1] * (1 + float(cur @ r))
        cur = cur * (1 + r) / (1 + float(cur @ r))  # 月内漂移
    return pd.Series(out, index=base, name="tri_leg")


def fmt(lbl, nav):
    m, c, d, sh, n = cim.metrics(nav)
    print(f"  {lbl:<40} {m:10.1f}x  CAGR {c*100:6.1f}%  MDD {d*100:6.1f}%  Sharpe {sh:.2f}")
    return m, c, d, sh


def main():
    px, us, first_off = load_aligned()
    mc = {d["sym"]: (d.get("mcap") or 0) for d in json_load(SNAP)}
    start, end = px.index[0], px.index[-1]
    yrs = (end - start).days / 365.25
    print(f"窗口: {start.date()} -> {end.date()} ({yrs:.1f}y), 加密面板{px.shape[1]}币")
    print(f"小币进攻端首只上市周: {first_off.date()} (此前资金全在防御端=BTC/ETH+美股)")

    # 三条腿
    us3 = us_nav(us, US_THREE)
    us2 = us_nav(us, US_TWO)
    big_cap = big_nav(px, mc, "cap")        # BTC/ETH 市值比例
    big_eq = big_nav(px, mc, "equal")       # BTC/ETH 各半
    off = off_nav(px, first_off)            # 小币等权(30币), 从首只上市周起
    print("=" * 100)

    # 旧结构参照
    _, def_nav, off_all = sm.load_sleeves()
    old_60 = sm.mix(0.6, def_nav, off_all)  # 旧 sleeve 60/40 (全池市值/全池等权)
    print("--- 参照 ---")
    fmt("旧结构: 纯加密 60/40 sleeve (全池)", old_60)
    print("--- 单腿 ---")
    fmt("美股三指数(SPY/QQQ/DIA 等权月调)", us3)
    fmt("美股两指数(SPY/QQQ 等权月调)", us2)
    fmt("BTC/ETH 市值加权腿(月调)", big_cap)
    fmt("BTC/ETH 各半腿(月调)", big_eq)
    fmt("加密小币等权腿(30币,月调,自上市周)", off)

    # 主结构: 2017-11 前全防御(BTC/ETH:美股 按防御内各半), 之后 30/30/40
    wb = [0.5, 0.5, 0.0]                     # 无进攻标的: 防御两腿归一各半
    wa = [W_US, W_BIG, W_OFF]                # 30 美股 / 30 大市值 / 40 小币
    print("\n--- 主结构: 30美股 + 30大市值 + 40小币进攻, 月度再平衡 ---")
    main_nav = mix_monthly([us3, big_cap, off], wb, wa, first_off)
    fmt("A. 美股三指数 / BTC+ETH市值 / 小币40", main_nav)
    alt1 = mix_monthly([us3, big_eq, off], wb, wa, first_off)
    fmt("B. A但BTC/ETH各半", alt1)
    alt2 = mix_monthly([us2, big_cap, off], wb, wa, first_off)
    fmt("C. A但美股缩成SPY/QQQ", alt2)
    alt3 = mix_monthly([us2, big_eq, off], wb, wa, first_off)
    fmt("D. BTC/ETH各半 + 美股两指数", alt3)

    # 年度收益 & 熊市段回撤 (主结构 A vs 旧纯加密)
    print("\n=== 逐年收益: 旧纯加密 sleeve vs 主结构A ===")
    yc = old_60.resample("YE").last().pct_change()
    ym = main_nav.resample("YE").last().pct_change()
    print(f"  {'年份':<6}{'纯加密60/40':>14}{'主结构A':>16}")
    for yr in yc.index:
        if yr.year < 2017:
            continue
        print(f"  {yr.year:<6}{yc.get(yr, np.nan)*100:>13.1f}%{ym.get(yr, np.nan)*100:>15.1f}%")

    print("\n=== 主要熊市段最深回撤 (纯加密 vs 主结构A) ===")
    dd_old = old_60 / old_60.cummax() - 1.0
    dd_new = main_nav / main_nav.cummax() - 1.0
    for lbl, lo, hi in [("2018 加密熊", "2018-01-01", "2019-03-01"),
                        ("2022 加密熊", "2021-11-01", "2023-03-01"),
                        ("2026 回调", "2025-12-01", "2026-09-04")]:
        s_old = dd_old[(dd_old.index >= lo) & (dd_old.index <= hi)]
        s_new = dd_new[(dd_new.index >= lo) & (dd_new.index <= hi)]
        print(f"  {lbl:<12} 纯加密 {s_old.min()*100:6.1f}%   主结构A {s_new.min()*100:6.1f}%")

    if "--chart" in sys.argv:
        _chart(px, old_60, main_nav, alt1, us3, big_cap, off)


def _chart(px, old_60, main_nav, alt1, us3, big_cap, off):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    plt.rcParams.update({"axes.facecolor": "#fff", "figure.facecolor": "#fff",
                         "savefig.facecolor": "#fff", "axes.edgecolor": "#888",
                         "axes.labelcolor": "#222", "text.color": "#222",
                         "xtick.color": "#444", "ytick.color": "#444", "grid.color": "#e2e2e2"})
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 8.4), sharex=True,
                                 gridspec_kw={"height_ratios": [2.4, 1], "hspace": 0.08})

    def line(ax, nav, col, lw, ls, lbl):
        m, c, d, sh, _ = cim.metrics(nav)
        ax.plot(nav.index, nav.values, color=col, lw=lw, ls=ls,
                label=f"{lbl}  {m:.0f}x | MDD {d*100:.0f}% | Sh {sh:.2f}")

    line(a1, old_60, "#c62828", 1.2, "--", "Old: pure crypto 60/40 sleeve")
    line(a1, main_nav, "#2e7d32", 2.3, "-", "NEW 30US/30Big/40Off (monthly reb)  <-- plan")
    line(a1, alt1, "#7b1fa2", 1.4, "-.", "NEW but BTC/ETH 50-50")
    line(a1, big_cap, "#e65100", 1.0, ":", "Big-cap leg (BTC/ETH mcap)")
    line(a1, us3, "#1565c0", 1.2, "-", "US 3-index leg")
    a1.set_yscale("log")
    a1.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:,.0f}x"))
    a1.set_title(f"Tri-Leg 30/30/40 Monthly Rebal - Equity Curve "
                 f"({px.index[0]:%Y-%m} ~ {px.index[-1]:%Y-%m}, log)",
                 fontsize=12.5, fontweight="bold")
    a1.grid(True, which="both", alpha=0.35)
    a1.legend(loc="upper left", fontsize=8.0, framealpha=0.9)

    def dd(nav):
        return nav / nav.cummax() - 1.0

    for nav, col, ls in [(old_60, "#c62828", "--"), (main_nav, "#2e7d32", "-"),
                         (alt1, "#7b1fa2", "-."), (us3, "#1565c0", "-")]:
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
