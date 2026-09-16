# -*- coding: utf-8 -*-
"""markets/dca/dca_backtest.py —— 长期定投推演引擎

口径
----
- 每腿按**自己的交易日**投固定金额（用户口径：每腿 10 元/工作日，四腿合计 40 元）。
- 复权价用 adjclose（含分红再投资）；^GSPC 等价格指数 adjclose==close，不含分红，
  一律显式标注为「价格口径 = 下限」。
- 年化用 XIRR（资金加权），与「终值/投入」的简单倍数**分开报**（IRR 高 ≠ 钱多）。
- 通胀调整用美国 CPI（长窗口）/ 中国 CPI（近期人民币口径），明确标注。
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "data", "history")
MACRO = os.path.join(HERE, "data", "macro")
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

_cache: dict[str, tuple[list, np.ndarray]] = {}


def load(sym: str) -> tuple[list, np.ndarray]:
    """读盘。返回 (dates[list[date]], adjclose[np.ndarray])。"""
    if sym in _cache:
        return _cache[sym]
    safe = sym.replace("^", "IDX_").replace("=", "_").replace("/", "_")
    path = os.path.join(HIST, f"{safe}.csv")
    dates, vals = [], []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            v = row["adjclose"]
            if v in ("", "None", "null"):
                continue
            try:
                fv = float(v)
            except ValueError:
                continue
            if fv <= 0:
                continue
            y, m, d = (int(x) for x in row["date"].split("-"))
            dates.append(dt.date(y, m, d))
            vals.append(fv)
    arr = np.asarray(vals, dtype=float)
    _cache[sym] = (dates, arr)
    return dates, arr


def load_macro(series: str) -> tuple[list, np.ndarray]:
    path = os.path.join(MACRO, f"{series}.csv")
    dates, vals = [], []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                fv = float(row["value"])
            except (ValueError, KeyError):
                continue
            s = row["date"]
            y, m = int(s[:4]), int(s[5:7])
            dates.append(dt.date(y, m, 1))
            vals.append(fv)
    return dates, np.asarray(vals, dtype=float)


# ------------------------------------------------------------------ 核心
def dca(prices: np.ndarray, amount: float) -> tuple[np.ndarray, float]:
    """每日定额买入。返回 (每日账户市值曲线, 累计投入)。"""
    shares = 0.0
    invested = 0.0
    eq = np.empty(len(prices))
    inv = np.empty(len(prices))
    for i, p in enumerate(prices):
        shares += amount / p
        invested += amount
        eq[i] = shares * p
        inv[i] = invested
    return eq, invested, inv


def xirr(cfs: list[tuple[dt.date, float]]) -> float:
    """资金加权年化。cfs = [(日期, 现金流)]，投入为负、终值为正。"""
    if not cfs:
        return float("nan")
    t0 = cfs[0][0]
    xs = np.array([(d - t0).days / 365.25 for d, _ in cfs])
    ys = np.array([v for _, v in cfs])

    def npv(r):
        return float(np.sum(ys / np.power(1.0 + r, xs)))

    lo, hi = -0.9, 3.0
    if npv(lo) * npv(hi) > 0:
        return float("nan")
    for _ in range(300):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def cagr_first_last(prices: np.ndarray, dates: list) -> float:
    yr = (dates[-1] - dates[0]).days / 365.25
    return (prices[-1] / prices[0]) ** (1 / yr) - 1 if yr > 0 else float("nan")


def metrics(prices: np.ndarray, dates: list, amount: float) -> dict:
    eq, invested, inv = dca(prices, amount)
    under = eq < inv
    # 最长连续水下（交易日数）
    longest = cur = 0
    for u in under:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    cfs = [(d, -amount) for d in dates] + [(dates[-1], float(eq[-1]))]
    idx_worst = int(np.argmin(eq / inv))
    return dict(
        days=len(dates),
        years=round((dates[-1] - dates[0]).days / 365.25, 2),
        start=dates[0].isoformat(), end=dates[-1].isoformat(),
        invested=float(invested),
        final=float(eq[-1]),
        multiple=float(eq[-1] / invested),
        xirr=xirr(cfs),
        under_pct=float(under.mean()),
        max_dd_vs_invested=float((eq / inv).min() - 1),
        worst_date=dates[idx_worst].isoformat(),
        longest_under_days=int(longest),
    )


def rolling_windows(dates: list, prices: np.ndarray, years: int,
                    step_years: int = 1) -> list[tuple[int, int]]:
    """返回 [(i0,i1)] 满足 i1-i0 ≈ years 年。"""
    out = []
    n = len(dates)
    for i0 in range(n):
        target = dates[i0].replace(year=dates[i0].year + years)
        j = np.searchsorted([d.toordinal() for d in dates],
                            target.toordinal(), side="left")
        if j >= n:
            break
        if out and (dates[i0].year - dates[out[-1][0]].year) < step_years:
            continue
        out.append((i0, int(j)))
    return out


def real_value(nominal: float, d0: dt.date, d1: dt.date,
               cpi_dates: list, cpi_vals: np.ndarray) -> float:
    """把 d1 时点的名义金额折成 d0 时点的购买力。"""
    def at(d):
        j = np.searchsorted([x.toordinal() for x in cpi_dates], d.toordinal(),
                            side="right") - 1
        return cpi_vals[max(j, 0)]
    return nominal * at(d0) / at(d1)


# ------------------------------------------------------------------ 场景
def scenario_century() -> dict:
    """场景1：美股 40 年定投的百年分布（^GSPC 价格口径 = 下限）。"""
    dates, px = load("IDX_GSPC")
    cd, cv = load_macro("CPIAUCNS")
    wins = rolling_windows(dates, px, 40)
    rows = []
    for i0, i1 in wins:
        m = metrics(px[i0:i1 + 1], dates[i0:i1 + 1], 10.0)
        m["start_year"] = dates[i0].year
        m["real_final"] = real_value(m["final"], dates[i0], dates[i1], cd, cv)
        m["real_invested"] = real_value(m["invested"], dates[i0], dates[i1], cd, cv)
        rows.append(m)
    return dict(label="^GSPC 标普500价格指数 · 40年窗口 · 每交易日10元",
                price_only=True, windows=rows)


def scenario_real_fourleg() -> dict:
    """场景2：四腿在共同可得窗口的真实定投（人民币口径）。"""
    legs = [("IDX_SP500TR", "标普500全收益", "USD"),
            ("IDX_NDX", "纳指100", "USD"),
            ("515100.SS", "红利低波100ETF", "CNY"),
            ("3110.HK", "恒生高股息率ETF", "HKD")]
    data = {}
    for sym, name, ccy in legs:
        try:
            data[sym] = load(sym)
        except FileNotFoundError:
            print(f"  缺数据: {sym}")
    # 共同窗口 = 各腿起始日的最大值
    common_start = max(d[0][0] for d in data.values())
    out = {}
    for sym, name, ccy in legs:
        if sym not in data:
            continue
        dates, px = data[sym]
        i0 = np.searchsorted([x.toordinal() for x in dates],
                             common_start.toordinal(), side="left")
        out[sym] = dict(name=name, ccy=ccy,
                        **metrics(px[i0:], dates[i0:], 10.0))
    return dict(label="四腿真实窗口（人民币/原币未折算）",
                common_start=common_start.isoformat(), legs=out)


def scenario_hold_vs_dca(sym: str, label: str, years: int | None = None) -> dict:
    """场景3：定投 vs 一次性（同额资金）对照。"""
    dates, px = load(sym)
    if years:
        target = dates[0].replace(year=dates[0].year + years)
        j = int(np.searchsorted([d.toordinal() for d in dates],
                                target.toordinal(), side="left"))
        dates, px = dates[:j + 1], px[:j + 1]
    m = metrics(px, dates, 10.0)
    lump = m["invested"] / px[0] * px[-1]
    return dict(label=label, sym=sym, **m,
                lump_final=float(lump), lump_multiple=float(lump / m["invested"]),
                lump_cagr=float(cagr_first_last(px, dates)))


def main() -> int:
    res = {}

    print("=" * 72)
    print("场景1 · 美股 40 年定投的百年分布（^GSPC 价格口径，下限）")
    print("=" * 72)
    s1 = scenario_century()
    rows = s1["windows"]
    mult = np.array([r["multiple"] for r in rows])
    xr = np.array([r["xirr"] for r in rows])
    dd = np.array([r["max_dd_vs_invested"] for r in rows])
    up = np.array([r["under_pct"] for r in rows])
    rf = np.array([r["real_final"] for r in rows])
    ri = np.array([r["real_invested"] for r in rows])
    print(f"窗口数 {len(rows)}  起投年份 {rows[0]['start_year']}~{rows[-1]['start_year']}")
    for nm, a, f in [("终值倍数", mult, "{:.2f}×"), ("XIRR", xr, "{:.2%}"),
                     ("最深浮亏", dd, "{:.1%}"), ("水下占比", up, "{:.1%}"),
                     ("实际购买力倍数", rf / ri, "{:.2f}×")]:
        print(f"  {nm:12s} 中位 {f.format(np.median(a)):>9s}  "
              f"P5 {f.format(np.percentile(a,5)):>9s}  "
              f"P95 {f.format(np.percentile(a,95)):>9s}  "
              f"最差 {f.format(a.min()):>9s}  最好 {f.format(a.max()):>9s}")
    best = max(rows, key=lambda r: r["multiple"])
    worst = min(rows, key=lambda r: r["multiple"])
    print(f"  最佳起点 {best['start_year']}  倍数 {best['multiple']:.2f}×  "
          f"终值 {best['final']:,.0f}")
    print(f"  最差起点 {worst['start_year']}  倍数 {worst['multiple']:.2f}×  "
          f"终值 {worst['final']:,.0f}  最深浮亏 {worst['max_dd_vs_invested']:.1%}")
    res["scenario1_century"] = s1

    print()
    print("=" * 72)
    print("场景2 · 真实全收益 38.7 年（^SP500TR 含分红再投）与纳指 41 年")
    print("=" * 72)
    s3 = {}
    for sym, lab in [("IDX_SP500TR", "标普500全收益 1988-2026"),
                     ("IDX_NDX", "纳指100 1985-2026"),
                     ("IDX_HSI", "恒生指数 1986-2026（价格口径）"),
                     ("IDX_IXIC", "纳斯达克综合 1971-2026（价格口径）")]:
        r = scenario_hold_vs_dca(sym, lab)
        s3[sym] = r
        print(f"  {lab:34s} {r['years']:5.1f}y  投{r['invested']:>8,.0f}  "
              f"终值{r['final']:>11,.0f}  {r['multiple']:.2f}×  "
              f"XIRR {r['xirr']:6.2%}  一次性{r['lump_multiple']:.2f}×  "
              f"最深浮亏{r['max_dd_vs_invested']:7.1%}  水下{r['under_pct']:5.1%}")
    res["scenario2_real"] = s3

    print()
    print("=" * 72)
    print("场景3 · 四腿真实共同窗口")
    print("=" * 72)
    s2 = scenario_real_fourleg()
    print(f"  共同起点 {s2['common_start']}")
    for sym, r in s2["legs"].items():
        print(f"  {r['name']:20s} {r['years']:5.1f}y  投{r['invested']:>7,.0f}  "
              f"终值{r['final']:>9,.0f}  {r['multiple']:.3f}×  "
              f"XIRR {r['xirr']:6.2%}  最深浮亏{r['max_dd_vs_invested']:7.1%}")
    res["scenario3_fourleg"] = s2

    with open(os.path.join(OUT, "long_dca_result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=float)
    print(f"\n结果: {os.path.join(OUT,'long_dca_result.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
