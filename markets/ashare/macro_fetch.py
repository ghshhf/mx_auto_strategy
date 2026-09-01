# -*- coding: utf-8 -*-
"""
macro_fetch.py - 宏观周期数据抓取 (v6.17)
===========================================
抓取 PMI / M2 / 社融, 落地为 CSV, 供 backtest_engine 的宏观叠加层读取。

★ 前视偏差防护 (本模块的核心)
  宏观数据存在发布滞后, 回测中若在数据"所属月份"就使用, 等于偷看未来。
  本脚本在落盘时即写入 available_date (可用日期 = 所属月 + 发布滞后),
  引擎只按 available_date 取数, 从源头杜绝前视。

  滞后取保守值:
    PMI    : 国统局月末发布当月值 -> 滞后 1 个月 (下月 1 日起可用)
    M2     : 央行次月 10-15 日发布上月值 -> 滞后 2 个月
    社融   : 同 M2 -> 滞后 2 个月

依赖: akshare (在 G:\\venv\\quant)
运行: G:\\venv\\quant\\Scripts\\python.exe macro_fetch.py
输出: data/macro_monthly.csv
"""
import os
import sys
import csv
from datetime import date

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
OUT = os.path.join(DATA, "macro_monthly.csv")

# 发布滞后 (月)
LAG_PMI = 1
LAG_M2 = 2
LAG_SHRZ = 2


def _shift_month(ym, k):
    """ym = 'YYYY-MM' 字符串, 前移 k 个月, 返回该月 1 日的 'YYYY-MM-DD'。"""
    y, m = int(ym[:4]), int(ym[5:7])
    m += k
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}-01"


def _norm_ym(raw):
    """把各种月份写法归一为 'YYYY-MM'。
    支持: '2026年07月份' / '201501' / '2025-07-31' / Timestamp。
    """
    s = str(raw).strip()
    if "年" in s:
        y = s.split("年")[0]
        m = s.split("年")[1].replace("月份", "").replace("月", "")
        return f"{int(y):04d}-{int(m):02d}"
    if len(s) == 6 and s.isdigit():
        return f"{s[:4]}-{s[4:]}"
    if len(s) >= 7 and s[4] == "-":
        return s[:7]
    return None


def fetch():
    import akshare as ak

    rows = {}  # ym -> dict

    def put(ym, key, val):
        if ym is None or val is None:
            return
        try:
            v = float(val)
        except (TypeError, ValueError):
            return
        if v != v:  # NaN
            return
        rows.setdefault(ym, {})[key] = v

    # --- PMI (制造业指数) ---
    try:
        df = ak.macro_china_pmi()
        for _, r in df.iterrows():
            put(_norm_ym(r["月份"]), "pmi", r["制造业-指数"])
        print(f"[macro] PMI: {len(df)} 月", file=sys.stderr)
    except Exception as e:
        print(f"[macro] PMI 抓取失败: {e}", file=sys.stderr)

    # --- M2 同比 ---
    try:
        df = ak.macro_china_money_supply()
        for _, r in df.iterrows():
            put(_norm_ym(r["月份"]), "m2_yoy", r["货币和准货币(M2)-同比增长"])
        print(f"[macro] M2: {len(df)} 月", file=sys.stderr)
    except Exception as e:
        print(f"[macro] M2 抓取失败: {e}", file=sys.stderr)

    # --- 社融增量 (亿元) ---
    try:
        df = ak.macro_china_shrzgm()
        for _, r in df.iterrows():
            put(_norm_ym(r["月份"]), "shrz", r["社会融资规模增量"])
        print(f"[macro] 社融: {len(df)} 月", file=sys.stderr)
    except Exception as e:
        print(f"[macro] 社融抓取失败: {e}", file=sys.stderr)

    if not rows:
        print("[macro] 无任何数据, 中止", file=sys.stderr)
        sys.exit(1)

    # --- 社融同比 (增量 12 月同比, 平滑掉春节等季节性) ---
    yms = sorted(rows)
    for i, ym in enumerate(yms):
        prev_ym = _shift_month(ym + "-01", -12)[:7]
        cur = rows[ym].get("shrz")
        prv = rows.get(prev_ym, {}).get("shrz")
        if cur is not None and prv is not None and prv > 0:
            rows[ym]["shrz_yoy"] = round((cur / prv - 1.0) * 100, 2)

    os.makedirs(DATA, exist_ok=True)
    cols = ["month", "available_date", "pmi", "m2_yoy", "shrz", "shrz_yoy"]
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for ym in yms:
            d = rows[ym]
            # available_date 取三者中最保守 (最晚) 的可用日:
            # 有 m2/社融 -> 滞后 2 月; 仅 PMI -> 滞后 1 月
            lag = LAG_PMI if (("m2_yoy" not in d) and ("shrz" not in d)) else LAG_M2
            avail = _shift_month(ym + "-01", lag)
            w.writerow([ym, avail,
                        d.get("pmi", ""), d.get("m2_yoy", ""),
                        d.get("shrz", ""), d.get("shrz_yoy", "")])

    print(f"[macro] 落盘 {len(yms)} 月 -> {OUT}")
    print(f"[macro] 区间: {yms[0]} ~ {yms[-1]}")
    have_pmi = sum(1 for y in yms if "pmi" in rows[y])
    have_m2 = sum(1 for y in yms if "m2_yoy" in rows[y])
    have_sh = sum(1 for y in yms if "shrz_yoy" in rows[y])
    print(f"[macro] 覆盖: PMI {have_pmi} / M2 {have_m2} / 社融同比 {have_sh}")
    print(f"[macro] 发布滞后已写入 available_date (PMI+{LAG_PMI}月, M2/社融+{LAG_M2}月)")


if __name__ == "__main__":
    fetch()
