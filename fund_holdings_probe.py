""" fund_holdings_probe.py - v6.9+ 公募基金真实持仓行业集中度探针(防御端·真实层)
================================================================================
与 concentration_probe.py 的「实时拥挤度」源互补, 本模块提供**真实季报持仓**层:

  * 实时层(concentration_probe 内): 用东方财富板块成交额/资金流/涨幅 HHI 合成,
    反映"当下资金抱团", 但只是市场症状的代理。
  * 真实层(本模块): 遍历一支代表性主动股基白名单, 用东方财富妙想(MX)接口拉取
    每只基金最新季报前十大重仓股, 再查每只重仓股的申万一级行业, 聚合出
    "主动基金整体对少数行业的真实抱团浓度", 正是用户原话的"白酒行情式结构性抱团"。

两源正交、互补:
  - 实时层 = 当下症状(快, 但只是代理)
  - 真实层 = 结构性风格(滞后一个季度, 但更贴近用户想要的"公募真实持仓集中度")

合成在 concentration_probe.get_fund_concentration 中: score = w_rt*实时 + w_h*真实。

设计约束(与 temperature_probe / concentration_probe 一致, 实盘优先, 不死机)
--------------------------------------------------------------------------------
  * 仅标准库(urllib/json), 无第三方依赖 -> 生产 bot 环境直接跑, 不需 requests/pandas。
  * 妙想接口仅在「缓存过期」时刷新, 且刷新在后台守护线程进行, 绝不阻塞下单主循环。
  * 任何失败(无 MX_APIKEY / 网络断 / 配额满 / 解析失败) -> 返回 None,
    concentration_probe 自动退回"仅实时层"(或原逻辑), 不干预仓位。
  * 股票->申万行业映射本地长期缓存(stock_industry_cache.json), 避免重复打妙想。
  * 聚合结果本地缓存(fund_holdings_cache.json), 默认 24h 刷新一次(季报级数据, 慢刷即可)。
  * 白名单约 35 只代表性主动股基(跨 消费/医药/科技成长/价值/金融地产/均衡 风格),
    近似全市场主动基金行业配置, 比"仅几只重点基金"覆盖更全。
================================================================================
"""
import os
import sys
import json
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_MX_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"
_REFRESHING = False  # 同进程内防并发刷新
_REFRESH_LOCK = threading.Lock()

REQUEST_GAP_SEC = 1.2     # 妙想接口最小调用间隔(防 112 限频)
_RATE_BACKOFF = 3.0       # 触发限频后的退避基数(秒)
_REQUEST_GAP = REQUEST_GAP_SEC
_last_call = [0.0]

CACHE_DIR = os.path.dirname(os.path.abspath(__file__))
HOLDINGS_CACHE = os.path.join(CACHE_DIR, "fund_holdings_cache.json")
INDUSTRY_CACHE = os.path.join(CACHE_DIR, "stock_industry_cache.json")

# 默认查询周期: 抓最新可用季报。东方财富妙想对"前十大重仓股"不加周期默认回最新。
DEFAULT_QUERY_PERIOD = "最新"

