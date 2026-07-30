"""
us_adoption.py - 美股原生「科技渗透率 / 采用率 S 曲线」引擎
===========================================================
改编自项目 mx_auto_strategy/tech_adoption.py (木头姐 Cathie Wood / ARK 框架)。
将"莱特定律 + 渗透率 S 曲线"逻辑抽成**通用引擎**, 配一份**美股原生**题材相位表,
使进攻仓能按年份自动轮动到"当期加速渗透的热门成长题材"。

相位 -> 权重乘子 (沿用项目 strategy_config.tech_adoption 原值):
  accelerating(加速甜区) 1.35 | early(早期甜区) 1.15 |
  saturating(饱和) 0.65 | mature(成熟) 0.80 | policy/unknown 中性 1.0

用法:
  from us_adoption import offense_weights_for_year
  wt = offense_weights_for_year(2024)   # -> {'NVDA':0.21, 'AMD':0.13, ...}
"""

# ---- 美股原生题材 -> 标的 (US50 篮子: 48 进攻 + KO/ABBV 2 防御 = 50) ----
# 对标 科创50 / 美股50 指数式篮子: 流动性大盘核心为主, 砍掉高波动投机票(鞭梢源)。
THEME_STOCKS = {
    "AI算力":     ["NVDA", "AMD", "AVGO", "PLTR", "ORCL"],
    "半导体":     ["AMAT", "MU", "LRCX", "MRVL", "ASML", "QCOM", "TSM"],
    "CloudSaaS":  ["AMZN", "MSFT", "CRM", "NOW", "DDOG", "NET", "ADBE", "SNOW"],
    "EV新能源":    ["TSLA", "GOOGL"],
    "光伏储能":    ["ENPH", "FSLR", "NEE"],
    "GLP1减肥药":  ["LLY", "NVO", "VRTX", "REGN"],
    "网络安全":    ["CRWD", "ZS", "PANW", "FTNT"],
    "机器人":      ["ISRG", "TER"],
    "Fintech":    ["MA", "PYPL", "COIN", "AXP", "V", "NU"],
    "电商互联网":   ["META", "BABA", "BKNG", "DASH", "SPOT", "MELI", "SE", "PDD", "SHOP"],
    "流媒体娱乐":   ["NFLX"],
    "算力基础设施":  ["EQIX", "VRT"],
    "前沿科技":     ["AAPL", "HOOD"],
}

# ---- 美股原生题材渗透相位 (as_of 2025Q4 视角, 时变) ----
# penetration: 当前渗透率近似 %; phase: early/accelerating/saturating/mature
THEMES = {
    "AI算力":     {"penetration": 35, "phase": "accelerating", "note": "企业GenAI/算力渗透快速提升, 仍处甜区"},
    "半导体":     {"penetration": 22, "phase": "accelerating", "note": "AI驱动国产化/先进制程渗透加速"},
    "CloudSaaS":  {"penetration": 62, "phase": "mature",       "note": "企业云渗透已高, 成熟"},
    "EV新能源":    {"penetration": 50, "phase": "saturating",   "note": "美国EV渗透~10%放缓, 价格战"},
    "光伏储能":    {"penetration": 55, "phase": "mature",       "note": "户用光伏/储能饱和, 利率敏感"},
    "GLP1减肥药":  {"penetration": 12, "phase": "accelerating", "note": "肥胖药渗透极低~1-2%, 爆发前夜->加速"},
    "网络安全":    {"penetration": 45, "phase": "mature",       "note": "云安全渗透较高, 成熟"},
    "机器人":      {"penetration": 5,  "phase": "early",        "note": "人形机器人渗透极低, 早期甜区"},
    "Fintech":    {"penetration": 60, "phase": "mature",        "note": "数字支付渗透高, 成熟"},
    "电商互联网":   {"penetration": 70, "phase": "mature",       "note": "电商/互联网渗透已高, 成熟(含 META 广告复苏)"},
    "流媒体娱乐":   {"penetration": 65, "phase": "mature",       "note": "流媒体饱和/整合, 成熟"},
    "算力基础设施":  {"penetration": 30, "phase": "accelerating", "note": "AI 电力/散热/数据中心基建, 2023起加速"},
    "前沿科技":     {"penetration": 8,  "phase": "early",        "note": "量子/卫星/航天/新银行, 高投机前沿早期"},
}

