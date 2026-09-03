from .base import BaseResearchSource, compute_record_id, read_jsonl, append_jsonl_atomic
from .exchange_research import ExchangeResearchSource
from .media_keyword import MediaKeywordSource, GoogleNewsSource
from .price_target_agg import PriceTargetAggSource

__all__ = [
    "BaseResearchSource",
    "compute_record_id",
    "read_jsonl",
    "append_jsonl_atomic",
    "ExchangeResearchSource",
    "MediaKeywordSource",
    "GoogleNewsSource",
    "PriceTargetAggSource",
]

def get_all_sources():
    """返回所有已启用的抓取源列表。"""
    return [
        ExchangeResearchSource(),
        MediaKeywordSource(),
        # 深度通道：按币生成关键词检索，补头部 RSS「仅最新数十条」的窗口盲区
        GoogleNewsSource(),
        PriceTargetAggSource(),
    ]
