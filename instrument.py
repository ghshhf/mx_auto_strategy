"""
instrument.py - v6.16 品种元数据单一真相源 (Single Source of Truth)

职责: 把"资产类型 -> 每手股数 / 交易时段 / 是否可下单"这三件事收敛到一个模块,
      消除全仓 8 处 `//100*100` 硬编码(转债漏钱洞)与 A 股交易时段硬编码。

设计约定(与 docs/system_design.md §六 共享知识一致):
  1. 资产类型枚举仅 4 值: "A" | "HK" | "ETF" | "KZZ"
  2. 手数解析唯一入口 lot_of(); 优先级 per_code > lot_rules[market].lot > default_lot
  3. 取整唯一入口 round_qty(); 禁止任何模块再写 //100*100
  4. 港股未登记每手股数 + strict_unknown_lot=true -> 抛 UnknownLotError 拒单,
     绝不猜 100 (宁可不交易, 不可发废单)
  5. 兼容存量 .cost_basis.json (无 market 字段) -> 按代码形态回退推断, 无需数据迁移

依赖: 仅标准库 (json / os / datetime)。本模块不得 import 任何业务模块, 避免循环依赖。
"""
import json
import os
from datetime import datetime, time as _time
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 资产类型枚举
# ---------------------------------------------------------------------------
MARKET_A: str = "A"
MARKET_HK: str = "HK"
MARKET_ETF: str = "ETF"
MARKET_KZZ: str = "KZZ"
VALID_MARKETS: Tuple[str, ...] = (MARKET_A, MARKET_HK, MARKET_ETF, MARKET_KZZ)

CONFIG_PATH: str = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "strategy_config.json"
)

# A 股/ETF/可转债默认时段; 港股在 config 里覆盖为 09:30-12:00,13:00-16:00
DEFAULT_SESSIONS: str = "09:30-11:30,13:00-15:00"

# 配置缺失时的兜底(保证本模块单独 import 也能工作, 行为与改造前一致: 全部 100)
DEFAULT_INSTRUMENT_CFG: Dict[str, object] = {
    "default_lot": 100,
    "strict_unknown_lot": True,
    "lot_rules": {
        MARKET_A: {"lot": 100, "unit": "股", "sessions": DEFAULT_SESSIONS},
        MARKET_ETF: {"lot": 100, "unit": "份", "sessions": DEFAULT_SESSIONS},
        MARKET_KZZ: {"lot": 10, "unit": "张", "sessions": DEFAULT_SESSIONS},
        MARKET_HK: {"lot": None, "unit": "股", "sessions": "09:30-12:00,13:00-16:00"},
    },
    "per_code": {},
}

# 降级开关兜底: 配置缺 tradable_markets 时视为"全部可交易"(向后兼容改造前行为)
DEFAULT_TRADABLE_MARKETS: Tuple[str, ...] = VALID_MARKETS

_CFG_CACHE: Optional[dict] = None


class UnknownLotError(ValueError):
    """每手股数未登记且开启了严格模式 —— 拒单, 不猜手数。"""


# ---------------------------------------------------------------------------
# 配置读取
# ---------------------------------------------------------------------------
def load_config(path: Optional[str] = None, force: bool = False) -> dict:
    """读取 strategy_config.json(带进程内缓存)。读取失败返回空 dict, 由调用方走兜底。"""
    global _CFG_CACHE
    target = path or CONFIG_PATH
    if not force and path is None and _CFG_CACHE is not None:
        return _CFG_CACHE
    data: dict = {}
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    if path is None:
        _CFG_CACHE = data
    return data


def _resolve_cfg(cfg: Optional[dict] = None) -> dict:
    """cfg 为 None 时懒加载全局配置; 传入则原样使用(便于单测注入)。"""
    return cfg if isinstance(cfg, dict) else load_config()


def _instrument_cfg(cfg: Optional[dict] = None) -> dict:
    """取 instrument 段, 缺失键逐项回退到 DEFAULT_INSTRUMENT_CFG。"""
    raw = _resolve_cfg(cfg).get("instrument")
    if not isinstance(raw, dict):
        return dict(DEFAULT_INSTRUMENT_CFG)
    merged = dict(DEFAULT_INSTRUMENT_CFG)
    merged.update({k: v for k, v in raw.items() if not k.startswith("_")})
    # lot_rules 需要按市场逐项合并, 避免用户只写了 HK 就丢掉 A/ETF/KZZ
    rules = dict(DEFAULT_INSTRUMENT_CFG["lot_rules"])  # type: ignore[arg-type]
    for mk, rule in (raw.get("lot_rules") or {}).items():
        if isinstance(rule, dict):
            rules[mk] = rule
    merged["lot_rules"] = rules
    return merged


def _market_cfg(cfg: Optional[dict] = None) -> dict:
    raw = _resolve_cfg(cfg).get("market")
    return raw if isinstance(raw, dict) else {}


