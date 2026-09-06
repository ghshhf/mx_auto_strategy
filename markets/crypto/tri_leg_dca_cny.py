"""
tri_leg_dca_cny.py — 人民币现金流(DCA)回测: 初始¥7000 + 每月充值¥2000, 30/30/40三腿月度再平衡
========================================================================================================
与 tri_leg_dca.py 的唯一差别在现金流口径(2026-09-07 用户校准):
  - 用户真实操作 = 人民币充值交易所再买入, 不是"每月$100"
  - 每月充值 ¥2,000 (≈ $285~290), 初始 ¥7,000 (≈ 2017-01 的 $1,000 按当时汇率)
  - 充值日按当月 USDCNY 实际汇率折成 USD 建仓 (FRED DEXCHUS, 日频月末取用, 周轴 ffill)
  - 资产全程以 USD 计(币价/股价均为美元), 期末账户同时报 USD 与 按期末汇率折算的 CNY
结构 (沿用 tri_leg_dca.py):
  - 防御 60%: 30% 美股指数(SPY/QQQ/DIA 等权) + 30% BTC/ETH(市值加权)
  - 进攻 40%: 加密小币【市值加权】(用户选币按龙头/市值)
  - 层内+层间全部月度再平衡; 加仓日=调仓日=每月初首周
  - 2017-11-03 前无进攻标的, 资金默认全在防御端, 之后切 30/30/40

输出: 期末 USD/CNY / 累计投入CNY / 增值倍数 / 人民币口径IRR(年化) + 对照(¥版等权小币、$100版市值加权)
用法: python tri_leg_dca_cny.py [--chart] [--initial CNY] [--monthly CNY]
      例: python tri_leg_dca_cny.py --chart --initial 10000   (初始¥1万 + 每月¥2000)
"""
import os
import sys
import json
import datetime

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tri_leg_monthly as tlm
import tri_leg_dca as tld

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
SNAP = os.path.join(HERE, "mcap_snapshot.json")
FX_CSV = os.path.join(HERE, "data", "DEXCHUS.csv")     # FRED: China / US FX, 日频

_REPORTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "reports_archive")
if not os.path.isdir(_REPORTS):
    _REPORTS = os.path.join(HERE, "out")
OUT_PNG = os.path.join(_REPORTS, f"tri_leg_dca_cny_{datetime.date.today():%Y-%m-%d}.png")
OUT_JSON = os.path.join(HERE, "tri_leg_dca_cny_results.json")

INITIAL_CNY = 7000.0     # 初始本金 CNY (≈ 2017-01 的 $1,000)
MONTHLY_CNY = 2000.0     # 每月充值 CNY (用户真实口径)
US_SYMS = tlm.US_THREE   # SPY/QQQ/DIA
W = np.array([0.30, 0.30, 0.40])
WB = np.array([0.50, 0.50, 0.00])


def json_load(p):
    return json.load(open(p, encoding="utf-8"))


def load_fx():
    """FRED DEXCHUS 日频 -> 月频(月末值) Series[CNY per USD]. 缺失('.' )剔除."""
    df = pd.read_csv(FX_CSV, index_col=0, parse_dates=True, na_values=["."]).dropna()
    df = df[df.index >= "2016-12-01"]
    fx = df.iloc[:, 0].astype(float)
    fx = fx[~fx.index.duplicated(keep="last")].sort_index()
    return fx


def offense_cap_nav(px, mc, first_off):
    import cap_index_monthly as cim
    import crypto_adoption_v2 as ca2
    syms = [c for c in ca2.ALL_COINS if c not in ("BTC", "ETH") and c in px.columns]
    sub = px[syms].astype(float)
    sub = sub[sub.index >= first_off]
    return cim.cap_monthly_nav(sub, mc, syms)


