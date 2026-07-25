"""
crypto_hist_data.py - 加密历史K线数据下载 (v1.0, 免费·多源)

设计目的:
  为 crypto_stocks/ 回测子系统提供周频收盘价数据.
  BTC / ETH / OKB 三币种, 从 Binance 主源 + OKX 备源拉取周K线,
  聚合为 weekly_adjclose_crypto3.csv 供回测引擎使用.

数据源 (免费·无需key):
  Binance : api.binance.com/api/v3/klines (周K, 2017年起)
  OKX     : www.okx.com/api/v5/market/candles (周K, 备源)

加密特殊性:
  - 7x24 全天候交易, 无"收盘"概念, 周K线按自然周聚合
  - 无复权问题(不存在送股/除权), close 即 adjclose
  - 估值不用PE/PB, 用市值/流通市值/网络活跃度

用法:
  python3 crypto_hist_data.py          # 下载全部币种, 输出到 data/
  python3 crypto_hist_data.py --only btc  # 只下某个
"""
import os, sys, json, csv, time
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
os.makedirs(DATA, exist_ok=True)

# ---------- 币种配置 ----------
COINS = {
    'BTC':  {'binance': 'BTCUSDT',   'okx': 'BTC-USDT',   'cg_id': 'bitcoin',          'name': 'Bitcoin',  'start': '2015-08-01'},
    'ETH':  {'binance': 'ETHUSDT',   'okx': 'ETH-USDT',   'cg_id': 'ethereum',         'name': 'Ethereum', 'start': '2017-01-01'},
    'OKB':  {'binance': 'OKBUSDT',   'okx': 'OKB-USDT',   'cg_id': 'okb',              'name': 'OKB',      'start': '2018-03-20'},
}


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.binance.com/" if "binance" in url else "https://www.okx.com/"
    })
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


# ========== Binance 周K线 ==========
def _binance_weekly_klines(symbol, start_ms=None, limit=1000):
    """拉取 Binance 周K线. 返回 [{timestamp, open, high, low, close, volume}, ...]"""
    rows = []
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1w&limit={limit}"
    if start_ms:
        url += f"&startTime={start_ms}"
    try:
        raw = _get(url)
        arr = json.loads(raw)
        for x in arr:
            rows.append({
                'timestamp': int(x[0]),
                'open': float(x[1]),
                'high': float(x[2]),
                'low': float(x[3]),
                'close': float(x[4]),
                'volume': float(x[5]),
            })
    except Exception as e:
        print(f"  [Binance] {symbol} 拉取失败: {e}", file=sys.stderr)
    return rows


def fetch_binance_full(symbol, start_date):
    """Binance 分页拉取, 直到 start_date. 每次最多1000条, 自动翻页."""
    start_ms = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
    all_rows = []
    end_ms = None
    while True:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1w&limit=1000"
        if end_ms:
            url += f"&startTime={end_ms}"
        else:
            url += f"&startTime={start_ms}"
        try:
            raw = _get(url)
            arr = json.loads(raw)
            if not arr:
                break
            for x in arr:
                all_rows.append({
                    'timestamp': int(x[0]),
                    'open': float(x[1]),
                    'high': float(x[2]),
                    'low': float(x[3]),
                    'close': float(x[4]),
                    'volume': float(x[5]),
                })
            # 下一页 startTime = 最后一条的 closeTime + 1
            end_ms = int(arr[-1][6]) + 1
            # 如果最后一条已经接近现在, 停止
            if end_ms > int(time.time() * 1000):
                break
            time.sleep(0.2)  # rate limit
        except Exception as e:
            print(f"  [Binance] 翻页失败: {e}", file=sys.stderr)
            break
    return all_rows


