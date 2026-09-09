# -*- coding: utf-8 -*-
"""
Twelve Data 全球个股抓取 (需 API key, 存于 keys.local.json)

补充腾讯行情接口覆盖不到的市场 —— 主要是日股。
免费档: 800 credits/天, 8/分钟, 20+ 年历史, 70+ 交易所
API:  https://api.twelvedata.com/time_series?symbol=SYM&exchange=EXCH&interval=1week&outputsize=5000&apikey=KEY
      搜索: /symbol_search?symbol=xxx   交易所列表: /exchanges
要点: 日本股票 symbol=7203 + exchange=JPX(mic XJPX); 港股 0700 + exchange=HKEX; 美股直接 AMD
"""
import json
import os
import time

import pandas as pd
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data")
RAW_DIR = os.path.join(OUT_DIR, "raw_twelvedata")
os.makedirs(RAW_DIR, exist_ok=True)

KEY = json.load(open(os.path.join(HERE, "keys.local.json")))["twelvedata"]["key"]
BASE = "https://api.twelvedata.com/time_series?"

TARGETS = [
    ("7203", "JPX", "7203_T_TOYOTA", "丰田汽车"),
]


def fetch(symbol, exchange, interval="1week", outputsize=5000):
    params = {
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": KEY,
        "order": "ASC",
    }
    url = BASE + urllib.parse.urlencode(params) if False else BASE + "&".join(
        f"{k}={v}" for k, v in params.items()
    )
    with urllib.request.urlopen(url, timeout=40) as r:
        d = json.load(r)
    if d.get("status") == "error" or "values" not in d:
        raise RuntimeError(str(d)[:200])
    return d


def main():
    frames = {}
    for sym, exch, tag, name in TARGETS:
        print(f"[{name}] {sym} @{exch}")
        try:
            d = fetch(sym, exch)
        except Exception as e:
            print(f"    ERR {str(e)[:150]}")
            continue
        df = pd.DataFrame(d["values"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        s = pd.Series(df["close"].values, index=pd.to_datetime(df["datetime"]), name=tag)
        s = s[~s.index.duplicated(keep="last")].sort_index()
        print(f"    {len(s)} 周  {s.index[0].date()} ~ {s.index[-1].date()}  "
              f"{s.iloc[0]:.2f} -> {s.iloc[-1]:.2f} ({s.iloc[-1] / s.iloc[0]:.1f}x)  "
              f"货币={d.get('meta', {}).get('currency')}")
        s.to_csv(os.path.join(RAW_DIR, f"{tag}.csv"), header=["close"])
        frames[tag] = s
        time.sleep(8)  # 免费档 8 credits/分钟

    if not frames:
        print("无数据")
        return

    # 合并进主面板
    panel_path = os.path.join(OUT_DIR, "equities_weekly_adjclose.csv")
    if os.path.exists(panel_path):
        panel = pd.read_csv(panel_path, index_col=0, parse_dates=True)
    else:
        panel = pd.DataFrame()
    for tag, s in frames.items():
        panel[tag] = s
    panel = panel[~panel.index.duplicated()].sort_index()
    panel.to_csv(panel_path)
    print(f"\n面板更新: {panel_path}  {panel.shape[0]} 行 x {panel.shape[1]} 列")
    for c in panel.columns:
        col = panel[c].dropna()
        if len(col):
            print(f"  {c:18s} {len(col):5d} 周  {col.index[0].date()} ~ {col.index[-1].date()}")


if __name__ == "__main__":
    main()
