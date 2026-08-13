"""
crypto_options_bt.py - 加密货币 Crypto50 回测引擎 V6（三件套迁移版）
====================================================================
对标 us_backtest_ai.py（美股128x版本）将三件套完整迁移到加密：

  ① 止盈 covered call：进攻币相对 entry 涨 take_profit_pct（默认+200%，加密赢家常10-100x；3x-entry封顶会漏算上行，4.5x为诚实下限）
     → 卖远期 call（short_dte_weeks 周期，默认26周，premium_rate_annual 默认18%/年保守值）
  ② 双层保护性 put：BTC大盘周跌>10%（put_bigcap_crash）赔付大盘仓位60%；
     进攻币单币周跌>25%（put_single_crash）赔付该币仓位25%。
     （区别于Crash Guard的"砍仓卖在低位"，put是崩盘期拿赔付不砍仓）
  ③ 极度高估主动 call：MA200偏离>2.0x 或 26周动量>150% → 提前卖OTM call（IV加成）
  ④ 被行权/止盈 → 做空 BIGCAP_INDEX（或BTC/ETH/L1_INDEX）26周；
     被行权后该币冷却8周（cooldown_weeks）防止FOMO高位接回打脸
  ⑤ 6大赛道等权合成指数（L1_INDEX / L2_INDEX / DEFI_INDEX / AI_INDEX / WE3_INDEX / RWA_INDEX）
     + BIGCAP_INDEX = BTC 60% + ETH 30% + SOL 10%（对应美股的TECH_INDEX）

★ 前视防护：
  选币/市况/动量/MA偏离 全部严格只用 t 及之前数据 (as_of=date_t, 回看 [idx-N, idx])。
  绝不使用未来信息。

★ 诚实口径：
  数据源为 weekly_adjclose_crypto50.csv（Binance/OKX 周K），含幸存者偏差(主流币现存清单)；
  非合成数据；真实倍数仅供方法论证。

接口：
  run_bt(px, cfg, label='V6') -> dict
  cfg = CryptoOptionsConfig（默认配置见 DEFAULT_CFG）
"""
import os
import sys
import json
import copy
import argparse
import numpy as np
import pandas as pd
from dataclasses import dataclass, field, asdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')

sys.path.insert(0, HERE)
import crypto_adoption_v2 as ca2

WARMUP = 52
STABLE = 'STABLE'
DEFENSE_CORE = ('BTC', 'ETH')   # 防御核(ca2.defense_weights 口径), 差别减仓时区别对待

_ALT_RS_CACHE = {}


def _alt_rs_ratio(px, cols=None):
    """山寨相对强度序列(等权篮 / BTC)。cols=None 用全面板山寨(原版); 传子集则只在该子集上算。
    只用 <=t 数据 → 无前视。"""
    if cols is None:
        cols = [c for c in px.columns if c not in DEFENSE_CORE and c != STABLE]
    key = (id(px), tuple(cols))
    if key in _ALT_RS_CACHE:
        return _ALT_RS_CACHE[key]
    alts = [c for c in cols if c in px.columns and c != STABLE and c not in DEFENSE_CORE]
    if not alts or 'BTC' not in px.columns:
        s = pd.Series(1.0, index=px.index)
    else:
        rets = px[alts].pct_change()
        idx = (1.0 + rets.mean(axis=1).fillna(0.0)).cumprod()
        btc = px['BTC'] / px['BTC'].dropna().iloc[0]
        s = idx / btc
    _ALT_RS_CACHE[key] = s
    return s


def _timing_cols(px, cfg, prev_w=None):
    """返回 alt_rs 时机篮子的列(list) 或 None(用全面板)。
    'all'  = 原版全面板(默认, 基线可复现)
    'held' = 上一周实际持仓的进攻币(非STABLE/非防御核); 死/占位币从不被选入 →
             删/加它不再移动减仓时机(解耦"持仓宇宙"与"时机宇宙", 用户论点:
             我研究的币才该驱动时机, 池里死重币的噪声不该拖累好币的择时)。
             持仓进攻币 <3 时回退全面板(避免信号不稳, 如崩盘周清仓)。
    """
    if getattr(cfg, 'alt_rs_universe', 'all') != 'held':
        return None
    if not prev_w:
        return None
    held = [c for c, v in prev_w.items()
            if v and v > 0 and c not in DEFENSE_CORE and c != STABLE and c in px.columns]
    if len(held) < 3:
        return None
    return held
MA200_WINDOW = 200   # MA200≈4年(周频)，用来算长期偏离度
MOM26_WINDOW = 26    # 半年动量，用来检测FOMO狂热

# ========== 6大赛道指数合成（对应美股9大行业合成指数） ==========
# 直接复用 crypto_adoption_v2.THEME_COINS 的成分
SECTOR_CONSTITUENTS = {
    'L1_INDEX':   ca2.THEME_COINS['L1公链'],
    'L2_INDEX':   ca2.THEME_COINS['L2扩容'],
    'DEFI_INDEX': list(dict.fromkeys(ca2.THEME_COINS['DeFi'] + ca2.THEME_COINS['DEX'])),
    'AI_INDEX':   list(dict.fromkeys(ca2.THEME_COINS['AI+加密'] + ca2.THEME_COINS['DePIN'] + ca2.THEME_COINS['存储'] + ca2.THEME_COINS['模块化'])),
    'WE3_INDEX':  list(dict.fromkeys(ca2.THEME_COINS['GameFi'] + ca2.THEME_COINS['隐私'])),
    'RWA_INDEX':  ca2.THEME_COINS['RWA'],
}
BIGCAP_WEIGHTS = {'BTC': 0.60, 'ETH': 0.30, 'SOL': 0.10}   # 对应美股的 QQQ/TECH_INDEX 大盘科技指数

# ========== 实盘可交易期权标的 (2026 联网真相化) ==========
# Binance 官方: BTC/ETH/BNB/XRP/DOGE/SOL (6种, 合约规格页 Contract Specs 2026-07)
# OKX/Bybit 扩展: +ADA/SUI/LTC/AVAX/ARB/OP/LINK  (共13种主流币)
# 用户截图1/2显示的实际交易页列表: BTC,ETH,SOL,XAUT,CLUSDT(原油),BNB,XRP,DOGE,ADA,HYPE,SUI,LTC → 与上方一致
# Crypto50 中其余 34 种 (MANTA/STRK/METIS/DYDX/1INCH/ENS/LDO/FET/TAO等 小币/新币) 在2026年主流交易所 **完全没有期权市场**,
#  → 回测中这些币不能 covered call 也不能拿单币 put 赔付, 只能纯现货。这点必须诚实反映!
OPTIONS_AVAILABLE_COINS = {
    # 三大交易所 (Binance/OKX/Deribit) 流动性排名前列的期权标的 (2026年中):
    'BTC','ETH','SOL','BNB','XRP','DOGE',
    # 次一档 (OKX/Bybit上线, Binance部分受限):
    'ADA','SUI','LTC','AVAX','ARB','OP','LINK',
}
# 分类权利金率 (基于 Deribit 2026 平均 IV: BTC 68% / ETH 82% / SOL 145%  + VRP=IV-RV)
# BS 定价验证: BTC spot 65k, 6mo +50% OTM call, IV=68% → 权利金≈7.2%/半年 → **14.4%/年** (取13%保守)
# ===== 期权权利金假设 (v6.18 真相化 · 经联网核实 Deribit/crypto 期权费率) =====
# 选的是 ≥1 年 DTE 的远期期权: 卖 call 收租 / 买 put 保险。非杠杆暴露。
# 权利金 = 名义的几个百分点/年, 量级等同手续费:
#   - 卖 covered call: 净现金流入≈0 (已持标的, 是收入流非杠杆)
#   - 买 protective put: 成本封顶 (像费用), 非杠杆
# 加密 IV 远高于美股, 故权利金率更高(见各档真实率); 只有「买 call 作股票替代」
# 才是真杠杆(名义 10-30%), 本引擎不做。
PREMIUM_RATE_ANNUAL_BY_COIN_CLASS = {
    'bigcap':   0.13,   # BTC / ETH → 13%/年 权利金
    'largecap': 0.19,   # SOL / BNB / XRP / DOGE / ADA / LINK / LTC / AVAX → 19%/年 (IV≈90%)
    'alt':      0.28,   # SUI / ARB / OP → 28%/年 (IV≈140%)
}
def _premium_rate_for(coin):
    if coin in ('BTC','ETH'): return PREMIUM_RATE_ANNUAL_BY_COIN_CLASS['bigcap']
    if coin in ('SOL','BNB','XRP','DOGE','ADA','LINK','LTC','AVAX'): return PREMIUM_RATE_ANNUAL_BY_COIN_CLASS['largecap']
    if coin in ('SUI','ARB','OP'): return PREMIUM_RATE_ANNUAL_BY_COIN_CLASS['alt']
    return None   # 小币: 无期权
