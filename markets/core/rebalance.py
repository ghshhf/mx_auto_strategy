# -*- coding: utf-8 -*-
"""
🔒 配对/多标的等权再平衡 —— **唯一引擎真源** (single source of truth)

历史背景 (2026-09-15 收敛):
  原先存在**两份并行实现**:
    · markets/crypto/crypto_btc_ada_pair.py :: sim()      (65 行, 逐点盯市 + 换手/序列)
    · markets/ashare/ashare_pair_all.py     :: sim_pair() (28 行, 向量化盯市)
    · markets/ashare/ashare_pair_50_50.py   :: sim_pair() (与 all 那份等价的第三份)
  经 AST 归一化 + 合成数据对账确认: **三者核心算法完全一致**, 差异只在
  ① 返回契约不同 ② 盯市写法(逐点 vs 向量化) ③ 是否记录逐期币量/换手。
  ⇒ 但只要以后改一处忘了另一处, 跨市场数字就不可比, 且**没有任何测试会报错**。
  ⇒ 因此收敛为本文件; 各市场的 sim/sim_pair 退化成**薄包装**, 保留原返回契约。

算法 (等权 w = ones(n)/n, 每 rebal_weeks 期调仓, 单边 cost_bp 费率):
  - 调仓点 k: 目标份额 tgt = tot·w/p_k;  成交额 traded = |tgt − units|·p_k
  - 手续费按成交额扣, **同比例缩减总仓位**: units = tgt·(tot − fee)/tot
  - 段内盯市 NAV_t = Σ units·p_t   (units 在段内不变)

⚠️ 修改本文件的任何数值逻辑, 都必须同步跑:
     pytest tests/test_rebalance_engine_parity.py
  该测试锁死「三市场同输入同输出」。
"""

import numpy as np

__all__ = ["rebalance_kernel", "rebalance_step",
           "DEFAULT_REBAL_WEEKS", "DEFAULT_COST_BP"]

DEFAULT_REBAL_WEEKS = 4      # 月度
DEFAULT_COST_BP = 10.0       # 单边 10bp


def rebalance_step(units, p, w, c):
    """**单次调仓** —— 全仓唯一的调仓数学, 任何变体都必须走这里。

    参数
    ----
    units : (n,)  调仓前份额
    p     : (n,)  调仓时点价格
    w     : (n,)  目标权重 (等权 = ones(n)/n)
    c     : float 单边费率 (小数, 非 bp)

    返回 (new_units, traded_notional, turnover_ratio)
    """
    val = units * p
    tot = float(val.sum())
    tgt = tot * w / p
    traded = float(np.abs(tgt - units).dot(p))
    fee = traded * c
    new_units = tgt * ((tot - fee) / tot) if tot > 0 else tgt
    return new_units, traded, (traded / tot if tot > 0 else 0.0)


def rebalance_kernel(pr, rebal_weeks=DEFAULT_REBAL_WEEKS, cost_bp=0.0,
                     capital=1.0, track=False, phase=None, track_trades=False):
    """等权周期再平衡内核。

    参数
    ----
    pr : (T, n) array-like   价格矩阵 (行=期, 列=标的)
    rebal_weeks : int        每隔多少期调仓一次
    cost_bp : float          单边费率 (bp), 按成交额扣
    capital : float          初始资金 (只影响 NAV 量级, 不影响任何倍数/比率)
    track : bool             记录逐期币量倍数 R_hist
    phase : int or None      首个调仓日 (None → rebal_weeks)。**相位检验**用:
                             调仓日 = phase, phase+rebal_weeks, ...
    track_trades : bool      记录每次调仓的 (时点/调仓前份额/调仓后份额/价格)

    返回 dict
    --------
    units    (n,)   期末份额
    U0       (n,)   期初份额
    NAV      (T,)   逐期组合净值 (初始 = capital)
    R_hist   (T,n)  or None   逐期币量倍数 (track=True)
    turns    list   每次调仓的换手率 (占组合价值)
    ntr      int    调仓次数
    w        (n,)   目标权重
    steps    list   or None   逐次调仓明细 (track_trades=True)
    """
    pr = np.asarray(pr, dtype=float)
    T, n = pr.shape
    w = np.ones(n) / n
    c = cost_bp / 1e4

    units = (w * capital) / pr[0]
    U0 = units.copy()
    # 用 capital 兜底而非 np.empty: 相位版(phase=0)首格可能不被任何段覆盖,
    # 未初始化的 np.empty 会读到垃圾内存。未盯市时按「初始投入」计价是对的。
    NAV = np.full(T, float(capital))
    R_hist = np.empty((T, n)) if track else None
    turns = []
    steps = [] if track_trades else None
    ntr = 0
    seg = 0
    start_k = rebal_weeks if phase is None else phase

    for k in list(range(start_k, T, rebal_weeks)) + [T]:
        seg_end = min(k, T)
        if seg_end > seg:                                  # 段内盯市
            NAV[seg:seg_end] = (units[None, :] * pr[seg:seg_end]).sum(axis=1)
            if track:
                R_hist[seg:seg_end] = units / U0
        if k < T:                                          # 调仓
            before = units
            units, traded, ratio = rebalance_step(units, pr[k], w, c)
            turns.append(ratio)
            if track_trades:
                steps.append(dict(k=k, units_before=before.copy(),
                                  units_after=units.copy(), price=pr[k].copy(),
                                  traded=traded, turnover=ratio))
            ntr += 1
            seg = k

    return dict(units=units, U0=U0, NAV=NAV, R_hist=R_hist,
                turns=turns, ntr=ntr, w=w, steps=steps)
