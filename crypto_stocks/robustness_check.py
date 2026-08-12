"""
robustness_check.py - 进攻权重 equal vs inv_vol 多窗口稳健性验证
避免单一样本过拟合: 在不同起点窗口上确认 inv_vol 是否一致胜出。
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


def run(mode, start):
    cfg = dict(bt.DEFAULT_CFG)
    cfg['offense_weight_mode'] = mode
    return bt.run_bt(px, cfg_dict=cfg, label=mode, start=start)


if __name__ == '__main__':
    print(f"{'window':<12}{'equal':>12}{'inv_vol':>12}{'Δ倍数':>9}{'eqSharpe':>9}{'ivSharpe':>9}")
    wins = 0
    for start in WINDOWS:
        e = run('equal', start)
        v = run('inv_vol', start)
        tag = (start or 'full(2017)')[:11]
        delta = (v['multiple'] / e['multiple'] - 1) * 100
        if delta > 0:
            wins += 1
        print(f"{tag:<12}{e['multiple']:>11.0f}x{v['multiple']:>11.0f}x{delta:>+8.1f}%{e['sharpe']:>9.2f}{v['sharpe']:>9.2f}")
    print(f"\ninv_vol 胜出窗口数: {wins}/{len(WINDOWS)}")