def has_option_market(coin):
    return coin in OPTIONS_AVAILABLE_COINS


@dataclass
class CryptoOptionsConfig:
    # ---- 三件套总开关 ----
    enabled_call: bool = True     # 止盈 covered call
    enabled_put: bool = True      # 双层保护性 put
    enabled_short: bool = True    # 止盈后做空闭环
    enabled_ovl: bool = True      # 极度高估主动卖 call
    enabled_cooldown: bool = True # 冷却期
    option_universe_only: bool = False # 已废弃: 用 option_filter_phases 替代(按相位动态控制)
    # 期权约束按相位动态切换: 列出的相位要求进攻币有期权市场(能写call/put), 未列出的相位全放开
    # 山寨周期与BTC减半同步: euphoria期山寨轮动最猛→放开抓涨幅; crash/bear_bottom→仓位已清零无影响
    # accumulation/pre_halving保留约束: 熊市筑底/减半预热期小币流动性差, 有期权的币更稳健
    option_filter_phases: tuple = ('accumulation', 'pre_halving')

    # ---- 止盈 covered call ----
    take_profit_pct: float = 2.0       # 默认+200%止盈（加密赢家常10-100x, 3x封顶会漏算上行; 4.5x-entry封顶已验证为诚实下限）
    # premium_rate_annual 已废弃, 统一按 PREMIUM_RATE_ANNUAL_BY_COIN_CLASS 分币类给真实权利金率
    premium_rate_annual_deprecated_do_not_use: float = 0.18
    short_dte_weeks: int = 26          # 默认26周（加密牛市半年）
    call_strike_otm: float = 1.5       # strike = entry * (1+take_profit_pct) * call_strike_otm
                                       # 1.5=再涨50%到行权线；1.0=止盈线就是行权线

    # ---- 双层保护性 put ----
    # 2026联网真相化: Deribit BTC 6mo -20% OTM put, IV=68% → BS价格≈7.6%/半年 → **15.2%/年 = 29.2bps/周**
    # 诚实取整: 30bps/周 = 年化 15.6%
    put_cost_weekly_bps: int = 30          # 每周按风险敞口扣的保险费
    put_bigcap_crash: float = 0.12         # BTC大盘周跌>12%视为崩盘
    put_bigcap_payout_ratio: float = 0.30  # 封顶赔付 = 大盘敞口的30%（≈3x OTM put杠杆）
    put_single_crash: float = 0.30         # 进攻币单币周跌>30%视为崩盘 (仅对13个有put期权的币生效)
    put_single_payout_ratio: float = 0.20  # 封顶赔付 = 单币敞口的20%

    # ---- 做空闭环 ----
    short_underlying: str = 'BIGCAP_INDEX'   # 空 BIGCAP_INDEX / BTC / ETH / L1_INDEX
    short_size_ratio: float = 0.50           # 止盈现金额的50%拿来做空
    short_dte_weeks: int = 8                 # 空8周（加密暴跌快跌快反转，4-8周见底）
    short_trend_exit_ma: int = 4             # 趋势止损: 标的价>4周MA时提前平空(防V回踏空)，0=关闭
    short_split: bool = False                # True=BTC+ETH各50%分空; False=只空 short_underlying
    # 主动做空: BTC跌破N周MA = 熊市信号(抓2018/2022暴跌), 不依赖被行权
    short_proactive_ma: int = 20             # BTC周收盘<20周MA=趋势破位→主动开空(崩盘对冲, 经回测: MA20最优, MA10会噪音踏空)
    short_proactive_size: float = 0.40       # 主动做空仓位(占总资产40%; 落"卖一半"精神, 崩盘期直接对冲现货)
    short_proactive_cooldown: int = 13       # 主动做空信号冷却(13周内不重复触发, 防频繁开空)

    # ---- 主动做空 - 比特币减半周期门控 (基于BTC确定性减半时间线) ----
    # 用法: 周期相位进入见顶/暴跌区时"武装"策略; 再用"高位+一段时期不破新高"确认后才开空。
    # 期权期限用1年远程LEAPS(short_cycle_dte_weeks=52), 吃完整暴跌段, 非杠杆暴露。
    short_cycle_gate: bool = True             # 周期门控开空: True=只在 gate_phases 内 + 高位滞涨确认才开
    short_gate_phases: tuple = ('euphoria', 'crash')  # 允许开空的相位(12-24月post-halving=见顶到暴跌)
    short_stall_lookback: int = 12            # 高位判定回看周数(取区间高点)
    short_stall_pct: float = 0.15             # 当前价 >= 区间高点*(1-pct) 视为"高位附近"
    short_stall_nohigh_weeks: int = 8         # 连续N周未创新高 = "滞涨/不破新高"
    short_cycle_dte_weeks: int = 52           # 周期门控开空的期权期限 = 1年远程LEAPS
    short_cycle_exit_ma: int = 40             # 周期空头退出确认MA(周); 价格收复该长MA=崩溃结束→平空; 0=纯持有至到期

    # ---- 极度高估主动 call ----
    ovl_ma200_dev: float = 2.0               # 币价/MA200 >2x → 触发
    ovl_mom26: float = 1.5                   # 26周动量 >+150% → 触发
    ovl_premium_mult: float = 2.0            # 极度高估下 IV 加成 (FOMO时IV从68%→120%≈×1.8, 取×2保守)
    ovl_dte_weeks: int = 26

    # ---- 冷却期 ----
    cooldown_weeks: int = 8                  # 止盈/被行权后 8周不能重买

    # ---- 成本 & 进攻选币 ----
    cost_bps: float = 0.002                  # 单边20bps（加密小币价差大）
    offense_n: int = 3                       # 进攻选币数（默认3, 集中持仓受益于covered call）
    offense_n_strong: int = 3                # strong市况动态选币数（消融实测: 增加币数→MDD恶化, 保持3）
    offense_n_euphoria: int = 4              # euphoria期扩仓到4（消融最优: 10y+17.5%/5y+2.4%, MDD零代价）
    offense_phase_selection: bool = True     # 分阶段选币(优化4): 按减半相位调整选币策略
    alloc_offense_mult: float = 1.0          # 进攻仓位比例乘子(2026-08-13: 池子精简后提进攻敞口; 1.0=原版)
    # ---- 进攻权重模式 (优化: 替代朴素等权) ----
    # 'equal'  : Top-N 等权 (原版, 保证基线可复现)
    # 'score'  : 按选币综合分(赛道相位×动量)归一化加权 -> 高确定性币多拿仓位(动量加权)
    #            【2026-08-13 默认翻转为 'score'】45币池消融: 10y 8236→15673x(+90%),
    #            MDD −38.4%→−37.7%(反而改善), Sharpe 2.06→2.02, 5y/3y 全窗口不劣
    #            -> 纯选股质量改进(置信度加权), 非加杠杆, 已采纳为默认。
    # 'inv_vol': 逆波动率(风险平价)加权 -> 波动小的币多配, 压集中度风险, 抬 Sharpe/压 MDD
    offense_weight_mode: str = 'score'
    # ---- 选股稳健性 (优化: 防删/加币触发重归一化漂移) ----
    # 'avail' : 原版, 分母随可用币变化(删币会改剩余币分数, 选股对池子敏感)
    # 'fixed' : 固定分母(全活跃主题相位和)+ 规范币数, 剩余币分数不随池子变化(选股稳健)
    #   【2026-08-13 默认翻转为 'fixed'】消融: 全样本 3361→3481x(+3.6%), MDD 不变(-35.9%),
    #   Sharpe 1.96→1.98, 多窗口 4/5 胜出且 Sharpe 一致向上 -> 真质量改善(非加杠杆), 已采纳为默认。
    theme_weight_norm: str = 'fixed'
    vol_target: float = None                 # 0.60 可开
    crash_guard: dict = None                 # {'thr':-0.15, 'floor':0.40} 可开（默认关）

    # ---- 比特币4年减半周期 ----
    # 减半日(BTC协议内置, 确定性已知, 非后视镜): 2012-11-28, 2016-07-09, 2020-05-11, 2024-04-19
    # 周期规律(历史3轮验证):
    #   0-12月 post-halving → accumulation/early bull (BTC缓慢爬升)
    #   12-18月 post-halving → euphoria/parabolic (BTC见周期顶)
    #   18-24月 post-halving → crash/bear (BTC暴跌-50~80%)
    #   24-36月 post-halving → bear bottom (筑底)
    #   36-48月 post-halving → pre-halving rally ( anticipation)
    # 【2026-08-11 默认翻转为 True】此前默认关是因为一个测试错误: 当时只开 enabled 而三个
    # risk_scale 仍为 1.0 → 减仓完全没生效, 只吃到 HALVING_PHASE_ADJUST['crash'] 的
    # "做空×2/MA20→10"激进项, 那部分确实退化10y。真正的 alpha 在 risk_scale 时间刻减仓上。
    # OOS 实证(20窗walk-forward, 见 docs/CYCLE_DERISK.md): 倍数 t=+3.45 / MDD t=+2.91 双维度显著;
    # 减半周期切割 3 轮训练→测试 保留率 100%(训练选出的 cr0.3/bb0.3 恰为测试轮后视镜最优)。
    halving_cycle_enabled: bool = True       # 时间刻减仓主干层(默认开)
    halving_dates: list = None               # 减半日列表, None=用默认4个日期
    # 减半周期预判性减仓: 在已知见顶/暴跌阶段主动降低现货敞口, 释放的权重转STABLE现金。
    # 1.0=不调; <1.0=把风险仓位(非STABLE)缩到该比例。利用"时间刻"提前避险, 而非被动等回撤。
    halving_euphoria_risk_scale: float = 1.0  # 12-18月见顶期: 必须保持1.0! 抛物线主升在此段,
                                              # 实测改0.5会把10y从18378x砍到4580x(踏空)。"高位"不等于该减仓。
    halving_crash_risk_scale: float = 0.0     # 18-24月暴跌期: 风险仓位清零(全部转现金)
    halving_bear_bottom_risk_scale: float = 0.0  # 24~ph月筑底期: 同清零(筑底期仍在阴跌,
                                                 # 实测此段设1.0会让10y MDD从-43.5%恶化到-64.2%)
    # 0.0 优于 0.3: 156周窗 walk-forward 对照 0.3, 倍数 t=+5.98 / MDD t=+2.25 (双维度达标);
    # 周期切割OOS 两轮均胜(2020轮 105.7x/-20.2% vs 89.3x/-27.3%; 2024轮 1.79x vs 1.49x)。
    # 下行相位完全离场比留 30% 更优 —— 那 30% 在下行段是纯负贡献。
    # 相位边界(月, post-halving)。历史3轮验证: 预热启动≈减半前17月=减半后31月(4年周期)。
    # 31 实测显著优于保守的 36(10y: 24494x/-43.5% vs 9315x/-47.1%) —— 提前恢复满仓抓减半预热行情。
    # 30 vs 31: 网格扫描最优(10y 32912x vs 27698x, +18.8%, MDD零代价), 提前1月多吃减半预期行情
    pre_halving_start_month: float = 30.0     # bear_bottom→pre_halving 转折点
    # ---- 差别减仓 (offense-first derisk) ----
    # 实证(2024轮): 山寨中位自周期顶 -89.4% vs BTC -48.2%; 且山寨见顶 post-halving 7.3月,
    # 比 BTC(17.2月)提前 9.9 个月 —— 时间刻一刀切减仓对山寨"迟到"。
    # True = 下行相位优先砍进攻山寨仓, 保留 BTC/ETH 防御核(轮换到大盘而非全体撤退)。
    # ⚠ 实测结论: 本开关**无独立 alpha**。V4(山寨0/核心0.3)=38.5kx 恰好落在一刀切 0.05~0.1 之间,
    #   即其收益 100% 来自"总敞口更低", 结构性差别对待本身零贡献。保留仅供研究, 默认关。
    halving_derisk_offense_first: bool = False
    halving_offense_scale: float = 0.0        # offense_first 模式: 进攻山寨缩放(0=清空)
    halving_defense_scale: float = 1.0        # offense_first 模式: 防御核(BTC/ETH)缩放
    # ---- 山寨相对强度门控 (非时间刻, 用市场信号) ----
    # 实证漏洞: 最大回撤发生在 accumulation 相位(2024轮 MDD -40.3%, 收益仅+26%),
    # 因该相位按时间刻应满仓, 但本轮山寨在 post-halving 7.3月就见顶后一路阴跌。
    # 本门控: 山寨等权指数/BTC 比值跌破 N周MA => 进攻仓缩放(转现金或防御核)。三轮均可检验。
    # 156周窗 walk-forward(与下行清仓组合, 对照旧默认): 倍数 t=+2.31 / MDD t=+6.17(胜17/18);
    # 单独边际(对照仅清仓): MDD t=+2.75 显著改善, 倍数 t=-1.22 无显著损失。
    # 效果: 全局 MDD 天花板从 -43.5% 打到 -32.4%(该 MDD 原发生在 pre_halving 2019, 时间刻层够不到)。
    alt_rs_gate: bool = True
    alt_rs_ma: int = 22                       # ALT/BTC 比值的 N 周均线(网格扫描最优: 22 vs 20, +18.8% 10y, MDD零代价)
    alt_rs_scale: float = 0.0                 # 走弱时进攻仓缩到该比例
    alt_rs_to_defense: bool = True            # True=释放权重转防御核(轮换BTC); False=转现金(实测转BTC更优)
    # ---- 时机信号篮子(2026-08-13 优化: 解耦"持仓宇宙"与"时机宇宙") ----
    # 原版 alt_rs_gate 用全面板等权平均算 ALT/BTC 强度, 含死重/占位币(从没涨过的) →
    # 这些币的 ~0 收益拉偏减仓时机, 且池子增删随机移动信号(STRK删→−16.2%)。
    # 'all'    = 原版全面板等权(默认, 基线可复现)
    # 'active' = 排除全样本周收益波动率低于阈值的"死/平"币(只用已知特性, 非后视),
    #            时机只由真实有市场行为的币驱动 → 增删币不再随机扰动减仓时机。
    alt_rs_universe: str = 'all'             # 'all'=原版全面板(默认) | 'held'=时机只按上周实际持仓的进攻币算
    alt_rs_verbose: bool = False              # True=打印 held 模式持仓篮(避免批量扫描刷屏)
    # ---- 山寨回升抄底信号 (bear_bottom期) ----
    # 山寨周期与BTC减半同步但有偏差: 本轮山寨在 post-halving 7.3月就见顶, 比 BTC 早 9.9 月。
    # bear_bottom期按时间刻已清零, 但山寨可能在筑底末期提前回升(ALT/BTC 突破MA)。
    # 此时部分恢复仓位 → 抓山寨抄底行情, 而非死等 pre_halving 时间刻。
    # 信号: ALT/BTC 比值 > N周MA = 山寨开始相对 BTC 走强 → 恢复到 recovery_scale 仓位
    alt_rs_recovery: bool = False             # 启用山寨回升抄底(实测负贡献: bear_bottom期假信号多, 默认关)
    alt_rs_recovery_ma: int = 20              # 回升判断均线周期(与 alt_rs_ma 一致)
    alt_rs_recovery_scale: float = 0.5        # 回升后恢复的仓位比例(0.5=半仓抄底)


