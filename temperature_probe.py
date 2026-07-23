""" temperature_probe.py - v6.9 市场冷热温度计 (方案C, 纯国内A股)
=================================================================
设计目标
--------
给 auto_trader 提供一个轻量的"市场冷热/强弱"观测, 作为「进攻时机的刻度」
(不是硬防御开关)。综合 4 个国内维度加权成 0~100 的温度:

    breadth 宽度(全A涨跌家数比)        权重 30%
    volume  量能(全市场成交额 / 20日均量) 权重 30%
    trend   趋势(沪深300 对20日MA偏离, 复用 market_data) 权重 25%
    funding 资金(沪深两融/融资余额环比)  权重 15%

海外(美股 VIX)仅作「参考标签」, 不参与打分, 不参与决策。

输出  get_market_temperature(cfg) -> dict:
    score, label(hot/warm/cold), fragile(bool), vix_tag(str),
    offense_multiplier(0~1), enabled, shadow, apply, detail, _parts

稳健性(实盘优先, 不死机)
------------------------
  * 任一维度抓取失败 -> 该维度权重 redistributed 到其他可用维度(renormalize)
  * 全部失败         -> offense_multiplier = 1.0 (等于不干预, 退回原逻辑)
  * 结果缓存 cache_seconds, 避免 loop 模式频繁打接口
  * 仅标准库(urllib/json), 与 market_data.py 风格一致, 无第三方依赖
  * 所有网络调用均 try/except, 异常绝不上抛到下单主流程
=================================================================
"""
import os
import sys
import json
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market_data as md  # 复用腾讯行情的 get_kline / 前缀处理

_CACHE = {"ts": 0.0, "data": None}


def _cfg(cfg):
    return cfg.get("temperature_probe", {}) or {}


def _get_json(url, timeout=10):
    """拉取 JSON, 与 market_data._get 同源风格(仅标准库)。"""
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; mx-temp/1.0)",
        "Referer": "https://quote.eastmoney.com/",
    })
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
    return json.loads(raw)


# ---------------------------------------------------------------------------
# 维度抓取 (任一函数返回 None 表示该维度本次不可用, 由上层降权处理)
# ---------------------------------------------------------------------------
def fetch_breadth():
    """全A涨跌家数 -> (up, down, flat)。东方财富 clist 全市场, 统计 f3(涨跌幅)。"""
    url = ("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10000&po=1&np=1"
           "&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
           "&fields=f12,f14,f3")
    try:
        j = _get_json(url)
        rows = (j.get("data") or {}).get("diff") or []
        up = sum(1 for r in rows if (r.get("f3") or 0) > 0)
        down = sum(1 for r in rows if (r.get("f3") or 0) < 0)
        flat = len(rows) - up - down
        if up + down == 0:
            return None
        return up, down, flat
    except Exception:
        return None


def fetch_market_volume():
    """全市场成交额(沪+深) 与 20日均值 -> (today_amt, avg20_amt)。单位: 元。"""
    tot_today = 0.0
    hist = []
    for secid in ("1.000001", "0.399001"):
        url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}"
               f"&klt=101&fqt=1&lmt=21&fields1=f1,f2&fields2=f51,f57")
        try:
            j = _get_json(url)
            kl = (((j.get("data") or {}).get(secid) or {}).get("klines") or [])
            for r in kl:
                parts = r.split(",")
                try:
                    amt = float(parts[1])  # fields2=f51(日期),f57(成交额)
                except (ValueError, IndexError):
                    continue
                hist.append(amt)
        except Exception:
            continue
    if not hist:
        return None
    tot_today = hist[-1]
    avg = sum(hist[:-1]) / max(1, len(hist) - 1) if len(hist) > 1 else hist[0]
    return tot_today, avg


def fetch_trend_dev(cfg):
    """沪深300 对 20日MA 偏离% (与 selector.market_regime 同口径, 复用 market_data)。"""
    bench = cfg.get("auto_select", {}).get("defensive_benchmark", "sh000300")
    ma_days = cfg.get("auto_select", {}).get("defensive_ma_days", 20)
    try:
        kl = md.get_kline(bench, "day", ma_days + 5)
        if len(kl) < ma_days:
            return None
        closes = [k["close"] for k in kl[-ma_days:]]
        ma = sum(closes) / len(closes)
        last = closes[-1]
        return (last - ma) / ma * 100
    except Exception:
        return None


