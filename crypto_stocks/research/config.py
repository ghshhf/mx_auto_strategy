"""机构研报子模块的静态配置：白名单、同义映射、分桶常量、代币别名。

绝不从外部加载；纯常量，可任意 import。
"""
from __future__ import annotations

# ──────────────────────────────────────────────────────
# 1. 机构白名单（3级）—— 只有在名单内的机构预测才默认收录
# ──────────────────────────────────────────────────────
TIER1_TRADITIONAL: list[str] = [
    "Standard Chartered", "JPMorgan", "Goldman Sachs", "Morgan Stanley",
    "ARK Invest", "Fidelity", "BlackRock", "VanEck", "Deutsche Bank",
    "Citi", "Bank of America", "UBS",
]

TIER2_EXCHANGE_NATIVE: list[str] = [
    "Galaxy Digital", "Binance Research", "OKX Insights",
    "Coinbase Research", "Kraken Intelligence",
    "Glassnode", "Messari", "Delphi Digital",
]

TIER3_MEDIA_MENTION: list[str] = [
    "Bernstein", "Matrixport", "Fundstrat",
    "Cantor Fitzgerald", "Pantera Capital",
]

TRACKED_INSTITUTIONS: list[str] = TIER1_TRADITIONAL + TIER2_EXCHANGE_NATIVE + TIER3_MEDIA_MENTION

def tier_of(institution: str) -> str:
    """返回 'tier1' / 'tier2' / 'tier3'；不在白名单返回 'unknown'（默认过滤）。"""
    if institution in TIER1_TRADITIONAL:
        return "tier1"
    if institution in TIER2_EXCHANGE_NATIVE:
        return "tier2"
    if institution in TIER3_MEDIA_MENTION:
        return "tier3"
    return "unknown"

# ──────────────────────────────────────────────────────
# 2. 机构同义映射（媒体常写简称；解析时先归一化）
# ──────────────────────────────────────────────────────
INSTITUTION_SYNONYMS: dict[str, str] = {
    "渣打": "Standard Chartered", "Standard Chartered Bank": "Standard Chartered",
    "SCB": "Standard Chartered",
    "摩根大通": "JPMorgan", "JPM": "JPMorgan", "JP Morgan": "JPMorgan",
    "高盛": "Goldman Sachs", "GS": "Goldman Sachs",
    "大摩": "Morgan Stanley", "Morgan Stanley Wealth": "Morgan Stanley",
    "方舟": "ARK Invest", "Cathie Wood": "ARK Invest", "Ark Invest": "ARK Invest",
    "富达": "Fidelity", "Fidelity Investments": "Fidelity",
    "贝莱德": "BlackRock", "Blackrock": "BlackRock", "iShares": "BlackRock",
    "德银": "Deutsche Bank", "DB": "Deutsche Bank",
    "花旗": "Citi", "Citigroup": "Citi",
    "美银": "Bank of America", "BofA": "Bank of America",
    "瑞银": "UBS", "UBS Group": "UBS",
    "Galaxy": "Galaxy Digital", "Galaxy Research": "Galaxy Digital",
    "Binance": "Binance Research", "币安研究院": "Binance Research",
    "OKX Research": "OKX Insights", "OKX": "OKX Insights", "欧易": "OKX Insights",
    "Coinbase Institute": "Coinbase Research", "Coinbase": "Coinbase Research",
    "Kraken": "Kraken Intelligence",
    "Alliance Bernstein": "Bernstein",
    "Tom Lee": "Fundstrat", "Fundstrat Global Advisors": "Fundstrat",
}

def normalize_institution(raw_name: str) -> str:
    """同义归一化：先 trim + 查 SYNONYMS → 再查白名单精确匹配。不命中则原样返回。"""
    if not raw_name:
        return ""
    name = raw_name.strip()
    mapped = INSTITUTION_SYNONYMS.get(name)
    if mapped:
        return mapped
    if name in TRACKED_INSTITUTIONS:
        return name
    lower_map = {k.lower(): v for k, v in INSTITUTION_SYNONYMS.items()}
    return lower_map.get(name.lower(), name)

