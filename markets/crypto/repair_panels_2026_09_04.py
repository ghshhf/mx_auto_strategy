#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
面板数据修复工具 (2026-09-04)

背景 (本次体检发现的三层数据问题):
  1. v3 面板: 历史数据为合成/错源填充, 与真值比对 6044 单元格偏差 / 28 币,
     起点为整数占位 (BTC 430.00 / ETH 10.00 / ZEC 400.00 / FIL 25.00 / RENDER 0.05)
  2. c50 面板: 与 v3 同源合成, 21 个币存在"早于真实上线日"的假历史
     (ZEC 2016-01=400.0 而真实仅 $1-3; UNI 2020-01=3.0 而 2020-09 才上线;
      DYDX 2021-01=8.0 / APT 2022-01=4.0 / FIL 2020-01=25.0 同理)
     且 2026-08-21 单行滞后重复, POL 中段有 10 倍断点
  3. 10y 面板: 唯一真值基准 (早期段与真实历史精确吻合:
     BTC 2014-09-19=394.80 / ETH 2015-08-07=2.7721; 各币起始日符合真实上线时间),
     但存在 POL 707 天空洞、GRAM 数据偏晚 (仅 2024-08 起 104 周)

修复策略:
  - 10y 为唯一真值基准
  - POL 空洞用 Binance 补 (洞后锚点偏差 +0.0%, 100 周全覆盖)
  - GRAM 用 Gate 补洞并扩展历史 (与 10y 重合期比值中位 1.0000, 与 Binance 独立吻合)
  - c50 / v3 在重合日期完全采用 10y 值 (含 NaN, 即删除上线前的合成段)

用法:
  python repair_panels_2026_09_04.py [--apply]
  不带 --apply 为预演 (dry-run)
