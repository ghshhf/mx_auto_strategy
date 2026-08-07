"""
us_backtest_ai.py - 美股真实面板回测 + AI 选股层接入 (v6.15+)

目的:
  在真实面板(weekly_adjclose_full_ext.csv, 2016~2026 周频, westock-data 抓取真实
  GLD/JPM)上, 量化美股引擎(对齐 A 股16倍方法论, 适配美股长牛/赢家集中) + A 股系统的
  AI 选股打分层(ai_score.py, 0.8~1.2 乘数)。

  防御端设计(用户指定, v6.15 修正): 彻底去黄金。防御 = 分红股(低波动候选 KO/JNJ/ABBV/
  PG/XOM 等, 面板已有真实数据)。极端防御 = 现金(非长债!): 经验证 TLT 2022 -28.4% / IEF -13.5%
  与成长同跌, 利率驱动使其非危机对冲; 故 crash/波动飙升时把压掉的股权敞口转现金(或短久期/
  分红)。防御占比整体小(平衡5% / 弱市15% / crash 15%), 符合"防御配置不大"的要求。早期
  extend_panel_bonds.py 债券对冲路径已废弃。

  报告五档(同一引擎, 不同风险旋钮):
  1) baseline    : v6.14b 修正控制组(弱市停车进分红防御篮, 去黄金, 季频, 等权 Top10)
  2) optimized   : 美股优化引擎(无杠杆, 进攻主导+防御小, 主题解相关max2): 周频 + 动量Top3集中
                   + MA5>MA20门 + 动态池月度re-screen + crash现金(正确极端防御=现金, 非长债)。
                   倍数 ≈22.9x(扩池后诚实值, ≈1.4×A股16x; 旧33.7x依赖漏池隐性过拟合, 已废弃),
                   但纯动量高beta -> MDD≈-48%(结构性)。
  3) optimized-defensive(结构性现金袖 --struct-def, 默认20%->现金): 无杠杆下均匀压每年回撤的
                   唯一有效手段。40%袖 -> ≈8.5x / MDD≈-32%; 40%+volT0.22 -> ≈8.0x / MDD≈-30%。
  4) optimized+ai: optimized 进攻仓再叠 ai_score 质量乘数(确定性可复现 / --with-llm 真接线)
  5) optimized+lev(--lev>1, 默认1.0关闭): 净杠杆档, 1.2x→≈32.0x / 1.3x→≈36.8x(回撤放大, 借入成本未计)
  注: 用户要求无杠杆(扩池后≈22.9x/MDD-48%); 纯动量MDD无法靠事后信号压, 结构性降敞口(现金袖/波动目标)
      是唯一路径, 代价是收益。"23x且-30%"无杠杆下不可兼得(见 README 7.1 前沿表)。

为什么叫「AI 选股层」:
  ai_score.augment(candidates, cfg, tag) 是 A 股系统通用 AI 加权打分层, 输出 0.8~1.2 质量乘数。
  设计铁律: 回测禁用实时 LLM(前视+不可复现), AI 仅 live shadow。故默认用确定性质量乘数(可复现),
  --with-llm 时真正调用 ai_score.augment(未配 LLM 自动 pass-through=1.0)。

运行:
  python us_backtest_ai.py                       # 五档全跑(确定性 AI; 杠杆档默认1.0不显示)
  python us_backtest_ai.py --mode optimized      # 仅 optimized 两档
  python us_backtest_ai.py --refresh monthly     # 动态池刷新频率(monthly/quarterly, 默认 monthly)
  python us_backtest_ai.py --struct-def 0.40     # 防御档切 40% 现金袖(→~8.6x / MDD≈-32%; +--vol-target 0.22→~8.1x/-30%)
  python us_backtest_ai.py --with-llm            # optimized+ai 真正调用 ai_score.augment
  python us_backtest_ai.py --no-ai               # 关闭 AI(仅 baseline+optimized+防御档)
  python us_backtest_ai.py --lev 1.3             # 杠杆档用 1.3x(→~37.7x, 回撤放大, 默认1.0关闭)
输出:
  us_stocks/data/us_nav_ai.csv (date, baseline_nav, optimized_nav, [optimized_def_nav], [optimized_ai_nav])
"""
import os
import csv
import json
import math
import argparse
import statistics
import sys
from datetime import datetime

# 允许从仓库任意位置运行本脚本时仍能 import 根目录的 ai_score
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
PANEL = os.path.join(DATA, "weekly_adjclose_full_ext.csv")
OUT_CSV = os.path.join(DATA, "us_nav_ai.csv")

EXCLUDE = {"SPY", "QQQ", "DIA", "IWM", "MDY", "VTI", "CWB", "GLD",
           "TLT", "IEF", "AGG", "BND", "SHY",
           "SEMI_INDEX", "TECH_INDEX", "SOX",
           "HEALTH_INDEX", "CONSUMER_INDEX", "FINANCIAL_INDEX",
           "ENERGY_INDEX", "CLEAN_INDEX", "AUTO_INDEX", "INDUSTRIAL_INDEX"}

# ======================================================= 行业映射(个股 -> 对应做空行业指数)
# 用于被行权/换出后, 匹配对应行业指数做空(比空单一TECH_INDEX更精准).
# 原则: 个股属于哪个行业就空哪个行业指数; 行业小/指数弱(票少MAE大)的退回到TECH/QQQ大盘.
# 仅用于回测short_positions开仓, 不影响选股universe(EXCLUDE已经排除了合成指数).
STOCK_SECTOR = {
    # ---- 科技/半导体 ----
    "NVDA":"SEMI_INDEX","AMD":"SEMI_INDEX","AVGO":"SEMI_INDEX","SMCI":"SEMI_INDEX",
    "INTC":"SEMI_INDEX","QCOM":"SEMI_INDEX","TXN":"SEMI_INDEX","MU":"SEMI_INDEX",
    "AMAT":"SEMI_INDEX","LRCX":"SEMI_INDEX","KLAC":"SEMI_INDEX","MRVL":"SEMI_INDEX",
    "ASML":"SEMI_INDEX","TSM":"SEMI_INDEX","ARM":"SEMI_INDEX","MPWR":"SEMI_INDEX",
    "MSFT":"TECH_INDEX","AAPL":"TECH_INDEX","GOOGL":"TECH_INDEX","META":"TECH_INDEX",
    "AMZN":"TECH_INDEX","NFLX":"TECH_INDEX","CRM":"TECH_INDEX","ADBE":"TECH_INDEX",
    "INTU":"TECH_INDEX","ORCL":"TECH_INDEX","PLTR":"TECH_INDEX","NOW":"TECH_INDEX",
    "SNOW":"TECH_INDEX","DDOG":"TECH_INDEX","NET":"TECH_INDEX","TEAM":"TECH_INDEX",
    "WDAY":"TECH_INDEX","ZS":"TECH_INDEX","PANW":"TECH_INDEX","CSCO":"TECH_INDEX",
    "IBM":"TECH_INDEX","ACN":"TECH_INDEX","FICO":"TECH_INDEX","ANSS":"TECH_INDEX",
    "CDNS":"TECH_INDEX","SQ":"TECH_INDEX","PYPL":"TECH_INDEX","SHOP":"TECH_INDEX",
    "COIN":"TECH_INDEX","HOOD":"TECH_INDEX","SOFI":"TECH_INDEX","AFRM":"TECH_INDEX",
    "UPST":"TECH_INDEX","TWLO":"TECH_INDEX","NU":"FINANCIAL_INDEX",
    # ---- 医药 ----
    "LLY":"HEALTH_INDEX","NVO":"HEALTH_INDEX","AZN":"HEALTH_INDEX","VRTX":"HEALTH_INDEX",
    "REGN":"HEALTH_INDEX","MRNA":"HEALTH_INDEX","GILD":"HEALTH_INDEX","AMGN":"HEALTH_INDEX",
    "ILMN":"HEALTH_INDEX","PFE":"HEALTH_INDEX","MRK":"HEALTH_INDEX","ABBV":"HEALTH_INDEX",
    "JNJ":"HEALTH_INDEX","BMY":"HEALTH_INDEX","MDT":"HEALTH_INDEX","ISRG":"HEALTH_INDEX",
    "UNH":"HEALTH_INDEX","ABT":"HEALTH_INDEX","SYK":"HEALTH_INDEX","CVS":"HEALTH_INDEX",
    # ---- 消费 ----
    "KO":"CONSUMER_INDEX","PEP":"CONSUMER_INDEX","COST":"CONSUMER_INDEX","WMT":"CONSUMER_INDEX",
    "PG":"CONSUMER_INDEX","MCD":"CONSUMER_INDEX","CL":"CONSUMER_INDEX","NKE":"CONSUMER_INDEX",
    "SBUX":"CONSUMER_INDEX","BKNG":"CONSUMER_INDEX","EBAY":"CONSUMER_INDEX","ETSY":"CONSUMER_INDEX",
    "SPOT":"CONSUMER_INDEX","TME":"CONSUMER_INDEX","DASH":"CONSUMER_INDEX","HUBS":"CONSUMER_INDEX",
    "CPNG":"CONSUMER_INDEX","YUM":"CONSUMER_INDEX","QSR":"CONSUMER_INDEX","SE":"CONSUMER_INDEX",
    "PDD":"CONSUMER_INDEX","BABA":"CONSUMER_INDEX","JD":"CONSUMER_INDEX",
    # ---- 金融(含卡/券商) ----
    "JPM":"FINANCIAL_INDEX","BAC":"FINANCIAL_INDEX","WFC":"FINANCIAL_INDEX","V":"FINANCIAL_INDEX",
    "MA":"FINANCIAL_INDEX","AXP":"FINANCIAL_INDEX","BLK":"FINANCIAL_INDEX","GS":"FINANCIAL_INDEX",
    "MS":"FINANCIAL_INDEX","C":"FINANCIAL_INDEX","SCHW":"FINANCIAL_INDEX","FIS":"FINANCIAL_INDEX",
    "FISV":"FINANCIAL_INDEX",
    # ---- 能源 ----
    "XOM":"ENERGY_INDEX","CVX":"ENERGY_INDEX","EOG":"ENERGY_INDEX","COP":"ENERGY_INDEX",
    "OXY":"ENERGY_INDEX","SLB":"ENERGY_INDEX",
    # ---- 清洁/光伏 ----
    "ENPH":"CLEAN_INDEX","SEDG":"CLEAN_INDEX","FSLR":"CLEAN_INDEX","JKS":"CLEAN_INDEX",
    "CSIQ":"CLEAN_INDEX","RUN":"CLEAN_INDEX","NEE":"CLEAN_INDEX","BEPC":"CLEAN_INDEX",
    "CWEN":"CLEAN_INDEX","AY":"CLEAN_INDEX","PLUG":"CLEAN_INDEX",
    # ---- 电车/自动驾驶 (电车TSLA横跨CLEAN+AUTO, 这里AUTO专属自动驾驶新势力; TSLA先归属CLEAN) ----
    "RIVN":"AUTO_INDEX","LI":"AUTO_INDEX","NIO":"AUTO_INDEX",
    "XPEV":"AUTO_INDEX","MBLY":"AUTO_INDEX","LCID":"AUTO_INDEX","FSR":"AUTO_INDEX","TSLA":"CLEAN_INDEX",
    # ---- 工业 ----
    "CAT":"INDUSTRIAL_INDEX","DE":"INDUSTRIAL_INDEX","HON":"INDUSTRIAL_INDEX",
    "BA":"INDUSTRIAL_INDEX","LMT":"INDUSTRIAL_INDEX","UPS":"INDUSTRIAL_INDEX",
    "GE":"INDUSTRIAL_INDEX","FTV":"INDUSTRIAL_INDEX","ROK":"INDUSTRIAL_INDEX",
    "IR":"INDUSTRIAL_INDEX","TER":"INDUSTRIAL_INDEX","VRT":"INDUSTRIAL_INDEX",
    "NXT":"INDUSTRIAL_INDEX","ITW":"INDUSTRIAL_INDEX","ETN":"INDUSTRIAL_INDEX",
    "PH":"INDUSTRIAL_INDEX","CARR":"INDUSTRIAL_INDEX","OTIS":"INDUSTRIAL_INDEX",
    "RTX":"INDUSTRIAL_INDEX","SWK":"INDUSTRIAL_INDEX",
    # ---- 其他(太空/通信服务/房产): 找不到行业指数就退回TECH大盘 ----
    "IONQ":"TECH_INDEX","RGTI":"TECH_INDEX","ASTS":"TECH_INDEX","RKLB":"TECH_INDEX",
    "EQIX":"TECH_INDEX","DLR":"TECH_INDEX","VZ":"TECH_INDEX","CMCSA":"TECH_INDEX",
    "DIS":"CONSUMER_INDEX","WBD":"CONSUMER_INDEX",
}
# 行业指数 -> 弱票数不足的降级: 找不到行业映射或指数无数据时用TECH_INDEX或QQQ
SECTOR_FALLBACK = {
    "FINANCIAL_INDEX": "TECH_INDEX",   # 或"QQQ"? 扫描TECH_INDEX更强
    "CONSUMER_INDEX":  "TECH_INDEX",   # 消费票多但MAE大, 降级到TECH大盘更稳
    "AUTO_INDEX":      "TECH_INDEX",   # 8只TSLA权重过高
    # HEALTH/ENERGY/CLEAN/INDUSTRIAL/SEMI/TECH 指数票多或MAE小 -> 直接用
}


