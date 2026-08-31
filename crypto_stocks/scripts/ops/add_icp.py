
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
"""加入 ICP (Internet Computer, Dfinity 的 L1 公链). 可重入: 已完成的编辑自动跳过.

流程:
  1. (联网) 经本地机场代理拉 ICPUSDT 周K线, 对齐周五, 校验非空.
  2. 加 ICP: crypto_adoption_v2.py (L1公链 THEME + COIN_META) / data_sources.py
     / sync_crypto_panel.py / fetch_mcaps.py / held_weeks.json / mcap_snapshot.json / 3 个 CSV 列.
  3. 重新 import 校验: ICP 在 OFFENSE, 进攻数 >= 38.
"""
import json
import subprocess
import time
import datetime
from datetime import datetime as dt, timedelta, timezone

import pandas as pd

PROXY = "socks5h://127.0.0.1:1080"
SYMBOL = "ICPUSDT"
START = "2020-01-01"
FILES = [
    "data/weekly_adjclose_crypto50.csv",
    "data/weekly_adjclose_crypto50_v3.csv",
    "data/weekly_adjclose_crypto50_10y.csv",
]
ICP_SUPPLY = 5.2e8  # 流通量近似 (~5.2亿, 2026-08 NNS 解锁持续释放中)


def _friday_align(ts_ms):
    d = dt.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    friday = d - timedelta(days=(d.weekday() - 4) % 7)
    return friday.strftime("%Y-%m-%d")


def fetch_icp_weekly():
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
            print("  解析失败:", e, r.stdout[:200])
            break
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


def _edit_file(path, repls):
    with open(path, "r", encoding="utf-8") as f:
        s = f.read()
    changed = False
    for old, new in repls:
        if old in s:
            s = s.replace(old, new, 1)
            changed = True
        else:
            print(f"    [skip] 已无匹配: {path} :: {old!r}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)
    print(f"[+] 编辑 {path}" + ("" if changed else " (无变更)"))


def main():
    # ---- 1. 拉 ICP 数据 ----
    weekly = fetch_icp_weekly()
    if not weekly:
        raise SystemExit("ICP 拉取为空, 终止 (未改动任何文件)")
    ks = sorted(weekly)
    last_price = weekly[ks[-1]]
    print(f"[+] ICP Binance周K: {len(weekly)} 周, {ks[0]} -> {ks[-1]}, 末价={last_price:.2f}")
    mcap = last_price * ICP_SUPPLY
    print(f"    估算 mcap=${mcap/1e9:.2f}B, yi={mcap/1e8:.2f}")

    # ---- 2. 源码 ----
    _edit_file("crypto_adoption_v2.py", [
        ("    \"L1公链\":  ['SOL', 'ADA', 'AVAX', 'INJ', 'DOT', 'NEAR', 'APT'],",
         "    \"L1公链\":  ['SOL', 'ADA', 'AVAX', 'INJ', 'DOT', 'NEAR', 'APT', 'ICP'],"),
        ("    'BCH': {'name': 'Bitcoin Cash', 'role': 'offense', 'theme': '支付链', 'launch': 2017},\n}",
         "    'BCH': {'name': 'Bitcoin Cash', 'role': 'offense', 'theme': '支付链', 'launch': 2017},\n"
         "    'ICP': {'name': 'Internet Computer', 'role': 'offense', 'theme': 'L1公链', 'launch': 2021},\n}"),
    ])
    _edit_file("data_sources.py", [
        ("    'CFG': 'centrifuge',",
         "    'CFG': 'centrifuge', 'ICP': 'internet-computer',"),
        ("    'DOT': 6636, 'DYDX': 28324,",
         "    'DOT': 6636, 'DYDX': 28324, 'ICP': 8916,"),
    ])
    _edit_file("sync_crypto_panel.py", [
        ("    'DOT': 6636,",
         "    'DOT': 6636,    'ICP': 8916,"),
    ])
    _edit_file("fetch_mcaps.py", [
        ("    'XLM': 'stellar', 'LTC': 'litecoin',",
         "    'XLM': 'stellar', 'LTC': 'litecoin', 'ICP': 'internet-computer',"),
    ])

    # ---- 3. JSON: 加 ICP 条目 (去重) ----
    for jf in ["held_weeks.json", "mcap_snapshot.json"]:
        with open(jf, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not any(d.get("sym") == "ICP" for d in data):
            if jf == "held_weeks.json":
                data.append({"sym": "ICP", "held": 0, "mcap_usd": mcap, "sector": "L1公链"})
            else:
                data.append({"sym": "ICP", "mcap": mcap, "yi": mcap / 1e8, "price": last_price})
            print(f"[+] JSON {jf}: 加 ICP")
        else:
            print(f"    [skip] JSON {jf}: ICP 已存在")
        with open(jf, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ---- 4. CSV: 加 ICP 列 (可重入) ----
    for f in FILES:
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        icp = pd.Series(index=df.index, dtype=float)
        for i, d in enumerate(df.index):
            key = d.strftime("%Y-%m-%d")
            if key in weekly:
                icp.iloc[i] = weekly[key]
        if "ICP" in df.columns:
            df = df.drop(columns=["ICP"])
        df["ICP"] = icp.values
        df.to_csv(f, index=True)
        fv = df["ICP"].first_valid_index()
        print(f"[+] CSV {f}: 加 ICP 列({df.shape[1]}列), ICP首有效={fv.date() if fv else None}")

    # ---- 5. 校验 ----
    import sys
    if "crypto_adoption_v2" in sys.modules:
        del sys.modules["crypto_adoption_v2"]
    import crypto_adoption_v2 as ca2
    assert "ICP" in ca2.OFFENSE_COINS, "ICP 未进 OFFENSE!"
    assert len(ca2.OFFENSE_COINS) >= 38, f"断言失败: OFFENSE n={len(ca2.OFFENSE_COINS)}"
    print(f"\n[OK] DEFENSE={ca2.DEFENSE_COINS}  OFFENSE n={len(ca2.OFFENSE_COINS)}  "
          f"ALL={len(ca2.ALL_COINS)}  ICP在L1={'ICP' in ca2.THEME_COINS['L1公链']}")


if __name__ == "__main__":
    main()
