"""Exchange Research 源桩：Binance Research / OKX Insights 等交易所研报页。

网络失败→空列表；首日不联网即可用，空列表不影响系统。
"""
from __future__ import annotations
import logging
import re
import urllib.parse

from .base import BaseResearchSource

logger = logging.getLogger(__name__)


class ExchangeResearchSource(BaseResearchSource):
    source_name = "exchange_research"
    source_type = "scrape"

    ENDPOINTS = {
        "binance": "https://www.binance.com/en/research?query={coin}",
        "okx":     "https://www.okx.com/insights/search?q={coin}",
    }

    def _fetch_coins_impl(self, coins):
        out = []
        for coin in coins:
            for label, url_tpl in self.ENDPOINTS.items():
                url = url_tpl.format(coin=urllib.parse.quote(coin))
                status, body = self._get(url, headers={
                    "Accept-Language": "en-US,en;q=0.9"
                })
                if status != 200 or not body:
                    continue
                out.extend(self._extract(coin, label, body, url))
        return out

    # ── 非常轻量的解析：任何价格匹配 + 白名单机构匹配即抽出 ──
    PRICE_RE = re.compile(
        r"""(?:target|expect|forecas)?t?\s*(?:price|level|目标价)?[:：]?\s*
            \$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)|[0-9]+(?:\.[0-9]+)?)""",
        re.VERBOSE | re.IGNORECASE,
    )
    FIRM_HINTS = [("Binance Research", "binance"), ("OKX Insights", "okx")]

    def _extract(self, coin, label, body, url):
        results = []
        firm = next((f for f, k in self.FIRM_HINTS if k == label), None)
        if not firm:
            return []
        prices = list({float(m.replace(",", "")) for m in self.PRICE_RE.findall(body or "") if m})
        if not prices:
            return []
        # 限每个 coin 最多 3 个价格
        for price in prices[:3]:
            results.append({
                "institution": firm,
                "coin": coin,
                "target_price": price,
                "pub_date": "",
                "source_url": url,
                "excerpt": f"Auto-extracted from {firm} research page for {coin}",
            })
        return results