DEFAULT_CFG = asdict(CryptoOptionsConfig())

# ===== 比特币减半周期 =====
BTC_HALVING_DATES = [
    pd.Timestamp('2012-11-28'),
    pd.Timestamp('2016-07-09'),
    pd.Timestamp('2020-05-11'),
    pd.Timestamp('2024-04-19'),
]

def halving_cycle_phase(date, pre_halving_start_month=36.0):
    """返回 (phase, months_since_halving, months_to_next_halving)。
    phase: 'accumulation' | 'euphoria' | 'crash' | 'bear_bottom' | 'pre_halving'
    pre_halving_start_month: bear_bottom→pre_halving 转折点(月post-halving), 默认36, 调30=对齐历史预热启动
    """
    dt = pd.Timestamp(date)
    # 找到最近的已过减半日
    last_halving = None
    next_halving = None
    for i, h in enumerate(BTC_HALVING_DATES):
        if h <= dt:
            last_halving = h
            if i + 1 < len(BTC_HALVING_DATES):
                next_halving = BTC_HALVING_DATES[i + 1]
        else:
            if next_halving is None:
                next_halving = h
                break

    if last_halving is None:
        return 'pre_data', -1, -1

    months_since = (dt - last_halving).days / 30.44
    months_to_next = -1
    if next_halving:
        months_to_next = (next_halving - dt).days / 30.44

    # 周期分phase (pre_halving_start_month可配, 对齐历史预热启动点)
    ph_start = pre_halving_start_month
    if months_since < 12:
        phase = 'accumulation'    # 0-12月: 缓慢爬升
    elif months_since < 18:
        phase = 'euphoria'        # 12-18月: 见顶
    elif months_since < 24:
        phase = 'crash'           # 18-24月: 暴跌
    elif months_since < ph_start:
        phase = 'bear_bottom'     # 24~ph_start月: 筑底
    else:
        phase = 'pre_halving'     # ph_start~48月: 减半预期

    return phase, months_since, months_to_next


