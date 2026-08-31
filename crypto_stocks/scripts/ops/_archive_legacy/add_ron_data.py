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
"""抓取 RON(Ronin) 周K线并入 3 个面板 CSV.
数据源: OKX history-candles (Binance 现货/合约均已下架 RONUSDT).
对齐: 周五映射(与 Binance 周K同口径), 面板网格严格一致.
RON: CMC id=14101, CoinGecko id='ronin', OKX=RON-USDT.
赛道归属: GameFi (Ronin 游戏链, Sky Mavis 自营 Axie/Pixels).
"""
import json
import subprocess
import time
from datetime import datetime as dt, timedelta

import pandas as pd

PROXY = "socks5h://127.0.0.1:1080"
SYMBOL = "RON-USDT"
FILES = [
    "data/weekly_adjclose_crypto50.csv",
    "data/weekly_adjclose_crypto50_v3.csv",
    "data/weekly_adjclose_crypto50_10y.csv",
]


def _friday_align(ts_ms):
    d = dt.utcfromtimestamp(ts_ms / 1000)
    friday = d - timedelta(days=(d.weekday() - 4) % 7)
    return friday.strftime("%Y-%m-%d")


def fetch_ron_weekly():
    rows = {}
    after = None
    for page in range(12):
        url = ("https://www.okx.com/api/v5/market/history-candles"
               f"?instId={SYMBOL}&bar=1W&limit=100")
        if after:
            url += f"&after={after}"
        r = subprocess.run(["curl", "-s", "-m", "40", "-x", PROXY, url],
                           capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
        except Exception as e:
            print("  解析失败:", e, r.stdout[:200]); break
        if d.get("code") != "0" or not d.get("data"):
            print("  API 异常:", d.get("msg"), "page", page); break
        data = d["data"]  # 新→旧排序
        if not data:
            break
        for x in data:  # [ts, o, h, l, c, vol, ...]
            ts = int(x[0])
            close = float(x[4])
            rows[_friday_align(ts)] = close
        oldest = data[-1][0]
        # OKX after 分页: 传本页最旧时间戳, 再往前
        if len(data) < 100 or after == oldest:
            break
        after = oldest
        time.sleep(0.3)
    return rows


def main():
    weekly = fetch_ron_weekly()
    if not weekly:
        raise SystemExit("RON 拉取为空, 终止")
    ks = sorted(weekly)
    print(f"[+] RON OKX周K: {len(weekly)} 周, {ks[0]} -> {ks[-1]}, 首值={weekly[ks[0]]:.4f}")
    for f in FILES:
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        ron = pd.Series(index=df.index, dtype=float)
        for i, d in enumerate(df.index):
            key = d.strftime("%Y-%m-%d")
            if key in weekly:
                ron.iloc[i] = weekly[key]
        if "RON" in df.columns:
            df = df.drop(columns=["RON"])
        df["RON"] = ron.values
        fv = df["RON"].first_valid_index()
        print(f"{f}: 加 RON 列, 共 {df.shape[1]} 列, 首次有效={fv.date() if fv else None}, "
              f"末值={df['RON'].iloc[-1]:.4f}")
        df.to_csv(f, index=True)


if __name__ == "__main__":
    main()
