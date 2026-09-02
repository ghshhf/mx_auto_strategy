"""源 2：财经媒体/新闻关键词搜索（CryptoPanic）。

不联网时返回空列表，不阻断流程。

修复记录（2026-09-03）：
- 原代码把 `auth_token=FREE` 硬编码进 URL，CryptoPanic 对匿名 FREE token 返回 403（Cloudflare 拦），
  导致任何币都 0 条。
- 改为从环境变量 `CRYPTOPANIC_TOKEN` 读取真实 token（cryptopanic.com 免费注册即得）；
  未配置则明确跳过并提示，不再静默 0。
"""
from __future__ import annotations
import json
import logging
import os
import re

from .base import BaseResearchSource

logger = logging.getLogger(__name__)


class MediaKeywordSource(BaseResearchSource):
    source_name = "media_keyword"
    source_type = "scrape"

    BASE = "https://cryptopanic.com/api/v1/posts/?auth_token={token}&currencies={coins}&filter=important"

    def _fetch_coins_impl(self, coins):
        token = (os.environ.get("CRYPTOPANIC_TOKEN") or "").strip()
        if not token:
            logger.info("CRYPTOPANIC_TOKEN 未配置，跳过 media_keyword 源")
            return []
        joined = ",".join(c for c in coins if c)
        if not joined:
            return []
        url = self.BASE.format(token=token, coins=joined)
        status, body = self._get(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)",
        })
        if status != 200 or not body:
            logger.info("cryptopanic status=%s, skipped", status)
            return []
        return self._parse_json(coins, body, url)

    COIN_RE = re.compile(
        r"\b(BTC|ETH|SOL|BNB|XRP|ADA|DOGE|DOT|POL|UNI|LTC|"
        r"LINK|AVAX|AAVE|XLM|TRX|GRAM|BCH|ZEC|FIL|NEAR|APT|"
        r"INJ|HBAR|ICP|JUP|RAY|GT|OKB|DYDX|HYPE|RENDER|GLM|"
        r"ONDO|ETHFI|PENDLE|SHIB|PEPE|ARB|TAO)\b",
        re.IGNORECASE,
    )
    PRICE_RE = re.compile(r"(?:\$|US\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?)")
    FIRM_RE = re.compile(
        r"(Standard Chartered|JPMorgan|Goldman Sachs|Morgan Stanley|ARK Invest|"
        r"Fidelity|BlackRock|Galaxy Digital|Binance Research|OKX Insights|Coinbase|"
        r"VanEck|Messari|Delphi Digital|Fundstrat|Pantera|Bitwise|21Shares|"
        r"Canary Capital|Grayscale|Bernstein|Matrixport|Cantor Fitzgerald|"
        r"Kraken Intelligence|Coinbase Research)",
        re.IGNORECASE,
    )

    def _parse_json(self, coins, body, url):
        out = []
        if not body:
            return []
        wanted = {c.upper() for c in coins if c}
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {"results": []}
        results = data.get("results") or []
        for item in results[:15]:
            title = item.get("title") or ""
            # 标题需同时含：机构名 + 目标币 + 价格
            firms = {m.group(1).strip().lower() for m in self.FIRM_RE.finditer(title)}
            if not firms:
                continue
            coins_in = {m.group(1).upper() for m in self.COIN_RE.finditer(title)} & wanted
            if not coins_in:
                continue
            prices = sorted({float(p.replace(",", "")) for p in self.PRICE_RE.findall(title) if p},
                            reverse=True)
            prices = [p for p in prices if p > 0]
            if not prices:
                continue
            for coin in coins_in:
                for price in prices[:3]:
                    out.append({
                        "institution": self._pick_firm(firms),
                        "coin": coin,
                        "target_price": price,
                        "pub_date": (item.get("published_at") or "")[:10],
                        "source_url": item.get("url") or url,
                        "excerpt": title[:200],
                    })
        return out

    @staticmethod
    def _pick_firm(firms):
        # 优先返回白名单精确名（title() 仅首字母大写，足够 base 归一）
        name = next(iter(firms))
        return name.title()
