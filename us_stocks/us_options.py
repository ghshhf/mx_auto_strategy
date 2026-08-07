"""美股期权覆盖层(阶段2 实现, 阶段1 空壳)。

阶段1: 所有函数返回 None, run_optimized 走纯现货逻辑。
阶段2: 拉 yfinance option_chain, 实现 covered call / protective put。

设计哲学(用户原话):
  - 远期 OTM put (LEAPS) 套保: "虚值特别虚, 特别便宜", 崩盘时暴涨对冲组合回撤
  - Covered call at 止盈价: "100 美元时卖出 150 美元, 刚好 150 是止盈线",
    行权价=止盈价, 到期被行权即按止盈价交割, 不到则收权利金
  - 期权是缺失的非对称 payoff 工具, 现货止损无法替代

阶段2 实施时只需实现本文件三个函数, run_optimized 主循环结构不变。
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class CoveredCall:
    """备兑看涨期权(阶段2 实现)。"""
    underlying: str        # 标的代码
    strike: float          # 行权价(=止盈价)
    expiry: date           # 到期日(远期 LEAPS)
    premium: float         # 权利金(阶段2 从 yfinance option_chain 拉)
    contracts: int         # 张数(每张 100 股)


@dataclass
class ProtectivePut:
    """保护性看跌期权(阶段2 实现)。"""
    underlying: str        # 标的代码(SPY/QQQ 大盘指数 ETF)
    strike: float          # 行权价(OTM, 低于现货)
    expiry: date           # 到期日(远期 LEAPS)
    premium: float         # 权利金
    contracts: int         # 张数


def covered_call_at_take_profit(code: str, strike: float,
                                  cfg: dict) -> Optional[CoveredCall]:
    """止盈触发时调用。

    阶段1: 返回 None = 纯现货清仓。
    阶段2: 拉 yfinance option_chain(code), 选 LEAPS 远月到期,
           找 strike 最接近的 OTM call, 返回 CoveredCall。
           run_optimized 收到后: 卖 call 收权利金, 留仓等被行权(按止盈价交割)。
    """
    return None  # 阶段1 占位


def protective_put_for_hedge(code: str, spot: float,
                               cfg: dict) -> Optional[ProtectivePut]:
    """高位套保时调用。

    阶段1: 返回 None = 不套保。
    阶段2: 拉 yfinance option_chain(SPY/QQQ), 选 LEAPS 远月到期,
           找 OTM put (strike = spot × (1 - otm_pct), 默认 otm_pct=0.10),
           返回 ProtectivePut。run_optimized 收到后: 买 put 付权利金,
           崩盘时 put 暴涨对冲组合回撤。
    """
    return None  # 阶段1 占位
