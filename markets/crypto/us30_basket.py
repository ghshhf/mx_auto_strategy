"""
us30_basket.py — 美股篮子敏感性: 指数/行业/龙头 权重与构成扫描
====================================================================
背景 (2026-09-07): 用户口述美股持仓结构 = "两三大指数 + 能源/科技/消费/医疗
行业指数 + 龙头股(当小市值进攻方向)", 想确认"基本这样跑出来 1000 多万"。

本脚本对同一套 30 年周线面板跑多组权重/构成, 输出 30y 全窗口 + 2017-起(加密同窗)
两档, 度量: 期末人民币 / 增值 / IRR(年化) / MDD。
数据: us/data/weekly_adjclose_us30.csv (SPY,QQQ,DIA,XLE,XLP,XLV,XLU,AAPL,NVDA,MSFT[,XLK])
现金流口径与 us30_dca.py 完全一致 (初始¥10,000 + 每月¥2,000, FRED DEXCHUS 折美元)。
用法: python us30_basket.py [--chart]
"""
import os
import sys
import json
import datetime

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import us30_dca as u                      # load_px / load_fx_series / sim_dca 复用
import tri_leg_dca as tld                 # irr_monthly

INITIAL_CNY = u.INITIAL_CNY
MONTHLY_CNY = u.MONTHLY_CNY

CONFIGS = [
    # (名称, 指数层, 行业层, 龙头层, 层权重(指数,行业,龙头))
    ("A. 基准60/20/20 三指数", ["SPY", "QQQ", "DIA"], ["XLE", "XLP", "XLV", "XLU"],
     ["AAPL", "NVDA", "MSFT"], (0.60, 0.20, 0.20)),
    ("B. 两指数50/行业30/龙头20", ["SPY", "QQQ"], ["XLE", "XLP", "XLV", "XLU"],
     ["AAPL", "NVDA", "MSFT"], (0.50, 0.30, 0.20)),
    ("C. 两指数60/20/20", ["SPY", "QQQ"], ["XLE", "XLP", "XLV", "XLU"],
     ["AAPL", "NVDA", "MSFT"], (0.60, 0.20, 0.20)),
    ("D. 龙头进攻加重 40/30/30", ["SPY", "QQQ"], ["XLE", "XLP", "XLV", "XLU"],
     ["AAPL", "NVDA", "MSFT"], (0.40, 0.30, 0.30)),
    ("E. 行业含科技(XLK) 50/30/20", ["SPY", "QQQ"], ["XLE", "XLK", "XLP", "XLV"],
     ["AAPL", "NVDA", "MSFT"], (0.50, 0.30, 0.20)),
    ("F. 三指数40/科技30/其他30/龙头", ["SPY", "QQQ", "DIA"], ["XLE", "XLK", "XLP", "XLV", "XLU"],
     ["AAPL", "NVDA", "MSFT"], (0.40, 0.30, 0.30)),
]

WINDOWS = [("1996-01-01", "30y全窗"), ("2017-01-01", "2017起(加密同窗)")]


def w0_of(cfg, cols):
    _, idx_syms, sec_syms, lead_syms, (wi, ws, wl) = cfg
    w = {}
    for syms, wl_ in ((idx_syms, wi), (sec_syms, ws), (lead_syms, wl)):
        alive = [s for s in syms if s in cols]
        if alive:
            for s in alive:
                w[s] = wl_ / len(alive)
    return w


def metrics(acct_cny, contrib_cny):
    final_cny = float(acct_cny.iloc[-1])
    tot_cny = float(contrib_cny.iloc[-1])
    mult = final_cny / tot_cny
    idx = acct_cny.index
    dep_dates = [idx[0].to_pydatetime().date()]
    dep_amts = [INITIAL_CNY]
    for t in range(1, len(idx)):
        if idx[t].month != idx[t - 1].month:
            dep_dates.append(idx[t].to_pydatetime().date())
            dep_amts.append(MONTHLY_CNY)
    irr = tld.irr_monthly(dep_dates, dep_amts, idx[-1].to_pydatetime().date(), final_cny)
    mdd = float((acct_cny / acct_cny.cummax() - 1).min())
    return final_cny, mult, irr, mdd, tot_cny


