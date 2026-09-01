"""
sync_crypto_panel.py - 增量同步加密周K面板到今天 (Binance > OKX > CMC 三级降级)
=============================================================================
复用 crypto_hist_data 的符号映射/取数函数, 仅追加 "现有最后日期之后" 的周K,
不动历史行, 保证网格(Friday)与现有数据严格连续.

数据源优先级:
  1. Binance api.binance.com (周K, 免费, 主源)
  2. OKX     www.okx.com      (周K, 免费, 备源)
  3. CoinMarketCap pro-api.coinmarketcap.com (日线聚合周五, 需 API key, 兜底)

目标文件 (回测实际读取的):
  data/weekly_adjclose_crypto50.csv      (crypto_options_bt.py)
  data/weekly_adjclose_crypto50_10y.csv  (OOS/10y 脚本)

用法:
  python sync_crypto_panel.py
  CMC_API_KEY=xxx python sync_crypto_panel.py   # 可选, 无则跳过 CMC
"""
import os
import sys
import csv
import time
import datetime
import urllib.request
import json

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # 仓库根, 供 net_config
sys.path.insert(0, HERE)
import crypto_hist_data as chd  # noqa: E402

# ---------- 代理 (统一走 net_config 解析) ----------
# 2026-09-01: 原为 "环境变量优先"。沙箱注入的 61350 对 Binance/OKX 全返 502,
# 会让增量同步卡死; 改由 net_config 存活探测 + 回退 3067, 从源头规避。
import net_config  # noqa: E402

_PROXY = net_config.proxy_url()
_op = urllib.request.build_opener(
    urllib.request.ProxyHandler({'http': _PROXY, 'https': _PROXY}))
urllib.request.install_opener(_op)

