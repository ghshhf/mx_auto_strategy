"""
crypto_adoption.py - 加密篮子定义 (v1.0)

设计目的:
  定义加密回测的候选篮子, 类似 markets/us/us_adoption.py 对美股 US50 的定义.

加密篮子 (Crypto3):
  BTC  - Bitcoin,   数字黄金/市值锚定, 全球第一大加密货币
  ETH  - Ethereum,  智能合约平台, DeFi/NFT/Layer2 基础设施
  OKB  - OKB,       OKX 平台币, 交易所生态代币 (用户指定)

加密 vs 股票的差异:
  - 无行业分类: 三币种分别代表 "价值存储(L1)" / "智能合约(L1)" / "交易所生态(L2应用)"
  - 无 PE/PB: 估值用市值排名 / NTVL / 活跃地址数
  - 7x24 交易: 无涨停跌停, 波动率远高于股票
  - 无送股除权: close 即 adjclose, 不需复权
  - T+0: 可以随时买卖, 再平衡频率可以更高

篮子逻辑:
  防御端: BTC (数字黄金, 波动最低, 大市值锚定)
  进攻端: ETH (技术驱动, DeFi 生态, 中等波动) + OKB (高弹性, 交易所赛道, 高波动)
  与 A 股 "防御蓝筹 + 进攻成长" 同源, 但分类维度不同.

回测时期:
  - 完整期: 三币种公共数据起始 ~ 当前
  - BTC/ETH 对比期: 从 2017-10 起 (ETH 有足够流动性)
  - 含牛熊: 覆盖 2018 熊市 / 2021 牛市 / 2022 崩盘 / 2023-24 复苏
"""

# ========== 篮子定义 ==========

# 防御币种 (类似 A 股蓝筹 / 美股 KO+ABBV)
DEFENSE_COINS = ['BTC']

# 进攻币种 (类似 A 股成长股 / 美股 48 只进攻)
OFFENSE_COINS = ['ETH', 'OKB']

# 全部候选
ALL_COINS = DEFENSE_COINS + OFFENSE_COINS

# 币种元信息
COIN_META = {
    'BTC': {
        'name': 'Bitcoin',
        'role': 'defense',
        'category': 'L1-Value-Store',
        'description': '数字黄金, 市值锚定, 波动最低',
        'max_supply': 21_000_000,
        'launch_year': 2009,
    },
    'ETH': {
        'name': 'Ethereum',
        'role': 'offense',
        'category': 'L1-Smart-Contract',
        'description': '智能合约平台, DeFi/NFT/Layer2 基础设施',
        'max_supply': None,  # 无上限 (但有 EIP-1559 燃烧)
        'launch_year': 2015,
    },
    'OKB': {
        'name': 'OKB',
        'role': 'offense',
        'category': 'Exchange-Token',
        'description': 'OKX 平台币, 交易所生态, 回购销毁',
        'max_supply': None,
        'launch_year': 2018,
    },
}

# ========== 仓位配置 (类似 strategy_config.json 的 REGIME_ALLOC) ==========

# 市况判定: 基于 BTC 的价格与 MA_N 的偏离度
# 加密市场用 BTC 作基准 (类似 A 股用沪深300)
REGIME_ALLOC_CRYPTO = {
    'weak': {
        'defense': 0.60,   # 弱势: 60% BTC (避险)
        'offense': 0.20,   # 20% ETH+OKB (低配进攻)
        'stable': 0.20,    # 20% 现金 (USDT/稳定币)
    },
    'flat': {
        'defense': 0.45,   # 平衡: 45% BTC
        'offense': 0.40,   # 40% ETH+OKB
        'stable': 0.15,     # 15% 现金
    },
    'strong': {
        'defense': 0.30,   # 强势: 30% BTC (降低防御)
        'offense': 0.55,    # 55% ETH+OKB (进攻加码)
        'stable': 0.15,     # 15% 现金
    },
}

# 进攻端内部分配 (ETH vs OKB)
# ETH 更稳, OKB 更弹, 按 6:4 分
OFFENSE_INNER_WEIGHTS = {
    'ETH': 0.60,
    'OKB': 0.40,
}

# ========== 市况判定参数 ==========

REGIME_PARAMS = {
    'ma_window': 10,          # BTC 周线 MA10 (加密波动大, 比A股票MA20短)
    'band_weak': 0.08,        # BTC 跌破 MA10 的 8% -> 弱势 (加密波动大, 带宽更宽)
    'band_strong': 0.08,      # BTC 涨破 MA10 的 8% -> 强势
}


def offense_weights():
    """返回进攻端内部分配权重 {symbol: weight}."""
    return dict(OFFENSE_INNER_WEIGHTS)


def get_coin_info(symbol):
    """返回币种元信息."""
    return COIN_META.get(symbol, {'name': symbol, 'role': 'unknown', 'category': 'unknown'})


if __name__ == '__main__':
    print("=== 加密篮子 Crypto3 ===")
    print(f"  防御: {DEFENSE_COINS}")
    print(f"  进攻: {OFFENSE_COINS}")
    print(f"  全部: {ALL_COINS}")
    print(f"\n  仓位配置:")
    for regime, alloc in REGIME_ALLOC_CRYPTO.items():
        print(f"    {regime}: 防御{alloc['defense']:.0%} + 进攻{alloc['offense']:.0%} + 现金{alloc['stable']:.0%}")
    print(f"\n  进攻内部分配: {OFFENSE_INNER_WEIGHTS}")
    print(f"\n  币种详情:")
    for s in ALL_COINS:
        m = COIN_META[s]
        print(f"    {s} ({m['name']}): {m['description']} [{m['category']}]")
