"""主题领导力检测(纯数据, 零前视):
  ① 用引擎已有的 compute_sector_indices 合成 6 大赛道指数 + BIGCAP
  ② 在每个历史周期的上行窗口, 只看数据(不看 PHASE_HISTORY)→ 哪家赛道 RS 最强
     -> 验证"数据驱动能还原已知叙事"(2021 DeFi / 2024 AI)
  ③ 当前(2026-08-07)各赛道 13w/26w RS 快照 -> 谁在领涨 / 谁在退潮
  ④ 历史轮动表 -> 预判下一轮大概率题材
"""
import pandas as pd, numpy as np, json

df = pd.read_csv('data/weekly_adjclose_crypto50.csv', parse_dates=['date']).sort_values('date').reset_index(drop=True)
df = df.set_index('date')
import crypto_options_bt as eng
sectors = eng.compute_sector_indices(df)
THEMES = ['L1_INDEX','L2_INDEX','DEFI_INDEX','AI_INDEX','WE3_INDEX','RWA_INDEX']
print(f"赛道指数: {THEMES}")
print(f"区间: {df.index[0].date()} ~ {df.index[-1].date()}  周数={len(df)}")

def rs_vs_bigcap(series, base, w):
    """trailing w-week RS of series vs base(均为指数)"""
    s = series / series.shift(w)
    b = base / base.shift(w)
    return (s - b).dropna()

# ---- ① 各历史周期上行窗口: 纯数据 RS 排名 ----
cycles = {
    '2017(partial)': ('2017-08-11','2017-12-31'),
    '2021':          ('2020-05-11','2021-11-05'),   # halving -> BTC顶
    '2024':          ('2024-04-19','2025-09-26'),   # halving -> BTC顶
}
print("\n===== 各周期上行窗口: 赛道累计收益(纯数据, 无手标) =====")
cycle_rs = {}
for cname,(s,e) in cycles.items():
    sub = sectors.loc[s:e]
    if len(sub) < 5: continue
    rets = {t: sub[t].iloc[-1]/sub[t].iloc[0]-1 for t in THEMES}
    order = sorted(rets, key=rets.get, reverse=True)
    print(f"\n[{cname}] {s}~{e}")
    for t in order:
        print(f"   {t:12s} {rets[t]*100:+8.1f}%")
    cycle_rs[cname] = rets

# ---- ② 当前(最新周) 各赛道 13w/26w RS vs BIGCAP ----
last = sectors.index[-1]
print(f"\n===== 当前快照 @ {last.date()}: 赛道 13w/26w RS vs BIGCAP (正=跑赢大盘) =====")
cur = {}
for t in THEMES:
    r13 = rs_vs_bigcap(sectors[t], sectors['BIGCAP_INDEX'], 13).iloc[-1]
    r26 = rs_vs_bigcap(sectors[t], sectors['BIGCAP_INDEX'], 26).iloc[-1]
    cur[t] = (r13, r26)
order = sorted(cur, key=lambda x: cur[x][1], reverse=True)
for t in order:
    r13,r26 = cur[t]
    print(f"   {t:12s} 13w RS {r13*100:+7.1f}pp   26w RS {r26*100:+7.1f}pp")

# ---- ③ 当前领涨赛道近 13w 的 RS 趋势(看是加速还是退潮) ----
print("\n===== 当前第一领涨赛道的 RS 走势(近 13 周, 看是否在加速) =====")
lead = order[0]
lead_series = rs_vs_bigcap(sectors[lead], sectors['BIGCAP_INDEX'], 13).dropna()
for d in lead_series.index[-13:]:
    print(f"   {d.date()}  {lead_series[d]*100:+7.1f}pp")

# ---- ④ 历史轮动 + 下一轮预判(基于"上一轮早期/边缘题材, 下一轮成熟爆发") ----
rotation = {
 '2017': 'ICO + 公链平台(ETH/NEO/平台币) — 叙事: "区块链+万物代币化"',
 '2021': 'DeFi(UNI/AAVE) + NFT + memecoin(DOGE/SHIB) + 高性能L1(SOL/AVAX) — 叙事: "去中心化金融/链上乐高"',
 '2024': 'AI(FET/RENDER/TAO) + RWA(ONDO) + 低费L1/L2(SOL/TON/SUI) + 模块化 — 叙事: "AI×加密/现实资产上链"',
}
print("\n===== 历史题材轮动(已验证, 来自数据与公开叙事) =====")
for y,v in rotation.items():
    print(f"  {y}: {v}")
print("\n===== 下一轮(约2028减半后)预判: 本轮早期/边缘题材 -> 下轮成熟爆发 =====")
pred = [
 'DePIN(去中心化物理基建: HNT/AKT/PEAQ) — 本轮 early, 下轮最可能"AI基建"承接',
 'RWA 扩圈(除ONDO外: 国债/股票/信用上链) — 监管落地后加速',
 '模块化/意图/链抽象(CEL/TIA/DYM) — 本轮 early, 下轮基础设施主线',
 'AI-Agent 自主经济(本轮AI炒作的子层, 下轮分化出真正现金流者)',
 'BTC L2 / 稳定币合规(政策驱动, 美国GENIUS法案后机构稳定币)',
 'wildcard: 新一轮 memecoin 超级周期(每轮必有, 难预埋但需留口)',
]
for p in pred:
    print(f"  • {p}")

out = {'cycle_upwindow_rets':cycle_rs,
       'current_snapshot':{t:list(cur[t]) for t in cur},
       'leading_theme_now':lead,
       'rotation':rotation,'next_round_prediction':pred}
with open('_scratch_theme_leadership.json','w') as f:
    json.dump(out,f,indent=2,default=str)
print("\n[done] -> _scratch_theme_leadership.json")