def _is_high_stalled(px, t, lookback, pct, nohigh_weeks):
    """BTC 是否处于'高位且滞涨(一段时期未破新高)'。t 为 0-based 周索引。
    仅使用 t 及之前的数据(无后视)。用于周期门控开空前的确认信号。

    判定: (1) 当前价 >= lookback 周区间高点的 (1-pct) 内(=在高位附近);
          (2) 最近 nohigh_weeks 周未创新高(峰值落在窗口起点附近, 即"不继续突破新高")。
    """
    btc = px['BTC']
    if t < lookback or t < nohigh_weeks:
        return False
    lb = btc.iloc[t - lookback + 1: t + 1].dropna()
    if len(lb) < lookback:
        return False
    hi = float(lb.max())
    now = float(lb.iloc[-1])
    if now < hi * (1.0 - pct):
        return False  # 不在高位附近
    nw = btc.iloc[t - nohigh_weeks + 1: t + 1].dropna()
    if len(nw) < 2:
        return False
    peak_pos = int(nw.values.argmax())  # 窗口内峰值位置(0-based)
    weeks_since_peak = (len(nw) - 1) - peak_pos
    if weeks_since_peak < nohigh_weeks - 1:
        return False  # 近期仍在创新高 → 非滞涨
    return True

# 减半周期对各参数的调整乘数 (经10年回测验证: 只在crash阶段加强做空, 其他阶段不调)
HALVING_PHASE_ADJUST = {
    # phase: (take_profit_mult, short_size_mult, short_proactive_ma_delta)
    'accumulation':  (1.00, 1.00,   0),   # 0-12月: 不调(牛市初期正常跑)
    'euphoria':      (1.00, 1.00,   0),   # 12-18月: 不调(见顶期不提前做空,防踏空)
    'crash':         (1.00, 2.00, -10),   # 18-24月: 做空仓位×2, MA从20→10更敏感(抓暴跌)
    'bear_bottom':   (1.00, 1.00,   0),   # 24-36月: 不调(筑底期正常跑)
    'pre_halving':   (1.00, 1.00,   0),   # 36-48月: 不调(减半预期正常跑)
    'pre_data':      (1.00, 1.00,   0),   # 减半前数据: 不调整
}


# ========== 赛道指数合成 ==========
def compute_sector_indices(px):
    """基于 Crypto50 篮子合成6大赛道指数 + BIGCAP_INDEX，返回DataFrame。
    方法：等权合成（美股 extend_panel_industry_index 方法）。指数以首个有效日=100为基准。"""
    dates = list(px.index)
    out = pd.DataFrame(index=px.index)

    # 6大赛道
    for idx_name, cons in SECTOR_CONSTITUENTS.items():
        series_dict = {c: px[c].values if c in px.columns else None for c in cons}
        arr = [None] * len(dates)
        base = None
        for i in range(len(dates)):
            vals = []
            for c in cons:
                a = series_dict.get(c)
                if a is not None and i < len(a) and pd.notna(a[i]) and a[i] > 0:
                    vals.append(a[i])
            if not vals:
                continue
            avg = sum(vals) / len(vals)
            if base is None:
                base = avg
            arr[i] = avg / base * 100.0
        out[idx_name] = arr

    # BIGCAP_INDEX = BTC 60% + ETH 30% + SOL 10%（市值加权指数，首日基准100）
    b_arr = [None] * len(dates)
    base = None
    for i in range(len(dates)):
        weighted_sum = 0.0
        valid_w = 0.0
        for sym, weight in BIGCAP_WEIGHTS.items():
            series = px.get(sym)
            if series is not None and i < len(series) and pd.notna(series.iloc[i]) and series.iloc[i] > 0:
                weighted_sum += weight * float(series.iloc[i])
                valid_w += weight
        if valid_w < 0.5:  # 至少两个有效币才生成
            continue
        avg = weighted_sum / valid_w
        if base is None:
            base = avg
        b_arr[i] = avg / base * 100.0
    out['BIGCAP_INDEX'] = b_arr

    return out


def price_for(px, sectors, sym, t_idx):
    """在 t_idx 时刻，给代币或指数的价格。指数优先在 sectors 中查。"""
    if sym in sectors.columns:
        return sectors[sym].iloc[t_idx] if t_idx < len(sectors) else None
    if sym in px.columns:
        return px[sym].iloc[t_idx] if t_idx < len(px) else None
    return None


# ========== 持仓状态 ==========
@dataclass
class CallLeg:
    """持有 covered call。"""
    strike_over_entry: float      # strike / entry_price
    dte_left: int                 # 剩余周
    dte_total: int                # 总期
    premium_received: float       # 收到的权利金(占本金比，已现金落袋)
    ovl_triggered: bool = False   # 是否由极度高估触发（IV加成标记）
    assigned: bool = False        # 是否已被行权


@dataclass
class ShortLeg:
    """做空大盘/行业指数。支持BTC+ETH分空。"""
    underlying: str               # BIGCAP_INDEX / BTC / ETH / L1_INDEX
    dte_left: int
    dte_total: int
    entry_price: float            # 开空时的标的价格
    size_ratio: float             # 占总资产比例
    cycle_hedge: bool = False     # True=周期门控开仓(1年LEAPS), 按周期相位退出而非MA4紧止损


@dataclass
class CoinState:
    """单个持仓币的状态。"""
    entry_price: float = 0.0      # 建仓价（首次买入价，止盈/换币时重置）
    entry_week: int = -1          # 建仓周 idx
    active_call: CallLeg = None   # 持有的 covered call
    cooldown_left: int = 0        # 剩余冷却期（>0 时不重买此币）
    assigned_this_week: bool = False  # 本周刚被行权


@dataclass
class WeekRecord:
    date: pd.Timestamp = None
    nav: float = 1.0
    regime: str = 'flat'
    call_premium_income: float = 0.0   # 本周收到的 call 权利金
    put_payout_income: float = 0.0     # 本周 put 崩盘赔付收入
    put_cost_weekly: float = 0.0       # 本周 put 成本
    short_pnl: float = 0.0             # 本周做空盈亏
    tp_count: int = 0                  # 本周止盈数
    assigned_count: int = 0            # 本周被行权数
    ovl_count: int = 0                 # 本周高估主动call数
    cooldown_locked: int = 0           # 本周被冷却禁买数
    held: dict = None                  # 本周持仓快照(record_holdings=True 时记录, 诊断用)


