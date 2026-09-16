# -*- coding: utf-8 -*-
"""markets/dca/fetch_macro.py —— 宏观长序列落盘（FRED，免 key）

FRED 的 fredgraph.csv 接口免 key、直出 CSV，是长历史宏观最稳的口子。
落盘到 data/macro/{SERIES}.csv，二次运行读盘。
"""
from __future__ import annotations

import csv
import io
import os
import ssl
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
from net_config import proxy_opener, proxy_url  # noqa: E402

ssl._create_default_https_context = ssl._create_unverified_context
MACRO = os.path.join(HERE, "data", "macro")
os.makedirs(MACRO, exist_ok=True)

SERIES = [
    ("CPIAUCSL",        "美国 CPI (季调, 指数)",       "inflation_us"),
    ("CPIAUCNS",        "美国 CPI (未季调)",           "inflation_us"),
    ("CHNCPIALLMINMEI", "中国 CPI (OECD, 月度)",       "inflation_cn"),
    ("DEXCHUS",         "美元兑人民币 (月均)",          "fx"),
    ("DEXHKUS",         "美元兑港元",                  "fx"),
    ("FEDFUNDS",        "联邦基金利率",                "rate"),
    ("DFEDTARU",        "联邦基金目标上限",             "rate"),
    ("DGS10",           "美债 10 年",                  "rate"),
    ("DGS30",           "美债 30 年",                  "rate"),
    ("M2SL",            "美国 M2",                     "money"),
]


def fetch(series: str) -> list[list[str]]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    req = __import__("urllib.request", fromlist=["Request"]).Request(
        url, headers={"User-Agent": "Mozilla/5.0"})
    with proxy_opener().open(req, timeout=60) as r:
        txt = r.read().decode("utf-8", "ignore")
    rows = []
    for line in io.StringIO(txt):
        line = line.strip()
        if not line:
            continue
        p = line.split(",")
        if p[0].lower() in ("date", "observation_date"):
            continue
        if p[1] in (".", "", "NA"):
            continue
        rows.append([p[0], p[1]])
    return rows


def main() -> int:
    print(f"代理: {proxy_url()}")
    ok = fail = 0
    for series, name, kind in SERIES:
        path = os.path.join(MACRO, f"{series}.csv")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                n = sum(1 for _ in f) - 1
            if n > 12:
                print(f"  [skip] {series:16s} {name:24s} 已有 {n} 条")
                ok += 1
                continue
        try:
            rows = fetch(series)
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["date", "value"])
                w.writerows(rows)
            print(f"  [ ok ] {series:16s} {name:24s} {len(rows):6d} 条  "
                  f"{rows[0][0]} -> {rows[-1][0]}")
            ok += 1
        except Exception as e:
            print(f"  [FAIL] {series:16s} {name:24s} {type(e).__name__}: {str(e)[:60]}")
            fail += 1
        time.sleep(0.4)
    print(f"\n完成: 成功 {ok} / 失败 {fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
