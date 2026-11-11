# -*- coding: utf-8 -*-
"""
audit_daily_vs_weekly.py - 日线->周线 对账审计 (数据闸门, 2026-09-18 建立)
============================================================================
动机: 面板周K直接取自交易所, 一旦某格有错(跨所补洞/迁移期/快照冻结),
没有日线对照就永远发现不了. 实跑抓出 GRAM 2026-06-26 错值 +10%
(Gate.io 补洞的跨所拼接值), 已在面板躺 12 周 —— 本脚本把这类错误变成
每周可复检的闸门.

做法:
  1. 拉全部币的**日线** (Binance 1d 为主源; OKB/HYPE 等非 Binance 现货走 OKX 1D,
     ⚠️ OKX 日K按 UTC+8 切日, 标签 = (开盘ts+8h) 的 UTC 日期).
  2. 按面板同约定聚合成周线 (标签 = 周一 openTime 往前 3 天的周五;
     周值 = 该 Mon..Sun 窗口内最后一个日线收盘).
  3. 与面板逐格对账 (只对已收盘周; 未收盘周快照对快照不判错), 报告
     偏差 > 阈值 的格子 + 结构性发现(缺周/标签错位).
  4. 日线落缓存 data/daily_cache_crypto50.csv, 重跑可用 --offline 免网.

退出码: 发现偏差 > 阈值 => 1 (可接 CI/自动化); 干净 => 0.

用法 (仓库根或本目录):
  python markets/crypto/audit_daily_vs_weekly.py                # 全量在线审计 + 写缓存
  python markets/crypto/audit_daily_vs_weekly.py --offline      # 用缓存对账 (免网)
  python markets/crypto/audit_daily_vs_weekly.py --thresh 0.001 # 更严阈值
"""
import os
import sys
import csv
import json
import time
import argparse
import urllib.request
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
PANEL_DEFAULT = os.path.join(DATA, 'weekly_adjclose_crypto50.csv')
CACHE_DEFAULT = os.path.join(DATA, 'daily_cache_crypto50.csv')

sys.path.insert(0, os.path.dirname(HERE))          # markets/
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # 仓库根, 供 net_config
import net_config  # noqa: E402

_PROXY = net_config.proxy_url()
_op = urllib.request.build_opener(
    urllib.request.ProxyHandler({'http': _PROXY, 'https': _PROXY}))
urllib.request.install_opener(_op)

# 不在 Binance 现货的币 -> OKX (日K, UTC+8 切日)
OKX_ONLY_COINS = {'OKB', 'HYPE'}
START_DEFAULT = '2017-08-01'   # Binance 现货起点; 更早的面板行属 CMC/Gate 补洞盲区

# ---- 盲区段 (<2017-08-01) 独立验证 (2026-09-18) ----
# 面板 2017-08 前只有 BTC/ETH 有值, 来源 = **标签周五的日收盘** (CMC 兜底口径,
# 见 sync_crypto_panel.fetch_cmc_weekly 注释), 而币安期 = 周日24:00 收盘 ——
# 两种语义各自自洽, 相位差 2 天, 回测收益系列不受影响 (勿"修正"成周日口径,
# 否则动真值基线且引入跨所基差).
# 独立裁判 = Coinbase Exchange 日K (BTC-USD 自 2014-12, ETH-USD 自 2016-05),
# 用**标签日收盘**口径对账; 跨所价差实测 2~5% => 阈值 3%, 超限只警告不失败.
EARLY_CUTOFF = '2017-08-01'
EARLY_COVERAGE = {'BTC': ('BTC-USD', '2014-12-01'), 'ETH': ('ETH-USD', '2016-05-01')}
EARLY_CACHE = os.path.join(DATA, 'daily_cache_early_coinbase.csv')
EARLY_THRESH = 0.03


def coinbase_daily(prod, start_date):
    """Coinbase Exchange 日K全量翻页 -> {utc_date: close}; 300 根/页."""
    out = {}
    cur = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)
    while cur < end:
        nxt = min(cur + timedelta(days=300), end)
        url = (f"https://api.exchange.coinbase.com/products/{prod}/candles"
               f"?granularity=86400&start={cur.isoformat()}&end={nxt.isoformat()}")
        arr, last_err = None, None
        for attempt in range(5):
            try:
                arr = json.loads(_get(url, "https://www.coinbase.com/"))
                break
            except Exception as e:
                last_err = e
                print(f"    [{prod}] 第{attempt+1}次重试: {e}", file=sys.stderr)
                time.sleep(1 + attempt)
        if arr is None:
            raise RuntimeError(f"[Coinbase] {prod} 翻页中断: {last_err}")
        for x in arr:
            d = datetime.fromtimestamp(int(x[0]), timezone.utc).strftime("%Y-%m-%d")
            out[d] = float(x[4])
        cur = nxt
        time.sleep(0.25)
    return out


