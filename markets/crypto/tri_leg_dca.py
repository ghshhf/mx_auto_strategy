"""
tri_leg_dca.py — 现金流(DCA)回测: 初始$1000 + 每月工资$100加仓, 30/30/40三腿月度再平衡
========================================================================================================
结构 (2026-09-07 用户最终定型):
  - 防御 60%: 30% 美股指数(SPY/QQQ/DIA 等权) + 30% BTC/ETH(市值加权~84/16)
  - 进攻 40%: 加密小币【市值加权】—— 用户选币按龙头/市值, 非等权 (2026-09-07 校正)
  - 层内 + 层间全部【月度】再平衡; 加仓日 = 调仓日 = 每月初首周
  - 现金流: t0=$1,000, 此后每月 +$100 (模拟月薪定投), 问"跑到现在值多少钱"
  - 2017-11-03 前无进攻标的, 资金默认全在防御端(BTC/ETH+美股各半), 之后切 30/30/40

输出: 期末账户金额 / 累计投入 / 增值倍数 / 月度IRR(年化) + 等权小币对照
用法: python tri_leg_dca.py [--chart]
"""
import os
import sys
import json
import datetime

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cap_index_monthly as cim
import crypto_adoption_v2 as ca2
import tri_leg_monthly as tlm

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
SNAP = os.path.join(HERE, "mcap_snapshot.json")

_REPORTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "reports_archive")
if not os.path.isdir(_REPORTS):
    _REPORTS = os.path.join(HERE, "out")
OUT_PNG = os.path.join(_REPORTS, f"tri_leg_dca_{datetime.date.today():%Y-%m-%d}.png")
OUT_JSON = os.path.join(HERE, "tri_leg_dca_results.json")

INITIAL = 1000.0      # 初始本金 USD
MONTHLY = 100.0       # 每月加仓 USD
US_SYMS = tlm.US_THREE          # SPY/QQQ/DIA
W = np.array([0.30, 0.30, 0.40])  # 美股 / BTC+ETH / 小币市值加权
WB = np.array([0.50, 0.50, 0.00])  # 无进攻标的时: 防御两腿归一


def json_load(p):
    return json.load(open(p, encoding="utf-8"))


def offense_cap_nav(px, mc, first_off):
    """进攻腿 = 非BTC/ETH币【市值加权】月度再平衡 (从首只上市周起)."""
    syms = [c for c in ca2.ALL_COINS if c not in ("BTC", "ETH") and c in px.columns]
    sub = px[syms].astype(float)
    sub = sub[sub.index >= first_off]
    return cim.cap_monthly_nav(sub, mc, syms)


def dca_sim(navs, target_before, target_after, first_off, initial, monthly):
    """现金流模拟: 逐周应用腿收益, 月初(month change)重置目标权重并投入 monthly.
    monthly 可为标量(等额定投)或与周轴等长的数组(每期不等额, 如按汇率折算的人民币定投).
    返回 (账户余额Series, 累计投入Series, 各腿期末余额)."""
    base = navs[0].index
    M = []
    for s in navs:
        v = s.reindex(base).ffill().fillna(1.0)
        M.append(v.values)
    M = np.column_stack(M)
    rets = np.zeros_like(M)
    rets[1:] = M[1:] / M[:-1] - 1.0
    n = len(base)
    wb = target_before / target_before.sum()
    wa = target_after / target_after.sum()
    bal = np.zeros(len(navs))
    contrib = np.zeros(n)
    acct = np.zeros(n)
    # t=0: 初始本金按防御归一建仓
    bal[:] = initial * wb
    contrib[0] = initial
    acct[0] = initial
    active = False
    for t in range(1, n):
        bal *= (1 + rets[t])
        if base[t] >= first_off and not active:
            active = True
        # 月初: 加仓(工资) + 再平衡回目标权重
        is_month = base[t].month != base[t - 1].month
        amt = monthly if np.isscalar(monthly) else float(monthly[t])
        if is_month:
            bal += amt * (wa if active else wb)
            contrib[t] = contrib[t - 1] + amt
        else:
            contrib[t] = contrib[t - 1]
        w_target = wa if active else wb
        total = bal.sum()
        bal = total * w_target if is_month else bal
        acct[t] = bal.sum()
    ser_acct = pd.Series(acct, index=base, name="acct")
    ser_contrib = pd.Series(contrib, index=base, name="contrib")
    return ser_acct, ser_contrib, bal


