"""
sleeve_mix.py — 防御/进攻 双资金池混合基准 (用户实际结构: ~60% 防御 + ~40% 进攻)
=================================================================================
语义 (2026-09-07 用户口述校准):
  - 用户实际持仓既非纯市值加权也非纯等权, 而是按体量分两仓:
      防御仓(sleeve) = 大体量/大币, 用「市值加权 + 每月再平衡」近似 (84% BTC+ETH 压舱)
      进攻仓        = 小币弹性,   用「等权 + 每月再平衡」近似 (小币高弹性充分释放)
  - 主档: 60% 防御 + 40% 进攻 (池间固定分仓, 各自月调仓, 池间不再平衡)
  - 关键结论(2017-01~2026-09 实测): MDD 对配比极不敏感(纯防御 -81.4% → 纯进攻 -81.2%,
    60/40 仍 -80.2%) → 加密崩盘是系统性的, 大/小币配比改不了最深回撤; 配比真正改变的是
    逐年收益结构(2022/2025 小币崩盘年进攻端拖累, 2020/2021 牛市进攻端爆发)。
    想压回撤须上时间择时/风控层(见 crypto_options_bt 的 crash_guard/vol_target/减半相位,
    对应 MDD ~ -61% / FULL 10y -70.5%), 而非调大/小配比。

数据: data/weekly_adjclose_crypto50_10y.csv (窗口与 cap_index_monthly 一致 2017-01 起)
      mcap_snapshot.json (防御仓目标权重快照)
输出: 配比梯度指标表 + 可选 --chart 出 4 线对比图(市值/60-40/40-60/等权, 含回撤子图)
用法: python sleeve_mix.py [--chart]
"""
import os
import sys
import datetime

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cap_index_monthly as cim
import crypto_adoption_v2 as ca2

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
SNAP = os.path.join(HERE, "mcap_snapshot.json")

_REPORTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "reports_archive")
if not os.path.isdir(_REPORTS):
    _REPORTS = os.path.join(HERE, "out")
OUT_PNG = os.path.join(_REPORTS, f"crypto_sleeve_mix_{datetime.date.today():%Y-%m-%d}.png")


def load_sleeves():
    """返回 (px窗口, def_nav=市值加权月平衡, off_nav=等权月平衡)."""
    px = pd.read_csv(PANEL, index_col=0, parse_dates=True).sort_index()
    px = px[px.index >= pd.Timestamp("2017-01-01")]
    raw = {d["sym"]: (d.get("mcap") or 0) for d in json_load(SNAP)}
    symbols = [c for c in ca2.ALL_COINS if c in px.columns]
    mc = {s: raw.get(s, 0) for s in symbols}
    def_nav = cim.cap_monthly_nav(px, mc, symbols)    # 防御/大币
    off_nav = cim.equal_monthly_nav(px, symbols)      # 进攻/小币
    return px, def_nav, off_nav


def json_load(p):
    import json
    return json.load(open(p, encoding="utf-8"))


def mix(w_def, def_nav, off_nav):
    """两资金池: 初始按 w_def/(1-w_def) 分仓, 各自月调仓, 池间不再平衡(固定分仓)."""
    return (w_def * def_nav + (1 - w_def) * off_nav).rename("mix")


def fmt_row(lbl, nav):
    m, c, d, sh, w = cim.metrics(nav)
    print(f"  {lbl:<24} {m:9.1f}x  CAGR {c*100:6.1f}%  MDD {d*100:6.1f}%  Sharpe {sh:.2f}")
    return m, c, d, sh


def main():
    px, def_nav, off_nav = load_sleeves()
    print(f"窗口: {px.index[0].date()} -> {px.index[-1].date()} ({(px.index[-1]-px.index[0]).days/365.25:.1f}y)")
    print(f"成分: {def_nav.notna().sum() and '全池'} 防御=市值加权月平衡 / 进攻=等权月平衡\n")
    print("=" * 82)
    fmt_row("纯防御 100% (市值加权)", def_nav)
    for wd in (0.7, 0.6, 0.5, 0.4):
        fmt_row(f"防御{int(wd*100):02d}% / 进攻{int((1-wd)*100):02d}%", mix(wd, def_nav, off_nav))
    fmt_row("纯进攻 100% (等权)", off_nav)

    if "--chart" in sys.argv:
        _chart(px, def_nav, off_nav)


def _chart(px, def_nav, off_nav):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    m60 = mix(0.6, def_nav, off_nav)
    m40 = mix(0.4, def_nav, off_nav)
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

    line(a1, def_nav, "#2e7d32", 1.3, "-", "Def-sleeve = CapW + Monthly Rebal (large-cap)")
    line(a1, m60, "#7b1fa2", 2.2, "-", "MIX 60/40 def/off  <-- your structure")
    line(a1, m40, "#ad5fd1", 1.4, "--", "MIX 40/60 def/off")
    line(a1, off_nav, "#e65100", 1.3, "-", "Off-sleeve = EqualW + Monthly Rebal (small-cap)")
    a1.set_yscale("log")
    a1.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:,.0f}x"))
    a1.set_title(f"Defense/Offense Sleeve Mix - Equity Curve "
                 f"({px.index[0]:%Y-%m} ~ {px.index[-1]:%Y-%m}, log)",
                 fontsize=12.5, fontweight="bold")
    a1.grid(True, which="both", alpha=0.35)
    a1.legend(loc="upper left", fontsize=8.0, framealpha=0.9)

    def dd(nav):
        return nav / nav.cummax() - 1.0

    for nav, col, ls in [(def_nav, "#2e7d32", "-"), (m60, "#7b1fa2", "-"),
                         (m40, "#ad5fd1", "--"), (off_nav, "#e65100", "-")]:
        a2.fill_between(nav.index, dd(nav).values * 100, 0, color=col, alpha=0.12)
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
