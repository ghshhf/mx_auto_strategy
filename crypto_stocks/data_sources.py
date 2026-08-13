"""
data_sources.py - 加密行情数据源统一接口层 (v1, 加法重构)
================================================================
解决现状痛点: 取数逻辑分散在 crypto_hist_data.py (Binance/OKX + 全局副作用代理)
与 sync_crypto_panel.py (CMC + 私有 _CMC_ID_MAP + 又一套代理) 两个文件, 加一个新源
要改 2~3 处、复制代理/日期对齐代码。本模块把"源"抽象成统一接口, 新增源只写一个小类。

设计原则:
  - 纯标准库 (urllib/json/csv/datetime), 不依赖 pandas, 任何环境可跑, 不污染现有引擎。
  - 无 import 副作用: 代理在方法内按需构造, 不 install_opener 全局。
  - 防御式取数: 任何源失败都返回 {} 并降级到下一个, 绝不抛错中断回测。
  - 加法存在: 不删除/替换 sync_crypto_panel.py 与 crypto_hist_data.py, 现有 28,092x
    管线不受影响。本模块是它们的"干净继任者", 迁移时再删旧代码。

接口:
  BaseCryptoSource
    .name                    -> 源名称
    .supports(symbol)        -> 该源是否认识这个币 (有无翻译映射)
    .fetch_weekly(sym, start)-> {friday_date: close}  (周五对齐收盘价, 失败返回 {})
  CryptoDataClient(sources, cache_dir)
    .fetch(symbol, start)    -> 按降级顺序合并多源, 结果缓存到本地 JSON
  build_panel(coins, start, client, out) -> 写宽表 CSV (迁移 sync_crypto_panel 的路径)

用法:
  from data_sources import CryptoDataClient, BinanceSource, OkxSource, CoinGeckoSource, CmcSource
  client = CryptoDataClient([BinanceSource(), OkxSource(), CoinGeckoSource(), CmcSource()])
  btc = client.fetch('BTC', '2017-01-01')   # 多源降级 + 本地缓存
"""
import os
import sys
import json
import csv
import time
import datetime
import urllib.request
from abc import ABC, abstractmethod

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')


# ---------------- 代理 (方法内按需, 不全局 install) ----------------
def _proxy_opener():
    proxy = (os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
             or os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
             or 'http://127.0.0.1:3067')
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({'http': proxy, 'https': proxy})), proxy


def _http_get_json(url, headers=None, timeout=30):
    """带代理的 GET -> 解析 JSON; 失败返回 (None, err)。"""
    opener, _ = _proxy_opener()
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    try:
        raw = opener.open(req, timeout=timeout).read().decode('utf-8', 'ignore')
        return json.loads(raw), None
    except Exception as e:  # 网络/解析失败一律降级
        return None, str(e)


def align_friday(ts_ms):
    """毫秒时间戳 -> 当周周五日期字符串 'YYYY-MM-DD' (加密 7x24, 周K 以周五收盘对齐)."""
    dt = datetime.datetime.utcfromtimestamp(ts_ms / 1000.0)
    friday = dt - datetime.timedelta(days=(dt.weekday() - 4) % 7)
    return friday.strftime('%Y-%m-%d')


