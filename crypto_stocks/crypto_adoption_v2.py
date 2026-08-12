"""
crypto_adoption_v2.py - 加密 Crypto50 篮子定义 + 木头姐渗透率相位 (V2)
===================================================================

对标 us_stocks/us_adoption.py (美股 US50) + tech_adoption.py (木头姐框架).

篮子构成 (Crypto50):
  - 2 防御代币: BTC (数字黄金), ETH (基础设施)
  - 48 进攻代币: 按 12 个加密赛道分类, 覆盖 L1/L2/DeFi/游戏/AI/存储/隐私/社交等
  - 从 48 进攻中选出 Top N 长期持有 (类似 A 股 weekly_theme 选题材)

木头姐渗透率框架 (加密版):
  - 加密赛道也有 S 曲线: DeFi TVL渗透率 / L2 采用率 / RWA 上链率 等
  - accelerating (加速甜区): L2/AI+加密/模块化区块链
  - early (早期): DePIN/加密社交/意图驱动
  - saturating (饱和): DeFi借贷/DEX/NFT
  - mature (成熟): PoW挖矿/云挖矿/早期ICO模式
  - policy (政策驱动): 稳定币/合规RWA/央行CBDC

四档市况 (扩展自 A 股三档):
  - extreme_weak (极端防御): BTC < MA10*(1-15%), 全部转稳定币
  - weak (防御): BTC < MA10*(1-8%), 重防御+现金
  - flat (中等): MA10 ±8%, 均衡配置
  - strong (进攻): BTC > MA10*(1+8%), 重进攻
"""

# ========== 加密赛道定义 (12 个) ==========

CRYPTO_THEMES = {
    # ---- L1 公链 (基础设施层) ----
    "L1公链": {
        "penetration": 25, "phase": "accelerating", "as_of": "2026Q3",
        "note": "多链生态成熟, ETH L1 + Solana 高性能双雄, 采用率加速",
    },
    # ---- L2 扩容 (当前加速甜区) ----
    "L2扩容": {
        "penetration": 18, "phase": "accelerating", "as_of": "2026Q3",
        "note": "Rollup 渗透率加速, Arbitrum/Optimism/Base/ZK 生态爆发",
    },
    # ---- DeFi (去中心化金融) ----
    "DeFi": {
        "penetration": 12, "phase": "accelerating", "as_of": "2026Q3",
        "note": "DeFi TVL 占传统金融极低, 但增速快, 仍处加速段",
    },
    "DeFi借贷": {
        "penetration": 20, "phase": "saturating", "as_of": "2026Q3",
        "note": "Aave/Compound 渗透率高, 增速放缓",
    },
    "DEX": {
        "penetration": 15, "phase": "saturating", "as_of": "2026Q3",
        "note": "Uniswap/Curve 渗透见顶, 增长放缓",
    },
    # ---- AI+加密 (2024-2026 最热赛道, 加速甜区) ----
    "AI+加密": {
        "penetration": 3, "phase": "accelerating", "as_of": "2026Q3",
        "note": "AI Agent + 去中心化算力 + 验证, 渗透极低但增速爆发",
    },
    # ---- 模块化区块链 ----
    "模块化": {
        "penetration": 8, "phase": "accelerating", "as_of": "2026Q3",
        "note": "Celestia/Dymension 数据可用层, 模块化架构采用加速",
    },
    # ---- 存储/去中心化基础设施 ----
    "DePIN": {
        "penetration": 2, "phase": "early", "as_of": "2026Q3",
        "note": "去中心化物理基础设施, 渗透极低, 爆发前夜",
    },
    "存储": {
        "penetration": 5, "phase": "early", "as_of": "2026Q3",
        "note": "IPFS/Filecoin/Arweave, 去中心化存储采用率极低",
    },
    # ---- 游戏元宇宙 ----
    "GameFi": {
        "penetration": 8, "phase": "saturating", "as_of": "2026Q3",
        "note": "Axie之后回落, 渗透增速放缓, 等下一轮",
    },
    # ---- 隐私 ----
    "隐私": {
        "penetration": 3, "phase": "early", "as_of": "2026Q3",
        "note": "零知识证明应用, 监管合规驱动, 早期",
    },
    # ---- RWA / 稳定币 (政策驱动) ----
    "RWA": {
        "penetration": 1, "phase": "accelerating", "as_of": "2026Q3",
        "note": "现实资产上链, BlackRock BUIDL 基金入场, 加速中",
    },
}

