"""
backtest_engine.py - A 股策略周频回测引擎 (模块化, 可叠加优化杠杆)

设计约束(重要, 诚实声明):
  * 数据: 后复权周线 (腾讯 web.ifzq.gtimg.cn 源, 字段正确: open/close/high/low).
  * 交易成本 (v6.16+): 默认 costs=True, 含佣金(万2.5双边)+印花税(0.05%卖出)+滑点(0.1%双边).
    costs=False 可关闭以对比毛收益.
  * 防御端: 固定 DEF16 等权 (live 的 selector 三维评分需历史 PE/换手/分位, 无数据不可回测, 故防御锚定固定篮->忠实于 18 倍代理设定).
  * 进攻端: 可切换 固定 OFF4 / 动量动态选股(价格可回测) + 木头姐时变相位倾斜.
  * 网格: 以"现金弹药 sleeve"做周频均值回复代理(用周 OHLC 区间近似日网格), 低价超配进攻/高价回撤现金, 收割波动.
  * 温度计(temperature_probe)依赖实时宽度/量能/两融, 历史不可得 -> 回测中不启用(offense_multiplier=1.0), 标注为 live-only 杠杆.

基线 = 固定 DEF16 + 固定 OFF4 + regime 配置 + 死叉全防御 + (进攻无网格/无动量) -> 应逼近 18 倍(配置层代理).
优化 = 在基线上逐项叠加: 网格 / 动量动态进攻(含相位倾斜) / 波动率目标.
"""
import os
import sys
import csv
import json
import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

# ---- 篮子 (记忆中的 DEF16 + OFF4, 与 18 倍代理一致) ----
DEF16 = ["600900", "600036", "601088", "600377", "600519", "600887",
         "601318", "601398", "601166", "000333", "000651", "600276",
         "002415", "601668", "601899", "600028"]
OFF4 = ["300750", "300308", "002371", "002821"]

# 指数(周线死叉 + 三档识别) 与 可转债(弱势进攻替代)
HS300 = "000300"
DC_INDICES = ["000300", "000905", "000001", "399006", "000016", "000852"]
CONVERTIBLES = ["113050", "113052"]

# 核心仓时间扩展: OFF4 中上市较晚的票, 用更早上市的同主题票在其上市前替代,
# 以拉长回测窗口(上市后原样使用本尊, 故 2018+ 尾巴与未扩展时一致)。
# 宁德->比亚迪(新能源整车, 2011), 中际旭创->浪潮信息(AI服务器底座, 2000),
# 凯莱英->恒瑞医药(创新药, 2000)。均属同一科技/成长主题的早期化身。
CORE_SUB = {"300750": "002594", "300308": "000977", "002821": "600276"}

# weekly_theme 进攻黑名单(这些行业即使涨也不当进攻主线)
OFFENSE_BLACKLIST = {"石油", "银行", "电力", "家电", "食品", "白酒", "建筑", "建材",
                     "保险", "化工", "石化", "公用事业", "电信", "铁路", "公路", "港口"}

# 三档仓位模板 (防御/进攻/现金)
REGIME_ALLOC = {
    "weak":    {"def": 60, "off": 24, "cash": 16},
    "balance": {"def": 45, "off": 45, "cash": 10},
    "bull":    {"def": 35, "off": 60, "cash": 5},
}

# ---- 木头姐时变渗透率相位 (从 tech_adoption.py 摘抄, 离线) ----
PHASE_HISTORY = {
    "白酒": [(2016, 2020, "accelerating"), (2021, 2026, "mature")],
    "消费": [(2016, 2020, "accelerating"), (2021, 2026, "mature")],
    "新能源": [(2016, 2018, "early"), (2019, 2021, "accelerating"), (2022, 2026, "saturating")],
    "汽车": [(2019, 2021, "accelerating"), (2022, 2026, "saturating")],
    "锂矿": [(2019, 2021, "accelerating"), (2022, 2026, "mature")],
    "半导体设备": [(2019, 2021, "accelerating"), (2022, 2022, "mature"), (2023, 2026, "accelerating")],
    "半导体": [(2019, 2021, "accelerating"), (2023, 2026, "accelerating")],
    "AI": [(2018, 2022, "early"), (2023, 2026, "accelerating")],
    "计算机": [(2018, 2022, "early"), (2023, 2026, "accelerating")],
    "通信": [(2023, 2026, "accelerating")],
    "医药": [(2017, 2021, "accelerating"), (2022, 2026, "mature")],
    "光伏": [(2020, 2022, "accelerating"), (2023, 2026, "mature")],
    "机器人": [(2023, 2026, "early")],
    "电网": [(2021, 2026, "accelerating")],
    "港股科技": [(2023, 2026, "accelerating")],
    "科技宽基": [(2023, 2026, "accelerating")],
}
PHASE_MULT = {"accelerating": 1.35, "early": 1.15, "saturating": 0.65, "mature": 0.8, "unknown": 1.0}

# ---- 脏数据 / 次新股防火墙参数 (动量选股专用) ----
# MIN_VALID_PRICE : 低于此价视为错价(未复权残留/占位值)。
MIN_VALID_PRICE = 0.5
# MAX_WEEKLY_JUMP / MIN_WEEKLY_DROP : 常规期单周涨跌幅上限, 用于兜底拦截未复权或错价跳变。
#   实测本面板内「真实」单周大涨全部 <= +77.5%
#   (2024-09-30 东方财富 +77.5% / 同花顺 +67.4%, 2016-10 中际旭创重组复牌 +60.6%),
#   故 +80% 只拦错价、不误伤真实利好行情; 原值 +160% 过松, 连 +93% 的 IPO 伪迹都漏过。
MAX_WEEKLY_JUMP = 0.80
MIN_WEEKLY_DROP = -0.75
# IPO_SEASON_WEEKS : 次新股冷却期(周)。A 股新股上市后连续一字板 + 首发限售,
#   前一个季度的价格序列是统计假象而非可交易动量。实测 9 只票的 15 处
#   +50%~+93% 伪迹全部落在上市后第 1~4 根周线内; 而最早的一处「真实」单周大涨
#   发生在上市后第 199 根周线 —— 用一个季度(13周)做冷却期, 安全边际充足。
#   要求整段打分窗口都在冷却期之后, 即 i - first_listed >= max_lb + IPO_SEASON_WEEKS。
IPO_SEASON_WEEKS = 13

# first_listed_index 的缓存: momentum_select 对每周每只票都会调用一次(约 10 万次),
# 逐次线性扫描代价太高。key=id(列表), value=(列表引用, 首个有效索引);
# 保留列表引用有两个作用: (1) 防止列表被回收后 id 复用导致缓存串味;
# (2) 使缓存命中判定可以用 `is` 精确校验。
# 容量上限: list 不支持弱引用, 无法做自动淘汰, 故用「超限即整体清空」兜底。
# 单张面板约 125 列, 512 的上限保证同一次回测内绝不触发清空(全程命中);
# 而长驻进程/批量扫参反复 load_panel() 时, 内存有硬上界不会无限膨胀。
_FIRST_LISTED_CACHE = {}
_FIRST_LISTED_CACHE_MAX = 512

