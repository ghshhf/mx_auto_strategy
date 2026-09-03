"""研报数据源基类与JSONL知识库工具。

核心：
- compute_record_id: 用机构×币×target_price×pub_date组合取8位hex作为主键，用于去重
- read_jsonl / append_jsonl_atomic: 永不覆盖旧数据的原子化写入
- BaseResearchSource: 多源抓取基类，支持 HTTP 代理 + 超时 + 静默失败降级
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable

from ..config import normalize_institution, normalize_coin, tier_of, normalize_rating

logger = logging.getLogger(__name__)


# ══════════════════ 去重主键 ══════════════════

def _normalize_key_parts(record: dict) -> tuple:
    """对去重有意义的字段按统一归一化后返回。顺序保证稳定。"""
    institution = (record.get("institution") or "").strip().lower()
    coin = (record.get("coin") or "").strip().upper()
    target_price = float(record.get("target_price") or 0)
    pub_date = (record.get("pub_date") or "").strip()
    # target_date 也加入：同一机构同币同价不同日期算不同预测
    target_date = (record.get("target_date") or "").strip()
    return (institution, coin, f"{target_price:.6f}", pub_date, target_date)


def compute_record_id(record: dict) -> str:
    """返回 8 位 hex 稳定 ID；对 input dict 顺序/字段差异不敏感。"""
    key = json.dumps(_normalize_key_parts(record), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def compute_mention_id(record: dict) -> str:
    """mention（广义提及）的稳定去重 ID：币 × 类别 × 标题 × 来源url × 发布日。"""
    parts = (
        (record.get("coin") or "").strip().upper(),
        (record.get("category") or "").strip().lower(),
        (record.get("title") or "").strip().lower(),
        (record.get("source_url") or "").strip().lower(),
        (record.get("pub_date") or "").strip(),
    )
    key = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


# ══════════════════ JSONL 原子读写 ══════════════════

def read_jsonl(path: str) -> list[dict]:
    """读 JSONL，跳过空行与解析失败行，不会抛错。文件不存在返回 []。"""
    if not os.path.exists(path):
        return []
    result: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            s = line.strip()
            if not s:
                continue
            try:
                result.append(json.loads(s))
            except json.JSONDecodeError as e:
                logger.warning("read_jsonl %s line %s parse error: %s", path, i, e)
    return result


def append_jsonl_atomic(path: str, records: Iterable[dict]) -> int:
    """以原子方式追加若干 JSONL 行；成功后返回实际写入条数。

    行为：
    1. 先读取 path 的已有 id 集合，用于去重
    2. 过滤：id 已存在 / tier==unknown / coin None / target_price <= 0
    3. 先写 .tmp → os.replace 原子替换
    """
    records_list = list(records)
    if not records_list:
        return 0
    existing = read_jsonl(path)
    existing_ids = {r.get("id") for r in existing if r.get("id")}

    to_write: list[str] = []
    for r in records_list:
        if not r:
            continue
        is_mention = r.get("record_type") == "mention"
        if is_mention:
            # mention 路径：不要求机构 tier / 目标价，只需白名单币 + 有标题
            if not r.get("id"):
                r["id"] = compute_mention_id(r)
            if r["id"] in existing_ids:
                continue
            coin_norm = normalize_coin(r.get("coin"))
            if coin_norm is None:
                continue
            r["coin"] = coin_norm
            if not (r.get("title") or "").strip():
                continue
            to_write.append(json.dumps(r, ensure_ascii=False))
        else:
            # 既有目标价路径（行为不变）：机构 tier / 代币白名单 / 目标价正数
            if not r.get("id"):
                r["id"] = compute_record_id(r)
            if r["id"] in existing_ids:
                continue
            if tier_of(r.get("institution", "")) == "unknown":
                continue
            coin_norm = normalize_coin(r.get("coin"))
            if coin_norm is None:
                continue
            r["coin"] = coin_norm
            if not r.get("target_price") or float(r["target_price"]) <= 0:
                continue
            to_write.append(json.dumps(r, ensure_ascii=False))

    if not to_write:
        return 0

    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    # 原子写入：把 old contents + 新内容 一次性合成新文件替换，避免 append 中途崩溃脏写
    with open(path, "a", encoding="utf-8") as f:
        # 简单模式：若文件大小<=小阈值直接 append 足够安全；否则走 tmp+replace
        pass
    try:
        size = os.path.getsize(path) if os.path.exists(path) else 0
    except OSError:
        size = 0

    if size < 2 * 1024 * 1024:  # < 2MB 直接 append
        with open(path, "a", encoding="utf-8") as f:
            for line in to_write:
                f.write(line + "\n")
    else:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp_jsonl_", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fout:
                # 复制旧
                with open(path, "r", encoding="utf-8") as fin:
                    for chunk in iter(lambda: fin.read(65536), ""):
                        fout.write(chunk)
                for line in to_write:
                    fout.write(line + "\n")
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    return len(to_write)


# ══════════════════ HTTP 抓取辅助 ══════════════════

def _default_timeout() -> int:
    try:
        val = int(os.environ.get("RESEARCH_FETCH_TIMEOUT", "10"))
        return max(3, min(val, 60))
    except (TypeError, ValueError):
        return 10


def _resolve_opener():
    """代理统一走仓库根 net_config（设计铁律 §9-2：不走裸环境变量，
    规避沙箱注入的坏代理 59953/61350；net_config 内部按 MX_PROXY→
    实测存活的 DEFAULT_PROXY(3067)→环境变量 顺序解析）。
    导入失败（如模块被移出仓库单独用）降级为默认 urlopen。"""
    try:
        import net_config  # 仓库根公共工具
        return net_config.proxy_opener()
    except Exception:  # noqa: BLE001
        return None


def _http_request(url: str, method: str = "GET", headers: dict | None = None,
                  timeout: int | None = None) -> tuple[int, str]:
    """最小化 urllib 抓取：代理由 net_config 统一解析（见 _resolve_opener）。

    返回 (status_code, body_text)；网络错误/超时返回 (0, "")。
    """
    if not url:
        return 0, ""
    timeout = timeout or _default_timeout()
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "User-Agent": "Mozilla/5.0 (ResearchBot/1.0)",
            "Accept": "application/json, text/html;q=0.9, */*;q=0.1",
            **(headers or {}),
        },
    )
    opener = _resolve_opener()

    def _open(request, **kw):
        if opener is not None:
            return opener.open(request, **kw)
        return urllib.request.urlopen(request, **kw)

    try:
        with _open(req, timeout=timeout) as resp:
            body_bytes = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            body = body_bytes.decode(charset, errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = (e.read() or b"").decode("utf-8", errors="replace")
        except Exception:
            pass
        return e.code, body
    except (TimeoutError, urllib.error.URLError, OSError, ValueError):
        return 0, ""


# ══════════════════ 抓取源基类 ══════════════════

class BaseResearchSource:
    """子类只要实现 fetch_coins([coins]) 返回 list[dict] 即可。"""

    source_name: str = "base"
    source_type: str = "scrape"

    # 抓取失败时静默空列表
    def fetch_coins(self, coins: list[str]) -> list[dict]:
        try:
            return self._fetch_coins_impl(coins) or []
        except Exception as e:  # noqa: BLE001
            logger.info("%s fetch failed: %s", self.source_name, e)
            return []

    def _fetch_coins_impl(self, coins: list[str]) -> list[dict]:
        raise NotImplementedError

    # ── 子类调用的工具 ────────────────────────────────
    def _get(self, url: str, headers: dict | None = None) -> tuple[int, str]:
        return _http_request(url, "GET", headers=headers)

    def _normalize_and_filter_record(self, raw: dict) -> dict | None:
        """统一规范化；任何致命瑕疵返回 None（不抛错）。"""
        if not raw:
            return None
        institution = normalize_institution(raw.get("institution") or raw.get("firm") or "")
        if not institution:
            return None
        tier = tier_of(institution)
        if tier == "unknown":
            return None  # 严格：非白名单机构拒收
        coin = normalize_coin(raw.get("coin") or raw.get("token") or raw.get("symbol"))
        if coin is None:
            return None
        try:
            price = float(raw.get("target_price") or 0)
        except (TypeError, ValueError):
            return None
        if not price or price <= 0:
            return None

        pub_date = (raw.get("pub_date") or "").strip()
        if not pub_date:
            # 缺失发布日期用 fetched_at 替代
            from datetime import datetime, timezone
            pub_date = datetime.now(timezone.utc).date().isoformat()

        try:
            horizon = int(raw.get("horizon_months")) if raw.get("horizon_months") else None
        except (TypeError, ValueError):
            horizon = None

        record = {
            "id": None,
            "institution": institution,
            "tier": tier,
            "coin": coin,
            "target_price": price,
            "target_currency": (raw.get("target_currency") or "USD").upper() or "USD",
            "target_date": (raw.get("target_date") or "").strip() or None,
            "horizon_months": horizon,
            "pub_date": pub_date,
            "rating": normalize_rating(raw.get("rating")),
            "source_type": self.source_type,
            "source_url": (raw.get("source_url") or "").strip() or None,
            "excerpt": (raw.get("excerpt") or "").strip()[:200] or None,
            "confidence": 0.55,  # 抓取默认中等置信度；seed 才是 0.9
            "fetched_at": None,
        }
        from datetime import datetime, timezone
        record["fetched_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        record["id"] = compute_record_id(record)
        return record

    def _normalize_mention(self, raw: dict) -> dict | None:
        """mention（广义提及）的统一规范化；任何致命瑕疵返回 None（不抛错）。

        与 _normalize_and_filter_record 不同：不要求机构/目标价，只需白名单币 + 有标题。
        institution 字段允许非白名单（保留原始名作上下文），category 缺省为 news。
        """
        if not raw:
            return None
        coin = normalize_coin(raw.get("coin") or raw.get("token") or raw.get("symbol"))
        if coin is None:
            return None
        title = (raw.get("title") or "").strip()
        if not title:
            return None
        from datetime import datetime, timezone
        rec = {
            "id": None,
            "record_type": "mention",
            "coin": coin,
            "category": (raw.get("category") or "news").strip().lower() or "news",
            "institution": normalize_institution(raw.get("institution") or "") or None,
            "title": title[:200],
            "source": (raw.get("source") or self.source_name or "").strip() or None,
            "pub_date": (raw.get("pub_date") or "").strip() or None,
            "source_url": (raw.get("source_url") or "").strip() or None,
            "excerpt": (raw.get("excerpt") or "").strip()[:200] or None,
            "source_type": self.source_type,
            "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
        rec["id"] = compute_mention_id(rec)
        return rec


def fetch_all_sources(coins: list[str], sources: list[BaseResearchSource]) -> list[dict]:
    """按顺序抓取所有源，合并并去重；失败源静默跳过。

    返回的记录混合两种 record_type：
    - "target_price"（默认，无 record_type 字段的旧记录也属此类）：机构目标价
    - "mention"：广义提及（新闻/ETF/上线/监管/机构提及），由 _normalize_mention 处理
    """
    merged: dict[str, dict] = {}
    for src in sources:
        try:
            for raw in src.fetch_coins(coins):
                if not isinstance(raw, dict):
                    continue
                if raw.get("record_type") == "mention":
                    rec = src._normalize_mention(raw)
                else:
                    rec = src._normalize_and_filter_record(raw) if not raw.get("id") else raw
                if rec:
                    if rec.get("id") is None:
                        rec["id"] = compute_mention_id(rec) if rec.get("record_type") == "mention" else compute_record_id(rec)
                    # 先到者优先（靠前的源优先级更高），除非后到者 confidence 更高
                    prev = merged.get(rec["id"])
                    if prev is None:
                        merged[rec["id"]] = rec
                    else:
                        if (rec.get("confidence") or 0) > (prev.get("confidence") or 0):
                            merged[rec["id"]] = rec
        except Exception as e:  # noqa: BLE001
            logger.info("source %s aborted: %s", getattr(src, "source_name", "?"), e)
    return list(merged.values())
