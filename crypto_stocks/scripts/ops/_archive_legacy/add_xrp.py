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
"""加 XRP(Ripple) 到支付链赛道. Binance XRPUSDT 周K(与面板主源一致, 经代理).
XRP: CMC id=52, CoinGecko='ripple'(data_sources 已有), 支付链叙事核心(跨境结算).
"""
import io
import json
import subprocess
import time
from datetime import datetime as dt, timedelta

import pandas as pd

PROXY = "socks5h://127.0.0.1:1080"
SYMBOL = "XRPUSDT"
START = "2017-01-01"
FILES = ["data/weekly_adjclose_crypto50.csv",
         "data/weekly_adjclose_crypto50_v3.csv",
         "data/weekly_adjclose_crypto50_10y.csv"]


def _friday_align(ts_ms):
    d = dt.utcfromtimestamp(ts_ms / 1000)
    friday = d - timedelta(days=(d.weekday() - 4) % 7)
    return friday.strftime("%Y-%m-%d")


def fetch_xrp_weekly():
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
    return {_friday_align(ts): close for ts, close in rows}


def main():
    # ---- 1. 映射 + 赛道 ----
    p = 'crypto_adoption_v2.py'
    s = io.open(p, encoding='utf-8').read()
    s = s.replace('"支付链":  [\'XLM\', \'TRX\', \'GRAM\', \'LTC\'],',
                  '"支付链":  [\'XLM\', \'TRX\', \'GRAM\', \'LTC\', \'XRP\'],')
    s = s.replace("    'LTC': {'name': 'Litecoin', 'role': 'offense', 'theme': '\u652f\u4ed8\u94fe', 'launch': 2011},",
                  "    'LTC': {'name': 'Litecoin', 'role': 'offense', 'theme': '\u652f\u4ed8\u94fe', 'launch': 2011},\n"
                  "    'XRP': {'name': 'XRP', 'role': 'offense', 'theme': '\u652f\u4ed8\u94fe', 'launch': 2012},")
    io.open(p, 'w', encoding='utf-8', newline='').write(s)
    print(f"  [ok] {p}")

    p = 'data_sources.py'
    s = io.open(p, encoding='utf-8').read()
    s = s.replace("'OKB': 3897, 'ONDO': 21159, 'OP': 11840, 'INJ': 20646,",
                  "'OKB': 3897, 'ONDO': 21159, 'OP': 11840, 'INJ': 20646, 'XRP': 52,")
    io.open(p, 'w', encoding='utf-8', newline='').write(s)
    print(f"  [ok] {p}")

    p = 'sync_crypto_panel.py'
    s = io.open(p, encoding='utf-8').read()
    s = s.replace("'GRAM': 11419,   'TRX': 1958,    'UNI': 7083,     'ZEC': 1437,    'JOE': 11396,",
                  "'GRAM': 11419,   'TRX': 1958,    'UNI': 7083,     'ZEC': 1437,    'JOE': 11396,   'XRP': 52,")
    io.open(p, 'w', encoding='utf-8', newline='').write(s)
    print(f"  [ok] {p}")

    p = 'fetch_mcaps.py'
    s = io.open(p, encoding='utf-8').read()
    s = s.replace("'RENDER': 'render-token', 'RON': 'ronin',",
                  "'RENDER': 'render-token', 'RON': 'ronin', 'XRP': 'ripple',")
    io.open(p, 'w', encoding='utf-8', newline='').write(s)
    print(f"  [ok] {p}")

    # ---- 2. 拉数据并入 CSV ----
    weekly = fetch_xrp_weekly()
    if not weekly:
        raise SystemExit("XRP 拉取为空, 终止")
    ks = sorted(weekly)
    print(f"[+] XRP Binance周K: {len(weekly)} 周, {ks[0]} -> {ks[-1]}, 首值={weekly[ks[0]]:.4f}")
    for f in FILES:
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        xrp = pd.Series(index=df.index, dtype=float)
        for i, d in enumerate(df.index):
            key = d.strftime("%Y-%m-%d")
            if key in weekly:
                xrp.iloc[i] = weekly[key]
        if "XRP" in df.columns:
            df = df.drop(columns=["XRP"])
        df["XRP"] = xrp.values
        fv = df["XRP"].first_valid_index()
        print(f"{f}: 加 XRP 列, 共 {df.shape[1]} 列, 首次有效={fv.date() if fv else None}, 末值={df['XRP'].iloc[-1]:.4f}")
        df.to_csv(f, index=True)

    # ---- 3. held_weeks 加块 ----
    d = json.load(io.open('held_weeks.json', encoding='utf-8'))
    d.append({"sym": "XRP", "held": 0, "mcap_usd": None, "sector": "支付链"})
    io.open('held_weeks.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=2))
    print(f"  [ok] held_weeks.json ({len(d)} 条)")
    print("\n[done] 重跑 fetch_mcaps.py 补 XRP 市值")


if __name__ == "__main__":
    main()