# ---------------- 符号映射 ----------------
# CoinGecko 用 coin id (非 ticker); 此处为常用币映射, 未知币该源自动跳过。
COINGECKO_IDS = {
    'BTC': 'bitcoin', 'ETH': 'ethereum', 'OKB': 'okb', 'SOL': 'solana',
    'BNB': 'binancecoin', 'XRP': 'ripple', 'ADA': 'cardano', 'AVAX': 'avalanche-2',
    'DOGE': 'dogecoin', 'DOT': 'polkadot', 'LINK': 'chainlink', 'POL': 'polygon-ecosystem-token',
    'TRX': 'tron', 'ATOM': 'cosmos', 'UNI': 'uniswap', 'LTC': 'litecoin',
    'NEAR': 'near', 'APT': 'aptos', 'ARB': 'arbitrum', 'OP': 'optimism',
    'SUI': 'sui', 'FET': 'fetch-ai', 'MKR': 'maker', 'AAVE': 'aave',
    'INJ': 'injective', 'TIA': 'celestia',
    'IMX': 'immutable-x', 'GRT': 'the-graph', 'FIL': 'filecoin', 'CRV': 'curve-dao-token',
    'LDO': 'lido-dao', 'SNX': 'havven', 'COMP': 'compound-governance-token',
    'SAND': 'the-sandbox', 'MANA': 'decentraland',
    'DYDX': 'dydx', 'ENS': 'ethereum-name-service', 'GALA': 'gala', 'ZEC': 'zcash',
    'DASH': 'dash', 'AR': 'arweave', 'ILV': 'illuvium',
    'JUP': 'jupiter', 'JOE': 'joe', 'TAO': 'bittensor', 'ONDO': 'ondo-finance',     'GRAM': 'the-open-network',
    'CFG': 'centrifuge', 'POLYX': 'polymesh',
    'AKT': 'akash-network', 'MANTA': 'manta-network', 'XLM': 'stellar',
    'APEX': 'apex-protocol', 'BCH': 'bitcoin-cash',
}

# CMC id 映射 (从 sync_crypto_panel._CMC_ID_MAP 迁来, 自此以本模块为唯一真相源;
# 迁移完成后旧文件里的副本可删)。
CMC_IDS = {
    '1INCH': 8104, 'AAVE': 7278, 'ADA': 2010, 'AKT': 7431, 'APT': 21794, 'AR': 5632,
    'ARB': 11841, 'AVAX': 5805, 'BTC': 1, 'XLM': 512,
    'COMP': 5692, 'CRV': 6538, 'DASH': 131, 'DOT': 6636, 'DYDX': 28324,
    'ENS': 13855, 'ETH': 1027, 'FET': 3773, 'FIL': 2280, 'GALA': 7080,
    'ILV': 8719, 'IMX': 10603, 'JUP': 29210, 'LDO': 8000, 'LINK': 1975, 'LTC': 2, 'MANTA': 13631,
    'CFG': 4160, 'POL': 6690, 'MKR': 1518, 'NEAR': 6535,
    'OKB': 3897, 'ONDO': 21159, 'OP': 11840, 'INJ': 20646,
    'POLYX': 20362, 'RENDER': 5690,
    'SNX': 2586, 'SOL': 5426, 'SUI': 20947, 'TAO': 22974,
    'TIA': 22861, 'GRAM': 11419, 'TRX': 1958, 'UNI': 7083, 'ZEC': 1437, 'JOE': 11396,
}


# ---------------- 抽象基类 ----------------
class BaseCryptoSource(ABC):
    """所有行情源的统一契约。子类只需实现 name / supports / fetch_weekly。"""
    @property
    @abstractmethod
    def name(self):
        ...

    @abstractmethod
    def supports(self, symbol):
        """该源能否提供这个币 (有无符号翻译)。"""
        ...

    @abstractmethod
    def fetch_weekly(self, symbol, start_date):
        """返回 {friday_date: close}; 失败/不支持返回 {}。绝不抛错。"""
        ...


