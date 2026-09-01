"""aggregate.py —— 9+ 个单元测试。"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pytest

from markets.crypto.research.aggregate import (
    analyze_coins, latest, build_report, _bucket_of, _horizon_months,
)

# ── 构造测试用 records ──────────────────────────────────────────
TODAY = datetime.now(timezone.utc).date()

def _mk(id, inst, coin, price, pub_offset_days, horizon_months, tier="tier1"):
    pub_date = (TODAY - timedelta(days=pub_offset_days)).isoformat()
    r = {
        "id": id,
        "institution": inst, "tier": tier, "coin": coin,
        "target_price": price, "target_currency": "USD",
        "target_date": None,
        "horizon_months": horizon_months,
        "pub_date": pub_date,
        "rating": "bullish",
        "source_type": "seed",
        "source_url": None,
        "excerpt": "e",
        "confidence": 0.9,
        "fetched_at": "",
    }
    return r


SAMPLE = [
    # BTC within_1y: 80K 100K 150K → count 3, min=80K max=150K
    _mk("b1", "JPMorgan", "BTC",  80000,  200, 10),
    _mk("b2", "VanEck",  "BTC", 100000,  180,  8),
    _mk("b3", "渣打未归一化前", "BTC", 150000,  60,  3, "tier1"),  # 未用 normalize 但测试不影响
    # BTC 1-3y: 250K
    _mk("b4", "VanEck",  "BTC", 250000,  365, 24),
    # BTC beyond_3y: 1M
    _mk("b5", "ARK Invest", "BTC", 1000000, 600, 60),
    # ETH within_1y: 6500 8000
    _mk("e1", "Galaxy", "ETH", 6500, 120, 6, "tier2"),
    _mk("e2", "渣打", "ETH", 8000, 90, 12),
    # SOL within_1y: 320 450
    _mk("s1", "VanEck", "SOL", 450, 100, 12),
    _mk("s2", "Galaxy", "SOL", 320, 50, 7, "tier2"),
]
# 修正: 数组顺序 = [b1 b2 b3 b4 b5 e1 e2 s1 s2]（共 9 条）
SAMPLE[2]["institution"] = "Standard Chartered"  # b3
SAMPLE[5]["institution"] = "Galaxy Digital"      # e1
SAMPLE[6]["institution"] = "Standard Chartered"  # e2
SAMPLE[8]["institution"] = "Galaxy Digital"      # s2


# ══ _horizon_months / _bucket_of ════════════════════════════════
def test_bucket_of_within_1y():
    r = {"horizon_months": 9, "pub_date": "2025-01-01", "target_date": "2025-10-01"}
    assert _bucket_of(r) == "within_1y"

def test_bucket_of_1_to_3y():
    r = {"horizon_months": 24, "pub_date": "", "target_date": None}
    assert _bucket_of(r) == "1_to_3y"

def test_bucket_of_beyond_3y_fallback_horizon():
    r = {"horizon_months": 72}
    assert _bucket_of(r) == "beyond_3y"

def test_horizon_months_from_target_date():
    r = {"horizon_months": None,
         "pub_date": "2025-01-01", "target_date": "2026-06-01"}
    assert _horizon_months(r) == 17


# ══ analyze_coins ═════════════════════════════════════════════
def test_analyze_coins_btc_has_5_institutions_and_bucket_stats():
    out = analyze_coins(["BTC"], seed_records=[],
                        scraped_records=SAMPLE)
    assert len(out) == 1
    r = out[0]
    assert r["coin"] == "BTC"
    # 5 条 BTC 记录，机构有 JPMorgan/VanEck/Standard Chartered/ARK Invest → 4家
    assert r["coverage_count"] == 4
    # within_1y 有 3 条，max 150000 min 80000
    b = r["target_price_ranges"]["within_1y"]
    assert b["count"] == 3
    assert b["min"] == 80000
    assert b["max"] == 150000
    assert abs(b["mean"] - (80000+100000+150000)/3) < 0.5
    assert b["divergence_ratio"] == round(150000 / 80000, 2)
    # 1-3y
    assert r["target_price_ranges"]["1_to_3y"]["count"] == 1
    assert r["target_price_ranges"]["1_to_3y"]["max"] == 250000
    # beyond_3y
    assert r["target_price_ranges"]["beyond_3y"]["count"] == 1


def test_analyze_coins_unknown_coin_zero_coverage_note():
    # DOGE 在白名单内但无任何样本
    out = analyze_coins(["DOGE"], seed_records=[], scraped_records=SAMPLE)
    assert out[0]["coin"] == "DOGE"
    assert out[0]["coverage_count"] == 0
    assert out[0]["note"] == "暂未收录机构研报"
    # 不能含任何占位区间字段
    assert "target_price_ranges" not in out[0]
    assert "institutions" not in out[0]


def test_analyze_coins_not_in_supported_coin_unknown():
    out = analyze_coins(["FAKECOIN"], seed_records=[], scraped_records=SAMPLE)
    assert out[0]["coin"] == "FAKECOIN"
    assert out[0]["coverage_count"] == 0
    assert "不在 SUPPORTED_COINS" in out[0]["note"]


def test_analyze_coins_upside_from_current_prices():
    out = analyze_coins(["SOL"], seed_records=[], scraped_records=SAMPLE,
                        current_prices={"SOL": 100.0})
    r = out[0]
    b = r["target_price_ranges"]["within_1y"]
    # median of [320,450] = (320+450)/2 = 385
    median = 385
    upside_pct = round((median - 100) / 100 * 100, 1)
    assert b["upside_vs_current_pct"] == upside_pct


def test_analyze_coins_dedup_by_id():
    # 重复 id 记录：手动重复 b1 三条，机构覆盖数不应变 3
    dup = SAMPLE + [SAMPLE[0].copy(), SAMPLE[0].copy()]
    out = analyze_coins(["BTC"], seed_records=[], scraped_records=dup)
    assert out[0]["coverage_count"] == 4


# ══ latest ════════════════════════════════════════════════
def test_latest_filters_by_window_and_sorts():
    # 默认 180 天窗口。SAMPLE 内 ≤ 180 天:
    # b2 (180), b3 (60), b5 (600 NO), b4 (365 NO), b1 (200 NO)
    # → BTC: b2 + b3 = 2 条
    out = latest("BTC", seed_records=[], scraped_records=SAMPLE,
                 window_days=180)
    assert out["coin"] == "BTC"
    assert out["window_days"] == 180
    assert out["coverage_count"] == 2
    assert len(out["records"]) == 2
    # 按 pub_date desc 排序 → b3 (60 天前，新) 先于 b2 (180 天前)
    assert out["records"][0]["pub_date"] >= out["records"][1]["pub_date"]


def test_latest_uncovered_sol_note_and_records_but_no_window_warn():
    # DOGE: 无任何记录
    out = latest("DOGE", seed_records=[], scraped_records=SAMPLE)
    assert out["coin"] == "DOGE"
    assert out["coverage_count"] == 0
    assert out["records"] == []
    assert out["note"] == "暂未收录机构研报"

    # BTC: 把窗口缩到 30 天 → 无近期记录，退为「全部历史」(5条)
    out2 = latest("BTC", seed_records=[], scraped_records=SAMPLE, window_days=30)
    assert out2["coverage_count"] == 4  # 历史所有机构数
    assert "无更新；以下为全部历史记录" in out2["note"]
    assert len(out2["records"]) == 5


# ══ build_report 与可 JSON 序列化 ═════════════════════════
def test_build_report_json_serializable():
    import json as _json
    rep = build_report(["BTC", "DOGE", "FAKE"],
                       seed_records=[], scraped_records=SAMPLE)
    s = _json.dumps(rep, ensure_ascii=False)
    # 必须可完整反序列化回来
    back = _json.loads(s)
    assert back["coins"] == ["BTC", "DOGE", "FAKE"]
    assert "generated_at" in back
    # BTC 有 analyze + latest 两个字段
    assert back["latest"]["BTC"]["coin"] == "BTC"
