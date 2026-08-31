
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
"""抓取 JOE(Trader Joe) 周K线并入 3 个面板 CSV.

数据源: Binance api.binance.com (与面板主源一致), 经本地机场代理 127.0.0.1:1080.
对齐: 复用 crypto_hist_data.rows_to_weekly_close 的周五映射, 保证与面板网格严格一致.
JOE CMC id=11396, CoinGecko id='joe', Binance=JOEUSDT, OKX=JOE-USDT.
赛道归属: DeFi + DEX (与 UNI/CRV/1INCH 同处理).
"""
import json
import subprocess
import os
import time
import datetime
from datetime import datetime as dt, timedelta

import pandas as pd

PROXY = "socks5h://127.0.0.1:1080"
SYMBOL = "JOEUSDT"
START = "2020-01-01"
FILES = [
    "data/weekly_adjclose_crypto50.csv",
    "data/weekly_adjclose_crypto50_v3.csv",
    "data/weekly_adjclose_crypto50_10y.csv",
]


def _friday_align(ts_ms):
    d = dt.utcfromtimestamp(ts_ms / 1000)
    friday = d - timedelta(days=(d.weekday() - 4) % 7)
    return friday.strftime("%Y-%m-%d")


def fetch_joe_weekly():
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
    weekly = fetch_joe_weekly()
    if not weekly:
        raise SystemExit("JOE 拉取为空, 终止")
    ks = sorted(weekly)
    print(f"[+] JOE Binance周K: {len(weekly)} 周, {ks[0]} -> {ks[-1]}, 首值={weekly[ks[0]]:.4f}")
    for f in FILES:
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        joe = pd.Series(index=df.index, dtype=float)
        for i, d in enumerate(df.index):
            key = d.strftime("%Y-%m-%d")
            if key in weekly:
                joe.iloc[i] = weekly[key]
        if "JOE" in df.columns:
            df = df.drop(columns=["JOE"])
        df["JOE"] = joe.values
        fv = df["JOE"].first_valid_index()
        print(f"{f}: 加 JOE 列, 共 {df.shape[1]} 列, 首次有效={fv.date() if fv else None}")
        df.to_csv(f, index=True)
        with open(f, "r", encoding="utf-8-sig") as fh:
            print("   末行:", fh.read().strip().splitlines()[-1][:90])


if __name__ == "__main__":
    main()
