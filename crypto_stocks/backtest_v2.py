"""
backtest_v2.py - 加密 Crypto50 回测引擎 (V5 设计, 重建版)
================================================================

消费 weekly_adjclose CSV (周频收盘价, 列=代币), 复刻 crypto_adoption_v2.py 的设计:

  - 防御核: BTC/ETH/OKB, 按 defense_weights() 长期持有, 周频再平衡回目标权重
  - 进攻:   每期从 OFFENSE_COINS 选 Top-N (动量 × 相位, 见 offense_top_n)
  - 四档市况 REGIME_ALLOC (BTC 价格偏离 MA10)
  - Crash Guard: 组合回撤超过阈值 -> 砍仓转稳定币 (STABLE)
  - Vol Target: 组合年化波动超过目标 -> 超额敞口转稳定币
  - cost_bps:   单边交易成本 (手续费 + 滑点)

★ 前视防护 (关键):
   选币 / 市况判定 / 动量回看 全部只使用 t 及之前的数据 (as_of=date_t,
   动量回看 [idx-52, idx])。绝不使用未来信息。

★ 数据诚实性:
   本引擎消费 CSV, 真/假数据格式相同。若喂入合成数据, 产出数字**不可信**;
   只有喂入 Binance/OKX 真实周频收盘价时, 倍数才有意义。详见 README 真相化章节。

接口 (供 realistic_validation.py / 独立运行):
   run_backtest(px, cost_bps=0.001, label='', vol_target=None,
                crash_guard=None, offense_n=3, start=None) -> dict
   返回 {label, multiple, cagr, mdd, sharpe, nav(pd.Series), weekly_ret, ...}

用法:
   python3 backtest_v2.py                # 用默认 crypto50 csv 跑 V5 默认配置
   python3 backtest_v2.py --offense-n 5  # 改进攻选币数
"""
import os
import sys
import argparse
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')

sys.path.insert(0, HERE)
import crypto_adoption_v2 as ca2

# 回看窗口: MA10(10) + 动量(52) -> 取 52 周预热
WARMUP = 52
STABLE = 'STABLE'   # 稳定币/现金占位列 (收益恒为 0)


def _available(px, t_idx):
    """t_idx 时刻有有效收盘价的代币集合 (排除 NaN / 0)."""
    row = px.iloc[t_idx]
    return set(c for c in px.columns if pd.notna(row.get(c)) and row.get(c) not in (0, None))


def build_target_weights(px, t_idx, offense_n=3):
    """构造 t_idx 周的目标权重 (防御 + 进攻 + 稳定币), 严格只用 <=t 数据."""
    date_t = px.index[t_idx]
    year = date_t.year
    btc_series = px['BTC'].iloc[: t_idx + 1].dropna()
    if len(btc_series) < ca2.REGIME_PARAMS['ma_window']:
        return None
    ma10 = float(btc_series.iloc[-ca2.REGIME_PARAMS['ma_window']:].mean())
    btc_t = float(btc_series.iloc[-1])
    regime = ca2.detect_regime(btc_t, ma10)
    alloc = ca2.REGIME_ALLOC[regime]

    avail = _available(px, t_idx)

    # ---- 防御核 ----
    dw = ca2.defense_weights()            # {BTC:.5, ETH:.3, OKB:.2}
    dw = {k: v for k, v in dw.items() if k in avail}
    s = sum(dw.values())
    if s <= 0:
        return None
    dw = {k: v / s for k, v in dw.items()}      # 归一化 (上市前缺币则重配)
    defense_w = {k: v * alloc['defense'] for k, v in dw.items()}

    # ---- 进攻 Top-N ----
    valid_off = [c for c in ca2.OFFENSE_COINS if c in avail]
    off_w = {}
    if alloc['offense'] > 0 and valid_off and t_idx >= WARMUP:
        top = ca2.offense_top_n(year, n=offense_n, valid=set(valid_off),
                                px=px, as_of=date_t)
        top = [c for c in top if c in avail][:offense_n]
        if top:
            each = alloc['offense'] / len(top)
            off_w = {c: each for c in top}

    # ---- 稳定币 ----
    target = {}
    target.update(defense_w)
    target.update(off_w)
    target[STABLE] = alloc['stable']
    return target, regime