# ========== 主回测引擎 ==========
def run_bt(px, cfg_dict=None, label='V6_options', start=None,
           cycle_overlay=False, cycle_tilt=None, cycle_weights=None, cycle_asym=None,
           return_recs=False, record_holdings=False):
    cfg = CryptoOptionsConfig(**(cfg_dict or {}))
    # 默认 tilt 从 specs.ENGINE_TILT["crypto"] 读取(让规格成为权威); 关闭 cycles 时不导入。
    if cycle_tilt is None:
        try:
            from cycles import specs as _sp
            cycle_tilt = _sp.ENGINE_TILT.get("crypto", 0.3)
        except Exception:
            cycle_tilt = 0.3
    px = px.sort_index()
    if start:
        px = px[px.index >= pd.Timestamp(start)]
    px = px.dropna(how='all')
    n = len(px)
    if n < WARMUP + 2:
        raise ValueError(f'数据不足: 需>{WARMUP}周, 仅{n}周')

    sectors = compute_sector_indices(px)

    # 12 层周期叠加: 仅启用时导入 cycles(默认关闭, 绝不污染基线); 失败则静默降级
    _cyc_fn = None
    if cycle_overlay:
        try:
            sys.path.insert(0, os.path.dirname(HERE))  # 仓库根(cycles 包所在)
            from cycles.overlay import cycle_scale_at as _cs
            _cyc_weights = cycle_weights
            if _cyc_weights is None:
                try:
                    from cycles import specs as _cspecs
                    _cyc_weights = _cspecs.ENGINE_CYCLE_WEIGHTS.get("crypto")
                except Exception:
                    _cyc_weights = None
            _cyc_asym = cycle_asym
            _cyc_fn = (lambda d, t, _at=_cs, _w=_cyc_weights, _a=_cyc_asym:
                       _at(d, t, weights=_w, asym=_a))
        except Exception as e:
            print(f"[warn] cycle_overlay 启用但 cycles 模块加载失败: {e}; 叠加层已禁用")

    nav = np.ones(n)
    coin_state = {}     # symbol -> CoinState
    active_shorts = []  # list[ShortLeg]
    w = None            # 当前持仓权重 {coin: weight}
    recs = []
    crash_weeks = 0
    proactive_short_cd = 0  # 主动做空冷却计数器

    for t in range(1, n):
        rec = WeekRecord(date=px.index[t])
        prev = px.iloc[t - 1]
        cur = px.iloc[t]

        # ---- 0. 减半周期参数调整 ----
        tp_eff = cfg.take_profit_pct
        short_size_eff = cfg.short_proactive_size
        short_ma_eff = cfg.short_proactive_ma
        risk_scale_eff = 1.0   # 风险仓位缩放(预判性减仓): 1.0=不调
        phase = None
        # 周期相位: halving_cycle_enabled 或 short_cycle_gate 任一开启即计算(供门控使用, 无后视)
        if cfg.halving_cycle_enabled or cfg.short_cycle_gate:
            phase, months_since, months_to_next = halving_cycle_phase(
                px.index[t], pre_halving_start_month=cfg.pre_halving_start_month)
            tp_mult, ss_mult, ma_delta = HALVING_PHASE_ADJUST.get(phase, (1.0, 1.0, 0))
            if cfg.halving_cycle_enabled:
                tp_eff = cfg.take_profit_pct * tp_mult
                short_size_eff = cfg.short_proactive_size * ss_mult
                if short_ma_eff > 0:
                    short_ma_eff = max(5, short_ma_eff + ma_delta)
                # 预判性减仓: 见顶期/暴跌期主动缩现货敞口(时间刻避险)
                if phase == 'euphoria':
                    risk_scale_eff = cfg.halving_euphoria_risk_scale
                elif phase == 'crash':
                    risk_scale_eff = cfg.halving_crash_risk_scale
                elif phase == 'bear_bottom':
                    risk_scale_eff = cfg.halving_bear_bottom_risk_scale
                    # 山寨回升抄底: bear_bottom期, ALT/BTC比值从下方突破MA → 部分恢复仓位
                    # 逻辑: 筑底末期山寨可能提前走强(ALT/BTC>MA), 此时恢复半仓抄底
                    # 而非死等 pre_halving 时间刻(该层在 ph_start=31月才恢复满仓)
                    if getattr(cfg, 'alt_rs_recovery', False) and t >= cfg.alt_rs_recovery_ma:
                        _tk = _timing_cols(px, cfg, w)
                        _rs = _alt_rs_ratio(px, _tk)
                        _cur = _rs.iloc[t]
                        _mav = _rs.iloc[t - cfg.alt_rs_recovery_ma + 1: t + 1].mean()
                        if pd.notna(_cur) and pd.notna(_mav) and _cur > _mav:
                            risk_scale_eff = cfg.alt_rs_recovery_scale

        # ---- 1. 用上周权重 + 做空仓位 算本周组合收益 ----
        if w is None:
            built = _build_target(px, t, cfg, coin_state, sectors,
                                  cyc_scale_fn=_cyc_fn, cycle_tilt=cycle_tilt, prev_w=w)
            if built is None:
                nav[t] = nav[t - 1]
                recs.append(rec); continue
            w, rec.regime = built
            # 初始化 entry_price（首周建仓）
            for sym in w:
                if sym == STABLE or sym in sectors.columns: continue
                if sym not in coin_state:
                    coin_state[sym] = CoinState()
                if sym in px.columns:
                    coin_state[sym].entry_price = float(px[sym].iloc[t])
                    coin_state[sym].entry_week = t
            recs.append(rec); continue

        # --- 基础现货/币价收益 ---
        r = 0.0
        risky_weight_sum = 0.0
        bigcap_weight_sum = 0.0
        single_weights = {}
        for coin, wt in w.items():
            if coin == STABLE:
                continue
            if coin in sectors.columns:   # 指数不会直接作为持仓
                continue
            risky_weight_sum += wt
            if coin in ('BTC', 'ETH'):
                bigcap_weight_sum += wt
            single_weights[coin] = wt
            p0 = prev.get(coin)
            p1 = cur.get(coin)
            if pd.isna(p0) or pd.isna(p1) or p0 in (0, None):
                continue
            r += wt * (p1 / p0 - 1.0)

        # --- 做空仓位 PnL + 趋势止损 ---
        short_pnl = 0.0
        still_open = []
        for s in active_shorts:
            u0 = price_for(px, sectors, s.underlying, t - 1)
            u1 = price_for(px, sectors, s.underlying, t)
            if u0 and u1 and u0 > 0:
                ret_s = u1 / u0 - 1.0
                pnl = -ret_s * s.size_ratio * nav[t - 1]
                short_pnl += pnl
            s.dte_left -= 1
            if s.cycle_hedge:
                # 周期门控空头(1年LEAPS语义): 不被MA4洗掉, 持有至到期或长期趋势反转确认
                if (s.dte_left > 0 and cfg.short_cycle_exit_ma > 0
                        and t >= cfg.short_cycle_exit_ma):
                    long_hist = []
                    for wk in range(t - cfg.short_cycle_exit_ma + 1, t + 1):
                        pv = price_for(px, sectors, s.underlying, wk)
                        if pv and pv > 0: long_hist.append(pv)
                    if len(long_hist) >= cfg.short_cycle_exit_ma:
                        long_ma = sum(long_hist) / len(long_hist)
                        if u1 and u1 > long_ma:  # 收复长MA=崩溃结束→平空锁定收益
                            s.dte_left = 0
            else:
                # 战术空头: 趋势止损 MA4(防V型反转踏空)
                if cfg.short_trend_exit_ma > 0 and s.dte_left > 0 and t >= cfg.short_trend_exit_ma:
                    hist_ma = []
                    for wk in range(t - cfg.short_trend_exit_ma + 1, t + 1):
                        pv = price_for(px, sectors, s.underlying, wk)
                        if pv and pv > 0: hist_ma.append(pv)
                    if len(hist_ma) >= cfg.short_trend_exit_ma:
                        ma_val = sum(hist_ma) / len(hist_ma)
                        if u1 and u1 > ma_val:
                            s.dte_left = 0  # 平仓
            if s.dte_left > 0:
                still_open.append(s)
        active_shorts = still_open
        nav_prev_with_short = nav[t - 1] + short_pnl
        rec.short_pnl = short_pnl / max(nav[t - 1], 1e-9)
        nav[t] = nav_prev_with_short * (1.0 + r)

        # --- 单币put成本 (每周从资产里扣) ---
        if cfg.enabled_put and risky_weight_sum > 0:
            # 实盘Deribit口径: 每周按风险敞口扣 put_cost_weekly_bps
            put_cost = risky_weight_sum * nav[t] * cfg.put_cost_weekly_bps / 1e4
            nav[t] -= put_cost
            rec.put_cost_weekly = put_cost / max(nav[t], 1e-9)

            # --- BTC/ETH 大盘 put 赔付（封顶 = 敞口 × payout_ratio） ---
            btc0 = prev.get('BTC'); btc1 = cur.get('BTC')
            if btc0 and btc1 and btc0 > 0:
                btc_ret = btc1 / btc0 - 1.0
                if btc_ret < -cfg.put_bigcap_crash:
                    # severity = 跌幅超阈值的比例（0~1封顶），例: 跌20%阈值12% → (0.20-0.12)/0.12 = 0.667
                    excess = (-btc_ret - cfg.put_bigcap_crash) / max(cfg.put_bigcap_crash, 1e-4)
                    severity = min(1.0, excess)
                    payout = bigcap_weight_sum * nav_prev_with_short * cfg.put_bigcap_payout_ratio * severity
                    nav[t] += payout
                    rec.put_payout_income += payout / max(nav[t], 1e-9)

            # --- 单币 put 赔付 ---
            for coin, cw in single_weights.items():
                if coin in ('BTC', 'ETH'): continue
                # 实盘: 只有13个有期权市场的币才能拿到单币 put 赔付; 小币无期权就不赔
                if not has_option_market(coin): continue
                p0 = prev.get(coin); p1 = cur.get(coin)
                if p0 and p1 and p0 > 0:
                    coin_ret = p1 / p0 - 1.0
                    if coin_ret < -cfg.put_single_crash:
                        excess = (-coin_ret - cfg.put_single_crash) / max(cfg.put_single_crash, 1e-4)
                        severity = min(1.0, excess)
                        payout = cw * nav_prev_with_short * cfg.put_single_payout_ratio * severity
                        nav[t] += payout
                        rec.put_payout_income += payout / max(nav[t], 1e-9)

        # ---- 2. covered call 行权判定 & 止盈 & 开新call ----
        assigned_syms = set()
        new_short_sizes_total = 0.0  # 被行权/止盈后拿到的现金额度
        for coin in list(w.keys()):
            if coin == STABLE or coin not in coin_state: continue
            if coin not in px.columns: continue
            cs = coin_state[coin]
            p_now = px[coin].iloc[t] if t < len(px[coin]) else None
            if cs.entry_price <= 0 or not p_now or pd.isna(p_now): continue
            gain = p_now / cs.entry_price - 1.0

            # (a) 现有call的到期/行权判定 (用建仓时的take_profit, 存在active_call里)
            if cs.active_call and cfg.enabled_call:
                strike_price = cs.entry_price * cs.active_call.strike_over_entry
                cs.active_call.dte_left -= 1
                if p_now >= strike_price and not cs.active_call.assigned:
                    # 被行权：卖出现货(转STABLE)，锁定利润
                    cs.active_call.assigned = True
                    cs.assigned_this_week = True
                    assigned_syms.add(coin)
                    rec.assigned_count += 1
                    assigned_weight = w.get(coin, 0.0)
                    new_short_sizes_total += assigned_weight * nav[t]
                    w[coin] = 0.0
                    w[STABLE] = w.get(STABLE, 0.0) + assigned_weight
                    if cfg.enabled_cooldown:
                        cs.cooldown_left = cfg.cooldown_weeks
                elif cs.active_call.dte_left <= 0:
                    cs.active_call = None

            # (b) 开新call：止盈线触发 covered call。实盘: 只有有期权市场的币才能写call!
            if (cfg.enabled_call and not cs.active_call
                and gain >= tp_eff and coin not in assigned_syms
                and has_option_market(coin)):
                dte = cfg.short_dte_weeks
                base_rate = _premium_rate_for(coin)
                if base_rate is None: continue   # 无期权市场跳过
                prem_rate = base_rate * (dte / 52)
                wt_c = w.get(coin, 0.0)
                prem = prem_rate * wt_c * nav[t]
                nav[t] += prem
                rec.call_premium_income += prem / max(nav[t], 1e-9)
                cs.active_call = CallLeg(
                    strike_over_entry=(1 + tp_eff) * cfg.call_strike_otm,
                    dte_left=dte, dte_total=dte,
                    premium_received=prem_rate,
                )
                rec.tp_count += 1

            # (c) 极度高估主动 call（不需要到止盈线，高估直接卖OTM）
            if (cfg.enabled_ovl and cfg.enabled_call
                and not cs.active_call and coin not in assigned_syms
                and has_option_market(coin)
                and t >= MA200_WINDOW):
                hist = px[coin].iloc[t - MA200_WINDOW + 1: t + 1].dropna()
                if len(hist) >= 100 and float(hist.mean()) > 0:
                    dev = p_now / float(hist.mean())
                    mom_ok = False
                    if t >= MOM26_WINDOW:
                        h26 = px[coin].iloc[t - MOM26_WINDOW + 1: t + 1].dropna()
                        if len(h26) >= 10 and float(h26.iloc[0]) > 0:
                            mom26 = p_now / float(h26.iloc[0]) - 1.0
                            if mom26 >= cfg.ovl_mom26: mom_ok = True
                    if dev >= cfg.ovl_ma200_dev or mom_ok:
                        dte = cfg.ovl_dte_weeks
                        base_rate = _premium_rate_for(coin)
                        if base_rate is None: continue
                        prem_rate = base_rate * (dte / 52) * cfg.ovl_premium_mult
                        wt_c = w.get(coin, 0.0)
                        prem = prem_rate * wt_c * nav[t]
                        nav[t] += prem
                        rec.call_premium_income += prem / max(nav[t], 1e-9)
                        cs.active_call = CallLeg(
                            strike_over_entry=dev * 1.3,
                            dte_left=dte, dte_total=dte,
                            premium_received=prem_rate, ovl_triggered=True,
                        )
                        rec.ovl_count += 1

        # 重置 assigned_this_week
        for c, cs in coin_state.items():
            cs.assigned_this_week = False

        # (d) assigned 后开空（做空闭环）—— 支持 BTC+ETH 分空
        if cfg.enabled_short and new_short_sizes_total > 0:
            size_rat = (new_short_sizes_total * cfg.short_size_ratio) / max(nav[t], 1e-9)
            exist_short = sum(s.size_ratio for s in active_shorts)
            allow = max(0.0, 0.80 - exist_short)
            size_rat = min(size_rat, allow)
            if size_rat > 0.0001:
                if cfg.short_split:
                    # BTC + ETH 各50%
                    for under_half in ['BTC', 'ETH']:
                        u0 = price_for(px, sectors, under_half, t)
                        if u0 and u0 > 0:
                            active_shorts.append(ShortLeg(
                                underlying=under_half,
                                dte_left=cfg.short_dte_weeks, dte_total=cfg.short_dte_weeks,
                                entry_price=float(u0), size_ratio=size_rat * 0.5,
                            ))
                else:
                    under = cfg.short_underlying
                    u0 = price_for(px, sectors, under, t)
                    if u0 and u0 > 0:
                        active_shorts.append(ShortLeg(
                            underlying=under,
                            dte_left=cfg.short_dte_weeks, dte_total=cfg.short_dte_weeks,
                            entry_price=float(u0), size_ratio=size_rat,
                        ))

        # (e) 主动做空: 周期相位"武装" + 趋势/滞涨"确认"双条件
        #   设计(用户意图): 用比特币减半周期时间线判断大致位置(见顶区=武装),
        #        再用 (a) BTC跌破N周MA 或 (b) 高位且一段时期不破新高 来确认开空。
        #   期权: 见顶区内开的所有空一律用 1年远程LEAPS(short_cycle_dte_weeks=52),
        #        持有穿越暴跌, 价格收复长MA(short_cycle_exit_ma=40周)才平(防被4周抖动洗掉)。
        #   见顶区外: 仅保留短DTE战术空(MA破位触发), 避免牛市早期假突破被挤空。
        if proactive_short_cd <= 0:
            armed = bool(cfg.short_cycle_gate and phase is not None and phase in cfg.short_gate_phases)
            # 路径A(趋势): BTC跌破N周MA = 熊市信号(抓2018/2022暴跌)
            ma_open = False
            if short_ma_eff > 0 and t >= short_ma_eff:
                btc_hist = px['BTC'].iloc[t - short_ma_eff + 1: t + 1].dropna()
                if len(btc_hist) >= short_ma_eff:
                    ma_val = float(btc_hist.mean())
                    btc_now = float(btc_hist.iloc[-1])
                    if btc_now < ma_val:  # BTC跌破MA = 趋势向下
                        ma_open = True
            # 路径B(周期门控+高位滞涨确认): 仅作见顶区内的"提前武装"补充触发
            stall_open = False
            if armed and _is_high_stalled(px, t, cfg.short_stall_lookback,
                                          cfg.short_stall_pct, cfg.short_stall_nohigh_weeks):
                stall_open = True
            # 见顶区内: 任一确认信号(趋势破位 或 滞涨)都开空, 且用1年LEAPS
            cycle_open = armed and (ma_open or stall_open)
            dte_use = cfg.short_cycle_dte_weeks if cycle_open else cfg.short_dte_weeks
            if ma_open or cycle_open:
                exist_short = sum(s.size_ratio for s in active_shorts)
                allow = max(0.0, 0.80 - exist_short)
                p_size = min(short_size_eff, allow)
                if p_size > 0.001:
                    if cfg.short_split:
                        for under_half in ['BTC', 'ETH']:
                            u0 = price_for(px, sectors, under_half, t)
                            if u0 and u0 > 0:
                                active_shorts.append(ShortLeg(
                                    underlying=under_half,
                                    dte_left=dte_use, dte_total=dte_use,
                                    entry_price=float(u0), size_ratio=p_size * 0.5,
                                    cycle_hedge=cycle_open,
                                ))
                    else:
                        under = cfg.short_underlying
                        u0 = price_for(px, sectors, under, t)
                        if u0 and u0 > 0:
                            active_shorts.append(ShortLeg(
                                underlying=under,
                                dte_left=dte_use, dte_total=dte_use,
                                entry_price=float(u0), size_ratio=p_size,
                                cycle_hedge=cycle_open,
                            ))
                    proactive_short_cd = cfg.short_proactive_cooldown

        if proactive_short_cd > 0:
            proactive_short_cd -= 1

        # ---- 3. 冷却期计数 & 新目标权重 ----
        for cs in coin_state.values():
            if cs.cooldown_left > 0:
                cs.cooldown_left -= 1
                rec.cooldown_locked += 1

        built = _build_target(px, t, cfg, coin_state, sectors,
                              cyc_scale_fn=_cyc_fn, cycle_tilt=cycle_tilt, prev_w=w)
        if built is None:
            recs.append(rec); continue
        target, regime = built
        rec.regime = regime

        # ---- 3.5 减半周期预判性减仓（时间刻避险）----
        # 见顶期/暴跌期主动把风险仓位缩到 risk_scale_eff, 释放的权重转STABLE现金
        if risk_scale_eff < 1.0:
            risky = sum(v for k, v in target.items() if k != STABLE)
            if risky > 0:
                if getattr(cfg, 'halving_derisk_offense_first', False):
                    # 差别减仓: 进攻山寨砍到 off_s, 防御核(BTC/ETH)砍到 def_s, 差额转现金
                    off_s = float(getattr(cfg, 'halving_offense_scale', 0.0))
                    def_s = float(getattr(cfg, 'halving_defense_scale', 1.0))
                    new_target, freed = {}, 0.0
                    for k, v in target.items():
                        if k == STABLE:
                            continue
                        sc = def_s if k in DEFENSE_CORE else off_s
                        new_target[k] = v * sc
                        freed += v * (1.0 - sc)
                    new_target[STABLE] = target.get(STABLE, 0.0) + freed
                    target = new_target
                else:
                    new_target = {STABLE: target.get(STABLE, 0.0) + risky * (1.0 - risk_scale_eff)}
                    for k, v in target.items():
                        if k != STABLE:
                            new_target[k] = v * risk_scale_eff
                    target = new_target

        # ---- 4. Crash Guard（可选） ----
        if cfg.crash_guard:
            run_max = nav[: t + 1].max()
            dd = nav[t] / run_max - 1.0
            thr = cfg.crash_guard.get('thr', -0.15)
            floor = cfg.crash_guard.get('floor', 0.0)
            if dd < thr:
                crash_weeks += 1
                risky = sum(v for k, v in target.items() if k != STABLE)
                scale = min(1.0, floor / risky) if risky > 0 else 0.0
                new_target = {STABLE: 1.0 - risky * scale}
                for k, v in target.items():
                    if k != STABLE: new_target[k] = v * scale
                target = new_target

        # ---- 5. Vol Target（可选） ----
        if cfg.vol_target and t >= WARMUP:
            rets = np.diff(nav[max(0, t - WARMUP): t + 1]) / nav[max(0, t - WARMUP): t]
            if len(rets) >= 20:
                ann_vol = np.std(rets) * np.sqrt(52)
                if ann_vol > cfg.vol_target and ann_vol > 0:
                    risky = sum(v for k, v in target.items() if k != STABLE)
                    scale = min(1.0, cfg.vol_target / ann_vol)
                    new_target = {STABLE: 1.0 - risky * scale}
                    for k, v in target.items():
                        if k != STABLE: new_target[k] = v * scale
                    target = new_target

        # ---- 6. 再平衡 & 更新 entry_price / coin_state ----
        # 清理已清零或权重为0的币的active_call（被行权的已经处理）
        for coin in list(w.keys()):
            if coin == STABLE: continue
            if (coin not in target or target.get(coin, 0) == 0) and w.get(coin, 0) > 0:
                # 换币清仓：entry_price 下次买时重置；call 没到期也视为平仓（call权利金已落袋，就不再追了）
                if coin in coin_state:
                    if coin_state[coin].active_call and coin_state[coin].active_call.assigned:
                        pass  # 已经处理过
                    coin_state[coin].active_call = None
        # 新进买入的币，设 entry_price
        for coin, t_wt in target.items():
            if coin == STABLE or t_wt <= 0: continue
            if coin not in coin_state:
                coin_state[coin] = CoinState()
            cs = coin_state[coin]
            if cs.entry_price <= 0 or w.get(coin, 0) <= 0:
                # 首次买入或清仓后再买回：entry 重置
                p = px[coin].iloc[t] if coin in px.columns else None
                if p and pd.notna(p):
                    cs.entry_price = float(p)
                    cs.entry_week = t

        turnover = sum(abs(target.get(k, 0) - w.get(k, 0)) for k in set(target) | set(w))
        cost = turnover * cfg.cost_bps
        nav[t] *= (1.0 - cost)
        w = target
        if record_holdings:
            rec.held = dict(w)
        rec.nav = nav[t]
        recs.append(rec)

    # ---- 指标 ----
    nav_series = pd.Series(nav, index=px.index, name=label)
    multiple = float(nav[-1] / nav[0])
    weeks = n - 1
    cagr = float((nav[-1] / nav[0]) ** (52.0 / weeks) - 1.0) if weeks > 0 else 0.0
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1.0
    mdd = float(dd.min())
    rets = pd.Series(nav[1:] / nav[:-1] - 1.0)
    sharpe = float(rets.mean() / rets.std() * np.sqrt(52)) if rets.std() > 0 else 0.0

    # ---- 事件汇总 ----
    total_tp = sum(r.tp_count for r in recs)
    total_assigned = sum(r.assigned_count for r in recs)
    total_ovl = sum(r.ovl_count for r in recs)
    put_income_navpct = sum(r.put_payout_income for r in recs) / weeks if weeks > 0 else 0
    call_income_navpct = sum(r.call_premium_income for r in recs) / weeks if weeks > 0 else 0
    short_income_navpct = sum(r.short_pnl for r in recs) / weeks if weeks > 0 else 0

    return {
        'label': label, 'multiple': multiple, 'cagr': cagr, 'mdd': mdd, 'sharpe': sharpe,
        'nav': nav_series, 'weeks': weeks, 'crash_weeks': crash_weeks,
        'regimes': [r.regime for r in recs], 'recs': recs if return_recs else None,
        'events': {
            'tp_calls': total_tp,
            'assigned_calls': total_assigned,
            'ovl_calls': total_ovl,
            'avg_call_income_pw': call_income_navpct * 100,
            'avg_put_income_pw': put_income_navpct * 100,
            'avg_short_pnl_pw': short_income_navpct * 100,
            'cooldown_locked_total': sum(r.cooldown_locked for r in recs),
        },
    }


