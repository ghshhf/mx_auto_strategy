# -*- coding: utf-8 -*-
"""
repair_panels_2026_09_18.py - 修复日线-周线审计发现的错值 (三面板同步修)
==========================================================================
背景: 2026-09-18 日线-周线对账审计 (audit_daily_vs_weekly.py) 发现 2 格:
  1) GRAM 2026-06-26: 面板 1.6 (Gate.io 补洞的跨所拼接值, 整数可疑)
                  vs Binance GRAMUSDT 周K终值 1.778 (+10.0%) —— 补洞错值.
  2) POL  2024-09-06: 面板 0.3794 vs Binance POLUSDT 周K终值 0.3887 (+2.39%)
                  —— 2026-09-10 TAIL_REFRESH 修复前的"周中快照冻结"遗留.
修复: 用 Binance **周K终值**(与面板主源同口径)覆写三面板中对应格.
只动列出的格子, 其余历史不碰.

用法 (仓库根): python markets/crypto/repair_panels_2026_09_18.py [--dry-run]
"""
import os
import sys
import csv
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import net_config  # noqa: E402

# (coin, label) -> 归因说明
FIXES = [
    ('GRAM', '2026-06-26', 'Gate.io 补洞跨所拼接错值 (+10.0%)'),
    ('POL',  '2024-09-06', '周中快照冻结遗留 (09-10 修复前写入) (+2.4%)'),
]
PANELS = ['weekly_adjclose_crypto50.csv',
          'weekly_adjclose_crypto50_v3.csv',
          'weekly_adjclose_crypto50_10y.csv']

_proxy = net_config.proxy_url()
_op = urllib.request.build_opener(
    urllib.request.ProxyHandler({'http': _proxy, 'https': _proxy}))
urllib.request.install_opener(_op)


def binance_weekly_close(sym, label):
    """取标签对应周的 Binance 周K收盘 (openTime = 标签+3天的周一 00:00 UTC)."""
    open_dt = datetime.strptime(label, "%Y-%m-%d").replace(tzinfo=timezone.utc) \
        + timedelta(days=3)
    start_ms = int(open_dt.timestamp() * 1000)
    url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1w&startTime={start_ms}&limit=1"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                               "Referer": "https://www.binance.com/"})
    for attempt in range(5):
        try:
            arr = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
            if arr and int(arr[0][0]) == start_ms:
                return float(arr[0][4])
            raise RuntimeError(f"openTime 不匹配: want {start_ms} got {arr[0][0] if arr else '空'}")
        except Exception as e:
            if attempt == 4:
                raise
            print(f"  重试{attempt+1}: {e}", file=sys.stderr)
            time.sleep(1 + attempt)


def main():
    dry = '--dry-run' in sys.argv
    for coin, label, why in FIXES:
        truth = binance_weekly_close(coin + 'USDT', label)
        print(f"[真值] Binance {coin}USDT 周K close @ {label} 周 = {truth}   ({why})")
        for fname in PANELS:
            path = os.path.join(DATA, fname)
            with open(path, newline='', encoding='utf-8-sig') as f:
                rows = list(csv.reader(f))
            if coin not in rows[0]:
                print(f"  {fname}: 无 {coin} 列, 跳过")
                continue
            ci = rows[0].index(coin)
            hit = False
            for r in rows[1:]:
                if r[0] == label:
                    old = r[ci]
                    if old == '':
                        print(f"  {fname}: {label} 格为空, 跳过")
                        break
                    dev = abs(float(old) / truth - 1)
                    print(f"  {fname}: {label} {coin} {old} -> {truth}  (偏差 {dev*100:.2f}%)")
                    if not dry:
                        r[ci] = repr(truth)
                    hit = True
                    break
            if hit and not dry:
                with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                    csv.writer(f).writerows(rows)
                print(f"    已写回 {fname}")
    if dry:
        print("[dry-run] 未落盘")


if __name__ == '__main__':
    main()
