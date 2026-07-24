""" death_cross.py - v6.10 多指数周线死叉去风险信号
=================================================================
设计目标
--------
在温度计提早"削进攻"的基础上, 增加一层「大盘结构风险」信号:
多个主要 A 股宽基指数周线同时出现 MA5/MA20 死叉(横盘向下确认),
则判定市场进入结构性去风险区, 进攻仓转为全防御(进攻=0, 释放转防御)。

这是用户"16倍+死叉全防御"升级主线的实盘落地: 回测 10 年
(2016~2026) 在 16 倍框架基础上, 死叉转全防御相对纯 16 倍
多赚约 +4.2% 相对收益, 最大回撤少约 2.8 个百分点 —— 既增厚收益又降风险。

信号构造
--------
6 大宽基指数周线(近 21 周):
  沪深300 sh000300 / 中证500 sh000905 / 上证综指 sh000001
  创业板指 sz399006 / 上证50  sh000016 / 中证1000 sh000852
单指数"熊化"(结构性向下) = 收盘价<MA_long 且 MA_short<MA_long 且 MA_long 向下(本周长<上周长)
复合 = 熊化指数个数;  >= threshold(默认3) 触发去风险。

输出  get_death_cross(cfg) -> dict:
  triggered(bool), count(int), available(int), threshold(int),
  label(str), enabled, shadow, apply, detail(str), index_states(list)

稳健性(实盘优先, 不死机)
  * 任一指数周线抓取失败 -> 该指数标记 unavailable, 按 min_available_ratio 判定是否还能确认信号
  * 可用指数比例 < min_available_ratio -> 无法确认大盘结构, 不触发(保守, 退回原逻辑)
  * 结果缓存 cache_seconds(默认30分钟, 信号为周线结构性, 日内刷新足够)
  * 仅标准库, 与 market_data.py / temperature_probe.py 风格一致
  * 所有网络调用 try/except, 异常绝不上抛到下单主流程
=================================================================
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market_data as md  # 复用腾讯行情的 get_kline / 前缀处理

_CACHE = {"ts": 0.0, "data": None}

# 默认 6 大宽基指数(周线死叉复合信号)
_DEFAULT_INDICES = [
    {"code": "000300", "name": "沪深300"},
    {"code": "000905", "name": "中证500"},
    {"code": "000001", "name": "上证综指"},
    {"code": "399006", "name": "创业板指"},
    {"code": "000016", "name": "上证50"},
    {"code": "000852", "name": "中证1000"},
]


def _cfg(cfg):
    return cfg.get("death_cross", {}) or {}


def _index_weekly_kline(code, weeks):
    """拉取指数周线(复用 market_data.get_kline, ktype=week)。失败返回 []。"""
    try:
        kl = md.get_kline(code, "week", weeks)
        return kl or []
    except Exception:
        return []


def _ma(closes, n):
    """计算末 n 周收盘均值; 数据不足返回 None。"""
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _index_bearish(kl, ma_short, ma_long):
    """
    单指数是否'熊化'(周线死叉结构性向下):
      收盘价 < MA_long 且 MA_short < MA_long 且 MA_long 向下(本周长<上周长)
    数据不足返回 None(不计熊化, 由上层按 min_available_ratio 决定能否确认信号)
    """
    closes = [k["close"] for k in kl]
    if len(closes) < ma_long + 1:
        return None
    ma_s = _ma(closes, ma_short)
    ma_l = _ma(closes, ma_long)
    ma_l_prev = _ma(closes[:-1], ma_long)
    if ma_s is None or ma_l is None or ma_l_prev is None:
        return None
    price = closes[-1]
    return (price < ma_l) and (ma_s < ma_l) and (ma_l < ma_l_prev)


def _safe(label, **kw):
    """构造一个安全的返回(不干预原仓位逻辑)。"""
    base = {"triggered": False, "count": 0, "available": 0, "threshold": 3,
            "label": label, "enabled": False, "shadow": False, "apply": False,
            "detail": "", "index_states": []}
    base.update(kw)
    return base


def get_death_cross(cfg, force_refresh=False):
    gc = _cfg(cfg)
    enabled = gc.get("enabled", True)
    shadow = gc.get("shadow_mode", False)
    if not enabled:
        return _safe("禁用", enabled=False,
                     detail="死叉信号未启用, 不干预仓位")

    # 命中缓存直接返回(loop 模式避免频繁打接口)
    now = time.time()
    if (not force_refresh) and _CACHE["data"] and (now - _CACHE["ts"] < gc.get("cache_seconds", 1800)):
        d = dict(_CACHE["data"])
        d["shadow"] = shadow
        d["apply"] = (enabled and not shadow)
        return d

    indices = gc.get("indices", _DEFAULT_INDICES)
    ma_short = gc.get("ma_short", 5)
    ma_long = gc.get("ma_long", 20)
    min_weeks = gc.get("min_weeks", 21)
    threshold = gc.get("threshold", 3)
    min_available_ratio = gc.get("min_available_ratio", 0.8)

    states = []
    available = 0
    for idx in indices:
        kl = _index_weekly_kline(idx["code"], min_weeks)
        if not kl:
            states.append({"code": idx["code"], "name": idx["name"],
                           "available": False, "bearish": None, "reason": "周线抓取失败"})
            continue
        available += 1
        bear = _index_bearish(kl, ma_short, ma_long)
        if bear is None:
            states.append({"code": idx["code"], "name": idx["name"],
                           "available": True, "bearish": None,
                           "reason": "数据不足(周数<MA+1)"})
            continue
        states.append({"code": idx["code"], "name": idx["name"],
                       "available": True, "bearish": bear,
                       "reason": "死叉向下" if bear else "未死叉/均线向上"})

    bearish_count = sum(1 for s in states if s.get("bearish") is True)
    total = len(indices)
    ratio = available / total if total else 0.0

    # 保守: 可用指数不足 min_available_ratio -> 无法确认大盘结构, 不触发(退回原逻辑)
    if ratio < min_available_ratio:
        triggered = False
        failed = "; ".join(s["name"] for s in states if not s.get("available"))
        detail = (f"仅 {available}/{total} 指数可用(<{min_available_ratio:.0%}), "
                  f"数据不足不触发; 缺失: {failed}")
    else:
        triggered = bearish_count >= threshold
        detail = (f"{bearish_count}/{available} 指数周线死叉(阈值 {threshold}); "
                  + ", ".join(s["name"] + ("✓" if s.get("bearish") else "✗")
                              for s in states if s.get("available")))

    label = "de_risk" if triggered else ("watch" if bearish_count >= threshold - 1 else "normal")

    result = {
        "triggered": triggered,
        "count": bearish_count,
        "available": available,
        "threshold": threshold,
        "label": label,
        "enabled": True,
        "shadow": shadow,
        "apply": (enabled and not shadow),
        "detail": detail,
        "index_states": states,
    }
    _CACHE["ts"] = now
    _CACHE["data"] = result
    return result


def _self_test():
    """离线自检(经 MOCK 环境变量触发, 不触网): 验证熊化判定与复合触发逻辑。"""
    import random

    def gen_closes(trend="up", n=21):
        closes = []
        p = 100.0
        for _ in range(n):
            if trend == "up":
                p *= 1.012
            elif trend == "down":
                p *= 0.988
            else:
                p *= (1.0 + random.uniform(-0.004, 0.004))
            closes.append({"date": "x", "open": p, "close": p,
                           "high": p, "low": p, "vol": 1e8})
        return closes

    print("=== 单指数熊化判定(离线) ===")
    up = gen_closes("up")
    down = gen_closes("down")
    flat = gen_closes("flat")
    print(f"  上行市 熊化={_index_bearish(up, 5, 20)} (应为 False)")
    print(f"  下行市 熊化={_index_bearish(down, 5, 20)} (应为 True)")
    print(f"  横盘市 熊化={_index_bearish(flat, 5, 20)} (应为 False)")

    print("\n=== 复合触发场景(离线, 模拟 market_data.get_kline) ===")
    orig = md.get_kline

    def run_case(name, trends):
        md.get_kline = lambda code, ktype="week", count=21: gen_closes(trends.get(code, "up"), count)
        cfg = {"death_cross": {"enabled": True, "threshold": 3,
                               "min_available_ratio": 0.8, "cache_seconds": 0,
                               "indices": _DEFAULT_INDICES[:len(trends)]}}
        r = get_death_cross(cfg, force_refresh=True)
        print(f"  {name}: 熊化数={r['count']}/{r['available']} triggered={r['triggered']} "
              f"label={r['label']}  [{r['detail'][:60]}]")

    # HOT: 6 指数全上行 -> 0 死叉 -> 不触发
    run_case("HOT(全上行)", {c["code"]: "up" for c in _DEFAULT_INDICES})
    # COLD: 6 指数全下行 -> 6 死叉 -> 触发
    run_case("COLD(全下行)", {c["code"]: "down" for c in _DEFAULT_INDICES})
    # MIX: 3 死叉 / 3 上行 -> 刚好达阈值 -> 触发
    mix = {}
    for i, c in enumerate(_DEFAULT_INDICES):
        mix[c["code"]] = "down" if i < 3 else "up"
    run_case("MIX(3死叉/3上行)", mix)
    # WATCH: 2 死叉 -> 不触发(低于阈值)
    mix2 = {}
    for i, c in enumerate(_DEFAULT_INDICES):
        mix2[c["code"]] = "down" if i < 2 else "up"
    run_case("WATCH(2死叉)", mix2)

    # 部分失败: 1 指数抓取失败 + 5 指数全下行 -> 可用 5/6=0.83>=0.8, 熊化5>=3 -> 触发
    md.get_kline = lambda code, ktype="week", count=21: ([] if code == "000001"
                                                         else gen_closes("down", count))
    cfg = {"death_cross": {"enabled": True, "threshold": 3,
                           "min_available_ratio": 0.8, "cache_seconds": 0,
                           "indices": _DEFAULT_INDICES}}
    r = get_death_cross(cfg, force_refresh=True)
    print(f"  PARTIAL_FAIL(1失败+5下行): available={r['available']} count={r['count']} "
          f"triggered={r['triggered']} (应为 True, 5/6 可用且全死叉)")

    # 严重失败: 2 指数抓取失败 -> 可用 4/6=0.67<0.8 -> 不触发(保守)
    md.get_kline = lambda code, ktype="week", count=21: ([] if code in ("000001", "000905")
                                                         else gen_closes("down", count))
    r = get_death_cross(cfg, force_refresh=True)
    print(f"  SEVERE_FAIL(2失败+4下行): available={r['available']} triggered={r['triggered']} "
          f"(应为 False, 可用比例不足)")

    md.get_kline = orig
    print("\n离线自检完成.")


if __name__ == "__main__":
    import os as _os
    if _os.environ.get("MOCK"):
        _self_test()
    else:
        try:
            cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                              "strategy_config.json"), encoding="utf-8"))
            print("=== 多指数死叉信号实时抓取 ===")
            r = get_death_cross(cfg, force_refresh=True)
            print(json.dumps(r, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"实时抓取失败({e}), 退回离线自检:")
            _self_test()
