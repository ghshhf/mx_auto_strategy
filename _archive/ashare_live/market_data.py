"""
market_data.py - 免费行情数据获取 (腾讯财经)
依赖: 仅标准库 (urllib, json, re)
用途: 为 auto_trader 提供 实时价 / 历史K线 / PE / 价格分位
"""
import os
import sys
import time
import json
import re
import logging
import urllib.error
import urllib.request
from datetime import datetime, time  # noqa: F401  (保留对外符号, 历史调用方可能引用)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import instrument  # noqa: E402  (v6.16 品种元数据单一真相源: 交易时段)

logger = logging.getLogger(__name__)

# 默认网络参数 (可被 strategy_config.market_data 覆盖)
_DEFAULT_TIMEOUT_SEC = 10
_DEFAULT_RETRIES = 2
_DEFAULT_RETRY_BACKOFF = 0.5  # 秒, 指数退避基数

PREFIX = {"6": "sh", "0": "sz", "3": "sz", "9": "sh"}
# ETF 代码映射: 51xxxx->sh(沪), 15xxxx->sz(深), 其它5位默认sh
ETF_PREFIX = {"5": "sh", "1": "sz"}

# 常见指数代码映射 (避免 000xxx 个股与指数冲突)
INDEX_PREFIX = {
    "000001": "sh", "000002": "sh", "000003": "sh", "000004": "sh",
    "000005": "sh", "000006": "sh", "000007": "sh", "000008": "sh",
    "000009": "sh", "000010": "sh", "000016": "sh", "000043": "sh",
    "000049": "sh", "000050": "sh", "000052": "sh", "000054": "sh",
    "000090": "sh", "000104": "sh", "000132": "sh", "000133": "sh",
    "000134": "sh", "000135": "sh", "000136": "sh", "000137": "sh",
    "000138": "sh", "000139": "sh", "000141": "sh", "000142": "sh",
    "000143": "sh", "000145": "sh", "000146": "sh", "000147": "sh",
    "000148": "sh", "000149": "sh", "000150": "sh", "000151": "sh",
    "000152": "sh", "000153": "sh", "000155": "sh", "000157": "sh",
    "000158": "sh", "000159": "sh", "000160": "sh", "000161": "sh",
    "000162": "sh", "000163": "sh", "000164": "sh", "000165": "sh",
    "000166": "sh", "000167": "sh", "000168": "sh", "000169": "sh",
    "000170": "sh", "000171": "sh", "000300": "sh", "000688": "sh",
    "000852": "sh", "000905": "sh", "000932": "sh", "000933": "sh",
    "000934": "sh", "000935": "sh", "000936": "sh", "000937": "sh",
    "000938": "sh", "000939": "sh", "000940": "sh", "000941": "sh",
    "000942": "sh", "000943": "sh", "000944": "sh", "000945": "sh",
    "000946": "sh", "000947": "sh", "000948": "sh", "000949": "sh",
    "000950": "sh", "000951": "sh", "000952": "sh", "000953": "sh",
    "399001": "sz", "399002": "sz", "399003": "sz", "399004": "sz",
    "399005": "sz", "399006": "sz", "399007": "sz", "399008": "sz",
    "399009": "sz", "399010": "sz", "399011": "sz", "399012": "sz",
    "399100": "sz", "399101": "sz", "399102": "sz", "399103": "sz",
    "399106": "sz", "399107": "sz", "399108": "sz", "399330": "sz",
    "399481": "sz",
}


def _net_cfg():
    """从 strategy_config.market_data 读 timeout/retries/backoff, 失败/缺省用默认值。"""
    try:
        mcfg = instrument.load_config().get("market_data") or {}
        return {
            "timeout": int(mcfg.get("timeout_sec", _DEFAULT_TIMEOUT_SEC)),
            "retries": int(mcfg.get("retries", _DEFAULT_RETRIES)),
            "backoff": float(mcfg.get("retry_backoff_sec", _DEFAULT_RETRY_BACKOFF)),
        }
    except Exception:
        return {"timeout": _DEFAULT_TIMEOUT_SEC,
                "retries": _DEFAULT_RETRIES,
                "backoff": _DEFAULT_RETRY_BACKOFF}


