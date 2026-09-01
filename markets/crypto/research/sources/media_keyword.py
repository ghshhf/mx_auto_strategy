"""源桩 2：财经媒体关键词搜索（CoinTelegraph / CryptoPanic）。

不联网时返回空列表，不阻断流程。"""
from __future__ import annotations
import json
import logging
import re

from .base import BaseResearchSource

logger = logging.getLogger(__name__)


class MediaKeywordSource(BaseResearchSource):
    source_name = "media_keyword"
    source_type = "scrape"

    CRYPTOPANIC = "https://cryptopanic.com/api/v1/posts/?auth_token=FREE&currencies={coins}&filter=important"

    def _fetch_coins_impl(self, coins):
        joined = ",".join(c for c in coins if c)
        if not joined:
            return []
        url = self.CRYPTOPANIC_API(joined)
        status, body = self._get(url)
        return self._parse_json(coins, body, url)

    def CRYPTOPANIC_API(self, coins):
        return self.CRYPTOPANIC.format(coins=coins)

    TOKEN_PRICE_RE = re.compile(
        r"(BTC|ETH|SOL|BNB|XRP).{0,80}?\$?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+))",
        re.IGNORECASE,
    )
    FIRM_RE = re.compile(
        r"(Standard Chartered|JPMorgan|Goldman Sachs|Morgan Stanley|ARK Invest|"
        r"Fidelity|BlackRock|Galaxy Digital|Binance Research|OKX Insights|Coinbase|"
        r"VanEck|Messari|Delphi Digital|Fundstrat|Pantera)",
        re.IGNORECASE,
    )

    def _parse_json(self, coins, body, url):
        out = []
        if not body:
            return []
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {"results": []}
        results = data.get("results") or []
        for item in results[:15]:
            title = item.get("title") or ""
            # 简单解析：标题中是否有机构名 + 币 + 价格
            firms = {m.group(1).strip().lower() for m in self.FIRM_RE.finditer(title)}
            if not firms:
                continue
            for m in self.TOKEN_PRICE_RE.finditer(title):
                coin = m.group(1).upper()
                if coin not in coins:
                    continue
                try:
                    price = float(m.group(2).replace(",", ""))
                except ValueError:
                    continue
                out.append({
                    "institution": next(iter(firms)).title(),
                    "coin": coin,
                    "target_price": price,
                    "pub_date": (item.get("published_at") or "")[:10],
                    "source_url": item.get("url") or url,
                    "excerpt": title[:200],
                })
        return out
