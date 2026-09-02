"""源 3：PriceTarget 聚合（基于 CoinGecko 币种描述抽取机构提及+目标价）。

网络失败/空 → []；绝不伪造任何值。

修复记录（2026-09-03）：
- 原 FIRM 正则只覆盖 10 个机构，漏掉白名单其余成员；改为复用 config.TRACKED_INSTITUTIONS 全量匹配。
- 注意：CoinGecko 描述为中性百科文字，极少含「机构名+具体目标价」，本源对绝大多数币天然 0 条，
  属数据源限制（非代码 bug）。若需真实分析师目标价，应使用 Messari/Glassnode/CryptoPanic 等
  需 key 的研报 API（见 media_keyword / exchange_research 的接入方式）。
"""
from __future__ import annotations
import json
import logging
import re

from .base import BaseResearchSource
from ..config import TRACKED_INSTITUTIONS

logger = logging.getLogger(__name__)


class PriceTargetAggSource(BaseResearchSource):
    source_name = "price_target_agg"
    source_type = "scrape"

    COINGECKO_COIN_API = "https://api.coingecko.com/api/v3/coins/{coin_lower}?tickers=false&community_data=false&developer_data=false"

    COIN_MAP = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
        "DOGE": "dogecoin", "DOT": "polkadot", "POL": "polygon",
        "UNI": "uniswap", "LTC": "litecoin", "LINK": "chainlink",
        "AVAX": "avalanche-2", "AAVE": "aave", "XLM": "stellar",
        "TRX": "tron", "GRAM": "the-open-network", "BCH": "bitcoin-cash",
        "ZEC": "zcash", "FIL": "filecoin", "NEAR": "near",
        "APT": "aptos", "INJ": "injective-protocol",
        "HBAR": "hedera-hashgraph", "ICP": "internet-computer",
        "JUP": "jupiter-exchange-solana", "RAY": "raydium",
        "GT": "gatechain-token", "OKB": "okb", "DYDX": "dydx-v4",
        "HYPE": "hyperliquid", "GLM": "golem", "RENDER": "render-token",
        "ONDO": "ondo-finance", "ETHFI": "ether-fi",
        "PENDLE": "pendle", "TAO": "bittensor",
        "SHIB": "shiba-inu", "PEPE": "pepe", "ARB": "arbitrum",
    }

    # 机构词（复用白名单全量，描述中出现此类词 + 数字价才产出）
    FIRM = re.compile("|".join(re.escape(f) for f in TRACKED_INSTITUTIONS), re.IGNORECASE)
    TARGET = re.compile(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+))")

    def _fetch_coins_impl(self, coins):
        out = []
        for coin in coins:
            cg_id = self.COIN_MAP.get(coin)
            if not cg_id:
                continue
            status, body = self._get(self.COINGECKO_COIN_API.format(coin_lower=cg_id))
            if status != 200 or not body:
                continue
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                continue
            description = (data.get("description") or {}).get("en") or ""
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", description) if len(s) > 10]
            for s in sentences:
                fmatch = self.FIRM.search(s)
                if not fmatch:
                    continue
                pmatches = self.TARGET.findall(s)
                if not pmatches:
                    continue
                try:
                    price = max(float(p.replace(",", "")) for p in pmatches)
                except ValueError:
                    continue
                if price <= 0:
                    continue
                out.append({
                    "institution": fmatch.group(1),
                    "coin": coin,
                    "target_price": price,
                    "pub_date": "",
                    "source_url": f"https://www.coingecko.com/en/coins/{cg_id}",
                    "excerpt": s[:200],
                })
        return out
