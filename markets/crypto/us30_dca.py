"""
us30_dca.py — 美股30年纯权益DCA回测: 初始¥1万 + 每月¥2,000, 指数+行业+龙头, 月度再平衡
========================================================================================================
背景 (2026-09-07 用户): "单独看美股这块30年, 只买指数和行业和龙头(苹果英伟达这种), 看最后能得多少"
对照锚点: 加密 tri_leg 30/30/40 (2017-2026, 同现金流) 期末 ¥1,277 万 (i10000_m2000版)

组合 (目标权重, 层内等权, 月度再平衡):
  指数层 60%: SPY(标普500) / QQQ(纳指100) / DIA(道指)
  行业层 20%: XLE(能源) / XLP(必需消费) / XLV(医疗) / XLU(公用)
  龙头层 20%: AAPL / NVDA / MSFT
  未上市标的权重实时摊给已上市标的(无前视); 加仓日=调仓日=每月初

现金流口径 (与 tri_leg_dca_cny.py 一致):
  初始 ¥10,000 + 每月 ¥2,000, 按 FRED DEXCHUS 当月汇率折 USD 买入; 期末按最近汇率折人民币

两个窗口:
  A. 美股 30 年全窗口 (1996-01 ~ 2026-09, 能拿多久拿多久)
  B. 加密同窗口对照 (2017-01 ~ 2026-09) —— 与加密版并排, 回答"加密是不是一山更比一山高"
用法: python us30_dca.py [--chart]
"""
import os
import sys
import json
import datetime

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MARKETS = os.path.dirname(HERE)                        # markets/
sys.path.insert(0, HERE)
import tri_leg_dca as tld                       # markets/crypto/ 的 irr_monthly 复用

US30_CSV = os.path.join(MARKETS, "us", "data", "weekly_adjclose_us30.csv")
FX_CSV = os.path.join(HERE, "data", "DEXCHUS.csv")     # FRED USDCNY

_REPORTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "reports_archive")
if not os.path.isdir(_REPORTS):
    _REPORTS = os.path.join(HERE, "out")
OUT_PNG = os.path.join(_REPORTS, f"us30_dca_{datetime.date.today():%Y-%m-%d}.png")
OUT_JSON = os.path.join(HERE, "us30_dca_results.json")

INITIAL_CNY = 10000.0
MONTHLY_CNY = 2000.0

GROUPS = {
    "指数": ["SPY", "QQQ", "DIA"],
    "行业": ["XLE", "XLP", "XLV", "XLU"],
    "龙头": ["AAPL", "NVDA", "MSFT"],
}
LAYER_W = {"指数": 0.60, "行业": 0.20, "龙头": 0.20}     # 层权重
US30_ALL = [t for g in GROUPS.values() for t in g]


def json_load(p):
    return json.load(open(p, encoding="utf-8"))


def load_px():
    px = pd.read_csv(US30_CSV, index_col=0, parse_dates=True).sort_index()
    return px


def load_fx_series():
    df = pd.read_csv(FX_CSV, index_col=0, parse_dates=True, na_values=["."]).dropna()
    fx = df.iloc[:, 0].astype(float)
    fx = fx[~fx.index.duplicated(keep="last")].sort_index()
    return fx


def target_w():
    """个股级目标权重: 层权重/层内等权."""
    w = {}
    for layer, syms in GROUPS.items():
        for s in syms:
            w[s] = LAYER_W[layer] / len(syms)
    return w


