"""抓取 27 币「全历史日度 价格 + 市值 + 流通量」——CMC 免费数据源，两种端点组合。

为什么用 CMC
------------
1) 官方 pro-api（用 CMC_API_KEY，免费档）/v1/cryptocurrency/map
   → 一次拿到 27 币的 CMC id（免费档允许）。
2) 网页版内部 data-api（无需 key）
   /data-api/v3/cryptocurrency/detail/chart?id=<id>&range=ALL
   → 返回**全历史**日度点，每点 c = [price, volume, market_cap]。
   因此  流通量_t = market_cap_t / price_t  ——  这条序列天然包含
   「协议发行 + 归属解锁 − 销毁」，是**实测净增发**。

对比 CoinGecko
-------------
CG Demo 档 market_chart 只允许 days<=365；CMC data-api 的 range=ALL
可以回溯到币种上线日 → 能算 1y/2y/3y/5y 多个窗口的真实净增发率。

落盘
----
markets/crypto/data/cmc_history/<SYM>.json   （已存在则跳过，可重复运行）
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from net_config import proxy_opener  # noqa: E402

OUT = ROOT / "markets" / "crypto" / "data" / "cmc_history"
OUT.mkdir(parents=True, exist_ok=True)

SYMS = ["BTC", "ETH", "OKB", "AAVE", "ADA", "APT", "AVAX", "DOT", "FIL", "LINK",
        "POL", "RENDER", "SOL", "GRAM", "TRX", "UNI", "ZEC", "BNB", "XLM", "LTC",
        "XRP", "GLM", "BCH", "RAY", "PENDLE", "ETHFI", "HYPE"]

# 本地面板符号 -> CMC 官方 symbol（CMC 已把 Toncoin 改名为 Gram，故 GRAM 直接用 GRAM）
CMC_SYMBOL = {s: s for s in SYMS}

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"),
    "Accept": "application/json",
}


def get(url: str, headers: dict | None = None, tries: int = 4) -> dict:
    op = proxy_opener()
    hdr = dict(UA)
    if headers:
        hdr.update(headers)
    wait = 6.0
    for k in range(tries):
        try:
            return json.load(op.open(urllib.request.Request(url, headers=hdr), timeout=90))
        except Exception as e:                                    # noqa: BLE001
            code = getattr(e, "code", None)
            if code in (429, 503, 500) and k < tries - 1:
                print(f"      {code} backoff {wait:.0f}s")
                time.sleep(wait)
                wait *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def cmc_ids() -> dict:
    """取币的 CMC id。

    坑：/map 对同一 symbol 会返回多个条目（同名克隆币/已下架代币），
    例如 BTC 对应的克隆 id=39556、真 BTC 是 id=1。必须按 rank 取正主：
    只保留 rank>0 的条目并取最小 rank。取不到的 symbol 明确报出。
    """
    key = os.environ.get("CMC_API_KEY")
    out: dict = {}
    for cmc_sym, local_sym in CMC_SYMBOL.items():
        url = ("https://pro-api.coinmarketcap.com/v1/cryptocurrency/map"
               f"?symbol={cmc_sym}&limit=5000")
        d = get(url, {"X-CMC_PRO_API_KEY": key or ""})
        cands = [r for r in d.get("data", []) if r.get("rank", 0) and r["rank"] > 0]
        if not cands:
            print(f"  !! {local_sym}({cmc_sym}) 无 rank>0 条目，跳过")
            continue
        best = min(cands, key=lambda r: r["rank"])
        out[local_sym] = best["id"]
        if len(cands) > 1:
            print(f"  {local_sym:7s} 候选 {len(cands)} 个 -> 取 rank={best['rank']} id={best['id']}")
        time.sleep(0.4)
    return out


def main() -> None:
    delay = 2.5
    if "--delay" in sys.argv:
        delay = float(sys.argv[sys.argv.index("--delay") + 1])

    idf = ROOT / "markets" / "crypto" / "data" / "cmc_ids.json"
    if idf.exists() and "--refresh-ids" not in sys.argv:
        ids = json.loads(idf.read_text(encoding="utf-8"))
        print("id 映射（缓存）:", len(ids), "币（--refresh-ids 可强制重取）")
    else:
        ids = cmc_ids()
        idf.write_text(json.dumps(ids, indent=1), encoding="utf-8")
        print("id 映射（新取）:", len(ids), "币")
    missing = [s for s in SYMS if s not in ids]
    if missing:
        print("!! 未取到 id:", missing)

    # 价格交叉校验基准：CoinGecko 快照当前价（用于自动识别 id 映射错误）
    ref: dict = {}
    snap = ROOT / "markets" / "crypto" / "out" / "cg_supply_2026-09-12.json"
    if snap.exists():
        for s, v in json.loads(snap.read_text(encoding="utf-8")).items():
            ref[s] = v.get("px")

    todo = [(s, ids[s]) for s in SYMS if s in ids and not (OUT / f"{s}.json").exists()]
    print(f"待抓取 {len(todo)} / {len(SYMS)} 币，间隔 {delay}s")
    ok = fail = 0
    for n, (sym, cid) in enumerate(todo, 1):
        try:
            d = get("https://api.coinmarketcap.com/data-api/v3/cryptocurrency/"
                    f"detail/chart?id={cid}&range=ALL")
            raw_pts = d["data"]["points"]
            # 只保留标准 3 元组 c=[price, volume, market_cap]；克隆币/异常点会被剔除
            pts = {k: v["c"] for k, v in raw_pts.items()
                   if isinstance(v, dict) and isinstance(v.get("c"), list) and len(v["c"]) == 3}
            if len(pts) < 30:
                raise ValueError(f"有效点仅 {len(pts)}")
            ks = sorted(pts, key=int)
            first, last = pts[ks[0]], pts[ks[-1]]
            px_last = last[0]
            dev = abs(px_last / ref[sym] - 1) * 100 if ref.get(sym) else float("nan")
            rec = {"sym": sym, "id": cid, "points": pts,
                   "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
            if dev > 25:
                print(f"  [{n:2d}/{len(todo)}] {sym:7s} id={cid} 价格偏差 {dev:.0f}% "
                      f"(cmc {px_last:.4f} vs CG {ref[sym]:.4f}) → id 可能取错，不落盘")
                fail += 1
            else:
                (OUT / f"{sym}.json").write_text(json.dumps(rec), encoding="utf-8")
                print(f"  [{n:2d}/{len(todo)}] {sym:7s} id={cid:6d} n={len(pts):5d} "
                      f"{time.strftime('%Y-%m-%d', time.gmtime(int(ks[0])))} -> "
                      f"{time.strftime('%Y-%m-%d', time.gmtime(int(ks[-1])))}  "
                      f"supply {first[2] / first[0]:>15,.0f} -> {last[2] / last[0]:>15,.0f}"
                      f"  对账偏差 {dev:4.0f}%")
                ok += 1
        except Exception as e:                                     # noqa: BLE001
            print(f"  [{n:2d}/{len(todo)}] {sym:7s} FAIL {type(e).__name__} {str(e)[:90]}")
            fail += 1
        if n < len(todo):
            time.sleep(delay)
    print(f"\n完成: ok={ok} fail={fail}")


if __name__ == "__main__":
    main()