def irr_monthly(dep_dates, dep_amounts, end_date, final_value):
    """月度定投年化: 求月收益率 m 使 各笔投入复利到期末之和 = final_value.
    f(m)=Σ dep_i*(1+m)^(days_to_end/30.4375) - final, 单调增, 二分求解."""
    days = np.array([(end_date - d).days / 30.4375 for d in dep_dates], float)
    cfs = np.array(dep_amounts, float)

    def f(m):
        return float(np.sum(cfs * (1 + m) ** days) - final_value)

    lo, hi = -0.999, 2.0
    if f(lo) * f(hi) > 0:      # 超出范围(几乎不可能), 抬上限
        hi = 10.0
    for _ in range(300):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    m = (lo + hi) / 2
    return (1 + m) ** 12 - 1


def fmt_row(lbl, acct, contrib):
    final = float(acct.iloc[-1])
    tot = float(contrib.iloc[-1])
    mult = final / tot
    print(f"  {lbl:<42} 期末 ${final:>12,.0f}  投入 ${tot:>8,.0f}  增值 {mult:7.1f}x")


def main():
    px, us, first_off = tlm.load_aligned()
    mc = {d["sym"]: (d.get("mcap") or 0) for d in json_load(SNAP)}
    start, end = px.index[0], px.index[-1]
    months = (end.year - start.year) * 12 + (end.month - start.month)
    n_dep = months  # 首个整月起每月一次(初始月为 initial)
    print(f"窗口: {start.date()} -> {end.date()}, 首只小币 {first_off.date()} 上市")
    print(f"现金流: 初始 ${INITIAL:.0f} + 每月 ${MONTHLY:.0f} x {n_dep} 次 "
          f"(合计投入 ${INITIAL + n_dep * MONTHLY:,.0f})")
    print("=" * 100)

    us3 = tlm.us_nav(us, US_SYMS)
    big = tlm.big_nav(px, mc, "cap")
    off_cap = offense_cap_nav(px, mc, first_off)     # 小币市值加权(用户要的)
    off_eq = tlm.off_nav(px, first_off)              # 小币等权(旧, 对照)

    acct_cap, contrib_cap, _ = dca_sim([us3, big, off_cap], WB, W, first_off,
                                       INITIAL, MONTHLY)
    acct_eq, contrib_eq, _ = dca_sim([us3, big, off_eq], WB, W, first_off,
                                     INITIAL, MONTHLY)

    print("\n--- 期末账户 (初始$1000 + 月投$100) ---")
    fmt_row("主案: 小币【市值加权】+ 美股三指数", acct_cap, contrib_cap)
    fmt_row("对照: 小币等权 + 美股三指数", acct_eq, contrib_eq)

    # 关键指标(主案)
    final = float(acct_cap.iloc[-1])
    tot = float(contrib_cap.iloc[-1])
    # 单看初始$1000 与 月投部分分别增值
    # 简化: 总账户 / 总投入 为整体倍数
    mult = final / tot
    # IRR
    dates = []
    cfs = []
    idx = contrib_cap.index
    prev = -1
    for t in range(len(idx)):
        c = float(contrib_cap.iloc[t])
        if c > prev:
            dates.append(idx[t].to_pydatetime().date())
            cfs.append(INITIAL if t == 0 else MONTHLY)
            prev = c
    irr = irr_monthly(dates, cfs, idx[-1].to_pydatetime().date(), final)

    mdd_acct = float((acct_cap / acct_cap.cummax() - 1).min())
    # 从投入达到>0后算(其实t0就有投入)
    yrs = (end - start).days / 365.25
    cagr_eq = (final / INITIAL) ** (1 / yrs) - 1  # 仅初始本金视角(粗)
    print("\n--- 主案细节 ---")
    print(f"  期末账户余额: ${final:,.0f}")
    print(f"  累计投入: ${tot:,.0f} (初始${INITIAL:.0f} + 月投${MONTHLY:.0f}x{n_dep})")
    print(f"  整体增值: {mult:.1f}x")
    print(f"  月度定投年化 IRR: {irr*100:.1f}%")
    print(f"  账户最大回撤(按资金曲线): {mdd_acct*100:.1f}%")

    # 逐年: 年末账户 & 当年投入
    y_end = acct_cap.resample("YE").last()
    y_contrib = contrib_cap.resample("YE").last()
    print("\n=== 年末账户轨迹 ===")
    print(f"  {'年份':<6}{'年末账户':>14}{'累计投入':>12}")
    for yr in y_end.index:
        if yr.year < 2017:
            continue
        print(f"  {yr.year:<6}${y_end.get(yr, np.nan):>11,.0f}${y_contrib.get(yr, np.nan):>10,.0f}")

    # 存 JSON
    res = {
        "window": [str(start.date()), str(end.date())],
        "first_off": str(first_off.date()),
        "initial_usd": INITIAL, "monthly_usd": MONTHLY,
        "n_deposits": n_dep, "total_contrib": tot,
        "structure": "30%US_idx(SPY/QQQ/DIA) + 30%BTC/ETH(cap) + 40%smallcap(capW)",
        "main_capW": {"final_usd": final, "total_contrib": tot, "multiple": mult,
                      "irr_annual": irr, "acct_mdd": mdd_acct},
        "equalW_offense_final_usd": float(acct_eq.iloc[-1]),
        "equalW_offense_total_contrib": float(contrib_eq.iloc[-1]),
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"\n结果JSON: {OUT_JSON}")

    if "--chart" in sys.argv:
        _chart(acct_cap, contrib_cap, acct_eq)


