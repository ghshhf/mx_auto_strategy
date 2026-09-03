"""源②：加密媒体 RSS 快讯关键词匹配（按设计文档 §7 源② 实现）。

设计口径（docs/superpowers/specs/2026-08-31-crypto-institutional-research-design.md）：
- 源：CoinDesk / The Block / Cointelegraph / Decrypt / BitcoinMagazine 公开 RSS（免费无 key）
- 两类信号产出：
  (A) 机构目标价记录：A=白名单机构 ∩ B=白名单代币 ∩ C=目标价数字，三者齐才产出
  (B) 广义提及 mention：只要白名单代币被 RSS 命中即产出（新闻 / ETF / 上线 / 监管 /
      机构提及），不要求机构或目标价——满足「别只盯机构」的扩展检索需求
- 任何源失败静默返回 []，不中断其他源（防御式）

历史教训：初版误用 CryptoPanic（免费 token 被 Cloudflare 403）；
2026-09 曾误入搜索引擎 HTML 抓取（Bing/DDG 反爬限流 202），均非设计本意。
RSS 是结构化 XML、无 WAF，才是设计指定的正确入口。
"""
from __future__ import annotations
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

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

# ── 深度检索通道：Google News RSS ────────────────────────────────────────
# 为什么需要它（2026-09-03 实测，BCH 触发）：
#   头部媒体 RSS 只保留最新 10~40 条，窗口仅数小时~数天。123 条样本里 BCH /
#   "Bitcoin Cash" 命中均为 0 —— 这是**窗口宽度问题，不是没消息**。BCH 是
#   2017 年分叉的老牌币，Google News 一查即返回 100 条（跨度 5 月~9 月）。
# Google News RSS 是官方公开 RSS 接口（结构化 XML，非 HTML 抓取），支持任意
# 关键词 + 约 100 条历史，把低热度币的可检索窗口从「数天」拉到「数月」。
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

# 币 → 检索词（全名优先，全名比符号召回高一个量级；符号作兜底）
COIN_QUERY_TERMS: dict[str, str] = {
    "BTC": "Bitcoin BTC", "ETH": "Ethereum ETH", "SOL": "Solana SOL",
    "XRP": "XRP Ripple", "BCH": "Bitcoin Cash BCH", "LTC": "Litecoin LTC",
    "ADA": "Cardano ADA", "AVAX": "Avalanche AVAX", "DOT": "Polkadot DOT",
    "LINK": "Chainlink LINK", "XLM": "Stellar XLM", "TRX": "Tron TRX",
    "DOGE": "Dogecoin DOGE", "SHIB": "Shiba Inu SHIB", "PEPE": "Pepe coin",
    "TON": "Toncoin TON", "NEAR": "NEAR Protocol", "APT": "Aptos APT",
    "ICP": "Internet Computer ICP", "HBAR": "Hedera HBAR", "FIL": "Filecoin FIL",
    "ZEC": "Zcash ZEC", "HYPE": "Hyperliquid HYPE", "ONDO": "Ondo Finance ONDO",
    "TAO": "Bittensor TAO", "RENDER": "Render RNDR", "ARB": "Arbitrum ARB",
    "POL": "Polygon POL", "UNI": "Uniswap UNI", "AAVE": "Aave AAVE",
    "PENDLE": "Pendle PENDLE", "ETHFI": "Ether.fi ETHFI", "INJ": "Injective INJ",
    "JUP": "Jupiter JUP", "RAY": "Raydium RAY", "DYDX": "dYdX",
    "GLM": "Golem GLM", "BNB": "BNB Binance Coin", "OKB": "OKB OKX",
    "GT": "GateToken GT",
}

# 反歧义：Google News 聚合全网，大写符号可能命中同名股票/公司/部门。
# 规则：命中「全名或别名」→ 直接采信；仅命中大写符号 → 要求加密语境共现。
_CRYPTO_CONTEXT_RE = re.compile(
    r"\b(crypto|cryptocurrency|bitcoin|blockchain|token|coin|altcoin|"
    r"defi|blockchain|exchange|wallet|ETF|stablecoin|airdrop|staking)\b",
    re.IGNORECASE,
)