# ========== 时变相位表 (每个时代当红加密赛道) ==========
PHASE_HISTORY = {
    # 2016-2017: ICO 热潮
    "L1公链":   [(2016, 2017, "early"), (2018, 2018, "mature"), (2019, 2020, "accelerating"),
                 (2021, 2021, "accelerating"), (2022, 2022, "saturating"), (2023, 2026, "accelerating")],
    "L2扩容":   [(2020, 2021, "early"), (2022, 2022, "early"), (2023, 2026, "accelerating")],
    "DeFi":     [(2019, 2020, "early"), (2021, 2021, "accelerating"), (2022, 2022, "mature"),
                 (2023, 2026, "accelerating")],
    "DeFi借贷": [(2020, 2021, "accelerating"), (2022, 2026, "saturating")],
    "DEX":      [(2020, 2021, "accelerating"), (2022, 2026, "saturating")],
    "AI+加密":  [(2023, 2024, "early"), (2025, 2026, "accelerating")],
    "模块化":   [(2023, 2024, "early"), (2025, 2026, "accelerating")],
    "DePIN":    [(2024, 2026, "early")],
    "存储":     [(2019, 2021, "early"), (2022, 2026, "early")],
    "GameFi":   [(2021, 2021, "accelerating"), (2022, 2023, "saturating"), (2024, 2026, "saturating")],
    "隐私":     [(2019, 2026, "early")],
    "RWA":      [(2023, 2024, "early"), (2025, 2026, "accelerating")],
}

# ========== 相位乘子 (沿用项目原值) ==========
_PHASE_MULT = {
    "accelerating": 1.35,
    "early": 1.15,
    "saturating": 0.65,
    "mature": 0.80,
    "unknown": 1.0,
    "policy": 1.0,
}


# ========== Crypto50 篮子 (2 防御 + 48 进攻 = 50) ==========

# 防御代币 (2个) - 只有BTC数字黄金 + ETH基础设施; OKB/BNB是平台币属进攻
DEFENSE_COINS = ['BTC', 'ETH']

def defense_weights():
    """防御端内部分配: BTC 数字黄金 60% + ETH 基础设施 40%."""
    return {'BTC': 0.60, 'ETH': 0.40}


# 进攻代币池 (47个, 按 12 赛道分类) - 赛道: [代币列表]
THEME_COINS = {
    "L1公链":  ['SOL', 'ADA', 'AVAX', 'DOT', 'NEAR', 'APT', 'SUI', 'GRAM', 'TRX', 'INJ', 'XLM'],
    "L2扩容":  ['ARB', 'OP', 'POL', 'MANTA', 'STRK'],
    "DeFi":    ['UNI', 'AAVE', 'MKR', 'SNX', 'COMP', 'CRV', '1INCH', 'LDO', 'JOE'],
    "DeFi借贷": ['AAVE', 'COMP', 'CRV'],  # 与 DeFi 重叠, 复用
    "DEX":     ['UNI', 'CRV', '1INCH', 'JUP', 'JOE'],
    "平台币":  ['BNB', 'OKB'],
    "链上永续交易所": ['DYDX', 'GMX'],
    "基础设施": ['LINK', 'ENS', 'API3', 'GRT'],
    "AI+加密": ['FET', 'RENDER', 'TAO', 'AKT'],
    "模块化":  ['TIA'],
    "DePIN":   ['RENDER', 'AKT'],
    "存储":    ['FIL', 'AR'],
    "GameFi":  ['GALA', 'IMX', 'ILV'],
    "隐私":    ['ZEC', 'DASH'],
    "RWA":     ['ONDO', 'CFG', 'POLYX'],
}

# 去重后的进攻代币列表 (48个)
_OFFENSE_SET = set()
for _coins in THEME_COINS.values():
    for c in _coins:
        _OFFENSE_SET.add(c)
OFFENSE_COINS = sorted(_OFFENSE_SET)
# 确保总数
assert len(OFFENSE_COINS) >= 45, f"进攻代币不足 45, 当前 {len(OFFENSE_COINS)}"

ALL_COINS = DEFENSE_COINS + OFFENSE_COINS


# ========== 四档市况仓位配置 ==========

