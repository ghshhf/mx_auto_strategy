# -*- coding: utf-8 -*-
"""
refresh_daily_tail.py - 刷新日线尾部面板 (2026-09-18 固化自 _tmp 脚本)
=======================================================================
data/daily_tail_crypto50.csv = 27 币真实 UTC 日期日线 close, 覆盖"未收盘周",
与周面板(标签=周五, 有 9 天语义偏移)解耦: freshness 看这里, 回测定稿看周面板.

取数: Binance 1d (25 币) + OKX 1D (OKB/HYPE, ⚠️ UTC+8 切日: 标签=(开盘ts+8h)的UTC日期).
行为: 合并刷新 —— 既有日期行就地覆盖(拿终值), 新日期行追加; OKX 币在
其最早可得 bar 之前的格子保持空白(诚实留空, 不编造).

用法 (仓库根):
  python markets/crypto/scripts/ops/refresh_daily_tail.py            # 全量刷新
  python markets/crypto/scripts/ops/refresh_daily_tail.py --days 14  # 只刷最近14天
"""
import os
import sys
import csv
import json
import time
import argparse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))   # markets/crypto/
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..', '..', '..')))  # 仓库根
import net_config  # noqa: E402

TAIL_PATH = os.path.normpath(os.path.join(HERE, '..', '..', 'data', 'daily_tail_crypto50.csv'))

_PROXY = net_config.proxy_url()
_op = urllib.request.build_opener(
    urllib.request.ProxyHandler({'http': _PROXY, 'https': _PROXY}))
urllib.request.install_opener(_op)


def _get(url, referer, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Referer": referer})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def binance_daily(sym, start_ms):
    """-> {utc_date: close}; 逐页重试, 中断抛 RuntimeError."""
    out, end_ms = {}, None
    while True:
        url = (f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1d&limit=1000"
               + (f"&startTime={end_ms}" if end_ms else f"&startTime={start_ms}"))
        arr, last_err = None, None
        for attempt in range(5):
            try:
                arr = json.loads(_get(url, "https://www.binance.com/"))
                break
            except Exception as e:
                last_err = e
                print(f"    [{sym}] 第{attempt+1}次重试: {e}", file=sys.stderr)
                time.sleep(1 + attempt)
        if arr is None:
            raise RuntimeError(f"[Binance] {sym} 日线翻页中断: {last_err}")
        if not arr:
            break
        for x in arr:
            d = datetime.fromtimestamp(int(x[0]) / 1000, timezone.utc).strftime("%Y-%m-%d")
            out[d] = float(x[4])
        end_ms = int(arr[-1][6]) + 1
        if end_ms > int(time.time() * 1000):
            break
        time.sleep(0.15)
    return out


def okx_daily(inst, start_ms):
    """-> {utc_date: close}; 标签=(开盘ts+8h)的UTC日期 (OKX 日K按 UTC+8 切日)."""
    out = {}
    for ep in ("market/history-candles", "market/candles"):
        after = ""
        for _ in range(400):
            url = (f"https://www.okx.com/api/v5/{ep}?instId={inst}&bar=1D&limit=100"
                   + (f"&after={after}" if after else ""))
            arr = json.loads(_get(url, "https://www.okx.com/")).get("data", [])
            if not arr:
                break
            oldest = min(int(x[0]) for x in arr)
            for x in arr:
                ts = int(x[0])
                if ts < start_ms:
                    continue
                d = datetime.fromtimestamp(ts / 1000 + 8 * 3600, timezone.utc).strftime("%Y-%m-%d")
                out[d] = float(x[4])
            if oldest <= start_ms:
                break
            after = str(oldest - 1)
            time.sleep(0.12)
    return out


def main():
    ap = argparse.ArgumentParser(description="刷新日线尾部面板")
    ap.add_argument('--days', type=int, default=0, help='只保留最近 N 天 (0=从文件首日全刷)')
    args = ap.parse_args()

    if not os.path.exists(TAIL_PATH):
        print(f"[错误] 尾部文件不存在: {TAIL_PATH}", file=sys.stderr)
        return 2
    with open(TAIL_PATH, newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    header, data = rows[0], rows[1:]
    coins = header[1:]
    first_date = data[0][0]
    if args.days > 0:
        base = datetime.strptime(data[-1][0], "%Y-%m-%d") - timedelta(days=args.days)
    else:
        base = datetime.strptime(first_date, "%Y-%m-%d")
    start_dt = base.replace(tzinfo=timezone.utc)
    start_ms = int(start_dt.timestamp() * 1000)
    print(f"[tail] {os.path.basename(TAIL_PATH)}: {len(coins)} 币, "
          f"{len(data)} 行 ({first_date}..{data[-1][0]}), 刷新起点 {start_dt.date()}")

    fetched = {}
    for c in coins:
        try:
            if c in ('OKB', 'HYPE'):
                fetched[c] = okx_daily(c + "-USDT", start_ms)
            else:
                fetched[c] = binance_daily(c + "USDT", start_ms)
            print(f"  {c:<8} {len(fetched[c]):>3} 天", flush=True)
        except RuntimeError as e:
            print(f"  [警告] {c}: {e} (该币本段留旧值)", file=sys.stderr)

    # ---- 合并: 覆盖既有行 + 追加新日期 ----
    by_date = {r[0]: r for r in data}
    all_dates = sorted(set(by_date) | {d for m in fetched.values() for d in m})
    ci = {c: header.index(c) for c in coins}
    updated = appended = 0
    for d in all_dates:
        if d not in by_date:
            by_date[d] = [d] + [''] * (len(header) - 1)
            appended += 1
        row = by_date[d]
        for c in coins:
            v = fetched.get(c, {}).get(d)
            if v is not None:
                if row[ci[c]] != '' and str(row[ci[c]]) != str(v):
                    updated += 1
                row[ci[c]] = v

    out_rows = [by_date[d] for d in all_dates]
    with open(TAIL_PATH, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(out_rows)
    last = out_rows[-1]
    missing = [header[i] for i in range(1, len(header)) if last[i] == '']
    print(f"[ok] 共 {len(out_rows)} 行 ({out_rows[0][0]}..{last[0]}), "
          f"覆盖 {updated} 格, 追加 {appended} 行, 末行缺失列: {missing or '无'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
