"""Exchange Research 源：Binance Research / OKX Insights 等交易所研报页。

网络失败→空列表；首日不联网即可用，空列表不影响系统。

修复记录（2026-09-03）：
- 原 ENDPOINTS 写死为前端页面（Binance /en/research?query= 返 202 反爬空体、
  OKX /insights/search 返 404），导致任何币都 0 条。
- 改为交易所真实公开文章 API + 浏览器级 UA/Referer，并在解析层抽取「机构名+币+目标价」。
- 机构标签固定为白名单内的 "Binance Research" / "OKX Insights"（tier2），可过 base 的 tier 门槛。
"""
from __future__ import annotations
import logging
import re
import urllib.parse

from .base import BaseResearchSource

logger = logging.getLogger(__name__)

# 浏览器级请求头，绕过部分 WAF 的裸 UA 拦截
_BROWSER_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.binance.com/",
}

# 交易所研报公开文章 API（前端页面是 JS 渲染，直连拿不到正文）
ENDPOINTS = {
    "binance": "https://www.binance.com/bapi/research/wapi/public/v1/article/latest?pageNo=1&pageSize=20",
    "okx": (
        "https://www.okx.com/priapi/v1/insights/article/list"
        "?categoryId=0&currentPage=1&pageSize=20&language=en-US"
    ),
}

FIRM_BY_LABEL = {
    "binance": "Binance Research",
    "okx": "OKX Insights",
}


class ExchangeResearchSource(BaseResearchSource):
    source_name = "exchange_research"
    source_type = "scrape"

    # ── 价格抽取：标题/摘要里任意 $数字（含 1,000 千分位） ──
    PRICE_RE = re.compile(r"(?:\$|US\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?)")
    # 币符号（大写简写）出现在文本中即认为覆盖该币
    COIN_HINT_RE = re.compile(r"\b(BTC|ETH|SOL|BNB|XRP|ADA|DOGE|DOT|POL|UNI|LTC|"
                               r"LINK|AVAX|AAVE|XLM|TRX|GRAM|BCH|ZEC|FIL|NEAR|APT|"
                               r"INJ|HBAR|ICP|JUP|RAY|GT|OKB|DYDX|HYPE|RENDER|GLM|"
                               r"ONDO|ETHFI|PENDLE|SHIB|PEPE|ARB|TAO)\b")

    def _fetch_coins_impl(self, coins):
        out = []
        wanted = {c.upper() for c in coins if c}
        for label, url in ENDPOINTS.items():
            status, body = self._get(url, headers=_BROWSER_HEADERS)
            if status != 200 or not body:
                logger.info("%s endpoint status=%s, skipped", label, status)
                continue
            out.extend(self._extract(label, body, wanted))
        return out

    # ── 解析：不同源结构不同，统一抽 title/summary 文本后匹配 ──
    def _extract(self, label, body, wanted):
        firm = FIRM_BY_LABEL.get(label)
        if not firm:
            return []
        try:
            data = self._payload_list(body)
        except Exception as e:  # noqa: BLE001
            logger.info("%s parse failed: %s", label, e)
            return []

        results = []
        for item in data:
            title = (item.get("title") or "").strip()
            summary = (item.get("summary") or item.get("desc") or item.get("brief") or "").strip()
            text = f"{title} {summary}"
            if not text.strip():
                continue
            # 哪些目标币出现在本文
            hit_coins = {m.group(1) for m in self.COIN_HINT_RE.finditer(text)} & wanted
            if not hit_coins:
                continue
            prices = sorted({float(m.replace(",", "")) for m in self.PRICE_RE.findall(text) if m},
                            reverse=True)
            prices = [p for p in prices if p > 0]
            # 限每个 coin 最多 3 个价格
            for coin in hit_coins:
                for price in prices[:3]:
                    results.append({
                        "institution": firm,
                        "coin": coin,
                        "target_price": price,
                        "pub_date": (item.get("publishDate") or item.get("published_at")
                                     or item.get("displayDate") or "")[:10],
                        "source_url": item.get("articleUrl") or item.get("url") or item.get("link") or "",
                        "excerpt": (title or summary)[:200],
                    })
        return results

    @staticmethod
    def _payload_list(body: str) -> list[dict]:
        """兼容多种响应结构，提取文章对象列表。"""
        import json
        try:
            j = json.loads(body)
        except json.JSONDecodeError:
            return []
        # Binance: {"code":0,"data":[{...}]}
        if isinstance(j, dict):
            for key in ("data", "list", "items", "results"):
                v = j.get(key)
                if isinstance(v, list):
                    return v
            # OKX: {"data":{"items":[...]}} 或 {"data":[...]}
            inner = j.get("data")
            if isinstance(inner, dict):
                for key in ("items", "list", "articles"):
                    if isinstance(inner.get(key), list):
                        return inner[key]
        if isinstance(j, list):
            return j
        return []
