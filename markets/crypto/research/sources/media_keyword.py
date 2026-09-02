"""源②：加密媒体 RSS 快讯关键词匹配（按设计文档 §7 源② 实现）。

设计口径（docs/superpowers/specs/2026-08-31-crypto-institutional-research-design.md）：
- 源：CoinDesk / The Block / Cointelegraph / Decrypt / BitcoinMagazine 公开 RSS（免费无 key）
- 三重匹配：A=白名单机构 ∩ B=白名单代币 ∩ C=目标价数字，三者齐才产出记录
- 任何源失败静默返回 []，不中断其他源（防御式）

历史教训：初版误用 CryptoPanic（免费 token 被 Cloudflare 403）；
2026-09 曾误入搜索引擎 HTML 抓取（Bing/DDG 反爬限流 202），均非设计本意。
RSS 是结构化 XML、无 WAF，才是设计指定的正确入口。
"""
from __future__ import annotations
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from ..config import (
    TRACKED_INSTITUTIONS, INSTITUTION_SYNONYMS, COIN_ALIASES,
    SUPPORTED_COINS_UPPER,
)
from .base import BaseResearchSource, _http_request

logger = logging.getLogger(__name__)

# 设计文档指定的公开 RSS 源（2026-09-03 实测 3067 代理下全部 200）
RSS_FEEDS: list[tuple[str, str]] = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("BitcoinMagazine", "https://bitcoinmagazine.com/.rss/full/"),
]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.8",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text or "")).strip()


def _word_pattern(term: str, case_sensitive: bool) -> re.Pattern:
    """整词匹配；全大写短词（ARB/BCH/ARK/JPM）强制大小写敏感，防止误命中
    （如 'arb' 误中 arbitrage、'ark' 误中 Arkham）。"""
    flags = 0 if case_sensitive else re.IGNORECASE
    # 含中文/空格的词不能用 \b 首尾，统一用非字母数字边界
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", flags)


def _build_institution_patterns() -> list[tuple[str, re.Pattern]]:
    """返回 [(规范机构名, pattern)]：白名单全名 + 同义词表的 key。"""
    pats: list[tuple[str, re.Pattern]] = []
    seen: set[str] = set()
    for name in TRACKED_INSTITUTIONS:
        if name.lower() not in seen:
            seen.add(name.lower())
            pats.append((name, _word_pattern(name, case_sensitive=name.isupper())))
    for alias, canonical in INSTITUTION_SYNONYMS.items():
        if alias.lower() not in seen and canonical in TRACKED_INSTITUTIONS:
            seen.add(alias.lower())
            pats.append((canonical, _word_pattern(alias, case_sensitive=alias.isupper())))
    # 长名优先，避免短名先吃掉长名的语境
    pats.sort(key=lambda kv: -len(kv[0]))
    return pats


def _build_coin_patterns() -> dict[str, list[re.Pattern]]:
    """返回 {COIN: [patterns]}：符号（大写敏感）+ 别名（含中文/全名，不敏感）。"""
    out: dict[str, list[re.Pattern]] = {}
    for coin in SUPPORTED_COINS_UPPER:
        pats = [_word_pattern(coin, case_sensitive=True)]
        for alias, canonical in COIN_ALIASES.items():
            if canonical == coin:
                pats.append(_word_pattern(alias, case_sensitive=alias.isupper()))
        out[coin] = pats
    return out


_INSTITUTION_PATS = _build_institution_patterns()
_COIN_PATS = _build_coin_patterns()

