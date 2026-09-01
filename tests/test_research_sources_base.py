"""sources/base.py 的纯函数单元测试。"""
import json
import os
import tempfile

import pytest

from markets.crypto.research.sources.base import (
    compute_record_id, read_jsonl, append_jsonl_atomic,
    BaseResearchSource, _http_request,
)


# ══ compute_record_id ═══════════════════════════════════════════
def test_compute_record_id_deterministic():
    r1 = {"institution": "Standard Chartered", "coin": "BTC",
          "target_price": 150000, "pub_date": "2024-07-15"}
    r2 = {"institution": "Standard Chartered", "coin": "BTC",
          "target_price": 150000, "pub_date": "2024-07-15"}
    assert compute_record_id(r1) == compute_record_id(r2)
    assert len(compute_record_id(r1)) == 8


def test_compute_record_id_different_on_field_change():
    base = {"institution": "JPMorgan", "coin": "BTC",
            "target_price": 80000, "pub_date": "2024-12-10"}
    id1 = compute_record_id(base)
    changed = dict(base, target_price=80001)
    assert compute_record_id(changed) != id1
    changed2 = dict(base, coin="ETH")
    assert compute_record_id(changed2) != id1


def test_compute_record_id_whitespace_and_case_normalized():
    a = {"institution": "  ARK Invest  ", "coin": "btc",
         "target_price": "1000000.0", "pub_date": "2024-08-14"}
    b = {"institution": "ARK Invest", "coin": "BTC",
         "target_price": 1_000_000, "pub_date": "2024-08-14"}
    assert compute_record_id(a) == compute_record_id(b)


# ══ JSONL 读写 ═══════════════════════════════════════════
def test_read_jsonl_missing_file_empty(tmp_path):
    assert read_jsonl(str(tmp_path / "no.jsonl")) == []


def test_read_jsonl_parses_lines(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join([
        '{"id":"abc1"}',
        '   ',
        '{"id":"def2"}',
        '{broken!',
        '{"id":"last"}',
    ]), encoding="utf-8")
    out = read_jsonl(str(f))
    assert [r.get("id") for r in out] == ["abc1", "def2", "last"]


def test_append_jsonl_atomic_write_and_dedupe(tmp_path):
    kb = tmp_path / "kb.jsonl"
    r1 = {"id": "a1", "institution": "JPMorgan", "tier": "tier1",
          "coin": "BTC", "target_price": 80000.0}
    n1 = append_jsonl_atomic(str(kb), [r1])
    assert n1 == 1
    # 再写同一条 → 去重 0
    n2 = append_jsonl_atomic(str(kb), [r1])
    assert n2 == 0
    # 加一条新的
    r2 = {"id": "a2", "institution": "ARK Invest", "tier": "tier1",
          "coin": "ETH", "target_price": 25000.0}
    n3 = append_jsonl_atomic(str(kb), [r2])
    assert n3 == 1
    assert len(read_jsonl(str(kb))) == 2


def test_append_jsonl_atomic_auto_computes_missing_id_and_filters_tier(tmp_path):
    kb = tmp_path / "kb2.jsonl"
    inputs = [
        # 正常 JPMorgan（tier1，有 ID）
        {"id": None, "institution": "JPMorgan", "coin": "BTC",
         "target_price": 80000, "pub_date": "2024-01-01"},
        # 过滤：unknown 机构
        {"id": None, "institution": "Random Blogger", "coin": "BTC",
         "target_price": 1, "pub_date": "2024-01-01"},
        # 过滤：price = 0
        {"id": None, "institution": "ARK Invest", "coin": "ETH",
         "target_price": 0, "pub_date": "2024-01-01"},
        # 过滤：coin None（Fake123 不在白名单）
        {"id": None, "institution": "Goldman Sachs", "coin": "FAKE123",
         "target_price": 500, "pub_date": "2024-01-01"},
    ]
    written = append_jsonl_atomic(str(kb), inputs)
    assert written == 1
    saved = read_jsonl(str(kb))
    assert saved[0]["id"] and len(saved[0]["id"]) == 8
    assert saved[0]["institution"] == "JPMorgan"


# ══ BaseResearchSource ══════════════════════════════════
class GoodSource(BaseResearchSource):
    source_name = "good"

    def _fetch_coins_impl(self, coins):
        return [
            {"institution": "JPMorgan", "coin": "BTC",
             "target_price": 80000, "pub_date": "2024-12-10",
             "rating": "hold", "source_url": "https://example/a",
             "excerpt": "A good one"},
            {"institution": "Unknown Firm 123", "coin": "BTC",
             "target_price": 1},
            {"institution": "渣打", "coin": "ETH",
             "target_price": 8000, "pub_date": "2024-07-15",
             "rating": "看涨"},
        ]


class CrashingSource(BaseResearchSource):
    source_name = "boom"

    def _fetch_coins_impl(self, coins):
        raise RuntimeError("boom")


def test_base_source_normalizes_and_filters():
    s = GoodSource()
    # fetch_coins 返回 raw；外部调用需要走 _normalize_and_filter_record
    raws = s._fetch_coins_impl(["BTC", "ETH"])
    out = [s._normalize_and_filter_record(r) for r in raws]
    out = [x for x in out if x]
    assert len(out) == 2
    ids = sorted(set(r["id"] for r in out))
    assert len(ids) == 2
    jpm, scb = out
    if jpm["institution"] != "JPMorgan":
        jpm, scb = scb, jpm
    assert jpm["tier"] == "tier1"
    assert jpm["coin"] == "BTC"
    assert jpm["target_currency"] == "USD"
    assert jpm["rating"] == "neutral"  # hold → neutral
    assert 0 <= (jpm.get("confidence") or 0) <= 1
    # 渣打同义映射
    assert scb["institution"] == "Standard Chartered"
    assert scb["coin"] == "ETH"
    assert scb["rating"] == "bullish"


def test_base_source_crashes_silently():
    assert CrashingSource().fetch_coins(["BTC"]) == []


# ══ HTTP 代理环境 ══════════════════════════════════════════
def test_http_request_respects_invalid_url_returns_zero_status():
    code, body = _http_request("")
    assert code == 0
    assert body == ""
    # 假域名在沙箱或无网环境是 code 0；若存在 HTTP_PROXY 可能返回 502/代理错误码
    # 此处断言核心不变：任何情况都不会是 200，body 始终安全（不会抛错）
    code, body = _http_request("http://this-domain-will-never-exist-xyz123.invalid/nothing", timeout=1)
    assert code != 200
    assert isinstance(body, str)
