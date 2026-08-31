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
两个必须回答的问题:
A) V4(山寨0/核心0.3) 胜出, 是"结构性差别对待"还是仅仅"总敞口减得更狠"?
   -> 扫描一刀切 risk_scale 0.30/0.20/0.15/0.10/0.05, 与 V4 做等敞口对照。
B) 为何各变体 MDD 完全相同(-43.5%/-41.4%)? 最大回撤到底发生在哪个相位?
   -> 若发生在 accumulation(满仓段), 说明真正漏洞在别处。
"""
import pandas as pd, numpy as np
import crypto_options_bt as m

px10 = pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()
px = pd.read_csv('data/weekly_adjclose_crypto50.csv', index_col=0, parse_dates=True).sort_index()
WINDOWS = [('10y', px10, None), ('9y', px, None),
           ('5y', px, '2021-08-13'), ('3y', px, '2023-08-11'), ('2y', px, '2024-08-09')]

print("=" * 104)
print("A) 一刀切 risk_scale 扫描  vs  V4 差别减仓 —— 是结构价值还是单纯减更狠?")
print("=" * 104)
hdr = f"{'配置':<26}"
for nm, _, _ in WINDOWS:
    hdr += f"{nm:>12}{'MDD':>8}"
print(hdr + f"{'Shp10y':>8}")
print("-" * 104)

CANDS = [(f'一刀切 {s}', dict(halving_crash_risk_scale=s, halving_bear_bottom_risk_scale=s))
         for s in (0.30, 0.20, 0.15, 0.10, 0.05, 0.00)]
CANDS.append(('V4 差别 山寨0/核心0.3',
              dict(halving_derisk_offense_first=True,
                   halving_offense_scale=0.0, halving_defense_scale=0.3)))
CANDS.append(('V4b 差别 山寨0/核心0.15',
              dict(halving_derisk_offense_first=True,
                   halving_offense_scale=0.0, halving_defense_scale=0.15)))

store = {}
for label, over in CANDS:
    line = f"{label:<26}"
    s10 = 0
    row = {}
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

# ---- 平均风险敞口(非STABLE权重)统计 ----
print()
print("=" * 104)
print("等敞口校验: 下行相位(crash+bear_bottom)内的平均风险敞口")
print("=" * 104)
for label, over in CANDS:
    c = dict(m.DEFAULT_CFG); c.update(over)
    r = m.run_bt(px10, c, label='exp', return_recs=True)
    recs = r.get('recs') or []
    exps = []
    for i, rc in enumerate(recs):
        if i >= len(px10):
            break
        ph, _, _ = m.halving_cycle_phase(px10.index[i], pre_halving_start_month=31.0)
        if ph in ('crash', 'bear_bottom'):
            w = getattr(rc, 'weights', None) or getattr(rc, 'target', None)
            if isinstance(w, dict):
                exps.append(sum(v for k, v in w.items() if k != m.STABLE))
    if exps:
        print(f"{label:<26} 下行段平均风险敞口 {np.mean(exps)*100:>6.1f}%  (n={len(exps)}周)")
    else:
        print(f"{label:<26} (recs 无权重字段, 跳过)")

# ---- B) MDD 落在哪个相位 ----
print()
print("=" * 104)
print("B) 最大回撤区间定位 (当前默认配置, 10y 面板)")
print("=" * 104)
r = m.run_bt(px10, dict(m.DEFAULT_CFG), label='mdd')
nav = r.get('nav')
if nav is None:
    print("(无 nav 序列)")
else:
    nav = pd.Series(nav, index=px10.index[:len(nav)]) if not isinstance(nav, pd.Series) else nav
    dd = nav / nav.cummax() - 1
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    ph_p, mp, _ = m.halving_cycle_phase(peak, pre_halving_start_month=31.0)
    ph_t, mt, _ = m.halving_cycle_phase(trough, pre_halving_start_month=31.0)
    print(f"全局 MDD {dd.min()*100:.1f}%")
    print(f"  峰 {peak.date()}  相位={ph_p} (post-halving {mp:.1f}月)")
    print(f"  谷 {trough.date()}  相位={ph_t} (post-halving {mt:.1f}月)")
    print(f"  历时 {(trough-peak).days/7:.0f} 周")
    print()
    print("  回撤路径中各相位占比:")
    seg = dd.loc[peak:trough]
    cnt = {}
    for t in seg.index:
        p_, _, _ = m.halving_cycle_phase(t, pre_halving_start_month=31.0)
        cnt[p_] = cnt.get(p_, 0) + 1
    for k, v in sorted(cnt.items(), key=lambda x: -x[1]):
        print(f"    {k:<14} {v:>3} 周 ({v/len(seg)*100:.0f}%)")

    print()
    print("  各相位内的独立最大回撤 (10y):")
    rows = []
    cur, start = None, None
    for t in nav.index:
        p_, _, _ = m.halving_cycle_phase(t, pre_halving_start_month=31.0)
        if p_ != cur:
            if cur is not None:
                rows.append((cur, start, prev))
            cur, start = p_, t
        prev = t
    rows.append((cur, start, prev))
    for p_, a, b in rows:
        s = nav.loc[a:b]
        if len(s) < 3:
            continue
        d = (s / s.cummax() - 1).min()
        print(f"    {p_:<14} {str(a.date())}~{str(b.date())}  MDD {d*100:>7.1f}%  收益 {(s.iloc[-1]/s.iloc[0]-1)*100:>8.1f}%")
