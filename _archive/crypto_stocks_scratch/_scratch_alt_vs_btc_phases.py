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
用户质疑: "你这一轮只看比特币了, 你不看其他代币, 跌得比上一轮还猛"
=> 把三轮减半周期的每个相位, 分别用 BTC / 等权山寨指数 / 中位数币 重算。
验证: 本轮(2024轮) alt 的 crash+bear 跌幅是否真的比上轮更猛?
如果成立 -> "时间刻高位减仓/做空" 在 alt 上的 alpha 远大于 BTC 口径的估计。
"""
import pandas as pd, numpy as np
import crypto_options_bt as m

px = pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()
px = px.loc[:, [c for c in px.columns if c and str(c).strip()]]
BTC = px['BTC'].dropna()

PH = 31.0  # pre_halving_start_month 新默认

# 给每周打相位标签
phases = []
for t in px.index:
    ph, ms, _ = m.halving_cycle_phase(t, pre_halving_start_month=PH)
    phases.append((t, ph, ms))
pdf = pd.DataFrame(phases, columns=['date', 'phase', 'months']).set_index('date')

# 切出连续相位段
segs = []
cur_ph, start = None, None
for t, row in pdf.iterrows():
    if row['phase'] != cur_ph:
        if cur_ph is not None:
            segs.append((cur_ph, start, prev_t))
        cur_ph, start = row['phase'], t
    prev_t = t
segs.append((cur_ph, start, prev_t))


def perf(sub: pd.DataFrame):
    """返回 (BTC涨跌, alt等权涨跌, alt中位数涨跌, alt等权MDD, 参与币数)"""
    if len(sub) < 2:
        return None
    out = {}
    b = sub['BTC'].dropna()
    out['btc'] = b.iloc[-1] / b.iloc[0] - 1 if len(b) >= 2 else np.nan
    bser = sub['BTC'] / sub['BTC'].iloc[0]
    out['btc_mdd'] = (bser / bser.cummax() - 1).min()

    alts = [c for c in sub.columns if c != 'BTC']
    rets, curves = [], []
    for c in alts:
        s = sub[c].dropna()
        # 要求覆盖该段 >=80% 的周, 且首末都有值
        if len(s) < max(3, int(0.8 * len(sub))):
            continue
        rets.append(s.iloc[-1] / s.iloc[0] - 1)
        curves.append((sub[c] / s.iloc[0]).ffill())
    out['n'] = len(rets)
    if not rets:
        out.update(alt_ew=np.nan, alt_med=np.nan, alt_mdd=np.nan)
        return out
    out['alt_ew'] = float(np.mean(rets))
    out['alt_med'] = float(np.median(rets))
    idx = pd.concat(curves, axis=1).mean(axis=1)  # 等权指数(每周再平衡近似)
    out['alt_mdd'] = float((idx / idx.cummax() - 1).min())
    return out


print("=" * 108)
print("三轮减半周期 × 各相位: BTC vs 山寨等权 vs 山寨中位数")
print("=" * 108)
print(f"{'相位':<14}{'区间':<26}{'周':>4}{'BTC':>10}{'BTCmdd':>9}{'ALT等权':>11}{'ALT中位':>10}{'ALTmdd':>9}{'币数':>6}")
print("-" * 108)
rows = []
for ph, a, b in segs:
    sub = px.loc[a:b]
    r = perf(sub)
    if r is None:
        continue
    rows.append((ph, a, b, r))
    print(f"{ph:<14}{str(a.date())+'~'+str(b.date()):<26}{len(sub):>4}"
          f"{r['btc']*100:>9.1f}%{r['btc_mdd']*100:>8.1f}%"
          f"{r['alt_ew']*100:>10.1f}%{r['alt_med']*100:>9.1f}%{r['alt_mdd']*100:>8.1f}%{r['n']:>6}")

print()
print("=" * 108)
print("★ 核心裁决: 逐轮对比 (只看 euphoria / crash / bear_bottom)")
print("=" * 108)
for key in ('euphoria', 'crash', 'bear_bottom'):
    print(f"\n--- {key} ---")
    print(f"{'轮次':<26}{'BTC':>10}{'ALT等权':>11}{'ALT中位':>10}{'ALT-BTC差':>12}{'币数':>6}")
    sel = [x for x in rows if x[0] == key]
    for ph, a, b, r in sel:
        if np.isnan(r.get('alt_ew', np.nan)):
            continue
        d = r['alt_ew'] - r['btc']
        print(f"{str(a.date())+'~'+str(b.date()):<26}{r['btc']*100:>9.1f}%{r['alt_ew']*100:>10.1f}%"
              f"{r['alt_med']*100:>9.1f}%{d*100:>11.1f}pp{r['n']:>6}")

# 合并 crash+bear_bottom = "下行段"
print()
print("=" * 108)
print("★★ 下行段合并 (crash + bear_bottom 连续): 这才是减仓层要避的东西")
print("=" * 108)
print(f"{'轮次下行段':<26}{'周':>4}{'BTC':>10}{'ALT等权':>11}{'ALT中位':>10}{'ALTmdd':>9}{'最惨币':>22}")
print("-" * 108)
downs = []
i = 0
while i < len(rows):
    if rows[i][0] == 'crash':
        a = rows[i][1]
        b = rows[i][2]
        if i + 1 < len(rows) and rows[i + 1][0] == 'bear_bottom':
            b = rows[i + 1][2]
        downs.append((a, b))
        i += 2
    else:
        i += 1
for a, b in downs:
    sub = px.loc[a:b]
    r = perf(sub)
    if r is None or np.isnan(r.get('alt_ew', np.nan)):
        continue
    worst, wv = '', 0
    for c in sub.columns:
        if c == 'BTC':
            continue
        s = sub[c].dropna()
        if len(s) < max(3, int(0.8 * len(sub))):
            continue
        v = s.iloc[-1] / s.iloc[0] - 1
        if v < wv:
            worst, wv = c, v
    print(f"{str(a.date())+'~'+str(b.date()):<26}{len(sub):>4}{r['btc']*100:>9.1f}%"
          f"{r['alt_ew']*100:>10.1f}%{r['alt_med']*100:>9.1f}%{r['alt_mdd']*100:>8.1f}%"
          f"{worst+' '+format(wv*100,'.0f')+'%':>22}")

# ---- 本轮 alt 逐币跌幅明细 (2025-10 至今) ----
print()
print("=" * 108)
print("本轮下行段 (2025-10-24 ~ 2026-08-07) 逐币跌幅 (前20惨)")
print("=" * 108)
sub = px.loc['2025-10-24':'2026-08-07']
lst = []
for c in sub.columns:
    s = sub[c].dropna()
    if len(s) < int(0.8 * len(sub)):
        continue
    lst.append((c, s.iloc[-1] / s.iloc[0] - 1))
lst.sort(key=lambda x: x[1])
for c, v in lst[:20]:
    print(f"  {c:<10}{v*100:>8.1f}%")
print(f"  ... 共 {len(lst)} 币, 等权 {np.mean([v for _,v in lst])*100:.1f}%, 中位 {np.median([v for _,v in lst])*100:.1f}%")
print(f"  跌超50%的币: {sum(1 for _,v in lst if v<-0.5)}/{len(lst)}"
      f" | 跌超70%: {sum(1 for _,v in lst if v<-0.7)}/{len(lst)}")

# ---- 上轮同期对比 ----
print()
sub2 = px.loc['2021-11-14':'2022-12-31']
lst2 = []
for c in sub2.columns:
    s = sub2[c].dropna()
    if len(s) < int(0.8 * len(sub2)):
        continue
    lst2.append((c, s.iloc[-1] / s.iloc[0] - 1))
if lst2:
    print(f"上轮下行段 (2021-11-14 ~ 2022-12-31): {len(lst2)} 币, 等权 {np.mean([v for _,v in lst2])*100:.1f}%,"
          f" 中位 {np.median([v for _,v in lst2])*100:.1f}%,"
          f" 跌超50% {sum(1 for _,v in lst2 if v<-0.5)}/{len(lst2)},"
          f" 跌超70% {sum(1 for _,v in lst2 if v<-0.7)}/{len(lst2)}")