def _get(url, decode="gbk", timeout=None):
    """带重试 + 日志的 HTTP GET。

    H5: 旧实现单次 urlopen 失败即抛, 上层 get_realtime/get_kline 用裸 except 静默吞,
        网络抖动时策略看不到行情会静默跳过买卖/止损。现加 2 次指数退避重试 + warning 日志。
    timeout 可显式传入, 默认从 config.market_data.timeout_sec 读。
    """
    nc = _net_cfg()
    if timeout is None:
        timeout = nc["timeout"]
    retries = nc["retries"]
    backoff = nc["backoff"]
    last_err = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; mx-auto/1.0)",
            "Referer": "https://finance.qq.com/"
        })
        try:
            return urllib.request.urlopen(req, timeout=timeout).read().decode(decode)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
            if attempt < retries:
                # 指数退避: 0.5s, 1.0s, 2.0s ...
                time.sleep(backoff * (2 ** attempt))
                continue
    # 全部重试失败, 记 warning (旧实现静默吞, 现在留痕便于排查)
    logger.warning("HTTP GET 失败 (重试%d次): %s | url=%s", retries, last_err, url[:120])
    raise last_err if last_err else RuntimeError("HTTP GET 失败: " + url)


class UnknownCodeError(KeyError):
    """代码格式无法识别 (前缀表里没登记)。"""


def _pad(code):
    """腾讯行情代码前缀补全:
    A股: 6/9->sh, 0/3->sz;  ETF: 51/15开头同A股规则;
    港股(hk前缀或5位): hk+代码;  已有前缀(sh/sz/hk)原样返回。
    指数: 000xxx/399xxx 系列通过 INDEX_PREFIX 映射, 避免与个股冲突。
    注意: 若需查询冲突个股(如000001平安银行), 请传带前缀的 sz000001。

    M10: 旧实现空代码 -> code[0] IndexError, 未知前缀 -> PREFIX[X] KeyError 直接炸穿
         到调用方。现对空/异常代码明确报错, 让 get_realtime/get_kline 能捕获并跳过。
    """
    if not code or not isinstance(code, str) or not code.strip():
        raise UnknownCodeError("代码为空或非字符串")
    code = code.strip()
    if code.startswith(("sh", "sz", "hk")):
        return code
    # 常见指数代码优先判断 (避免 000001 等个股/指数冲突)
    if code in INDEX_PREFIX:
        return f"{INDEX_PREFIX[code]}{code}"
    if len(code) == 5:  # 港股5位代码
        return f"hk{code}"
    if not code.isdigit():
        raise UnknownCodeError(f"代码含非数字字符: {code!r}")
    # 可转债优先判断 (沪市11xxxx→sh, 深市12xxxx→sz) — 必须在ETF分支前
    if code[0] == "1" and code[1] == "1" and len(code) == 6:
        return f"sh{code}"          # 沪市转债 113xxx/110xxx/111xxx
    if code[0] == "1" and code[1] == "2" and len(code) == 6:
        return f"sz{code}"          # 深市转债 123xxx/127xxx/128xxx
    if code[0] in ("5", "1") and len(code) == 6:
        # ETF: 51xxxx->sh, 15xxxx->sz (此处1开头仅剩15xxxx类)
        return f"{ETF_PREFIX.get(code[0], 'sh')}{code}"
    if code[0] not in PREFIX:
        raise UnknownCodeError(f"未知代码前缀: {code!r}")
    return f"{PREFIX[code[0]]}{code}"