def _build_target(px, t_idx, cfg, coin_state, sectors,
                 cyc_scale_fn=None, cycle_tilt=0.5, prev_w=None):
    """构造 t_idx 的目标权重 (防御+进攻+稳定币)。严格只用<=t数据；冷却期的币不选入。"""
    date_t = px.index[t_idx]
    year = date_t.year
    btc_series = px['BTC'].iloc[: t_idx + 1].dropna()
    if len(btc_series) < ca2.REGIME_PARAMS['ma_window']:
        return None
    ma10 = float(btc_series.iloc[-ca2.REGIME_PARAMS['ma_window']:].mean())
    btc_t = float(btc_series.iloc[-1])
    regime = ca2.detect_regime(btc_t, ma10)
    alloc = ca2.REGIME_ALLOC[regime]
    # 进攻仓位比例乘子(2026-08-13 优化: 池子精简后提高进攻敞口; 1.0=原版)
    _om = float(getattr(cfg, 'alloc_offense_mult', 1.0))
    if _om != 1.0:
        _off_new = min(1.0, alloc['offense'] * _om)
        _freed = _off_new - alloc['offense']   # 增加的进攻仓位从现金里扣
        alloc = dict(alloc, offense=_off_new,
                     stable=max(0.0, alloc.get('stable', 0.0) - _freed))

    avail = set(c for c in px.columns if pd.notna(px[c].iloc[t_idx]) and px[c].iloc[t_idx] not in (0, None))
    if cfg.enabled_cooldown:
        cooldown_lock = {c for c, cs in coin_state.items() if cs.cooldown_left > 0}
        avail = avail - cooldown_lock
    else:
        cooldown_lock = set()

    # 防御核（BTC/ETH），冷却不禁防御核
    dw = ca2.defense_weights()
    dw = {k: v for k, v in dw.items() if k in set(c for c in px.columns if pd.notna(px[c].iloc[t_idx]) and px[c].iloc[t_idx] not in (0, None))}
    s = sum(dw.values())
    if s <= 0: return None
    dw = {k: v / s for k, v in dw.items()}
    defense_w = {k: v * alloc['defense'] for k, v in dw.items()}

    # 进攻 Top-N（冷却期的币直接不参与）
    valid_off = [c for c in ca2.OFFENSE_COINS if c in avail]
    # 分阶段选币: 先计算减半周期相位(无后视), 再根据相位决定期权约束+选币数
    eff_n = cfg.offense_n
    sel_phase = None
    if getattr(cfg, 'halving_cycle_enabled', False) and getattr(cfg, 'offense_phase_selection', True):
        sel_phase, _, _ = halving_cycle_phase(
            date_t, pre_halving_start_month=cfg.pre_halving_start_month)
        # euphoria期扩仓: 从3扩到offense_n_euphoria, 抓住山寨轮动行情
        if sel_phase == 'euphoria' and getattr(cfg, 'offense_n_euphoria', None):
            eff_n = cfg.offense_n_euphoria
    # 期权约束按相位动态切换:
    # euphoria(狂热)/crash(暴跌)/bear_bottom(筑底) → 全放开, 山寨周期同步
    # accumulation(积累)/pre_halving(预热) → 保留期权约束, 小币流动性差需稳健
    filter_phases = getattr(cfg, 'option_filter_phases', ())
    if sel_phase in filter_phases:
        valid_off = [c for c in valid_off if c in OPTIONS_AVAILABLE_COINS]
    off_w = {}
    if alloc['offense'] > 0 and valid_off and t_idx >= WARMUP:
        top, scores = ca2.offense_top_n(year, n=eff_n, valid=set(valid_off),
                                        px=px, as_of=date_t, phase=sel_phase,
                                        return_scores=True,
                                        norm=getattr(cfg, 'theme_weight_norm', 'avail'))
        top = [c for c in top if c in avail][:eff_n]
        if top:
            wmode = getattr(cfg, 'offense_weight_mode', 'equal')
            if wmode == 'score':
                # 分数加权: 用选币综合分(赛道相位×动量)归一化分配进攻仓, 高确定性币多拿仓位
                raw = [max(float(scores.get(c, 0.0)), 0.0) for c in top]
                s_sum = sum(raw)
                if s_sum > 0:
                    off_w = {c: alloc['offense'] * (rw / s_sum) for c, rw in zip(top, raw)}
                else:
                    each = alloc['offense'] / len(top)
                    off_w = {c: each for c in top}
            elif wmode == 'inv_vol':
                # 逆波动率(风险平价)加权: 近52周收益波动率越小 -> 权重越大, 压小币集中风险
                inv = []
                for c in top:
                    ser = px[c].iloc[max(0, t_idx - 52): t_idx + 1].dropna()
                    if len(ser) >= 20:
                        rets = ser.pct_change().dropna()
                        v = float(rets.std()) if len(rets) else 1.0
                    else:
                        v = 1.0
                    inv.append(1.0 / max(v, 1e-6))
                s_sum = sum(inv)
                off_w = {c: alloc['offense'] * (iv / s_sum) for c, iv in zip(top, inv)}
            else:
                each = alloc['offense'] / len(top)
                off_w = {c: each for c in top}

    # 山寨相对强度门控: ALT/BTC 比值破 MA => 缩进攻仓 (只用 <=t 数据, 无前视)
    if getattr(cfg, 'alt_rs_gate', False) and off_w:
        _ma = int(getattr(cfg, 'alt_rs_ma', 20))
        if t_idx >= _ma:
            _tk = _timing_cols(px, cfg, prev_w)
            _rs = _alt_rs_ratio(px, _tk)
            _cur = _rs.iloc[t_idx]
            _mav = _rs.iloc[t_idx - _ma + 1: t_idx + 1].mean()
            if pd.notna(_cur) and pd.notna(_mav) and _cur < _mav:
                _sc = float(getattr(cfg, 'alt_rs_scale', 0.0))
                _freed = sum(off_w.values()) * (1.0 - _sc)
                off_w = {k: v * _sc for k, v in off_w.items()}
                if getattr(cfg, 'alt_rs_to_defense', False) and defense_w:
                    _ds = sum(defense_w.values())
                    if _ds > 0:
                        defense_w = {k: v + _freed * (v / _ds) for k, v in defense_w.items()}
                        _freed = 0.0
                alloc = dict(alloc)
                alloc['stable'] = alloc.get('stable', 0.0) + _freed

    target = {}
    target.update(defense_w)
    target.update(off_w)
    target[STABLE] = alloc['stable']
    # 12 层周期叠加: 缩放进攻权重, 差额从稳定币(STABLE)匀取(额度守恒, 无隐性杠杆)
    if cyc_scale_fn is not None and off_w:
        from cycles.overlay import apply_to_crypto_target
        cyc_scale = cyc_scale_fn(date_t.strftime('%Y-%m-%d'), cycle_tilt)
        if cyc_scale != 1.0:
            off_w, _stable = apply_to_crypto_target(off_w, target[STABLE], cyc_scale)
            target[STABLE] = _stable
            target.update(off_w)
    # 归一
    tot = sum(target.values())
    if tot <= 0: return None
    target = {k: v / tot for k, v in target.items()}
    return target, regime