def load_early_cache(path):
    """早期缓存 -> {coin: {date: close}}."""
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    header = rows[0]
    out = {}
    for r in rows[1:]:
        for i, c in enumerate(header[1:]):
            if r[i + 1] != '':
                out.setdefault(c, {})[r[0]] = float(r[i + 1])
    return out


def save_early_cache(path, early):
    dates = sorted({d for rows in early.values() for d in rows})
    coins = sorted(early)
    import csv as _csv
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = _csv.writer(f)
        w.writerow(['date'] + coins)
        for d in dates:
            w.writerow([d] + [early[c].get(d, '') for c in coins])


def _get(url, referer, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Referer": referer})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def binance_daily(sym, start_ms):
    """Binance 日K全量翻页 -> [(utc_date, close)]; 逐页重试, 中断抛 RuntimeError."""
    out, end_ms = [], None
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
            raise RuntimeError(f"[Binance] {sym} 日线翻页中断(已取 {len(out)} 天): {last_err}")
        if not arr:
            break
        for x in arr:
            out.append((datetime.fromtimestamp(int(x[0]) / 1000, timezone.utc)
                        .strftime("%Y-%m-%d"), float(x[4])))
        end_ms = int(arr[-1][6]) + 1
        if end_ms > int(time.time() * 1000):
            break
        time.sleep(0.15)
    return out


def okx_daily(inst, start_ms):
    """OKX 日K全量翻页 -> {utc_date: close}; 标签=(开盘ts+8h)的UTC日期(UTC+8切日)."""
    out = {}
    after = int(time.time() * 1000)
    while True:
        url = (f"https://www.okx.com/api/v5/market/history-candles?instId={inst}"
               f"&bar=1D&after={after}&limit=100")
        arr = json.loads(_get(url, "https://www.okx.com/")).get("data", [])
        if not arr:
            break
        for x in arr:
            ts = int(x[0])
            if ts >= start_ms:
                d = datetime.fromtimestamp(ts / 1000 + 8 * 3600, timezone.utc).strftime("%Y-%m-%d")
                out[d] = float(x[4])
        oldest = min(int(x[0]) for x in arr)
        if oldest <= start_ms:
            break
        after = oldest - 1
        time.sleep(0.12)
    # 最新未收盘 bar (history-candles 只回已收盘)
    try:
        arr = json.loads(_get(
            f"https://www.okx.com/api/v5/market/candles?instId={inst}&bar=1D&limit=3",
            "https://www.okx.com/")).get("data", [])
        for x in arr:
            ts = int(x[0])
            if ts >= start_ms:
                d = datetime.fromtimestamp(ts / 1000 + 8 * 3600, timezone.utc).strftime("%Y-%m-%d")
                out[d] = float(x[4])
    except Exception as e:
        print(f"    [{inst}] 最新bar获取失败: {e}", file=sys.stderr)
    return sorted(out.items())


def load_cache(path):
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    header = rows[0]
    out = {}
    for r in rows[1:]:
        for i, c in enumerate(header[1:]):
            if r[i + 1] != '':
                out.setdefault(c, []).append((r[0], float(r[i + 1])))
    return out


def save_cache(path, daily):
    """daily: {coin: [(date, close), ...]} -> 宽表 CSV (date 列并集)."""
    dates = sorted({d for rows in daily.values() for d, _ in rows})
    coins = sorted(daily)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['date'] + coins)
        idx = {c: {d: v for d, v in rows} for c, rows in daily.items()}
        for d in dates:
            w.writerow([d] + [idx[c].get(d, '') for c in coins])


def week_label(day_str):
    dt = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    monday = dt - timedelta(days=dt.weekday())
    return (monday - timedelta(days=3)).strftime("%Y-%m-%d")


