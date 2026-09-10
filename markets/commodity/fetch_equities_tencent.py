# -*- coding: utf-8 -*-
"""
全球个股周线面板抓取 —— 腾讯行情接口 (无需 API key)

通道(2026-09-09 实测):
  港股: https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?param=hk00700,week,<start>,<end>,<count>,hfq
  美股: https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get?param=usAMD.OQ,week,<start>,<end>,<count>,qfq
  ❌ 无日股 (jpfqkline controller 不存在)

要点:
  1. 单段上限 640 条 -> 必须按日期分段滚动推进
  2. 🔴 港股长期 qfq(前复权) 会把早期价格压成负数 -> 收益率计算必须用 hfq(后复权)
  3. 单条串行 + 随机间隔, 避免风控
"""
import os
import random
import time

import pandas as pd
import requests

OUT_DIR = os.path.join(os.path.dirname(__file__), "data")
RAW_DIR = os.path.join(OUT_DIR, "raw_tencent")
os.makedirs(RAW_DIR, exist_ok=True)

HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
PROXIES = {"http": "http://127.0.0.1:3067", "https": "http://127.0.0.1:3067"}

HK = "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?param={sym},week,{start},{end},640,{fq}"
US = "https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get?param={sym},week,{start},{end},640,{fq}"

# 用户点名标的 (日股丰田 7203.T 待 Twelve Data, 此处留位)
TARGETS = [
    ("hk00700", "700_HK_TENCENT", "hk", "腾讯控股"),
    ("hk00883", "883_HK_CNOOC", "hk", "中国海洋石油"),
    ("hk02899", "2899_HK_ZIJIN", "hk", "紫金矿业"),
    ("usAMD.OQ", "AMD_US", "us", "超威半导体"),
]

CHUNK_DAYS = 640 * 7  # 640 周 ≈ 4480 天, 留余量用 12 年一段


def fetch_segment(sym, market, start, end, fq="hfq"):
    """拉一段; 返回 [(date, close), ...]"""
    url = (HK if market == "hk" else US).format(sym=sym, start=start, end=end, fq=fq)
    try:
        r = requests.get(url, headers=HDR, proxies=PROXIES, timeout=30)
        js = r.json()
    except Exception as e:
        print(f"    ERR {start}~{end}: {str(e)[:60]}")
        return []
    data = js.get("data")
    if not isinstance(data, dict) or not data:
        return []
    node = data.get(sym)
    if not isinstance(node, dict):
        return []
    keys = [k for k in node if "week" in k]
    if not keys:
        return []
    arr = node[keys[0]]
    out = []
    for row in arr:
        try:
            out.append((row[0], float(row[2])))  # date, close
        except (ValueError, IndexError):
            continue
    return out


def fetch_full(sym, market, name, fq="hfq", start_year=1990):
    """分段滚动拉全历史

    ⚠️ 关键: 首段无数据不能 break —— 标的上市晚(腾讯2004/紫金2003/AMD2007),
    必须继续按年份推进直到覆盖到今天。
    """
    print(f"[{name}] {sym} ({market}) fq={fq}")
    all_rows, seen = [], set()
    cur = f"{start_year}-01-01"
    this_year = pd.Timestamp.today().year
    while True:
        end_y = int(cur[:4]) + 12
        seg = fetch_segment(sym, market, cur, f"{end_y}-12-31", fq)
        new = [(d, c) for d, c in seg if d not in seen]
        for d, c in new:
            seen.add(d)
        all_rows.extend(new)
        print(f"    {cur}~{end_y}-12-31: {len(seg)} 条 (新增 {len(new)}) 累计 {len(all_rows)}")
        if seg and len(seg) >= 5:
            nxt = seg[-1][0]
            if nxt <= cur or len(all_rows) > 4000:
                break
            cur = nxt
        else:
            # 空段: 上市前 -> 继续推进年份, 直到越过今年才停
            if end_y >= this_year:
                break
            cur = f"{end_y + 1}-01-01"
        time.sleep(random.uniform(0.5, 1.4))
    s = pd.Series({d: c for d, c in sorted(all_rows)}, name=name)
    s.index = pd.to_datetime(s.index)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    if len(s):
        print(f"    => {len(s)} 周  {s.index[0].date()} ~ {s.index[-1].date()}  "
              f"{s.iloc[0]:.3f} -> {s.iloc[-1]:.3f} ({s.iloc[-1] / s.iloc[0]:.1f}x)")
    return s


def main():
    cols = {}
    for sym, tag, market, name in TARGETS:
        s = fetch_full(sym, market, name)
        if len(s):
            cols[tag] = s
            s.to_csv(os.path.join(RAW_DIR, f"{tag}.csv"), header=["close"])
        time.sleep(random.uniform(0.8, 1.8))

    if not cols:
        print("无数据")
        return
    panel = pd.DataFrame(cols).sort_index()
    out = os.path.join(OUT_DIR, "equities_weekly_adjclose.csv")
    panel.to_csv(out)
    print(f"\n面板: {out}  {panel.shape[0]} 行 x {panel.shape[1]} 列")
    print(f"区间: {panel.dropna(how='all').index[0].date()} ~ {panel.dropna(how='all').index[-1].date()}")
    print("\n各列有效起点:")
    for c in panel.columns:
        col = panel[c].dropna()
        print(f"  {c:18s} {len(col):5d} 周  {col.index[0].date()} ~ {col.index[-1].date()}")


if __name__ == "__main__":
    main()