# 代表性主动股基白名单(~35只, 跨风格近似全市场主动基金行业配置)
# name 用于妙想自然语言匹配; code 仅供参考(部分含 HK/场外)。
FUND_WHITELIST = [
    {"code": "005827", "name": "易方达蓝筹精选"},
    {"code": "110022", "name": "易方达消费行业"},
    {"code": "110011", "name": "易方达优质精选"},
    {"code": "161005", "name": "富国天惠成长"},
    {"code": "519915", "name": "富国消费主题"},
    {"code": "260108", "name": "景顺长城新兴成长"},
    {"code": "260116", "name": "景顺长城核心竞争力"},
    {"code": "163406", "name": "兴全合润"},
    {"code": "163402", "name": "兴全趋势投资"},
    {"code": "163415", "name": "兴全商业模式"},
    {"code": "166002", "name": "中欧新蓝筹"},
    {"code": "003095", "name": "中欧医疗健康"},
    {"code": "001938", "name": "中欧时代先锋"},
    {"code": "166005", "name": "中欧价值发现"},
    {"code": "000083", "name": "汇添富消费行业"},
    {"code": "519069", "name": "汇添富价值精选"},
    {"code": "270002", "name": "广发稳健增长"},
    {"code": "005911", "name": "广发双擎升级"},
    {"code": "162703", "name": "广发小盘成长"},
    {"code": "000251", "name": "工银瑞信金融地产"},
    {"code": "001717", "name": "工银瑞信前沿医疗"},
    {"code": "000746", "name": "招商优质成长"},
    {"code": "000854", "name": "鹏华养老产业"},
    {"code": "206007", "name": "鹏华消费优选"},
    {"code": "002851", "name": "南方品质优选"},
    {"code": "040035", "name": "华安逆向策略"},
    {"code": "460005", "name": "华泰柏瑞价值增长"},
    {"code": "180012", "name": "银华富裕主题"},
    {"code": "180031", "name": "银华中小盘"},
    {"code": "160505", "name": "博时主题行业"},
    {"code": "660012", "name": "农银汇理消费主题"},
    {"code": "001102", "name": "前海开源国家比较优势"},
    {"code": "001751", "name": "嘉实新兴产业"},
    {"code": "002001", "name": "华夏大盘精选"},
    {"code": "000001", "name": "华夏成长"},
    {"code": "519606", "name": "国泰金鑫"},
]