REGIME_ALLOC = {
    'extreme_weak': {
        'defense': 0.20,   # 仅留 20% 防御底仓
        'offense': 0.00,   # 清空进攻
        'stable': 0.80,    # 80% 稳定币 (极端避险)
        'desc': '极端防御: 80%稳定币 + 20%BTC/ETH',
    },
    'weak': {
        'defense': 0.50,   # 50% 防御
        'offense': 0.15,   # 15% 进攻 (5代币各3%)
        'stable': 0.35,    # 35% 稳定币
        'desc': '防御: 50%防御 + 15%进攻 + 35%现金',
    },
    'flat': {
        'defense': 0.35,   # 35% 防御
        'offense': 0.40,   # 40% 进攻 (5代币各8%)
        'stable': 0.25,    # 25% 稳定币
        'desc': '中等: 35%防御 + 40%进攻 + 25%现金',
    },
    'strong': {
        'defense': 0.20,   # 20% 防御 (降到最低)
        'offense': 0.65,   # 65% 进攻 (5代币各13%)
        'stable': 0.15,    # 15% 稳定币
        'desc': '进攻: 20%防御 + 65%进攻 + 15%现金',
    },
}

# 市况判定参数
REGIME_PARAMS = {
    'ma_window': 10,
    'band_extreme': 0.15,   # 偏离 > 15% -> 极端防御
    'band_weak': 0.08,      # 偏离 > 8%  -> 防御
    'band_strong': 0.08,    # 偏离 > 8%  -> 进攻
}


# ========== 渗透率框架函数 ==========

def _phase_for(theme, year):
    """查时变相位表."""
    hist = PHASE_HISTORY.get(theme, [])
    for (s, e, ph) in hist:
        if s <= year <= e:
            return ph
    return CRYPTO_THEMES.get(theme, {}).get("phase", "unknown")


def phase_multiplier(phase):
    """phase -> 权重乘子."""
    return _PHASE_MULT.get(phase, 1.0)


def get_adoption(theme, year=None):
    """查某赛道当年相位与乘子."""
    ph = _phase_for(theme, year) if year is not None else CRYPTO_THEMES.get(theme, {}).get("phase", "unknown")
    info = CRYPTO_THEMES.get(theme, {})
    return {
        "theme": theme, "penetration": info.get("penetration"),
        "phase": ph, "multiplier": phase_multiplier(ph),
        "note": info.get("note", ""),
    }


def hot_themes_for_year(year):
    """该年处于甜区 (accelerating/early) 的赛道."""
    return [th for th in THEME_COINS
            if get_adoption(th, year=year)["phase"] in ("accelerating", "early")]


def offense_weights_for_year(year, valid=None, mode='theme_first', norm='avail'):
    """
    该年所有进攻代币按赛道相位乘子 -> 权重 (归一化).
    复刻 us_adoption.py 的 offense_weights_for_year.

    norm='avail' (默认, 原版):
        仅统计「有可用币的主题」, 分母=这些主题相位和; 每币除「可用币数」。
        → 删/加币会触发剩余币重归一化, 改变选股综合分(选股对池子敏感)。
    norm='fixed' (稳健选股):
        分母=全部活跃主题(相位>0)的相位和(固定, 不随可用币变化);
        每币除「主题规范币数」(THEME_COINS 原始长度, 固定)。
        → 剩余币分数只取决于自身叙事相位+动量, 与池中还剩几个兄弟币无关;
          选股对删/加币不敏感(防清理池子时的分数漂移)。
    """
    if mode == 'theme_first':
        # 主题相位权重(仅依赖叙事, 与池子无关)
        theme_mult = {}
        for th in THEME_COINS:
            m = get_adoption(th, year=year)["multiplier"]
            if m > 0:
                theme_mult[th] = m
        if not theme_mult:
            return None
        if norm == 'fixed':
            tot = sum(theme_mult.values())          # 固定分母: 不随可用币变化
            wt = {}
            for theme, m in theme_mult.items():
                share = m / tot
                csz = len(THEME_COINS[theme])         # 规范币数(固定)
                if csz <= 0:
                    continue
                for c in THEME_COINS[theme]:
                    if valid and c not in valid:
                        continue
                    wt[c] = wt.get(c, 0.0) + share / csz
            return wt
        # 原版 avail: 仅统计有可用币的主题, 每币除可用币数
        theme_w = {}
        for theme, m in theme_mult.items():
            avail = [c for c in THEME_COINS[theme] if (not valid or c in valid)]
            if not avail:
                continue
            theme_w[theme] = (m, avail)
        if not theme_w:
            return None
        tot = sum(v[0] for v in theme_w.values())
        wt = {}
        for theme, (m, coins) in theme_w.items():
            share = m / tot
            for c in coins:
                wt[c] = wt.get(c, 0.0) + share / len(coins)
        return wt
    else:
        # stock_sum 模式 (旧方案)
        wt = {}
        for theme, coins in THEME_COINS.items():
            ad = get_adoption(theme, year=year)
            m = ad["multiplier"]
            if m <= 0: continue
            for c in coins:
                if valid and c not in valid: continue
                wt[c] = wt.get(c, 0.0) + m / len(coins)
        tot = sum(wt.values())
        return {s: w / tot for s, w in wt.items()} if tot > 0 else None