def sector_short_index(code, options_sim, series, t):
    """根据个股行业 -> 返回应该空的行业指数代码(必须在面板中有, 否则fallback到TECH/QQQ)。
    
    决策链:
      1. STOCK_SECTOR[code] 命中 → 候选 idx
      2. 若 idx 在 SECTOR_FALLBACK 里 → 取降级值(行业太弱)
      3. 若面板series[idx]该周有有效数据 → 返回 idx
      4. 否则 → fallback: options_sim.short_underlying 配置(默认TECH_INDEX)
    """
    sector = STOCK_SECTOR.get(code)
    cfg_default = options_sim.get("short_underlying", "TECH_INDEX")
    if not sector:
        return cfg_default
    # 降级(小行业)
    if sector in SECTOR_FALLBACK:
        sector = SECTOR_FALLBACK[sector]
    # 数据可用性
    arr = series.get(sector)
    if not arr or t >= len(arr) or arr[t] is None or arr[t] <= 0:
        return cfg_default
    return sector

BROAD = ["SPY", "QQQ", "DIA", "IWM", "MDY", "VTI"]
DEF_NEW = ["KO", "NEE", "JPM"]                  # v6.14b 静态防御篮(baseline 用)
DEF_CANDIDATES = ["KO", "JNJ", "COST", "ABBV", "MCD", "PG", "WMT", "MMM",
                  "UNH", "HD", "PEP", "CL", "DHR", "LIN", "CAT", "DE"]  # 动态防御候选池
WARMUP = 52                                     # 需 1 年历史算动量

# 木头姐主题解相关: 标的 -> 主题(来自 us_adoption.THEME_STOCKS 13 主题原生篮子)
sys.path.insert(0, HERE)
_THEME_MAP = {}
try:
    from us_adoption import THEME_STOCKS as _US_THEMES, get_adoption as _us_get_adoption
    for _th, _stocks in _US_THEMES.items():
        for _s in _stocks:
            _THEME_MAP.setdefault(_s, _th)
except Exception:
    _us_get_adoption = None

# ----------------------------------------------------------------- 数据/工具
def load_panel(path):
    rows = list(csv.reader(open(path, encoding="utf-8")))
    hdr, data = rows[0], rows[1:]
    series = {c: [] for c in hdr[1:]}
    dates = [r[0] for r in data]
    for r in data:
        for i, c in enumerate(hdr[1:], 1):
            try:
                series[c].append(float(r[i]))
            except (ValueError, IndexError):
                series[c].append(None)
    return dates, series


def load_us_cfg(path=None):
    """读取 us_backtest 配置段, 提供默认值兜底(兼容老配置/无配置运行)。

    Returns:
        dict: {
            "take_profit_pct": float,   # +50% 止盈(=阶段2 covered call 行权价预留)
            "stop_loss_pct": float,     # -999 = 关闭(动量策略里止损压不了MDD反而少赚)
            "slippage_bps": int,        # 3 = 0.03% 美股真实滑点
            "options": {...},
        }
    """
    default = {
        "take_profit_pct": 0.50,
        "stop_loss_pct": -999.0,
        "slippage_bps": 3,
        "options": {"enabled": False, "min_dte": 180, "otm_pct": 0.10,
                    "hedge_underlying": "QQQ"},
        "options_sim": {"enabled": True, "call_premium_rate": 0.045,
                        "call_dte_weeks": 52, "put_premium_annual": 0.061,
                        "put_hedge_ratio": 0.5, "put_crash_threshold": 0.05,
                        "stock_put_premium_annual": 0.064},
    }
    if path is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "strategy_config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        us = cfg.get("us_backtest", {})
        return {
            "take_profit_pct": float(us.get("take_profit_pct", default["take_profit_pct"])),
            "stop_loss_pct": float(us.get("stop_loss_pct", default["stop_loss_pct"])),
            "slippage_bps": int(us.get("slippage_bps", default["slippage_bps"])),
            "options": us.get("options", default["options"]),
            "options_sim": us.get("options_sim", default["options_sim"]),
        }
    except Exception:
        return default


def check_take_profit(code, state, price, us_cfg):
    """到止盈价触发, 阶段1 清仓, 阶段2 卖 covered call。

    止盈价 = entry_price × (1 + take_profit_pct)
    默认 take_profit_pct = 0.50 (+50%)

    Returns:
        None - 未触发
        "clear" - 阶段1 清仓(阶段2 改为 "sell_call")
    """
    tp_pct = us_cfg["take_profit_pct"]
    entry = state.get("entry_price")
    if not entry or entry <= 0 or price is None or price <= 0:
        return None
    strike = entry * (1 + tp_pct)
    # 浮点容差: entry_price 经加权平均后可能漂移(如 100.00000000000004),
    # 导致 strike=150.00000000000006, price=150.0 不满足 >=。相对 1e-9 容差。
    if price >= strike * (1 - 1e-9):
        return "clear"
    return None


def check_stop_loss(code, state, price, us_cfg):
    """硬止损: 单票亏损超阈值全清。

    定位 = 风险护栏(防单票爆雷), 非压MDD手段。
    原作者注释"止损无法压MDD"在纯现货框架下成立,
    但本止损定位为风险护栏, 与 struct_def/vol_target 压MDD手段正交。
    阶段2 加入大盘 protective put 后, 单票止损 + 大盘 put 双重保护。

    默认 stop_loss_pct = -0.08 (-8%)
    """
    sl_pct = us_cfg["stop_loss_pct"]
    entry = state.get("entry_price")
    if not entry or entry <= 0 or price is None or price <= 0:
        return None
    # 用乘法避免除法浮点误差(92/100-1 != -0.08, 但 92 <= 100*0.92 精确)
    if price <= entry * (1 + sl_pct):
        return "clear"
    return None


def check_extreme_overvaluation(series, code, t, ovl_cfg):
    """极度高估检测(互联网泡沫级)。

    用户原意: "检测到个股/行业属于极度高估状态, 类似互联网泡沫,
    通过卖出远期期权(1年+)提前规避或套保"。

    两道闸(任一满足=极度高估):
      1. price / MA200 > dev_threshold (相对200周MA翻倍级偏离)
         默认 dev_threshold=2.0 (price >= MA200×2.0)
      2. 26周动量 > mom_threshold (半年涨150%级)
         默认 mom_threshold=1.5

    Returns:
        None - 未高估
        {"reason": "dev"|"mom", "spot": float, "ma200": float, "mom26": float} - 极度高估
    """
    arr = series.get(code)
    if not arr or t < 200 or arr[t] is None or arr[t] <= 0:
        return None
    price = arr[t]
    ma200 = _ma(arr, t, 200)
    if ma200 is None or ma200 <= 0:
        return None
    dev_ratio = price / ma200
    if dev_ratio >= ovl_cfg.get("dev_threshold", 2.0):
        return {"reason": "dev", "spot": price, "ma200": ma200, "mom26": None}
    if t >= 26 and arr[t - 26] not in (None, 0):
        mom26 = price / arr[t - 26] - 1
        if mom26 >= ovl_cfg.get("mom_threshold", 1.5):
            return {"reason": "mom", "spot": price, "ma200": ma200, "mom26": mom26}
    return None


def _ma(vals, i, n):
    win = [v for v in vals[max(0, i - n + 1):i + 1] if v is not None]
    return sum(win) / len(win) if win else None


def regime_of(series, i):
    spy = series.get("SPY")
    if not spy or spy[i] is None:
        return "balance"
    ma = _ma(spy, i, 20)
    if ma is None or ma == 0:
        return "balance"
    dev = (spy[i] / ma - 1) * 100
    return "weak" if dev < -3 else ("bull" if dev > 3 else "balance")


def death_cross_count(series, i):
    if i < 20:
        return 0
    cnt = 0
    for c in BROAD:
        v = series.get(c)
        if not v or v[i] is None:
            continue
        ma20 = _ma(v, i, 20); ma5 = _ma(v, i, 5)
        if ma20 is None or ma5 is None:
            continue
        ma20_prev = _ma(v, i - 1, 20)
        if v[i] < ma20 and ma5 < ma20 and (ma20_prev is None or ma20 < ma20_prev):
            cnt += 1
    return cnt


# ----------------------------------------------------------------- 选股
def select_baseline(series, i, universe, top_n=10):
    """52周动量 TopN 等权 (baseline / PR#5 原数)。"""
    scored = []
    for c in universe:
        arr = series.get(c)
        if not arr or i < WARMUP or arr[i] is None or arr[i - WARMUP] in (None, 0):
            continue
        scored.append((arr[i] / arr[i - WARMUP] - 1, c))
    scored.sort(reverse=True)
    return scored[:top_n]


