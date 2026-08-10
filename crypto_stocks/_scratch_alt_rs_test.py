# -*- coding: utf-8 -*-
"""
两条线一起裁决:
① 下行相位 risk_scale=0.0(完全清仓) 是否真优于 0.3 —— walk-forward 验证
② alt_rs_gate (山寨/BTC 相对强度门控) 能否堵住 accumulation 相位的 -40.3% 漏洞
"""
import pandas as pd, numpy as np
import crypto_options_bt as m

px10 = pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()
px = pd.read_csv('data/weekly_adjclose_crypto50.csv', index_col=0, parse_dates=True).sort_index()
WINDOWS = [('10y', px10, None), ('9y', px, None),
           ('5y', px, '2021-08-13'), ('3y', px, '2023-08-11'), ('2y', px, '2024-08-09')]

VARIANTS = {
    'V0 基线(下行0.3)': {},
    'S0 下行清仓0.0': dict(halving_crash_risk_scale=0.0, halving_bear_bottom_risk_scale=0.0),
    'RS-a 门控→现金 MA20': dict(alt_rs_gate=True, alt_rs_ma=20, alt_rs_scale=0.0),
    'RS-b 门控→BTC MA20': dict(alt_rs_gate=True, alt_rs_ma=20, alt_rs_scale=0.0, alt_rs_to_defense=True),
    'RS-c 门控→BTC MA13': dict(alt_rs_gate=True, alt_rs_ma=13, alt_rs_scale=0.0, alt_rs_to_defense=True),
    'RS-d 门控→BTC MA26': dict(alt_rs_gate=True, alt_rs_ma=26, alt_rs_scale=0.0, alt_rs_to_defense=True),
    'RS-e 半仓→BTC MA20': dict(alt_rs_gate=True, alt_rs_ma=20, alt_rs_scale=0.5, alt_rs_to_defense=True),
    'COMBO 清仓0.0+门控BTC': dict(halving_crash_risk_scale=0.0, halving_bear_bottom_risk_scale=0.0,
                                  alt_rs_gate=True, alt_rs_ma=20, alt_rs_scale=0.0, alt_rs_to_defense=True),
}

print("=" * 112)
print("① 下行清仓  ② 山寨相对强度门控 —— 多窗口")
print("=" * 112)
hdr = f"{'变体':<24}"
for nm, _, _ in WINDOWS:
    hdr += f"{nm:>12}{'MDD':>8}"
print(hdr + f"{'Shp10y':>8}")
print("-" * 112)
store = {}
for label, over in VARIANTS.items():
    line, s10, row = f"{label:<24}", 0, {}
    for nm, p, st in WINDOWS:
        pp = p if st is None else p.loc[st:]
        c = dict(m.DEFAULT_CFG); c.update(over)
        r = m.run_bt(pp, c, label=nm)
        row[nm] = r
        mu = r['multiple']
        line += (f"{mu:>11.1f}x" if mu < 10000 else f"{mu/1000:>10.1f}kx") + f"{r['mdd']*100:>7.1f}%"
        if nm == '10y':
            s10 = r.get('sharpe', 0)
    store[label] = row
    print(line + f"{s10:>8.2f}")

# ---- accumulation 相位专项: 门控是否真堵住了 2024 轮的 -40.3% ----
print()
print("=" * 112)
print("accumulation 相位专项 (2024-04-19 ~ 2025-04-18, 本轮山寨崩盘段)")
print("=" * 112)
SEGS = [('accumulation 2024轮', '2024-04-19', '2025-04-18'),
        ('euphoria 2024轮', '2025-04-25', '2025-10-17'),
        ('下行段 2024轮', '2025-10-24', '2026-08-07'),
        ('pre_halving 2019', '2019-02-08', '2020-05-08')]
for label, over in VARIANTS.items():
    c = dict(m.DEFAULT_CFG); c.update(over)
    src = px10 if True else px
    r = m.run_bt(src, c, label='seg')
    nav = r.get('nav')
    nav = pd.Series(nav, index=src.index[:len(nav)]) if not isinstance(nav, pd.Series) else nav
    parts = []
    for sn, a, b in SEGS:
        s = nav.loc[a:b]
        if len(s) < 3:
            parts.append(f"{sn}: n/a")
            continue
        parts.append(f"{sn}: {(s.iloc[-1]/s.iloc[0]-1)*100:>7.1f}% / MDD {(s/s.cummax()-1).min()*100:>6.1f}%")
    print(f"{label:<24}")
    for p_ in parts:
        print(f"    {p_}")

# ---- walk-forward 配对 t ----
print()
print("=" * 112)
print("Walk-forward 配对 t 检验 (104周窗/26周步进, 10y面板, 对照 V0)")
print("=" * 112)


def wf(over, p, win=104, step=26):
    outs, i = [], 0
    while i + win <= len(p):
        c = dict(m.DEFAULT_CFG); c.update(over)
        try:
            r = m.run_bt(p.iloc[i:i + win], c, label='wf')
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
        dm.append(np.log(m1) - np.log(m0)); dd.append(d1 - d0)
    n = len(dm)
    if n < 3:
        continue
    tm = np.mean(dm) / (np.std(dm, ddof=1) / np.sqrt(n)) if np.std(dm, ddof=1) > 0 else 0
    td = np.mean(dd) / (np.std(dd, ddof=1) / np.sqrt(n)) if np.std(dd, ddof=1) > 0 else 0
    print(f"{label:<24} n={n:<3} log倍数 t={tm:>+6.2f} (胜{sum(1 for x in dm if x>0)}/{n})"
          f"   MDD t={td:>+6.2f} (胜{sum(1 for x in dd if x>0)}/{n})")
