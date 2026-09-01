"""
regime_tune.py - regime 仓位分配 walk-forward 调参 (防过拟合)

杠杆: 每市况(regime)下的 offense/defense/stable 比例, 这是组合最大的权重旋钮。
方法:
  1. 运行时替换 ca2.REGIME_ALLOC (不动基线代码), 沿 strong/flat/weak 三档进攻仓位
     做 3x3x3 = 27 组候选 (extreme_weak 固定进攻=0, 防御核内部分配 60/40 不变)。
  2. 训练窗 2017-2022 按 Sharpe 选最优 (限制 MDD >= -60% 以防极端)。
  3. 测试窗 2022-2026 验证 OOS 是否稳健胜出默认。
  4. 同时跑全样本看整体景观。

关键: 选参只看训练窗, 测试窗结果代表 OOS 泛化, 防止单样本过拟合。
"""
import os
import sys
import itertools
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crypto_options_bt as bt          # noqa: E402
import crypto_adoption_v2 as ca2        # noqa: E402

CSV = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50.csv')
px = pd.read_csv(CSV, index_col=0, parse_dates=True)

TRAIN_END = '2022-01-01'   # 训练窗 = 全样本截断到此
TEST_START = '2022-01-01'  # 测试窗 = 从此开始

# ---- 候选生成 ----
STRONG_OFF = [0.55, 0.65, 0.75]   # 当前默认 0.65
FLAT_OFF   = [0.30, 0.40, 0.50]    # 当前默认 0.40
WEAK_OFF   = [0.10, 0.15, 0.25]    # 当前默认 0.15
STRONG_DEF, FLAT_DEF, WEAK_DEF, EW_DEF = 0.20, 0.35, 0.50, 0.20


def make_alloc(so, fo, wo):
    return {
        'extreme_weak': {'defense': EW_DEF, 'offense': 0.0, 'stable': 1 - EW_DEF},
        'weak':         {'defense': WEAK_DEF, 'offense': wo, 'stable': 1 - WEAK_DEF - wo},
        'flat':         {'defense': FLAT_DEF, 'offense': fo, 'stable': 1 - FLAT_DEF - fo},
        'strong':       {'defense': STRONG_DEF, 'offense': so, 'stable': 1 - STRONG_DEF - so},
    }


def run_with(alloc, px_in):
    ca2.REGIME_ALLOC = alloc
    cfg = dict(bt.DEFAULT_CFG)   # 不触发 offense_weight_mode(默认 equal)
    return bt.run_bt(px_in, cfg_dict=cfg, label='tune')


def main():
    # 默认 alloc (作为基准)
    default_alloc = make_alloc(0.65, 0.40, 0.15)

    # ---- 1. 训练窗 + 全样本 双跑 27 候选 ----
    train_rows, full_rows = [], []
    for so, fo, wo in itertools.product(STRONG_OFF, FLAT_OFF, WEAK_OFF):
        alloc = make_alloc(so, fo, wo)
        tr = run_with(alloc, px[px.index < TRAIN_END])
        fu = run_with(alloc, px)
        train_rows.append((so, fo, wo, tr['multiple'], tr['sharpe'], tr['mdd']))
        full_rows.append((so, fo, wo, fu['multiple'], fu['sharpe'], fu['mdd']))
        print(f"  cand strong_off={so} flat_off={fo} weak_off={wo} | "
              f"train mult={tr['multiple']:.0f}x Sharpe={tr['sharpe']:.2f} | "
              f"full mult={fu['multiple']:.0f}x Sharpe={fu['sharpe']:.2f}")

    # ---- 2. 训练窗选最优 (Sharpe 优先, MDD 限制) ----
    valid = [r for r in train_rows if r[5] >= -0.60]
    best = max(valid, key=lambda r: r[4])
    b_so, b_fo, b_wo = best[0], best[1], best[2]
    print(f"\n[训练窗最优] strong_off={b_so} flat_off={b_fo} weak_off={b_wo} "
          f"train Sharpe={best[4]:.2f} mult={best[3]:.0f}x")

    # ---- 3. 测试窗 OOS 验证: 最优候选 vs 默认 ----
    best_alloc = make_alloc(b_so, b_fo, b_wo)
    best_test = run_with(best_alloc, px[px.index >= TEST_START])
    def_test = run_with(default_alloc, px[px.index >= TEST_START])

    print("\n===== 测试窗 OOS 验证 (2022-2026) =====")
    print(f"{'方案':<22}{'倍数':>10}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}")
    print(f"{'默认(0.65/0.40/0.15)':<22}{def_test['multiple']:>9.0f}x"
          f"{def_test['cagr']*100:>8.1f}%{def_test['mdd']*100:>8.1f}%{def_test['sharpe']:>9.2f}")
    print(f"{'训练最优':<22}{best_test['multiple']:>9.0f}x"
          f"{best_test['cagr']*100:>8.1f}%{best_test['mdd']*100:>8.1f}%{best_test['sharpe']:>9.2f}")
    d_mult = (best_test['multiple'] / def_test['multiple'] - 1) * 100
    d_sh = best_test['sharpe'] - def_test['sharpe']
    verdict = "OOS 胜出 (稳健)" if d_mult > 0 and d_sh >= 0 else "OOS 未胜出 (过拟合警报)"
    print(f"\nOOS Δ倍数={d_mult:+.1f}%  ΔSharpe={d_sh:+.2f}  → {verdict}")

    # ---- 4. 全样本景观: 默认 vs 全样本最优 vs 训练最优 ----
    full_best = max(full_rows, key=lambda r: r[4])
    print("\n===== 全样本景观 =====")
    print(f"默认 mult={run_with(default_alloc, px)['multiple']:.0f}x")
    print(f"全样本 Sharpe 最高候选: strong_off={full_best[0]} flat_off={full_best[1]} "
          f"weak_off={full_best[2]} full mult={full_best[3]:.0f}x Sharpe={full_best[4]:.2f}")
    print("（注: 全样本最高 ≠ 该选; 防过拟合以训练窗选参 + 测试窗验证为准）")


if __name__ == '__main__':
    main()
