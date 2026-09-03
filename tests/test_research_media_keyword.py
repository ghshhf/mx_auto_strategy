"""media_keyword 源：机构目标价 + 广义提及(mention) 双信号单元测试。

另含 GoogleNewsSource（深度检索通道）的反歧义与噪声过滤用例。
"""
import xml.etree.ElementTree as ET

from markets.crypto.research.sources.media_keyword import (
    MediaKeywordSource, GoogleNewsSource, _classify_mention, _coin_query,
)
from markets.crypto.research.sources.base import (
    compute_mention_id, append_jsonl_atomic, read_jsonl,
)


def _mk_item(title, desc="", link="https://x/", pub="2026-09-01"):
    item = ET.Element("item")
    ET.SubElement(item, "title").text = title
    ET.SubElement(item, "description").text = desc
    ET.SubElement(item, "link").text = link
    ET.SubElement(item, "pubDate").text = pub
    return item


# ══ _classify_mention ═══════════════════════════════════════
def test_classify_mention_priority_order():
    # ETF > 监管 > 上线 > 机构提及 > 采用 > 行情 > 新闻
    assert _classify_mention("Bitcoin ETFs see record inflows", None) == "etf"
    # 复数 ETFs 必须命中（历史坑：\bETF\b 会整批漏掉 ETFs）
    assert _classify_mention("Spot ETFs approval expected", None) == "etf"
    assert _classify_mention("SEC lawsuit against exchange", None) == "regulatory"
    assert _classify_mention("Token gets listed on Binance", None) == "listing"
    assert _classify_mention("Goldman says the network is undervalued", "Goldman Sachs") == "institution_mention"
    assert _classify_mention("Merchant adoption doubles this quarter", None) == "adoption"
    assert _classify_mention("Bitcoin Cash Drops 3% Amid Pullback", None) == "price_move"
    assert _classify_mention("Developer ecosystem grows", None) == "news"


# ══ _match_item：双信号 ═════════════════════════════════════
def test_match_item_returns_mention_for_bch_news():
    src = MediaKeywordSource()
    item = _mk_item("Bitcoin Cash adds privacy upgrade for on-chain payments")
    rec = src._match_item(item, "Decrypt", {"BCH"})
    assert rec is not None
    assert rec["record_type"] == "mention"
    assert rec["coin"] == "BCH"
    assert rec["title"]


def test_match_item_matches_bch_full_name():
    """英文媒体写 'Bitcoin Cash' 而非 BCH —— 全名别名必须召回。"""
    src = MediaKeywordSource()
    item = _mk_item("Bitcoin Cash ETF application rumored as payments heat up")
    rec = src._match_item(item, "Cointelegraph", {"BCH"})
    assert rec["record_type"] == "mention"
    assert rec["coin"] == "BCH"
    assert rec["category"] == "etf"


def test_match_item_returns_target_price_when_institution_and_price():
    src = MediaKeywordSource()
    item = _mk_item("Standard Chartered sets BTC price target of $150000 by year end")
    rec = src._match_item(item, "CoinDesk", {"BTC"})
    assert rec is not None
    assert rec.get("record_type") != "mention"  # target_price 记录
    assert rec["institution"] == "Standard Chartered"
    assert rec["coin"] == "BTC"
    assert rec["target_price"] == 150000


def test_match_item_none_when_coin_not_wanted():
    src = MediaKeywordSource()
    item = _mk_item("Bitcoin hits new high")  # BTC 但 wanted 只有 BCH
    assert src._match_item(item, "CoinDesk", {"BCH"}) is None


# ══ GoogleNewsSource：反歧义 + 噪声过滤 ═══════════════════════
def test_google_news_coin_query_prefers_full_name():
    assert _coin_query("BCH") == "Bitcoin Cash BCH"
    assert _coin_query("BTC") == "Bitcoin BTC"
    assert _coin_query("NOT_A_COIN") == "NOT_A_COIN"


def test_google_news_rejects_noise_title():
    src = GoogleNewsSource()
    item = _mk_item("Convert 1 Bitcoin Cash (BCH) to USD (United States Dollar)")
    assert src._match_item(item, "GoogleNews/Bitcoin Cash BCH", {"BCH"}) is None


def test_google_news_accepts_full_name_hit():
    src = GoogleNewsSource()
    item = _mk_item("Bitcoin Cash sinks 12% in a week: can bulls stop BCH")
    rec = src._match_item(item, "GoogleNews/Bitcoin Cash BCH", {"BCH"})
    assert rec is not None
    assert rec["coin"] == "BCH"
    assert rec["category"] == "price_move"


def test_google_news_rejects_symbol_only_without_crypto_context():
    """仅靠大写符号命中（同名股票/公司）且无加密语境 → 判噪声。"""
    src = GoogleNewsSource()
    item = _mk_item("BCH Corp announces quarterly dividend")  # 无 crypto 语境
    assert src._match_item(item, "GoogleNews/Bitcoin Cash BCH", {"BCH"}) is None


def test_google_news_accepts_symbol_only_with_crypto_context():
    src = GoogleNewsSource()
    item = _mk_item("BCH token volume spikes across crypto exchanges")
    rec = src._match_item(item, "GoogleNews/Bitcoin Cash BCH", {"BCH"})
    assert rec is not None
    assert rec["coin"] == "BCH"


# ══ mention 知识库写入 ═════════════════════════════════════
def test_append_jsonl_atomic_writes_mention(tmp_path):
    kb = tmp_path / "mentions.jsonl"
    m = {
        "record_type": "mention", "coin": "BCH", "category": "news",
        "title": "Bitcoin Cash partners with payments startup",
        "source": "Decrypt", "pub_date": "2026-09-01",
        "source_url": "https://decrypt.co/x",
    }
    n = append_jsonl_atomic(str(kb), [m])
    assert n == 1
    saved = read_jsonl(str(kb))
    assert saved[0]["id"] and len(saved[0]["id"]) == 8
    assert saved[0]["record_type"] == "mention"
    assert saved[0]["coin"] == "BCH"
    # 重复 → 0
    assert append_jsonl_atomic(str(kb), [m]) == 0


def test_append_jsonl_atomic_rejects_mention_unknown_coin(tmp_path):
    kb = tmp_path / "mentions.jsonl"
    m = {"record_type": "mention", "coin": "FAKE123", "category": "news",
         "title": "x", "source": "Decrypt"}
    assert append_jsonl_atomic(str(kb), [m]) == 0


def test_compute_mention_id_deterministic():
    a = {"coin": "BCH", "category": "news", "title": "Bitcoin Cash partners",
         "source_url": "https://x", "pub_date": "2026-09-01"}
    b = dict(a)
    assert compute_mention_id(a) == compute_mention_id(b)
    assert len(compute_mention_id(a)) == 8
