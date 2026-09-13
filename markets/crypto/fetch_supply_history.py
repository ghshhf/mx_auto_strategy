"""抓取 27 币「真实流通量历史」——用 CoinGecko market_chart 的日度市值 / 日度价格。

原理
----
CoinGecko 的 market_chart 同时返回 prices 与 market_caps（均按流通量口径）。
    流通量_t = market_cap_t / price_t
这天然包含「协议发行 + 归属解锁 − 销毁」，因此得到的是**实测净增发**，
不依赖任何排放计划推测。

档位约束
--------
CG Demo 档 `days=max` / `market_chart/range` 会报 10012（超范围）；
`days=365&interval=daily` 可用 → 恰好覆盖过去 12 个月，正好是我们要的窗口。

限速
----
Demo 档约 30 req/min。27 币 → 每次请求间隔 2.6s，遇 429 指数退避重试。
结果按币落盘到 data/supply_history/<sym>.json，已存在则跳过（可重复运行）。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from net_config import proxy_opener  # noqa: E402

OUT = ROOT / "markets" / "crypto" / "data" / "supply_history"
OUT.mkdir(parents=True, exist_ok=True)

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"),
    "Accept": "application/json",
}

# 本地面板符号 -> CoinGecko id
IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "OKB": "okb", "AAVE": "aave",
    "ADA": "cardano", "APT": "aptos", "AVAX": "avalanche-2", "DOT": "polkadot",
    "FIL": "filecoin", "LINK": "chainlink", "POL": "polygon-ecosystem-token",
    "RENDER": "render-token", "SOL": "solana", "GRAM": "the-open-network",
    "TRX": "tron", "UNI": "uniswap", "ZEC": "zcash", "BNB": "binancecoin",
    "XLM": "stellar", "LTC": "litecoin", "XRP": "ripple", "GLM": "golem",
    "BCH": "bitcoin-cash", "RAY": "raydium", "PENDLE": "pendle",
    "ETHFI": "ether-fi", "HYPE": "hyperliquid",
}


def fetch(coin_id: str, days: int = 365, tries: int = 4) -> dict:
    url = (f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
           f"?vs_currency=usd&days={days}&interval=daily")
    op = proxy_opener()
    wait = 8.0
    for k in range(tries):
        try:
            return json.load(op.open(urllib.request.Request(url, headers=UA), timeout=70))
        except Exception as e:                                    # noqa: BLE001
            code = getattr(e, "code", None)
            if code in (429, 503) and k < tries - 1:
                print(f"      rate-limited ({code}), backoff {wait:.0f}s")
                time.sleep(wait)
                wait *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def main() -> None:
    # --delay N: 请求间隔秒数（默认 2.6；重试撞限速的币时调大，如 --delay 12）
    delay = 2.6
    if "--delay" in sys.argv:
        delay = float(sys.argv[sys.argv.index("--delay") + 1])
    todo = [(s, i) for s, i in IDS.items() if not (OUT / f"{s}.json").exists()]
    print(f"待抓取 {len(todo)} / {len(IDS)} 币（已有缓存则跳过），间隔 {delay}s")
    ok = fail = 0
    for n, (sym, cid) in enumerate(todo, 1):
        try:
            d = fetch(cid)
            rec = {
                "sym": sym, "id": cid,
                "prices": d["prices"], "market_caps": d["market_caps"],
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            (OUT / f"{sym}.json").write_text(json.dumps(rec), encoding="utf-8")
            s0 = d["market_caps"][0][1] / d["prices"][0][1]
            s1 = d["market_caps"][-1][1] / d["prices"][-1][1]
            print(f"  [{n:2d}/{len(todo)}] {sym:7s} n={len(d['prices']):3d}  "
                  f"supply {s0:>14,.0f} -> {s1:>14,.0f}  ({(s1/s0-1)*100:+6.2f}%)")
            ok += 1
        except Exception as e:                                     # noqa: BLE001
            print(f"  [{n:2d}/{len(todo)}] {sym:7s} FAIL {type(e).__name__} {str(e)[:90]}")
            fail += 1
        if n < len(todo):
            time.sleep(delay)
    print(f"\n完成: ok={ok} fail={fail}  缓存目录 {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