def run_backtest(px, cost_bps=0.001, label='V5', vol_target=None,
                 crash_guard=None, offense_n=3, start=None):
    """
    周频回测主循环。

    参数:
      px          : DataFrame, 索引=周日期, 列=代币(收盘价), 可选含 STABLE(否则视为现金收益0)
      cost_bps    : 单边成本 (小数, 0.001 = 10 bps)
      vol_target  : 年化波动目标 (如 0.60); None=不启用
      crash_guard : dict {'mode':'self', 'thr':-0.15, 'floor':0.40}; None=不启用
                    thr=触发砍仓的组合回撤阈值; floor=砍后保留的风险敞口上限(其余转稳定币)
      offense_n   : 进攻选币数
      start       : 起始日期 (可选)

    返回 dict (含 nav: pd.Series)。
    """
    px = px.sort_index()
    if start is not None:
        px = px[px.index >= pd.Timestamp(start)]
    px = px.dropna(how='all')
    n = len(px)
    if n < WARMUP + 2:
        raise ValueError(f"数据不足: 需 >{WARMUP} 周, 仅 {n} 周")

    nav = np.ones(n)
    w = None                        # 当前持仓权重 (进入每周时)
    regimes = []
    crash_weeks = 0

    for t in range(1, n):
        prev = px.iloc[t - 1]
        cur = px.iloc[t]

        # ---- 1. 用上周权重计算本周组合收益 ----
        if w is None:
            # 首周建仓: 用目标权重作为初始权重, 不计成本
            built = build_target_weights(px, t, offense_n)
            if built is None:
                nav[t] = nav[t - 1]
                regimes.append('flat')
                continue
            w, _ = built

        r = 0.0
        for coin, wt in w.items():
            if coin == STABLE:
                continue
            p0 = prev.get(coin)
            p1 = cur.get(coin)
            if pd.isna(p0) or pd.isna(p1) or p0 in (0, None):
                # 持仓币本周无价 -> 该权重视为转稳定币 (收益0), 不贡献
                continue
            r += wt * (p1 / p0 - 1.0)
        nav[t] = nav[t - 1] * (1.0 + r)

        # ---- 2. 计算本周目标权重 ----
        built = build_target_weights(px, t, offense_n)
        if built is None:
            regimes.append('flat')
            continue
        target, regime = built
        regimes.append(regime)

        # ---- 3. Crash Guard ----
        if crash_guard is not None:
            run_max = nav[: t + 1].max()
            dd = nav[t] / run_max - 1.0
            thr = crash_guard.get('thr', -0.15)
            floor = crash_guard.get('floor', 0.0)
            if dd < thr:
                crash_weeks += 1
                risky = sum(v for k, v in target.items() if k != STABLE)
                # 砍仓: 风险敞口压到 floor, 其余转稳定币
                scale = min(1.0, floor / risky) if risky > 0 else 0.0
                new_target = {STABLE: 1.0 - risky * scale}
                for k, v in target.items():
                    if k != STABLE:
                        new_target[k] = v * scale
                target = new_target

        # ---- 4. Vol Target ----
        if vol_target is not None and t >= WARMUP:
            rets = np.diff(nav[max(0, t - WARMUP): t + 1]) / nav[max(0, t - WARMUP): t]
            if len(rets) >= 20:
                ann_vol = np.std(rets) * np.sqrt(52)
                if ann_vol > vol_target and ann_vol > 0:
                    risky = sum(v for k, v in target.items() if k != STABLE)
                    scale = min(1.0, vol_target / ann_vol)
                    new_target = {STABLE: 1.0 - risky * scale}
                    for k, v in target.items():
                        if k != STABLE:
                            new_target[k] = v * scale
                    target = new_target

        # ---- 5. 再平衡 + 成本 ----
        turnover = sum(abs(target.get(k, 0) - w.get(k, 0))
                        for k in set(target) | set(w))
        cost = turnover * cost_bps
        nav[t] *= (1.0 - cost)
        w = target

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

    return {
        'label': label,
        'multiple': multiple,
        'cagr': cagr,
        'mdd': mdd,
        'sharpe': sharpe,
        'nav': nav_series,
        'weeks': weeks,
        'crash_weeks': crash_weeks,
        'regimes': regimes,
    }


def _load_default():
    path = os.path.join(DATA, 'weekly_adjclose_crypto50.csv')
    if not os.path.exists(path):
        alt = os.path.join(DATA, 'weekly_adjclose_crypto50_v3.csv')
        path = alt if os.path.exists(alt) else path
    return pd.read_csv(path, index_col=0, parse_dates=True).sort_index()


def main():
    ap = argparse.ArgumentParser(description="加密 Crypto50 回测引擎 (重建版)")
    ap.add_argument('--data', type=str, default=None, help='周频收盘价CSV')
    ap.add_argument('--cost-bps', type=float, default=0.001, help='单边成本(小数)')
    ap.add_argument('--offense-n', type=int, default=3, help='进攻选币数')
    ap.add_argument('--vol-target', type=float, default=None, help='年化波动目标(如0.60)')
    ap.add_argument('--crash-thr', type=float, default=None,
                    help='Crash Guard回撤阈值(如-0.15)')
    ap.add_argument('--crash-floor', type=float, default=0.40, help='Crash后保留风险敞口')
    args = ap.parse_args()

    px = pd.read_csv(args.data, index_col=0, parse_dates=True).sort_index() if args.data \
        else _load_default()

    cg = None
    if args.crash_thr is not None:
        cg = {'mode': 'self', 'thr': args.crash_thr, 'floor': args.crash_floor}

    r = run_backtest(px, cost_bps=args.cost_bps, label='V5',
                     vol_target=args.vol_target, crash_guard=cg,
                     offense_n=args.offense_n)
    print(f"\n=== Crypto50 回测 (重建引擎) ===")
    print(f"  数据: {px.shape[0]}周 × {px.shape[1]}币  ({px.index[0].date()}~{px.index[-1].date()})")
    print(f"  配置: cost={args.cost_bps*10000:.0f}bps offense_n={args.offense_n} "
          f"volT={args.vol_target} crash={args.crash_thr}")
    print(f"  {'倍数':>10}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}{'crash周':>8}")
    print(f"  {'-'*55}")
    print(f"  {r['multiple']:>9.1f}x{r['cagr']*100:>8.1f}%{r['mdd']*100:>8.1f}%"
          f"{r['sharpe']:>8.2f}{r['crash_weeks']:>8}")
    print(f"\n  ⚠ 注意: 若数据为合成(generate_synthetic_*), 此数字不可信。")


if __name__ == '__main__':
    main()
