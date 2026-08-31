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
"""最终裁决: COMBO 相对 S0(仅清仓) 的边际价值 + 减半周期切割 OOS。"""
import pandas as pd, numpy as np
import crypto_options_bt as m

px10 = pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()

S0 = dict(halving_crash_risk_scale=0.0, halving_bear_bottom_risk_scale=0.0)
RS = dict(alt_rs_gate=True, alt_rs_ma=20, alt_rs_scale=0.0, alt_rs_to_defense=True)
COMBO = {**S0, **RS}


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


def paired(a, b, na, nb):
    dm, dd = [], []
    for (m0, d0), (m1, d1) in zip(a, b):
        if np.isnan(m0) or np.isnan(m1) or m0 <= 0 or m1 <= 0:
            continue
        dm.append(np.log(m1) - np.log(m0)); dd.append(d1 - d0)
    n = len(dm)
    tm = np.mean(dm) / (np.std(dm, ddof=1) / np.sqrt(n)) if n > 2 and np.std(dm, ddof=1) > 0 else 0
    td = np.mean(dd) / (np.std(dd, ddof=1) / np.sqrt(n)) if n > 2 and np.std(dd, ddof=1) > 0 else 0
    print(f"  {nb} vs {na}:  n={n}  log倍数 t={tm:>+6.2f} (胜{sum(1 for x in dm if x>0)}/{n})"
          f"   MDD t={td:>+6.2f} (胜{sum(1 for x in dd if x>0)}/{n})")


print("=" * 100)
print("① Walk-forward 边际价值 (104周窗/26周步进)")
print("=" * 100)
w_s0 = wf(S0, px10)
w_cb = wf(COMBO, px10)
w_rs = wf(RS, px10)
paired(w_s0, w_cb, 'S0(仅清仓)', 'COMBO')
paired(w_rs, w_cb, 'RS(仅门控)', 'COMBO')

print()
print("② 更长窗口 walk-forward (156周窗/26周步进) —— 检验短窗偏差")
print("=" * 100)
b3 = wf({}, px10, win=156)
c3 = wf(COMBO, px10, win=156)
s3 = wf(S0, px10, win=156)
paired(b3, c3, 'V0基线', 'COMBO')
paired(b3, s3, 'V0基线', 'S0')

print()
print("=" * 100)
print("③ 减半周期切割 OOS: 训练前N轮 → 测试第N+1轮 (完全样本外)")
print("=" * 100)
CUTS = [
    ('训2016轮 → 测2020轮', '2020-05-11', '2022-12-09'),
    ('训2016+2020 → 测2024轮', '2024-04-20', '2026-08-07'),
]
CANDS = {'V0 基线': {}, 'S0 仅清仓': S0, 'RS 仅门控': RS, 'COMBO': COMBO}
for nm, a, b in CUTS:
    print(f"\n{nm}   测试区间 {a} ~ {b}")
    # 测试段需要 WARMUP, 从更早喂数据但只统计测试段
    for label, over in CANDS.items():
        c = dict(m.DEFAULT_CFG); c.update(over)
        r = m.run_bt(px10, c, label='oos')
        nav = r.get('nav')
        nav = pd.Series(nav, index=px10.index[:len(nav)]) if not isinstance(nav, pd.Series) else nav
        s = nav.loc[a:b]
        if len(s) < 5:
            continue
        mu = s.iloc[-1] / s.iloc[0]
        mdd = (s / s.cummax() - 1).min()
        yrs = (s.index[-1] - s.index[0]).days / 365.25
        cagr = mu ** (1 / yrs) - 1 if yrs > 0 else 0
        print(f"  {label:<12} {mu:>8.2f}x   CAGR {cagr*100:>6.1f}%   MDD {mdd*100:>7.1f}%")

print()
print("=" * 100)
print("④ 当前实盘状态 (COMBO 配置)")
print("=" * 100)
rs = m._alt_rs_ratio(px10)
cur = rs.iloc[-1]; ma20 = rs.iloc[-20:].mean()
ph, ms, _ = m.halving_cycle_phase(px10.index[-1], pre_halving_start_month=31.0)
print(f"  日期 {px10.index[-1].date()}  相位={ph} (post-halving {ms:.1f}月)")
print(f"  ALT/BTC 相对强度 = {cur:.4f}  vs MA20 = {ma20:.4f}  → 门控{'触发(进攻仓→BTC)' if cur < ma20 else '未触发(正常持有山寨)'}")
print(f"  下行相位清仓: {'是(风险仓→0)' if ph in ('crash','bear_bottom') else '否'}")
# 连续触发周数
k = 0
for i in range(len(rs) - 1, 19, -1):
    if rs.iloc[i] < rs.iloc[i - 19:i + 1].mean():
        k += 1
    else:
        break
print(f"  ALT/BTC 已连续走弱 {k} 周")