# ---- 幸存者偏差声明 (诚实口径) ----
# 候选池 (candidate_pool) 是当前"赢家"的静态名单, 回测建在历史幸存者上,
# 不含已退市/暴跌至无关紧要的标的 -> 回测倍数系统性偏高。
# 引擎的 first_listed_index 防止使用 IPO 前数据(技术层面已处理),
# 但无法消除"池子本身就是幸存者"的结构性偏差。
# 真正修复需历史指数成分股 point-in-time 宇宙, 目前不可得。
# 敏感性检查: 用 survivorship_check.py 移除 TopN 涨幅股后重算, 评估偏差量级。
SURVIVORSHIP_BIAS_NOTE = (
    "候选池为静态幸存者样本(当前赢家), 回测倍数含向上偏差。"
    "建议结合 survivorship_check.py 做敏感性分析。"
)


def first_listed_index(vals):
    """返回序列中首个有效价格(非 None 且 > 0)的索引; 整列无效返回 None。

    对前向填充后的面板而言, 该索引即该代码的「上市/数据起点」。
    """
    key = id(vals)
    hit = _FIRST_LISTED_CACHE.get(key)
    if hit is not None and hit[0] is vals:
        return hit[1]
    fv = None
    for k, v in enumerate(vals):
        if v is not None and v > 0:
            fv = k
            break
    if len(_FIRST_LISTED_CACHE) >= _FIRST_LISTED_CACHE_MAX:
        _FIRST_LISTED_CACHE.clear()
    _FIRST_LISTED_CACHE[key] = (vals, fv)
    return fv


def phase_for(industry, year):
    hist = PHASE_HISTORY.get(industry)
    if hist:
        for (s, e, ph) in hist:
            if s <= year <= e:
                return ph
    return "unknown"


def tech_mult(industry, year):
    return PHASE_MULT.get(phase_for(industry, year), 1.0)


# ---- 数据驱动行业相位 (tech_mode="data", 用于消除 PHASE_HISTORY 的前视偏差) ----
# ★ 手写 PHASE_HISTORY 的结构性缺陷: 它是 2026 年回看历史标注出来的
#   (例 "AI": 2023-2026 accelerating, "新能源": 2022-2026 saturating)。
#   回测跑到 2019 年那一周时, 引擎其实已经"知道"2023 年 AI 会加速 ——
#   这是典型的前视偏差, 且无法通过参数调整消除, 只能换成时点数据推断。
#   本节的数据驱动版在任意第 i 周只读 [0, i] 区间的行业指数, 不引用未来。
PHASE_LONG_LB = 52   # 长期动量窗口(周)=1年, 判定该行业"是否处于上行"
PHASE_SHORT_LB = 13  # 短期动量窗口(周)=1季, 年化后与长期比较得到加速度


def build_industry_index(dates, series, pool_meta):
    """按行业构建等权指数, point-in-time 安全。返回 {industry: [float]}。

    用「逐周成分股收益等权平均, 再链式累乘」而非价格直接平均:
    成分股在上市/停牌时进出样本, 价格平均会产生虚假跳变, 收益等权则不会。
    单周收益同样过 MIN_WEEKLY_DROP/MAX_WEEKLY_JUMP 闸, 防止未复权错价污染指数。
    """
    by_ind = {}
    for code, meta in pool_meta.items():
        if code in series:
            by_ind.setdefault(meta.get("industry", "unknown"), []).append(code)
    n = len(dates)
    out = {}
    for ind, codes in by_ind.items():
        idx = [1.0] * n
        for i in range(1, n):
            rs = []
            for c in codes:
                v = series[c]
                a, b = v[i - 1], v[i]
                if a and b and a > 0:
                    rr = b / a - 1.0
                    if MIN_WEEKLY_DROP <= rr <= MAX_WEEKLY_JUMP:
                        rs.append(rr)
            idx[i] = idx[i - 1] * (1.0 + (sum(rs) / len(rs) if rs else 0.0))
        out[ind] = idx
    return out


def phase_from_index(idx_vals, i, long_lb=PHASE_LONG_LB, short_lb=PHASE_SHORT_LB):
    """由行业指数在第 i 周判定渗透率相位(S 曲线四象限), 只用 [0, i] 的数据。

      accelerating : 长期上行 且 短期年化 > 长期   (曲线陡峭段, 渗透加速)
      mature       : 长期上行 但 短期年化 <= 长期  (仍在涨, 斜率已转平)
      early        : 长期未上行 但 短期转正        (刚起步 / 触底回升)
      saturating   : 长短期双负                    (渗透饱和 / 退潮)
    数据不足 -> "unknown" -> 乘子 1.0 (中性, 等价于不加权)。
    """
    if idx_vals is None or i - long_lb < 0 or i - short_lb < 0:
        return "unknown"
    a, b, c = idx_vals[i - long_lb], idx_vals[i - short_lb], idx_vals[i]
    if not a or not b or a <= 0 or b <= 0:
        return "unknown"
    mom_l = c / a - 1.0
    mom_s = c / b - 1.0
    ann_s = (1.0 + mom_s) ** (52.0 / short_lb) - 1.0 if mom_s > -1.0 else -1.0
    if mom_l > 0:
        return "accelerating" if ann_s > mom_l else "mature"
    return "early" if mom_s > 0 else "saturating"


def build_industry_phases(dates, series, pool_meta):
    """预计算 {industry: [每周相位]}, 让选股环节 O(1) 查表而非逐票重算。"""
    idxs = build_industry_index(dates, series, pool_meta)
    return {ind: [phase_from_index(v, i) for i in range(len(dates))]
            for ind, v in idxs.items()}


# ------------------------- 数据加载 -------------------------
def load_panel(panel_path=None):
    path = panel_path or os.path.join(DATA, "ashare_panel_close.csv")
    rows = []
    with open(path, encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r)
        codes = header[1:]
        for line in r:
            rows.append(line)
    dates = [row[0] for row in rows]
    # code -> list of float/None
    series = {}
    for j, c in enumerate(codes):
        col = []
        for row in rows:
            v = row[j + 1].strip()
            col.append(float(v) if v not in ("", "None") else None)
        # 前向填充(上市后缺失补最后有效值; 上市前仍为 None)
        last = None
        for k in range(len(col)):
            if col[k] is not None:
                last = col[k]
            elif last is not None:
                col[k] = last
        series[c] = col
    return dates, codes, series