def offense_top_n(year, n=5, valid=None, px=None, as_of=None, phase=None, return_scores=False, norm='avail'):
    """
    从进攻池选出 Top N 代币 (默认5).
    逻辑: 甜区赛道动量 × 相位乘子 排序 -> Top N.
    复刻 us_adoption.py 的 offense_two_positions (但选5个而非2个).

    phase (优化4 分阶段选币):
      - 'accumulation' / 'pre_halving': 赛道相位优先 (70%相位 + 30%动量)
        → 熊市筑底/减半预热期, 选赛道叙事强的币, 动量信号噪音大
      - 'euphoria': 动量优先 (30%相位 + 70%动量)
        → 牛市狂热期, 跟随资金流向, 动量最强的币最可能继续涨
      - 其他/None: 均衡 (原版逻辑, 相位基础分30% + 动量加权)

    return_scores=True 时返回 (picked_list, scored_dict):
      scored_dict 含全部候选币的「赛道相位×动量」综合分, 供 _build_target
      做分数加权(替代朴素等权)使用; 默认 False 维持原 list 返回以兼容既有调用。
    """
    # 1. 获取该年赛道权重
    wt = offense_weights_for_year(year, valid=valid, mode='theme_first', norm=norm)
    if not wt:
        return ([], {}) if return_scores else []

    # 默认(无价格/短数据): 综合分 = 赛道相位权重
    scored = dict(wt)
    picked = sorted(wt, key=wt.get, reverse=True)

    # 2. 有价格数据则叠加动量, 重算综合分
    if px is not None and len(px) > 52:
        mom = {}
        bench = 'BTC'
        idx = None
        if as_of is not None:
            try:
                idx = px.index.get_loc(as_of)
            except Exception:
                idx = len(px) - 1
        else:
            yr_rows = px[px.index.year == year]
            idx = px.index.get_loc(yr_rows.index[-1]) if len(yr_rows) > 0 else len(px) - 1

        if idx is not None and idx >= 52:
            bench_ret = (px[bench].iloc[idx] / px[bench].iloc[idx - 52]) - 1 if bench in px.columns else 0
            for c in wt:
                if c in px.columns:
                    ser = px[c].iloc[idx - 52: idx + 1].dropna()
                    if len(ser) >= 40:
                        r = ser.iloc[-1] / ser.iloc[0] - 1
                        rel = r - bench_ret
                        mom[c] = (r + rel) / 2.0

            # 分阶段选币: 根据减半周期相位调整相位/动量权重(优化4)
            if phase in ('accumulation', 'pre_halving'):
                # 赛道相位优先: 熊市筑底/减半预热, 动量噪音大, 信赛道叙事
                phase_ratio, mom_ratio = 0.7, 0.3
            elif phase == 'euphoria':
                # 动量优先 + 解耦赛道权重: 牛市狂热期, 冷门赛道也可能涨最猛
                # 裸动量(不乘w)占主导, 赛道权重仅作小幅加权
                phase_ratio, mom_ratio = 0.2, 0.8
            else:
                # 均衡(原版): 相位基础分 + 动量加权
                phase_ratio, mom_ratio = 0.3, 1.0
            scored = {}
            for c, w in wt.items():
                m = mom.get(c, 0.0)
                if phase == 'euphoria':
                    # 裸动量 * 0.8 + 赛道权重 * 0.2 (动量不被赛道权重压制)
                    scored[c] = max(m, 0.0) * mom_ratio + w * phase_ratio
                else:
                    scored[c] = w * phase_ratio + max(m, 0.0) * w * mom_ratio
            picked = sorted(scored, key=scored.get, reverse=True)

    # 3. 按 valid 过滤 + 取 Top N
    if valid:
        picked = [c for c in picked if c in valid]
    picked = picked[:n]

    if return_scores:
        return picked, scored
    return picked


