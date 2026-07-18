"""
crypto_data.py - 加密资产数据源 (v1.0, 免费·全币种·多交易所)

为什么需要:
  用户加密投资额度与股票并列, 需并入总资金统计. 本模块只做一件事:
  拉取加密实时价 + 交易所相关数据, 供 manual_log 的加密账号估值使用.
  ⛔ 仅用公开行情 API, 不接任何交易所私有/交易接口(无密钥·无风险).

数据源 (全部免费·无需 key):
  主源  CoinGecko : 全市场几千币种, 且自带交易所维度数据
        - simple/price      : 按 id 批量拉任意币种价格 (全币种, 不只BTC/ETH)
        - coins/markets    : 全市场榜单(市值/涨跌/上架交易所)
        - exchanges        : 交易所列表与相关数据
        - exchanges/{id}   : 某交易所的上架币种/成交量/价差
  备源  Binance     : api.binance.com/api/v3/ticker/price (全交易对实时价)
        OKX         : www.okx.com/api/v5/market/tickers (全币种ticker)

设计: 多源容错. CoinGecko 主, Binance/OKX 备, 哪个通用于哪个. 全不通友好报错.
注意: 部分沙箱/境内网络封锁境外加密API, 此时会报网络错误 —— 在可访问境外网络的环境(用户本机/服务器)即可正常使用.

用法:
  python3 crypto_data.py price btc eth sol
  python3 crypto_data.py markets --n 10
  python3 crypto_data.py exchanges
  python3 crypto_data.py exchange binance
"""
import os
import sys
import json
import urllib.request
import argparse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# 常见符号 -> CoinGecko id 映射 (顺手覆盖, 避免用户记id)
SYM2ID = {
    "btc": "bitcoin", "eth": "ethereum", "sol": "solana", "bnb": "binancecoin",
    "xrp": "ripple", "ada": "cardano", "doge": "dogecoin", "dot": "polkadot",
    "matic": "matic-network", "avax": "avalanche-2", "link": "chainlink",
    "ton": "the-open-network", "shib": "shiba-inu", "ltc": "litecoin",
    "trx": "tron", "uni": "uniswap", "atom": "cosmos", "near": "near",
    "apt": "aptos", "arb": "arbitrum", "op": "optimism", "fil": "filecoin",
    "usdt": "tether", "usdc": "usd-coin",
}


def _get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.google.com/"})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


# ---------------------------------------------------------------- 主源 CoinGecko

def _cg_simple_price(ids, vs="usd"):
    """CoinGecko simple/price: 按 id 批量拉价. 返回 {symbol_upper: price}."""
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(ids)}&vs_currencies={vs}"
    raw = _get(url)
    j = json.loads(raw)
    out = {}
    for cid, vals in j.items():
        # symbol 不直接给, 用 id 反查映射(未知则留id)
        sym = next((k.upper() for k, v in SYM2ID.items() if v == cid), cid.upper())
        out[sym] = vals.get(vs)
    return out


def _cg_markets(n=10, vs="usd"):
    url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency={vs}&order=market_cap_desc&per_page={n}&page=1"
    return json.loads(_get(url))


def _cg_exchanges():
    return json.loads(_get("https://api.coingecko.com/api/v3/exchanges?per_page=20&page=1"))


def _cg_exchange_detail(ex_id):
    return json.loads(_get(f"https://api.coingecko.com/api/v3/exchanges/{ex_id}"))


# ---------------------------------------------------------------- 备源 Binance / OKX

def _bn_prices(symbols):
    """Binance ticker/price: 全市场或指定. 返回 {SYM: price} (USDT计价)."""
    if symbols:
        out = {}
        for s in symbols:
            sym = s.upper()
            pair = sym if sym.endswith("USDT") else f"{sym}USDT"
            j = json.loads(_get(f"https://api.binance.com/api/v3/ticker/price?symbol={pair}"))
            out[sym] = float(j.get("price", 0))
        return out
    # 全市场 (可能较大)
    arr = json.loads(_get("https://api.binance.com/api/v3/ticker/price"))
    return {x["symbol"].replace("USDT", ""): float(x["price"]) for x in arr if x["symbol"].endswith("USDT")}


