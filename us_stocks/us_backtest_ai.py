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
                   倍数 ≈33.7x(≈2×A股16x), 但纯动量高beta -> MDD≈-46%(结构性)。
  3) optimized-defensive(结构性现金袖 --struct-def, 默认20%->现金): 无杠杆下均匀压每年回撤的
                   唯一有效手段。40%袖 -> ≈11x / MDD≈-30%; 可选叠加波动率目标化 --vol-target。
  4) optimized+ai: optimized 进攻仓再叠 ai_score 质量乘数(确定性可复现 / --with-llm 真接线)
  5) optimized+lev(--lev>1, 默认1.0关闭): 净杠杆档, 1.2x→≈52x / 1.3x→≈62x(回撤放大, 借入成本未计)
  注: 用户要求无杠杆(≈34x/MDD-46%); 纯动量MDD无法靠事后信号压, 结构性降敞口(现金袖/波动目标)
      是唯一路径, 代价是收益。"34x且-30%"无杠杆下不可兼得(见 README 7.1 前沿表)。

为什么叫「AI 选股层」:
  ai_score.augment(candidates, cfg, tag) 是 A 股系统通用 AI 加权打分层, 输出 0.8~1.2 质量乘数。
  设计铁律: 回测禁用实时 LLM(前视+不可复现), AI 仅 live shadow。故默认用确定性质量乘数(可复现),
  --with-llm 时真正调用 ai_score.augment(未配 LLM 自动 pass-through=1.0)。

运行:
  python us_backtest_ai.py                       # 五档全跑(确定性 AI; 杠杆档默认1.0不显示)
  python us_backtest_ai.py --mode optimized      # 仅 optimized 两档
  python us_backtest_ai.py --refresh monthly     # 动态池刷新频率(monthly/quarterly, 默认 monthly)
  python us_backtest_ai.py --struct-def 0.40     # 防御档切 40% 现金袖(→~11x / MDD≈-30%)
  python us_backtest_ai.py --with-llm            # optimized+ai 真正调用 ai_score.augment
  python us_backtest_ai.py --no-ai               # 关闭 AI(仅 baseline+optimized+防御档)
  python us_backtest_ai.py --lev 1.3             # 杠杆档用 1.3x(→~62x, 回撤放大, 默认1.0关闭)
输出:
  us_stocks/data/us_nav_ai.csv (date, baseline_nav, optimized_nav, [optimized_def_nav], [optimized_ai_nav])
"""
import os
import csv
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
           "TLT", "IEF", "AGG", "BND", "SHY"}  # 指数/工具/债券: 不进进攻选股(债券仅 crash 对冲)
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
                  struct_def=0.0, gauge="QQQ"):
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
        # 动态股票池刷新(月度/季度)
        if t >= WARMUP and (t - last_pool >= refresh_weeks or last_pool < 0):
            universe = eligible_universe(series, t); last_pool = t
        need_rebal = (t == WARMUP) or (t - last_rebal >= REBAL)
        if t >= WARMUP and need_rebal:
            selected = select_optimized(series, t, universe, top_n,
                                        trend_gate, lookback, score_mode,
                                        theme_div, max_per_theme, phase_tilt,
                                        year=dates[t][:4]); last_rebal = t
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
        elif t == WARMUP and not selected:
            weights = {"__cash__": 1.0}
    return finalize(nav, nav_hist, mdd, dates, yearly, n, weak_weeks, crash_weeks, 0)


def finalize(nav, nav_hist, mdd, dates, yearly, n, weak_weeks, crash_weeks=0, guard_weeks=0):
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
    }


# series_proxy: finalize 内取 SPY 用(模块级, run_* 前 set)
series_proxy = {}


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
                    help="防御档永久现金袖比例(默认0; 0.20≈-38%MDD@20x, 0.40≈-30%MDD@11x)")
    ap.add_argument("--lev", type=float, default=1.0,
                    help="净杠杆档总杠杆(默认1.0=无杠杆; >1 冲更高倍数, 放大回撤, 用户默认不用)")
    args = ap.parse_args()

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
                                     theme_div=True, max_per_theme=2)
    print(f"[optimized] 期末倍数 {opt_st['multiple']:.2f}x | CAGR {opt_st['cagr']:.1f}% | "
          f"MDD {opt_st['mdd']*100:.1f}% | 弱市 {opt_st['weak_pct']:.1f}% | crash {opt_st['crash_pct']:.1f}%")

    # optimized-defensive (结构性防御袖 -> 现金, 均匀压每年回撤; 可选叠加波动率目标)
    def_struct = args.struct_def if args.struct_def > 0 else 0.20
    def_hist, def_st = (None, None)
    if def_struct > 0 or args.vol_target > 0:
        def_hist, def_st = run_optimized(series, dates, use_ai=False, cfg=None,
                                         refresh_weeks=refresh_weeks,
                                         theme_div=True, max_per_theme=2,
                                         vol_target=args.vol_target, struct_def=def_struct)
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
                                               theme_div=True, max_per_theme=2)
        print(f"[opt+ai  ] 期末倍数 {opt_ai_st['multiple']:.2f}x | CAGR {opt_ai_st['cagr']:.1f}% | "
              f"MDD {opt_ai_st['mdd']*100:.1f}%")

    # 净杠杆档(可选, 默认1.0=无杠杆)
    lev = max(1.0, args.lev)
    lev_hist, lev_st = run_optimized(series, dates, use_ai=False, cfg=None,
                                     refresh_weeks=refresh_weeks,
                                     theme_div=True, max_per_theme=2, lev=lev)
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


if __name__ == "__main__":
    main()