# ---------- 数据源配置 (key 来自 .env / 环境变量, 不硬编码) ----------
def _load_env_file():
    """读取项目内 .env (已被 .gitignore 屏蔽, 不入库), 仅本地开发用."""
    env = {}
    p = os.path.join(HERE, '.env')
    if os.path.exists(p):
        with open(p, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


_LOCAL_ENV = _load_env_file()
_CMC_KEY = (os.environ.get('CMC_API_KEY')
            or _LOCAL_ENV.get('CMC_API_KEY', ''))

# CMC symbol -> id 映射 (56/57 币; PAS 不在 CMC 上)
# 来源: 2026-08-11 实时查询 pro-api.coinmarketcap.com
# 注意: RENDER id=5690; GRAM(原 TON, 2026-06-15 更名, ticker TON->GRAM, id 不变=11419)
_CMC_ID_MAP = {
    'HBAR': 4642,  # 2026-08-31
    'AAVE': 7278,   'ADA': 2010,
    'APT': 21794,    'AVAX': 5805,
    'BTC': 1, 'BCH': 1831, 'XLM': 512,
    'DOT': 6636,    'ICP': 8916,
    'DYDX': 28324,    'ETH': 1027,
    'GLM': 1455,     'FIL': 2280,    'JUP': 29210,    'LINK': 1975,    'LTC': 2,       'POL': 6690,
    'NEAR': 6535,    'OKB': 3897,
    'ONDO': 21159,   'RENDER': 5690,    'SOL': 5426,
    'GRAM': 11419,   'TRX': 1958,    'UNI': 7083,     'ZEC': 1437,   'XRP': 52,
    'GT': 4269,
}


def _cmc_get(url):
    """CMC HTTP GET (带 key + 代理)."""
    req = urllib.request.Request(url, headers={
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': _CMC_KEY,
    })
    return json.loads(_op.open(req, timeout=30).read().decode())


def fetch_cmc_weekly(cmc_id, start_date):
    """从 CMC quotes/historical 拉日线, 聚合为 {friday_date: close}.
    CMC 免费版仅支持 daily interval, 我们取每周五的 close 作为周收盘价."""
    if not _CMC_KEY or not cmc_id:
        return {}
    url = (f'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/historical'
           f'?id={cmc_id}&time_start={start_date}&interval=daily')
    try:
        d = _cmc_get(url)
        quotes = d.get('data', {}).get('quotes', [])
        if not quotes:
            return {}
    except Exception as e:
        print(f"    [CMC] id={cmc_id} 失败: {e}", file=sys.stderr)
        return {}

    weekly = {}
    for q in quotes:
        ts_str = q.get('timestamp', '')
        if not ts_str:
            continue
        # CMC timestamp format: "2026-08-08T00:00:00.000Z"
        try:
            dt = datetime.datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            friday = (dt - datetime.timedelta(days=(dt.weekday() - 4) % 7))
            fri_str = friday.strftime('%Y-%m-%d')
        except (ValueError, OSError):
            continue
        close = (q.get('quote', {}).get('USD', {}).get('close')
                 or q.get('quote', {}).get('USD', {}).get('price'))
        if close is not None:
            weekly[fri_str] = close
    return weekly


def fetch_coin_from(start_date, binance_sym, okx_sym, cmc_id=None):
    """三级降级取数: Binance -> OKX -> CMC. 返回 {friday_date: close}."""
    # Level 1: Binance
    rows = chd.fetch_binance_full(binance_sym, start_date)
    if len(rows) >= 2:
        return chd.rows_to_weekly_close(rows)

    # Level 2: OKX
    print(f"    Binance 不足 ({len(rows)}), 试 OKX ...", file=sys.stderr)
    rows = chd.fetch_okx_weekly(okx_sym, start_date)
    if len(rows) >= 2:
        return chd.rows_to_weekly_close(rows)

    # Level 3: CMC
    print(f"    OKX 也不足 ({len(rows)}), 试 CMC ...", file=sys.stderr)
    if cmc_id and _CMC_KEY:
        w = fetch_cmc_weekly(cmc_id, start_date)
        if len(w) >= 1:
            print(f"    CMC 成功: {len(w)} 周", file=sys.stderr)
            return w
        print(f"    CMC 数据为空", file=sys.stderr)

    return {}


def sync_file(fname):
    path = os.path.join(DATA, fname)
    if not os.path.exists(path):
        print(f"[跳过] {fname} 不存在")
        return
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        rows = list(reader)
    header = rows[0]
    data = rows[1:]
    coins = header[1:]
    last_date = data[-1][0]
    cmc_status = "ON" if _CMC_KEY else "OFF"
    print(f"\n=== {fname} ===  现有末日={last_date}  币种={len(coins)}  CMC={cmc_status}")

    syms = chd.all_coin_symbols()
    new_series = {}
    empty_coins = []
    for coin in coins:
        cfg = syms.get(coin)
        cmc_id = _CMC_ID_MAP.get(coin)
        if not cfg:
            print(f"  [警告] {coin} 无符号映射, 留空")
            empty_coins.append(coin)
            continue
        w = fetch_coin_from(last_date, cfg['binance'], cfg['okx'], cmc_id=cmc_id)
        w = {d: p for d, p in w.items() if d > last_date}
        new_series[coin] = w
        time.sleep(0.05)

    all_new_dates = set()
    for coin in coins:
        all_new_dates.update(new_series.get(coin, {}).keys())
    new_dates = sorted(all_new_dates)
    if not new_dates:
        print("  无需追加 (已是最新)")
        return

    print(f"  新增周: {new_dates}")
    for d in new_dates:
        row = [d] + [('' if coin in empty_coins else new_series.get(coin, {}).get(d, ''))
                     for coin in coins]
        data.append(row)
    data.sort(key=lambda r: r[0])

    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)
    print(f"  已写入 -> {path}  现共 {len(data)} 周, 末日={data[-1][0]}")

    cov = {c: sum(1 for r in data if r[header.index(c)] != '')
           for c in coins}
    miss = [c for c, n in cov.items() if n < len(data)]
    if miss:
        print(f"  [提示] 仍有空值币种(上市晚/源缺): {miss[:10]}")


if __name__ == '__main__':
    sync_file('weekly_adjclose_crypto50.csv')
    sync_file('weekly_adjclose_crypto50_10y.csv')
    print("\n完成。")
