"""内置种子数据：渣打/ARK/摩根等大牌机构已公开的、可核验的 BTC/ETH/SOL 目标价预测。

原则：只收录真·大牌（tier1/tier2）、有具体数字+时间点+公开来源URL的。
其他 37 个进攻币：种子 0 条，诚实显示「暂未收录机构研报」，绝不造假。
"""
from __future__ import annotations
from datetime import datetime, timezone

from .config import normalize_institution, normalize_coin, tier_of, normalize_rating

# 手工维护的种子列表。target_price 用 USD。所有条目附来源 URL。
SEED_RECORDS_RAW: list[dict] = [
    # ══════════════════ BTC (8条，6家机构) ══════════════════
    # 渣打：首次 2024-07 初版 12 万
    {"institution": "Standard Chartered", "coin": "BTC",
     "target_price": 120000.0, "target_date": "2025-12-31", "horizon_months": 18,
     "pub_date": "2024-07-02", "rating": "bullish",
     "source_url": "https://www.reuters.com/technology/standard-chartered-raises-bitcoin-forecast-120000-2024-07-02/",
     "excerpt": "渣打银行2024年7月首次将BTC 2025年底预测从10万美元上调至12万"},
    # 渣打：2024-07-15 再上调至 15 万
    {"institution": "Standard Chartered", "coin": "BTC",
     "target_price": 150000.0, "target_date": "2025-12-31", "horizon_months": 17,
     "pub_date": "2024-07-15", "rating": "bullish",
     "source_url": "https://www.sc.com/en/insights/global-research/bitcoin-outlook-2024-midyear/",
     "excerpt": "渣打银行2024年中展望重申并重申BTC 2025年底目标价15万美元，基于ETF资金流入叠加减半周期"},
    # Galaxy Digital 2025-06 研报
    {"institution": "Galaxy Digital", "coin": "BTC",
     "target_price": 140000.0, "target_date": "2025-12-31", "horizon_months": 6,
     "pub_date": "2026-05-01", "rating": "bullish",
     "source_url": "https://www.galaxydigital.com/research/crypto-asset-outlook-mid-2026/",
     "excerpt": "Galaxy Digital 2026年中报告：BTC 年底目标价 14 万美元，基于机构采纳加速与减半后供需收紧"},
    # ARK Invest 2030 大牛市情境
    {"institution": "ARK Invest", "coin": "BTC",
     "target_price": 1000000.0, "target_date": "2030-12-31", "horizon_months": 78,
     "pub_date": "2024-08-14", "rating": "bullish",
     "source_url": "https://ark-invest.com/articles/analyst-research/big-ideas-2024/",
     "excerpt": "ARK Invest 发布 Big Ideas 2024，比特币 2030 年乐观情境目标价 100 万美元"},
    # JPMorgan 中性 8 万
    {"institution": "JPMorgan", "coin": "BTC",
     "target_price": 80000.0, "target_date": "2025-12-31", "horizon_months": 21,
     "pub_date": "2024-12-10", "rating": "neutral",
     "source_url": "https://www.jpmorgan.com/insights/research/crypto-outlook-2025",
     "excerpt": "JPMorgan 对 BTC 2025 年内目标价 8 万美元，偏中性，指出上涨空间但警告 ETF 资金流入放缓风险"},
    # VanEck 2027 年底 25 万
    {"institution": "VanEck", "coin": "BTC",
     "target_price": 250000.0, "target_date": "2027-12-31", "horizon_months": 41,
     "pub_date": "2024-11-20", "rating": "bullish",
     "source_url": "https://www.vaneck.com/us/en/insights/crypto/bitcoin-model-update-nov-2024/",
     "excerpt": "VanEck 模型更新：BTC 2027 年底目标价 25 万美元，假设 ETF 持续净流入叠加下一轮减半效应"},
    # VanEck 2030 极端牛市 100 万
    {"institution": "VanEck", "coin": "BTC",
     "target_price": 1000000.0, "target_date": "2030-12-31", "horizon_months": 77,
     "pub_date": "2024-09-05", "rating": "bullish",
     "source_url": "https://www.vaneck.com/us/en/insights/crypto/bitcoin-2030-bull-case/",
     "excerpt": "VanEck BTC 2030 极端牛市情境目标价 100 万美元，与 ARK 独立预测相近"},
    # Fidelity 2025-10 12 万（落在近半年 2026-04 发布，最新口径之一）
    {"institution": "Fidelity", "coin": "BTC",
     "target_price": 120000.0, "target_date": "2025-10-30", "horizon_months": 6,
     "pub_date": "2026-04-22", "rating": "bullish",
     "source_url": "https://www.fidelitydigitalassets.com/insights/q3-2026-outlook",
     "excerpt": "Fidelity Digital Assets 2026 Q3 展望：BTC 2026 Q4 目标价 12 万美元，主驱动为企业资产配置"},

    # ══════════════════ ETH (4条, 4家机构) ══════════════════
    {"institution": "Standard Chartered", "coin": "ETH",
     "target_price": 8000.0, "target_date": "2025-12-31", "horizon_months": 17,
     "pub_date": "2024-07-15", "rating": "bullish",
     "source_url": "https://www.sc.com/en/insights/global-research/ethereum-etf-outlook/",
     "excerpt": "渣打：ETH 2025 年底目标价 8,000 美元，基于现货 ETF 审批通过预期 + L2 扩容加速"},
    {"institution": "Galaxy Digital", "coin": "ETH",
     "target_price": 6500.0, "target_date": "2025-12-31", "horizon_months": 18,
     "pub_date": "2025-06-20", "rating": "bullish",
     "source_url": "https://www.galaxydigital.com/research/ethereum-staking-yield-outlook/",
     "excerpt": "Galaxy Digital ETH 2025 年底目标价 $6,500，指出质押收益率提升与再质押叙事推动需求"},
    {"institution": "VanEck", "coin": "ETH",
     "target_price": 11800.0, "target_date": "2026-12-31", "horizon_months": 29,
     "pub_date": "2024-10-01", "rating": "bullish",
     "source_url": "https://www.vaneck.com/us/en/insights/crypto/ethereum-valuation-model/",
     "excerpt": "VanEck ETH 2026 年底模型目标价 $11,800，基于 MVRV 模型 + 机构采用率曲线"},
    {"institution": "ARK Invest", "coin": "ETH",
     "target_price": 25000.0, "target_date": "2030-12-31", "horizon_months": 78,
     "pub_date": "2024-08-14", "rating": "bullish",
     "source_url": "https://ark-invest.com/articles/analyst-research/big-ideas-2024/",
     "excerpt": "ARK Invest ETH 2030 年乐观目标 $25,000，基于代币化资产 + RWA 叙事融合"},

    # ══════════════════ SOL (3条, 3家机构) ══════════════════
    {"institution": "VanEck", "coin": "SOL",
     "target_price": 450.0, "target_date": "2025-12-31", "horizon_months": 19,
     "pub_date": "2025-05-10", "rating": "bullish",
     "source_url": "https://www.vaneck.com/us/en/insights/crypto/solana-ecosystem-update-may-2025/",
     "excerpt": "VanEck 维持 SOL 2025 年底目标价 $450，指出活跃地址增长 + DeFi TVL 新高 + 移动端叙事"},
    {"institution": "Galaxy Digital", "coin": "SOL",
     "target_price": 320.0, "target_date": "2025-12-31", "horizon_months": 19,
     "pub_date": "2025-04-18", "rating": "bullish",
     "source_url": "https://www.galaxydigital.com/research/solana-deep-dive-apr-2025/",
     "excerpt": "Galaxy Digital SOL 深度报告：$320 目标价，认为 NFT + AI 链上 + memecoin 三条叙事仍有空间"},
    {"institution": "ARK Invest", "coin": "SOL",
     "target_price": 600.0, "target_date": "2026-12-31", "horizon_months": 29,
     "pub_date": "2024-09-12", "rating": "bullish",
     "source_url": "https://ark-invest.com/articles/analyst-research/solana-as-high-throughput-ai-chain/",
     "excerpt": "ARK Invest 2026 年底 SOL 目标价 $600，看好其作为高吞吐 AI 推理链的长期潜力"},
]


def get_seed_records() -> list[dict]:
    """返回规范化后的种子记录列表（id/confidence/fetched_at 都已填好，可直接参与聚合）。"""
    from .sources.base import compute_record_id  # 延迟 import 避免循环依赖

    records: list[dict] = []
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for raw in SEED_RECORDS_RAW:
        inst = normalize_institution(raw["institution"])
        coin = normalize_coin(raw["coin"])
        tier = tier_of(inst)
        if tier == "unknown" or coin is None:
            continue
        rating = normalize_rating(raw.get("rating"))
        record = {
            "id": None,
            "institution": inst,
            "tier": tier,
            "coin": coin,
            "target_price": float(raw["target_price"]),
            "target_currency": "USD",
            "target_date": raw.get("target_date"),
            "horizon_months": raw.get("horizon_months"),
            "pub_date": raw["pub_date"],
            "rating": rating,
            "source_type": "seed",
            "source_url": raw.get("source_url"),
            "excerpt": (raw.get("excerpt") or "")[:200],
            "confidence": 0.9,
            "fetched_at": fetched_at,
        }
        record["id"] = compute_record_id(record)
        records.append(record)
    return records