def select_optimized(series, i, universe, top_n=8, trend_gate="ma5", lookback=52,
                      score_mode="mom", theme_div=False, max_per_theme=2,
                      phase_tilt=False, year=None):
    """动量 + 趋势门 + 可选主题解相关(木头姐) + 可选渗透率相位倾斜。
    theme_div: 跨主题分散(限制同主题最多 max_per_theme 只, 降低进攻仓内部相关性, 压回撤)。
    phase_tilt: 动量得分 × 主题渗透率相位乘子(加速1.35/早期1.15/成熟0.80), 木头姐倾斜。
    year: 相位查询年份(回测按年取时变相位); None 用当前。
    返回 [(mom, code), ...] 降序。"""
    scored = []
    for c in universe:
        arr = series.get(c)
        if not arr or i < lookback or arr[i] is None or arr[i - lookback] in (None, 0):
            continue
        mom = arr[i] / arr[i - lookback] - 1
        if trend_gate == "ma5":
            ma5 = _ma(arr, i, 5); ma20 = _ma(arr, i, 20)
            if ma5 is None or ma20 is None or ma5 <= ma20:
                continue
        elif trend_gate == "ma200":
            ma20 = _ma(arr, i, 20); ma200 = _ma(arr, i, 200)
            if ma20 is None or ma200 is None or ma20 <= ma200:
                continue
        score = mom
        if phase_tilt and _us_get_adoption is not None and c in _THEME_MAP:
            try:
                score = mom * _us_get_adoption(_THEME_MAP[c], year=year)["multiplier"]
            except Exception:
                score = mom
        elif score_mode == "risk_adj":
            win = [v for v in arr[max(0, i - lookback + 1):i + 1] if v not in (None, 0)]
            rets = [win[k] / win[k - 1] - 1 for k in range(1, len(win)) if win[k - 1] not in (None, 0)]
            vol = statistics.pstdev(rets) if len(rets) > 1 else 0.0
            score = mom / (vol * (52 ** 0.5)) if vol > 0 else mom
        scored.append((score, mom, c))
    scored.sort(reverse=True)
    # 主题分散(木头姐解相关): 限制同主题最多 max_per_theme 只, 强制跨主题铺开
    if theme_div:
        picked = []; per_theme = {}
        for score, mom, c in scored:
            th = _THEME_MAP.get(c, "__unmapped__")
            if per_theme.get(th, 0) >= max_per_theme:
                continue
            picked.append((mom, c)); per_theme[th] = per_theme.get(th, 0) + 1
            if len(picked) >= top_n:
                break
        return picked
    return [(sm, c) for _, sm, c in scored[:top_n]]


def pick_defense_lowvol(series, i, n=3, exclude=None):
    """动态防御: 从 DEF_CANDIDATES 选近20周波动最低者(低波动=防御属性)。"""
    exclude = exclude or set()
    cand = []
    for c in DEF_CANDIDATES:
        if c in exclude:
            continue
        arr = series.get(c)
        if not arr or i < 20 or arr[i] is None:
            continue
        win = [v for v in arr[max(0, i - 19):i + 1] if v not in (None, 0)]
        rets = [win[k] / win[k - 1] - 1 for k in range(1, len(win)) if win[k - 1] not in (None, 0)]
        if len(rets) < 8:
            continue
        cand.append((statistics.pstdev(rets), c))
    cand.sort()
    return [c for _, c in cand[:n]]


# ----------------------------------------------------------------- 动态股票池
def eligible_universe(series, i):
    """动态池: 剔除指数/工具 + 需满 WARMUP 年历史 + 当前可交易(非 None)。
    新股 IPO 满1年自动入池, 退市(长期 None)自动出池。"""
    out = []
    for c, arr in series.items():
        if c in EXCLUDE:
            continue
        if i < WARMUP or arr[i] is None or arr[i - WARMUP] in (None, 0):
            continue
        out.append(c)
    return out


# ----------------------------------------------------------------- AI 选股层
def ai_mult_deterministic(series, i, code):
    """确定性质量乘数 [0.8,1.2] (可复现, 无前视)。"""
    arr = series.get(code)
    if not arr or i < WARMUP or arr[i] is None or arr[i - WARMUP] in (None, 0):
        return 1.0
    mom = arr[i] / arr[i - WARMUP] - 1
    win = [v for v in arr[max(0, i - WARMUP):i + 1] if v not in (None, 0)]
    rets = [win[k] / win[k - 1] - 1 for k in range(1, len(win)) if win[k - 1] not in (None, 0)]
    vol = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    risk_adj = mom / (vol * (52 ** 0.5)) if vol > 0 else mom
    high = max(win)
    dist_high = arr[i] / high if high else 1.0
    norm_mom = max(-1.0, min(1.0, risk_adj / 1.0))
    norm_high = max(-1.0, min(1.0, (dist_high - 0.85) / 0.15))
    comp = 0.6 * norm_mom + 0.4 * norm_high
    return max(0.8, min(1.2, 1.0 + 0.2 * comp))


def ai_mult_via_llm(series, i, scored, cfg):
    """真正调用 ai_score.augment 取乘数(需 LLM 配置; 否则 pass-through=1.0)。"""
    try:
        import ai_score
    except Exception as e:
        print(f"  [ai_score] 模块不可用({e}), 退回确定性乘数")
        return {c: 1.0 for _, c in scored}
    candidates = []
    for mom, c in scored:
        arr = series.get(c) or []
        chg20 = None
        if i >= 4 and arr[i] not in (None, 0) and arr[i - 4] not in (None, 0):
            chg20 = (arr[i] / arr[i - 4] - 1) * 100
        candidates.append({
            "code": c, "name": c, "industry": "us",
            "final_score": round(mom, 4), "chg20": round(chg20, 1) if chg20 is not None else None,
        })
    augmented = ai_score.augment(candidates, cfg, tag="us_offensive")
    return {d["code"]: d.get("ai_multiplier", 1.0) for d in augmented}


# ----------------------------------------------------------------- 引擎
def run_baseline(series, dates, use_ai, cfg=None):
    """v6.14b 修正逻辑(baseline 控制组): 弱市停车进分红防御篮(去黄金), 季频, 等权 Top10。"""
    universe = [c for c in series if c not in EXCLUDE and c not in DEF_NEW]
    ALLOC = {
        "bull":    {"off": 80, "def": 10, "park": 0,  "cash": 0,  "park_asset": "DIV"},
        "balance": {"off": 60, "def": 20, "park": 0,  "cash": 20, "park_asset": "DIV"},
        "weak":    {"off": 20, "def": 60, "park": 0,  "cash": 0,  "park_asset": "DIV"},
    }
    REBAL = 13; TOP_N = 10
    n = len(dates); nav = 1.0; nav_hist = []; peak = 1.0; mdd = 0.0
    weights = {"__cash__": 1.0}; selected = []; last_rebal = -100; yearly = {}; weak_weeks = 0
    for t in range(n):
        if t > 0 and weights:
            growth = 0.0
            for c, w in weights.items():
                if c == "__cash__":
                    continue
                arr = series.get(c)
                if not arr or arr[t] is None or arr[t - 1] in (None, 0):
                    continue
                growth += w * (arr[t] / arr[t - 1] - 1)
            nav *= (1 + growth); nav_hist.append(nav); peak = max(peak, nav)
            mdd = min(mdd, nav / peak - 1); y = dates[t][:4]
            yearly.setdefault(y, 1.0); yearly[y] *= (1 + growth)
        else:
            nav_hist.append(nav)
        need_rebal = (t == WARMUP) or (t - last_rebal >= REBAL)
        if t >= WARMUP and need_rebal:
            selected = select_baseline(series, t, universe, TOP_N); last_rebal = t
        if t >= WARMUP and selected:
            weak = (regime_of(series, t) == "weak") or (death_cross_count(series, t) >= 3)
            if weak:
                weak_weeks += 1
            a = ALLOC["weak" if weak else regime_of(series, t)]
            tw = {}
            if use_ai and cfg is not None:
                mult_map = ai_mult_via_llm(series, t, selected, cfg)
            elif use_ai:
                mult_map = {c: ai_mult_deterministic(series, t, c) for _, c in selected}
            else:
                mult_map = {c: 1.0 for _, c in selected}
            off_total = a["off"] / 100.0
            msum = sum(mult_map.get(c, 1.0) for _, c in selected) or 1.0
            for _, c in selected:
                tw[c] = off_total * mult_map.get(c, 1.0) / msum
            per_def = a["def"] / 100.0 / len(DEF_NEW)
            for c in DEF_NEW:
                tw[c] = per_def
            if a["park"] > 0:
                if a["park_asset"] == "DIV":   # 分红防御篮(去黄金): 等权 DEF_NEW
                    per = a["park"] / 100.0 / len(DEF_NEW)
                    for c in DEF_NEW:
                        tw[c] = per
                elif a["park_asset"] not in ("__cash__", None):
                    tw[a["park_asset"]] = a["park"] / 100.0
            tw["__cash__"] = (a["cash"] + (a["park"] if a["park_asset"] == "__cash__" else 0)) / 100.0
            tot = sum(tw.values())
            weights = {c: (w / tot if tot > 0 else 0) for c, w in tw.items()} if tot > 0 else {"__cash__": 1.0}
        elif t == WARMUP and not selected:
            weights = {"__cash__": 1.0}
    return finalize(nav, nav_hist, mdd, dates, yearly, n, weak_weeks)


