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
关键追问: 山寨的"周期时钟"是否早于 BTC?
如果 alt 见顶显著早于 BTC, 那么按 BTC 减半刻度减仓对 alt 来说就是"迟到",
真正的修正 = alt 相位时钟前移 / euphoria 段把仓位集中到 BTC。
"""
import pandas as pd, numpy as np
import crypto_options_bt as m

px = pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()
px = px.loc[:, [c for c in px.columns if c and str(c).strip()]]

HALVINGS = [pd.Timestamp('2016-07-09'), pd.Timestamp('2020-05-11'), pd.Timestamp('2024-04-20')]
CYCLES = [
    ('2016轮', '2016-07-09', '2019-02-01'),
    ('2020轮', '2020-05-11', '2022-12-09'),
    ('2024轮', '2024-04-20', '2026-08-07'),
]

print("=" * 100)
print("① 各轮周期内: BTC 高点 vs 山寨等权指数高点 vs 山寨中位币高点  (post-halving 月数)")
print("=" * 100)
print(f"{'轮次':<10}{'BTC顶周':<14}{'月':>6}   {'ALT等权顶':<14}{'月':>6}   {'ALT提前':>9}{'参与币':>7}")
print("-" * 100)
for nm, a, b in CYCLES:
    sub = px.loc[a:b]
    hv = HALVINGS[[x[0] for x in CYCLES].index(nm)]
    b_s = sub['BTC'].dropna()
    b_top = b_s.idxmax(); b_m = (b_top - hv).days / 30.44

    curves = []
    for c in sub.columns:
        if c == 'BTC':
            continue
        s = sub[c].dropna()
        if len(s) < int(0.6 * len(sub)):
            continue
        curves.append((sub[c] / s.iloc[0]).ffill())
    if not curves:
        print(f"{nm:<10}{str(b_top.date()):<14}{b_m:>6.1f}   (山寨样本不足)")
        continue
    idx = pd.concat(curves, axis=1).mean(axis=1)
    a_top = idx.idxmax(); a_m = (a_top - hv).days / 30.44
    print(f"{nm:<10}{str(b_top.date()):<14}{b_m:>6.1f}   {str(a_top.date()):<14}{a_m:>6.1f}   "
          f"{(b_m-a_m):>8.1f}月{len(curves):>7}")

print()
print("=" * 100)
print("② 逐币 '周期内高点' 分布 (2024轮): 多少币的顶出现在 BTC 见顶之前?")
print("=" * 100)
sub = px.loc['2024-04-20':'2026-08-07']
btc_top = sub['BTC'].dropna().idxmax()
print(f"BTC 本轮顶: {btc_top.date()}  (post-halving {(btc_top-HALVINGS[2]).days/30.44:.1f} 月)")
before, after, tops = 0, 0, []
for c in sub.columns:
    if c == 'BTC':
        continue
    s = sub[c].dropna()
    if len(s) < int(0.6 * len(sub)):
        continue
    tp = s.idxmax()
    tops.append((c, tp, s.max(), s.iloc[-1] / s.max() - 1))
    if tp < btc_top:
        before += 1
    else:
        after += 1
print(f"顶在 BTC 之前: {before} 币 | 顶在 BTC 当周或之后: {after} 币")
mons = [(t - HALVINGS[2]).days / 30.44 for _, t, _, _ in tops]
print(f"山寨见顶月数分布: 中位 {np.median(mons):.1f} 月 | 均值 {np.mean(mons):.1f} 月 | "
      f"BTC {(btc_top-HALVINGS[2]).days/30.44:.1f} 月")
dd = [d for _, _, _, d in tops]
print(f"山寨自周期顶回撤: 中位 {np.median(dd)*100:.1f}% | 均值 {np.mean(dd)*100:.1f}% | "
      f"BTC {(sub['BTC'].iloc[-1]/sub['BTC'].max()-1)*100:.1f}%")

print()
print("=" * 100)
print("③ 三轮对比: 山寨'自周期顶'的真实回撤 (这才是持有山寨的人真实感受)")
print("=" * 100)
print(f"{'轮次':<10}{'BTC自顶回撤':>13}{'ALT中位自顶回撤':>18}{'ALT均值':>11}{'跌超80%占比':>13}{'币数':>6}")
print("-" * 100)
for nm, a, b in CYCLES:
    sub = px.loc[a:b]
    bs = sub['BTC'].dropna()
    b_dd = bs.iloc[-1] / bs.max() - 1
    ds = []
    for c in sub.columns:
        if c == 'BTC':
            continue
        s = sub[c].dropna()
        if len(s) < int(0.6 * len(sub)):
            continue
        ds.append(s.iloc[-1] / s.max() - 1)
    if not ds:
        continue
    print(f"{nm:<10}{b_dd*100:>12.1f}%{np.median(ds)*100:>17.1f}%{np.mean(ds)*100:>10.1f}%"
          f"{sum(1 for d in ds if d<-0.8)/len(ds)*100:>12.1f}%{len(ds):>6}")

print()
print("=" * 100)
print("④ euphoria 相位: 持 BTC 还是持山寨? (中位数币口径)")
print("=" * 100)
for nm, hv in zip(['2016轮', '2020轮', '2024轮'], HALVINGS):
    a = hv + pd.Timedelta(days=int(12 * 30.44))
    b = hv + pd.Timedelta(days=int(18 * 30.44))
    sub = px.loc[a:b]
    if len(sub) < 5:
        continue
    bs = sub['BTC'].dropna()
    rs = []
    for c in sub.columns:
        if c == 'BTC':
            continue
        s = sub[c].dropna()
        if len(s) < int(0.8 * len(sub)):
            continue
        rs.append(s.iloc[-1] / s.iloc[0] - 1)
    if not rs:
        continue
    print(f"{nm}  {a.date()}~{b.date()}  BTC {(bs.iloc[-1]/bs.iloc[0]-1)*100:>7.1f}%  |  "
          f"ALT中位 {np.median(rs)*100:>7.1f}%  ALT均值 {np.mean(rs)*100:>7.1f}%  "
          f"跑赢BTC的币 {sum(1 for r in rs if r > bs.iloc[-1]/bs.iloc[0]-1)}/{len(rs)}")