# ---- 时变相位表 (每个时代当红成长赛道) ----
PHASE_HISTORY = {
    "AI算力":     [(2018, 2022, "early"),        (2023, 2026, "accelerating")],
    "半导体":     [(2019, 2021, "accelerating"), (2022, 2022, "mature"), (2023, 2026, "accelerating")],
    "CloudSaaS":  [(2016, 2020, "accelerating"), (2021, 2026, "mature")],
    "EV新能源":    [(2016, 2021, "accelerating"), (2022, 2026, "saturating")],
    "光伏储能":    [(2020, 2022, "accelerating"), (2023, 2026, "mature")],
    "GLP1减肥药":  [(2021, 2022, "early"),        (2023, 2026, "accelerating")],
    "网络安全":    [(2018, 2022, "accelerating"), (2023, 2026, "mature")],
    "机器人":      [(2023, 2026, "early")],
    "Fintech":    [(2016, 2021, "accelerating"), (2022, 2026, "mature")],
    "电商互联网":   [(2016, 2020, "accelerating"), (2021, 2026, "mature")],
    "流媒体娱乐":   [(2016, 2021, "accelerating"), (2022, 2026, "mature")],
    "算力基础设施":  [(2016, 2022, "mature"),       (2023, 2026, "accelerating")],
    "前沿科技":     [(2016, 2022, "unknown"),       (2023, 2026, "early")],
}

# 乘子 (沿用项目原值)
_PHASE_KEY = {"accelerating":"boost_accelerating","early":"early_boost",
              "saturating":"cut_saturating","mature":"mature_mult"}
_MULT = {"accelerating":1.35,"early":1.15,"saturating":0.65,"mature":0.80,"unknown":1.0}

def _phase_for(theme, year):
    for (s,e,ph) in PHASE_HISTORY.get(theme, []):
        if s <= year <= e: return ph
    return THEMES.get(theme, {}).get("phase", "unknown")

def phase_multiplier(phase):
    return _MULT.get(phase, 1.0)

def get_adoption(theme, year=None):
    """查某题材当年相位与乘子。year=None 用当前视角。"""
    ph = _phase_for(theme, year) if year is not None else THEMES.get(theme,{}).get("phase","unknown")
    info = THEMES.get(theme, {})
    return {"theme":theme,"penetration":info.get("penetration"),"phase":ph,
            "multiplier":phase_multiplier(ph),"note":info.get("note","")}