def run_optimized(series, dates, use_ai, cfg, refresh_weeks=4, top_n=3,
                  trend_gate="ma5", lookback=52, alloc=None, rebal=1, lev=1.0,
                  score_mode="mom", theme_div=False, max_per_theme=2,
                  phase_tilt=False, crash_off=80, vol_target=0.0, vol_floor=0.3,
                  struct_def=0.0, gauge="QQQ", us_cfg=None, options_sim=None):
    """美股优化引擎(默认 = 稳健甜点配置, 扫参确定):
    - 进攻占比拉满(bull100/balance95/weak75), 仅 death-cross 重仓现金(替代 GLD 停车)
    - 周频再平衡(对齐 A 股)
    - 动量 Top3 集中(扫参显示 Top3 为稳健最优, Top1 虽更高但 MDD -78% 过脆)
    - 趋势门 MA5>MA20(剔除下行趋势)
    - 52 周动量窗口(扫参稳健胜出)
    - 动态股票池: 月度/季度 re-screen, IPO 满1年自动入池, 退市自动出池
    - 主题解相关(theme_div) + 渗透率相位倾斜(phase_tilt): 木头姐框架, 压进攻仓内部相关性
    - crash_off: death-cross(crash)档进攻占比(其余转现金+分红对冲), 越小越防御、回撤越小
    - vol_target: 波动率目标化(无杠杆下压MDD的唯一有效手段)。用 gauge(默认QQQ, 高beta)
      近20周已实现波动率(年化)作风险温度, 股权敞口 = clip(vol_target/realized, vol_floor, 1)
      × 基准进攻占比。平静牛市 vol低->满仓吃收益; 崩盘 vol飙->敞口自动压到 floor, 削深跌段。
      压掉的敞口 + 防御袖剩余 -> 现金(正确极端防御: 2022长债TLT -28%与成长同跌, 现金/短久期才是对冲)。
      经验证: 事后信号(MA/护栏/止损/广度)均无法压MDD(要么太迟要么鞭梢); 结构性降敞口是唯一路径, 代价是收益。
    trend_gate: 'ma5'(MA5>MA20) | 'ma200'(MA20>MA200) | None。"""
    ALLOC = alloc or {  # 默认: 进攻主导 + 防御小(用户指定); 防御=分红股(非黄金)
        "bull":    {"off": 100, "def": 0,  "cash": 0},
        "balance": {"off": 95,  "def": 5,  "cash": 0},
        "weak":    {"off": 85,  "def": 15, "cash": 0},
        "crash":   {"off": 80,  "def": 15, "cash": 5},   # death_cross>=3; 现金+分红对冲
    }
    # crash 档进攻占比覆盖(压回撤核心杠杆): 其余 def(15)+cash
    ALLOC["crash"] = {"off": crash_off, "def": 15, "cash": 85 - crash_off}
    REBAL = rebal                               # 再平衡周期(周, 默认1=周频, 对齐A股)
    n = len(dates); nav = 1.0; nav_hist = []; peak = 1.0; mdd = 0.0
    weights = {"__cash__": 1.0}; selected = []; last_rebal = -100; yearly = {}
    weak_weeks = 0; crash_weeks = 0; vol_weeks = 0
    last_pool = -100; universe = []; gauge_arr = series.get(gauge) or series.get("SPY")
    # === v6.18 新增: 持仓跟踪 + 止盈止损 + 成本模型 ===
    if us_cfg is None:
        us_cfg = load_us_cfg()
    holdings_state = {}      # {code: {"entry_price": float, "entry_week": int, "weight": float}}
    prev_weights = {}        # 再平衡前权重快照(供成本扣减对照)
    cost_total = 0.0         # 累计成本(滑点)
    tp_count = 0             # 止盈触发次数
    sl_count = 0             # 止损触发次数
    ovl_call_count = 0       # 极度高估卖call次数
    # === v6.18e 新增: 空仓(被行权后顺高位做空, 远期put/short) ===
    # 用户原意: "被行权相当于到了高位, 可以做空远期期权, 又能做多又能做空"
    short_positions = {}     # {code: {"entry_price": float, "entry_week": int, "weight": float, "expiry_week": int}}
    short_pnl_total = 0.0    # 空仓累计盈亏(相对 nav)
    short_count = 0          # 开空仓次数
    # === v6.18c 新增: 阶段2 期权模拟统计 ===
    call_premium_total = 0.0    # covered call 权利金收入(相对 nav)
    call_settle_total = 0.0     # call 被行权的封顶损失(相对 nav, 负值)
    put_cost_total = 0.0        # protective put 权利金成本(相对 nav)
    put_hedge_total = 0.0       # protective put 崩盘对冲收益(相对 nav)
    # === v6.18d 新增: 被行权后冷却期(防止立即重建仓循环套利) ===
    # 用户原意: "被行权又不代表不能重新买入" → 可以重新买入, 但需冷却期(默认26周)
    ovl_cooldown = {}           # {code: 冷却到期周}
    # v6.18d: LEAPS call 存活期记录(卖call后52周内不再为该股卖新call, 防换出重建仓循环)
    ovl_call_last = {}          # {code: 上次卖高估call的周}
    for t in range(n):
        # === v6.18 新增: 再平衡前快照权重(供成本扣减对照) ===
        prev_weights = dict(weights)
        if t > 0 and weights:
            growth = 0.0
            for c, w in weights.items():
                if c == "__cash__":
                    continue
                arr = series.get(c)
                if not arr or arr[t] is None or arr[t - 1] in (None, 0):
                    continue
                growth += w * (arr[t] / arr[t - 1] - 1)
            nav *= (1 + growth); nav_hist.append(nav); peak = max(peak, nav)
            mdd = min(mdd, nav / peak - 1); y = dates[t][:4]
            yearly.setdefault(y, 1.0); yearly[y] *= (1 + growth)
        else:
            nav_hist.append(nav)
        # === v6.18 新增: 止盈止损检查(每周, 再平衡前) ===
        if t > WARMUP and holdings_state:
            to_clear = []
            for code, state in list(holdings_state.items()):
                arr = series.get(code)
                if not arr or t >= len(arr) or arr[t] is None or arr[t] <= 0:
                    continue
                price = arr[t]
                # 止盈优先(止盈触发后不再检查止损)
                if check_take_profit(code, state, price, us_cfg) == "clear":
                    if options_sim and not state.get("call_sold"):
                        # 阶段2: 卖 covered call, 收权利金, 不清仓
                        strike = state["entry_price"] * (1 + us_cfg["take_profit_pct"])
                        premium = state["entry_price"] * options_sim["call_premium_rate"]
                        state["call_sold"] = True
                        state["call_strike"] = strike
                        state["call_premium"] = premium
                        state["call_expiry_week"] = t + options_sim["call_dte_weeks"]
                        w = weights.get(code, 0)
                        income = w * premium / price
                        nav *= (1 + income)
                        nav_hist[-1] = nav
                        call_premium_total += income
                        tp_count += 1
                    else:
                        to_clear.append((code, "take_profit"))
                        tp_count += 1
                elif check_stop_loss(code, state, price, us_cfg) == "clear":
                    to_clear.append((code, "stop_loss"))
                    sl_count += 1
            # 执行清仓: 权重转现金, 移除 holdings_state
            if to_clear:
                for code, reason in to_clear:
                    if code in weights:
                        weights["__cash__"] = weights.get("__cash__", 0) + weights[code]
                        del weights[code]
                    if code in holdings_state:
                        del holdings_state[code]
                # 清仓也算换手, 扣成本
                new_w = weights
                turnover = sum(abs(new_w.get(c, 0) - prev_weights.get(c, 0))
                               for c in set(new_w) | set(prev_weights)) / 2.0
                cost = turnover * us_cfg["slippage_bps"] / 10000.0
                nav *= (1 - cost)
                nav_hist[-1] = nav
                cost_total += cost
        # === v6.18d 新增: 极度高估检测 → 卖远期 LEAPS call 套保 ===
        # 用户原意: "检测到极度高估(类似互联网泡沫), 卖远期期权(1年+)提前规避"
        # 与止盈call区别: 止盈call=+50%固定阈值; 高估call=估值触发(动态, 可能在+30%时就卖)
        # strike=spot×1.10(轻度OTM, 高估股波动大权利金更高), dte=52周
        if options_sim and options_sim.get("ovl_enabled") and t > WARMUP and holdings_state:
            ovl_cfg = options_sim
            for code, state in list(holdings_state.items()):
                if state.get("call_sold"):  # 已卖call(止盈或高估), 不重复
                    continue
                # LEAPS 存活期检查: 上次卖call后 dte 周内不再卖(防换出重建仓循环)
                last = ovl_call_last.get(code)
                if last is not None and t - last < options_sim["call_dte_weeks"]:
                    continue
                ovl = check_extreme_overvaluation(series, code, t, ovl_cfg)
                if ovl is None:
                    continue
                price = ovl["spot"]
                # 卖远期call: strike=spot×otm_pct(轻度OTM), 权利金按高估程度加成
                otm = options_sim.get("ovl_call_otm", 0.10)
                strike = price * (1 + otm)
                base_prem = options_sim["call_premium_rate"]
                # 高估股波动更大, 权利金×1.5(实证: 高估股IV更高)
                premium = price * base_prem * options_sim.get("ovl_premium_mult", 1.5)
                state["call_sold"] = True
                state["call_strike"] = strike
                state["call_premium"] = premium
                state["call_expiry_week"] = t + options_sim["call_dte_weeks"]
                state["call_reason"] = "overvaluation"
                ovl_call_last[code] = t  # 记录存活期起点
                w = weights.get(code, 0)
                if w > 0 and price > 0:
                    income = w * premium / price
                    nav *= (1 + income)
                    nav_hist[-1] = nav
                    call_premium_total += income
                    ovl_call_count += 1
        # === v6.18c 新增: call 到期结算(被行权=按strike卖出 / 作废=权利金白赚) ===
        if options_sim and holdings_state:
            for code, state in list(holdings_state.items()):
                if not state.get("call_sold") or state.get("call_settled"):
                    continue
                if t < state.get("call_expiry_week", 0):
                    continue
                arr = series.get(code)
                if not arr or t >= len(arr) or arr[t] is None or arr[t] <= 0:
                    continue
                price = arr[t]; strike = state["call_strike"]
                w = weights.get(code, 0)
                if price >= strike:
                    # 被行权: 按 strike 卖出, 封顶损失 = (strike-price)/price × w
                    # 用 prev_weights 兜底(再平衡可能已换出但 holdings_state 还在)
                    w_eff = w if w > 0 else prev_weights.get(code, 0)
                    settle = w_eff * (strike - price) / price
                    nav *= (1 + settle)
                    nav_hist[-1] = nav
                    call_settle_total += settle
                    if w > 0:
                        weights["__cash__"] = weights.get("__cash__", 0) + w
                        if code in weights: del weights[code]
                    if code in holdings_state: del holdings_state[code]
                    # 被行权后冷却期(=空仓持有期, 期间不重新买入多仓)
                    cd = options_sim.get("ovl_cooldown_weeks", 4)
                    ovl_cooldown[code] = t + cd
                    # === v6.18j: 被行权=高位, 顺势做空【对应行业】指数(非单一TECH) ===
                    # 用户原意: "做空是做空大盘或行业指数, 空个股亏损更大 → 个股属于啥行业空啥行业"
                    # 决策链: 个股行业 → 大行业直接空; 小行业降级到TECH; 无数据 → 配置short_underlying
                    if options_sim.get("short_enabled", False) and w_eff > 0:
                        use_sector = options_sim.get("short_by_sector", True)
                        if use_sector:
                            idx = sector_short_index(code, options_sim, series, t)
                        else:
                            idx = options_sim.get("short_underlying", "TECH_INDEX")
                        idx_arr = series.get(idx)
                        if idx_arr and t < len(idx_arr) and idx_arr[t] and idx_arr[t] > 0:
                            short_w = w_eff * options_sim.get("short_size_ratio", 0.5)
                            short_dte = options_sim.get("short_dte_weeks", 13)
                            # 支持同时空多个行业(不同票被行权不同行业): short_positions[idx]累加权重
                            existing = short_positions.get(idx)
                            if existing:
                                # 同行业新仓位合并: 按权重加权平均重算entry_price(简化但近似)
                                tot_w = existing["weight"] + short_w
                                if tot_w > 0:
                                    avg_p = (existing["entry_price"]*existing["weight"] + idx_arr[t]*short_w) / tot_w
                                    existing["entry_price"] = avg_p
                                    existing["weight"] = tot_w
                                    existing["expiry_week"] = max(existing["expiry_week"], t + short_dte)
                                # 否则保持原仓
                            else:
                                short_positions[idx] = {
                                    "entry_price": idx_arr[t],
                                    "entry_week": t,
                                    "weight": short_w,
                                    "expiry_week": t + short_dte,
                                }
                            short_count += 1
                else:
                    state["call_settled"] = True  # 作废, 股票继续持有
        # === v6.18c 新增: protective put 成本(theta衰减) + 崩盘对冲 ===
        # v6.18d: 双层对冲 = 大盘put(QQQ周跌>5%) + 个股put(个股周跌>15%, 更精准)
        #         用户原意: "增加更多期权, 行业指数期权" → 个股级put替代行业ETF(面板无行业ETF)
        if options_sim:
            eq_w = sum(w for c, w in weights.items() if c != "__cash__")
            if eq_w > 0:
                put_cost = eq_w * options_sim["put_premium_annual"] / 52
                nav *= (1 - put_cost)
                nav_hist[-1] = nav
                put_cost_total += put_cost
                # 第一层: 大盘put(QQQ/SPY 周跌>5%)
                g_arr = series.get(gauge) or series.get("SPY")
                if g_arr and t > 0 and g_arr[t] and g_arr[t-1] and g_arr[t-1] > 0:
                    g_ret = g_arr[t] / g_arr[t-1] - 1
                    if g_ret < -options_sim["put_crash_threshold"]:
                        put_hedge = eq_w * abs(g_ret) * options_sim["put_hedge_ratio"]
                        nav *= (1 + put_hedge)
                        nav_hist[-1] = nav
                        put_hedge_total += put_hedge
                # 第二层: 个股put(个股周跌>15%, 比大盘更精准, 替代行业ETF)
                if options_sim.get("stock_put_enabled"):
                    stock_thresh = options_sim.get("stock_put_crash_threshold", 0.15)
                    stock_hedge_ratio = options_sim.get("stock_put_hedge_ratio", 0.3)
                    stock_put_prem = options_sim.get("stock_put_premium_annual", 0.02)
                    for code, w in list(weights.items()):
                        if code == "__cash__" or w <= 0:
                            continue
                        arr = series.get(code)
                        if not arr or t <= 0 or t >= len(arr) or not arr[t] or not arr[t-1] or arr[t-1] <= 0:
                            continue
                        # 个股put成本(每周theta衰减)
                        s_cost = w * stock_put_prem / 52
                        nav *= (1 - s_cost)
                        nav_hist[-1] = nav
                        put_cost_total += s_cost
                        s_ret = arr[t] / arr[t-1] - 1
                        if s_ret < -stock_thresh:
                            s_hedge = w * abs(s_ret) * stock_hedge_ratio
                            nav *= (1 + s_hedge)
                            nav_hist[-1] = nav
                            put_hedge_total += s_hedge
        # === v6.18e 新增: 空仓 PnL 计算(每周按价格变动结算, 到期平仓) ===
        # 用户原意: "被行权后做空, 又能做多又能做空"
        # 空仓收益 = -weight × (price_t/price_{t-1} - 1)  (价格跌=空仓赚)
        if short_positions and t > 0:
            for code in list(short_positions.keys()):
                pos = short_positions[code]
                arr = series.get(code)
                if not arr or t >= len(arr) or arr[t] is None or arr[t] <= 0:
                    continue
                if t <= 0 or arr[t-1] is None or arr[t-1] <= 0:
                    continue
                price_ret = arr[t] / arr[t-1] - 1
                w = pos["weight"]
                # 空仓 PnL: 价格跌=正收益, 价格涨=亏损
                pnl = -w * price_ret
                nav *= (1 + pnl)
                nav_hist[-1] = nav
                short_pnl_total += pnl
                # 到期平仓
                if t >= pos["expiry_week"]:
                    del short_positions[code]
        # 动态股票池刷新(月度/季度)
        if t >= WARMUP and (t - last_pool >= refresh_weeks or last_pool < 0):
            universe = eligible_universe(series, t); last_pool = t
        need_rebal = (t == WARMUP) or (t - last_rebal >= REBAL)
        if t >= WARMUP and need_rebal:
            selected = select_optimized(series, t, universe, top_n,
                                        trend_gate, lookback, score_mode,
                                        theme_div, max_per_theme, phase_tilt,
                                        year=dates[t][:4]); last_rebal = t
            # v6.18d: 过滤冷却期股票(被行权后 N 周内不再建仓, 防循环套利)
            if ovl_cooldown and selected:
                selected = [(m, c) for m, c in selected
                            if c not in ovl_cooldown or t >= ovl_cooldown[c]]
        if t >= WARMUP and selected:
            dcc = death_cross_count(series, t)
            regime = regime_of(series, t)
            if dcc >= 3:
                key = "crash"; crash_weeks += 1
            elif regime == "weak":
                key = "weak"; weak_weeks += 1
            else:
                key = regime
            a = ALLOC[key]
            # 波动率目标化: 压股权敞口(崩盘 vol 飙升时自动降仓到现金)
            vol_scale = 1.0
            if vol_target > 0 and t >= 20 and gauge_arr is not None:
                rets = []
                for k in range(t - 19, t + 1):
                    if gauge_arr[k] and gauge_arr[k - 1] and gauge_arr[k - 1] > 0:
                        rets.append(gauge_arr[k] / gauge_arr[k - 1] - 1)
                if len(rets) >= 10:
                    rv = statistics.pstdev(rets) * (52 ** 0.5)
                    vol_scale = max(vol_floor, min(1.0, vol_target / rv)) if rv > 0 else 1.0
            if vol_scale < 1.0:
                vol_weeks += 1
            tw = {}
            if use_ai and cfg is not None:
                mult_map = ai_mult_via_llm(series, t, selected, cfg)
            elif use_ai:
                mult_map = {c: ai_mult_deterministic(series, t, c) for _, c in selected}
            else:
                mult_map = {c: 1.0 for _, c in selected}
            # 集中加权: 进攻仓按(质量乘数 × 动量强度^0.5)分配, 赢家权重更高
            # lev = 总杠杆(默认1.0); >1 时进攻仓放大, 现金变负=借入(净杠杆)。防御仓不放大。
            # struct_def = 永久防御袖(现金/分红): 结构性降股权敞口, 是唯一能均匀压每年回撤的手段。
            off_pct = a["off"] * vol_scale * lev
            equity_pct = off_pct * (1.0 - struct_def)
            wts = []
            for mom, c in selected:
                m = mult_map.get(c, 1.0) * max(mom, 0.0) ** 0.5
                wts.append((m, c))
            msum = sum(m for m, _ in wts) or 1.0
            for m, c in wts:
                tw[c] = (equity_pct / 100.0) * m / msum
            # 动态防御(低波动候选 Top3, 小仓) —— 分红相关防御(用户指定, 非黄金)
            def_b = pick_defense_lowvol(series, t, n=3,
                                        exclude={c for _, c in selected})
            if def_b and a["def"] > 0:
                per = a["def"] / 100.0 / len(def_b)
                for c in def_b:
                    tw[c] = per
            # 极端防御(正确): 压掉的股权敞口 + 永久防御袖 + 防御袖剩余 -> 现金。
            # 长债(TLT/IEF)在2022与成长同跌(利率驱动), 非危机对冲; 现金/短久期/分红才是对冲。
            struct_pct = off_pct * struct_def
            cash_frac = (a["cash"] + (a["off"] - off_pct) + struct_pct) / 100.0
            tw["__cash__"] = cash_frac
            weights = {c: w for c, w in tw.items() if w > 0} or {"__cash__": 1.0}
            # === v6.18 新增: 再平衡成本扣减 ===
            if t > 0 and prev_weights:
                turnover = sum(abs(weights.get(c, 0) - prev_weights.get(c, 0))
                               for c in set(weights) | set(prev_weights)) / 2.0
                cost = turnover * us_cfg["slippage_bps"] / 10000.0
                nav *= (1 - cost)
                nav_hist[-1] = nav
                cost_total += cost
            # === v6.18 新增: 持仓状态更新(再平衡后) ===
            for c, w in weights.items():
                if c == "__cash__" or w <= 0:
                    continue
                arr = series.get(c)
                price = arr[t] if arr and t < len(arr) else None
                if price is None or price <= 0:
                    continue
                if c not in holdings_state:
                    holdings_state[c] = {"entry_price": price, "entry_week": t, "weight": w}
                else:
                    old = holdings_state[c]
                    old_w = old["weight"]
                    if w > old_w and old_w > 0:
                        old["entry_price"] = (old["entry_price"] * old_w + price * (w - old_w)) / w
                    old["weight"] = w
            for c in list(holdings_state.keys()):
                if c not in weights:
                    # 再平衡换出: 如果有未结算 call, 按 current price 立即结算
                    state = holdings_state[c]
                    if options_sim and state.get("call_sold") and not state.get("call_settled"):
                        arr = series.get(c)
                        if arr and t < len(arr) and arr[t] and arr[t] > 0:
                            price = arr[t]; strike = state["call_strike"]
                            w = prev_weights.get(c, 0)
                            if price >= strike:
                                settle = w * (strike - price) / price
                                nav *= (1 + settle)
                                nav_hist[-1] = nav
                                call_settle_total += settle
                                # v6.18j: 再平衡换出被行权也做空【对应行业】指数
                                if options_sim.get("short_enabled", False) and w > 0:
                                    use_sector = options_sim.get("short_by_sector", True)
                                    if use_sector:
                                        idx = sector_short_index(c, options_sim, series, t)
                                    else:
                                        idx = options_sim.get("short_underlying", "TECH_INDEX")
                                    idx_arr = series.get(idx)
                                    if idx_arr and t < len(idx_arr) and idx_arr[t] and idx_arr[t] > 0:
                                        short_w = w * options_sim.get("short_size_ratio", 0.5)
                                        short_dte = options_sim.get("short_dte_weeks", 13)
                                        existing = short_positions.get(idx)
                                        if existing:
                                            tot_w = existing["weight"] + short_w
                                            if tot_w > 0:
                                                avg_p = (existing["entry_price"]*existing["weight"] + idx_arr[t]*short_w) / tot_w
                                                existing["entry_price"] = avg_p
                                                existing["weight"] = tot_w
                                                existing["expiry_week"] = max(existing["expiry_week"], t + short_dte)
                                        else:
                                            short_positions[idx] = {
                                                "entry_price": idx_arr[t], "entry_week": t,
                                                "weight": short_w, "expiry_week": t + short_dte,
                                            }
                                        short_count += 1
                                        cd = options_sim.get("ovl_cooldown_weeks", 4)
                                        ovl_cooldown[c] = t + cd
                    del holdings_state[c]
        elif t == WARMUP and not selected:
            weights = {"__cash__": 1.0}
    # === v6.18c 新增: 循环结束后结算未到期 call(按最末周价格判断) ===
    if options_sim:
        for code, state in list(holdings_state.items()):
            if not state.get("call_sold") or state.get("call_settled"):
                continue
            arr = series.get(code)
            if not arr or not arr[-1] or arr[-1] <= 0:
                continue
            price = arr[-1]; strike = state["call_strike"]
            if price >= strike:
                w = weights.get(code, 0) or state.get("weight", 0)
                settle = w * (strike - price) / price
                nav *= (1 + settle)
                nav_hist[-1] = nav
                call_settle_total += settle
                # 循环结束被行权也开空仓(但不再计算 PnL, 仅统计)
                if options_sim.get("short_enabled", True) and w > 0:
                    short_count += 1
    return finalize(nav, nav_hist, mdd, dates, yearly, n, weak_weeks, crash_weeks, 0,
                    cost_total=cost_total, tp_count=tp_count, sl_count=sl_count,
                    call_premium=call_premium_total, call_settle=call_settle_total,
                    put_cost=put_cost_total, put_hedge=put_hedge_total,
                    ovl_call_count=ovl_call_count,
                    short_pnl=short_pnl_total, short_count=short_count)