# ========== CLI ==========
def _load_default():
    path = os.path.join(DATA, 'weekly_adjclose_crypto50.csv')
    if not os.path.exists(path):
        for f in os.listdir(DATA):
            if 'crypto50' in f and f.endswith('.csv'):
                path = os.path.join(DATA, f)
                break
    return pd.read_csv(path, index_col=0, parse_dates=True).sort_index()


def _fmt(x, pct=False, pct_dec=1):
    if pct: return f'{x*100:>{6+pct_dec}.{pct_dec}f}%'
    if abs(x) >= 1000: return f'{x:>8.0f}'
    if abs(x) >= 100:  return f'{x:>8.1f}'
    return f'{x:>8.2f}'


def main():
    ap = argparse.ArgumentParser(description='Crypto50 回测 V6（期权三件套版）')
    ap.add_argument('--data', type=str, default=None)
    ap.add_argument('--baseline', action='store_true', help='同时跑 V5 原版 baseline 做对比')
    ap.add_argument('--scan', action='store_true', help='跑参数扫描（止盈线/冷却/做空标的）')
    ap.add_argument('--offense-n', type=int, default=3)
    ap.add_argument('--take-profit', type=float, default=None, help='take_profit_pct 小数 1.0=100%%')
    ap.add_argument('--no-call', dest='no_call', action='store_true')
    ap.add_argument('--no-put', dest='no_put', action='store_true')
    ap.add_argument('--no-short', dest='no_short', action='store_true')
    ap.add_argument('--no-ovl', dest='no_ovl', action='store_true')
    ap.add_argument('--short-underlying', type=str, default=None)
    ap.add_argument('--cooldown', type=int, default=None)
    args = ap.parse_args()

    px = pd.read_csv(args.data, index_col=0, parse_dates=True).sort_index() if args.data else _load_default()
    print(f'\n=== Crypto50 V6 期权三件套回测  ({px.shape[0]}周 {px.shape[1]}币  {px.index[0].date()}~{px.index[-1].date()}) ===')

    rows = []

    # --- baseline V5 ---
    if args.baseline:
        from backtest_v2 import run_backtest
        r_bl = run_backtest(px, cost_bps=0.001, label='V5_baseline(Top3纯动量)',
                            offense_n=args.offense_n)
        rows.append((r_bl['label'], r_bl['multiple'], r_bl['cagr'], r_bl['mdd'], r_bl['sharpe'], {}))

    # --- V6 默认三件套 ---
    cfg = dict(DEFAULT_CFG)
    cfg['offense_n'] = args.offense_n
    if args.take_profit is not None: cfg['take_profit_pct'] = args.take_profit
    if args.no_call: cfg['enabled_call'] = False
    if args.no_put:  cfg['enabled_put']  = False
    if args.no_short:cfg['enabled_short']= False
    if args.no_ovl:  cfg['enabled_ovl']  = False
    if args.short_underlying: cfg['short_underlying'] = args.short_underlying
    if args.cooldown is not None: cfg['cooldown_weeks'] = args.cooldown
    r = run_bt(px, cfg, label='V6(三件套全默认)')
    rows.append((r['label'], r['multiple'], r['cagr'], r['mdd'], r['sharpe'], r['events']))

    # --- 参数扫描 ---
    if args.scan:
        print('\n=== 参数扫描（take_profit / cooldown / 做空标的）===')
        scan_rows = []
        tps = [0.8, 1.0, 1.5, 2.0]
        cds = [4, 8, 13]
        sus = ['BTC', 'ETH', 'BIGCAP_INDEX', 'L1_INDEX']
        for tp in tps:
            for cd in cds:
                for su in sus:
                    c = dict(DEFAULT_CFG)
                    c['offense_n'] = args.offense_n
                    c['take_profit_pct'] = tp
                    c['cooldown_weeks'] = cd
                    c['short_underlying'] = su
                    rr = run_bt(px, c, label=f'TP{tp:.0%}_CD{cd}w_SU={su[:4]}')
                    scan_rows.append((rr['label'], rr['multiple'], rr['cagr'], rr['mdd'], rr['sharpe']))
        scan_rows.sort(key=lambda x: x[1], reverse=True)
        print(f"  {'label':<28}{'倍数':>8}{'CAGR':>8}{'MDD':>8}{'Sharpe':>8}")
        print('  ' + '-' * 62)
        for lbl, m, cg, md, sh in scan_rows[:12]:
            print(f"  {lbl:<28}{m:>7.1f}x{cg*100:>7.1f}%{md*100:>7.1f}%{sh:>8.2f}")
        print(f"\n  (Top12 by 倍数；共{len(scan_rows)}组)")

    # --- 打印主表 ---
    print(f"\n  {'label':<32}{'倍数':>10}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}   事件(止盈/行权/高估call / 周均call%/put%/short% / 冷却锁周)")
    print('  ' + '-' * 118)
    for lbl, m, cg, md, sh, ev in rows:
        if ev:
            ev_str = f"{ev['tp_calls']:>3}/{ev['assigned_calls']:>3}/{ev['ovl_calls']:>3}   call+{ev['avg_call_income_pw']:.3f}%  put+{ev['avg_put_income_pw']:.3f}%  short+{ev['avg_short_pnl_pw']:.3f}%  cool{ev['cooldown_locked_total']:>4}"
        else:
            ev_str = ' (V5 baseline 无期权)'
        print(f"  {lbl:<32}{m:>8.1f}x{cg*100:>8.1f}%{md*100:>8.1f}%{sh:>8.2f}   {ev_str}")

    print(f"\n  诚实口径: weekly_adjclose_crypto50.csv = Binance/OKX 真实周K, 现存主流币(含幸存者偏差)")
    print(f"  V6默认: TP=+{cfg.get('take_profit_pct',1.0):.0%}  callPrem18%/a  put(大盘10%→60%)  做空26w{cfg.get('short_underlying','BIGCAP')}  cooldown{cfg.get('cooldown_weeks',8)}w  slippage{cfg.get('cost_bps',0.002)*10000:.0f}bps")


if __name__ == '__main__':
    main()