# 噪声标题：Google News 会混入换算页/计算器/行情挂件等垃圾条目
_NOISE_TITLE_RE = re.compile(
    r"(?:\bconvert\b.{0,40}\bto\b|\bprice\s+today\b|calculator|"
    r"\bhow\s+to\s+buy\b|\bexchange\s+rate\b|\bstock\s+trades\b)",
    re.IGNORECASE,
)

# 稳定性参数（2026-09-03 全币实测标定）：
# 40 币连续请求时，Google News 间歇性超时（默认 10s timeout 偏紧），
# 失败被静默跳过 —— 表现为 BCH/APT/BNB 等币"0 提及"，极易误判为"没消息"。
# 故：单次用更长超时 + 失败退避重试 + 币间间隔。
_GN_TIMEOUT = 25
_GN_RETRIES = 2
_GN_SLEEP = 0.4

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


def _build_coin_name_patterns() -> dict[str, list[re.Pattern]]:
    """只含「全名/别名」pattern，排除与符号仅大小写差异的条目（如 bch/BCH）。

    用途：Google News 反歧义 —— 区分「命中真实全名」与「仅命中大写符号」。
    若不排除同形小写别名，符号命中会被误判为全名命中，反歧义形同虚设。
    """
    out: dict[str, list[re.Pattern]] = {}
    for coin in SUPPORTED_COINS_UPPER:
        out[coin] = [
            _word_pattern(alias, case_sensitive=alias.isupper())
            for alias, canonical in COIN_ALIASES.items()
            if canonical == coin and alias.lower() != coin.lower()
        ]
    return out


def _pick_coin(text: str, wanted: set[str]) -> str | None:
    """在所有命中的币里，按「匹配到的最长别名」决定归属，而非先到先得。

    历史坑（2026-09-03 多币实测）：wanted 是 set，遍历顺序不确定，
    BTC 的别名 'bitcoin' 会先吃掉 'Bitcoin Cash'，导致 BCH 在
    `fetch --coins BCH,LTC,XRP,SOL,BTC` 时整批消失（0 条）。
    长名优先即可解决：'bitcoin cash'(12) > 'bitcoin'(7)。
    """
    best: str | None = None
    best_len = -1
    for c in wanted:
        for p in _COIN_PATS.get(c, []):
            m = p.search(text)
            if m and len(m.group(0)) > best_len:
                best, best_len = c, len(m.group(0))
    return best


_INSTITUTION_PATS = _build_institution_patterns()
_COIN_PATS = _build_coin_patterns()
_COIN_NAME_PATS = _build_coin_name_patterns()

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

# mention 分类正则（仅用于广义信号归类，不影响目标价抽取）
# ETF：必须含复数（"ETFs" 是主流写法，\bETF\b 会整批漏掉）
_ETF_RE = re.compile(r"\bETFs?\b", re.IGNORECASE)
_REGULATORY_RE = re.compile(
    r"\b(SEC|CFTC|regulat\w*|lawsuit|settlement|cease\s*(?:and\s*desist)?|subpoena|"
    r"enforcement|ban(?:ned)?|prohibit\w*)\b", re.IGNORECASE)
