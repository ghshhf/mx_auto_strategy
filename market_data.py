"""
market_data.py - 免费行情数据获取 (腾讯财经)
依赖: 仅标准库 (urllib, json, re)
用途: 为 auto_trader 提供 实时价 / 历史K线 / PE / 价格分位
"""
import urllib.request
import json
import re
from datetime import datetime, time

PREFIX = {"6": "sh", "0": "sz", "3": "sz", "9": "sh"}
# ETF 代码映射: 51xxxx->sh(沪), 15xxxx->sz(深), 其它5位默认sh
ETF_PREFIX = {"5": "sh", "1": "sz"}


def _get(url, decode="gbk", timeout=10):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; mx-auto/1.0)",
        "Referer": "https://finance.qq.com/"
    })
    return urllib.request.urlopen(req, timeout=timeout).read().decode(decode)


def _pad(code):
    """腾讯行情代码前缀补全:
    A股: 6/9->sh, 0/3->sz;  ETF: 51/15开头同A股规则;
    港股(hk前缀或5位): hk+代码;  已有前缀(sh/sz/hk)原样返回。"""
    if code.startswith(("sh", "sz", "hk")):
        return code
    if len(code) == 5:  # 港股5位代码
        return f"hk{code}"
    # 可转债优先判断 (沪市11xxxx→sh, 深市12xxxx→sz) — 必须在ETF分支前
    if code[0] == "1" and code[1] == "1" and len(code) == 6:
        return f"sh{code}"          # 沪市转债 113xxx/110xxx/111xxx
    if code[0] == "1" and code[1] == "2" and len(code) == 6:
        return f"sz{code}"          # 深市转债 123xxx/127xxx/128xxx
    if code[0] in ("5", "1") and len(code) == 6:
        # ETF: 51xxxx->sh, 15xxxx->sz (此处1开头仅剩15xxxx类)
        return f"{ETF_PREFIX.get(code[0], 'sh')}{code}"
    return f"{PREFIX[code[0]]}{code}"


def get_realtime(codes):
    """
    获取实时行情。交易时段返回数据, 非交易时段可能为空(正常)。
    返回: {code: {price, pe_ttm, pe_dynamic, pb, turnover, name, ...}}
    """
    if isinstance(codes, str):
        codes = [codes]
    q = "|".join(_pad(c) for c in codes)
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
        if len(parts) < 50:
            # 字段不全(非交易时段部分字段缺失), 仍尽量解析
            pass
        def g(i):
            return parts[i] if i < len(parts) else ""

        def fnum(i):
            """安全解析浮点: 复合串取第一段, 非法返回None"""
            s = g(i).split("/")[0].strip()
            try:
                return float(s) if s else None
            except ValueError:
                return None

        out[code[2:]] = {
            "name": g(1),
            "price": fnum(3),
            "prev_close": fnum(4),
            "open": fnum(5),
            "pe_ttm": fnum(39),
            "pe_dynamic": fnum(39),
            "pb": fnum(46),
            "turnover_pct": fnum(38),
            "limit_up": fnum(41),
            "limit_down": fnum(42),
            "total_mv": g(44),
            "circ_mv": g(45),
        }
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
        prefixed = _pad(code)
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
    except Exception:
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


def is_trade_time(now=None):
    """判断当前是否为交易时段(简单版, 不含节假日)"""
    now = now or datetime.now()
    if now.weekday() >= 5:  # 周末
        return False
    t = now.time()
    am = (time(9, 30) <= t <= time(11, 30))
    pm = (time(13, 0) <= t <= time(15, 0))
    return am or pm


if __name__ == "__main__":
    # 自测
    print("=== K线分位测试 ===")
    for c in ["603259", "601398"]:
        cur, pct = price_percentile(c)
        print(f"{c}: 当前/最新={cur} 历史分位={pct}")
    print("=== 实时行情测试(交易时段才有) ===")
    rt = get_realtime(["603259", "601398"])
    print(json.dumps(rt, ensure_ascii=False, indent=2))
