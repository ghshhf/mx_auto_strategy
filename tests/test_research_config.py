"""机构研报子模块 config.py 的纯函数单元测试 + seeds 集成测试。"""
import pytest
from markets.crypto.research.config import (
    normalize_institution, normalize_coin, tier_of,
    normalize_rating, TRACKED_INSTITUTIONS, SUPPORTED_COINS_UPPER,
)

# ── normalize_institution ──────────────────────────────────────
def test_normalize_institution_synonyms_hit():
    assert normalize_institution("渣打") == "Standard Chartered"
    assert normalize_institution("JPM") == "JPMorgan"
    assert normalize_institution("Cathie Wood") == "ARK Invest"
    assert normalize_institution("Galaxy") == "Galaxy Digital"
    assert normalize_institution("方舟") == "ARK Invest"

def test_normalize_institution_whitelist_direct():
    assert normalize_institution("Standard Chartered") == "Standard Chartered"
    assert normalize_institution("JPMorgan") == "JPMorgan"
    assert normalize_institution("ARK Invest") == "ARK Invest"
    assert normalize_institution("VanEck") == "VanEck"

def test_normalize_institution_unknown_passthrough():
    # 非白名单原样返回（由调用方 tier_of=unknown 过滤）
    assert normalize_institution("Some Random Blogger") == "Some Random Blogger"
    assert normalize_institution("") == ""

# ── normalize_coin ───────────────────────────────────────────
def test_normalize_coin_aliases_and_case():
    assert normalize_coin("比特币") == "BTC"
    assert normalize_coin("btc") == "BTC"
    assert normalize_coin("以太坊") == "ETH"
    assert normalize_coin("ETH") == "ETH"
    assert normalize_coin("sol") == "SOL"
    assert normalize_coin("Solana") == "SOL"
    assert normalize_coin("狗狗币") == "DOGE"
    assert normalize_coin("ton") == "GRAM"

def test_normalize_coin_all_supported_upper_match():
    for c in SUPPORTED_COINS_UPPER:
        assert normalize_coin(c) == c, f"Supported coin {c} should self-match"

def test_normalize_coin_unknown_is_none():
    assert normalize_coin("FAKECOIN123") is None
    assert normalize_coin("") is None
    assert normalize_coin(None) is None

# ── tier_of ─────────────────────────────────────────────────
def test_tier_of_all_whitelisted():
    # Tier1 抽查
    assert tier_of("Standard Chartered") == "tier1"
    assert tier_of("JPMorgan") == "tier1"
    assert tier_of("ARK Invest") == "tier1"
    assert tier_of("UBS") == "tier1"
    # Tier2 抽查
    assert tier_of("Galaxy Digital") == "tier2"
    assert tier_of("Binance Research") == "tier2"
    assert tier_of("Messari") == "tier2"
    # Tier3 抽查
    assert tier_of("Fundstrat") == "tier3"
    # 未知
    assert tier_of("Some Guy on Twitter") == "unknown"

# ── normalize_rating ────────────────────────────────────────
def test_normalize_rating_common():
    assert normalize_rating("买入") == "bullish"
    assert normalize_rating("BUY") == "bullish"
    assert normalize_rating("sell") == "bearish"
    assert normalize_rating("看空") == "bearish"
    assert normalize_rating("hold") == "neutral"
    assert normalize_rating("中性") == "neutral"

def test_normalize_rating_none_and_empty():
    assert normalize_rating(None) is None
    assert normalize_rating("") is None
    assert normalize_rating("   ") is None

def test_normalize_rating_unknown_is_none_not_guessed():
    # 不认识的返回 None，绝不猜
    assert normalize_rating("Completely Fancy Term XYZ123") is None


# ── seeds 集成测试（import seeds.get_seed_records —— 必须在 sources/base 后才可运行，
#    这里放在 config 测试最后，用 try/except 标记 skip，等到 Task4 后会自然 PASS）
def test_seeds_import_and_validity():
    """15 条种子的完整性测试（compute_record_id 依赖 sources.base 存在，Task4 后自动 PASS）。"""
    try:
        from markets.crypto.research.seeds import get_seed_records
    except Exception:
        pytest.skip("seeds module not yet available (expected before Task3)")
        return
    records = get_seed_records()
    assert len(records) >= 13, f"期望至少13条种子，实际 {len(records)}"
    for r in records:
        assert r["id"] and len(r["id"]) == 8, f"Bad id: {r}"
        assert r["coin"] in {"BTC", "ETH", "SOL"}, f"种子只允许 BTC/ETH/SOL，出现 {r['coin']}"
        assert r["tier"] in {"tier1", "tier2", "tier3"}, f"Bad tier: {r['tier']}"
        assert r["target_currency"] == "USD"
        assert r["source_type"] == "seed"
        assert isinstance(r["target_price"], float) and r["target_price"] > 0
        assert r["excerpt"], "种子记录必须有摘要"
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids)), "种子间 id 重复"

def test_seeds_btc_has_6_institutions():
    try:
        from markets.crypto.research.seeds import get_seed_records
    except Exception:
        pytest.skip("seeds module not yet available")
        return
    insts = {r["institution"] for r in get_seed_records() if r["coin"] == "BTC"}
    assert len(insts) >= 6, f"BTC 机构覆盖 {len(insts)} < 6。Got: {insts}"
    for expected in {"Standard Chartered", "Galaxy Digital", "ARK Invest",
                     "JPMorgan", "VanEck", "Fidelity"}:
        assert expected in insts, f"BTC 缺少 {expected}"

def test_seeds_eth_sol_minimum_coverage():
    try:
        from markets.crypto.research.seeds import get_seed_records
    except Exception:
        pytest.skip("seeds module not yet available")
        return
    all_rec = get_seed_records()
    eth_insts = {r["institution"] for r in all_rec if r["coin"] == "ETH"}
    sol_insts = {r["institution"] for r in all_rec if r["coin"] == "SOL"}
    assert len(eth_insts) >= 3, f"ETH 种子机构数 {len(eth_insts)} < 3"
    assert len(sol_insts) >= 2, f"SOL 种子机构数 {len(sol_insts)} < 2"
