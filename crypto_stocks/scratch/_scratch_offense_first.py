# -*- coding: utf-8 -*-

# --- [relocated 2026-08-31] 目录重构引导: 等效于在 crypto_stocks/ 根目录下运行 ---
import os as _os, sys as _sys
_SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))
_d = _SCRIPT_DIR
while _os.path.basename(_d) != 'crypto_stocks' and _d != _os.path.dirname(_d):
    _d = _os.path.dirname(_d)
_CS_ROOT = _d if _os.path.basename(_d) == 'crypto_stocks' else _SCRIPT_DIR
if _CS_ROOT != _SCRIPT_DIR:
    if _CS_ROOT not in _sys.path:
        _sys.path.insert(0, _CS_ROOT)
    _os.chdir(_CS_ROOT)
# --- [relocated] 引导结束 ---
"""
基于实证(山寨自顶 -89.4% vs BTC -48.2%, 且山寨提前 9.9 月见顶):
测试"差别减仓"—— 下行相位优先清空进攻山寨, 保留 BTC/ETH 防御核。
对照当前默认(一刀切 risk_scale=0.3)。
"""
import pandas as pd, numpy as np
import crypto_options_bt as m

px10 = pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()
px = pd.read_csv('data/weekly_adjclose_crypto50.csv', index_col=0, parse_dates=True).sort_index()

WINDOWS = [('10y', px10, None), ('9y', px, None),
           ('5y', px, '2021-08-13'), ('3y', px, '2023-08-11'), ('2y', px, '2024-08-09')]


def run(cfg_over, label):
    out = {}
    for nm, p, st in WINDOWS:
        pp = p if st is None else p.loc[st:]
        c = dict(m.DEFAULT_CFG); c.update(cfg_over)
        r = m.run_bt(pp, c, label=f'{label}-{nm}')
        out[nm] = r
    return out


VARIANTS = {
    'V0 当前默认(一刀切0.3)': {},
    'V1 差别: 山寨0 / 核心1.0': dict(halving_derisk_offense_first=True,
                                     halving_offense_scale=0.0, halving_defense_scale=1.0),
    'V2 差别: 山寨0 / 核心0.6': dict(halving_derisk_offense_first=True,
                                     halving_offense_scale=0.0, halving_defense_scale=0.6),
    'V3 差别: 山寨0.15/核心0.6': dict(halving_derisk_offense_first=True,
                                      halving_offense_scale=0.15, halving_defense_scale=0.6),
    'V4 差别: 山寨0 / 核心0.3': dict(halving_derisk_offense_first=True,
                                     halving_offense_scale=0.0, halving_defense_scale=0.3),
    'V5 差别: 山寨0.15/核心1.0': dict(halving_derisk_offense_first=True,
                                      halving_offense_scale=0.15, halving_defense_scale=1.0),
}

res = {}
print("=" * 112)
print("差别减仓 (offense-first) vs 一刀切  —— 全部含现有周期门控做空")
print("=" * 112)
hdr = f"{'变体':<24}"
for nm, _, _ in WINDOWS:
    hdr += f"{nm+'倍数':>13}{'MDD':>8}"
print(hdr)
print("-" * 112)
for label, over in VARIANTS.items():
    r = run(over, label)
    res[label] = r
    line = f"{label:<24}"
    for nm, _, _ in WINDOWS:
        mu = r[nm]['multiple']
        s = f"{mu:>12.1f}x" if mu < 10000 else f"{mu/1000:>11.1f}kx"
        line += s + f"{r[nm]['mdd']*100:>7.1f}%"
    print(line)

print()
print("Sharpe 对比")
print("-" * 112)
for label in VARIANTS:
    line = f"{label:<24}"
    for nm, _, _ in WINDOWS:
        line += f"{res[label][nm].get('sharpe', 0):>9.2f}"
    print(line)

# ---- walk-forward 配对 t 检验: 最优变体 vs V0 ----
print()
print("=" * 112)
print("Walk-forward 配对 t 检验 (104周窗 / 26周步进, 10y面板)")
print("=" * 112)


def wf(cfg_over, p, win=104, step=26):
    outs = []
    i = 0
    while i + win <= len(p):
        sub = p.iloc[i:i + win]
        c = dict(m.DEFAULT_CFG); c.update(cfg_over)
        try:
            r = m.run_bt(sub, c, label='wf')
            outs.append((r['multiple'], r['mdd']))
        except Exception:
            outs.append((np.nan, np.nan))
        i += step
    return outs


base = wf({}, px10)
for label, over in VARIANTS.items():
    if label.startswith('V0'):
        continue
    cand = wf(over, px10)
    dm, dd = [], []
    for (m0, d0), (m1, d1) in zip(base, cand):
        if np.isnan(m0) or np.isnan(m1) or m0 <= 0 or m1 <= 0:
            continue
        dm.append(np.log(m1) - np.log(m0))
        dd.append(d1 - d0)          # MDD 是负数, 差>0 = 候选回撤更浅 = 更好
    n = len(dm)
    if n < 3:
        continue
    tm = np.mean(dm) / (np.std(dm, ddof=1) / np.sqrt(n))
    td = np.mean(dd) / (np.std(dd, ddof=1) / np.sqrt(n))
    print(f"{label:<24} n={n:<3} log倍数 t={tm:>+6.2f} (胜{sum(1 for x in dm if x>0)}/{n})"
          f"   MDD t={td:>+6.2f} (胜{sum(1 for x in dd if x>0)}/{n})")
