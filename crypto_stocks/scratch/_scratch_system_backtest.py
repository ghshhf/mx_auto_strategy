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
用户要求: "用我那个时间刻度作为真正的系统底层回测" —— 在 FULL 56币面板上, 把减半时间刻
作为系统最底层, 验证 (A) 时间刻减仓是否真能挡住本轮山寨崩盘, (B) "其他代币跌得比上一轮还猛" 是否成立。

三组集成回测 (10y 全面板):
  A baseline : halving OFF + alt_rs OFF  (纯策略, 无时间刻/无山寨门控)
  B timescale: halving ON  + alt_rs OFF  (仅时间刻减仓底层)
  C default  : halving ON  + alt_rs ON   (时间刻 + 山寨相对强度门控 = 当前默认)

并逐窗口切片对比本轮下行段(2025-10-24~2026-08-07)的真实防护力。
"""
import pandas as pd, numpy as np
import crypto_options_bt as m

px = pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()
px = px.loc[:, [c for c in px.columns if c and str(c).strip()]]

def mult_mdd(nav):
    nav = pd.Series(nav, index=px.index)
    mult = nav.iloc[-1] / nav.iloc[0]
    peak = nav.cummax()
    mdd = (nav / peak - 1).min()
    return float(mult), float(mdd)

def slice_stat(nav, a, b):
    s = pd.Series(nav, index=px.index).loc[a:b]
    if len(s) < 2: return np.nan, np.nan
    ret = s.iloc[-1] / s.iloc[0] - 1
    mdd = ((s / s.cummax()) - 1).min()
    return float(ret), float(mdd)

configs = {
    'A_baseline_no_timescale': dict(halving_cycle_enabled=False, alt_rs_gate=False),
    'B_timescale_only':        dict(halving_cycle_enabled=True,  alt_rs_gate=False),
    'C_default_full':          dict(halving_cycle_enabled=True,  alt_rs_gate=True),
}

DOWN_A, DOWN_B = '2025-10-24', '2026-08-07'
print("=" * 96)
print("FULL 56-COIN PANEL 集成回测 (10y, weekly_adjclose_crypto50_10y.csv)")
print("=" * 96)
print(f"{'config':<26}{'倍数':>10}{'全局MDD':>10}{'本轮下行段收益':>16}{'本轮下行段MDD':>16}")
print("-" * 96)
rows = {}
for name, ov in configs.items():
    res = m.run_bt(px, cfg_dict=ov, label=name)
    mult, mdd = mult_mdd(res['nav'])
    dr, dm = slice_stat(res['nav'], DOWN_A, DOWN_B)
    rows[name] = (mult, mdd, dr, dm)
    print(f"{name:<26}{mult:>9.1f}x{mdd*100:>9.1f}%{dr*100:>15.1f}%{dm*100:>15.1f}%")

print()
print("=" * 96)
print("逐层贡献 (vs baseline A)")
print("=" * 96)
base = rows['A_baseline_no_timescale']
for name in ('B_timescale_only', 'C_default_full'):
    mult, mdd, dr, dm = rows[name]
    print(f"  {name:<22} 倍数 {mult/base[0]*100-100:>+6.1f}%  | 全局MDD {mdd*100:>6.1f}% (Δ{(mdd-base[1])*100:>+5.1f}pp)"
          f" | 本轮下行 {dr*100:>6.1f}% (Δ{(dr-base[2])*100:>+5.1f}pp), MDD {dm*100:>6.1f}% (Δ{(dm-base[3])*100:>+5.1f}pp)")

# ---- 山寨见顶 vs BTC 见顶 时间错位 ----
print()
print("=" * 96)
print("★ 核心机制: 山寨见顶比 BTC 早多少? (决定时间刻对山寨是否'迟到')")
print("=" * 96)
BTC = px['BTC']
alts = [c for c in px.columns if c != 'BTC']
# 本轮(2024减半后)各币相对减半日的峰值月
for label, halving in (('2020轮', pd.Timestamp('2020-05-11')),
                       ('2024轮', pd.Timestamp('2024-04-19'))):
    sub_btc = BTC[BTC.index >= halving]
    if len(sub_btc) < 5: continue
    btc_peak_w = sub_btc.idxmax()
    btc_peak_m = (btc_peak_w - halving).days / 30.44
    # alt 等权指数峰值
    altidx = px[alts].dropna(thresh=int(0.6*len(alts))).loc[halving:]
    altidx = (altidx / altidx.iloc[0]).mean(axis=1)
    alt_peak_w = altidx.idxmax()
    alt_peak_m = (alt_peak_w - halving).days / 30.44
    print(f"  {label}: BTC见顶 @ post-halving {btc_peak_m:4.1f}月 ({btc_peak_w.date()})"
          f" | 山寨等权见顶 @ {alt_peak_m:4.1f}月 ({alt_peak_w.date()})"
          f" | 错位 {alt_peak_m-btc_peak_m:>+4.1f}月")

# ---- 本轮下行段: 各层对山寨的"减仓时点"是否踩中 ----
print()
print("=" * 96)
print("本轮下行段逐月: BTC / 山寨等权 收益, 以及时间刻相位 (看减仓是否踩中山寨崩")
print("=" * 96)
PH = 31.0
phases = [m.halving_cycle_phase(d, pre_halving_start_month=PH)[0] for d in px.index]
pdf = pd.DataFrame({'phase': phases}, index=px.index)
sub = px.loc[DOWN_A:DOWN_B]
pds = pdf.loc[DOWN_A:DOWN_B]
bs = sub['BTC'] / sub['BTC'].iloc[0] - 1
ai = sub[alts].dropna(thresh=int(0.6*len(alts)))
aii = (ai / ai.iloc[0]).mean(axis=1) - 1
print(f"{'月':<10}{'相位':<14}{'BTC累计':>11}{'山寨等权累计':>14}")
for d in pds.index[::4]:
    print(f"{str(d.date()):<10}{pds.loc[d,'phase']:<14}{bs.loc[d]*100:>10.1f}%{aii.loc[d]*100:>13.1f}%")
print(f"{'结束':<10}{pds.iloc[-1]['phase']:<14}{bs.iloc[-1]*100:>10.1f}%{aii.iloc[-1]*100:>13.1f}%")
