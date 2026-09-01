"""Task 6: llm_extract 在未配置 LLM 场景的静默性 smoke 测试。"""
from crypto_stocks.research.parsers.llm_extract import (
    extract_records_from_texts, _normalize_parsed,
)


def test_extract_no_client_no_texts_is_empty():
    assert extract_records_from_texts([], client=None) == []


def test_extract_with_texts_but_no_client_is_empty():
    texts = ["Some unparsed news body, but NO LLM configured should be safe."]
    # 没配置 client → 静默 []，不抛任何异常
    out = extract_records_from_texts(texts, client=None)
    assert out == []


def test_normalize_parsed_good_input():
    raw = {
        "institution": "渣打", "coin": "BTC",
        "target_price": 150000, "pub_date": "2024-07-15",
        "rating": "买入", "excerpt": "OK",
    }
    r = _normalize_parsed(raw)
    assert r is not None
    assert r["institution"] == "Standard Chartered"
    assert r["coin"] == "BTC"
    assert r["tier"] == "tier1"
    assert r["rating"] == "bullish"
    assert r["source_type"] == "llm_parse"
    assert isinstance(r["confidence"], float) and 0.7 <= r["confidence"] < 0.9


def test_normalize_parsed_rejects_unknown_firm_and_coin():
    assert _normalize_parsed({"institution": "Random X", "coin": "BTC",
                              "target_price": 100, "pub_date": "2024-01-01"}) is None
    assert _normalize_parsed({"institution": "ARK Invest", "coin": "Fake123",
                              "target_price": 100, "pub_date": "2024-01-01"}) is None
    assert _normalize_parsed({"institution": "ARK Invest", "coin": "BTC",
                              "target_price": -5, "pub_date": "2024-01-01"}) is None
    assert _normalize_parsed({"institution": "ARK Invest", "coin": "BTC",
                              "target_price": 0, "pub_date": "2024-01-01"}) is None