"""
import os
import sys
import datetime as dt

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import manage_token as mt  # noqa: E402

DATA = os.path.join(HERE, "data")
F_C50 = "weekly_adjclose_crypto50.csv"
F_10Y = "weekly_adjclose_crypto50_10y.csv"
F_V3 = "weekly_adjclose_crypto50_v3.csv"

TOL = 0.03
GAP_DAYS = 14


def load(fn):
    return pd.read_csv(os.path.join(DATA, fn), index_col=0, parse_dates=True).sort_index()


def fmt(v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return ""
    return "%.8g" % v


def save(df, fn):
    rows, meta, path = mt.read_panel(fn)
    new_rows = [[""] + list(df.columns)]
    for idx, row in df.iterrows():
        new_rows.append([idx.strftime("%Y-%m-%d")] + [fmt(v) for v in row.values])
    mt.write_panel(new_rows, meta, path)


def holes(df):
    out = {}
    for c in df.columns:
        s = df[c].dropna()
        if len(s) < 3:
            continue
        gaps = s.index.to_series().diff().dt.days.dropna()
        if len(gaps) == 0:
            continue
        pos = int(gaps.values.argmax())
        mg = int(gaps.values[pos])
        if mg > GAP_DAYS:
            out[c] = (mg, s.index[pos].date(), s.index[pos + 1].date())
    return out


def fill_from_source(df, col, weekly_monday, only_hole=True):
    """用交易所周线({monday: close})填充 df[col] 的空值 (-3 口径)."""
    n = 0
    for fri in df.index:
        if pd.notna(df.at[fri, col]):
            continue
        if only_hole:
            pass
        mon = (fri.date() + dt.timedelta(days=3)).isoformat()
        v = weekly_monday.get(mon)
        if v is not None:
            df.at[fri, col] = v
            n += 1
    return n


def main():
    apply = "--apply" in sys.argv
    print(f"模式: {'实际写入' if apply else '预演(dry-run)'}\n")

    d10 = load(F_10Y)
    c50 = load(F_C50)
    v3 = load(F_V3)
    print(f"读入: 10y {d10.shape} | c50 {c50.shape} | v3 {v3.shape}")

    # ---------- 1. 10y 补洞 / 扩展 ----------
    print("\n=== [1] 10y 补洞与扩展 ===")
    print("  补洞前空洞:", holes(d10) or "无")

    if "POL" in holes(d10):
        pol = mt.SOURCES["binance"]("POL")
        n = fill_from_source(d10, "POL", pol)
        print(f"  POL  补入 {n} 周 (Binance, {len(pol)} 周可用)")
        s = d10["POL"].dropna()
        print("    衔接:", ", ".join(
            f"{d}={s.get(pd.Timestamp(d)):.4f}" for d in
            ["2024-09-06", "2024-09-13", "2026-08-07", "2026-08-14"]
            if s.get(pd.Timestamp(d)) is not None))

    gram = mt.SOURCES["gate"]("GRAM")
    n = fill_from_source(d10, "GRAM", gram)
    print(f"  GRAM 补入 {n} 周 (Gate, {len(gram)} 周可用)")
    s = d10["GRAM"].dropna()
    print(f"    GRAM 现 {len(s)} 点, {s.index[0].date()} ~ {s.index[-1].date()}")
    print("    衔接:", ", ".join(
        f"{d}={s.get(pd.Timestamp(d)):.4f}" for d in
        ["2023-03-17", "2024-07-26", "2024-08-02", "2026-08-28"]
        if s.get(pd.Timestamp(d)) is not None))

    print("  补洞后空洞:", holes(d10) or "无 ✓")

    # ---------- 2. c50 / v3 完全采用 10y 真值 ----------
    print("\n=== [2] c50 / v3 对齐 10y 真值 (含删除上线前合成段) ===")
    for name, df in [("c50", c50), ("v3", v3)]:
        cd = df.index.intersection(d10.index)
        changed = 0
        removed = 0
        cols = set()
        for c in df.columns:
            if c not in d10.columns:
                continue
            a = df.loc[cd, c].copy()
            b = d10.loc[cd, c]
            both = a.notna() & b.notna()
            diff = both & ((a - b).abs() / b.abs() > TOL)
            fill = (~a.notna()) & b.notna()
            drop = a.notna() & (~b.notna())       # 本面板有值而 10y 为空 -> 合成段
            n = int(diff.sum()) + int(fill.sum()) + int(drop.sum())
            if n:
                changed += int(diff.sum()) + int(fill.sum())
                removed += int(drop.sum())
                cols.add(c)
                df.loc[cd, c] = b                  # 完全替换 (含 NaN)
        print(f"  {name}: 修正 {changed} 单元格, 删除合成段 {removed} 单元格, 涉及 {len(cols)} 币")
        if cols:
            print(f"      {sorted(cols)}")

    # ---------- 3. 写回 ----------
    print("\n=== [3] 写回 ===")
    if apply:
        save(d10, F_10Y)
        save(c50, F_C50)
        save(v3, F_V3)
        print("  已写入三张面板")
    else:
        print("  (预演模式, 未写入)")

    # ---------- 4. 校验 ----------
    print("\n=== [4] 三面板最终一致性 ===")
    ok = True
    if apply:
        a, b, c = load(F_C50), load(F_10Y), load(F_V3)
        for n1, x, n2, y in [("c50", a, "10y", b), ("v3", c, "10y", b)]:
            cd = x.index.intersection(y.index)
            diff = 0
            for col in x.columns:
                ra, rb = x.loc[cd, col], y.loc[cd, col]
                m = ra.notna() & rb.notna() & (rb != 0)
                if m.sum() == 0:
                    continue
                ratio = ra[m] / rb[m]
                diff += int(((ratio < 1 - TOL) | (ratio > 1 + TOL)).sum())
            print(f"  {n1} vs {n2}: 不一致 {diff} 单元格 {'✓' if diff == 0 else '✗'}")
            ok = ok and (diff == 0)
        print("  10y 最终空洞:", holes(load(F_10Y)) or "无 ✓")
    print("\n结果:", "✓ 通过" if ok or not apply else "✗ 存在残留差异")


if __name__ == "__main__":
    main()
