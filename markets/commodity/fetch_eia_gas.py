# -*- coding: utf-8 -*-
"""
EIA API v2 气体/能源数据抓取 (需 API key, 存于 keys.local.json)

通道要点 (2026-09-09 实踩):
  1. api.eia.gov **必须直连**, 走 127.0.0.1:3067 代理会返回 HTTP 200 但 body 为空 -> 极坑
  2. v2 目录结构: response.routes / response.children; 叶节点看 facets (duoarea/product/process/series)
  3. 取数端点: /v2/{route}/data/?frequency=monthly&data[0]=value&length=5000&offset=N
  4. 单次 length 上限 5000, 需分页
目标: 补 FRED/World Bank 没有的气体与能源全链 —— 天然气/丙烷/丁烷/乙烷/氦气候选/电力
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
BASE = "https://api.eia.gov/v2/{route}/data/?"

# 目标数据集 (先抓这些, 后续按目录继续扩)
ROUTES = [
    ("natural-gas/pri/sum", "NG_PRICE_SUM"),      # 天然气价格(Henry Hub 现货等)
    ("natural-gas/pri/fut", "NG_FUT"),            # NYMEX 天然气期货
    ("petroleum/pri/spt", "PET_SPOT"),            # 石油+NGPL 现货价(丙烷/丁烷/乙烷 Mont Belvieu)
    ("petroleum/pri/prop", "PROPANE_RETAIL"),     # 民用丙烷价格
    ("natural-gas/stor", "NG_STORAGE"),           # 天然气库存(基本面)
]


def fetch_series(route, frequency="monthly", start="1980-01", max_pages=40):
    """分页拉一个 route 的全部序列"""
    rows = []
    for page in range(max_pages):
        params = {
            "api_key": KEY,
            "frequency": frequency,
            "data[0]": "value",
            "start": start,
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "length": 5000,
            "offset": page * 5000,
        }
        url = BASE.format(route=route) + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                d = json.load(r)
        except Exception as e:
            print(f"    ERR {route} p{page}: {str(e)[:70]}")
            break
        resp = d.get("response", {})
        data = resp.get("data", [])
        if not data:
            break
        rows.extend(data)
        total = resp.get("total")
        if total and len(rows) >= int(total):
            break
        time.sleep(0.7)
    return rows


def main():
    summary = []
    panels = {}
    for route, tag in ROUTES:
        print(f"[{tag}] {route}")
        rows = fetch_series(route)
        if not rows:
            print("    无数据")
            continue
        df = pd.DataFrame(rows)
        df.to_csv(os.path.join(RAW_DIR, f"{tag}_raw.csv"), index=False)
        cols = [c for c in ["period", "series", "seriesDescription", "value", "units", "duoarea", "product", "process"] if c in df.columns]
        print(f"    {len(df)} 行, 列: {cols}")
        if "series" in df.columns:
            uniq = df.groupby("series").agg(
                n=("value", "size"),
                first=("period", "min"),
                last=("period", "max"),
                unit=("units", "first"),
                area=("duoarea", "first"),
                prod=("product", "first"),
            ).sort_values("n", ascending=False)
            print(f"    序列数: {len(uniq)}")
            for sid, r in uniq.head(15).iterrows():
                print(f"      {sid:40s} {r['n']:6d}点 {r['first']}~{r['last']} {str(r['unit'])[:14]:>14s} area={r['area']} prod={r['prod']}")
            # 透视成面板
            piv = df.pivot_table(index="period", columns="series", values="value", aggfunc="last")
            piv = piv[sorted(piv.columns)]
            panels[tag] = piv
            piv.to_csv(os.path.join(RAW_DIR, f"{tag}_panel.csv"))
        summary.append((tag, route, len(df), df["series"].nunique() if "series" in df.columns else 0))
        time.sleep(1.0)

    print("\n=== 汇总 ===")
    for tag, route, n, ns in summary:
        print(f"  {tag:18s} {route:24s} {n:7d} 行  {ns:4d} 序列")

    # 合并面板
    if panels:
        out = os.path.join(OUT_DIR, "eia_gas_monthly.csv")
        allp = pd.concat(panels.values(), axis=1)
        allp = allp[~allp.index.duplicated()].sort_index()
        allp.to_csv(out)
        print(f"\n合并面板: {out}  {allp.shape[0]} 行 x {allp.shape[1]} 列")


if __name__ == "__main__":
    main()