def fmt_row(lbl, acct_cny, contrib_cny, acct_usd=None, mul_unit="x"):
    final_cny = float(acct_cny.iloc[-1])
    tot_cny = float(contrib_cny.iloc[-1])
    mult = final_cny / tot_cny
    extra = ""
    if acct_usd is not None:
        extra = f"  美元等值 ${float(acct_usd.iloc[-1]):>12,.0f}"
    print(f"  {lbl:<38} 期末 ¥{final_cny:>13,.0f}{extra}  投入 ¥{tot_cny:>10,.0f}  增值 {mult:6.1f}{mul_unit}")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="人民币现金流 DCA 回测 (30/30/40 月度再平衡)")
    ap.add_argument("--chart", action="store_true", help="输出资金曲线图")
    ap.add_argument("--initial", type=float, default=INITIAL_CNY, help="初始本金 CNY")
    ap.add_argument("--monthly", type=float, default=MONTHLY_CNY, help="每月充值 CNY")
    args = ap.parse_args()
    initial, monthly = args.initial, args.monthly

    # 输出文件: 默认参数沿用旧名, 自定义参数带标记
    if abs(initial - INITIAL_CNY) < 1e-9 and abs(monthly - MONTHLY_CNY) < 1e-9:
        out_json = os.path.join(HERE, "tri_leg_dca_cny_results.json")
        out_png = os.path.join(_REPORTS, f"tri_leg_dca_cny_{datetime.date.today():%Y-%m-%d}.png")
    else:
        tag = f"i{initial:.0f}_m{monthly:.0f}"
        out_json = os.path.join(HERE, f"tri_leg_dca_cny_{tag}_results.json")
        out_png = os.path.join(_REPORTS, f"tri_leg_dca_cny_{tag}_{datetime.date.today():%Y-%m-%d}.png")

    px, us, first_off = tlm.load_aligned()
    mc = {d["sym"]: (d.get("mcap") or 0) for d in json_load(SNAP)}
    start, end = px.index[0], px.index[-1]
    n_dep = (end.year - start.year) * 12 + (end.month - start.month)   # 月投次数(不含初始)
    fx = load_fx()
    fx_w = fx.reindex(px.index, method="ffill")       # 每根周K对应可用汇率
    fx_end = float(fx_w.iloc[-1])
    print(f"窗口: {start.date()} -> {end.date()}, 首只小币 {first_off.date()} 上市")
    print(f"现金流: 初始 ¥{initial:,.0f} + 每月 ¥{monthly:,.0f} x {n_dep} 次 "
          f"(合计 ¥{initial + n_dep * monthly:,.0f})")
    print(f"汇率: FRED DEXCHUS, 期末(最近) {fx_end:.4f} CNY/USD")
    print("=" * 108)

    us3 = tlm.us_nav(us, US_SYMS)
    big = tlm.big_nav(px, mc, "cap")
    off_cap = offense_cap_nav(px, mc, first_off)          # 小币市值加权
    off_eq = tlm.off_nav(px, first_off)                   # 小币等权(对照)

    # 每期充值额(USD) = ¥monthly / 当期汇率; 初始 = ¥initial / 首期汇率
    monthly_usd = (monthly / fx_w).values                 # 与周轴等长
    init_usd = initial / float(fx_w.iloc[0])

    acct_cny_cap, contrib_cny_cap, _ = tld.dca_sim([us3, big, off_cap], WB, W, first_off,
                                                   init_usd, monthly_usd)
    acct_cny_eq, contrib_cny_eq, _ = tld.dca_sim([us3, big, off_eq], WB, W, first_off,
                                                 init_usd, monthly_usd)
    # 对照: 美元版 $1000+$100 (原 tri_leg_dca 口径, 市值加权小币)
    acct_usd_ref, contrib_usd_ref, _ = tld.dca_sim([us3, big, off_cap], WB, W, first_off,
                                                   1000.0, 100.0)

    # 人民币计价账户曲线 = USD资产余额 x 期末汇率 (回答"现在值多少人民币")
    acct_cny_cap = acct_cny_cap * fx_end
    acct_cny_eq = acct_cny_eq * fx_end
    # 累计充值(人民币): t0 ¥initial, 此后每月 ¥monthly (固定, 与汇率无关)
    cidx = contrib_usd_ref.index
    contrib_cny = pd.Series(initial, index=cidx, dtype=float)
    month_pos = [t for t in range(1, len(cidx)) if cidx[t].month != cidx[t - 1].month]
    for k, t in enumerate(month_pos, start=1):
        contrib_cny.iloc[t:] = initial + k * monthly

    print(f"\n--- 期末账户 (初始¥{initial:,.0f} + 每月充值¥{monthly:,.0f}) ---")
    fmt_row("主案: 小币市值加权 (¥口径)", acct_cny_cap, contrib_cny)
    fmt_row("对照: 小币等权 (¥口径)", acct_cny_eq, contrib_cny)
    ref_final_usd = float(acct_usd_ref.iloc[-1])
    ref_tot_usd = float(contrib_usd_ref.iloc[-1])
    print(f"  参照: 美元版($1000+$100/月) 期末 ${ref_final_usd:,.0f} "
          f"(折¥{ref_final_usd*fx_end:,.0f}, 累计投入${ref_tot_usd:,.0f})")

    final_cny = float(acct_cny_cap.iloc[-1])
    final_usd = final_cny / fx_end
    tot_cny = initial + n_dep * monthly
    mult = final_cny / tot_cny

    # 人民币口径 IRR: 每笔投入 -CNY 复利到期末 = 期末CNY余额
    dep_dates = [cidx[0].to_pydatetime().date()]
    dep_amts = [initial]
    for t in range(1, len(cidx)):
        if cidx[t].month != cidx[t - 1].month:
            dep_dates.append(cidx[t].to_pydatetime().date())
            dep_amts.append(monthly)
    end_date = cidx[-1].to_pydatetime().date()
    irr = tld.irr_monthly(dep_dates, dep_amts, end_date, final_cny)

    mdd_cny = float((acct_cny_cap / acct_cny_cap.cummax() - 1).min())
    mdd_usd = float((acct_cny_cap / fx_end / (acct_cny_cap / fx_end).cummax() - 1).min())

    print("\n--- 主案细节 (人民币口径) ---")
    print(f"  期末账户: ¥{final_cny:,.0f}  ≈  ${final_usd:,.0f}")
    print(f"  累计充值: ¥{tot_cny:,.0f} (初始¥{initial:,.0f} + 月充¥{monthly:,.0f}x{n_dep})")
    print(f"  整体增值: {mult:.1f}x")
    print(f"  定投年化 IRR: {irr*100:.1f}%")
    print(f"  账户最大回撤(¥资金曲线): {mdd_cny*100:.1f}%")

    # 逐年: 年末账户(¥) & 当年累计充值(¥)
    y_end = acct_cny_cap.resample("YE").last()
    y_contrib = contrib_cny.resample("YE").last()
    print("\n=== 年末账户轨迹 (人民币) ===")
    print(f"  {'年份':<6}{'年末账户':>16}{'累计充值':>13}")
    for yr in y_end.index:
        if yr.year < 2017:
            continue
        print(f"  {yr.year:<6}¥{y_end.get(yr, np.nan):>13,.0f}¥{y_contrib.get(yr, np.nan):>11,.0f}")

    res = {
        "window": [str(start.date()), str(end.date())],
        "first_off": str(first_off.date()),
        "fx_note": f"FRED DEXCHUS 月末/周ffill, 期末 {fx_end:.4f} CNY/USD",
        "initial_cny": initial, "monthly_cny": monthly,
        "n_deposits": n_dep, "total_contrib_cny": tot_cny,
        "structure": "30%US_idx(SPY/QQQ/DIA) + 30%BTC/ETH(cap) + 40%smallcap(capW) monthly",
        "main_capW": {"final_cny": final_cny, "final_usd": final_usd,
                      "multiple_cny": mult, "irr_annual_cny": irr, "mdd_cny": mdd_cny},
        "equalW_offense_final_cny": float(acct_cny_eq.iloc[-1]),
        "usd100_ref_final_cny": float(acct_usd_ref.iloc[-1]) * fx_end,
        "year_end_cny": {int(yr.year): round(float(v), 2) for yr, v in y_end.items() if yr.year >= 2017},
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"\n结果JSON: {out_json}")

    if args.chart:
        _chart(acct_cny_cap, contrib_cny, acct_cny_eq, out_png,
               f"Tri-Leg 30/30/40 DCA - 人民币现金流账户 "
               f"(初始¥{initial:,.0f} + 每月充值¥{monthly:,.0f}, 按当月USDCNY折美元买入)")