# C：目标价数字。两类合法形态：
#   1) 显式目标价：「target/forecast/price target (of/to/at) $X」「目标价 $X」
#   2) 预测语境中的 $X：数字附近出现预测动词（sees/predicts/expects/could hit/reach...）
# 铁律防误报（2026-09-03 实证踩坑）："$170 million inflow"（资金流入）、
# "$37M purchase"（买入金额）不是目标价——带 million/billion 量词的一律排除。
_TARGET_OF_RE = re.compile(
    r"(?:price\s+target|target|forecast|目标价)\s*(?:of|to|at|[:：])?\s*"
    r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
_DOLLAR_RE = re.compile(
    r"\$\s*([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)"
)
# 金额量词 / 百分数 → 是资金流或涨跌幅，不是目标价
_MAGNITUDE_RE = re.compile(r"^\s*(?:million|billion|trillion|mn|bn|[mMbBkK])\b")
_PCT_RE = re.compile(r"^\s*%")
# 预测语境词（价格须出现在这些词 ±100 字符内才采信）
_PREDICT_CONTEXT_RE = re.compile(
    r"(?:target|forecast|predict\w*|expect\w*|sees?\b|seeing|could\s+(?:hit|reach|rise|fall)|"
    r"rise[sn]?\s+to|fall(?:s|ing)?\s+to|hit(?:ting)?\s+\$|reach(?:es|ing)?\s+\$|"
    r"by\s+(?:year[\s-]?end|end\s+of|Q[1-4])|年底|目标价|预测|上看|下看)",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")

_BULL_WORDS = re.compile(r"\b(raise[sd]?|hike[sd]?|bullish|rally|upside|soar|surge|上调|看[涨多])\b", re.I)
_BEAR_WORDS = re.compile(r"\b(cut[sd]?|lower[sd]?|bearish|downside|crash|plunge|下调|看跌)\b", re.I)


def _to_float(num: str) -> float | None:
    num = num.replace(",", "")
    if _YEAR_RE.match(num):
        return None
    try:
        val = float(num)
    except ValueError:
        return None
    return val if val > 0 else None


def _extract_price(text: str) -> float | None:
    """提取最可能的目标价：显式 target 形态优先，其次预测语境内的 $ 数字；
    带 million/billion 量词或 % 的金额一律排除（防资金流/涨跌幅误报）。"""
    cands: list[float] = []
    for m in _TARGET_OF_RE.finditer(text):
        val = _to_float(m.group(1))
        if val is not None:
            cands.append(val)
    if cands:
        return max(cands)
    for m in _DOLLAR_RE.finditer(text):
        tail = text[m.end():m.end() + 12]
        if _MAGNITUDE_RE.match(tail) or _PCT_RE.match(tail):
            continue
        val = _to_float(m.group(1))
        if val is None:
            continue
        window = text[max(0, m.start() - 100):m.end() + 100]
        if _PREDICT_CONTEXT_RE.search(window):
            cands.append(val)
    return max(cands) if cands else None


def _guess_rating(text: str) -> str | None:
    if _BULL_WORDS.search(text):
        return "bullish"
    if _BEAR_WORDS.search(text):
        return "bearish"
    return None


def _parse_pub_date(item: ET.Element) -> str | None:
    raw = item.findtext("pubDate") or item.findtext("date") or ""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    return m.group(1) if m else None


class MediaKeywordSource(BaseResearchSource):
    """加密媒体 RSS 关键词源：A∩B∩C 三重匹配产出机构目标价记录。"""

    source_name = "media_keyword"
    source_type = "media_keyword"

    def _fetch_coins_impl(self, coins: list[str]) -> list[dict]:
        wanted = {c.upper() for c in coins}
        out: list[dict] = []
        for feed_name, url in RSS_FEEDS:
            try:
                status, body = _http_request(url, headers=_HEADERS)
            except Exception as e:  # noqa: BLE001
                logger.info("%s %s request error: %s", self.source_name, feed_name, e)
                continue
            if status != 200 or not body:
                logger.info("%s %s http %s", self.source_name, feed_name, status)
                continue
            try:
                root = ET.fromstring(body.encode("utf-8"))
            except ET.ParseError as e:
                logger.info("%s %s xml parse error: %s", self.source_name, feed_name, e)
                continue
            for item in root.iter("item"):
                rec = self._match_item(item, feed_name, wanted)
                if rec:
                    out.append(rec)
        logger.info("%s 命中 %d 条（coins=%s）", self.source_name, len(out), sorted(wanted))
        return out

    def _match_item(self, item: ET.Element, feed_name: str, wanted: set[str]) -> dict | None:
        title = _clean(item.findtext("title") or "")
        desc = _clean(item.findtext("description") or "")
        text = f"{title} {desc}"
        if not title:
            return None

        # A：机构
        institution = None
        for canonical, pat in _INSTITUTION_PATS:
            if pat.search(text):
                institution = canonical
                break
        if not institution:
            return None

        # B：代币（限定在用户请求的 coins 内）
        coin = None
        for c in wanted:
            pats = _COIN_PATS.get(c)
            if pats and any(p.search(text) for p in pats):
                coin = c
                break
        if not coin:
            return None

        # C：目标价
        price = _extract_price(text)
        if price is None:
            return None

        link = (item.findtext("link") or "").strip() or None
        return {
            "institution": institution,
            "coin": coin,
            "target_price": price,
            "pub_date": _parse_pub_date(item),
            "rating": _guess_rating(text),
            "source_url": link,
            "excerpt": f"[{feed_name}] {title}"[:200],
        }