def finalize(nav, nav_hist, mdd, dates, yearly, n, weak_weeks, crash_weeks=0, guard_weeks=0,
             cost_total=0.0, tp_count=0, sl_count=0,
             call_premium=0.0, call_settle=0.0, put_cost=0.0, put_hedge=0.0,
             ovl_call_count=0, short_pnl=0.0, short_count=0):
    yrs = (n - WARMUP) / 52.0
    cagr = (nav ** (1 / yrs) - 1) * 100 if yrs > 0 else 0
    spy_arr = series_proxy.get("SPY")
    spy_mult = (spy_arr[n - 1] / spy_arr[WARMUP]) if spy_arr and spy_arr[WARMUP] else None
    return nav_hist, {
        "multiple": nav, "cagr": cagr, "mdd": mdd,
        "weak_pct": weak_weeks / max(1, (n - WARMUP)) * 100,
        "crash_pct": crash_weeks / max(1, (n - WARMUP)) * 100,
        "guard_pct": guard_weeks / max(1, (n - WARMUP)) * 100,
        "spy_mult": spy_mult, "yrs": yrs, "yearly": yearly,
        "cost_total": cost_total, "take_profit_count": tp_count, "stop_loss_count": sl_count,
        "call_premium": call_premium, "call_settle": call_settle,
        "put_cost": put_cost, "put_hedge": put_hedge,
        "options_net": call_premium + call_settle - put_cost + put_hedge + short_pnl,
        "ovl_call_count": ovl_call_count,
        "short_pnl": short_pnl, "short_count": short_count,
    }