_ETP_RE = re.compile(r"\b(ETP|trust|fund)\b", re.IGNORECASE)
# 行情波动报道：涨跌/新高/新低/市值。单独成类，便于与「实质消息」区分
_PRICE_MOVE_RE = re.compile(
    r"(\b(?:up|down|surge[sd]?|soar\w*|slump\w*|sink[sn]?|drop(?:s|ped)?|"
    r"fall(?:s|ing)?|rally|rallies|jump(?:s|ed)?|plunge[sd]?|crash\w*|slide[sn]?|"
    r"gain[sn]?|los(?:e|es|t)|climb[sn]?|retreat\w*|rebound\w*|dip(?:s|ped)?)\b"
    r"|\b(?:all-time\s+high|ATH|record\s+high|record\s+low)\b"
    r"|[+-]?\d+(?:\.\d+)?\s*%)",
    re.IGNORECASE,
)
# 链上/采用/生态实质进展
_ADOPTION_RE = re.compile(
    r"\b(adoption|integrat\w*|partner\w*|merchant|payment|upgrade|hard\s*fork|"
    r"halving|network\s+activity|transaction\s+volume|active\s+address|"
    r"treasury|holdings?|accumulat\w*)\b",
    re.IGNORECASE,
)
_LISTING_RE = re.compile(
    r"(listed|listing|上线|launch(?:ed|ing)?\s+on|goes\s+live|debut|上线交易|"
    r"lists?\s+on|added\s+to)", re.IGNORECASE)

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

        # B：代币（限定在用户请求的 coins 内）—— 长名优先，决定这条归哪个币
        coin = _pick_coin(text, wanted)
        if not coin:
            return None
        return self._resolve(item, feed_name, coin, title, text)

    def _resolve(self, item: ET.Element, feed_name: str, coin: str,
                 title: str, text: str) -> dict | None:
        """已确定 coin 后，判机构目标价 or 广义提及。"""
        # A：机构（白名单）
        institution = None
        for canonical, pat in _INSTITUTION_PATS:
            if pat.search(text):
                institution = canonical
                break

        # C：目标价（仅当命中机构时才视为机构目标价，避免无来源的价格噪声）
        price = _extract_price(text) if institution else None
        if institution and price is not None:
            link = (item.findtext("link") or "").strip() or None
            return {
                "record_type": "target_price",
                "institution": institution,
                "coin": coin,
                "target_price": price,
                "pub_date": _parse_pub_date(item),
                "rating": _guess_rating(text),
                "source_url": link,
                "excerpt": f"[{feed_name}] {title}"[:200],
            }

        # 非机构目标价 → 广义信号（新闻 / ETF / 上线 / 监管 / 机构提及）。
        # 这是「别只盯机构」的扩展检索：只要代币被 RSS 命中即记录，不要求机构或价格。
        return self._build_mention(item, feed_name, coin, institution, title, text)

    def _build_mention(self, item: ET.Element, feed_name: str, coin: str,
                       institution: str | None, title: str, text: str) -> dict:
        category = _classify_mention(text, institution)
        link = (item.findtext("link") or "").strip() or None
        return {
            "record_type": "mention",
            "coin": coin,
            "category": category,
            "institution": institution,
            "title": title,
            "source": feed_name,
            "pub_date": _parse_pub_date(item),
            "source_url": link,
            "excerpt": f"[{feed_name}] {title}"[:200],
        }


def _classify_mention(text: str, institution: str | None) -> str:
    """把广义提及归到最具体的类别。

    优先级（越靠前越"实质"）：
      ETF > 监管 > 上线 > 机构提及 > 采用/生态 > 行情波动 > 新闻
    这样「Bitcoin Cash Drops 3%」归 price_move，不会与实质进展混为一谈。
    """
    if _ETF_RE.search(text):
        return "etf"
    if _REGULATORY_RE.search(text):
        return "regulatory"
    if _LISTING_RE.search(text):
        return "listing"
    if institution:
        return "institution_mention"
    if _ADOPTION_RE.search(text):
        return "adoption"
    if _PRICE_MOVE_RE.search(text):
        return "price_move"
    return "news"


def _coin_query(coin: str) -> str:
    """返回该币的检索词：优先显式配置，回退「全名别名 or 符号」。
    全名比符号召回高一个量级（英文媒体多写全名）。"""
    q = COIN_QUERY_TERMS.get(coin.upper())
    if q:
        return q
    # 从别名里挑最长的英文全名（去中文）
    names = [a for a, c in COIN_ALIASES.items() if c == coin and re.search(r"[A-Za-z]", a)]
    if names:
        longest = max(names, key=len)
        return f"{longest} {coin}"
    return coin


