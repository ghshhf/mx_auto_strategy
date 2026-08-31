"""
crypto_hist_data.py - 加密历史周K线数据下载 (v2.0, 免费·多源·全50币)
====================================================================

为 crypto_stocks/ 回测子系统提供**真实**周频收盘价数据.
设计对标 us_stocks/extend_panel_us_tickers.py (真实数据通道).

数据源 (免费·无需key):
  Binance : api.binance.com/api/v3/klines (周K, 2017年起, 主源)
  OKX     : www.okx.com/api/v5/market/candles (周K, 备源)

覆盖:
  - 3 防御币 BTC/ETH/OKB (原 v1.0 逻辑保留, --only 兼容)
  - 47 进攻币 (由 crypto_adoption_v2.COIN_META 自动推导 Binance/OKX 符号)
  - ⚠ 历史连续性: GRAM(原 TON) 在 Binance 的 GRAMUSDT 仅含 2026-06-15 更名后的周K(~7 周),
    更名前的 TON 全历史已固化在 data/weekly_adjclose_crypto50*.csv 的 GRAM 列中; 切勿从零重拉 GRAMUSDT,
    否则会丢失 2021→2026 的 TON 历史. 以后只追加 2026-08-14 之后的新周即可.
  - 上市前自然留空 (交易所无数据即空白, 绝不编造)

加密特殊性:
  - 7x24 全天候, 无"收盘"概念, 周K线按交易所 1W K线聚合
  - 无复权问题, close 即 adjclose
  - 估值不用PE/PB, 用市值/流通市值/网络活跃度

★ 诚实性:
  本脚本拉的是 Binance/OKX **真实成交周K线**. 经 127.0.0.1:3067 代理可直连
  (脚本自动从 HTTPS_PROXY/http_proxy 环境变量读取代理, 留空则直连).
  拉到的数据喂给 backtest_v2.py 即为**真实倍数**; 切勿用 generate_synthetic_* 的
  合成数据当真值 (详见 README 真相化章节).

用法:
  python3 crypto_hist_data.py            # 下载全部 50 币 -> weekly_adjclose_crypto50.csv
  python3 crypto_hist_data.py --only btc # 只下某个 (btc/eth/okb)
  python3 crypto_hist_data.py --check    # 仅打印符号映射, 不下载 (沙箱安全自检)
"""
import os
import sys
import json
import csv
import time
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
os.makedirs(DATA, exist_ok=True)

sys.path.insert(0, os.path.dirname(HERE))  # 仓库根, 供 net_config
sys.path.insert(0, HERE)
import crypto_adoption_v2 as ca2

# ---------- 代理支持 (统一走 net_config 解析) ----------
# 2026-09-01: 原先是 "环境变量优先且无回退"。沙箱/CI 会注入 61350 / 51245 之类
# 对 Binance/OKX 一律返回 502 的代理, 导致本模块取数卡死 (历史坑, 见 PITFALLS)。
# 改由 net_config 统一解析: 存活探测 + 回退默认 3067, 从源头规避坏代理。
import net_config  # noqa: E402

_PROXY = net_config.proxy_url()
_op = urllib.request.build_opener(
    urllib.request.ProxyHandler({'http': _PROXY, 'https': _PROXY}))
urllib.request.install_opener(_op)
print(f"  [代理] 已启用: {_PROXY}", file=sys.stderr)


# ---------- 原始 3 防御币配置 (v1.0 兼容) ----------
COINS = {
    'BTC':  {'binance': 'BTCUSDT',   'okx': 'BTC-USDT',   'start': '2015-08-01'},
    'ETH':  {'binance': 'ETHUSDT',   'okx': 'ETH-USDT',   'start': '2017-01-01'},
    'OKB':  {'binance': 'OKBUSDT',   'okx': 'OKB-USDT',   'start': '2018-03-20'},
}


def _coin_start_year(sym):
    """从 COIN_META 取上市年, 转起始日期 (粗略: 上市年1月; 真实数据自然只从实际上市起)."""
    yr = ca2.COIN_META.get(sym, {}).get('launch', 2017)
    return f"{int(yr) - 1}-06-01"   # 略早于上市年, 让交易所返回实际最早数据


def all_coin_symbols():
    """由 COIN_META 推导全部 50 币的 Binance/OKX 符号映射. Binance 统一 USDT 计价."""
    out = {}
    for sym in ca2.ALL_COINS:
        out[sym] = {
            'binance': f"{sym}USDT",
            'okx': f"{sym}-USDT",
            'start': _coin_start_year(sym),
        }
    # 防御币用精确 start (保留 v1.0)
    for k, v in COINS.items():
        out[k] = dict(v)
    return out


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.binance.com/" if "binance" in url else "https://www.okx.com/"
    })
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


# ========== Binance 周K线 ==========
def _binance_weekly_klines(symbol, start_ms=None, limit=1000):
    rows = []
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1w&limit={limit}"
    if start_ms:
        url += f"&startTime={start_ms}"
    try:
        raw = _get(url)
        arr = json.loads(raw)
        for x in arr:
            rows.append({'timestamp': int(x[0]), 'close': float(x[4])})
    except Exception as e:
        print(f"  [Binance] {symbol} 拉取失败: {e}", file=sys.stderr)
    return rows