# series_proxy: finalize 内取 SPY 用(模块级, run_* 前 set)
series_proxy = {}


# ========================================================= AI滚动选参（Live模式核心）
def _mini_window_bt(dates, series, cfg, sim, start_w, end_w, *,
                    short_underlying, short_by_sector, short_dte, short_size, ovl_enabled,
                    track_nav: bool = False):
    """【轻量mini回测】滚动扫描用，和主引擎决策逻辑一致，只求参数相对排名正确。

    track_nav=True 时额外返回每周 NAV 序列(用于OOS盲测算MDD)，向后兼容。
    """
    import copy as _copy
    weights = {"__cash__": 1.0}
    nav_hist = [1.0]
    holdings_state = {}
    ovl_cooldown = {}
    ovl_call_last = {}
    selected_last = -9999
    nav = 1.0
    short_count = 0
    short_positions = {}
    sim_s = dict(sim)
    sim_s["short_underlying"] = short_underlying
    sim_s["short_by_sector"] = short_by_sector
    sim_s["short_dte_weeks"] = short_dte
    sim_s["short_size_ratio"] = short_size
    sim_s["ovl_enabled"] = ovl_enabled
    gauge = sim_s.get("hedge_underlying", "QQQ")
    for t in range(start_w, end_w):
        # 空头到期结算
        for code in list(short_positions.keys()):
            pos = short_positions[code]
            if t < pos["expiry_week"]:
                continue
            arr = series.get(code)
            if not arr or t >= len(arr) or arr[t] is None or not pos["entry_price"]:
                if t >= pos["expiry_week"]: del short_positions[code]
                continue
            ret = arr[t] / pos["entry_price"] - 1
            pnl = pos["weight"] * (-ret)
            nav *= (1 + pnl)
            del short_positions[code]
        # 止盈 covered call
        for code, state in list(holdings_state.items()):
            w = weights.get(code, 0)
            if w <= 0 or state.get("call_sold"):
                continue
            arr = series.get(code)
            if not arr or t >= len(arr) or arr[t] is None or arr[t] <= 0:
                continue
            price = arr[t]
            strike = state.get("entry_price", 0) * (1 + cfg["take_profit_pct"])
            if price >= strike * (1 - 1e-9):
                premium = price * sim_s["call_premium_rate"]
                state["call_sold"] = True
                state["call_strike"] = strike
                state["call_premium"] = premium
                state["call_expiry_week"] = t + sim_s["call_dte_weeks"]
                state["call_reason"] = "tp"
                income = w * premium / price if price > 0 else 0
                nav *= (1 + income)
        # 极度高估主动卖call
        if ovl_enabled:
            for code, state in list(holdings_state.items()):
                if state.get("call_sold"):
                    continue
                last = ovl_call_last.get(code)
                if last is not None and t - last < sim_s["call_dte_weeks"]:
                    continue
                ovl = check_extreme_overvaluation(series, code, t, sim_s)
                if ovl is None:
                    continue
                price = ovl["spot"]
                strike = price * (1 + sim_s.get("ovl_call_otm", 0.10))
                premium = price * sim_s["call_premium_rate"] * sim_s.get("ovl_premium_mult", 1.5)
                state["call_sold"] = True
                state["call_strike"] = strike
                state["call_premium"] = premium
                state["call_expiry_week"] = t + sim_s["call_dte_weeks"]
                state["call_reason"] = "ovl"
                ovl_call_last[code] = t
                w = weights.get(code, 0)
                income = w * premium / price if price > 0 else 0
                nav *= (1 + income)
        # call 到期结算 → 被行权 → 做空
        for code, state in list(holdings_state.items()):
            if not state.get("call_sold") or state.get("call_settled"):
                continue
            if t < state.get("call_expiry_week", 1e18):
                continue
            arr = series.get(code)
            if not arr or t >= len(arr) or arr[t] is None or arr[t] <= 0:
                continue
            price = arr[t]; strike = state["call_strike"]
            w = weights.get(code, 0)
            if price >= strike:
                w_eff = w
                settle = w_eff * (strike - price) / price if price > 0 else 0
                nav *= (1 + settle)
                if w > 0:
                    weights["__cash__"] = weights.get("__cash__", 0) + w
                    if code in weights: del weights[code]
                if code in holdings_state: del holdings_state[code]
                cd = sim_s.get("ovl_cooldown_weeks", 4)
                ovl_cooldown[code] = t + cd
                if sim_s.get("short_enabled", True) and w_eff > 0:
                    if sim_s.get("short_by_sector"):
                        idx = sector_short_index(code, sim_s, series, t)
                    else:
                        idx = sim_s["short_underlying"]
                    idx_arr = series.get(idx)
                    if idx_arr and t < len(idx_arr) and idx_arr[t] and idx_arr[t] > 0:
                        sw = w_eff * short_size
                        short_positions[idx] = {
                            "entry_price": idx_arr[t], "entry_week": t,
                            "weight": sw, "expiry_week": t + short_dte
                        }
                        short_count += 1
            else:
                state["call_settled"] = True
        # put 成本 + 崩盘赔付
        eq_w = sum(w for c, w in weights.items() if c != "__cash__")
        if eq_w > 0:
            put_cost = eq_w * sim_s["put_premium_annual"] / 52
            nav *= (1 - put_cost)
            g_arr = series.get(gauge) or series.get("SPY")
            if g_arr and t > 0 and g_arr[t] and g_arr[t-1] and g_arr[t-1] > 0:
                g_ret = g_arr[t] / g_arr[t-1] - 1
                if g_ret < -sim_s.get("put_crash_threshold", 0.05):
                    nav *= (1 + eq_w * abs(g_ret) * sim_s["put_hedge_ratio"])
            if sim_s.get("stock_put_enabled"):
                for c2, w2 in list(weights.items()):
                    if c2 == "__cash__" or w2 <= 0:
                        continue
                    put_c2 = w2 * sim_s.get("stock_put_premium_annual", 0.02) / 52
                    nav *= (1 - put_c2)
                    a2 = series.get(c2)
                    if a2 and t > 0 and a2[t] and a2[t-1] and a2[t-1] > 0:
                        rr = a2[t] / a2[t-1] - 1
                        if rr < -sim_s.get("stock_put_crash_threshold", 0.15):
                            nav *= (1 + w2 * abs(rr) * sim_s.get("stock_put_hedge_ratio", 0.2))
        # 选股
        t_since = t - selected_last
        if t_since >= 4:
            universe = eligible_universe(series, t)
            uni2 = [c for c in universe if ovl_cooldown.get(c, -1) <= t]
            if len(uni2) < 3: uni2 = universe
            picks = select_optimized(series, t, uni2, top_n=8, trend_gate="ma5",
                                     lookback=52, score_mode="mom", theme_div=True, max_per_theme=2,
                                     phase_tilt=False)
            selected_last = t
            if picks:
                regime = regime_of(series, t)
                dc = death_cross_count(series, t)
                crash = dc >= 3
                if crash: bw = 0.60; dw = 0.20; cw = 0.20
                elif regime == "weak": bw = 0.80; dw = 0.15; cw = 0.05
                else: bw = 0.95; dw = 0.00; cw = 0.05
                def_p = pick_defense_lowvol(series, t, n=3, exclude=set(EXCLUDE))
                new_w = {}
                bpw = bw / len(picks); dpw = dw / len(def_p) if def_p else 0
                for _, c in picks: new_w[c] = new_w.get(c, 0) + bpw
                for c in def_p: new_w[c] = new_w.get(c, 0) + dpw
                new_w["__cash__"] = new_w.get("__cash__", 0) + cw
                for c in list(holdings_state.keys()):
                    if c not in new_w and c != "__cash__":
                        s2 = holdings_state[c]
                        cd_default = sim_s.get("ovl_cooldown_weeks", 4)
                        if s2.get("call_sold") and not s2.get("call_settled"):
                            a2 = series.get(c)
                            if a2 and t < len(a2) and a2[t] and a2[t] > 0:
                                p2 = a2[t]; s2k = s2["call_strike"]
                                pw2 = weights.get(c, 0)
                                if p2 >= s2k and sim_s.get("short_enabled") and pw2 > 0:
                                    settle2 = pw2 * (s2k - p2) / p2
                                    nav *= (1 + settle2)
                                    if sim_s["short_by_sector"]:
                                        idx2 = sector_short_index(c, sim_s, series, t)
                                    else:
                                        idx2 = sim_s["short_underlying"]
                                    a2i = series.get(idx2)
                                    if a2i and t < len(a2i) and a2i[t] and a2i[t] > 0:
                                        sw2 = pw2 * short_size
                                        short_positions[idx2] = {"entry_price": a2i[t], "entry_week": t, "weight": sw2, "expiry_week": t + short_dte}
                                        short_count += 1
                                        ovl_cooldown[c] = t + cd_default
                        del holdings_state[c]
                weights = {c: w for c, w in new_w.items() if w > 0} or {"__cash__": 1.0}
                for c, w in weights.items():
                    if c == "__cash__" or w <= 0:
                        continue
                    a3 = series.get(c)
                    price = a3[t] if a3 and t < len(a3) else None
                    if price is None or price <= 0: continue
                    if c not in holdings_state:
                        holdings_state[c] = {"entry_price": price, "entry_week": t, "weight": w}
                    else:
                        old = holdings_state[c]
                        old_w = old["weight"]
                        if w > old_w and old_w > 0:
                            old["entry_price"] = (old["entry_price"] * old_w + price * (w - old_w)) / w
                        old["weight"] = w
                # 滑点
                turnover = 0.25  # 近似
                nav *= (1 - turnover * cfg["slippage_bps"] / 10000.0)
        if track_nav:
            nav_hist.append(nav)
    return (nav, short_count, nav_hist) if track_nav else (nav, short_count)