def detect_regime(btc_price, btc_ma, params=None):
    """四档市况判定."""
    if params is None:
        params = REGIME_PARAMS
    if btc_ma == 0 or btc_price == 0:
        return 'flat'
    dev = (btc_price - btc_ma) / btc_ma
    if dev < -params['band_extreme']:
        return 'extreme_weak'
    elif dev < -params['band_weak']:
        return 'weak'
    elif dev > params['band_strong']:
        return 'strong'
    else:
        return 'flat'


# ========== 代币元信息 ==========
COIN_META = {
    # 防御
    'BTC': {'name': 'Bitcoin', 'role': 'defense', 'theme': 'L1公链', 'launch': 2009},
    'ETH': {'name': 'Ethereum', 'role': 'defense', 'theme': 'L1公链', 'launch': 2015},
    'OKB': {'name': 'OKB', 'role': 'offense', 'theme': '平台币', 'launch': 2018},
    # L1
    'SOL': {'name': 'Solana', 'role': 'offense', 'theme': 'L1公链', 'launch': 2020},
    'ADA': {'name': 'Cardano', 'role': 'offense', 'theme': 'L1公链', 'launch': 2017},
    'AVAX': {'name': 'Avalanche', 'role': 'offense', 'theme': 'L1公链', 'launch': 2020},
    'DOT': {'name': 'Polkadot', 'role': 'offense', 'theme': 'L1公链', 'launch': 2020},
    'NEAR': {'name': 'NEAR Protocol', 'role': 'offense', 'theme': 'L1公链', 'launch': 2020},
    'APT': {'name': 'Aptos', 'role': 'offense', 'theme': 'L1公链', 'launch': 2022},
    'SUI': {'name': 'Sui', 'role': 'offense', 'theme': 'L1公链', 'launch': 2023},
    # 2026-06-15 TON(Telegram Open Network 原生代币 Toncoin) 经社区投票(81.22%)更名为 Gram(GRAM),
    # 区块链仍叫 The Open Network, 代币 1:1 无迁移/无新合约. Binance 现货对 TONUSDT->GRAMUSDT.
    'GRAM': {'name': 'Gram', 'role': 'offense', 'theme': 'L1公链', 'launch': 2018},
    'TRX': {'name': 'TRON', 'role': 'offense', 'theme': 'L1公链', 'launch': 2017},
    'INJ': {'name': 'Injective', 'role': 'offense', 'theme': 'L1公链', 'launch': 2021},
    'XLM': {'name': 'Stellar', 'role': 'offense', 'theme': 'L1公链', 'launch': 2014},
    # L2
    'ARB': {'name': 'Arbitrum', 'role': 'offense', 'theme': 'L2扩容', 'launch': 2021},
    'OP': {'name': 'Optimism', 'role': 'offense', 'theme': 'L2扩容', 'launch': 2021},
    'POL':   {'name': 'Polygon (POL)', 'role': 'offense', 'theme': 'L2扩容', 'launch': 2017},
    'MANTA': {'name': 'Manta', 'role': 'offense', 'theme': 'L2扩容', 'launch': 2024},
    'STRK': {'name': 'StarkNet', 'role': 'offense', 'theme': 'L2扩容', 'launch': 2024},
    # DeFi
    'UNI': {'name': 'Uniswap', 'role': 'offense', 'theme': 'DeFi', 'launch': 2020},
    'LINK': {'name': 'Chainlink', 'role': 'offense', 'theme': '基础设施', 'launch': 2017},
    'AAVE': {'name': 'Aave', 'role': 'offense', 'theme': 'DeFi', 'launch': 2020},
    'MKR': {'name': 'Maker', 'role': 'offense', 'theme': 'DeFi', 'launch': 2017},
    'SNX': {'name': 'Synthetix', 'role': 'offense', 'theme': 'DeFi', 'launch': 2018},
    'COMP': {'name': 'Compound', 'role': 'offense', 'theme': 'DeFi', 'launch': 2018},
    'CRV': {'name': 'Curve', 'role': 'offense', 'theme': 'DeFi', 'launch': 2020},
    'DYDX': {'name': 'dYdX', 'role': 'offense', 'theme': '链上永续交易所', 'launch': 2021},
    '1INCH': {'name': '1inch', 'role': 'offense', 'theme': 'DeFi', 'launch': 2020},
    'ENS': {'name': 'ENS', 'role': 'offense', 'theme': '基础设施', 'launch': 2021},
    'LDO': {'name': 'Lido', 'role': 'offense', 'theme': 'DeFi', 'launch': 2020},
    'JUP': {'name': 'Jupiter', 'role': 'offense', 'theme': 'DeFi', 'launch': 2024},
    'JOE': {'name': 'Trader Joe (JOE)', 'role': 'offense', 'theme': 'DeFi', 'launch': 2021},
    # AI
    'FET': {'name': 'ASI / Fetch.ai', 'role': 'offense', 'theme': 'AI+加密', 'launch': 2019},
    'RENDER': {'name': 'Render', 'role': 'offense', 'theme': 'AI+加密', 'launch': 2020},
    'TAO': {'name': 'Bittensor', 'role': 'offense', 'theme': 'AI+加密', 'launch': 2023},
    'AKT': {'name': 'Akash', 'role': 'offense', 'theme': 'AI+加密', 'launch': 2021},
    # 模块化
    'TIA': {'name': 'Celestia', 'role': 'offense', 'theme': '模块化', 'launch': 2023},
    # DePIN
    # 存储
    'FIL': {'name': 'Filecoin', 'role': 'offense', 'theme': '存储', 'launch': 2020},
    'AR': {'name': 'Arweave', 'role': 'offense', 'theme': '存储', 'launch': 2020},
    # GameFi
    'GALA': {'name': 'Gala Games', 'role': 'offense', 'theme': 'GameFi', 'launch': 2020},
    'IMX': {'name': 'Immutable', 'role': 'offense', 'theme': 'GameFi', 'launch': 2021},
    'ILV': {'name': 'Illuvium', 'role': 'offense', 'theme': 'GameFi', 'launch': 2021},
    # 隐私
    'ZEC': {'name': 'Zcash', 'role': 'offense', 'theme': '隐私', 'launch': 2016},
    'DASH': {'name': 'Dash', 'role': 'offense', 'theme': '隐私', 'launch': 2014},
    # RWA
    'ONDO': {'name': 'Ondo', 'role': 'offense', 'theme': 'RWA', 'launch': 2024},
    'CFG': {'name': 'Centrifuge', 'role': 'offense', 'theme': 'RWA', 'launch': 2021},
    'POLYX': {'name': 'Polymesh', 'role': 'offense', 'theme': 'RWA', 'launch': 2022},
    # 平台币 / 链上永续交易所 / 基础设施 (2026-08-11 扩充)
    'BNB': {'name': 'BNB', 'role': 'offense', 'theme': '平台币', 'launch': 2017},
    'GMX': {'name': 'GMX', 'role': 'offense', 'theme': '链上永续交易所', 'launch': 2021},
    'API3': {'name': 'API3', 'role': 'offense', 'theme': '基础设施', 'launch': 2020},
    'GRT': {'name': 'The Graph', 'role': 'offense', 'theme': '基础设施', 'launch': 2020},
}


if __name__ == '__main__':
    print(f"=== Crypto50 篮子 (V2) ===")
    print(f"  防御 ({len(DEFENSE_COINS)}): {DEFENSE_COINS}")
    print(f"  进攻 ({len(OFFENSE_COINS)}): {OFFENSE_COINS[:10]}... 共{len(OFFENSE_COINS)}个")
    print(f"  总计: {len(DEFENSE_COINS) + len(OFFENSE_COINS)}")
    print(f"\n  四档市况:")
    for r, a in REGIME_ALLOC.items():
        print(f"    {r:<16} 防{a['defense']:.0%} + 进{a['offense']:.0%} + 现{a['stable']:.0%} | {a['desc']}")
    print(f"\n  赛道相位 (2026视角):")
    for th, info in CRYPTO_THEMES.items():
        print(f"    {th:<10} 渗透{info['penetration']:>3}%  {info['phase']:<14} ×{phase_multiplier(info['phase']):.2f}  {info['note']}")
    print(f"\n  2024年甜区赛道: {hot_themes_for_year(2024)}")
    print(f"  2025年甜区赛道: {hot_themes_for_year(2025)}")
