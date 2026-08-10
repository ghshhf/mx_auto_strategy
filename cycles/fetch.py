# -*- coding: utf-8 -*-
"""
fetch.py - 周期原始序列抓取 (v6.19)
===================================
从 FRED 抓取量化周期的月度真实序列, 落盘为 cycles/data/cycles_raw.csv。
设计原则(沿用 macro_fetch.py):
  1. 前视偏差防护: 每行写入 available_date = 月份 + 发布滞后(取所有列中最保守的滞后),
     引擎只按 available_date 取数, 从源头杜绝偷看未来。
  2. 优雅降级: 任一序列抓不到 → 该列留空, 不中止、不报错。
  3. 无硬依赖: 仅用 requests(已装) + pandas, 不依赖 fredapi/yfinance。

代理: 默认读环境 http_proxy/https_proxy, 缺失则回退本机 127.0.0.1:3067。
运行: G:\\venv\\quant\\Scripts\\python.exe cycles/fetch.py
"""
from __future__ import annotations
import os
import sys
import io

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests
import pandas as pd

from . import specs

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
RAW_OUT = os.path.join(DATA, "cycles_raw.csv")

# 所有量化周期里的最大发布滞后(月) — 保守: 一行只有全部列可用时才可用
MAX_LAG = max(c["lag_months"] for c in specs.QUANT_CYCLES)
FRED_START = "2005-01-01"


def get_proxy():
    p = os.environ.get("http_proxy") or os.environ.get("https_proxy")
    if p:
        return {"http": p, "https": p}
    return {"http": "http://127.0.0.1:3067", "https": "http://127.0.0.1:3067"}


def _shift_month(ym: str, k: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    m += k
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def _ym(d) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def fetch_fred_series(series_id: str, proxy: dict, transform: str = "last") -> dict:
    """返回 {YYYY-MM: float} 月度序列。transform: last|mean。"""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={FRED_START}"
    try:
        r = requests.get(url, proxies=proxy, timeout=40)
        if r.status_code != 200:
            print(f"[cycles] FRED {series_id} -> HTTP {r.status_code}", file=sys.stderr)
            return {}
        df = pd.read_csv(io.StringIO(r.text))
        cols = list(df.columns)
        date_col, val_col = cols[0], cols[-1]
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
        df = df.dropna().set_index(date_col).sort_index()
        if df.empty:
            return {}
        how = "mean" if transform == "mean" else "last"
        m = df[val_col].resample("ME").agg(how).dropna()
        return {_ym(idx): float(v) for idx, v in m.items()}
    except Exception as e:  # 优雅降级
        print(f"[cycles] FRED {series_id} 异常: {e}", file=sys.stderr)
        return {}


def _yoy(monthly: dict) -> dict:
    """对月度序列做 12 个月同比。"""
    vals = dict(sorted(monthly.items()))
    yms = list(vals.keys())
    out = {}
    for i, ym in enumerate(yms):
        if i < 12:
            continue
        prev = vals.get(_shift_month(ym + "-01", -12)[:7])
        cur = vals[ym]
        if prev and prev != 0:
            out[ym] = round((cur / prev - 1.0) * 100, 2)
    return out


def fetch_all(proxy=None):
    """抓取全部量化周期的原始月度序列。返回 {col: {ym: value}}。"""
    if proxy is None:
        proxy = get_proxy()
    series_cols: dict[str, dict] = {}
    for c in specs.QUANT_CYCLES:
        for sid, col, transform in c["fred"]:
            if col in series_cols:
                continue
            raw = fetch_fred_series(sid, proxy, transform)
            if not raw:
                continue
            series_cols[col] = _yoy(raw) if transform == "yoy" else raw
            print(f"[cycles] {sid} ({col}): {len(series_cols[col])} 月", file=sys.stderr)
    return series_cols


def build_raw_csv(proxy=None, out_path=RAW_OUT):
    """抓取并落盘 cycles_raw.csv。返回输出路径或 None。"""
    os.makedirs(DATA, exist_ok=True)
    series_cols = fetch_all(proxy)
    if not series_cols:
        print("[cycles] 无任何序列, 中止落盘", file=sys.stderr)
        return None
    # 统一月份并集
    all_months = sorted({ym for d in series_cols.values() for ym in d})
    avail_for = {ym: _shift_month(ym + "-01", MAX_LAG) for ym in all_months}
    # 收集所有列名(含每个 fred 的 col)
    col_names = []
    for c in specs.QUANT_CYCLES:
        for _sid, col, _t, _s in c["fred"]:
            if col not in col_names:
                col_names.append(col)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write("month,available_date," + ",".join(col_names) + "\n")
        for ym in all_months:
            row = [ym, avail_for[ym]]
            for col in col_names:
                row.append("" if ym not in series_cols.get(col, {}) else
                           repr(series_cols[col][ym]))
            f.write(",".join(row) + "\n")
    print(f"[cycles] 落盘 {len(all_months)} 月 -> {out_path} (可用滞后 +{MAX_LAG} 月)")
    return out_path


if __name__ == "__main__":
    build_raw_csv()
