"""Aggregate：把若干条 Record 交叉聚合成按代币 + 分桶的目标价上下区间。

纯函数，无 IO；输入 records，输出 analyze_coins / latest / report 的 dict 结果。
"""
from __future__ import annotations
import statistics
from datetime import datetime, timedelta, timezone

from .config import HORIZON_BUCKETS, LATEST_WINDOW_DAYS, SUPPORTED_COINS_UPPER
from .config import normalize_coin


def _months_between(pub_date_iso: str, target_date_iso) -> int:
    """用 (target - pub) 的月份差作为实际 horizon；缺失退回 horizon_months 字段或 18。"""
    try:
        pub = datetime.strptime(pub_date_iso[:10], "%Y-%m-%d").date()
        tgt = datetime.strptime(str(target_date_iso)[:10], "%Y-%m-%d").date()
        months = (tgt.year - pub.year) * 12 + (tgt.month - pub.month)
        return max(1, months)
    except (ValueError, TypeError):
        return 0


def _horizon_months(rec: dict) -> int:
    explicit = rec.get("horizon_months")
    if explicit:
        try:
            return max(1, int(explicit))
        except (TypeError, ValueError):
            pass
    m = _months_between(rec.get("pub_date") or "", rec.get("target_date"))
    if m >= 1:
        return m
    return 18  # 最后回退：默认 1.5y


def _bucket_of(rec: dict) -> str:
    hm = _horizon_months(rec)
    for name, lo, hi in HORIZON_BUCKETS:
        if lo <= hm <= hi:
            return name
    # 极端值：≤0 按 within_1y，>999 按 beyond_3y
    if hm <= 0:
        return HORIZON_BUCKETS[0][0]
    return HORIZON_BUCKETS[-1][0]


def _num_bucket_stats(values: list[float]):
    """对 list[price] 返回 {min, max, mean, median, count}；空列表返回 None。"""
    if not values:
        return None
    vs = sorted(float(v) for v in values)
    return {
        "count": len(vs),
        "min": vs[0],
        "max": vs[-1],
        "mean": round(statistics.mean(vs), 2),
        "median": round(statistics.median(vs), 2),
    }


def _load_all_records(seed_records: list[dict], kb_path: str | None,
                      scraped_records: list[dict] | None = None) -> list[dict]:
    """汇总三类来源，用 id 去重（优先顺序：manual(kb)+seed > scrape+llm）。"""
    from .sources.base import read_jsonl
    kb_records = read_jsonl(kb_path) if kb_path else []
    order = []
    index: dict[str, dict] = {}
    # 1) seed (confidence 0.9)；2) 手工录入 / kb；3) scraped
    for group in (seed_records or [], kb_records, (scraped_records or [])):
        for r in group:
            if not isinstance(r, dict):
                continue
            rid = r.get("id")
            if not rid:
                continue
            if rid in index:
                # 高置信度覆盖低
                if (r.get("confidence") or 0) > (index[rid].get("confidence") or 0):
                    index[rid] = r
            else:
                index[rid] = r
                order.append(rid)
    return [index[rid] for rid in order if index.get(rid)]


# ═══════════════════════════════════════════════════════════════
# 三大对外函数：analyze_coins / latest / build_report
# ═══════════════════════════════════════════════════════════════