def _per_code_map(icfg: dict) -> Dict[str, int]:
    """per_code 里可能混有 `_comment` 之类的说明键, 只保留能转 int 的正数条目。"""
    out: Dict[str, int] = {}
    for code, lot in (icfg.get("per_code") or {}).items():
        if str(code).startswith("_"):
            continue
        try:
            val = int(lot)
        except (TypeError, ValueError):
            continue
        if val > 0:
            out[str(code)] = val
    return out


# ---------------------------------------------------------------------------
# 资产类型推断
# ---------------------------------------------------------------------------
def normalize_code(code: str) -> str:
    """去掉腾讯行情前缀(sh/sz/hk), 返回纯代码。非字符串输入一律转字符串。"""
    s = str(code or "").strip()
    low = s.lower()
    if low.startswith(("sh", "sz", "hk")):
        return s[2:]
    return s


def market_of(code: str, meta: Optional[dict] = None) -> str:
    """
    解析资产类型, 返回 VALID_MARKETS 之一。

    优先级:
      1) meta["market"] 显式标注(来自 candidate_pool / _cost_basis 缓存)
      2) 代码形态推断 —— 规则与 market_data._pad 严格对齐:
           hk 前缀 或 5 位          -> HK
           6 位且 11xx / 12xx 开头  -> KZZ  (沪市 11xxxx / 深市 12xxxx 可转债)
           6 位且 5 / 1 开头        -> ETF  (51xxxx 沪 / 15xxxx 深, 11/12 已被上一条截走)
           其余                     -> A

    注: per_code 只登记"每手股数", 不携带市场信息, 故不参与本函数判定。
        存量 .cost_basis.json 无 market 字段时自动走形态推断, 无需数据迁移。
    """
    if isinstance(meta, dict):
        declared = meta.get("market")
        if isinstance(declared, str) and declared.upper() in VALID_MARKETS:
            return declared.upper()

    raw = str(code or "").strip()
    if raw.lower().startswith("hk"):
        return MARKET_HK

    s = normalize_code(raw)
    if not s.isdigit():
        return MARKET_A
    if len(s) == 5:
        return MARKET_HK
    if len(s) == 6:
        if s[:2] in ("11", "12"):
            return MARKET_KZZ
        if s[0] in ("5", "1"):
            return MARKET_ETF
    return MARKET_A


# ---------------------------------------------------------------------------
# 手数解析与取整
# ---------------------------------------------------------------------------
def lot_of(code: str, cfg: Optional[dict] = None, market: Optional[str] = None) -> int:
    """
    返回该标的每手数量(股/份/张)。

    优先级: per_code[code] > lot_rules[market].lot > default_lot

    安全阀: market == "HK" 且 per_code 未命中 且 lot_rules["HK"].lot 为 null
            且 strict_unknown_lot=true -> 抛 UnknownLotError(拒单, 不猜 100)。
    """
    icfg = _instrument_cfg(cfg)
    plain = normalize_code(code)
    mk = (market or market_of(code)).upper()

    # 1) per_code 精确覆盖(港股每手股数逐只不同, 必须走这里)
    per_code = _per_code_map(icfg)
    if plain in per_code:
        return per_code[plain]
    if str(code) in per_code:
        return per_code[str(code)]

    # 2) 市场级默认
    rule = (icfg.get("lot_rules") or {}).get(mk) or {}
    lot = rule.get("lot")
    if lot is not None:
        try:
            val = int(lot)
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass

    # 3) 全局默认 / 安全阀
    if mk == MARKET_HK and bool(icfg.get("strict_unknown_lot", True)):
        raise UnknownLotError(
            f"港股 {plain} 未在 instrument.per_code 登记每手股数, "
            f"且 strict_unknown_lot=true -> 拒单(不猜 100)。"
            f"请在 strategy_config.json 的 instrument.per_code 补录后重试。"
        )
    try:
        return int(icfg.get("default_lot", 100))
    except (TypeError, ValueError):
        return 100


def assert_lot_known(code: str, cfg: Optional[dict] = None, market: Optional[str] = None) -> None:
    """校验每手股数可解析; 不可解析时抛 UnknownLotError。用于下单前置检查。"""
    lot_of(code, cfg=cfg, market=market)


def round_qty(
    qty,
    code: str,
    cfg: Optional[dict] = None,
    market: Optional[str] = None,
    mode: str = "floor",
) -> int:
    """
    按每手数量取整 —— 全仓唯一的取整入口, 用于替换 8 处 `//100*100`。

    参数:
        qty    : 目标数量(可为 float, 例如 cash/price 的结果)
        code   : 标的代码
        cfg    : 策略配置; None 则懒加载 strategy_config.json
        market : 显式市场; None 则由 market_of(code) 推断
        mode   : "floor"(默认, 向下取整, 买卖通用安全口径)
                 "ceil" (向上取整)
                 "nearest"(就近取整)

    返回: 非负整数, 必为 lot 的整数倍。qty <= 0 或非法输入返回 0。

    示例:
        round_qty(60,  "113050") -> 60   (转债 lot=10; 旧代码 60//100*100 == 0  ← 漏钱洞)
        round_qty(150, "113050") -> 150  (旧代码 150//100*100 == 100 ← 剩 50 张孤儿仓)
        round_qty(650, "01810")  -> 600  (小米 lot=200)
        round_qty(650, "600519") -> 600  (A 股 lot=100, 行为与改造前一致)
    """
    try:
        q = float(qty)
    except (TypeError, ValueError):
        return 0
    if q <= 0 or q != q:  # q != q 过滤 NaN
        return 0

    lot = lot_of(code, cfg=cfg, market=market)
    if lot <= 0:
        return 0

    lots = q / lot
    if mode == "ceil":
        import math

        n = math.ceil(lots - 1e-9)
    elif mode == "nearest":
        n = int(lots + 0.5)
    else:  # floor(默认)
        n = int(lots + 1e-9)
    return max(0, n * lot)


