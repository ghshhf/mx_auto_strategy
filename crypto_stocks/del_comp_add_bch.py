"""删除 COMP + 加入 BCH (Bitcoin Cash). 可重入: 已完成的编辑自动跳过.

流程:
  1. (联网) 经本地机场代理拉 BCHUSDT 周K线, 对齐周五, 校验非空.
  2. 删 COMP / 加 BCH: crypto_adoption_v2.py / data_sources.py / sync_crypto_panel.py
     / fetch_mcaps.py / held_weeks.json / mcap_snapshot.json / 3 个 CSV 列.
  3. 重新 import 校验: COMP 不在 OFFENSE, BCH 在 OFFENSE.
"""
import json
import subprocess
import time
import datetime
from datetime import datetime as dt, timedelta, timezone

import pandas as pd

PROXY = "socks5h://127.0.0.1:1080"
SYMBOL = "BCHUSDT"
START = "2017-08-01"
FILES = [
    "data/weekly_adjclose_crypto50.csv",
    "data/weekly_adjclose_crypto50_v3.csv",
    "data/weekly_adjclose_crypto50_10y.csv",
]
BCH_SUPPLY = 19.9e6  # 流通量近似 (~19.9M)


def _friday_align(ts_ms):
    d = dt.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    friday = d - timedelta(days=(d.weekday() - 4) % 7)
    return friday.strftime("%Y-%m-%d")


def fetch_bch_weekly():
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
    # ---- 1. 拉 BCH 数据 ----
    weekly = fetch_bch_weekly()
    if not weekly:
        raise SystemExit("BCH 拉取为空, 终止 (未改动任何文件)")
    ks = sorted(weekly)
    last_price = weekly[ks[-1]]
    print(f"[+] BCH Binance周K: {len(weekly)} 周, {ks[0]} -> {ks[-1]}, 末价={last_price:.2f}")
    mcap = last_price * BCH_SUPPLY
    print(f"    估算 mcap=${mcap/1e9:.2f}B, yi={mcap/1e8:.2f}")

    # ---- 2. 删 COMP (源码) ----
    _edit_file("crypto_adoption_v2.py", [
        ("    \"DeFi\":    ['UNI', 'AAVE', 'SKY', 'COMP', 'LDO', 'JOE'],",
         "    \"DeFi\":    ['UNI', 'AAVE', 'SKY', 'LDO', 'JOE'],"),
        ("    \"DeFi借贷\": ['AAVE', 'COMP'],  # 与 DeFi 重叠, 复用",
         "    \"DeFi借贷\": ['AAVE'],  # 与 DeFi 重叠, 复用"),
        ("    'COMP': {'name': 'Compound', 'role': 'offense', 'theme': 'DeFi', 'launch': 2018},\n",
         ""),
    ])
    _edit_file("data_sources.py", [
        ("    'LDO': 'lido-dao', 'COMP': 'compound-governance-token',",
         "    'LDO': 'lido-dao',"),
        ("    'COMP': 5692, 'DASH': 131,",
         "    'DASH': 131,"),
        ("    'ARB': 11841, 'AVAX': 5805, 'BTC': 1, 'XLM': 512,",
         "    'ARB': 11841, 'AVAX': 5805, 'BCH': 1831, 'BTC': 1, 'XLM': 512,"),
    ])
    _edit_file("sync_crypto_panel.py", [
        ("    'COMP': 5692,       'DASH': 131,     'DOT': 6636,",
         "    'DASH': 131,     'DOT': 6636,"),
        ("    'BTC': 1,       'XLM': 512,",
         "    'BTC': 1, 'BCH': 1831, 'XLM': 512,"),
    ])
    _edit_file("fetch_mcaps.py", [
        ("    'COMP': 'compound-governance-token', 'DYDX': 'dydx',",
         "    'DYDX': 'dydx',"),
        ("    'LDO': 'lido-dao',",
         "    'LDO': 'lido-dao', 'BCH': 'bitcoin-cash',"),
    ])

    # ---- 3. 加 BCH (源码) ----
    _edit_file("crypto_adoption_v2.py", [
        ("    \"支付链\":  ['XLM', 'TRX', 'GRAM', 'LTC', 'XRP'],  # 2026-08-13 从L1拆分: 稳定币结算/跨境支付叙事",
         "    \"支付链\":  ['XLM', 'TRX', 'GRAM', 'LTC', 'XRP', 'BCH'],  # 2026-08-13 从L1拆分: 稳定币结算/跨境支付叙事"),
        ("    'API3': {'name': 'API3', 'role': 'offense', 'theme': '基础设施', 'launch': 2020},\n}",
         "    'API3': {'name': 'API3', 'role': 'offense', 'theme': '基础设施', 'launch': 2020},\n"
         "    'BCH': {'name': 'Bitcoin Cash', 'role': 'offense', 'theme': '支付链', 'launch': 2017},\n}"),
    ])

    # ---- 4. JSON: 删 COMP + 加 BCH (去重) ----
    for jf in ["held_weeks.json", "mcap_snapshot.json"]:
        with open(jf, "r", encoding="utf-8") as f:
            data = json.load(f)
        data = [d for d in data if d.get("sym") != "COMP"]
        if not any(d.get("sym") == "BCH" for d in data):
            if jf == "held_weeks.json":
                data.append({"sym": "BCH", "held": 0, "mcap_usd": mcap, "sector": "支付链"})
            else:
                data.append({"sym": "BCH", "mcap": mcap, "yi": mcap / 1e8, "price": last_price})
            print(f"[+] JSON {jf}: 删 COMP, 加 BCH")
        else:
            print(f"    [skip] JSON {jf}: BCH 已存在")
        with open(jf, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ---- 5. CSV: 删 COMP 列 + 加 BCH 列 (可重入) ----
    for f in FILES:
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        if "COMP" in df.columns:
            df = df.drop(columns=["COMP"])
        bch = pd.Series(index=df.index, dtype=float)
        for i, d in enumerate(df.index):
            key = d.strftime("%Y-%m-%d")
            if key in weekly:
                bch.iloc[i] = weekly[key]
        if "BCH" in df.columns:
            df = df.drop(columns=["BCH"])
        df["BCH"] = bch.values
        df.to_csv(f, index=True)
        fv = df["BCH"].first_valid_index()
        print(f"[+] CSV {f}: 删 COMP, 加 BCH 列({df.shape[1]}列), BCH首有效={fv.date() if fv else None}")

    # ---- 6. 校验 ----
    import importlib
    import sys
    if "crypto_adoption_v2" in sys.modules:
        del sys.modules["crypto_adoption_v2"]
    import crypto_adoption_v2 as ca2
    assert "COMP" not in ca2.OFFENSE_COINS, "COMP 仍在 OFFENSE!"
    assert "BCH" in ca2.OFFENSE_COINS, "BCH 未进 OFFENSE!"
    print(f"\n[OK] DEFENSE={ca2.DEFENSE_COINS}  OFFENSE n={len(ca2.OFFENSE_COINS)}  "
          f"ALL={len(ca2.ALL_COINS)}  BCH在支付链={'BCH' in ca2.THEME_COINS['支付链']}")


if __name__ == "__main__":
    main()