def _derive_turnover(fnum, is_hk):
    """
    换手率(%)统一口径。

    A 股 (88 字段): [38] 由腾讯自报, 直接用 —— 保持与改造前逐位一致(防回归)。
    港股 (78 字段): [38] 恒为 '0'(腾讯不提供), 必须派生:
                        换手率% = 成交额[37] / 1e8 / 总市值[44](亿) * 100
                    注意单位差异 —— 港股 [37] 单位是「元」, A 股 [37] 单位是「万元」。

    同尺度验证(实测 2026-07-31 收盘):
        A 股用 [37]/1e4/[44]*100 反算自报值: 茅台 0.4367≈0.44 / 工行 0.2211≈0.22 /
        五粮液 1.2825≈1.28  → 误差 < 0.01pp, 证明派生公式与 A 股口径同尺度, 无反向偏置。

    返回 float 或 None(数据不足)。None 会让 selector 走 pop_score=0.5 中性回退。
    """
    if not is_hk:
        return fnum(38)
    amount = fnum(37)     # 港股成交额, 单位: 元
    total_mv = fnum(44)   # 总市值, 单位: 亿
    if amount is None or total_mv is None or total_mv <= 0 or amount < 0:
        return None
    return round(amount / 1e8 / total_mv * 100, 4)


def _parse_quote(prefixed, parts):
    """
    把腾讯行情单条报文的字段数组解析成统一 dict。
    prefixed: 带前缀的代码(如 hk00700 / sh600519), 用于判定市场分支。
    parts   : 报文按 '~' 切分后的字段数组。

    M11: 字段下标硬编码 (fnum(38)/fnum(44) 等)。腾讯改字段顺序会静默返回错误 PE/换手。
         这正是 v6.16 eastmoney 字段错位导致 16.29x 假数的同类风险。现加字段数断言。
    """
    is_hk = str(prefixed).lower().startswith("hk")
    # A股 88 字段, 港股 78 字段。不足则字段下标访问会越界/静默错位
    min_fields = 47 if is_hk else 47
    if len(parts) < min_fields:
        logger.warning("行情字段数不足 (%s): %d < %d, 跳过 (代码=%s)",
                       "港股" if is_hk else "A股", len(parts), min_fields, prefixed)
        return None

    def g(i):
        return parts[i] if i < len(parts) else ""

    def fnum(i):
        """安全解析浮点: 复合串取第一段, 非法返回None"""
        s = g(i).split("/")[0].strip()
        try:
            return float(s) if s else None
        except ValueError:
            return None

    # 港股 [46] 是英文名(如 'TENCENT'/'XIAOMI-W'), 不是 PB —— 显式置 None, 避免污染数值字段。
    # (fnum 本身也会因 ValueError 返回 None, 此处显式化以表达意图。)
    pb = None if is_hk else fnum(46)

    price = fnum(3)
    # sanity check: 价格必须为正, 否则字段错位/停牌假数据, 返回 None 让上层跳过
    if price is None or price <= 0:
        return None

    return {
        "name": g(1),
        "price": price,
        "prev_close": fnum(4),
        "open": fnum(5),
        "pe_ttm": fnum(39),
        "pe_dynamic": fnum(39),
        "pb": pb,
        "turnover_pct": _derive_turnover(fnum, is_hk),
        # 港股无涨跌停, [41]/[42] 恒为 0.0(假值) —— 下游 `if limit_down and ...`
        # 判断会自动跳过, 行为恰好正确, 不要"修".
        "limit_up": fnum(41),
        "limit_down": fnum(42),
        "total_mv": g(44),
        "circ_mv": g(45),
        "market": instrument.market_of(prefixed),
    }