# ---------------------------------------------------------------------------
# 交易时段
# ---------------------------------------------------------------------------
def parse_sessions(spec: str) -> List[Tuple[_time, _time]]:
    """
    解析时段描述串 "09:30-11:30,13:00-15:00" -> [(time(9,30), time(11,30)), ...]。
    任何格式错误的片段被静默跳过; 全部失败则回退到 A 股默认时段。
    """
    out: List[Tuple[_time, _time]] = []
    for seg in str(spec or "").split(","):
        seg = seg.strip()
        if not seg or "-" not in seg:
            continue
        start_s, _, end_s = seg.partition("-")
        try:
            sh, sm = [int(x) for x in start_s.strip().split(":")]
            eh, em = [int(x) for x in end_s.strip().split(":")]
            out.append((_time(sh, sm), _time(eh, em)))
        except (ValueError, TypeError):
            continue
    if not out and spec != DEFAULT_SESSIONS:
        return parse_sessions(DEFAULT_SESSIONS)
    return out


def session_of(market: str = MARKET_A, cfg: Optional[dict] = None) -> str:
    """返回该市场的交易时段描述串(原样取自 config, 便于日志展示)。"""
    icfg = _instrument_cfg(cfg)
    rule = (icfg.get("lot_rules") or {}).get((market or MARKET_A).upper()) or {}
    spec = rule.get("sessions")
    return spec if isinstance(spec, str) and spec.strip() else DEFAULT_SESSIONS


def trade_sessions(market: str = MARKET_A, cfg: Optional[dict] = None) -> List[Tuple[_time, _time]]:
    """返回该市场的交易时段区间列表。A/ETF/KZZ 为两段, 港股午休更短、收盘更晚。"""
    return parse_sessions(session_of(market, cfg=cfg))


def is_trade_time(market: str = MARKET_A, now: Optional[datetime] = None,
                  cfg: Optional[dict] = None) -> bool:
    """
    判断给定市场当前是否处于交易时段(简单版, 不含节假日)。
    周六周日一律返回 False(A 股与港股共用此规则)。
    """
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    for start, end in trade_sessions(market, cfg=cfg):
        if start <= t <= end:
            return True
    return False


# ---------------------------------------------------------------------------
# 降级开关
# ---------------------------------------------------------------------------
def tradable_markets(cfg: Optional[dict] = None) -> Tuple[str, ...]:
    """返回可下单市场白名单。配置缺失时返回全部市场(向后兼容改造前行为)。"""
    raw = _market_cfg(cfg).get("tradable_markets")
    if not isinstance(raw, (list, tuple)) or not raw:
        return DEFAULT_TRADABLE_MARKETS
    return tuple(str(m).upper() for m in raw)


def is_tradable(market: str, cfg: Optional[dict] = None) -> bool:
    """
    降级开关判定: 该市场是否允许真实下单。

    当前 strategy_config.json 的 market.tradable_markets = ["A","ETF","KZZ"] —— 不含 HK,
    即港股"只选不买"(参与行情/评分/报表, 记为观察仓)。
    未来 mx-moni 确认支持港股下单后, 把 "HK" 加进该列表即可一行启用, 无需改码。
    """
    return (market or MARKET_A).upper() in tradable_markets(cfg)


if __name__ == "__main__":
    _cfg = load_config()
    print("=== market_of 形态推断 ===")
    for _c in ["00700", "01810", "113050", "123456", "510300", "159915", "600519", "sz000001", "hk00388"]:
        print(f"  {_c:<10} -> {market_of(_c)}")
    print("=== lot_of / round_qty ===")
    for _c, _q in [("00700", 350), ("01810", 650), ("00941", 1200), ("113050", 60),
                   ("113050", 150), ("600519", 650), ("510300", 1050)]:
        print(f"  {_c:<8} lot={lot_of(_c, _cfg):<4} round_qty({_q}) = {round_qty(_q, _c, _cfg)}")
    print("=== 交易时段 / 降级开关 ===")
    for _m in VALID_MARKETS:
        print(f"  {_m:<4} sessions={session_of(_m, _cfg):<26} tradable={is_tradable(_m, _cfg)}")