class BinanceSource(BaseCryptoSource):
    @property
    def name(self):
        return 'binance'

    def supports(self, symbol):
        return True  # Binance 统一 USDT 计价, 任何 ticker 都可拼

    def fetch_weekly(self, symbol, start_date):
        sym = f"{symbol.upper()}USDT"
        start_ms = int(datetime.datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
        out = {}
        try:
            end_ms = start_ms
            for _ in range(200):  # 翻页上限保护
                url = (f"https://api.binance.com/api/v3/klines?symbol={sym}"
                       f"&interval=1w&limit=1000&startTime={end_ms}")
                data, err = _http_get_json(url)
                if err or not data:
                    break
                for x in data:
                    out[align_friday(int(x[0]))] = float(x[4])
                last = int(data[-1][6]) + 1
                if last > int(time.time() * 1000):
                    break
                end_ms = last
                time.sleep(0.15)
        except Exception as e:
            print(f"  [Binance] {symbol} 失败: {e}", file=sys.stderr)
            return {}
        return out


class OkxSource(BaseCryptoSource):
    @property
    def name(self):
        return 'okx'

    def supports(self, symbol):
        return True

    def fetch_weekly(self, symbol, start_date):
        inst = f"{symbol.upper()}-USDT"
        start_ms = int(datetime.datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
        rows = []
        try:
            after = int(time.time() * 1000)
            for _ in range(200):
                url = f"https://www.okx.com/api/v5/market/candles?instId={inst}&bar=1W&after={after}&limit=100"
                data, err = _http_get_json(url)
                if err or not data:
                    break
                for x in data:
                    rows.append((int(x[0]), float(x[4])))
                oldest = min(r[0] for r in rows)
                if oldest <= start_ms:
                    break
                after = oldest - 1
                time.sleep(0.15)
            rows.sort(key=lambda r: r[0])
        except Exception as e:
            print(f"  [OKX] {symbol} 失败: {e}", file=sys.stderr)
            return {}
        return {align_friday(ts): c for ts, c in rows}


class CoinGeckoSource(BaseCryptoSource):
    """覆盖广 (含许多 Binance/OKX 未上或下架的币), 作降级源。

    两种模式:
      - 无 key (默认): 免费档历史区间硬上限 365 天 (实测 days=366+ 返回 HTTP 401
        error_code 10012 "Public API users are limited to querying historical data")。
        因此无 key 时仅作"近 1 年"兜底源, 全历史仍靠 Binance/OKX。
      - 有 key: 带上 x-cg-demo-api-key 头后, 10012 限制解除, 可用 days=max 拉全历史 ——
        复现"过去能拉更多"的用法。Key 来源: 构造参数 api_key= 或环境变量 COINGECKO_API_KEY。
    """
    def __init__(self, api_key=None):
        self._key = api_key or os.environ.get('COINGECKO_API_KEY', '')

    @property
    def name(self):
        return 'coingecko'

    def supports(self, symbol):
        return symbol.upper() in COINGECKO_IDS

    def fetch_weekly(self, symbol, start_date):
        cid = COINGECKO_IDS.get(symbol.upper())
        if not cid:
            return {}
        headers = {"User-Agent": "Mozilla/5.0"}
        if self._key:
            # 有 key: 解除历史区间限制, 拉全历史 (days=max)
            headers['x-cg-demo-api-key'] = self._key
            days_param = 'max'
        else:
            # 无 key: 免费档上限 365 天; days 取 [start, 今天] 与 365 的较小者
            start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
            days_param = max(1, min((datetime.date.today() - start_dt).days, 365))
        url = (f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart"
               f"?vs_currency=usd&days={days_param}")
        data, err = _http_get_json(url, headers=headers)
        if err or not data:
            print(f"  [CoinGecko] {symbol} 失败: {err}", file=sys.stderr)
            return {}
        prices = data.get('prices', [])
        if not prices:
            return {}
        out = {}
        for ts_ms, price in prices:
            d = align_friday(int(ts_ms))
            if datetime.datetime.strptime(d, '%Y-%m-%d').date() >= datetime.datetime.strptime(start_date, '%Y-%m-%d').date():
                out[d] = float(price)
        return out


class CmcSource(BaseCryptoSource):
    """CoinMarketCap 历史接口, 需 key (环境变量 CMC_API_KEY 或 .env); 无 key 自动跳过。"""
    def __init__(self):
        self._key = (os.environ.get('CMC_API_KEY')
                     or self._read_env().get('CMC_API_KEY', ''))

    @staticmethod
    def _read_env():
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

    @property
    def name(self):
        return 'cmc'

    def supports(self, symbol):
        return self._key and symbol.upper() in CMC_IDS

    def fetch_weekly(self, symbol, start_date):
        if not self._key:
            return {}
        cid = CMC_IDS.get(symbol.upper())
        if not cid:
            return {}
        url = (f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/historical"
               f"?id={cid}&time_start={start_date}&interval=daily")
        data, err = _http_get_json(
            url, headers={'Accepts': 'application/json',
                          'X-CMC_PRO_API_KEY': self._key})
        if err or not data:
            print(f"  [CMC] {symbol} 失败: {err}", file=sys.stderr)
            return {}
        out = {}
        for q in data.get('data', {}).get('quotes', []):
            ts = q.get('timestamp', '')
            if not ts:
                continue
            dt = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
            fri = (dt - datetime.timedelta(days=(dt.weekday() - 4) % 7)).strftime('%Y-%m-%d')
            close = (q.get('quote', {}).get('USD', {}).get('close')
                     or q.get('quote', {}).get('USD', {}).get('price'))
            if close is not None:
                out[fri] = float(close)
        return out


# ---------------- 客户端: 多级降级 + 缓存 ----------------
class CryptoDataClient:
    """
    按 sources 顺序降级取数并合并, 结果缓存到 cache_dir/<SYMBOL>.json。
    同一币重复查询直接读缓存, 不重复打网络 -> "更好的查数据"体验。
    """
    def __init__(self, sources=None, cache_dir=None, prefer=None):
        self.sources = sources or [BinanceSource(), OkxSource(),
                                   CoinGeckoSource(), CmcSource()]
        self.cache_dir = cache_dir or os.path.join(DATA, '_cache')
        os.makedirs(self.cache_dir, exist_ok=True)
        self.prefer = prefer  # 可选: 指定降级顺序的源 name 列表

    def _ordered(self):
        if not self.prefer:
            return self.sources
        by_name = {s.name: s for s in self.sources}
        ordered = [by_name[n] for n in self.prefer if n in by_name]
        ordered += [s for s in self.sources if s.name not in (self.prefer or [])]
        return ordered

    def fetch(self, symbol, start_date='2015-01-01'):
        symbol = symbol.upper()
        cache_path = os.path.join(self.cache_dir, f"{symbol}.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, encoding='utf-8') as fh:
                    return json.load(fh)
            except Exception:
                pass
        merged = {}
        for src in self._ordered():
            if not src.supports(symbol):
                continue
            w = src.fetch_weekly(symbol, start_date)
            if w:
                merged.update(w)
                print(f"    [{src.name}] {symbol}: +{len(w)} 周", file=sys.stderr)
        if merged:
            with open(cache_path, 'w', encoding='utf-8') as fh:
                json.dump(merged, fh, sort_keys=True)
        return merged


# ---------------- 面板构建 (迁移 sync_crypto_panel 的路径) ----------------
def build_panel(coins, start_date='2015-01-01', client=None,
                output=None, cache_only=True):
    """
    用 client 拉全部币, 写宽表 CSV (date + 各币), 周五对齐, 上市前留空。
    cache_only=True 时只合并已缓存结果, 不触发网络 (适合离线重建面板)。
    返回输出路径。
    """
    client = client or CryptoDataClient()
    output = output or os.path.join(DATA, 'weekly_adjclose_crypto50.csv')
    all_weekly = {}
    for sym in coins:
        w = client.fetch(sym, start_date) if not cache_only else _read_cache(client, sym)
        for d, p in w.items():
            all_weekly.setdefault(d, {})[sym] = p
    dates = sorted(all_weekly.keys())
    with open(output, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date'] + list(coins))
        for d in dates:
            writer.writerow([d] + [all_weekly[d].get(s, '') for s in coins])
    print(f"  已保存 {len(dates)} 周 × {len(coins)} 币 -> {output}")
    return output


def _read_cache(client, symbol):
    p = os.path.join(client.cache_dir, f"{symbol.upper()}.json")
    if os.path.exists(p):
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    return {}


if __name__ == '__main__':
    # 快速自检: 拉 BTC, 打印前 3 / 末 3 周
    c = CryptoDataClient()
    btc = c.fetch('BTC', '2017-01-01')
    keys = sorted(btc.keys())
    print(f"BTC 周数: {len(keys)}  首 {keys[0]} {btc[keys[0]]:.2f}  末 {keys[-1]} {btc[keys[-1]]:.2f}")
