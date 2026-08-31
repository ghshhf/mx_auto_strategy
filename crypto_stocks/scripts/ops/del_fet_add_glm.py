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
"""FET -> GLM 交换: 删 FET(Fetch.ai) + 加 GLM(Golem, 用户实盘持有算力币).
GLM: CMC id=1455, CG='golem', Binance GLMUSDT 周K(2020-11 GNT迁移后).
"""
import io
import json
import subprocess
import time
from datetime import datetime as dt, timedelta

import pandas as pd

PROXY = "socks5h://127.0.0.1:1080"
SYMBOL = "GLMUSDT"
START = "2017-01-01"
FILES = ["data/weekly_adjclose_crypto50.csv",
         "data/weekly_adjclose_crypto50_v3.csv",
         "data/weekly_adjclose_crypto50_10y.csv"]


def _friday_align(ts_ms):
    d = dt.utcfromtimestamp(ts_ms / 1000)
    friday = d - timedelta(days=(d.weekday() - 4) % 7)
    return friday.strftime("%Y-%m-%d")


def fetch_glm_weekly():
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
    # ---- 1. 删 FET + 加 GLM 映射 ----
    p = 'crypto_adoption_v2.py'
    s = io.open(p, encoding='utf-8').read()
    s = s.replace('"AI+加密": [\'FET\', \'RENDER\', \'TAO\'],', '"AI+加密": [\'RENDER\', \'TAO\', \'GLM\'],')
    s = s.replace("    'FET': {'name': 'ASI / Fetch.ai', 'role': 'offense', 'theme': 'AI+加密', 'launch': 2019},\n", "")
    s = s.replace("    'RENDER': {'name': 'Render',", "    'GLM': {'name': 'Golem', 'role': 'offense', 'theme': 'AI+加密', 'launch': 2016},\n    'RENDER': {'name': 'Render',")
    io.open(p, 'w', encoding='utf-8', newline='').write(s)
    print(f"  [ok] {p}")

    p = 'data_sources.py'
    s = io.open(p, encoding='utf-8').read()
    s = s.replace("'SUI': 'sui', 'FET': 'fetch-ai', 'SKY': 'sky',", "'SUI': 'sui', 'SKY': 'sky', 'GLM': 'golem',")
    s = s.replace("'ETH': 1027, 'FET': 3773, 'FIL': 2280,", "'ETH': 1027, 'GLM': 1455, 'FIL': 2280,")
    io.open(p, 'w', encoding='utf-8', newline='').write(s)
    print(f"  [ok] {p}")

    p = 'sync_crypto_panel.py'
    s = io.open(p, encoding='utf-8').read()
    s = s.replace("'FET': 3773,     'FIL': 2280,", "'GLM': 1455,     'FIL': 2280,")
    io.open(p, 'w', encoding='utf-8', newline='').write(s)
    print(f"  [ok] {p}")

    p = 'fetch_mcaps.py'
    s = io.open(p, encoding='utf-8').read()
    s = s.replace("'SUI': 'sui', 'FET': 'fetch-ai',", "'SUI': 'sui', 'GLM': 'golem',")
    io.open(p, 'w', encoding='utf-8', newline='').write(s)
    print(f"  [ok] {p}")

    # ---- 2. JSON: 删 FET 块 + 加 GLM 块 ----
    d = json.load(io.open('held_weeks.json', encoding='utf-8'))
    d = [r for r in d if not (isinstance(r, dict) and r.get('sym') == 'FET')]
    d.append({"sym": "GLM", "held": 0, "mcap_usd": None, "sector": "AI+加密"})
    io.open('held_weeks.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=2))
    print(f"  [ok] held_weeks.json ({len(d)} 条)")

    d = json.load(io.open('mcap_snapshot.json', encoding='utf-8'))
    d = [r for r in d if not (isinstance(r, dict) and r.get('sym') == 'FET')]
    io.open('mcap_snapshot.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=2))
    print(f"  [ok] mcap_snapshot.json ({len(d)} 条, GLM待fetch)")

    # ---- 3. CSV: 删 FET 列 + 拉 GLM 并入 ----
    for p in FILES:
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        if 'FET' in df.columns:
            df = df.drop(columns=['FET'])
        df.to_csv(p, index=True)

    weekly = fetch_glm_weekly()
    if not weekly:
        raise SystemExit("GLM 拉取为空, 终止")
    ks = sorted(weekly)
    print(f"[+] GLM Binance周K: {len(weekly)} 周, {ks[0]} -> {ks[-1]}, 首值={weekly[ks[0]]:.4f}")
    for p in FILES:
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        glm = pd.Series(index=df.index, dtype=float)
        for i, d in enumerate(df.index):
            key = d.strftime("%Y-%m-%d")
            if key in weekly:
                glm.iloc[i] = weekly[key]
        df["GLM"] = glm.values
        fv = df["GLM"].first_valid_index()
        print(f"{p}: GLM列, 共{df.shape[1]}列, 首有效={fv.date() if fv else None}, 末值={df['GLM'].iloc[-1]:.4f}")
        df.to_csv(p, index=True)
    print("\n[done] 重跑 fetch_mcaps.py 补 GLM 市值")


if __name__ == "__main__":
    main()