def load_volume_panel(close_panel_path):
    """加载与 close 面板同索引的成交量宽表, 返回 {code: [float|None]}。

    路径推导: <...>_close_<tag>.csv -> <...>_volume_<tag>.csv。
    与 load_panel 的关键差异: **不做前向填充**。
    成交量前向填充会凭空捏造换手, 停牌周的真实成交量就是 0/缺失,
    填充会让缩量停牌票被误判为"放量"。缺失一律返回 None, 由调用方决定如何处理。

    找不到文件时返回 None (调用方据此自动关闭量能过滤器, 不报错)。
    """
    if not close_panel_path:
        return None
    vp = close_panel_path.replace("_close_", "_volume_")
    if vp == close_panel_path or not os.path.exists(vp):
        return None
    vols = {}
    with open(vp, encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r)
        vcodes = header[1:]
        cols = [[] for _ in vcodes]
        for line in r:
            for j in range(len(vcodes)):
                v = line[j + 1].strip() if j + 1 < len(line) else ""
                try:
                    fv = float(v)
                except ValueError:
                    fv = None
                cols[j].append(fv if (fv is not None and fv > 0) else None)
    for j, c in enumerate(vcodes):
        vols[c] = cols[j]
    return vols


def load_macro(path=None):
    """加载 macro_monthly.csv, 返回按 available_date 升序的行列表。

    ★ 每行的 available_date 是"该月数据最早可被使用的日期"(已含发布滞后),
      引擎只按 available_date 取数, 因此不存在前视偏差。
    文件缺失返回 None, 调用方据此静默关闭宏观叠加层。
    """
    p = path or os.path.join(BASE, "data", "macro_monthly.csv")
    if not os.path.exists(p):
        return None
    rows = []
    with open(p, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            def _f(k):
                v = (r.get(k) or "").strip()
                try:
                    return float(v)
                except ValueError:
                    return None
            rows.append({
                "month": r.get("month", ""),
                "avail": r.get("available_date", ""),
                "pmi": _f("pmi"), "m2_yoy": _f("m2_yoy"), "shrz_yoy": _f("shrz_yoy"),
            })
    rows = [r for r in rows if r["avail"]]
    rows.sort(key=lambda x: x["avail"])
    return rows or None


def load_valuation(path=None):
    """加载 valuation_daily.csv, 返回按日期升序的 [(date, pe, pb)]。

    文件缺失返回 None, 调用方据此静默关闭估值层。
    """
    p = path or os.path.join(BASE, "data", "valuation_daily.csv")
    if not os.path.exists(p):
        return None
    rows = []
    with open(p, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = (r.get("date") or "").strip()
            if not d:
                continue

            def _f(k):
                v = (r.get(k) or "").strip()
                try:
                    x = float(v)
                    return x if x > 0 else None
                except ValueError:
                    return None
            rows.append((d, _f("pe_ttm_median"), _f("pb_median")))
    rows.sort(key=lambda x: x[0])
    return rows or None


def build_valuation_pct(val_rows, min_hist=250):
    """预计算每个交易日的 PE/PB **扩展窗口分位**, 返回 [(date, pe_pct, pb_pct)]。

    ★ 扩展窗口 = 第 t 日的分位只统计 [0, t] 区间的历史观测, 绝不含未来。
      这是与 akshare 自带 quantile 列的关键区别 —— 后者用整段历史(含未来)计算,
      直接使用会让早年的回测"知道"自己处在全历史的第几分位。
    min_hist: 历史样本不足该数量时分位置 None(视为中性), 默认 250≈1 个交易年。
    """
    import bisect
    if not val_rows:
        return None
    pes, pbs, out = [], [], []
    for d, pe, pb in val_rows:
        pe_p = pb_p = None
        if pe is not None:
            bisect.insort(pes, pe)
            if len(pes) >= min_hist:
                pe_p = bisect.bisect_left(pes, pe) / (len(pes) - 1)
        if pb is not None:
            bisect.insort(pbs, pb)
            if len(pbs) >= min_hist:
                pb_p = bisect.bisect_left(pbs, pb) / (len(pbs) - 1)
        out.append((d, pe_p, pb_p))
    return out


def valuation_score_at(pct_rows, date_str, lag_days=7):
    """返回 date_str 当时可用的市场估值分, 范围 [-1, +1]。便宜为正, 贵为负。

    score = 1 - 2 × mean(pe_pct, pb_pct)
      全历史最低分位 -> +1 (极便宜, 倾向加进攻)
      全历史最高分位 -> -1 (极贵,   倾向减进攻)
    lag_days: 数据可用滞后(默认 7 天)。市场估值虽当日盘后即可得, 仍统一取
      「一周前」的读数, 确保决策时点该数据必然已公开, 不存在同期前视。
    无可用数据 -> 0.0 (中性, 等价于关闭)。
    """
    if not pct_rows or not date_str:
        return 0.0
    try:
        cutoff = (datetime.date.fromisoformat(date_str[:10])
                  - datetime.timedelta(days=lag_days)).isoformat()
    except ValueError:
        return 0.0
    lo, hi, idx = 0, len(pct_rows) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if pct_rows[mid][0] <= cutoff:
            idx = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if idx < 0:
        return 0.0
    parts = [p for p in (pct_rows[idx][1], pct_rows[idx][2]) if p is not None]
    if not parts:
        return 0.0
    return max(-1.0, min(1.0, 1.0 - 2.0 * (sum(parts) / len(parts))))


def macro_score_at(macro_rows, date_str, hist_n=24):
    """计算 date_str 当日可用的宏观景气分, 范围约 [-1, +1]。

    三个分项 (缺失项自动跳过, 按有效项数平均):
      pmi_s  : (PMI - 50) / 2, clip[-1,1]。荣枯线为锚, 52 记满分, 48 记满负。
      m2_s   : M2 同比相对过去 hist_n 月均值的偏离 / 2pp, clip[-1,1] (信用松紧的方向)。
      shrz_s : 社融增量同比 / 20%, clip[-1,1] (实体融资需求)。

    只取 available_date <= date_str 的最新一行, 历史均值也只用该行及之前的数据,
    因此本函数在任何时点都不会用到未来信息。
    无可用数据 -> 返回 0.0 (中性, 等价于关闭叠加)。
    """
    if not macro_rows or not date_str:
        return 0.0
    # 二分找最后一个 avail <= date_str
    lo, hi = 0, len(macro_rows) - 1
    idx = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if macro_rows[mid]["avail"] <= date_str:
            idx = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if idx < 0:
        return 0.0
    cur = macro_rows[idx]

    def _clip(x):
        return max(-1.0, min(1.0, x))

    parts = []
    if cur["pmi"] is not None:
        parts.append(_clip((cur["pmi"] - 50.0) / 2.0))
    if cur["m2_yoy"] is not None:
        hist = [macro_rows[k]["m2_yoy"] for k in range(max(0, idx - hist_n + 1), idx + 1)
                if macro_rows[k]["m2_yoy"] is not None]
        if len(hist) >= 6:
            parts.append(_clip((cur["m2_yoy"] - sum(hist) / len(hist)) / 2.0))
    if cur["shrz_yoy"] is not None:
        parts.append(_clip(cur["shrz_yoy"] / 20.0))
    if not parts:
        return 0.0
    return sum(parts) / len(parts)


def volume_confirmed(vol_series, code, i, short_n=4, long_n=26, ratio=1.0):
    """量能确认: 近 short_n 周均量 >= ratio × 近 long_n 周均量。

    意图: 过滤"缩量假突破"。价格创新高但成交量萎缩, 说明没有资金真正接力,
    这类突破的失败率显著高于放量突破。
    数据不足 / 缺列 -> 返回 True (不因数据缺失而误杀候选)。
    """
    if not vol_series:
        return True
    v = vol_series.get(code)
    if not v or i < long_n:
        return True
    s = [x for x in v[i - short_n + 1:i + 1] if x]
    l = [x for x in v[i - long_n + 1:i + 1] if x]
    if len(s) < max(2, short_n // 2) or len(l) < long_n // 2:
        return True
    return (sum(s) / len(s)) >= ratio * (sum(l) / len(l))


def extract(dates, series, codes_needed):
    """返回 {code: aligned list}, 并给出共同起始索引(所有 code 首个非 None 的最大值)."""
    aligned = {c: series[c] for c in codes_needed if c in series}
    missing = [c for c in codes_needed if c not in series]
    if missing:
        print(f"  [warn] 缺失数据: {missing}")
    start = 0
    for c, lst in aligned.items():
        first = 0
        while first < len(lst) and lst[first] is None:
            first += 1
        start = max(start, first)
    return aligned, start


# ------------------------- 信号 -------------------------
def ma(vals, i, n):
    if i - n + 1 < 0:
        return None
    seg = vals[i - n + 1:i + 1]
    if any(v is None for v in seg):
        return None
    return sum(seg) / n


def regime_at(hs, i, band=0.03, n=20):
    m = ma(hs, i, n)
    if m is None or hs[i] is None:
        return "balance"
    dev = (hs[i] - m) / m
    if hs[i] < m * (1 - band):
        return "weak"
    if hs[i] > m * (1 + band):
        return "bull"
    return "balance"


def death_cross_at(series, i, ma_s=5, ma_l=20, threshold=3):
    bear = 0
    avail = 0
    for idx in DC_INDICES:
        vals = series.get(idx)
        if not vals or i < ma_l:
            continue
        m_s = ma(vals, i, ma_s)
        m_l = ma(vals, i, ma_l)
        if m_s is None or m_l is None or vals[i] is None:
            continue
        avail += 1
        ml_prev = ma(vals, i - 1, ma_l)
        if ml_prev is None:
            continue
        if vals[i] < m_l and m_s < m_l and m_l < ml_prev:
            bear += 1
    if avail == 0:
        return False
    return bear >= threshold


def _realized_vol(vals, i, n):
    """近 n 周已实现周度波动率 (stdev of weekly returns)."""
    if i - n + 1 < 0 or vals[i] is None:
        return None
    rets = []
    for k in range(max(1, i - n + 1), i + 1):
        a, b = vals[k - 1], vals[k]
        if a and b:
            rets.append(b / a - 1)
    if len(rets) < 3:
        return None
    mu = sum(rets) / len(rets)
    sd = (sum((x - mu) ** 2 for x in rets) / len(rets)) ** 0.5
    return sd


def momentum_select(dates, series, pool_meta, i, lookback, use_tech=True,
                    score_mode="plain", trend_filter=False, industry_diversify=False,
                    rel_strength=False, hs_vals=None,
                    volume_confirm=False, vol_series=None, volume_ratio=1.0,
                    tech_mode="static", ind_phases=None, tech_strength=1.0):
    """从候选池选 Top2。score_mode 决定打分方式:
      plain    : 动量 * 相位乘子 (原版)
      blend    : 多周期融合(13w*0.35 + 26w*0.40 + 52w*0.25) * 相位, 平滑信号减少 whipsaw
      risk_adj : 风险调整动量 = 动量*相位 / 已实现波动 (Sharpe 式, 偏平滑趋势)
      sortino  : 动量*相位 / 下行波动 (仅惩罚回撤, 更激进但控回撤)
    可选过滤器 (全部默认关闭, 失败退回原逻辑):
      trend_filter      : 要求 MA5 > MA20 (上升通道, 拒绝死猫跳)
      industry_diversify: Top2 来自不同行业 (避免同行业集中)
      rel_strength      : 个股动量 > HS300 同期动量 (真 alpha 非 beta)
      volume_confirm    : 近4周均量 >= volume_ratio × 近26周均量 (放量突破,
                          拒绝缩量假突破)。需 vol_series, 缺数据自动放行。
    要求主 lookback 动量>0。"""
    year = int(dates[i][:4])
    if score_mode == "blend":
        lbs = [(13, 0.35), (26, 0.40), (52, 0.25)]
    else:
        lbs = [(lookback, 1.0)]
    cands = []
    for code, meta in pool_meta.items():
        if code not in series:
            continue
        vals = series[code]
        if vals[i] is None:
            continue
        if i - lookback < 0 or vals[i - lookback] in (None, 0):
            continue
        # ---- 脏数据 / 次新股防火墙 (三道闸, 任一命中则本周不选该票) ----
        # (1) 价格下限: 未复权残留/占位值通常表现为极小价格
        if vals[i] < MIN_VALID_PRICE or vals[i - lookback] < MIN_VALID_PRICE:
            continue
        max_lb = max(lb for lb, _ in lbs)
        # (2) 次新股冷却期(主闸, 精准拦 IPO 伪迹):
        #     整段打分窗口 [i-max_lb, i] 必须完全落在上市冷却期之后, 否则该票的
        #     动量由新股一字板跳涨堆出来(实测 +50%~+93%), 是统计假象而非真动量。
        #     只按「距上市周数」判定, 不看涨幅, 因此不会误伤中途的真实大涨/重组复牌。
        first_listed = first_listed_index(vals)
        if first_listed is None or i - first_listed < max_lb + IPO_SEASON_WEEKS:
            continue
        # (3) 异常跳变兜底: 打分窗口内出现未复权/错价级别的单周涨跌
        bad_jump = False
        for k in range(max(1, i - max_lb + 1), i + 1):
            a, b = vals[k - 1], vals[k]
            if a and b and a > 0:
                rr = b / a - 1
                if rr > MAX_WEEKLY_JUMP or rr < MIN_WEEKLY_DROP:
                    bad_jump = True
                    break
        if bad_jump:
            continue
        mom = vals[i] / vals[i - lookback] - 1
        if mom <= 0:
            continue
        ind = meta.get("industry", "unknown")
        if not use_tech:
            mult = 1.0
        else:
            if tech_mode == "data":
                # 时点推断相位: 只看截至本周的行业指数, 无前视
                seq = ind_phases.get(ind) if ind_phases else None
                mult = PHASE_MULT.get(seq[i] if seq else "unknown", 1.0)
            else:
                # 手写相位表: 含前视偏差, 保留仅为与历史结果对照
                mult = tech_mult(ind, year)
            # 强度缩放: strength=0 等价于完全关闭, 1.0 为原始乘子
            if tech_strength != 1.0:
                mult = 1.0 + (mult - 1.0) * tech_strength
        if score_mode == "plain":
            score = mom * mult
        elif score_mode == "blend":
            s = 0.0
            ok = True
            for lb, w in lbs:
                if i - lb < 0 or vals[i - lb] in (None, 0):
                    ok = False
                    break
                m = vals[i] / vals[i - lb] - 1
                if m <= 0:
                    ok = False
                    break
                s += w * m
            if not ok:
                continue
            score = s * mult
        elif score_mode in ("risk_adj", "sortino"):
            vol = _realized_vol(vals, i, lookback)
            if vol is None or vol <= 0:
                continue
            if score_mode == "risk_adj":
                score = mom * mult / vol
            else:
                rets = []
                for k in range(max(1, i - lookback + 1), i + 1):
                    a, b = vals[k - 1], vals[k]
                    if a and b:
                        rets.append(b / a - 1)
                down = [r for r in rets if r < 0]
                dvol = ((sum(r * r for r in down) / len(rets)) ** 0.5) if down else 1e-6
                score = mom * mult / (dvol + 1e-6)
        else:
            score = mom * mult
        cands.append((code, score, mom, ind))
    cands.sort(key=lambda x: x[1], reverse=True)
    # --- 可选过滤器 (全部失败退回: 过滤后 <2 候选则跳过该过滤器) ---
    filtered = list(cands)
    # 1) 趋势持续性: MA5 > MA20 (上升通道, 拒绝死猫跳)
    if trend_filter and len(filtered) >= 2:
        tf = []
        for c, s, m, ind in filtered:
            v = series[c]
            ma5 = ma(v, i, 5)
            ma20 = ma(v, i, 20)
            if ma5 is not None and ma20 is not None and ma5 > ma20:
                tf.append((c, s, m, ind))
        if len(tf) >= 2:
            filtered = tf
    # 2) 相对强度: 个股动量 > HS300 同期动量 (真 alpha 非 beta)
    if rel_strength and hs_vals and i >= lookback and len(filtered) >= 2:
        h0 = hs_vals[i - lookback] if i - lookback >= 0 else None
        h1 = hs_vals[i]
        if h0 and h1 and h0 > 0:
            hs_mom = h1 / h0 - 1
            rs = [(c, s, m, ind) for c, s, m, ind in filtered if m > hs_mom]
            if len(rs) >= 2:
                filtered = rs
    # 3) 量能确认: 放量突破优先 (缩量新高多为假突破)
    if volume_confirm and vol_series and len(filtered) >= 2:
        vc = [(c, s, m, ind) for c, s, m, ind in filtered
              if volume_confirmed(vol_series, c, i, ratio=volume_ratio)]
        if len(vc) >= 2:
            filtered = vc
    # 4) 行业分散: Top2 来自不同行业 (避免同行业集中)
    if industry_diversify and len(filtered) >= 2:
        picked, seen = [], set()
        for item in filtered:
            if item[3] not in seen:
                picked.append(item)
                seen.add(item[3])
            if len(picked) >= 2:
                break
        if len(picked) >= 2:
            rest = [x for x in filtered if x[0] not in {p[0] for p in picked}]
            filtered = picked + rest
    top = [c[0] for c in filtered[:2]]
    return top, filtered[:5]


# ------------------------- 回测主循环 -------------------------
def run(offense_mode="fixed", grid=False, grid_step=0.06, grid_band=0.12,
        momentum_lookback=26, use_tech=False, vol_target=False, death_cross=True,
        core_satellite=False, core_frac=0.6, grid_weak=False, vol_ref=0.05,
        start_capital=1_000_000, verbose=False, eval_lo=None, eval_hi=None,
        record_plan=False, score_mode="plain", panel_path=None, use_core_sub=False,
        trend_filter=False, industry_diversify=False, rel_strength=False,
        adaptive_lookback=False,
        costs=True, commission_rate=0.00025, stamp_duty_rate=0.0005, slippage=0.001,
        volume_confirm=False, volume_ratio=1.0,
        macro_overlay=False, macro_tilt=0.2, tech_mode="static", tech_strength=1.0,
        valuation_overlay=False, val_tilt=0.2,
        cycle_overlay=False, cycle_tilt=0.3, cycle_weights=None, start_date=None):
    """A 股周频回测引擎.

    交易成本参数 (v6.16+):
      costs=True (默认): 启用 A 股真实成本建模
      commission_rate: 双边佣金费率 (默认 万2.5 = 0.00025)
      stamp_duty_rate: 卖出印花税率 (默认 0.0005, 2023-08 起减半)
      slippage: 单边滑点 (默认 0.1% = 0.001)
      costs=False: 成本归零, 与旧版可比 (毛收益)

    量能确认 (v6.17+):
      volume_confirm=True: 动态选股时要求近4周均量 >= volume_ratio × 近26周均量。
      volume_ratio: 放量门槛 (1.0=持平即可, >1 更严)。
      需要 <panel>_volume_<tag>.csv 与 close 面板并存(由 tencent_hfq_rebuild.py
      自动产出); 找不到则该过滤器静默关闭, 结果与关闭时一致。

    宏观周期叠加 (v6.17+):
      macro_overlay=True: 用 PMI/M2/社融合成的景气分微调进攻仓位。
      macro_tilt: 倾斜幅度, 进攻仓乘数 = 1 + macro_tilt × score(score∈[-1,1])。
        默认 0.2 -> 乘数 0.8~1.2。
      加仓从防御仓匀额度、减仓释放到现金, 不产生隐性杠杆。
      需要 data/macro_monthly.csv (由 macro_fetch.py 产出, 已内建发布滞后)。

    行业相位来源 (v6.18+):
      tech_mode="static" (默认): 用手写 PHASE_HISTORY。★ 含前视偏差 ——
        该表是回看历史标注的, 早期年份即已"知道"后续哪个行业会加速。
        保留为默认仅为与历史结果可比, 不代表它是正确口径。
      tech_mode="data": 用行业等权指数在每个时点现算相位, 无前视。
        评估真实可复现能力时应使用此模式; 两者差值即前视偏差的量级。
      tech_strength: 相位乘子强度缩放, mult' = 1 + (mult-1)×strength。
        0 等价于关闭, 1.0 为原始乘子。

    市场估值分位叠加 (v6.18+, 默认关闭):
      valuation_overlay=True: 用全 A 中位数 PE/PB 的**扩展窗口分位**逆向调仓 ——
        估值处历史高分位则减进攻、低分位则加进攻。
      val_tilt: 倾斜幅度, 进攻仓乘数 = 1 + val_tilt × score(score∈[-1,1])。
      分位按时点现算(只用历史), 且数据读数滞后 1 周, 无前视。
      需要 data/valuation_daily.csv (由 valuation_fetch.py 产出)。

    12 层金融周期叠加 (v6.20+, 默认关闭):
      cycle_overlay=True: 用 cycles 模块的 12 层 composite_regime 微调进攻仓位。
      cycle_tilt: 倾斜幅度(默认 0.3 = cycles.specs.ENGINE_TILT['ashare']; 全局 specs.DEFAULT_TILT=0.2),
        进攻仓乘数 =
        1 + cycle_tilt × composite_regime(regime∈[-1,1]), 落在 [TILT_MIN=0.5, TILT_MAX=1.5]。
        与 macro/估值 同款额度守恒: 加仓从防御仓匀、减仓释放现金, 不产生隐性杠杆。
        前视防护由 cycles 模块保证(仅看 available_date <= 调仓日的周期数据)。
        需要 cycles/data/cycles_raw.csv + cycles_qualitative_seed.csv (由 cycles/fetch.py 产出)。
        默认关闭; 详见 docs/cycle_framework.md。

      ★ 实证结论(务必先读, 勿被表面数字误导):
        全样本 tilt=0.6 看似"倍数 18.185x->16.575x, MDD -33.31%->-24.63%",
        但逐年拆解显示这是**单点事件**而非稳定风控能力:
          - 基准全局 MDD 发生于 2015-06-05 -> 2016-01-29 (2015 泡沫破裂);
            估值层把该次回撤 -30.11% 压到 -21.08% (改善 9.03pp), 削平主峰后
            全局 MDD 只是"转移"到 2021 年那次 (-24.63%)。
          - 年内独立回撤对照: 改善 2 年 / 恶化 6 年 / 持平 5 年。
            2019/2020/2021/2023/2024/2025 全部恶化(最多 -3.4pp)。
          - walk-forward 1y/2y 窗口配对检验 MDD 差 t≈-1.3~-1.8 (方向为加深),
            与"逐年多数恶化"一致, 与全样本数字相反。
        判定: 仅在 2015 型全市场泡沫中有效, 常态年份为负贡献且付出 -8.9% 倍数
        代价。默认关闭, 定位为"极端泡沫可选保险", 不进主线配置。
    """
    dates, codes, series = load_panel(panel_path)
    vol_series = load_volume_panel(panel_path) if volume_confirm else None
    macro_rows = load_macro() if macro_overlay else None
    val_pct = build_valuation_pct(load_valuation()) if valuation_overlay else None
    # 12 层周期叠加: 仅启用时导入 cycles(默认关闭, 绝不污染基线); 导入失败则静默降级
    _cyc_fn = None
    if cycle_overlay:
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            from cycles.overlay import cycle_scale_at as _cycle_scale_at
            # 未显式传权重时, 按引擎 key 回退到 specs.ENGINE_CYCLE_WEIGHTS(逐引擎精选周期+权重)
            _cyc_weights = cycle_weights
            if _cyc_weights is None:
                try:
                    from cycles import specs as _cspecs
                    _cyc_weights = _cspecs.ENGINE_CYCLE_WEIGHTS.get("ashare")
                except Exception:
                    _cyc_weights = None
            _cyc_fn = (lambda d, t, _at=_cycle_scale_at, _w=_cyc_weights: _at(d, t, weights=_w))
        except Exception as e:
            print(f"[warn] cycle_overlay 启用但 cycles 模块加载失败: {e}; 叠加层已禁用")
    if use_core_sub:
        # 核心仓时间扩展: needed 用代理票(更早上市)决定起点, 把窗口前推到 ~2011;
        # 上市后原样使用 OFF4 本尊(first_valid 切换)。需配合干净的后复权面板。
        needed = DEF16 + [CORE_SUB.get(c, c) for c in OFF4] + [HS300] + DC_INDICES
        aligned, start = extract(dates, series, needed)
        first_valid = {}
        for c in list(OFF4) + list(CORE_SUB.values()) + DEF16 + CONVERTIBLES + DC_INDICES:
            lst = series.get(c)
            if not lst:
                continue
            fv = 0
            while fv < len(lst) and (lst[fv] is None or lst[fv] <= 0):
                fv += 1
            if fv < len(lst):
                first_valid[c] = fv
    else:
        # 默认(已验证): 不扩展, 窗口由 OFF4 最晚上市(宁德 2018-06)决定, 即 2018+。
        needed = DEF16 + OFF4 + [HS300] + DC_INDICES
        aligned, start = extract(dates, series, needed)
        first_valid = None

    # 窗口起点约束(用于 3/5/10 年回测): 交易从 start_date 当周开始, 不影响全样本基线(默认 None)
    if start_date:
        _sd = str(start_date)
        for _i, _d in enumerate(dates):
            if _d >= _sd:
                start = max(start, _i)
                break

    # 进攻候选池(剔除黑名单行业)元信息: 从 config 读 industry
    cfg = json.load(open(os.path.join(os.path.dirname(os.path.dirname(BASE)), "strategy_config.json"), encoding="utf-8"))
    pool_meta = {}
    for p in cfg.get("auto_select", {}).get("candidate_pool", []):
        if p.get("industry") not in OFFENSE_BLACKLIST:
            pool_meta[p["code"]] = p

    # 数据驱动相位: 全样本一次性预计算(每周只回看, 无前视), 之后 O(1) 查表
    ind_phases = (build_industry_phases(dates, series, pool_meta)
                  if (use_tech and tech_mode == "data") else None)

    hs = aligned[HS300]
    nav = [0.0] * len(dates)
    holdings = {}      # code -> shares
    cash = start_capital
    nav_val = start_capital
    # 初始化
    i = start
    plan = []   # record_plan=True 时记录每周调仓: (date, off_codes, c_pct, regime)
    # 先定首期持仓
    def_names = [c for c in DEF16 if c in aligned]
    off_names = list(OFF4) if offense_mode == "fixed" else []

    def compute_weights(i, regime, dc_trig, off_codes):
        alloc = REGIME_ALLOC[regime]
        d_pct = alloc["def"]; o_pct = alloc["off"]; c_pct = alloc["cash"]
        if dc_trig:
            d_pct = min(100, d_pct + o_pct); o_pct = 0.0
        # 波动率目标: 用进攻篮子近 13 周已实现波动缩放进攻仓(降回撤)
        if vol_target and off_codes and o_pct > 0:
            import math
            vols = []
            for c in off_codes:
                v = series.get(c)
                if not v or i < 13:
                    continue
                rets = [(v[k]/v[k-1]-1) for k in range(max(1,i-13), i+1) if v[k] and v[k-1]]
                if rets:
                    mu = sum(rets)/len(rets)
                    sd = (sum((x-mu)**2 for x in rets)/len(rets))**0.5
                    vols.append(sd)
            if vols:
                avg_vol = sum(vols)/len(vols)
                scale = max(0.55, min(1.3, vol_ref / (avg_vol + 1e-9)))
                new_o = max(0.0, min(80.0, o_pct * scale))
                if scale >= 1.0:
                    # 加仓进攻: 从防御仓匀额度, 杜绝 d+o+c>100 的隐性杠杆
                    d_pct = max(0.0, d_pct - (new_o - o_pct))
                else:
                    # 减仓进攻: 释放进现金
                    c_pct = c_pct + (o_pct - new_o)
                o_pct = new_o
        # 宏观周期叠加: 景气上行加进攻/下行减进攻 (与 vol_target 同样的额度守恒规则)
        if macro_rows and o_pct > 0:
            ms = macro_score_at(macro_rows, dates[i])
            if ms:
                scale = 1.0 + macro_tilt * ms
                new_o = max(0.0, min(80.0, o_pct * scale))
                if new_o > o_pct:
                    take = min(new_o - o_pct, d_pct)   # 只能从防御仓匀, 匀不出就不加
                    new_o = o_pct + take
                    d_pct = d_pct - take
                else:
                    c_pct = c_pct + (o_pct - new_o)
                o_pct = new_o
        # 市场估值分位叠加: 便宜加进攻 / 贵减进攻 (同样的额度守恒规则)
        if val_pct and o_pct > 0:
            vs = valuation_score_at(val_pct, dates[i])
            if vs:
                scale = 1.0 + val_tilt * vs
                new_o = max(0.0, min(80.0, o_pct * scale))
                if new_o > o_pct:
                    take = min(new_o - o_pct, d_pct)
                    new_o = o_pct + take
                    d_pct = d_pct - take
                else:
                    c_pct = c_pct + (o_pct - new_o)
                o_pct = new_o
        # 12 层金融周期叠加: composite_regime 微调进攻仓(同样的额度守恒规则)
        if _cyc_fn is not None and o_pct > 0:
            from cycles.overlay import apply_to_alloc
            cs = _cyc_fn(dates[i], cycle_tilt)
            if cs != 1.0:
                o_pct, d_pct, c_pct = apply_to_alloc(o_pct, d_pct, c_pct, cs)
        return d_pct, o_pct, c_pct

    # ---- 交易成本参数 (v6.16+) ----
    if not costs:
        commission_rate = 0.0
        stamp_duty_rate = 0.0
        slippage = 0.0
    # 卖出侧费率 = 佣金 + 印花税 + 滑点; 买入侧费率 = 佣金 + 滑点
    sell_cost_rate = commission_rate + stamp_duty_rate + slippage
    buy_cost_rate = commission_rate + slippage
    total_cost_deducted = 0.0  # 累计已扣成本 (用于统计)

    def rebalance(i, regime, dc_trig, off_spec, grid_on):
        nonlocal nav_val, holdings, cash, total_cost_deducted
        off_codes = [c for c, _ in off_spec]
        d_pct, o_pct, c_pct = compute_weights(i, regime, dc_trig, off_codes)
        total = nav_val
        w_def = {c: d_pct / len(def_names) / 100.0 for c in def_names}
        w_off = {c: (o_pct / 100.0) * w for c, w in off_spec}
        # 网格 sleeve: 仅在非弱势市启用(熊市不接飞刀)
        grid_active = grid_on and (regime != "weak" or grid_weak) and off_spec
        if grid_active:
            devs = []
            for c, _ in off_spec:
                v = series[c]
                m = ma(v, i, 13)
                devs.append(((v[i] - m) / m) if (m and v[i]) else 0.0)
            gs = [max(0.0, min(1.0, 1.0 - d / grid_band)) for d in devs]
            G = sum(gs)
            ammo = (c_pct / 100.0)
            if G > 0:
                for j, (c, _) in enumerate(off_spec):
                    w_off[c] = w_off.get(c, 0) + ammo * gs[j] / G
        combined_w = {**w_def, **w_off}

        # ---- 交易成本计算 (v6.16+) ----
        if costs and holdings:
            # 计算各标的调仓前/后市值, 算 turnover
            all_codes = set(list(combined_w.keys()) + list(holdings.keys()))
            sells_val = 0.0
            buys_val = 0.0
            for c in all_codes:
                price = series.get(c, [None] * (i + 1))[i] if c in series else None
                old_val = holdings.get(c, 0) * price if (price and price > 0) else 0.0
                new_val = total * combined_w.get(c, 0.0)
                if new_val < old_val:
                    sells_val += (old_val - new_val)
                elif new_val > old_val:
                    buys_val += (new_val - old_val)
            trade_cost = sells_val * sell_cost_rate + buys_val * buy_cost_rate
            total_cost_deducted += trade_cost
            net_total = total - trade_cost
        else:
            net_total = total

        new_hold = {}
        for c, w in combined_w.items():
            price = series[c][i]
            if price is None or price <= 0:
                continue
            new_hold[c] = net_total * w / price
        holdings = new_hold
        invested = sum(holdings[c] * series[c][i] for c in holdings if series[c][i])
        cash = max(0.0, net_total - invested)
        if record_plan:
            plan.append({"i": i, "date": dates[i], "off": off_codes,
                         "off_spec": [[c, w] for c, w in off_spec],
                         "c_pct": c_pct, "regime": regime, "dc": dc_trig,
                         "nav_i": nav[i]})

    # 逐周: 先用当前持仓按本周收盘估值(捕获周间涨跌), 再调仓
    for i in range(start, len(dates)):
        val = cash + sum(holdings[c] * series[c][i] for c in holdings if series[c][i] is not None and series[c][i] > 0)
        nav[i] = val
        nav_val = val
        regime = regime_at(hs, i)
        dc_trig = death_cross_at(aligned, i) if death_cross else False
        # 构建进攻 spec
        if offense_mode == "fixed":
            if use_core_sub and first_valid:
                off_codes = [c for c in OFF4 if first_valid.get(c) is not None and i >= first_valid[c]]
            else:
                off_codes = [c for c in OFF4 if c in aligned]
            off_spec = [(c, 1.0 / len(off_codes)) for c in off_codes] if off_codes else []
        else:
            # 市况自适应 lookback: 强势追趋势(短13w), 平衡中周期(26w), 弱势避假动量(长52w)
            if adaptive_lookback:
                lb_map = {"bull": 13, "balance": 26, "weak": 52}
                lb = lb_map.get(regime, momentum_lookback)
            else:
                lb = momentum_lookback
            dyn, _ = momentum_select(
                dates, series, pool_meta, i, lb, use_tech,
                score_mode=score_mode, trend_filter=trend_filter,
                industry_diversify=industry_diversify,
                rel_strength=rel_strength, hs_vals=hs,
                volume_confirm=volume_confirm, vol_series=vol_series,
                volume_ratio=volume_ratio,
                tech_mode=tech_mode, ind_phases=ind_phases,
                tech_strength=tech_strength)
            if not dyn:
                if use_core_sub and first_valid:
                    dyn = [c for c in OFF4 if first_valid.get(c) is not None and i >= first_valid[c]]
                else:
                    dyn = [c for c in OFF4 if c in aligned]
            if core_satellite:
                if use_core_sub and first_valid:
                    core = []
                    for c in OFF4:
                        if first_valid.get(c) is not None and i >= first_valid[c]:
                            core.append(c)
                        else:
                            sub = CORE_SUB.get(c)
                            if sub and first_valid.get(sub) is not None and i >= first_valid[sub]:
                                core.append(sub)
                else:
                    core = [c for c in OFF4 if c in aligned]
                if core:
                    core_set = set(core)
                    sat = [c for c in dyn if c not in core_set]
                    n_c, n_s = len(core), max(1, len(sat))
                    off_spec = [(c, core_frac / n_c) for c in core] + \
                               [(c, (1 - core_frac) / n_s) for c in sat]
                else:
                    off_spec = [(c, 1.0 / len(dyn)) for c in dyn] if dyn else []
            else:
                off_spec = [(c, 1.0 / len(dyn)) for c in dyn]
        rebalance(i, regime, dc_trig, off_spec, grid)

    # 指标 (支持 walk-forward: eval_lo/eval_hi 仅度量该切片, 倍数相对入口权益)
    lo = start if eval_lo is None else max(start, eval_lo)
    hi = len(dates) if eval_hi is None else min(len(dates), eval_hi)
    entry = nav[lo] if (nav[lo] and nav[lo] > 0) else start_capital
    slice_nav = [nav[i] for i in range(lo, hi) if nav[i] and nav[i] > 0]
    nav_valid = slice_nav if slice_nav else [entry]
    final = nav_valid[-1]
    mult = final / entry
    # MDD
    peak = nav_valid[0]; mdd = 0.0
    for v in nav_valid:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak)
    # 基准 HS300
    hs0 = hs[lo]; hs1 = hs[hi - 1]
    hs_ret = (hs1 / hs0) if hs0 else 1.0
    yrs = (hi - lo) / 52.0
    cagr = (mult) ** (1 / yrs) - 1 if yrs > 0 else 0
    excess = mult / hs_ret if hs_ret else mult
    stats = {
        "offense_mode": offense_mode, "grid": grid, "momentum_lookback": momentum_lookback,
        "use_tech": use_tech, "tech_mode": tech_mode, "tech_strength": tech_strength,
        "vol_target": vol_target, "death_cross": death_cross,
        "core_satellite": core_satellite, "core_frac": core_frac, "grid_weak": grid_weak,
        "vol_ref": vol_ref, "score_mode": score_mode,
        "trend_filter": trend_filter, "industry_diversify": industry_diversify,
        "rel_strength": rel_strength, "adaptive_lookback": adaptive_lookback,
        "macro_overlay": macro_overlay, "macro_tilt": macro_tilt,
        "valuation_overlay": valuation_overlay, "val_tilt": val_tilt,
        "costs": costs, "total_cost_deducted": round(total_cost_deducted),
        "survivorship_bias": SURVIVORSHIP_BIAS_NOTE,
        "start": dates[lo], "end": dates[hi - 1], "weeks": (hi - lo),
        "final_multiple": round(mult, 3), "final_nav": round(final),
        "mdd": round(mdd * 100, 2), "cagr": round(cagr * 100, 2),
        "hs300_multiple": round(hs_ret, 3), "excess_vs_hs300": round(excess, 2),
    }
    return stats, nav, start, plan


if __name__ == "__main__":
    print("=== A 股回测引擎: 基线 vs 优化杠杆对比 (含交易成本) ===\n")
    panel = os.path.join(DATA, "ashare_panel_close_em.csv")
    use_panel = panel_path if panel_path else (panel if os.path.exists(panel) else None)
    configs = [
        ("基线(固定OFF4, 无网格)", dict(offense_mode="fixed", grid=False, death_cross=True, panel_path=use_panel, use_core_sub=True)),
        ("动态26(纯动量)", dict(offense_mode="momentum", momentum_lookback=26, use_tech=True, grid=False, death_cross=True, panel_path=use_panel, use_core_sub=True)),
        ("动态26+核心卫星(0.5)", dict(offense_mode="momentum", momentum_lookback=26, use_tech=True, grid=False, core_satellite=True, core_frac=0.5, death_cross=True, panel_path=use_panel, use_core_sub=True, trend_filter=True)),
        ("动态26+卫星+波动目标", dict(offense_mode="momentum", momentum_lookback=26, use_tech=True, grid=False, core_satellite=True, core_frac=0.5, vol_target=True, vol_ref=0.06, death_cross=True, panel_path=use_panel, use_core_sub=True, trend_filter=True)),
        ("动态26+卫星+网格(非弱势)", dict(offense_mode="momentum", momentum_lookback=26, use_tech=True, grid=True, grid_weak=False, core_satellite=True, core_frac=0.5, death_cross=True, panel_path=use_panel, use_core_sub=True, trend_filter=True)),
    ]
    print(f"{'配置':<30}{'倍数':>8}{'MDD%':>8}{'CAGR%':>8}{'HS300x':>9}{'超额x':>8}{'成本':>10}")
    print("-" * 85)
    base_mult = None
    for name, kw in configs:
        s, _, _, _ = run(**kw)
        if base_mult is None:
            base_mult = s["final_multiple"]
        flag = "  <== 超基线" if s["final_multiple"] > base_mult else ""
        print(f"{name:<30}{s['final_multiple']:>8}{s['mdd']:>8}{s['cagr']:>8}"
              f"{s['hs300_multiple']:>9}{s['excess_vs_hs300']:>8}{s['total_cost_deducted']:>10}{flag}")
    print(f"\n窗口: {s['start']} ~ {s['end']} ({s['weeks']}周) | 基线倍数={base_mult}")
    print(f"交易成本: 佣金万2.5双边 + 印花税0.05%卖出 + 滑点0.1%双边 | 累计扣费: {s['total_cost_deducted']}")