def offense_weights_for_year(year, valid=None, mode='stock_sum'):
    """
    该年所有题材按相位乘子 -> 美股进攻权重(归一化)。
    valid=可用标的集合(数据齐的, 逐周过滤 pre-IPO)。
    mode:
      'stock_sum'  -- 旧方案: 每标的权重 = Σ(题材乘子/题材内标的数), 跨题材累加。
                      缺陷: 单票题材(如 LLY/TER)被高估, 多票加速题材(如 AI算力)被摊薄。
      'theme_first'-- 题材级先定权(题材权重∝乘子), 题材内等权。更均衡。
      'sweet_only' -- 仅保留甜区(accelerating/early)题材, 题材级定权+题材内等权。
                      最贴近木头姐"只赌早期/加速颠覆, 不碰成熟"的哲学。
    """
    if mode == 'stock_sum':
        wt = {}
        for theme, stocks in THEME_STOCKS.items():
            ad = get_adoption(theme, year=year)
            m = ad["multiplier"]
            if m <= 0: continue
            for s in stocks:
                if valid and s not in valid: continue
                wt[s] = wt.get(s, 0.0) + m/len(stocks)
        tot = sum(wt.values())
        return {s: w/tot for s, w in wt.items()} if tot > 0 else None

    # theme_first / sweet_only 共用: 先算题材权重
    sweet = set()
    for th in THEME_STOCKS:
        ph = get_adoption(th, year=year)["phase"]
        if ph in ("accelerating", "early"): sweet.add(th)
    theme_w = {}
    for theme, stocks in THEME_STOCKS.items():
        if mode == 'sweet_only' and theme not in sweet: continue
        ad = get_adoption(theme, year=year)
        m = ad["multiplier"]
        if m <= 0: continue
        avail_stocks = [s for s in stocks if (not valid or s in valid)]
        if not avail_stocks: continue
        theme_w[theme] = (m, avail_stocks)
    if not theme_w: return None
    tot = sum(v[0] for v in theme_w.values())
    wt = {}
    for theme, (m, stocks) in theme_w.items():
        share = m / tot                      # 题材在进攻仓中的占比
        for s in stocks:
            wt[s] = wt.get(s, 0.0) + share/len(stocks)   # 题材内等权
    return wt

def hot_themes_for_year(year):
    """该年处于甜区(accelerating/early)的题材, 用于诊断。"""
    return [(th, get_adoption(th, year=year)["phase"]) for th in THEME_STOCKS
            if get_adoption(th, year=year)["phase"] in ("accelerating","early")]

def offense_two_positions(year, valid=None, mode='stock_sum', px=None, as_of=None):
    """木头姐框架选出 2 个进攻仓位(对齐 A 股 weekly_theme: 选 Top2 题材, 每题材取权重最高标的)。

    与 A 股 weekly_theme 一致: 木头姐(科技渗透率相位)只**倾斜**进攻主线排序, 不是垄断。
    真实主线由"动量"决定, 相位只做加权:
      - 若提供 px(价格矩阵): 每年用**近12月涨幅 + 板块相对强度**算题材动量,
        甜区题材按 (动量 × 相位乘子) 排序取 Top2 —— 复刻 weekly_theme.scan_industry_momentum 的
        "跟随上一周已证明有资金的方向" + tech_adoption.apply_tilt 的相位倾斜;
      - 若不提供 px(无动量数据): 退回纯相位排序(仍用当年时变相位, 并加同题材连占<=2年限制防永久占坑)。
    """
    phase_mult = {"accelerating": 1.35, "early": 1.15, "mature": 0.8, "saturating": 0.65,
                  "unknown": 1.0, "policy": 1.0}
    # 题材 -> 动量得分(有px时) 或 相位乘子(无px时)
    if px is not None:
        mom = _theme_momentum(year, px, as_of) if as_of is not None else _theme_momentum(year, px)
        # 甜区题材才参与, 否则动量×0
        score = {}
        for th in THEME_STOCKS:
            ph = _phase_for(th, year)
            if ph in ("accelerating", "early"):
                score[th] = max(mom.get(th, 0.0), 0.0) * phase_mult[ph]
            else:
                score[th] = 0.0
        if not any(v > 0 for v in score.values()):
            score = {th: phase_mult[_phase_for(th, year)] for th in THEME_STOCKS}
        ranked = sorted(THEME_STOCKS.keys(), key=lambda th: score[th], reverse=True)
        # as_of 透传(回测用"上年末"动量避免年内前视; 不传则用当年末)
    else:
        phase_rank = {"accelerating": 4, "early": 3, "mature": 2, "saturating": 1, "unknown": 0, "policy": 0}
        sweet = [th for th in THEME_STOCKS if phase_rank.get(_phase_for(th, year), 0) >= 3]
        sweet.sort(key=lambda th: (phase_rank[_phase_for(th, year)],
                                   _theme_total_weight(th, year, valid, mode)), reverse=True)
        # 同题材连占上限, 强制老热点让位
        cap = 2
        chosen_themes = []
        for th in sweet:
            if len(chosen_themes) >= 2:
                break
            if _theme_occupied_recently(th, year, cap, valid, mode) and len(sweet) > 2:
                continue
            chosen_themes.append(th)
        for th in sweet:
            if len(chosen_themes) >= 2:
                break
            if th not in chosen_themes:
                chosen_themes.append(th)
        ranked = chosen_themes

    # 从 ranked 取 Top2 题材, 各选权重最高可用标的(去重)
    picked = []
    for th in ranked:
        if len(picked) >= 2:
            break
        cands = [(s, _stock_w2(th, s, year, valid, mode)) for s in THEME_STOCKS[th]
                 if (not valid or s in valid) and s not in picked]
        cands = [c for c in cands if c[1] > 0]
        if cands:
            picked.append(max(cands, key=lambda x: x[1])[0])
    if len(picked) < 2:
        wt = offense_weights_for_year(year, valid=valid, mode=mode) or {}
        for s, _ in sorted(wt.items(), key=lambda x: -x[1]):
            if s not in picked:
                picked.append(s)
            if len(picked) >= 2:
                break
    return picked[:2]