def _chart(acct, contrib, acct_eq):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    plt.rcParams.update({"axes.facecolor": "#fff", "figure.facecolor": "#fff",
                         "savefig.facecolor": "#fff", "axes.edgecolor": "#888",
                         "axes.labelcolor": "#222", "text.color": "#222",
                         "xtick.color": "#444", "ytick.color": "#444", "grid.color": "#e2e2e2"})
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 8.2), sharex=True,
                                 gridspec_kw={"height_ratios": [2.4, 1], "hspace": 0.08})
    a1.plot(acct.index, acct.values, color="#2e7d32", lw=2.0,
            label=f"小币市值加权 DCA  期末 ${acct.iloc[-1]:,.0f}")
    a1.plot(acct_eq.index, acct_eq.values, color="#7b1fa2", lw=1.2, ls="--",
            label=f"小币等权对照 DCA  期末 ${acct_eq.iloc[-1]:,.0f}")
    a1.plot(contrib.index, contrib.values, color="#999", lw=1.2, ls=":",
            label=f"累计投入  ${contrib.iloc[-1]:,.0f}")
    a1.set_title(f"Tri-Leg 30/30/40 DCA - Account Value "
                 f"(${acct.index[0]:%Y-%m} initial ${INITIAL:.0f}+${MONTHLY:.0f}/m)",
                 fontsize=12.5, fontweight="bold")
    a1.grid(True, alpha=0.35)
    a1.legend(loc="upper left", fontsize=9, framealpha=0.9)
    a1.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"${y:,.0f}"))

    def dd(s):
        return s / s.cummax() - 1.0

    a2.fill_between(acct.index, dd(acct).values * 100, 0, color="#2e7d32", alpha=0.15)
    a2.plot(acct.index, dd(acct).values * 100, color="#2e7d32", lw=0.9)
    a2.set_ylabel("Drawdown %", fontsize=10)
    a2.set_ylim(-70, 2)
    a2.grid(True, alpha=0.35)
    a2.set_xlabel("Weekly close", fontsize=10)
    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=130)
    print(f"输出对比图: {OUT_PNG}")


if __name__ == "__main__":
    main()
