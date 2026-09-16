# -*- coding: utf-8 -*-
"""markets/dca/dca_long.py —— 40 年「一生定投」推演

三个必须先解决的口径问题
------------------------
1. **价格指数 vs 全收益**：^GSPC/^NDX/^HSI 的 adjclose == close，不含分红。
   实测 1988-2026 重叠期，^SP500TR/^GSPC 的比价从 1.0 降到 0.4462，
   ⇒ 股息再投的累积贡献 = 1/0.4462 = **2.24 倍**（年化 +2.11%）。
   不做这步修正，40 年推演会**低估一倍以上**。
   本脚本用实测因子外推构造全收益序列，历史股息率其实更高 ⇒ 结果偏保守。
2. **通胀**：40 年后 40 元 ≠ 今天 40 元。按 2.5%/年，购买力只剩 37%。
3. **生活成本 / 收入成长**：固定 40 元/日 = 实际投入逐年缩水；按通胀加码是另一种活法。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dca_backtest import load, load_macro, dca, xirr, metrics  # noqa: E402

OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
RNG = np.random.default_rng(20260917)


# ------------------------------------------------------ 全收益序列构造
def div_factor(price_sym: str, tr_sym: str) -> float:
    """从「价格指数 + 含分红品种」的重叠期实测股息累积年化。"""
    dp, pp = load(price_sym)
    dtr, ptr = load(tr_sym)
    mp = {d.toordinal(): v for d, v in zip(dp, pp)}
    mt = {d.toordinal(): v for d, v in zip(dtr, ptr)}
    common = sorted(set(mp) & set(mt))
    i0, i1 = common[0], common[-1]
    yrs = (dt.date.fromordinal(i1) - dt.date.fromordinal(i0)).days / 365.25
    ratio = (mt[i1] / mt[i0]) / (mp[i1] / mp[i0])   # 全收益 / 价格
    return ratio ** (1 / yrs) - 1


def make_tr(sym: str, div_annual: float) -> tuple[list, np.ndarray]:
    d, p = load(sym)
    base = d[0]
    yrs = np.array([(x - base).days / 365.25 for x in d])
    return d, p * np.power(1.0 + div_annual, yrs)


DIV_US: float | None = None
DIV_HK: float | None = None


def init_div() -> None:
    global DIV_US, DIV_HK
    DIV_US = div_factor("IDX_GSPC", "IDX_SP500TR")
    DIV_HK = div_factor("IDX_HSI", "2800.HK")
    print(f"实测股息累积年化:  美股 {DIV_US:.2%}   港股 {DIV_HK:.2%}")


# ------------------------------------------------------ 滚动窗口
def _ord(dates):
    return np.array([d.toordinal() for d in dates])


def windows(dates, years: int, step_years: int = 1):
    o = _ord(dates)
    out = []
    n = len(dates)
    last_year = None
    for i0 in range(n):
        if last_year is not None and dates[i0].year - last_year < step_years:
            continue
        tgt = dates[i0].replace(year=dates[i0].year + years).toordinal()
        j = int(np.searchsorted(o, tgt, side="left"))
        if j >= n:
            break
        out.append((i0, j))
        last_year = dates[i0].year
    return out


def stats(a) -> dict:
    a = np.asarray(a, dtype=float)
    a = a[~np.isnan(a)]
    return dict(median=float(np.median(a)), p5=float(np.percentile(a, 5)),
                p25=float(np.percentile(a, 25)),
                p75=float(np.percentile(a, 75)),
                p95=float(np.percentile(a, 95)),
                min=float(a.min()), max=float(a.max()))


def cpi_at(cd, cv, d: dt.date, extend: float = 0.025) -> float:
    """取 d 时点的 CPI。超出样本末端则按 extend 外推（40 年推演必须外推）。"""
    o = _ord(cd)
    j = int(np.searchsorted(o, d.toordinal(), side="right")) - 1
    j = max(j, 0)
    if d <= cd[-1]:
        return float(cv[j])
    extra_yrs = (d - cd[-1]).days / 365.25
    return float(cv[-1]) * (1.0 + extend) ** extra_yrs


def run_window(px, dates, amount, cd, cv, today=dt.date(2026, 9, 16)) -> dict:
    eq, invested, inv = dca(px, amount)
    under = eq < inv
    longest = cur = 0
    for u in under:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    cfs = [(d, -amount) for d in dates] + [(dates[-1], float(eq[-1]))]
    yrs = (dates[-1] - dates[0]).days / 365.25
    # 折成「今天」购买力：终值按期末 CPI 折，投入按各自投入时点折
    c_today = cpi_at(cd, cv, today)
    real_final = float(eq[-1]) * c_today / cpi_at(cd, cv, dates[-1])
    real_invested = float(sum(amount * c_today / cpi_at(cd, cv, x) for x in dates))
    return dict(
        start=dates[0].isoformat(), end=dates[-1].isoformat(),
        start_year=dates[0].year, years=round(yrs, 2), days=len(dates),
        invested=float(invested), final=float(eq[-1]),
        multiple=float(eq[-1] / invested), xirr=xirr(cfs),
        max_dd=float((eq / inv).min() - 1),
        worst_date=dates[int(np.argmin(eq / inv))].isoformat(),
        under_pct=float(under.mean()), longest_under_days=int(longest),
        real_final_today=real_final,
        real_invested_today=real_invested,
        real_multiple=real_final / real_invested,
    )


# ================================================================== 主流程
def main() -> int:
    init_div()
    cd, cv = load_macro("CPIAUCNS")
    res: dict = {}

    # ---------------- 场景 A：美股 40 年定投的百年分布（全收益口径）--------
    print("\n" + "=" * 78)
    print("场景A · 标普500 全收益 · 40年窗口 · 每交易日 10 元（1927-2026 百年滚动）")
    print("=" * 78)
    d_us, p_us = make_tr("IDX_GSPC", DIV_US)
    wins = windows(d_us, 40)
    rows_a = [run_window(p_us[i0:i1 + 1], d_us[i0:i1 + 1], 10.0, cd, cv)
              for i0, i1 in wins]
    for nm, key, f in [("终值倍数", "multiple", "{:.2f}×"),
                       ("XIRR", "xirr", "{:.2%}"),
                       ("最深浮亏", "max_dd", "{:.1%}"),
                       ("水下占比", "under_pct", "{:.1%}"),
                       ("实际购买力倍数", "real_multiple", "{:.2f}×")]:
        s = stats([r[key] for r in rows_a])
        print(f"  {nm:16s} 中位 {f.format(s['median']):>9s}  "
              f"P5 {f.format(s['p5']):>9s}  P95 {f.format(s['p95']):>9s}  "
              f"最差 {f.format(s['min']):>9s}  最好 {f.format(s['max']):>9s}")
    worst = min(rows_a, key=lambda r: r["multiple"])
    best = max(rows_a, key=lambda r: r["multiple"])
    for tag, r in (("最差起点", worst), ("最佳起点", best)):
        print(f"  {tag} {r['start_year']}（{r['start']}→{r['end']}）  "
              f"投 {r['invested']:,.0f} → {r['final']:,.0f}  {r['multiple']:.2f}×  "
              f"XIRR {r['xirr']:.2%}  最深浮亏 {r['max_dd']:.1%}"
              f"（{r['worst_date']}）  水下 {r['under_pct']:.1%}"
              f"  折今日购买力 {r['real_final_today']:,.0f}")
    res["A_century_40y_tr"] = dict(stats_summary={
        k: stats([r[k] for r in rows_a]) for k in
        ["multiple", "xirr", "max_dd", "under_pct", "real_multiple"]},
        worst=worst, best=best, windows=rows_a)

    # ---------------- 场景 B：真实可得的最长全收益窗口 --------------------
    print("\n" + "=" * 78)
    print("场景B · 各腿真实最长窗口（全收益口径）")
    print("=" * 78)
    legs = [
        ("IDX_GSPC", "标普500（全收益构造）", DIV_US, 10.0),
        ("IDX_NDX", "纳指100（价格+微股息）", 0.006, 10.0),
        ("IDX_HSI", "恒生指数（全收益构造）", DIV_HK, 10.0),
        ("510880.SS", "上证红利ETF（真实含分红）", 0.0, 10.0),
        ("3110.HK", "恒生高股息率ETF（真实含分红）", 0.0, 10.0),
        ("515100.SS", "红利低波100ETF（真实含分红）", 0.0, 10.0),
    ]
    res["B_legs"] = {}
    for sym, name, div, amt in legs:
        try:
            d, p = make_tr(sym, div)
        except FileNotFoundError:
            print(f"  {name} 缺数据")
            continue
        r = run_window(p, d, amt, cd, cv)
        res["B_legs"][sym] = dict(name=name, div=div, **r)
        print(f"  {name:26s} {r['years']:5.1f}y  {r['start']}→{r['end']}  "
              f"投 {r['invested']:>8,.0f} → {r['final']:>11,.0f}  "
              f"{r['multiple']:6.2f}×  XIRR {r['xirr']:6.2%}  "
              f"最深浮亏 {r['max_dd']:7.1%}  水下 {r['under_pct']:5.1%}")

    # ---------------- 场景 C：40 元/日 四腿 40 年 bootstrap --------------
    print("\n" + "=" * 78)
    print("场景C · 四腿 40 年推演（区块 bootstrap，40 元/日 = 每腿 10 元）")
    print("=" * 78)
    s4 = bootstrap_fourleg(cd, cv, n_paths=800)
    res["C_bootstrap"] = s4

    res["D_sensitivity"] = sensitivity(cd, cv)

    # ---------------- 场景 E：投入是否随通胀加码 -------------------------
    print("\n" + "=" * 78)
    print("场景E · 固定 40 元/日  vs  按通胀加码（每年 +2.5%）")
    print("=" * 78)
    res["E_escalation"] = escalation(cd, cv)

    with open(os.path.join(OUT, "long_dca_result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=float)
    print(f"\n结果: {os.path.join(OUT,'long_dca_result.json')}")
    return 0


def escalation(cd, cv, n_paths: int = 400, seed: int = 777) -> dict:
    """固定名义投入 vs 按通胀加码：同样 40 年，购买力差多少。"""
    rng = np.random.default_rng(seed)
    legs = [("IDX_GSPC", "div_us"), ("IDX_NDX", 0.006),
            ("510880.SS", 0.0), ("IDX_HSI", "div_hk")]
    ser = []
    for sym, div in legs:
        dv = DIV_US if div == "div_us" else (DIV_HK if div == "div_hk" else div)
        d, p = make_tr(sym, dv)
        drift = geo_ann(d, p)
        ser.append((sym, d, p, drift))
    start = max(x[1][0] for x in ser)
    mats = []
    for sym, d, p, drift in ser:
        o = _ord(d)
        i0 = int(np.searchsorted(o, start.toordinal(), side="left"))
        mats.append(np.log(p[i0:] / np.concatenate([[p[i0]], p[i0:-1]])))
    n = min(len(m) for m in mats)
    R = np.column_stack([m[-n:] for m in mats])
    Rc = R - R.mean(axis=0)
    mu = np.array([np.log(1 + x[3]) / 252 for x in ser])
    days = 40 * 252
    out = {}
    c26 = cpi_at(cd, cv, dt.date(2026, 9, 16))
    c66 = cpi_at(cd, cv, dt.date(2066, 9, 16))
    for mode in ["flat", "escalated"]:
        totals, real_totals, reals_inv = [], [], []
        for k in range(n_paths):
            starts = rng.integers(0, n - 10, size=days // 10 + 1)
            idx = np.concatenate([np.arange(s, s + 10) for s in starts])[:days]
            path = np.exp(np.cumsum(Rc[idx] + mu, axis=0))
            tf = 0.0
            ri = 0.0
            for j in range(R.shape[1]):
                shares = 0.0
                for i in range(days):
                    amt = 10.0 if mode == "flat" else 10.0 * (1.025 ** (i / 252))
                    shares += amt / path[i, j]
                    if j == 0:
                        # 把第 i 天的名义投入折成 2026 年购买力（单腿值，四腿同额）
                        ri += amt * c26 / (c26 * (1.025 ** (i / 252)))
                tf += shares * path[-1, j]
            totals.append(tf)
            real_totals.append(tf / c66 * c26)
            reals_inv.append(ri * R.shape[1])   # 四腿合计
        out[mode] = dict(final=stats(totals), real=stats(real_totals),
                         real_invested=stats(reals_inv))
        lab = "固定 10 元/日（每腿）" if mode == "flat" else "按通胀 2.5% 加码"
        print(f"  {lab:22s} 名义终值中位 {stats(totals)['median']:>14,.0f}  "
              f"折今日终值中位 {stats(real_totals)['median']:>14,.0f}  "
              f"折今日累计投入 {stats(reals_inv)['median']:>12,.0f}  "
              f"实际倍数 {stats(real_totals)['median']/stats(reals_inv)['median']:>6.2f}×")
    inv_f = out["flat"]["real_invested"]["median"]
    inv_e = out["escalated"]["real_invested"]["median"]
    fin_f = out["flat"]["real"]["median"]
    fin_e = out["escalated"]["real"]["median"]
    eff_f = fin_f / inv_f
    eff_e = fin_e / inv_e
    print(f"  ⇒ 加码口径多投 {(inv_e/inv_f-1):.0%} 的实际购买力，"
          f"多拿 {(fin_e/fin_f-1):.0%} 的实际终值。")
    print(f"  ⇒ 但**每一元实际投入的效率**：固定口径 {eff_f:.1f}×，"
          f"加码口径 {eff_e:.1f}× —— 加码低 {(1-eff_e/eff_f):.0%}。"
          f"因为多出来的钱全压在复利时间更短的后半段。"
          f"结论：加码不是优化变量，只是「拿更多钱换更多钱」。")
    print(f"  ⇒ 固定名义口径的真正代价是**实际投入逐年缩水**："
          f"第 40 年的 40 元只剩今天约 1/2.69 ≈ 37% 的购买力。"
          f"这不是缺点，是「用越来越便宜的钱买同样的资产」。")
    return out


# ------------------------------------------------------- bootstrap 推演
LEGS = [("IDX_GSPC", "标普500（全收益构造）", "div_us", "USD"),
        ("IDX_NDX", "纳指100", 0.006, "USD"),
        ("510880.SS", "上证红利ETF（后复权）", 0.0, "CNY"),
        ("IDX_HSI", "恒生指数（全收益构造）", "div_hk", "HKD")]


def geo_ann(d, p, i0=0):
    yrs = (d[-1] - d[i0]).days / 365.25
    return float((p[-1] / p[i0]) ** (1 / yrs) - 1)


def bootstrap_fourleg(cd, cv, n_paths: int = 600, years: int = 40,
                      block: int = 10, adj: float = 0.0,
                      verbose: bool = True, seed: int = 20260917) -> dict:
    """四腿 40 年推演。

    ⚠ 方法论要点（第一版曾算出「中位 201×」的垃圾结果，原因就是这里）：
    共同窗口只有 2013-2026 共 12.8 年，恰是美股 + A股红利的大牛市
    （实测年化 14%~19%）。把这段样本的**漂移**直接 bootstrap 外推 40 年，
    复利会炸成天文数字。正确做法是**漂移与形状分离**：
      · 形状（波动、腿间相关、尾部聚集）← 共同窗口的**去均值**日收益，区块重采样
      · 漂移 ← 各腿**各自可得最长历史**的几何年化（百年/41年/19.7年/40年）
    这样既保住真实的相关结构与尾部，又不会把一段牛市当成永久状态。
    """
    res_legs, drift = [], {}
    for sym, name, div, ccy in LEGS:
        dv = DIV_US if div == "div_us" else (DIV_HK if div == "div_hk" else div)
        d, p = make_tr(sym, dv)
        drift[sym] = geo_ann(d, p)
        res_legs.append((sym, name, dv, ccy, d, p))
    if verbose:
        print("  长期漂移锚（各腿可得最长历史的几何年化）:")
        for sym, name, dv, ccy, d, p in res_legs:
            print(f"    {name:24s} {d[0]}→{d[-1]} "
                  f"({(d[-1]-d[0]).days/365.25:5.1f}y)  "
                  f"年化 {drift[sym]:6.2%}  股息调整 {dv:5.2%}")

    # --- 形状：共同窗口去均值
    start = max(v[4][0] for v in res_legs)
    mats = []
    for sym, name, dv, ccy, d, p in res_legs:
        o = _ord(d)
        i0 = int(np.searchsorted(o, start.toordinal(), side="left"))
        prev = np.concatenate([[p[i0]], p[i0:-1]])
        mats.append(np.log(p[i0:] / prev))
    n = min(len(m) for m in mats)
    R = np.column_stack([m[-n:] for m in mats])
    Rc = R - R.mean(axis=0)                      # 去样本期漂移，只留形状
    if verbose:
        print(f"  对齐起点 {start}  联合样本 {n} 交易日（{n/252:.1f}y）")
        print(f"  样本期年化（仅用于说明为何不能直接外推）: "
              + "  ".join(f"{nm}={np.exp(R[:,j].mean()*252)-1:.2%}"
                          for j, (_, nm, _, _, _, _) in enumerate(res_legs)))
        print(f"  年化波动: " + "  ".join(
            f"{nm}={R[:,j].std()*np.sqrt(252):.1%}"
            for j, (_, nm, _, _, _, _) in enumerate(res_legs)))
    C = np.corrcoef(R.T)
    if verbose:
        print("  腿间相关（日频）:\n" + "\n".join(
            "    " + "  ".join(f"{x:6.3f}" for x in row) for row in C))

    mu = np.array([np.log(1 + drift[s]) / 252 + adj / 252 for s, *_ in res_legs])
    rng = np.random.default_rng(seed)   # 每次调用独立播种，保证可复现
    days = int(years * 252)
    nb = int(np.ceil(days / block))
    finals, mults, dds, unders, longs, dd_at = [], [], [], [], [], []
    curves = None
    band = []          # 每 5 个交易日采样的账户倍数曲线（用于分位带）
    for k in range(n_paths):
        starts = rng.integers(0, n - block, size=nb)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:days]
        path = np.exp(np.cumsum(Rc[idx] + mu, axis=0))
        tot_f, tot_i = 0.0, 0.0
        worst_dd = 0.0
        worst_i = 0
        curve, cum_inv = [], []
        for j in range(R.shape[1]):
            eq, inv, invc = dca(path[:, j], 10.0)
            tot_f += eq[-1]
            tot_i += inv
            curve.append(eq)
            cum_inv.append(invc)
        tot_curve = np.sum(curve, axis=0)
        tinv = np.sum(cum_inv, axis=0)
        ratio = tot_curve / tinv
        worst_i = int(np.argmin(ratio))
        worst_dd = float(ratio.min() - 1)
        under = tot_curve < tinv
        cur_ = long_ = 0
        for u in under:
            cur_ = cur_ + 1 if u else 0
            long_ = max(long_, cur_)
        finals.append(tot_f)
        mults.append(tot_f / tot_i)
        dds.append(worst_dd)
        unders.append(float(under.mean()))
        longs.append(int(long_))
        dd_at.append(worst_i / 252.0)      # 最痛时刻在第几年
        band.append(ratio[::5].astype(np.float32))
        if k == 0:
            curves = ratio
    finals = np.array(finals)
    mults = np.array(mults)
    dds = np.array(dds)
    unders = np.array(unders)
    longs = np.array(longs)
    dd_at = np.array(dd_at)
    c_t = cpi_at(cd, cv, dt.date(2026, 9, 16))
    c_40 = cpi_at(cd, cv, dt.date(2066, 9, 16))
    inf_factor = c_40 / c_t
    real_finals = finals / inf_factor
    if verbose:
        print(f"\n  40 年累计投入: {tot_i:,.0f} 元（每腿 10 元/日 × 40 年）"
              f"  ≈ 每月 {10*4*21:,.0f} 元")
        print(f"  40 年通胀因子（CPI 外推 2.5%/年）: {inf_factor:.2f}×")
    for nm, a, f in [("名义终值", finals, "{:,.0f}"),
                     ("倍数", mults, "{:.2f}×"),
                     ("最深浮亏", dds, "{:.1%}"),
                     ("交易日水下占比", unders, "{:.1%}"),
                     ("最长连续水下(交易日)", longs, "{:,.0f}"),
                     ("最痛时刻(第几年)", dd_at, "{:.1f}"),
                     ("折今日购买力终值", real_finals, "{:,.0f}")]:
        s = stats(a)
        if verbose:
            print(f"  {nm:20s} 中位 {f.format(s['median']):>12s}  "
                  f"P5 {f.format(s['p5']):>12s}  P25 {f.format(s['p25']):>12s}  "
                  f"P75 {f.format(s['p75']):>12s}  P95 {f.format(s['p95']):>12s}")
    if verbose:
        print(f"  （最长连续水下的中位 {longs.mean()/252:.1f} 年，"
              f"P95 {np.percentile(longs,95)/252:.1f} 年）")
    return dict(legs=[dict(sym=s, name=nm, div=dv, ccy=c, drift=drift[s])
                      for s, nm, dv, c, _, _ in res_legs],
                aligned_start=start.isoformat(), sample_days=int(n),
                sample_ann_ret=[float(np.exp(R[:, j].mean() * 252) - 1)
                                for j in range(R.shape[1])],
                ann_vol=[float(R[:, j].std() * np.sqrt(252))
                         for j in range(R.shape[1])],
                corr=C.tolist(), years=years, block=block, adj=adj,
                invested_total=float(tot_i),
                inflation_factor=float(inf_factor),
                finals=stats(finals), multiples=stats(mults), max_dd=stats(dds),
                under_pct=stats(unders), longest_under_years=stats(longs / 252),
                worst_dd_at_year=stats(dd_at),
                real_finals=stats(real_finals),
                band_pct={q: np.percentile(np.vstack(band), q, axis=0).tolist()
                          for q in (5, 25, 50, 75, 95)},
                band_step_days=5, band_years=years,
                curve01=(curves.tolist() if curves is not None else None))


def sensitivity(cd, cv) -> dict:
    """漂移敏感性：全部腿的年化假设整体平移，看 40 年终值怎么变。

    这是全篇最重要的稳健性检验 —— 因为「未来 40 年的年化」是不可知的，
    任何单点数字都是伪精确。尤其纳指100 的 15.23% 取自 1985-2026 这段
    史上最猛的科技股行情，必须当作上限而非中枢。
    """
    print("\n" + "=" * 78)
    print("场景D · 漂移敏感性（四腿年化假设整体平移）")
    print("=" * 78)
    out = {}
    for adj, lab in [(-0.04, "深度保守 -4pp"), (-0.02, "保守 -2pp"),
                     (0.0, "基准（各腿自身历史漂移）"), (+0.02, "乐观 +2pp")]:
        r = bootstrap_fourleg(cd, cv, n_paths=250, years=40, block=10,
                              adj=adj, verbose=False)
        out[f"{adj:+.2f}"] = dict(label=lab, adj=adj,
                                  multiples=r["multiples"], finals=r["finals"],
                                  real_finals=r["real_finals"],
                                  max_dd=r["max_dd"], under_pct=r["under_pct"])
    print(f"  {'情景':22s} {'名义终值中位':>14s} {'倍数中位':>10s} "
          f"{'折今日中位':>14s} {'最深浮亏中位':>12s}")
    for k, v in out.items():
        print(f"  {v['label']:22s} {v['finals']['median']:>14,.0f} "
              f"{v['multiples']['median']:>9.2f}× "
              f"{v['real_finals']['median']:>14,.0f} "
              f"{v['max_dd']['median']:>11.1%}")
    lo = out["-0.04"]["multiples"]["median"]
    hi = out["+0.02"]["multiples"]["median"]
    print(f"  ⇒ 40 年倍数落在 {lo:.1f}× ~ {hi:.1f}× 之间，跨度 {hi/lo:.1f} 倍。"
          f"「年化差 6 个点」= 「终值差一倍以上」——这就是长期定投唯一的真问题。")
    return out


if __name__ == "__main__":
    raise SystemExit(main())
