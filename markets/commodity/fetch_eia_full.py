# -*- coding: utf-8 -*-
"""
EIA 全量补抓 (气体 / 石油 / 电力 / 库存)

⚠️ 关键坑 (2026-09-09 实测): api.eia.gov 走 3067 代理会返回 HTTP 200 但 body 为空
   → 必须**直连** (不走 proxy)

已抓(fetch_eia_gas.py): Henry Hub 现货 1980起 / Mont Belvieu 丙烷 1992起 /
                        WTI·Brent·柴油·航煤 / 全美各州气价 423 序列
本脚本补:  天然气库存 / 石油库存 / 电力(批发电价·用电量) / 天然气期货 / 国际能源 / 煤炭·可再生能源

用法: python fetch_eia_full.py
"""
import json
import os
import time
import urllib.parse
import urllib.request

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data")
RAW_DIR = os.path.join(OUT_DIR, "raw_eia")
os.makedirs(RAW_DIR, exist_ok=True)
KEY = json.load(open(os.path.join(HERE, "keys.local.json")))["eia"]["key"]

# (route, 标签, 频率)
ROUTES = [
    ("natural-gas/stor/sum", "NG_STOR", "monthly"),
    ("natural-gas/stor/wkly", "NG_STOR_WK", "weekly"),
    ("natural-gas/pri/fut", "NG_FUT", "daily"),
    ("natural-gas/sum/sndm", "NG_SUMMARY", "monthly"),
    ("petroleum/stoc/wstk", "OIL_STOC", "weekly"),
    ("petroleum/pri/spt", "OIL_SPOT", "daily"),
    ("petroleum/sum/sndw", "OIL_SUMMARY", "weekly"),
    ("electricity/retail-sales", "ELEC_RETAIL", "monthly"),
    ("electricity/eia-930/price", "ELEC_PRICE", "hourly"),
    ("coal/shipments", "COAL_SHIP", "quarterly"),
    ("total-energy/monthly", "TOTAL_ENERGY", "monthly"),
]


def fetch(route, frequency, start="1980-01", max_pages=25):
    """分页拉一个 route 全部数据"""
    rows = []
    for page in range(max_pages):
        params = {
            "api_key": KEY, "frequency": frequency, "data[0]": "value",
            "start": start, "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "length": 5000, "offset": page * 5000,
        }
        url = f"https://api.eia.gov/v2/{route}/data/?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                d = json.load(r)
        except Exception as e:
            print(f"    p{page} ERR {str(e)[:60]}")
            break
        resp = d.get("response", {})
        data = resp.get("data", [])
        if not data:
            break
        rows.extend(data)
        total = resp.get("total")
        try:
            if total and len(rows) >= int(total):
                break
        except (TypeError, ValueError):
            pass
        time.sleep(0.5)
        if len(data) < 5000:
            break
    return rows


def main():
    for route, tag, freq in ROUTES:
        print(f"\n=== {tag}  /{route}  ({freq}) ===", flush=True)
        out_raw = os.path.join(RAW_DIR, f"{tag}.csv")
        if os.path.exists(out_raw):
            print(f"    已存在, 跳过 ({out_raw})")
            continue
        t0 = time.time()
        rows = fetch(route, freq)
        if not rows:
            print("    无数据")
            continue
        df = pd.DataFrame(rows)
        df.to_csv(out_raw, index=False)
        print(f"    {len(df)} 行, 耗时 {time.time() - t0:.0f}s", flush=True)

        # 序列概览
        if "series" in df.columns and "period" in df.columns:
            g = df.groupby("series").agg(
                n=("value", "size"), first=("period", "min"), last=("period", "max"),
            ).sort_values("n", ascending=False)
            print(f"    序列数 {len(g)}")
            for sid, r in g.head(6).iterrows():
                print(f"      {str(sid):40s} {r['n']:6d}点 {r['first']}~{r['last']}")
        elif "period" in df.columns:
            print(f"    周期 {df['period'].min()} ~ {df['period'].max()}")
        time.sleep(1.0)


if __name__ == "__main__":
    main()