class GoogleNewsSource(MediaKeywordSource):
    """Google News RSS 关键词检索源（深度通道）。

    与 MediaKeywordSource 的差异：
      1) 每个请求币生成独立检索 URL（全名 + 符号），而非读固定媒体首页；
      2) 窗口约 100 条 / 数月，补齐头部 RSS「仅最新数十条」的盲区；
      3) 反歧义（同名股票/公司）+ 噪声标题过滤，因为 Google News 聚合全网。
    匹配与归类逻辑完全复用父类（机构目标价 / 广义提及同一口径）。
    """

    source_name = "google_news"
    source_type = "media_keyword"

    # 本轮请求失败的检索词。供 CLI 提示，用于区分
    # 「该币确实没消息」与「抓取失败导致 0 条」—— 后者极易被误读为前者。
    last_failed: list[str] = []

    def _fetch_with_retry(self, url: str, q: str) -> tuple[int, str]:
        """带退避重试的单次抓取。Google News 响应偏慢，且偶发限流/超时；
        失败必须可观测（记 logger），否则会表现为"该币没有消息"的假象。"""
        for attempt in range(1, _GN_RETRIES + 2):
            try:
                status, body = _http_request(url, headers=_HEADERS,
                                             timeout=_GN_TIMEOUT)
            except Exception as e:  # noqa: BLE001
                logger.info("%s %s attempt %d error: %s",
                            self.source_name, q, attempt, e)
                status, body = 0, ""
            if status == 200 and body:
                return status, body
            logger.info("%s %s attempt %d -> http %s",
                        self.source_name, q, attempt, status)
            if attempt <= _GN_RETRIES:
                time.sleep(_GN_SLEEP * attempt)
        return 0, ""

    def _fetch_coins_impl(self, coins: list[str]) -> list[dict]:
        wanted = {c.upper() for c in coins}
        out: list[dict] = []
        self.last_failed = []
        for i, coin in enumerate(sorted(wanted)):
            q = _coin_query(coin)
            if not q:
                continue
            if i:  # 币间间隔，降低连续请求被限流的概率
                time.sleep(_GN_SLEEP)
            url = GOOGLE_NEWS_RSS.format(query=quote(q))
            status, body = self._fetch_with_retry(url, q)
            if status != 200 or not body:
                logger.warning("%s %s 全部重试失败(http %s) —— 该币本轮无数据",
                               self.source_name, q, status)
                self.last_failed.append(f"{coin}({q})")
                continue
            try:
                root = ET.fromstring(body.encode("utf-8"))
            except ET.ParseError as e:
                logger.info("%s %s xml parse error: %s", self.source_name, q, e)
                continue
            for item in root.iter("item"):
                rec = self._match_item(item, f"GoogleNews/{q}", wanted)
                if rec:
                    out.append(rec)
        logger.info("%s 命中 %d 条（coins=%s）", self.source_name, len(out), sorted(wanted))
        return out

    def _match_item(self, item: ET.Element, feed_name: str, wanted: set[str]) -> dict | None:
        title = _clean(item.findtext("title") or "")
        desc = _clean(item.findtext("description") or "")
        text = f"{title} {desc}"
        if not title or _NOISE_TITLE_RE.search(title):
            return None

        coin = _pick_coin(text, wanted)
        if coin is None:
            return None
        # 是否命中「全名/别名」（排除与符号同形的小写别名，见 _build_coin_name_patterns）
        matched_by_name = any(p.search(text) for p in _COIN_NAME_PATS.get(coin, []))
        # 仅靠大写符号命中（如同名股票 BCH、公司 GLM）且无加密语境 → 判为噪声
        if not matched_by_name and not _CRYPTO_CONTEXT_RE.search(text):
            return None
        return self._resolve(item, feed_name, coin, title, text)
