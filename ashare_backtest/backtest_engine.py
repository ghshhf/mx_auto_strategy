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
                    rel_strength=False, hs_vals=None):
    """从候选池选 Top2。score_mode 决定打分方式:
      plain    : 动量 * 相位乘子 (原版)
      blend    : 多周期融合(13w*0.35 + 26w*0.40 + 52w*0.25) * 相位, 平滑信号减少 whipsaw
      risk_adj : 风险调整动量 = 动量*相位 / 已实现波动 (Sharpe 式, 偏平滑趋势)
      sortino  : 动量*相位 / 下行波动 (仅惩罚回撤, 更激进但控回撤)
    可选过滤器 (全部默认关闭, 失败退回原逻辑):
      trend_filter      : 要求 MA5 > MA20 (上升通道, 拒绝死猫跳)
      industry_diversify: Top2 来自不同行业 (避免同行业集中)
      rel_strength      : 个股动量 > HS300 同期动量 (真 alpha 非 beta)
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
        mult = tech_mult(ind, year) if use_tech else 1.0
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
    # 3) 行业分散: Top2 来自不同行业 (避免同行业集中)
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
        momentum_lookback=13, use_tech=True, vol_target=False, death_cross=True,
        core_satellite=False, core_frac=0.6, grid_weak=False, vol_ref=0.05,
        start_capital=1_000_000, verbose=False, eval_lo=None, eval_hi=None,
        record_plan=False, score_mode="plain", panel_path=None, use_core_sub=False,
        trend_filter=False, industry_diversify=False, rel_strength=False,
        adaptive_lookback=False,
        costs=True, commission_rate=0.00025, stamp_duty_rate=0.0005, slippage=0.001):
    """A 股周频回测引擎.

    交易成本参数 (v6.16+):
      costs=True (默认): 启用 A 股真实成本建模
      commission_rate: 双边佣金费率 (默认 万2.5 = 0.00025)
      stamp_duty_rate: 卖出印花税率 (默认 0.0005, 2023-08 起减半)
      slippage: 单边滑点 (默认 0.1% = 0.001)
      costs=False: 成本归零, 与旧版可比 (毛收益)
    """
    dates, codes, series = load_panel(panel_path)
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

    # 进攻候选池(剔除黑名单行业)元信息: 从 config 读 industry
    cfg = json.load(open(os.path.join(os.path.dirname(BASE), "strategy_config.json"), encoding="utf-8"))
    pool_meta = {}
    for p in cfg.get("auto_select", {}).get("candidate_pool", []):
        if p.get("industry") not in OFFENSE_BLACKLIST:
            pool_meta[p["code"]] = p

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
                rel_strength=rel_strength, hs_vals=hs)
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
        "use_tech": use_tech, "vol_target": vol_target, "death_cross": death_cross,
        "core_satellite": core_satellite, "core_frac": core_frac, "grid_weak": grid_weak,
        "vol_ref": vol_ref, "score_mode": score_mode,
        "trend_filter": trend_filter, "industry_diversify": industry_diversify,
        "rel_strength": rel_strength, "adaptive_lookback": adaptive_lookback,
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