# ========== OKX 周K线 (备源) ==========
def fetch_okx_weekly(instId, start_date):
    """OKX 周K线, 备用数据源."""
    start_str = start_date.replace('-', '').replace('00:00:00', '') + 'T00:00:00Z'
    rows = []
    url = f"https://www.okx.com/api/v5/market/candles?instId={instId}&bar=1W&after={start_str}&limit=100"
    try:
        raw = _get(url)
        data = json.loads(raw).get("data", [])
        for x in data:
            rows.append({
                'timestamp': int(x[0]),
                'open': float(x[1]),
                'high': float(x[2]),
                'low': float(x[3]),
                'close': float(x[4]),
                'volume': float(x[5]),
            })
        # OKX 返回降序, 按 timestamp 升序
        rows.sort(key=lambda r: r['timestamp'])
    except Exception as e:
        print(f"  [OKX] {instId} 拉取失败: {e}", file=sys.stderr)
    return rows


# ========== 聚合为周频 close ==========
def rows_to_weekly_close(rows):
    """将K线数据按自然周聚合. 加密7x24, 直接用交易所返回的1W K线即可."""
    # Binance 的 1W K线已经是按交易所周 (UTC 周一开盘~周日收盘)
    if not rows:
        return {}
    weekly = {}
    for r in rows:
        ts = r['timestamp'] / 1000
        dt = datetime.utcfromtimestamp(ts)
        # 使用周五作为周的代表日 (对齐美股回测用周五)
        friday = dt - timedelta(days=(dt.weekday() - 4) % 7)
        week_key = friday.strftime('%Y-%m-%d')
        # 如果同一周有多条(不太可能), 取最后一条的close
        weekly[week_key] = r['close']
    return weekly


def download_coin(coin_key):
    """下载单个币种的周K线数据. Binance主, OKX备. 返回 {date: close}."""
    cfg = COINS[coin_key]
    print(f"  下载 {coin_key} ({cfg['name']}) 从 {cfg['start']} ...")

    # 主源 Binance
    rows = fetch_binance_full(cfg['binance'], cfg['start'])
    if len(rows) < 10:
        print(f"    Binance 数据不足 ({len(rows)}条), 尝试 OKX ...")
        rows = fetch_okx_weekly(cfg['okx'], cfg['start'])
    if len(rows) < 10:
        raise RuntimeError(f"{coin_key} 所有数据源均不足")

    print(f"    获取 {len(rows)} 条K线")
    return rows_to_weekly_close(rows)


def build_csv(output_path=None):
    """下载全部币种, 合并为一个 CSV (类似 us_stocks/data/weekly_adjclose_us50.csv)."""
    if output_path is None:
        output_path = os.path.join(DATA, 'weekly_adjclose_crypto3.csv')

    all_weekly = {}
    for ck in COINS:
        try:
            w = download_coin(ck)
            for date_str, price in w.items():
                if date_str not in all_weekly:
                    all_weekly[date_str] = {}
                all_weekly[date_str][ck] = price
        except Exception as e:
            print(f"  {ck} 下载失败: {e}", file=sys.stderr)

    # 排序日期, 取三币种都有数据的公共区间
    dates = sorted(all_weekly.keys())
    # 确保所有币种都有数据 (允许少量前期缺失)
    # 写入 CSV
    symbols = list(COINS.keys())
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date'] + symbols)
        for d in dates:
            row = [d]
            for s in symbols:
                row.append(all_weekly.get(d, {}).get(s, ''))
            writer.writerow(row)

    print(f"\n  已保存 {len(dates)} 周数据 -> {output_path}")
    # 打印时间范围
    if dates:
        print(f"  时间范围: {dates[0]} ~ {dates[-1]}")
    return output_path


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description="加密周K线数据下载 (Binance+OKX, 免费)")
    ap.add_argument('--only', type=str, default=None, help='只下载指定币种 (如 btc)')
    ap.add_argument('--output', type=str, default=None, help='输出CSV路径')
    args = ap.parse_args()

    if args.only:
        ck = args.only.upper()
        if ck not in COINS:
            print(f"  不支持的币种: {ck}, 可选: {list(COINS.keys())}")
            sys.exit(1)
        w = download_coin(ck)
        out = args.output or os.path.join(DATA, f'weekly_{ck.lower()}.csv')
        with open(out, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['date', ck])
            for d, p in sorted(w.items()):
                writer.writerow([d, p])
        print(f"  已保存 -> {out}")
    else:
        build_csv(args.output)
