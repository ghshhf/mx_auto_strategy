# -*- coding: utf-8 -*-
"""用 CoinGecko 官方 API 拉当前池子每币官方分类(慢速+429重试)。
只拉面板内的币; 间隔6s; 429 等60s重试最多3次 → 防免费层限流。
"""
import csv
import json
import subprocess
import sys
import time

PROXY = "socks5h://127.0.0.1:1080"
PANEL = "data/weekly_adjclose_crypto50.csv"
OUT = "crypto_pool_cg_categories.json"

sys.path.insert(0, '.')
import data_sources as ds  # noqa: E402


def cg_coin(id_, tries=3):
    url = (f"https://api.coingecko.com/api/v3/coins/{id_}"
           f"?localization=false&tickers=false&market_data=false"
           f"&community_data=false&developer_data=false&sparkline=false")
    for attempt in range(tries):
        r = subprocess.run(["curl", "-s", "-m", "30", "-x", PROXY,
                            "-w", "\n%{http_code}", url],
                           capture_output=True, text=True)
        body = r.stdout
        code = body.rsplit("\n", 1)[-1].strip() if "\n" in body else ""
        data = body.rsplit("\n", 1)[0] if "\n" in body else body
        if code == "429":
            print(f"    429, 等60s重试({attempt+1}/{tries})...", file=sys.stderr)
            time.sleep(60)
            continue
        try:
            return json.loads(data)
        except Exception:
            return None
    return None


def main():
    with open(PANEL, encoding="utf-8-sig") as f:
        hdr = next(csv.reader(f))
    coins = [c for c in hdr if c and c.lower() != "date"]
    result, fails = {}, []
    print(f"[*] 池内 {len(coins)} 币", file=sys.stderr)
    for sym in coins:
        cgid = ds.COINGECKO_IDS.get(sym)
        if not cgid:
            fails.append(sym)
            result[sym] = ["(无CG映射)"]
            print(f"{sym:<5} 无CG映射")
            continue
        d = cg_coin(cgid)
        if not d or 'categories' not in d:
            fails.append(sym)
            result[sym] = []
            print(f"{sym:<5} FAIL")
        else:
            cats = d.get('categories', [])
            result[sym] = cats
            print(f"{sym:<5} ({len(cats)}): " + " | ".join(cats[:8]))
        time.sleep(6)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'generated': time.strftime('%Y-%m-%d %H:%M'),
                   'pool': 'current %d coins' % len(coins),
                   'result': result, 'fails': fails},
                  f, ensure_ascii=False, indent=2)
    print(f"\n[done] {len(coins)} 币, 失败 {len(fails)}: {fails} -> {OUT}", file=sys.stderr)


if __name__ == '__main__':
    main()
