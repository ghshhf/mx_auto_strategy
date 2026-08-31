# -*- coding: utf-8 -*-

# --- [relocated 2026-08-31] 目录重构引导: 等效于在 crypto_stocks/ 根目录下运行 ---
import os as _os, sys as _sys
_SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))
_d = _SCRIPT_DIR
while _os.path.basename(_d) != 'crypto_stocks' and _d != _os.path.dirname(_d):
    _d = _os.path.dirname(_d)
_CS_ROOT = _d if _os.path.basename(_d) == 'crypto_stocks' else _SCRIPT_DIR
if _CS_ROOT != _SCRIPT_DIR:
    if _CS_ROOT not in _sys.path:
        _sys.path.insert(0, _CS_ROOT)
    _os.chdir(_CS_ROOT)
# --- [relocated] 引导结束 ---
"""抓取 RAY(Raydium) 周K线并入 3 个面板 CSV.

数据源: Binance api.binance.com (与面板主源一致), 经本地机场代理 127.0.0.1:3067(http).
对齐: 周五映射(与 add_ltc.py 同口径), 面板网格严格一致.
RAY: CoinGecko id='raydium', Binance=RAYUSDT, 上线 2021-09(Solana AMM/DEX).
赛道归属: DEX (与 UNI/JUP 同主题; Solana 生态现货+永续 AMM).
"""
import json
import subprocess
import time
from datetime import datetime as dt, timedelta

import pandas as pd

PROXY = "http://127.0.0.1:3067"
SYMBOL = "RAYUSDT"
START = "2021-01-01"
FILES = [
    "data/weekly_adjclose_crypto50.csv",
    "data/weekly_adjclose_crypto50_v3.csv",
    "data/weekly_adjclose_crypto50_10y.csv",
]


def _friday_align(ts_ms):
    d = dt.utcfromtimestamp(ts_ms / 1000)
    friday = d - timedelta(days=(d.weekday() - 4) % 7)
    return friday.strftime("%Y-%m-%d")


def fetch_ray_weekly():
    start_ms = int(dt.strptime(START, "%Y-%m-%d").timestamp() * 1000)
    end_ms = None
    rows = []
    while True:
        url = (f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}"
               f"&interval=1w&limit=1000")
        url += f"&startTime={end_ms}" if end_ms else f"&startTime={start_ms}"
        r = subprocess.run(["curl", "-s", "-m", "60", "-x", PROXY, url],
                           capture_output=True, text=True)
        try:
            arr = json.loads(r.stdout)
        except Exception as e:
            print("  解析失败:", e, r.stdout[:200]); break
        if not arr:
            break
        for x in arr:
            rows.append((int(x[0]), float(x[4])))
        last_close = int(arr[-1][6])
        if last_close > int(time.time() * 1000):
            break
        end_ms = last_close + 1
        if len(arr) < 1000:
            break
        time.sleep(0.2)
    weekly = {_friday_align(ts): close for ts, close in rows}
    return weekly


def main():
    weekly = fetch_ray_weekly()
    if not weekly:
        raise SystemExit("RAY 拉取为空, 终止")
    ks = sorted(weekly)
    print(f"[+] RAY Binance周K: {len(weekly)} 周, {ks[0]} -> {ks[-1]}, 首值={weekly[ks[0]]:.4f}")
    for f in FILES:
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        ray = pd.Series(index=df.index, dtype=float)
        for i, d in enumerate(df.index):
            key = d.strftime("%Y-%m-%d")
            if key in weekly:
                ray.iloc[i] = weekly[key]
        if "RAY" in df.columns:
            df = df.drop(columns=["RAY"])
        df["RAY"] = ray.values
        fv = df["RAY"].first_valid_index()
        lv = df["RAY"].last_valid_index()
        nvalid = df["RAY"].notna().sum()
        print(f"{f}: 加 RAY 列, 共 {df.shape[1]} 列, 有效周={nvalid}, "
              f"首次有效={fv.date() if fv else None}, 末次有效={lv.date() if lv else None}, "
              f"末值={df['RAY'].iloc[-1]:.4f}")
        df.to_csv(f, index=True)


if __name__ == "__main__":
    main()