def _stock_w2(theme, stock, year, valid, mode):
    wt = offense_weights_for_year(year, valid=valid, mode=mode) or {}
    return wt.get(stock, 0.0)


def _theme_momentum(year, px, as_of=None):
    """题材动量 = 该题材成分股"近12月涨幅"与"相对SPY强度"的均值(复刻 weekly_theme 的动量扫描)。
    px: 周线复权价 DataFrame(列=标的, 索引=日期)。as_of: 该年结束日期(默认取该年最后可用行)。"""
    if as_of is None:
        # 取该年最后一行
        yr_rows = px[px.index.year == year]
        if len(yr_rows) == 0:
            # 跨年: 取 <= year-12-31 的最后一行
            yr_rows = px[px.index.year <= year]
        if len(yr_rows) == 0:
            return {}
        as_of = yr_rows.index[-1]
    try:
        i = px.index.get_loc(as_of)
    except Exception:
        i = len(px) - 1
    if i < 52:
        return {}
    win = px.iloc[i - 52: i + 1]
    bench_ret = (px['SPY'].iloc[i] / px['SPY'].iloc[i - 52]) - 1 if 'SPY' in px else 0.0
    mom = {}
    for th, stocks in THEME_STOCKS.items():
        rets = []
        for s in stocks:
            if s not in px.columns:
                continue
            ser = px[s].iloc[i - 52: i + 1]
            ser = ser.dropna()
            if len(ser) < 40:
                continue
            r = ser.iloc[-1] / ser.iloc[0] - 1
            rel = r - bench_ret
            rets.append((r + rel) / 2.0)   # 绝对涨幅 + 相对强度, 各半
        if rets:
            mom[th] = sum(rets) / len(rets)
    return mom


def _theme_total_weight(theme, year, valid, mode):
    wt = offense_weights_for_year(year, valid=valid, mode=mode) or {}
    return sum(wt.get(s, 0.0) for s in THEME_STOCKS[theme] if (not valid or s in valid))

def _theme_occupied_recently(theme, year, cap, valid, mode):
    if cap <= 1:
        return False
    yrs = list(range(year - cap + 1, year))
    if not yrs:
        return False
    return all(_theme_in_sweet_top2(theme, y, valid, mode) for y in yrs)

def _theme_in_sweet_top2(theme, year, valid, mode):
    phase_rank = {"accelerating": 4, "early": 3, "mature": 2, "saturating": 1, "unknown": 0, "policy": 0}
    sweet = [th for th in THEME_STOCKS if phase_rank.get(_phase_for(th, year), 0) >= 3]
    return theme in sweet[:2]