# ---------------------------------------------------------------------------
# 妙想查询(标准库 urllib, 与 mx_data.py 同源但零依赖)
# ---------------------------------------------------------------------------
def _mx_query(tool_query, timeout=25):
    """POST 妙想自然语言查询, 返回原始 JSON dict; 任何异常返回 None。"""
    import urllib.request
    key = os.environ.get("MX_APIKEY")
    if not key:
        return None
    try:
        req = urllib.request.Request(
            _MX_URL,
            data=json.dumps({"toolQuery": tool_query}).encode("utf-8"),
            headers={"Content-Type": "application/json", "apikey": key},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _mx_query_retry(tool_query, n=4, base_gap=None):
    """带最小间隔 + 限频重试的妙想查询。返回原始 JSON dict 或 None。

    妙想免费接口有频率限制(code=112 请求频率过高)。本函数:
      * 每次调用前确保距上次调用 >= gap 秒(默认 REQUEST_GAP_SEC);
      * 命中限频/空数据 -> 退避重试;
      * 全部失败返回 None(调用方按"该基金/股票缺失"容忍处理)。
    """
    gap = base_gap if base_gap is not None else _REQUEST_GAP
    for attempt in range(n):
        wait = gap - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        j = _mx_query(tool_query)
        _last_call[0] = time.time()
        if j is None:
            time.sleep(gap)
            continue
        # 限频(code=112)或顶层异常 -> 退避重试
        if j.get("code") == 112 or (j.get("data") is None and j.get("status") not in (0,)):
            time.sleep(_RATE_BACKOFF * (attempt + 1))
            continue
        return j
    return None


def _dtos(j):
    """从妙想返回里取 dataTableDTOList(安全, 容忍 None)。"""
    if not isinstance(j, dict):
        return None
    try:
        return (j.get("data") or {}).get("data", {}).get("searchDataResultDTO", {}).get("dataTableDTOList")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 解析: 基金前十大重仓 -> [(股票名, 市值元), ...]
# ---------------------------------------------------------------------------
def _parse_fund_holdings(j):
    dtos = _dtos(j)
    if not dtos:
        return None
    for dto in dtos:
        if not isinstance(dto, dict):
            continue
        raw = dto.get("rawTable") or dto.get("table") or {}
        names = raw.get("headName") or (dto.get("table") or {}).get("headName")
        mvs = raw.get("HOLD_MARKET_CAP") or (dto.get("table") or {}).get("HOLD_MARKET_CAP")
        if not names or not mvs or len(names) != len(mvs):
            continue
        out = []
        for nm, mv in zip(names, mvs):
            nm = (nm or "").strip()
            if not nm:
                continue
            try:
                val = float(mv)
            except (ValueError, TypeError):
                val = _parse_amount(str(mv))
            if val and val > 0:
                out.append((nm, val))
        if out:
            return out
    return None


def _parse_amount(s):
    """把 '11.69亿'/'5.572亿'/'313.1万' 这类中文数量转成浮点元。"""
    s = (s or "").strip().replace(",", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        pass
    mult = 1.0
    if "亿" in s:
        mult = 1e8
    elif "万" in s:
        mult = 1e4
    num = "".join(ch for ch in s if (ch.isdigit() or ch == "."))
    try:
        return float(num) * mult
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# 解析: 股票 -> 申万一级行业(本地缓存)
# ---------------------------------------------------------------------------
def _load_industry_cache():
    try:
        return json.load(open(INDUSTRY_CACHE, encoding="utf-8"))
    except Exception:
        return {}


def _save_industry_cache(cache):
    try:
        json.dump(cache, open(INDUSTRY_CACHE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    except Exception:
        pass


def _parse_industry(j):
    dtos = _dtos(j)
    if not dtos:
        return None
    for dto in dtos:
        if not isinstance(dto, dict):
            continue
        t = dto.get("table") or {}
        for k, v in t.items():
            if k == "headName":
                continue
            if isinstance(v, list) and v:
                val = str(v[0]).strip()
                if val and val not in ("-", "None", "null"):
                    return val
    return None


# 妙想对个别港股/能源股会错分到"化工"等, 这里按股票名强制纠正到正确申万一级
_OIL_STOCKS = {"中国海洋石油", "中国石油", "中国石化", "中海油服",
               "中国海油", "中海油田服务", "中国石油股份"}


def _norm_industry(ind):
    """归一为申万一级: 妙想有时返回'一级-二级-三级'层级串, 取第一段。"""
    if not ind:
        return ind
    ind = ind.strip()
    if "-" in ind:
        ind = ind.split("-")[0].strip()
    return ind


def _resolve_industry(stock_name, cache, force=False):
    """查(或命中缓存)某股票申万一级行业; 失败返回 None。"""
    if not force and stock_name in cache:
        return cache[stock_name] or None
    j = _mx_query_retry(f"{stock_name} 所属申万一级行业")
    ind = _norm_industry(_parse_industry(j))
    if ind:
        if stock_name in _OIL_STOCKS:
            ind = "石油石化"
        cache[stock_name] = ind
    return ind


def _query_fund_holdings(fname, code, period):
    """韧性拉取基金前十大重仓: 依次尝试 代码/原名/(代码)/A后缀 多种问法。

    妙想对基金名匹配不稳定(有的要带 A 后缀, 有的用代码更准), 故多形态兜底。
    命中限频自动重试(见 _mx_query_retry)。全部失败返回 None。
    """
    forms = []
    if code:
        forms.append(f"{code} 前十大重仓股")
    forms.append(f"{fname} 前十大重仓股")
    if code:
        forms.append(f"{fname}({code}) 前十大重仓股")
    forms.append(f"{fname}A 前十大重仓股")
    if period and period != "最新":
        forms = [f"{q} {period}" for q in forms]
    for q in forms:
        j = _mx_query_retry(q)
        h = _parse_fund_holdings(j)
        if h:
            return h
    return None


# ---------------------------------------------------------------------------
# 聚合: 跨基金行业市值权重 -> 集中度指标 + 0~100 指数
# ---------------------------------------------------------------------------
def _aggregate(industry_weights):
    """industry_weights: {行业: 权重(各基金内归一后累加)} -> 集中度结果。"""
    total = sum(industry_weights.values()) or 1.0
    norm = {k: v / total for k, v in industry_weights.items()}
    hhi = sum(w * w for w in norm.values())
    maxw = max(norm.values()) if norm else 0.0
    top3 = sum(sorted(norm.values(), reverse=True)[:3])
    # HHI 评分: 31 个申万一级行业"完全均匀"= 1/31 ≈ 0.032 -> 0 分;
    # 高度抱团(单行业 ~0.40 主导)HHI ≈ 0.18 -> 满分。中间线性。
    hhi_score = max(0.0, min(1.0, (hhi - 0.032) / (0.18 - 0.032)))
    # 最大行业权重评分(单行业占 ~12% 正常, ~40% 极端)
    max_score = max(0.0, min(1.0, (maxw - 0.12) / (0.40 - 0.12)))
    # 综合: HHI 为主, 最大行业权重作辅助(取两者较高但封顶)
    score = max(hhi_score, max_score * 0.85) * 100
    top = sorted(norm.items(), key=lambda x: -x[1])[:6]
    return {
        "hhi": round(hhi, 4),
        "max_weight": round(maxw, 4),
        "top3_share": round(top3, 4),
        "score": round(score, 1),
        "top_industries": [(k, round(v * 100, 1)) for k, v in top],
    }


# ---------------------------------------------------------------------------
# 单次完整刷新(阻塞, 供手动/后台线程调用)
# ---------------------------------------------------------------------------
def refresh_holdings_cache(cfg, verbose=False, period=None):
    """遍历白名单, 拉真实持仓+行业, 聚合写缓存。返回聚合结果 dict 或 None。

    设计: 股票->行业映射用本地缓存(长期有效); 聚合结果落盘缓存。
    任一只基金/股票失败均跳过, 不影响整体; 全失败返回 None。
    """
    gc = (cfg.get("concentration_probe", {}) or {}).get("holdings_layer", {}) or {}
    global _REQUEST_GAP
    period = period or gc.get("query_period", DEFAULT_QUERY_PERIOD)
    _REQUEST_GAP = float(gc.get("request_interval_sec", REQUEST_GAP_SEC))
    whitelist = gc.get("fund_whitelist", FUND_WHITELIST)
    cache = _load_industry_cache()
    industry_weights = {}
    fund_count = 0
    errors = []
    t0 = time.time()
    for i, f in enumerate(whitelist):
        fname = f.get("name")
        if not fname:
            continue
        holdings = _query_fund_holdings(fname, f.get("code"), period)
        if not holdings:
            errors.append(fname)
            if verbose:
                print(f"  [持仓] {fname}: 无数据, 跳过")
            continue
        # 基金内归一
        ftotal = sum(mv for _, mv in holdings) or 1.0
        for stock, mv in holdings:
            ind = _resolve_industry(stock, cache)
            if not ind:
                # 解析失败也容忍: 不计入该股市值(避免噪声行业)
                continue
            industry_weights[ind] = industry_weights.get(ind, 0.0) + (mv / ftotal)
        fund_count += 1
        if verbose:
            print(f"  [持仓] {fname}: {len(holdings)} 只重仓已聚合 (已处理 {fund_count}/{len(whitelist)})")
    _save_industry_cache(cache)
    if fund_count == 0:
        if verbose:
            print("  [持仓] 全部基金拉取失败, 不更新缓存")
        return None
    agg = _aggregate(industry_weights)
    agg["fund_count"] = fund_count
    agg["errors"] = errors
    agg["available"] = True
    agg["ts"] = time.time()
    try:
        json.dump(agg, open(HOLDINGS_CACHE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    except Exception:
        pass
    if verbose:
        top = ", ".join(f"{k}({v}%)" for k, v in agg["top_industries"][:4])
        print(f"  [持仓] 聚合完成: {fund_count} 只基金, HHI={agg['hhi']} "
              f"最大行业={agg['max_weight']*100:.1f}% 指数={agg['score']}/100 | 头部: {top}")
    return agg


def _maybe_refresh_async(cfg, cache_path):
    global _REFRESHING
    if _REFRESHING:
        return
    with _REFRESH_LOCK:
        if _REFRESHING:
            return
        _REFRESHING = True

    def _run():
        try:
            refresh_holdings_cache(cfg, verbose=False)
        except Exception:
            pass
        finally:
            global _REFRESHING
            _REFRESHING = False

    t = threading.Thread(target=_run, name="fund-holdings-refresh", daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# 主入口(供 concentration_probe 调用)
# ---------------------------------------------------------------------------
def compute_holdings_concentration(cfg, force_refresh=False, _result=None):
    """返回聚合结果 dict(含 available/score/hhi/top_industries/...) 或 None。

    - _result 注入: 测试/确定性场景, 跳过一切网络与缓存。
    - 缓存命中且未过期: 直接返回(不触发网络)。
    - 缓存存在但过期: 返回缓存结果(可用) + 后台异步刷新。
    - 无缓存且非强制: 触发后台异步刷新, 本次返回 None(退回实时层)。
    - force_refresh=True: 阻塞刷新并返回。
    """
    gc = (cfg.get("concentration_probe", {}) or {}).get("holdings_layer", {}) or {}
    if _result is not None:  # 注入: 测试/确定性场景, 跳过一切网络与缓存
        return _result
    if not gc.get("enabled", True):
        return None
    if not os.environ.get("MX_APIKEY"):  # 无密钥直接退出, 不触发刷新线程
        return None
    refresh_hours = float(gc.get("refresh_hours", 24))
    try:
        data = json.load(open(HOLDINGS_CACHE, encoding="utf-8"))
    except Exception:
        data = None
    if data and isinstance(data, dict) and data.get("available"):
        age = time.time() - data.get("ts", 0)
        if age < refresh_hours * 3600 and not force_refresh:
            return data
        # 过期但有数据: 仍可用, 触发后台刷新
        _maybe_refresh_async(cfg, HOLDINGS_CACHE)
        return data
    # 无缓存
    if force_refresh:
        return refresh_holdings_cache(cfg, verbose=False)
    _maybe_refresh_async(cfg, HOLDINGS_CACHE)
    return None


# ---------------------------------------------------------------------------
# 离线自检
# ---------------------------------------------------------------------------
def _self_test():
    print("=== 公募基金真实持仓行业集中度(聚合逻辑)离线自检 ===")
    # 合成: 35 只基金, 每只 top10, 一半重仓在 电子/半导体(代表 AI 抱团)
    ind_w = {}
    for _ in range(35):
        # 模拟一只基金: 5 只科技 + 5 只分散
        for ind, w in [("电子", 0.18), ("半导体", 0.16), ("计算机", 0.10),
                       ("食品饮料", 0.08), ("医药", 0.07), ("电力", 0.06),
                       ("银行", 0.05), ("汽车", 0.05), ("有色", 0.04), ("军工", 0.04)]:
            ind_w[ind] = ind_w.get(ind, 0.0) + w
    agg = _aggregate(ind_w)
    print(f"  合成(科技抱团): HHI={agg['hhi']} 最大={agg['max_weight']*100:.1f}% "
          f"top3={agg['top3_share']*100:.1f}% 指数={agg['score']}/100")
    # 合成: 完全均匀(31 行业等权)
    even = {f"行业{i}": 1.0 for i in range(31)}
    agg2 = _aggregate(even)
    print(f"  合成(完全均匀): HHI={agg2['hhi']:.4f} 最大={agg2['max_weight']*100:.1f}% "
          f"指数={agg2['score']}/100")
    print("  (注: 真实层需妙想接口, 运行 refresh_holdings_cache(cfg, verbose=True) 填充缓存)")


if __name__ == "__main__":
    if os.environ.get("MOCK"):
        _self_test()
    else:
        try:
            cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                              "strategy_config.json"), encoding="utf-8"))
            print("=== 公募基金真实持仓层 实时刷新 ===")
            r = refresh_holdings_cache(cfg, verbose=True)
            print(json.dumps(r, ensure_ascii=False, indent=2) if r else "无数据")
        except Exception as e:
            print(f"刷新失败({e}), 退回离线自检:")
            _self_test()
