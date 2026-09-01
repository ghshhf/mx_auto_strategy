from .base import BaseResearchSource, compute_record_id, read_jsonl, append_jsonl_atomic
from .exchange_research import ExchangeResearchSource
from .media_keyword import MediaKeywordSource
from .price_target_agg import PriceTargetAggSource

__all__ = [
    "BaseResearchSource",
    "compute_record_id",
    "read_jsonl",
    "append_jsonl_atomic",
    "ExchangeResearchSource",
    "MediaKeywordSource",
    "PriceTargetAggSource",
]

def get_all_sources():
    """返回所有已启用的抓取源列表。"""
    return [
        ExchangeResearchSource(),
        MediaKeywordSource(),
        PriceTargetAggSource(),
    ]