# ──────────────────────────────────────────────────────
# 3. 代币别名映射（中文/小写 → 统一大写简写）—— 覆盖40个篮子币
# ──────────────────────────────────────────────────────
COIN_ALIASES: dict[str, str] = {
    "比特币": "BTC", "btc": "BTC", "BITCOIN": "BTC", "Bitcoin": "BTC",
    "以太坊": "ETH", "eth": "ETH", "Ethereum": "ETH", "ETHEREUM": "ETH",
    "以太": "ETH",
    "sol": "SOL", "SOLANA": "SOL", "Solana": "SOL",
    "币安币": "BNB", "bnb": "BNB",
    "瑞波币": "XRP", "xrp": "XRP",
    "卡尔达诺": "ADA", "ada": "ADA",
    "狗狗币": "DOGE", "doge": "DOGE",
    "dot": "DOT", "波卡": "DOT", "Polkadot": "DOT",
    "matic": "POL", "polygon": "POL",
    "uni": "UNI", "Uniswap": "UNI",
    "ltc": "LTC", "莱特币": "LTC",
    "link": "LINK", "Chainlink": "LINK",
    "avax": "AVAX", "雪崩": "AVAX",
    "aave": "AAVE",
    "xlm": "XLM", "恒星币": "XLM",
    "trx": "TRX", "波场": "TRX",
    "ton": "GRAM", "toncoin": "GRAM",
    "bch": "BCH", "比特现金": "BCH",
    "zec": "ZEC", "大零币": "ZEC",
    "fil": "FIL", "Filecoin": "FIL",
    "near": "NEAR",
    "apt": "APT", "Aptos": "APT",
    "inj": "INJ", "Injective": "INJ",
    "hbar": "HBAR", "Hedera": "HBAR",
    "icp": "ICP",
    "jup": "JUP", "Jupiter": "JUP",
    "ray": "RAY", "Raydium": "RAY",
    "gt": "GT", "GateToken": "GT",
    "okb": "OKB",
    "dydx": "DYDX",
    "hype": "HYPE",
    "glm": "GLM", "Golem": "GLM",
    "render": "RENDER", "RNDR": "RENDER",
    "ondo": "ONDO",
    "ethfi": "ETHFI", "Ether.fi": "ETHFI",
    "pendle": "PENDLE",
}

SUPPORTED_COINS_UPPER: list[str] = [
    # 防御核 2
    "BTC", "ETH",
    # L1公链 9
    "SOL", "ADA", "AVAX", "INJ", "DOT", "NEAR", "APT", "ICP", "HBAR",
    # 支付链 6
    "XLM", "TRX", "GRAM", "LTC", "XRP", "BCH",
    # L2 1
    "POL",
    # DeFi 4
    "UNI", "AAVE", "PENDLE", "ETHFI",
    # 平台币 3
    "BNB", "OKB", "GT",
    # DEX/永续 4
    "DYDX", "HYPE", "JUP", "RAY",
    # 基础设施 1
    "LINK",
    # AI + 存储 3
    "RENDER", "GLM", "FIL",
    # 隐私 1
    "ZEC",
    # Memecoin/支付补充 1
    "DOGE",
    # RWA 1
    "ONDO",
]

def normalize_coin(raw_token: str):
    """归一化代币符号；命中白名单别名返回 SUPPORTED_COINS_UPPER 成员；否则 None。"""
    if not raw_token:
        return None
    t = raw_token.strip()
    if t in SUPPORTED_COINS_UPPER:
        return t
    mapped = COIN_ALIASES.get(t) or COIN_ALIASES.get(t.lower()) or COIN_ALIASES.get(t.capitalize())
    if mapped:
        return mapped
    upper = t.upper()
    if upper in SUPPORTED_COINS_UPPER:
        return upper
    return None

# ──────────────────────────────────────────────────────
# 4. 分桶常量（聚合时用）
# ──────────────────────────────────────────────────────
HORIZON_BUCKETS: tuple = (
    # (bucket_name, min_months_inclusive, max_months_inclusive)
    ("within_1y",  0,  12),
    ("1_to_3y",   13,  36),
    ("beyond_3y", 37, 999),
)

LATEST_WINDOW_DAYS = 180  # 「近半年」窗口 = 180 天

# ──────────────────────────────────────────────────────
# 5. Rating 允许值 + 归一化
# ──────────────────────────────────────────────────────
VALID_RATINGS = {
    "bullish", "bearish", "neutral",
    "buy", "overweight", "hold", "underweight", "sell",
    None,
}

def normalize_rating(raw):
    if not raw:
        return None
    if isinstance(raw, str):
        r = raw.strip().lower()
    else:
        return None
    if r in {"bullish", "buy", "overweight", "strong buy", "增持", "买入", "看涨", "看多"}:
        return "bullish"
    if r in {"bearish", "sell", "underweight", "减持", "卖出", "看跌", "看空"}:
        return "bearish"
    if r in {"neutral", "hold", "equal-weight", "持有", "中性", "观望"}:
        return "neutral"
    if r in VALID_RATINGS:
        return r
    return None