def get_realtime(codes):
    """
    获取实时行情。交易时段返回数据, 非交易时段可能为空(正常)。
    返回: {code: {price, pe_ttm, pe_dynamic, pb, turnover_pct, name, market, ...}}
    v6.16: 拆出 _parse_quote 分市场解析, 港股换手率由成交额/市值派生。
    """
    if isinstance(codes, str):
        codes = [codes]
    # M10: 跳过无法识别的代码, 不让一只坏代码炸掉整批行情
    padded = []
    code_map = {}  # padded -> original code
    for c in codes:
        try:
            p = _pad(c)
            padded.append(p)
            code_map[p] = c
        except UnknownCodeError as e:
            logger.warning("get_realtime 跳过无效代码 %r: %s", c, e)
    if not padded:
        return {}
    q = ",".join(padded)
    url = f"https://qt.gtimg.cn/q={q}"
    try:
        raw = _get(url, "gbk")
    except Exception:
        return {}
    out = {}
    for m in re.findall(r'v_(\w+)="([^"]*)"', raw):
        code, data = m[0], m[1]
        if code == "pv_none_match":
            continue
        parts = data.split("~")
        parsed = _parse_quote(code, parts)
        # M11: _parse_quote 字段不足/价格非正时返回 None, 跳过该条
        if parsed is None:
            continue
        out[code[2:]] = parsed
    return out


def get_kline(code, ktype="day", count=260):
    """
    获取历史K线 (用于价格分位计算)。
    code 支持纯数字(自动加sh/sz前缀) 或 已带前缀(如 sh000300 / sz399001)。
    返回: [{"date","open","close","high","low","vol"}, ...] 升序
    """
    # 已带 sh/sz 前缀 -> 直接用; 否则自动补
    if code[:2] in ("sh", "sz"):
        prefixed = code
    else:
        try:
            prefixed = _pad(code)
        except UnknownCodeError as e:
            logger.warning("get_kline 跳过无效代码 %r: %s", code, e)
            return []
    q = f"{prefixed},{ktype},,,{count},"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={q}"
    try:
        raw = _get(url, "utf-8")
    except Exception:
        return []
    try:
        j = json.loads(raw)
        node = j["data"].get(prefixed, {})
        arr = node.get(ktype, [])
        result = []
        for r in arr:
            # [date, open, close, high, low, vol, ...]
            result.append({
                "date": r[0], "open": float(r[1]), "close": float(r[2]),
                "high": float(r[3]), "low": float(r[4]), "vol": float(r[5]) if len(r) > 5 else 0
            })
        return result
    except Exception as e:
        logger.warning("get_kline 解析失败 (%s): %s", code, e)
        return []


def price_percentile(code, window=250, ktype="day"):
    """
    计算当前价在近 window 日价格区间的分位(0~1)。
    返回: (current_price, percentile)  percentile越低=越接近历史低位
    """
    kl = get_kline(code, ktype, window + 5)
    if not kl:
        return None, None
    kl = kl[-window:]
    lows = [k["low"] for k in kl]
    highs = [k["high"] for k in kl]
    cur = kl[-1]["close"]
    minp, maxp = min(lows), max(highs)
    if maxp == minp:
        pct = 0.5
    else:
        # 用最高/最低构成的区间定位当前价分位
        pct = (cur - minp) / (maxp - minp)
    return cur, round(pct, 3)


def is_trade_time(now=None, market="A"):
    """
    判断当前是否为交易时段(简单版, 不含节假日)。

    v6.16: 支持分市场时段, 时段表来自 instrument(读 strategy_config.json):
        A / ETF / KZZ : 09:30-11:30, 13:00-15:00
        HK            : 09:30-12:00, 13:00-16:00  (港股午休更短、收盘更晚, 每日多 1.5 小时)

    ⚠️ 参数顺序保持 (now, market) 而非设计稿的 (market, now) —— 因为
       market_adapter.py:75 存在位置调用 `md.is_trade_time(now)`, 换序会把
       datetime 误当 market 传入。无参调用 is_trade_time() 语义仍为 A 股(向后兼容)。
    """
    return instrument.is_trade_time(market=market or "A", now=now)


if __name__ == "__main__":
    # 自测
    print("=== K线分位测试 ===")
    for c in ["603259", "601398"]:
        cur, pct = price_percentile(c)
        print(f"{c}: 当前/最新={cur} 历史分位={pct}")
    print("=== 实时行情测试(交易时段才有) ===")
    rt = get_realtime(["603259", "601398"])
    print(json.dumps(rt, ensure_ascii=False, indent=2))