def main():
    px = u.load_px()
    fx = u.load_fx_series()
    cols = set(px.columns)
    print(f"面板: {px.shape}  {px.index[0].date()} ~ {px.index[-1].date()}")
    missing = [s for c in CONFIGS for g in c[1:4] for s in g if s not in cols]
    if missing:
        print(f"⚠ 面板缺列: {sorted(set(missing))} (E 配置将跳过缺科技腿)")
    print("=" * 118)

    charts = {}
    rows = []
    for cfg in CONFIGS:
        w0 = w0_of(cfg, cols)
        if not w0:
            print(f"\n### {cfg[0]}  -- 跳过(标的全缺)")
            continue
        res = {"cfg": cfg[0], "windows": {}}
        for start, tag in WINDOWS:
            pxw = px[px.index >= pd.Timestamp(start)]
            fx_w = fx.reindex(pxw.index, method="ffill")
            fxv = fx_w.dropna()
            fx_end = float(fxv.iloc[-1])
            init_usd = INITIAL_CNY / float(fxv.iloc[0])
            monthly_usd = (MONTHLY_CNY / fx_w).values
            acct, contrib = u.sim_dca(pxw, w0, fx_w, init_usd, monthly_usd)
            acct_cny = acct * fx_end
            fc, mult, irr, mdd, tot = metrics(acct_cny, contrib)
            yrs = (pxw.index[-1] - pxw.index[0]).days / 365.25
            rows.append((cfg[0], tag, yrs, fc, mult, irr, mdd))
            res["windows"][tag] = {"final_cny": fc, "multiple": mult,
                                   "irr": irr, "mdd": mdd, "years": yrs}
            if tag == "30y全窗":
                charts[cfg[0]] = acct_cny
            print(f"  [{cfg[0]:<28}] {tag:<12} {yrs:5.1f}y  "
                  f"期末¥{fc:>15,.0f}  {mult:5.1f}x  IRR {irr*100:5.1f}%  MDD {mdd*100:6.1f}%")
        print()

    print("=" * 118)
    print(f"{'配置':<28}{'窗口':<12}{'年数':>6}{'期末¥':>16}{'倍数':>7}{'IRR':>8}{'MDD':>9}")
    for r in rows:
        print(f"{r[0]:<28}{r[1]:<12}{r[2]:>6.1f}¥{r[3]:>13,.0f}{r[4]:>7.1f}"
              f"{r[5]*100:>7.1f}%{r[6]*100:>8.1f}%")

    out = os.path.join(HERE, "us30_basket_results.json")
    json.dump({"note": "初始¥10,000 + 每月¥2,000 按FRED DEXCHUS折USD; 月度再平衡; 未上市摊已上市",
               "configs": [{"name": r[0], "window": r[1], "years": r[2], "final_cny": r[3],
                            "multiple": r[4], "irr": r[5], "mdd": r[6]} for r in rows]},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nJSON: {out}")

    if "--chart" in sys.argv and charts:
        _chart(charts)


def _chart(charts):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    plt.rcParams.update({"axes.facecolor": "#fff", "figure.facecolor": "#fff",
                         "savefig.facecolor": "#fff", "axes.edgecolor": "#888",
                         "axes.labelcolor": "#222", "text.color": "#222",
                         "xtick.color": "#444", "ytick.color": "#444", "grid.color": "#e2e2e2",
                         "font.sans-serif": ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"],
                         "axes.unicode_minus": False})
    styles = {"A. 基准60/20/20 三指数": ("#666", "--", 1.6),
              "B. 两指数50/行业30/龙头20": ("#1565c0", "-", 2.0),
              "C. 两指数60/20/20": ("#6a1b9a", "-", 2.0),
              "D. 龙头进攻加重 40/30/30": ("#2e7d32", "-", 2.2),
              "E. 行业含科技(XLK) 50/30/20": ("#c62828", "-", 2.0),
              "F. 三指数40/科技30/其他30/龙头": ("#ef6c00", "-", 2.0)}
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11.5, 8.4), sharex=True,
                                 gridspec_kw={"height_ratios": [2.4, 1], "hspace": 0.08})
    for name, acct in charts.items():
        if name not in styles:
            continue
        c, ls, lw = styles[name]
        a1.plot(acct.index, acct.values, color=c, ls=ls, lw=lw,
                label=f"{name}  期末 ¥{acct.iloc[-1]/1e4:,.0f}万")
    a1.set_title("美股篮子敏感性 — 指数+行业+龙头 30年DCA (初始¥1万+月投¥2,000, 月度再平衡)",
                 fontsize=12.5, fontweight="bold")
    a1.grid(True, alpha=0.35)
    a1.legend(loc="upper left", fontsize=9, framealpha=0.9)
    a1.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"¥{y/1e6:,.1f}M"))

    ref = charts.get("A. 基准60/20/20 三指数")
    if ref is not None:
        def dd(s):
            return s / s.cummax() - 1.0
        a2.fill_between(ref.index, dd(ref).values * 100, 0, color="#666", alpha=0.15)
        a2.plot(ref.index, dd(ref).values * 100, color="#666", lw=0.9)
        a2.set_ylabel("Drawdown %", fontsize=10)
        a2.set_ylim(-60, 2)
        a2.grid(True, alpha=0.35)
        a2.set_xlabel("Weekly close", fontsize=10)
    plt.tight_layout()
    png = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))),
                       "reports_archive", f"us30_basket_{datetime.date.today():%Y-%m-%d}.png")
    plt.savefig(png, dpi=130)
    print(f"图: {png}")


if __name__ == "__main__":
    main()