def _chart(acct_cny, contrib_cny, acct_cny_eq, out_png, title):
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
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 8.2), sharex=True,
                                 gridspec_kw={"height_ratios": [2.4, 1], "hspace": 0.08})
    a1.plot(acct_cny.index, acct_cny.values, color="#2e7d32", lw=2.0,
            label=f"小币市值加权 DCA  期末 ¥{acct_cny.iloc[-1]:,.0f}")
    a1.plot(acct_cny_eq.index, acct_cny_eq.values, color="#7b1fa2", lw=1.2, ls="--",
            label=f"小币等权对照 DCA  期末 ¥{acct_cny_eq.iloc[-1]:,.0f}")
    a1.plot(contrib_cny.index, contrib_cny.values, color="#999", lw=1.2, ls=":",
            label=f"累计充值  ¥{contrib_cny.iloc[-1]:,.0f}")
    a1.set_title(title, fontsize=12.5, fontweight="bold")
    a1.grid(True, alpha=0.35)
    a1.legend(loc="upper left", fontsize=9, framealpha=0.9)
    a1.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"¥{y/1e6:,.1f}M"))

    def dd(s):
        return s / s.cummax() - 1.0

    a2.fill_between(acct_cny.index, dd(acct_cny).values * 100, 0, color="#2e7d32", alpha=0.15)
    a2.plot(acct_cny.index, dd(acct_cny).values * 100, color="#2e7d32", lw=0.9)
    a2.set_ylabel("Drawdown %", fontsize=10)
    a2.set_ylim(-70, 2)
    a2.grid(True, alpha=0.35)
    a2.set_xlabel("Weekly close", fontsize=10)
    plt.tight_layout()
    plt.savefig(out_png, dpi=130)
    print(f"输出对比图: {out_png}")


if __name__ == "__main__":
    main()
