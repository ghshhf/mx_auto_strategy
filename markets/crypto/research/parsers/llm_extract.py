"""可选 LLM 解析层：把「机构研报」的非结构化文本转成结构化 Record。

行为承诺：
- 未配置 LLM 或配置无效时静默返回空列表，不影响主流程
- 只有命中 schema 的条目返回；部分字段缺失但满足最低门槛也返回（由上层再过滤 tier）
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from ..config import (
    normalize_institution, normalize_coin, normalize_rating, tier_of,
)
from ..sources.base import compute_record_id

logger = logging.getLogger(__name__)

DEFAULT_SCHEMA_JSON = json.dumps({
    "type": "object",
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["institution", "coin", "target_price", "pub_date"],
                "properties": {
                    "institution":     {"type": "string", "description": "机构全称，如 Standard Chartered"},
                    "coin":            {"type": "string", "description": "代币大写简写，如 BTC / ETH / SOL"},
                    "target_price":    {"type": "number", "description": "美元目标价"},
                    "target_currency": {"type": "string", "description": "默认为 USD"},
                    "target_date":     {"type": "string", "description": "目标达成日期，YYYY-MM-DD 或 YYYY 年底"},
                    "horizon_months":  {"type": "integer", "description": "预测月份数"},
                    "pub_date":        {"type": "string", "description": "发布日期 YYYY-MM-DD"},
                    "rating":          {"type": "string", "description": "bullish / bearish / neutral"},
                    "source_url":      {"type": "string", "description": "原始 URL"},
                    "excerpt":         {"type": "string", "description": "200字摘要"},
                },
                "additionalProperties": False,
            },
        },
    },
    "required": ["records"],
    "additionalProperties": False,
}, ensure_ascii=False)


def _get_llm_client():
    """尝试导入公共工具的 llm_client；不可用返回 None，不中断。"""
    try:
        from llm_client import get_client  # type: ignore
        return get_client()
    except Exception:
        pass
    try:
        from net_config import get_default_llm_client  # type: ignore
        return get_default_llm_client()
    except Exception:
        return None


def _run_structured(client, prompt: str, schema_json: str):
    """调用 LLM 的 structured 生成能力；异常返回空列表。"""
    if client is None:
        return []
    try:
        # 常见结构化 API：client.beta.chat.completions.parse / client.chat.completions.create(response_format=)
        method = getattr(client.chat.completions, "parse", None) or client.chat.completions.create
        params = dict(
            model=getattr(client, "_model_name", None) or "gpt-4o-mini",
            messages=[
                {"role": "system",
                 "content": "You are a research-extractor. Only return records that explicitly "
                            "appear in the input. Fill missing fields with null. Never fabricate prices."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        # 若有 response_format 支持
        if "response_format" in method.__code__.co_varnames or True:  # 粗略尝试
            try:
                import json as _json
                params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "ResearchRecords", "strict": True,
                                   "schema": _json.loads(schema_json)},
                }
            except Exception:
                pass
        resp = method(**params)
        text = None
        # structured 返回的是 ParsedChatCompletion
        parsed = getattr(resp.choices[0].message, "parsed", None)
        if parsed:
            try:
                return list(parsed.get("records") or [])
            except Exception:
                pass
        text = resp.choices[0].message.content
        if not text:
            return []
        try:
            data = json.loads(text)
            return list(data.get("records") or [])
        except json.JSONDecodeError:
            return []
    except Exception as e:  # noqa: BLE001
        logger.info("llm_extract parse error: %s", e)
        return []


def _normalize_parsed(rec: dict):
    """把 LLM 返回的 dict 再做一次规范化 + 门槛过滤。"""
    institution = normalize_institution(rec.get("institution") or "")
    if not institution or tier_of(institution) == "unknown":
        return None
    coin = normalize_coin(rec.get("coin") or "")
    if coin is None:
        return None
    try:
        price = float(rec.get("target_price") or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    pub_date = (rec.get("pub_date") or "").strip() or now.date().isoformat()
    record = {
        "id": None,
        "institution": institution,
        "tier": tier_of(institution),
        "coin": coin,
        "target_price": price,
        "target_currency": (rec.get("target_currency") or "USD").upper(),
        "target_date": (rec.get("target_date") or "").strip() or None,
        "horizon_months": None,
        "pub_date": pub_date,
        "rating": normalize_rating(rec.get("rating")),
        "source_type": "llm_parse",
        "source_url": (rec.get("source_url") or "").strip() or None,
        "excerpt": (rec.get("excerpt") or "").strip()[:200] or None,
        "confidence": 0.75,
        "fetched_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    try:
        record["horizon_months"] = int(rec["horizon_months"])
    except (KeyError, TypeError, ValueError):
        pass
    record["id"] = compute_record_id(record)
    return record


def extract_records_from_texts(
    texts: list[str],
    client: Optional[object] = None,
    schema_json: Optional[str] = None,
) -> list[dict]:
    """把若干非结构化文本送入 LLM 抽取；失败/无LLM 静默返回 []。

    Args:
        texts: 每条对应一个原始文档/网页正文（建议 <8k chars）。
        client: 可选注入，未传走公共工具自动探测。
        schema_json: 可覆盖默认 schema JSON 字符串。
    """
    if not texts:
        return []
    client = client or _get_llm_client()
    if client is None:
        logger.info("llm_extract: 未配置 LLM，返回空列表")
        return []
    schema = schema_json or DEFAULT_SCHEMA_JSON
    records: list[dict] = []
    seen: set[str] = set()
    for t in texts:
        if not t or not t.strip():
            continue
        prompt = (
            "请从以下机构研报正文中抽取结构化目标价预测（JSON records 数组）。"
            "不要编造；只有明确数字价 + 机构 + 代币 + 发布日期才填入。\n\n"
            f"正文：\n{t[:6000]}"
        )
        for raw in _run_structured(client, prompt, schema):
            norm = _normalize_parsed(raw) if isinstance(raw, dict) else None
            if norm and norm["id"] not in seen:
                seen.add(norm["id"])
                records.append(norm)
    return records