def analyze_coins(
    coins: list[str],
    seed_records: list[dict],
    kb_path: str | None = None,
    scraped_records: list[dict] | None = None,
    current_prices: dict[str, float] | None = None,
) -> list[dict]:
    """按币返回结构化分析结果（覆盖数 / 分桶上下区间 / 分歧度 / 上行空间）。"""
    current_prices = current_prices or {}
    all_records = _load_all_records(seed_records, kb_path, scraped_records)

    # 归一化请求币
    req_coins: list[str] = []
    for c in coins:
        nc = normalize_coin(c)
        if nc is None:
            # 不认识的按原名挂一个 zero result
            req_coins.append(c.upper() if c else c)
        else:
            req_coins.append(nc)

    # 每个币的记录集合
    per_coin: dict[str, list[dict]] = {c: [] for c in req_coins}
    for r in all_records:
        if r.get("coin") in per_coin:
            per_coin[r["coin"]].append(r)

    results: list[dict] = []
    for coin in req_coins:
        recs = per_coin[coin]
        if coin not in SUPPORTED_COINS_UPPER:
            # 连币都不认识：仅返回 0 覆盖说明
            results.append({
                "coin": coin,
                "coverage_count": 0,
                "note": "代币不在 SUPPORTED_COINS 白名单 + 暂未收录机构研报",
            })
            continue
        if not recs:
            results.append({
                "coin": coin,
                "coverage_count": 0,
                "note": "暂未收录机构研报",
            })
            continue

        # 覆盖：机构集合 + 机构列表 + tier 分布
        insts: list[str] = sorted({r["institution"] for r in recs})
        tier_dist: dict[str, int] = {}
        for r in recs:
            tier_dist[r["tier"]] = tier_dist.get(r["tier"], 0) + 1

        # 分桶统计
        buckets_raw: dict[str, list[float]] = {b[0]: [] for b in HORIZON_BUCKETS}
        for r in recs:
            buckets_raw[_bucket_of(r)].append(r["target_price"])

        target_price_ranges: dict[str, dict] = {}
        for name, prices in buckets_raw.items():
            s = _num_bucket_stats(prices)
            if s is None:
                target_price_ranges[name] = {"count": 0}
                continue
            d = dict(s)
            if d["min"] > 0:
                d["divergence_ratio"] = round(d["max"] / d["min"], 2)
            cur = current_prices.get(coin)
            if cur and cur > 0:
                d["upside_vs_current_pct"] = round((d["median"] - cur) / cur * 100, 1)
            target_price_ranges[name] = d

        results.append({
            "coin": coin,
            "coverage_count": len(insts),
            "institutions": insts,
            "tier_distribution": tier_dist,
            "total_records": len(recs),
            "target_price_ranges": target_price_ranges,
        })
    return results


def latest(
    coin: str,
    seed_records: list[dict],
    kb_path: str | None = None,
    scraped_records: list[dict] | None = None,
    window_days: int = LATEST_WINDOW_DAYS,
    limit: int = 10,
) -> dict:
    """返回指定币近 N 天的按 tier 汇总 + 最新 N 条列表。空覆盖返回 {note}。"""
    nc = normalize_coin(coin)
    all_records = _load_all_records(seed_records, kb_path, scraped_records)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).date().isoformat()
    filtered = [
        r for r in all_records
        if r.get("coin") == nc and (r.get("pub_date") or "") >= cutoff
    ]
    if nc is None:
        return {"coin": coin, "coverage_count": 0,
                "note": "代币不在 SUPPORTED_COINS 白名单 + 暂未收录机构研报", "records": []}
    if not filtered:
        # 无近 N 天：也返回全部，但 note 说明
        all_coin_recs = sorted(
            [r for r in all_records if r.get("coin") == nc],
            key=lambda r: r.get("pub_date") or "", reverse=True,
        )
        summary = {
            "coin": nc,
            "coverage_count": len({r["institution"] for r in all_coin_recs}),
            "note": f"近 {window_days} 天无更新；以下为全部历史记录（{len(all_coin_recs)} 条）",
            "records": all_coin_recs[:limit],
        }
        if not all_coin_recs:
            summary["note"] = "暂未收录机构研报"
            summary["records"] = []
            summary["coverage_count"] = 0
        return summary

    filtered_sorted = sorted(
        filtered, key=lambda r: (r.get("pub_date") or "", r.get("institution") or ""),
        reverse=True,
    )
    insts = sorted({r["institution"] for r in filtered})
    # 分歧度：within_1y 的 max/min
    prices = [r["target_price"] for r in filtered if _bucket_of(r) == "within_1y"]
    divergence = None
    if len(prices) >= 2 and min(prices) > 0:
        divergence = round(max(prices) / min(prices), 2)
    return {
        "coin": nc,
        "window_days": window_days,
        "coverage_count": len(insts),
        "institutions_in_window": insts,
        "divergence_ratio_within_1y": divergence,
        "records": filtered_sorted[:limit],
    }


def build_report(coins: list[str], seed_records, kb_path=None, scraped_records=None,
                 current_prices=None) -> dict:
    """整合 analyze + latest，返回一份完整报告 dict。"""
    analyzed = analyze_coins(coins, seed_records, kb_path, scraped_records, current_prices)
    latests = {c: latest(c, seed_records, kb_path, scraped_records) for c in coins}
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "generated_at": generated_at,
        "coins": coins,
        "analyze": analyzed,
        "latest": latests,
    }
