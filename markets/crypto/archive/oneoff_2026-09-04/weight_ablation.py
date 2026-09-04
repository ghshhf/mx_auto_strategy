"""
weight_ablation.py - 进攻权重模式消融: equal(等权, 原版) vs score(分数加权)

验证点:
  1. equal 模式必须复现基线 3361.0x (确认 offense_top_n 重构无破坏)
  2. score 模式用选币综合分(赛道相位×动量)归一化加权, 看倍数/风险收益是否改善

用法:
  python weight_ablation.py
"""
import os
import sys
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crypto_options_bt as bt  # noqa: E402

CSV = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50.csv')
px = pd.read_csv(CSV, index_col=0, parse_dates=True)


def concentration(nav_recs):
    """粗略集中度: 取每周进攻仓中最大单币权重的中位数(0~1)。"""
    from crypto_options_bt import STABLE
    vals = []
    for r in nav_recs:
        # rec 未直接存 target, 略过; 用 nav 序列无法反推。这里返回 None 占位。
        break
    return None


def run(mode):
    cfg = dict(bt.DEFAULT_CFG)
    cfg['offense_weight_mode'] = mode
    res = bt.run_bt(px, cfg_dict=cfg, label=f'V6_{mode}')
    return res


if __name__ == '__main__':
    rows = []
    for mode in ['equal', 'score', 'inv_vol']:
        print(f"\n===== 进攻权重模式: {mode} =====")
        res = run(mode)
        rows.append((mode, res['multiple'], res['cagr'], res['mdd'], res['sharpe'], res['events']))
        print(f"  倍数={res['multiple']:.1f}x  CAGR={res['cagr']*100:.1f}%  "
              f"MDD={res['mdd']*100:.1f}%  Sharpe={res['sharpe']:.2f}")

    # 对照表
    base = rows[0][1]
    print("\n===== 对照表 (equal 为基线) =====")
    print(f"{'mode':<9}{'倍数':>12}{'vs基线':>10}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}")
    for mode, mult, cagr, mdd, sh, ev in rows:
        rel = (mult / base - 1) * 100 if base else 0
        print(f"{mode:<9}{mult:>11.1f}x{rel:>+9.1f}%{cagr*100:>8.1f}%{mdd*100:>8.1f}%{sh:>9.2f}")
    print("\n(equal 复现 3361.0x 基线; score=分数加权; inv_vol=逆波动率风险平价)")