def _okx_tickers(symbols):
    """OKX market/tickers: 返回 {SYM: last}."""
    raw = _get("https://www.okx.com/api/v5/market/tickers?instType=SPOT")
    arr = json.loads(raw).get("data", [])
    out = {}
    for x in arr:
        inst = x.get("instId", "")
        if inst.endswith("-USDT"):
            out[inst.replace("-USDT", "")] = float(x.get("last", 0))
    if symbols:
        out = {s.upper(): out.get(s.upper()) for s in symbols}
    return out


# ---------------------------------------------------------------- 统一入口(多源容错)

def get_prices(symbols, vs="usd"):
    """
    统一取价: CoinGecko 主, Binance/OKX 备. 返回 {SYMBOL_UPPER: price_usd}.
    symbols: 列表, 支持 btc/eth/sol 等符号或 CoinGecko id.
    """
    syms = [s.lower() for s in symbols]
    ids = [SYM2ID.get(s, s) for s in syms]  # 符号转id, 未知则原样当id
    # 1) 主源 CoinGecko
    try:
        cg = _cg_simple_price(ids, vs)
        if cg:
            return cg
    except Exception as e:
        print(f"  [crypto] CoinGecko 主源失败: {e}", file=sys.stderr)
    # 2) 备源 Binance
    try:
        bn = _bn_prices(syms)
        if bn:
            return bn
    except Exception as e:
        print(f"  [crypto] Binance 备源失败: {e}", file=sys.stderr)
    # 3) 备源 OKX
    try:
        ok = _okx_tickers(syms)
        if ok:
            return ok
    except Exception as e:
        print(f"  [crypto] OKX 备源失败: {e}", file=sys.stderr)
    raise RuntimeError("所有加密数据源均不可用(可能网络封锁境外API). 在可访问境外网络环境重试.")


# ---------------------------------------------------------------- CLI

def cmd_price(args):
    try:
        prices = get_prices(args.symbols)
    except RuntimeError as e:
        print(f"  ⚠️ {e}")
        return
    print(f"  💰 加密实时价 (USD):")
    for s, p in prices.items():
        print(f"    {s.upper()}: ${p:,.4f}" if p and p < 1 else f"    {s.upper()}: ${p:,.2f}")


def cmd_markets(args):
    try:
        arr = _cg_markets(args.n)
    except Exception as e:
        print(f"  ⚠️ CoinGecko 市场榜失败: {e}")
        return
    print(f"  📊 全市场榜单 (Top {len(arr)}):")
    for c in arr:
        print(f"    {c['symbol'].upper():6} {c['name'][:18]:18} ${c['current_price']:>12,.4f}  24h:{c.get('price_change_percentage_24h',0):+.1f}%")


def cmd_exchanges(args):
    try:
        arr = _cg_exchanges()
    except Exception as e:
        print(f"  ⚠️ 交易所列表失败: {e}")
        return
    print(f"  🏦 交易所 (Top {len(arr)}):")
    for x in arr:
        print(f"    {x.get('name','')[:22]:22} 可信分:{x.get('trust_score',0)}  24h成交量(BTC):{x.get('trade_volume_24h_btc',0):,.1f}")


def cmd_exchange(args):
    try:
        d = _cg_exchange_detail(args.id)
    except Exception as e:
        print(f"  ⚠️ 交易所详情失败: {e}")
        return
    print(f"  🏦 {d.get('name')} 交易所相关数据:")
    print(f"     网址: {d.get('url')}")
    print(f"     24h成交量(BTC): {d.get('trade_volume_24h_btc',0):,.1f}")
    print(f"     上架币种数: {d.get('tickers_count',0)}")
    tickers = d.get("tickers", [])[:8]
    if tickers:
        print(f"     部分上架交易对:")
        for t in tickers:
            print(f"       - {t.get('base','')}/{t.get('target','')}  价${t.get('converted_last',{}).get('usd',0):,.4f}  成交量${t.get('converted_volume',{}).get('usd',0):,.0f}")


def main():
    ap = argparse.ArgumentParser(description="加密数据源 (CoinGecko主·Binance/OKX备·免费全币种)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("price"); p.add_argument("symbols", nargs="+"); p.set_defaults(func=cmd_price)
    m = sub.add_parser("markets"); m.add_argument("--n", type=int, default=10); m.set_defaults(func=cmd_markets)
    e = sub.add_parser("exchanges"); e.set_defaults(func=cmd_exchanges)
    ex = sub.add_parser("exchange"); ex.add_argument("id"); ex.set_defaults(func=cmd_exchange)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
