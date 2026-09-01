
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
"""验证用户的周期底层论题:
  ① BTC涨≠山寨100%暴涨 (历史上并非锁步)
  ② 山寨与BTC基本都"差一点时间" (见顶时间错位)
  ③ 周期一样 -> 时间刻度(减半日历)代表"共同周期", 是放之全篮子的通用底层
做法: 用引擎的 halving_cycle_phase (纯日历, 零价格输入) 给每周打相位,
     然后跨 2017/2021/2024 三轮, 量化:
       A. 各相位内 BTC 与山寨等权 同向/反向占比 (验证①)
       B. 山寨等权 vs BTC 见顶时间错位(周) (验证②)
       C. crash+bear 相位内 处于自身回撤中的币种占比 (验证③: 共同周期)
"""
import pandas as pd, numpy as np, json, sys
sys.path.insert(0, '.')
from crypto_options_bt import halving_cycle_phase, BTC_HALVING_DATES

df = pd.read_csv('data/weekly_adjclose_crypto50.csv', parse_dates=['date']).sort_values('date').reset_index(drop=True)
df = df.set_index('date')
alts = [c for c in df.columns if c not in ('BTC',)]
print(f"数据: {df.index[0].date()} ~ {df.index[-1].date()}  周数={len(df)}  山寨数={len(alts)}")

# 相位序列
phases = df.index.map(lambda d: halving_cycle_phase(d, pre_halving_start_month=31.0)[0])
df['_phase'] = phases.values

# 山寨等权指数 (基准=各币自身首个有数据周=1, 等权平均; 用相对基准比)
def alt_index(series_base_ok):
    # base week = first week where BTC has data (halving week handled per-round)
    pass

# ---- 逐轮分析 ----
# 用 halving 日切分三轮: 2017(部分), 2021, 2024
halv = [h for h in BTC_HALVING_DATES if h.year >= 2016]
# 我们只分析有完整数据的轮: 2020-05 与 2024-04 起的两轮; 2017 用 2016-07 起的(数据仅从2017-08)
rounds = [
    ('2017(partial)', pd.Timestamp('2016-07-09'), pd.Timestamp('2020-05-11')),
    ('2021',          pd.Timestamp('2020-05-11'), pd.Timestamp('2024-04-19')),
    ('2024',          pd.Timestamp('2024-04-19'), pd.Timestamp('2099-01-01')),
]

phase_order = ['accumulation','euphoria','crash','bear_bottom','pre_halving']
results = {}
summary_rows = []

for rname, h0, h1 in rounds:
    sub = df[(df.index >= h0) & (df.index < h1)].copy()
    if len(sub) == 0:
        continue
    # 山寨等权指数: 基准周 = 该轮起点(h0)
    base = sub.iloc[0]
    # 每只币相对 base 的比值, 等权平均(仅用该周非NaN且有base值的币)
    idx = pd.Series(index=sub.index, dtype=float)
    for t in sub.index:
        row = sub.loc[t]
        valid = [c for c in alts if pd.notna(row[c]) and pd.notna(base[c]) and base[c] > 0]
        if valid:
            idx[t] = np.mean([row[c]/base[c] for c in valid])
    # BTC 指数
    btc_base = base['BTC']
    btc_idx = sub['BTC'] / btc_base

    # A. 各相位 BTC vs 山寨同向占比
    a_rows = []
    for ph in phase_order:
        phw = sub[sub['_phase'] == ph]
        if len(phw) < 2:
            continue
        # 相位内收益 = 末/初 -1
        btc_ret = btc_idx[phw.index[-1]]/btc_idx[phw.index[0]] - 1
        # 山寨逐币相位收益
        coin_rets = {}
        for c in alts:
            s = sub.loc[phw.index, c]
            s = s.dropna()
            if len(s) >= 2 and s.iloc[0] > 0:
                coin_rets[c] = s.iloc[-1]/s.iloc[0] - 1
        if not coin_rets:
            continue
        alt_mean = np.mean(list(coin_rets.values()))
        alt_med = np.median(list(coin_rets.values()))
        # 同向占比 (与BTC同号)
        same = sum(1 for v in coin_rets.values() if np.sign(v) == np.sign(btc_ret))
        same_pct = same/len(coin_rets)
        a_rows.append({'phase':ph,'weeks':len(phw),'btc_ret':btc_ret,
                       'alt_mean':alt_mean,'alt_med':alt_med,
                       'n_alts':len(coin_rets),'same_sign_pct':same_pct,
                       'alts_up_pct':sum(1 for v in coin_rets.values() if v>0)/len(coin_rets)})
    # B. 见顶时间错位: 在 accumulation->euphoria 窗口(至 halving+18月)内找峰值周
    up_end = h0 + pd.Timedelta(days=int(18*30.44))
    up_win = sub[sub.index <= up_end]
    if len(up_win) > 0:
        btc_peak_t = btc_idx[up_win.index].idxmax()
        alt_peak_t = idx[up_win.index].idxmax()
        btc_m = (btc_peak_t - h0).days/30.44
        alt_m = (alt_peak_t - h0).days/30.44
        offset_wk = (alt_peak_t - btc_peak_t).days/7.0
    else:
        btc_peak_t = alt_peak_t = None; btc_m = alt_m = offset_wk = np.nan
    # C. crash+bear 相位内 处于自身回撤中的币种占比
    cb = sub[sub['_phase'].isin(['crash','bear_bottom'])]
    in_dd = 0; tot = 0
    for c in alts:
        s = sub.loc[cb.index, c].dropna()
        if len(s) >= 2:
            tot += 1
            if s.min() < s.max()*0.98:  # 区间内出现过>2%回撤(即下行)
                in_dd += 1
    dd_pct = in_dd/tot if tot else np.nan

    results[rname] = {'A':a_rows,
                      'btc_peak':str(btc_peak_t.date()) if btc_peak_t is not None else None,
                      'alt_peak':str(alt_peak_t.date()) if alt_peak_t is not None else None,
                      'btc_peak_m':btc_m,'alt_peak_m':alt_m,'offset_wk':offset_wk,
                      'crash_bear_coins_in_drawdown_pct':dd_pct}
    print(f"\n===== 轮 {rname} ({h0.date()}~) =====")
    print(f"  BTC见顶: {results[rname]['btc_peak']} (post-halv {btc_m:.1f}月) | 山寨等权见顶: {results[rname]['alt_peak']} (post-halv {alt_m:.1f}月) | 错位 {offset_wk:.1f}周")
    print(f"  crash+bear 相位内 处于回撤的币种占比: {dd_pct*100:.1f}%  (共同周期证据)")
    for r in a_rows:
        print(f"   {r['phase']:12s} w={r['weeks']:2d}  BTC {r['btc_ret']*100:+7.1f}%  山寨均 {r['alt_mean']*100:+7.1f}%  中位 {r['alt_med']*100:+7.1f}%  | 同向 {r['same_sign_pct']*100:4.0f}%  上涨币 {r['alts_up_pct']*100:4.0f}%  (n={r['n_alts']})")

# 汇总: 跨轮 "BTC上涨相位里 山寨上涨占比" 与 "错位"
with open(_os.path.join(_SCRIPT_DIR, '_scratch_cycle_universal.json'),'w') as f:
    json.dump(results, f, indent=2, default=str)
print("\n[done] -> _scratch_cycle_universal.json")