def week_end(lbl):
    """标签+9天 = 该 Mon..Sun 窗口的周日 (用于判定已收盘)."""
    return (datetime.strptime(lbl, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            + timedelta(days=9)).strftime("%Y-%m-%d")


def main():
    ap = argparse.ArgumentParser(description="日线->周线 对账审计")
    ap.add_argument('--panel', default=PANEL_DEFAULT)
    ap.add_argument('--cache', default=CACHE_DEFAULT)
    ap.add_argument('--thresh', type=float, default=0.005, help='偏差阈值 (默认 0.5%%)')
    ap.add_argument('--offline', action='store_true', help='只用缓存, 不联网')
    ap.add_argument('--off-early', action='store_true',
                    help='跳过盲区段(<2017-08-01 BTC/ETH)的 Coinbase 对账')
    ap.add_argument('--start', default=START_DEFAULT)
    args = ap.parse_args()

    with open(args.panel, newline='', encoding='utf-8-sig') as f:
        rows = list(csv.reader(f))
    header = rows[0]
    coins = header[1:]
    panel = {}
    for r in rows[1:]:
        for i, c in enumerate(coins):
            if r[i + 1] != '':
                panel[(c, r[0])] = float(r[i + 1])
    panel_dates = sorted({k[1] for k in panel})
    print(f"[panel] {os.path.basename(args.panel)}: {len(coins)} 币, "
          f"{len(panel_dates)} 周 ({panel_dates[0]}..{panel_dates[-1]}), {len(panel)} 格")

    # ---- 取日线 (在线下载 / 离线缓存) ----
    if args.offline:
        if not os.path.exists(args.cache):
            print(f"[错误] --offline 但缓存不存在: {args.cache} (先跑一次在线审计)", file=sys.stderr)
            return 2
        daily = load_cache(args.cache)
        print(f"[cache] {os.path.basename(args.cache)}: {len(daily)} 币")
    else:
        start_ms = int(datetime.strptime(args.start, "%Y-%m-%d")
                       .replace(tzinfo=timezone.utc).timestamp() * 1000)
        daily = {}
        for c in coins:
            try:
                if c in OKX_ONLY_COINS:
                    rows_c = okx_daily(c + "-USDT", start_ms)
                else:
                    rows_c = binance_daily(c + "USDT", start_ms)
                daily[c] = rows_c
                print(f"  {c:<8} 日线 {len(rows_c):>5} 天", flush=True)
            except RuntimeError as e:
                print(f"  [跳过] {c}: {e}", file=sys.stderr)
        save_cache(args.cache, daily)
        print(f"[cache] 已写 {args.cache}")

    # ---- 聚合 + 对账 ----
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    disc, struct = [], []
    early_warn = []   # 盲区段 >3% (跨所价差或真错), 只警告不判失败
    n_cmp = 0

    # ---- 盲区段: BTC/ETH <2017-08-01, 用 Coinbase 标签日收盘口径 ----
    if not args.off_early:
        if args.offline:
            early = load_early_cache(EARLY_CACHE) if os.path.exists(EARLY_CACHE) else {}
        else:
            early = {}
            try:
                for c, (prod, sd) in EARLY_COVERAGE.items():
                    early[c] = coinbase_daily(prod, sd)
                    print(f"  [盲区] {c} Coinbase 日线 {len(early[c])} 天", flush=True)
                save_early_cache(EARLY_CACHE, early)
            except RuntimeError as e:
                print(f"  [警告] 盲区段跳过: {e}", file=sys.stderr)
        for c, dmap in early.items():
            for (coin, lbl), pv in panel.items():
                if coin != c or lbl >= EARLY_CUTOFF or lbl not in dmap:
                    continue
                dev = abs(pv / dmap[lbl] - 1)
                if dev > EARLY_THRESH:
                    early_warn.append((c, lbl, pv, dmap[lbl], dev))

    for c in coins:
        if c not in daily or not daily[c]:
            struct.append((c, "无日线数据(拉取失败或不在缓存)"))
            continue
        wk = {}
        for d, v in daily[c]:
            wk[week_label(d)] = v   # 后写覆盖 => 窗口内最后一个交易日
        first_day = daily[c][0][0]
        first_lbl = week_label(first_day)
        for (coin, lbl), pv in panel.items():
            if coin != c:
                continue
            if lbl not in wk:
                if lbl >= first_lbl and week_end(lbl) < today_utc:
                    struct.append((c, f"面板有值但日线聚合缺周: {lbl}"))
                continue
            if week_end(lbl) >= today_utc:   # 未收盘周: 快照对快照, 不判错
                continue
            av = wk[lbl]
            n_cmp += 1
            dev = abs(pv / av - 1) if av else float('inf')
            if dev > args.thresh:
                disc.append((c, lbl, pv, av, dev))

    disc.sort(key=lambda x: -x[4])
    print(f"\n=== 对账 {n_cmp} 格 (阈值 {args.thresh*100:.1f}%) ===")
    for c, lbl, pv, av, dev in disc[:40]:
        print(f"  {c:<8} {lbl}  面板={pv:<14.6g} 日线聚合={av:<14.6g}  偏差 {dev*100:6.2f}%")
    if len(disc) > 40:
        print(f"  ... 另 {len(disc)-40} 格")
    if struct:
        print("\n=== 结构性发现 ===")
        for c, msg in struct:
            print(f"  {c}: {msg}")
    if early_warn:
        print(f"\n=== 盲区段警告 (阈值 {EARLY_THRESH*100:.0f}%, 含跨所价差, 不计失败) ===")
        early_warn.sort(key=lambda x: -x[4])
        for c, lbl, pv, av, dev in early_warn[:15]:
            print(f"  {c:<6} {lbl}  面板={pv:<12.6g} CB={av:<12.6g}  {dev*100:5.2f}%")
        if len(early_warn) > 15:
            print(f"  ... 另 {len(early_warn)-15} 格")
    if not disc and not struct:
        print(f"\n结论: 偏差格 {len(disc)}, 结构性问题 {len(struct)}, 盲区警告 {len(early_warn)}"
              + ("  ✅ 通过" if not disc and not struct else ""))
        return 0
    print(f"\n结论: 偏差格 {len(disc)}, 结构性问题 {len(struct)}"
          + ("  -> 逐条归因后用独立 repair 脚本修复, 勿在审计里顺手改面板" if disc else ""))
    return 1


if __name__ == '__main__':
    sys.exit(main())