def rolling_param_sweep(dates, series, us_cfg, window_weeks=52):
    """【Live模式核心】滚动参数扫描: 过去window_weeks周跑384种参数组合, 返回Top5+模式切换建议。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(root, "strategy_config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            full_cfg = json.load(f)
        sweep_cfg = full_cfg.get("live_recommendations", {}).get("rolling_param_sweep_config", {})
    except Exception:
        sweep_cfg = {}

    curr_sim = us_cfg.get("options_sim", {})
    curr_params = {
        "short_underlying": curr_sim.get("short_underlying", "TECH_INDEX"),
        "short_by_sector": curr_sim.get("short_by_sector", False),
        "short_dte": curr_sim.get("short_dte_weeks", 13),
        "short_size": curr_sim.get("short_size_ratio", 0.5),
        "ovl_enabled": curr_sim.get("ovl_enabled", True),
    }
    su_list = sweep_cfg.get("scan_short_underlying",
        ["TECH_INDEX","QQQ","SOX","SEMI_INDEX","SPY","HEALTH_INDEX","ENERGY_INDEX","INDUSTRIAL_INDEX"])
    dte_list = sweep_cfg.get("scan_short_dte_weeks", [4, 8, 13, 26])
    sz_list = sweep_cfg.get("scan_short_size_ratio", [0.35, 0.5, 0.65])
    ovl_list = sweep_cfg.get("scan_ovl_enabled", [True, False])
    sbs_list = sweep_cfg.get("scan_short_by_sector", [False, True])
    switch_thr = sweep_cfg.get("switch_threshold_multiple", 1.10)
    end_w = len(dates) - 1
    start_w = max(WARMUP, end_w - window_weeks)
    print(f"  窗口: {dates[start_w]} ~ {dates[end_w]} ({end_w-start_w}周) | 组合数: {len(su_list)}×{len(dte_list)}×{len(sz_list)}×{len(ovl_list)}×{len(sbs_list)} = {len(su_list)*len(dte_list)*len(sz_list)*len(ovl_list)*len(sbs_list)}")

    # 当前参数先跑（基线）
    curr_nav, curr_short = _mini_window_bt(dates, series, us_cfg, curr_sim, start_w, end_w,
        short_underlying=curr_params["short_underlying"],
        short_by_sector=curr_params["short_by_sector"],
        short_dte=curr_params["short_dte"],
        short_size=curr_params["short_size"],
        ovl_enabled=curr_params["ovl_enabled"])
    print(f"  当前配置 {curr_params['short_underlying']}/sbs={curr_params['short_by_sector']}/dte={curr_params['short_dte']}/sz={curr_params['short_size']}/ovl={curr_params['ovl_enabled']}: 窗口内 {curr_nav:.2f}x  (做空开仓 {curr_short} 次)")

    results = []
    tot = len(su_list) * len(dte_list) * len(sz_list) * len(ovl_list) * len(sbs_list)
    i = 0
    for su in su_list:
        for dte in dte_list:
            for sz in sz_list:
                for ovl in ovl_list:
                    for sbs in sbs_list:
                        i += 1
                        if (i % 50) == 0:
                            print(f"  进度 {i}/{tot} ...", end="\r", flush=True)
                        try:
                            nav, sc = _mini_window_bt(dates, series, us_cfg, curr_sim, start_w, end_w,
                                short_underlying=su, short_by_sector=sbs, short_dte=dte,
                                short_size=sz, ovl_enabled=ovl)
                            results.append((nav, sc, su, sbs, dte, sz, ovl))
                        except Exception as e:
                            pass  # 某组合数据缺失跳过
    print(f"\n  完成 {len(results)}/{tot} 组")
    results.sort(reverse=True)

    print(f"\n{'='*100}")
    print(f"  Top5 参数组合 (当前配置窗口内 {curr_nav:.2f}x, 切换阈值 {switch_thr}×)")
    print(f"  {'Rank':<5}{'收益×':>8}{'做空#':>6}   {'short_underlying':<18}{'sbs':>4}  {'dte':>4}  {'size':>5}  {'ovl':>4}   领先当前")
    print(f"  {'-'*95}")
    for rank, (nav, sc, su, sbs, dte, sz, ovl) in enumerate(results[:5], 1):
        lead = f"{nav/curr_nav*100-100:>+.1f}%"
        sbs_ = "T" if sbs else "F"
        ovl_ = "T" if ovl else "F"
        marker = "  ★ 建议切换" if (nav / curr_nav) >= switch_thr else ""
        print(f"  {rank:<5}{nav:>8.2f}{sc:>6}   {su:<18}{sbs_:>4}  {dte:>4}w {sz:>5.2f}  {ovl_:>4}   {lead:>7}{marker}")

    best_nav, best_sc, best_su, best_sbs, best_dte, best_sz, best_ovl = results[0]
    print(f"\n=== 滚动选参结论:")
    if (best_nav / curr_nav) >= switch_thr:
        print(f"  ✅ 建议切换 -> short_underlying={best_su}, short_by_sector={best_sbs}, short_dte_weeks={best_dte}, short_size_ratio={best_sz}, ovl_enabled={best_ovl}")
        print(f"     窗口内从 {curr_nav:.2f}x → {best_nav:.2f}x ({(best_nav/curr_nav-1)*100:+.1f}% 提升)")
    else:
        print(f"  ✅ 保持当前配置不动 (最优仅领先 {(best_nav/curr_nav-1)*100:+.1f}%, 未到 {switch_thr*100-100:.0f}% 切换阈值, 避免抖动)")

    # 模式自动识别（tech_bubble / broad_bull / sector_rotation）
    print(f"\n=== AI模式识别建议:")
    # 1) tech_bubble: short TECH 1年能赢short QQQ 50%+, 且 TECH MA200偏离>1.8x
    #    近似: results里TECH dte短 vs QQQ高很多
    tech_ = [r for r in results if r[2] == "TECH_INDEX"]
    qqq_ = [r for r in results if r[2] == "QQQ"]
    if tech_ and qqq_:
        if tech_[0][0] > qqq_[0][0] * 1.5:
            print(f"  🟡 检测到 TECH_BUBBLE 模式: TECH_TOP {tech_[0][0]:.2f}x vs QQQ_TOP {qqq_[0][0]:.2f}x = {tech_[0][0]/qqq_[0][0]:.1f}× 差距 → 建议切 fallback_sets.tech_bubble_mode")
        elif qqq_[0][0] > tech_[0][0] * 1.1:
            # 2) broad_bull: QQQ赢TECH → 典型长牛宽基涨
            print(f"  🟢 检测到 BROAD_BULL_SMOOTH 模式: QQQ_TOP {qqq_[0][0]:.2f}x vs TECH_TOP {tech_[0][0]:.2f}x → 建议切 fallback_sets.broad_bull_smooth_mode")
        else:
            print(f"  ⚪ 无明显Bull/Bubble偏向")
    # 3) sector_rotation: 非科技行业(H/E/I) TOP 组合里 sbs=True 比 sbs=False 显著胜出
    sec_top_true = None
    sec_top_false = None
    for r in results:
        if r[2] in ("HEALTH_INDEX","ENERGY_INDEX","INDUSTRIAL_INDEX","CLEAN_INDEX","CONSUMER_INDEX","FINANCIAL_INDEX"):
            if r[3] is True and sec_top_true is None: sec_top_true = r[0]
            if r[3] is False and sec_top_false is None: sec_top_false = r[0]
    if sec_top_true and sec_top_false and (sec_top_true / sec_top_false) > 1.3:
        print(f"  🔵 检测到 SECTOR_ROTATION 模式: 非科技行业 short_by_sector=True 领先 sbs=False {sec_top_true/sec_top_false-1:+.0%} → 建议开 fallback_sets.sector_rotation_mode")
    else:
        print(f"  ⚪ 非科技行业占比较低，继续保持 short_by_sector=False (当前生产最优)")


# ----------------------------------------------------------------- 主程序
def main():
    global series_proxy
    ap = argparse.ArgumentParser(description="美股真实面板回测 + AI 选股层 (baseline / optimized)")
    ap.add_argument("--mode", choices=["both", "optimized"], default="both")
    ap.add_argument("--refresh", choices=["monthly", "quarterly"], default="monthly",
                    help="动态股票池刷新频率(默认 monthly=4周)")
    ap.add_argument("--with-llm", action="store_true", help="optimized+ai 调用 ai_score.augment")
    ap.add_argument("--no-ai", action="store_true", help="关闭 AI(仅 baseline+optimized)")
    ap.add_argument("--vol-target", type=float, default=0.0,
                    help="防御档波动率目标(年化, 默认0=关闭; >0 崩盘降仓到现金)")
    ap.add_argument("--struct-def", type=float, default=0.0,
                    help="防御档永久现金袖比例(默认0; 0.20≈-38%%MDD@20x, 0.40≈-30%%MDD@11x)")
    ap.add_argument("--lev", type=float, default=1.0,
                    help="净杠杆档总杠杆(默认1.0=无杠杆; >1 冲更高倍数, 放大回撤, 用户默认不用)")
    ap.add_argument("--rolling-sweep", action="store_true",
                    help="AI滚动选参: 跑过去N周参数全扫描, 输出Top5组合+切换建议(实盘每月跑一次)")
    ap.add_argument("--window", type=int, default=52,
                    help="--rolling-sweep 扫描窗口长度(周), 默认52=1年")
    args = ap.parse_args()

    if args.rolling_sweep:
        dates, series = load_panel(PANEL)
        us_cfg = load_us_cfg()
        print(f"=== AI滚动选参: 过去{args.window}周参数扫描 ===")
        rolling_param_sweep(dates, series, us_cfg, args.window)
        return

    use_ai = not args.no_ai
    refresh_weeks = 4 if args.refresh == "monthly" else 13
    cfg = None
    if args.with_llm:
        try:
            import ai_score
            cfg = ai_score.load_config()
            print(f"  [ai_score] enabled={ai_score._is_enabled(cfg)} shadow={cfg.get('ai_overlay',{}).get('shadow_mode')}")
        except Exception as e:
            print(f"  [ai_score] 加载失败({e}), 退回确定性乘数")

    dates, series = load_panel(PANEL)
    series_proxy.clear(); series_proxy.update(series)
    us_cfg = load_us_cfg()
    # 阶段2 期权模拟(LEAPS covered call + protective put)
    opt_sim_cfg = us_cfg.get("options_sim", {})
    options_sim = opt_sim_cfg if opt_sim_cfg.get("enabled", False) else None
    if options_sim:
        print(f"  [options_sim] 开启: call {options_sim['call_premium_rate']*100:.0f}% / "
              f"dte {options_sim['call_dte_weeks']}w / put {options_sim['put_premium_annual']*100:.0f}%年 / "
              f"hedge {options_sim['put_hedge_ratio']} / crash>{options_sim['put_crash_threshold']*100:.0f}%")
    print(f"面板: {os.path.basename(PANEL)} | {dates[0]} ~ {dates[-1]} ({len(dates)}周)")
    print(f"动态池刷新: {args.refresh}({refresh_weeks}周) | 趋势过滤+集中: 开 | AI 选股层: "
          f"{'--with-llm' if (args.with_llm and cfg) else ('确定性质量乘数' if use_ai else '关闭')}\n")

    # baseline (保留 PR#5 原数, 不含 AI 净效应已单列, 此处置 off 等权)
    base_hist, base_st = run_baseline(series, dates, use_ai=False)
    print(f"[baseline ] 期末倍数 {base_st['multiple']:.2f}x | CAGR {base_st['cagr']:.1f}% | "
          f"MDD {base_st['mdd']*100:.1f}% | SPY买入持有 {base_st['spy_mult']:.2f}x")

    # optimized (max, 无杠杆, 无vol目标, 主题解相关max2)
    opt_hist, opt_st = run_optimized(series, dates, use_ai=False, cfg=None,
                                     refresh_weeks=refresh_weeks,
                                     theme_div=True, max_per_theme=2, us_cfg=us_cfg,
                                     options_sim=options_sim)
    print(f"[optimized] 期末倍数 {opt_st['multiple']:.2f}x | CAGR {opt_st['cagr']:.1f}% | "
          f"MDD {opt_st['mdd']*100:.1f}% | 弱市 {opt_st['weak_pct']:.1f}% | crash {opt_st['crash_pct']:.1f}%")

    # optimized-defensive (结构性防御袖 -> 现金, 均匀压每年回撤; 可选叠加波动率目标)
    def_struct = args.struct_def if args.struct_def > 0 else 0.20
    def_hist, def_st = (None, None)
    if def_struct > 0 or args.vol_target > 0:
        def_hist, def_st = run_optimized(series, dates, use_ai=False, cfg=None,
                                         refresh_weeks=refresh_weeks,
                                         theme_div=True, max_per_theme=2,
                                         vol_target=args.vol_target, struct_def=def_struct,
                                         us_cfg=us_cfg, options_sim=options_sim)
        tag = f"结构袖{def_struct*100:.0f}%"
        if args.vol_target > 0:
            tag += f"+volT{args.vol_target}"
        print(f"[opt-def ] 期末倍数 {def_st['multiple']:.2f}x | CAGR {def_st['cagr']:.1f}% | "
              f"MDD {def_st['mdd']*100:.1f}%  ({tag}->现金, 无杠杆)")

    # optimized + AI
    opt_ai_hist, opt_ai_st = (None, None)
    if use_ai:
        opt_ai_hist, opt_ai_st = run_optimized(series, dates, use_ai=True,
                                               cfg=(cfg if args.with_llm else None),
                                               refresh_weeks=refresh_weeks,
                                               theme_div=True, max_per_theme=2,
                                               us_cfg=us_cfg, options_sim=options_sim)
        print(f"[opt+ai  ] 期末倍数 {opt_ai_st['multiple']:.2f}x | CAGR {opt_ai_st['cagr']:.1f}% | "
              f"MDD {opt_ai_st['mdd']*100:.1f}%")

    # 净杠杆档(可选, 默认1.0=无杠杆)
    lev = max(1.0, args.lev)
    lev_hist, lev_st = run_optimized(series, dates, use_ai=False, cfg=None,
                                     refresh_weeks=refresh_weeks,
                                     theme_div=True, max_per_theme=2, lev=lev,
                                     us_cfg=us_cfg, options_sim=options_sim)
    if lev > 1.0:
        print(f"[opt+{lev:.1f}x] 期末倍数 {lev_st['multiple']:.2f}x | CAGR {lev_st['cagr']:.1f}% | "
              f"MDD {lev_st['mdd']*100:.1f}%  (净杠杆, 借入成本未计)")

    print("\n=== 优化引擎净效应(baseline -> optimized, 无杠杆) ===")
    print(f"  收益倍数: {base_st['multiple']:.2f}x -> {opt_st['multiple']:.2f}x  "
          f"({(opt_st['multiple']/base_st['multiple']-1)*100:+.1f}%)")
    print(f"  MDD:      {base_st['mdd']*100:.1f}% -> {opt_st['mdd']*100:.1f}%  "
          f"({(opt_st['mdd']-base_st['mdd'])*100:+.1f}pp)")
    if def_st:
        print(f"\n=== 防御档净效应(optimized -> opt-def, 结构袖{def_struct*100:.0f}%"
              + (f"+波动率目标{args.vol_target}" if args.vol_target > 0 else "") + ") ===")
        print(f"  收益倍数: {opt_st['multiple']:.2f}x -> {def_st['multiple']:.2f}x  "
              f"({(def_st['multiple']/opt_st['multiple']-1)*100:+.1f}%)")
        print(f"  MDD:      {opt_st['mdd']*100:.1f}% -> {def_st['mdd']*100:.1f}%  "
              f"({(def_st['mdd']-opt_st['mdd'])*100:+.1f}pp)")
    if use_ai and opt_ai_st:
        print(f"\n=== AI 选股层净效应(optimized -> opt+ai, 无杠杆) ===")
        print(f"  收益倍数: {opt_st['multiple']:.2f}x -> {opt_ai_st['multiple']:.2f}x  "
              f"({(opt_ai_st['multiple']/opt_st['multiple']-1)*100:+.1f}%)")
        print(f"  MDD:      {opt_st['mdd']*100:.1f}% -> {opt_ai_st['mdd']*100:.1f}%  "
              f"({(opt_ai_st['mdd']-opt_st['mdd'])*100:+.1f}pp)")
    if lev > 1.0:
        print(f"\n=== 净杠杆效应(optimized -> opt+{lev:.1f}x) ===")
        print(f"  收益倍数: {opt_st['multiple']:.2f}x -> {lev_st['multiple']:.2f}x  "
              f"({(lev_st['multiple']/opt_st['multiple']-1)*100:+.1f}%)")
        print(f"  MDD:      {opt_st['mdd']*100:.1f}% -> {lev_st['mdd']*100:.1f}%  "
              f"({(lev_st['mdd']-opt_st['mdd'])*100:+.1f}pp)  ⚠️ 杠杆放大回撤; 借入成本未计")

    print("\n  逐年收益(baseline / optimized" +
          (" / opt-def" if def_st else "") +
          (" / opt+ai" if use_ai and opt_ai_st else "") + "):")
    yrs = sorted(set(base_st['yearly']) | set(opt_st['yearly']) |
                 (set(def_st['yearly']) if def_st else set()) |
                 (set(opt_ai_st['yearly']) if opt_ai_st else set()))
    for y in yrs:
        bv = base_st['yearly'].get(y, 1.0); ov = opt_st['yearly'].get(y, 1.0)
        line = f"    {y}: baseline {(bv-1)*100:+.1f}%  optimized {(ov-1)*100:+.1f}%"
        if def_st:
            dv = def_st['yearly'].get(y, 1.0)
            line += f"  opt-def {(dv-1)*100:+.1f}%"
        if opt_ai_st:
            av = opt_ai_st['yearly'].get(y, 1.0)
            line += f"  opt+ai {(av-1)*100:+.1f}%"
        print(line)

    # 输出 CSV (date, baseline_nav, optimized_nav, [optimized_def_nav], [optimized_ai_nav])
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        cols = ["date", "baseline_nav", "optimized_nav"]
        if def_st:
            cols.append("optimized_def_nav")
        if use_ai and opt_ai_hist:
            cols.append("optimized_ai_nav")
        w.writerow(cols)
        for idx, d in enumerate(dates):
            row = [d, f"{base_hist[idx]:.6f}", f"{opt_hist[idx]:.6f}"]
            if def_st:
                row.append(f"{def_hist[idx]:.6f}")
            if use_ai and opt_ai_hist:
                row.append(f"{opt_ai_hist[idx]:.6f}")
            w.writerow(row)
    print(f"\n  已写出 NAV 曲线: {OUT_CSV}")

    # === v6.18c 对照表: 原版纯动量 vs 现货+止盈 vs 期权模拟 ===
    print("\n" + "=" * 112)
    print("美股回测对照 (原版纯动量 vs 现货+止盈 vs 期权模拟)")
    print("=" * 112)
    us_cfg_off = {"take_profit_pct": 999.0, "stop_loss_pct": -999.0,
                  "slippage_bps": 0, "options": {"enabled": False}}
    us_cfg_spot = {"take_profit_pct": 0.50, "stop_loss_pct": -999.0,
                   "slippage_bps": 3, "options": {"enabled": False}}
    us_cfg_opt = load_us_cfg()
    print(f"{'窗口':<8}{'倍数(原版)':>14}{'倍数(现货+止盈)':>16}{'倍数(期权模拟)':>16}"
          f"{'MDD(原版)':>12}{'MDD(期权)':>12}{'期权净收益':>12}")
    print("-" * 112)
    n_total = len(dates)
    for ny in (3, 5, 10):
        start_idx = max(WARMUP, n_total - ny * 52)
        if start_idx < WARMUP or n_total - start_idx < WARMUP:
            continue
        sub_dates = dates[start_idx:]
        sub_series = {c: arr[start_idx:] for c, arr in series.items()}
        # 原版(纯动量无成本)
        series_proxy.clear(); series_proxy.update(sub_series)
        _, st_off = run_optimized(sub_series, sub_dates, use_ai=False, cfg=None,
                                   theme_div=True, max_per_theme=2, us_cfg=us_cfg_off)
        # 现货+止盈(无期权)
        series_proxy.clear(); series_proxy.update(sub_series)
        _, st_spot = run_optimized(sub_series, sub_dates, use_ai=False, cfg=None,
                                    theme_div=True, max_per_theme=2, us_cfg=us_cfg_spot)
        # 期权模拟
        series_proxy.clear(); series_proxy.update(sub_series)
        _, st_opt = run_optimized(sub_series, sub_dates, use_ai=False, cfg=None,
                                   theme_div=True, max_per_theme=2, us_cfg=us_cfg_opt,
                                   options_sim=options_sim)
        print(f"{ny}y{'':<6}{st_off['multiple']:>13.2f}x{st_spot['multiple']:>15.2f}x"
              f"{st_opt['multiple']:>15.2f}x"
              f"{st_off['mdd']*100:>11.1f}%{st_opt['mdd']*100:>11.1f}%"
              f"{st_opt.get('options_net',0)*100:>+11.1f}%")
    print("-" * 112)
    # 全量期权明细
    series_proxy.clear(); series_proxy.update(series)
    _, st_full = run_optimized(series, dates, use_ai=False, cfg=None,
                                theme_div=True, max_per_theme=2, us_cfg=us_cfg_opt,
                                options_sim=options_sim)
    print(f"\n全量期权明细:")
    print(f"  covered call 权利金收入: +{st_full.get('call_premium',0)*100:.2f}%")
    print(f"  call 被行权封顶损失:     {st_full.get('call_settle',0)*100:.2f}%")
    print(f"  protective put 成本:     -{st_full.get('put_cost',0)*100:.2f}%")
    print(f"  protective put 崩盘对冲: +{st_full.get('put_hedge',0)*100:.2f}%")
    print(f"  空仓做空盈亏(被行权后):  {st_full.get('short_pnl',0)*100:+.2f}% (开仓 {st_full.get('short_count',0)} 次)")
    print(f"  期权净收益:              {st_full.get('options_net',0)*100:+.2f}%")
    print(f"  止盈触发(卖call): {st_full['take_profit_count']} | 高估call: {st_full.get('ovl_call_count',0)} | 止损: {st_full['stop_loss_count']} | 成本: {st_full['cost_total']*100:.2f}%")
    print("=" * 112)


if __name__ == "__main__":
    main()