def sim_dca(px, w0, fx_w, initial_usd, monthly_usd, start_cny_note=""):
    """单组合现金流DCA: 周收益按当前权重(月初重置+月内漂移), 未上市权重摊给已上市.
    返回 acct_usd(Series), contrib_cny(Series, 人民币口径)."""
    n = len(px)
    idx = px.index
    syms = list(w0.keys())
    P = px[syms].values.astype(float)
    # 周收益: 前周有价才计 (上市首周为 NaN 按 0)
    R = np.zeros_like(P)
    R[1:] = np.where(np.isnan(P[:-1]) | np.isnan(P[1:]), 0.0, P[1:] / P[:-1] - 1.0)
    avail = ~np.isnan(P)

    w = np.array([w0[s] for s in syms], float)
    acct = np.zeros(n)
    contrib = np.zeros(n)
    # t=0: 初始本金建仓
    w0a = w * avail[0]
    w0a = w0a / w0a.sum()
    bal = initial_usd
    acct[0] = initial_usd
    contrib[0] = INITIAL_CNY
    cur = w0a.copy()
    for t in range(1, n):
        rp = float(cur @ R[t])
        bal *= (1 + rp)
        is_month = idx[t].month != idx[t - 1].month
        if is_month:
            bal += float(monthly_usd[t])
            contrib[t] = contrib[t - 1] + MONTHLY_CNY
            # 重置目标权重(按当前可用集归一)
            wa = w * avail[t]
            cur = wa / wa.sum()
        else:
            contrib[t] = contrib[t - 1]
            # 月内权重漂移
            num = cur * (1 + R[t])
            den = num.sum()
            cur = num / den if den > 0 else cur
        acct[t] = bal
    return pd.Series(acct, index=idx), pd.Series(contrib, index=idx)


def run_window(px, fx, start_date, tag):
    """跑一个窗口: 返回 (acct_usd, contrib_cny, fx_end, summary dict)."""
    pxw = px[px.index >= pd.Timestamp(start_date)]
    fx_w = fx.reindex(pxw.index, method="ffill")
    fx_end = float(fx_w.iloc[-1])
    init_usd = INITIAL_CNY / float(fx_w.iloc[0])
    monthly_usd = (MONTHLY_CNY / fx_w).values

    w0 = target_w()
    acct, contrib = sim_dca(pxw, w0, fx_w, init_usd, monthly_usd)

    # SPY 单标的对照 (只买标普500)
    w_spy = {t: (1.0 if t == "SPY" else 0.0) for t in US30_ALL}
    acct_spy, _ = sim_dca(pxw, w_spy, fx_w, init_usd, monthly_usd)

    final_usd = float(acct.iloc[-1])
    final_cny = final_usd * fx_end
    tot_cny = float(contrib.iloc[-1])
    n_dep = int((tot_cny - INITIAL_CNY) / MONTHLY_CNY)
    mult = final_cny / tot_cny

    # 人民币口径 IRR
    idx = acct.index
    dep_dates = [idx[0].to_pydatetime().date()]
    dep_amts = [INITIAL_CNY]
    for t in range(1, len(idx)):
        if idx[t].month != idx[t - 1].month:
            dep_dates.append(idx[t].to_pydatetime().date())
            dep_amts.append(MONTHLY_CNY)
    irr = tld.irr_monthly(dep_dates, dep_amts, idx[-1].to_pydatetime().date(), final_cny)

    acct_cny = acct * fx_end
    mdd = float((acct_cny / acct_cny.cummax() - 1).min())

    sumy = {"tag": tag, "window": [str(pxw.index[0].date()), str(pxw.index[-1].date())],
            "final_usd": final_usd, "final_cny": final_cny,
            "spy_only_final_cny": float(acct_spy.iloc[-1]) * fx_end,
            "total_contrib_cny": tot_cny, "n_deposits": n_dep,
            "multiple": mult, "irr_annual": irr, "mdd": mdd}
    print(f"\n=== {tag} ({pxw.index[0].date()} ~ {pxw.index[-1].date()}, "
          f"{(pxw.index[-1]-pxw.index[0]).days/365.25:.1f}y) ===")
    print(f"  初始¥{INITIAL_CNY:,.0f} + 月投¥{MONTHLY_CNY:,.0f}x{n_dep} 合计¥{tot_cny:,.0f}")
    print(f"  三层组合  期末 ¥{final_cny:,.0f}  (${final_usd:,.0f})   增值 {mult:6.1f}x  IRR {irr*100:5.1f}%  MDD {mdd*100:5.1f}%")
    print(f"  纯SPY对照 期末 ¥{sumy['spy_only_final_cny']:,.0f}")
    return acct_cny, contrib, sumy