def fetch_margin_debt():
    """沪深融资余额最新值 + 环比变化% -> (latest, pct_change)。东方财富数据中心。"""
    vals = {}
    pct = None
    for scode in ("SH", "SZ"):
        url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPTA_WEB_RZRQ_GDMX"
               f"&columns=ALL&filter=(SCODE%3D%22{scode}%22)&pageSize=2&sortColumns=DATE&sortTypes=-1"
               "&source=WEB&client=WEB")
        try:
            j = _get_json(url)
            rows = (j.get("result") or {}).get("data") or []
            if len(rows) >= 1:
                cur = float(rows[0].get("RZYE") or rows[0].get("RZYE") or 0)
                vals[scode] = cur
                if len(rows) >= 2:
                    prev = float(rows[1].get("RZYE") or rows[1].get("RZYE") or 0)
                    if prev:
                        pct = (cur - prev) / prev * 100
        except Exception:
            continue
    if not vals:
        return None
    latest = sum(vals.values())
    return latest, (pct or 0.0)


def fetch_vix():
    """海外参考 ONLY: 美股 VIX。失败返回 None, 不影响任何决策。"""
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=1d&interval=1d"
        j = _get_json(url)
        return j["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 维度打分 (输入已归一化到 0~1; None 表示维度缺失)
# ---------------------------------------------------------------------------
def _score_breadth(up, down, flat):
    adv = up / (up + down) if (up + down) else 0.5
    return max(0.0, min(1.0, (adv - 0.2) / 0.6))  # 0.2->0, 0.5->0.5, 0.8->1


def _score_volume(today, avg):
    r = today / avg if avg else 1.0
    return max(0.0, min(1.0, (r - 0.7) / 0.9))   # 0.7->0, 1.6->1


def _score_trend(dev_pct):
    return max(0.0, min(1.0, (dev_pct + 5) / 10))  # -5%->0, 0%->0.5, +5%->1


def _score_funding(pct_change):
    return max(0.0, min(1.0, (pct_change + 2) / 4))  # -2%->0, 0%->0.5, +2%->1


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def get_market_temperature(cfg, force_refresh=False):
    gc = _cfg(cfg)
    enabled = gc.get("enabled", True)
    shadow = gc.get("shadow_mode", False)
    if not enabled:
        return {"score": 50.0, "label": "warm", "fragile": False, "vix_tag": "禁用",
                "offense_multiplier": 1.0, "enabled": False, "shadow": False,
                "apply": False, "detail": "温度计未启用, 不干预仓位", "_parts": {}}

    # 命中缓存直接返回(loop 模式避免频繁打接口)
    now = time.time()
    if (not force_refresh) and _CACHE["data"] and (now - _CACHE["ts"] < gc.get("cache_seconds", 300)):
        d = dict(_CACHE["data"])
        d["shadow"] = shadow
        d["apply"] = (enabled and not shadow)
        return d

    w = gc.get("weights", {"breadth": 0.30, "volume": 0.30, "trend": 0.25, "funding": 0.15})

    # 抓取各维度
    br = fetch_breadth()
    vol = fetch_market_volume()
    dev = fetch_trend_dev(cfg)
    fd = fetch_margin_debt()

    parts = {}
    if br:
        parts["breadth"] = _score_breadth(*br)
    if vol:
        parts["volume"] = _score_volume(*vol)
    if dev is not None:
        parts["trend"] = _score_trend(dev)
    if fd:
        parts["funding"] = _score_funding(fd[1])

    # 全部维度缺失 -> 数据源全失败, 安全退回原逻辑(不干预仓位, 倍率=1.0)
    if not parts:
        return {"score": 0.0, "label": "unknown", "fragile": False, "vix_tag": "数据源全失败",
                "offense_multiplier": 1.0, "enabled": True, "shadow": shadow,
                "apply": (enabled and not shadow),
                "detail": "全部维度抓取失败, 退回原仓位逻辑(不干预)", "_parts": {}}

    # 可用维度权重重归一化(缺失维度不计入, 权重转移给其余维度)
    avail_w = {k: w.get(k, 0.0) for k in parts}
    tot = sum(avail_w.values()) or 1.0
    score = sum(parts[k] * avail_w[k] for k in parts) / tot * 100

    # 脆弱标记: 缩量(量能<0.35) 且 (宽度差 或 两融环比转负)
    fragile = False
    if "volume" in parts and parts["volume"] < 0.35:
        if ("breadth" in parts and parts["breadth"] < 0.4) or \
           ("funding" in parts and parts["funding"] < 0.4):
            fragile = True

    # 温度 -> 进攻倍率
    # 设计: 正常/偏热市(温度>=reduce_below)进攻不打折; 仅当转冷(30~reduce_below)逐步收缩;
    #       冰点(<cold)压到 cold 倍率; 脆弱态再乘 fragile_extra(下有 floor)。日常不无故削进攻。
    th = gc.get("thresholds", {"hot": 70, "cold": 30, "reduce_below": 55})
    om = gc.get("offense_multiplier", {"cold": 0.4, "fragile_extra": 0.6, "floor": 0.25})
    reduce_below = th.get("reduce_below", 55)
    if score >= reduce_below:
        base = 1.0
    elif score >= th["cold"]:
        base = om["cold"] + (1.0 - om["cold"]) * (score - th["cold"]) / (reduce_below - th["cold"])
    else:
        base = om["cold"]
    mult = base
    if fragile:
        mult = max(om["floor"], mult * om["fragile_extra"])

    # 海外参考标签(仅展示, 不参与决策)
    vix = fetch_vix()
    vix_tag = f"{vix:.1f}" if vix else "未知"
    warn = gc.get("vix_reference", {}).get("warn_above", 25)
    if vix and vix > warn:
        vix_tag += " ⚠️海外波动偏高"

    label = "hot" if score >= th["hot"] else ("cold" if score < th["cold"] else "warm")

    def _fmt_amt(x):
        return f"{x / 1e12:.2f}万亿" if x else "NA"

    detail = (f"宽度=涨{br[0]}/跌{br[1]}(平{br[2]}) " if br else "宽度=NA ") + \
             (f"量能={_fmt_amt(vol[0])}/{_fmt_amt(vol[1])} " if vol else "量能=NA ") + \
             (f"趋势偏离={dev:+.2f}% " if dev is not None else "趋势=NA ") + \
             (f"两融环比={fd[1]:+.2f}% " if fd else "两融=NA ")

    result = {
        "score": round(score, 1),
        "label": label,
        "fragile": fragile,
        "vix_tag": vix_tag,
        "offense_multiplier": round(mult, 2),
        "enabled": True,
        "shadow": shadow,
        "apply": (enabled and not shadow),
        "detail": detail.strip(),
        "_parts": {k: round(v, 3) for k, v in parts.items()},
    }
    _CACHE["ts"] = now
    _CACHE["data"] = result
    return result


def _self_test():
    """离线自检: 网络可用则打印真实温度; 不可用则演示打分逻辑(不依赖网络)。"""
    # 演示打分(不触发网络)
    print("=== 温度计打分逻辑自检(离线) ===")
    cases = [
        ("沸点(热)", _score_breadth(3500, 800, 200), _score_volume(2.0e12, 1.2e12), _score_trend(4.0), _score_funding(1.5)),
        ("常态(温)", _score_breadth(2200, 2000, 300), _score_volume(1.2e12, 1.2e12), _score_trend(0.5), _score_funding(0.2)),
        ("冰点(冷/脆弱)", _score_breadth(900, 3500, 100), _score_volume(0.6e12, 1.3e12), _score_trend(-4.5), _score_funding(-1.8)),
    ]
    for name, b, v, t, f in cases:
        s = (0.30 * b + 0.30 * v + 0.25 * t + 0.15 * f) * 100
        fragile = (v < 0.35) and ((b < 0.4) or (f < 0.4))
        if s >= 55:
            mult = 1.0
        elif s >= 30:
            mult = 0.4 + 0.6 * (s - 30) / 25.0
        else:
            mult = 0.4
        if fragile:
            mult = max(0.25, mult * 0.6)
        print(f"  {name}: 宽度{b:.2f} 量能{v:.2f} 趋势{t:.2f} 两融{f:.2f} -> "
              f"温度{s:.0f} 脆弱={fragile} 进攻刻度x{mult:.2f}")


if __name__ == "__main__":
    import os as _os
    if _os.environ.get("MOCK"):
        _self_test()
    else:
        try:
            cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                              "strategy_config.json"), encoding="utf-8"))
            print("=== 市场温度计实时抓取 ===")
            t = get_market_temperature(cfg, force_refresh=True)
            print(json.dumps(t, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"实时抓取失败({e}), 退回离线自检:")
            _self_test()