def fetch_binance_full(symbol, start_date):
    start_ms = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
    all_rows = []
    end_ms = None
    while True:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1w&limit=1000"
        url += f"&startTime={end_ms}" if end_ms else f"&startTime={start_ms}"
        try:
            raw = _get(url)
            arr = json.loads(raw)
            if not arr:
                break
            for x in arr:
                all_rows.append({'timestamp': int(x[0]), 'close': float(x[4])})
            end_ms = int(arr[-1][6]) + 1
            if end_ms > int(time.time() * 1000):
                break
            time.sleep(0.2)
        except Exception as e:
            print(f"  [Binance] 翻页失败: {e}", file=sys.stderr)
            break
    return all_rows


# ========== OKX 周K线 (备源) ==========
def fetch_okx_weekly(instId, start_date):
    """OKX candles: after/before 为毫秒时间戳(非ISO); 返回 newest-first, 需翻页."""
    start_ms = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
    rows = []
    after = int(time.time() * 1000)   # 从当前向历史翻页
    try:
        while True:
            url = f"https://www.okx.com/api/v5/market/candles?instId={instId}&bar=1W&after={after}&limit=100"
            data = json.loads(_get(url)).get("data", [])
            if not data:
                break
            for x in data:
                rows.append({'timestamp': int(x[0]), 'close': float(x[4])})
            oldest = min(int(x[0]) for x in data)
            if oldest <= start_ms:
                break
            after = oldest - 1
            time.sleep(0.2)
        rows.sort(key=lambda r: r['timestamp'])
    except Exception as e:
        print(f"  [OKX] {instId} 拉取失败: {e}", file=sys.stderr)
    return rows


def rows_to_weekly_close(rows):
    if not rows:
        return {}
    weekly = {}
    for r in rows:
        ts = r['timestamp'] / 1000
        dt = datetime.utcfromtimestamp(ts)
        friday = dt - timedelta(days=(dt.weekday() - 4) % 7)
        weekly[friday.strftime('%Y-%m-%d')] = r['close']
    return weekly


def download_coin(sym, cfg):
    """下载单币周K线. Binance主, OKX备. 返回 {date: close}."""
    print(f"  下载 {sym} (start {cfg['start']}) ...")
    rows = fetch_binance_full(cfg['binance'], cfg['start'])
    if len(rows) < 10:
        print(f"    Binance 不足 ({len(rows)}), 试 OKX ...")
        rows = fetch_okx_weekly(cfg['okx'], cfg['start'])
    if len(rows) < 10:
        print(f"    [警告] {sym} 数据源均不足, 跳过 (该币周留空)")
        return {}
    print(f"    获取 {len(rows)} 条K线")
    return rows_to_weekly_close(rows)


def build_csv_full(output_path=None):
    """下载全部 50 币, 合并为周频收盘价 CSV (真实数据). 上市前自然留空."""
    if output_path is None:
        output_path = os.path.join(DATA, 'weekly_adjclose_crypto50.csv')
    syms = all_coin_symbols()
    all_weekly = {}
    for sym, cfg in syms.items():
        w = download_coin(sym, cfg)
        for d, p in w.items():
            all_weekly.setdefault(d, {})[sym] = p
        time.sleep(0.1)
    dates = sorted(all_weekly.keys())
    symbols = list(syms.keys())
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date'] + symbols)
        for d in dates:
            row = [d] + [all_weekly[d].get(s, '') for s in symbols]
            writer.writerow(row)
    print(f"\n  已保存 {len(dates)} 周 × {len(symbols)} 币 -> {output_path}")
    if dates:
        print(f"  时间范围: {dates[0]} ~ {dates[-1]}")
    # 覆盖度自检
    cov = {s: sum(1 for d in dates if all_weekly[d].get(s)) for s in symbols}
    empty = [s for s, c in cov.items() if c == 0]
    if empty:
        print(f"  [提示] 以下币全空(可能上市晚/源缺失): {empty}")
    return output_path


def build_csv_legacy(output_path=None):
    """原 v1.0: 仅 3 防御币."""
    if output_path is None:
        output_path = os.path.join(DATA, 'weekly_adjclose_crypto3.csv')
    all_weekly = {}
    for ck in COINS:
        w = download_coin(ck, COINS[ck])
        for d, p in w.items():
            all_weekly.setdefault(d, {})[ck] = p
    dates = sorted(all_weekly.keys())
    symbols = list(COINS.keys())
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date'] + symbols)
        for d in dates:
            writer.writerow([d] + [all_weekly.get(d, {}).get(s, '') for s in symbols])
    print(f"\n  已保存 {len(dates)} 周 -> {output_path}")
    return output_path


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description="加密周K线下载 (Binance+OKX, 免费, 全50币)")
    ap.add_argument('--only', type=str, default=None, help='只下指定币 (btc/eth/okb)')
    ap.add_argument('--all', action='store_true', help='下载全部50币 (默认)')
    ap.add_argument('--check', action='store_true', help='仅打印符号映射, 不下载')
    ap.add_argument('--output', type=str, default=None)
    args = ap.parse_args()

    if args.check:
        syms = all_coin_symbols()
        print(f"全部 {len(syms)} 币符号映射:")
        for s, c in syms.items():
            print(f"  {s:8} Binance={c['binance']:12} OKX={c['okx']:12} start={c['start']}")
        sys.exit(0)

    if args.only:
        ck = args.only.upper()
        if ck not in COINS:
            print(f"  --only 仅支持 {list(COINS.keys())}")
            sys.exit(1)
        w = download_coin(ck, COINS[ck])
        out = args.output or os.path.join(DATA, f'weekly_{ck.lower()}.csv')
        with open(out, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['date', ck])
            for d, p in sorted(w.items()):
                writer.writerow([d, p])
        print(f"  已保存 -> {out}")
    else:
        build_csv_full(args.output)