def year_track(acct_cny, contrib_cny):
    y_end = acct_cny.resample("YE").last()
    y_contrib = contrib_cny.resample("YE").last()
    print("\n=== 年末账户轨迹 (人民币) ===")
    print(f"  {'年份':<6}{'年末账户':>16}{'累计充值':>13}")
    for yr in y_end.index:
        print(f"  {yr.year:<6}¥{y_end.get(yr, np.nan):>13,.0f}¥{y_contrib.get(yr, np.nan):>11,.0f}")


def _chart(acct30, acct17, contrib30):
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
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11.5, 8.4), sharex=True,
                                 gridspec_kw={"height_ratios": [2.4, 1], "hspace": 0.08})
    a1.plot(acct30.index, acct30.values, color="#1565c0", lw=2.0,
            label=f"美股30年 三层组合  期末 ¥{acct30.iloc[-1]/1e4:.0f}万")
    a1.plot(acct17.index, acct17.values, color="#2e7d32", lw=1.8,
            label=f"美股 2017起(加密同窗)  期末 ¥{acct17.iloc[-1]/1e4:.0f}万")
    a1.plot(contrib30.index, contrib30.values, color="#999", lw=1.2, ls=":",
            label=f"累计充值(30y)  ¥{contrib30.iloc[-1]:,.0f}")
    a1.set_title(f"美股纯权益 30年DCA (指数60/行业20/龙头20, 月平衡) — "
                 f"初始¥{INITIAL_CNY:,.0f}+月投¥{MONTHLY_CNY:,.0f}",
                 fontsize=12.5, fontweight="bold")
    a1.grid(True, alpha=0.35)
    a1.legend(loc="upper left", fontsize=9, framealpha=0.9)
    a1.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"¥{y/1e6:,.1f}M"))

    def dd(s):
        return s / s.cummax() - 1.0
    a2.fill_between(acct30.index, dd(acct30).values * 100, 0, color="#1565c0", alpha=0.15)
    a2.plot(acct30.index, dd(acct30).values * 100, color="#1565c0", lw=0.9)
    a2.set_ylabel("Drawdown %", fontsize=10)
    a2.set_ylim(-60, 2)
    a2.grid(True, alpha=0.35)
    a2.set_xlabel("Weekly close", fontsize=10)
    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=130)
    print(f"\n输出对比图: {OUT_PNG}")


def main():
    px = load_px()
    fx = load_fx_series()
    print(f"美股面板: {px.shape}, {px.index[0].date()} ~ {px.index[-1].date()}")
    print(f"组合: {json.dumps(GROUPS, ensure_ascii=False)} 层权重={LAYER_W}")
    print("=" * 100)

    acct30, contrib30, s30 = run_window(px, fx, "1996-01-01", "美股 30 年全窗口")
    year_track(acct30, contrib30)
    acct17, contrib17, s17 = run_window(px, fx, "2017-01-01", "美股 2017 起(加密同窗口)")

    # 加密对照
    try:
        c = json_load(os.path.join(HERE, "tri_leg_dca_cny_i10000_m2000_results.json"))
        print("\n=== 对照: 加密 tri_leg 30/30/40 (同现金流, 2017-2026) ===")
        print(f"  期末 ¥{c['main_capW']['final_cny']:,.0f}  增值 {c['main_capW']['multiple_cny']:.1f}x  "
              f"IRR {c['main_capW']['irr_annual_cny']*100:.1f}%  MDD {c['main_capW']['mdd_cny']*100:.1f}%")
    except Exception as e:
        print("加密对照读取失败:", e)

    res = {"structure": {"groups": GROUPS, "layer_w": LAYER_W,
                         "cash": {"initial_cny": INITIAL_CNY, "monthly_cny": MONTHLY_CNY}},
           "us30_full": s30, "us2017": s17,
           "crypto_ref": c if 'c' in dir() else None}
    json.dump(res, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n结果JSON: {OUT_JSON}")

    if "--chart" in sys.argv:
        _chart(acct30, acct17, contrib30)


if __name__ == "__main__":
    main()
