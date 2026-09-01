"""
selection_robust_ablation.py - 选股稳健性消融: avail(原版) vs fixed(防重归一化漂移)

验证点:
  1. avail 模式必须复现基线 3361.0x (确认 norm 重构无破坏)
  2. fixed 模式(固定分母)能否在清理后的 57 币池上找回因删币漂移掉的倍数
  3. 多窗口稳健性: fixed 是否一致优于 avail (防单样本过拟合)
"""
import os
import sys
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crypto_options_bt as bt  # noqa: E402

CSV = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50.csv')
px = pd.read_csv(CSV, index_col=0, parse_dates=True)

WINDOWS = [None, '2020-01-01', '2021-01-01', '2022-01-01', '2023-01-01']


def run(norm, start):
    cfg = dict(bt.DEFAULT_CFG)
    cfg['theme_weight_norm'] = norm
    return bt.run_bt(px, cfg_dict=cfg, label=norm, start=start)


if __name__ == '__main__':
    print(f"{'window':<12}{'avail':>12}{'fixed':>12}{'Δ倍数':>9}{'avSharpe':>9}{'fxSharpe':>9}")
    wins = 0
    for start in WINDOWS:
        a = run('avail', start)
        f = run('fixed', start)
        tag = (start or 'full(2017)')[:11]
        delta = (f['multiple'] / a['multiple'] - 1) * 100
        if delta > 0:
            wins += 1
        print(f"{tag:<12}{a['multiple']:>11.0f}x{f['multiple']:>11.0f}x{delta:>+8.1f}%{a['sharpe']:>9.2f}{f['sharpe']:>9.2f}")
    print(f"\nfixed 胜出窗口数: {wins}/{len(WINDOWS)}")
    print("(avail 应复现 3361x 基线; fixed=固定分母防删币漂移)")
