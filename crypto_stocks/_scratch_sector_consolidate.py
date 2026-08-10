"""赛道整合 + 下一轮领涨预判 (零前视, 数据驱动 + 有限叙事论)
  ① 把 56 币归并到一套互斥的"整合赛道"分类 (消除原 12 个重叠主题)
  ② 每个历史周期上行窗: 各整合赛道累计收益 / 对 BTC 的 RS (纯数据, 无手标)
  ③ 当前(2026-08-07)各赛道 13w/26w RS 快照 -> 谁在领涨(=饱和) 谁在垫底(=早期)
  ④ 用"有限叙事 + 轮动律 + 成熟度"给下一轮(≈2028减半后)领涨赛道概率排序
"""
import pandas as pd, numpy as np, json, html

CSV = 'data/weekly_adjclose_crypto50.csv'
df = pd.read_csv(CSV, parse_dates=['date']).sort_values('date').reset_index(drop=True)
df = df.set_index('date')
ALL = [c for c in df.columns if c != 'BTC']
print(f"区间 {df.index[0].date()} ~ {df.index[-1].date()}  周数={len(df)}  总币数={len(ALL)+1}(含BTC)")

# ===================== ① 整合赛道分类 (互斥主分类) =====================
# 用户论点: 加密叙事有限 -> 一套可穷举的"整合赛道"
SECTOR = {
 'L1 智能合约公链': ['ETH','ADA','AVAX','SOL','DOT','NEAR','APT','SUI','SEI','TRX','TON','METIS'],
 'L2 / 扩容':       ['ARB','OP','STRK','MANTA','MATIC'],
 'DeFi / DEX':      ['1INCH','AAVE','COMP','CRV','LDO','MKR','SNX','UNI','JUP'],
 '永续交易所 / Deriv DEX': ['DYDX','GMX'],
 'AI × 加密':       ['FET','RENDER','RNDR','TAO','PHB','BLZ'],
 'DePIN / AI基建':   ['HNT','PEAQ','AKT'],
 'GameFi / 元宇宙':  ['AXS','GALA','ILV','BEAM','IMX'],
 '隐私 / 匿名':      ['ZEC','SECRET','DASH'],
 'RWA / 真实资产':   ['ONDO','MANTRA','RIO','POLYX','PAS'],
 '存储 / 数据':      ['FIL','AR'],
 '模块化 / DA':      ['TIA','DYM'],
 '基础设施':         ['LINK','ENS','API3','GRT'],
 '平台币':           ['OKB','BNB'],
}
# 覆盖校验
mapped = [c for v in SECTOR.values() for c in v]
assert len(mapped) == len(set(mapped)), "重复映射!"
unmapped = [c for c in ALL if c not in mapped]
print(f"已映射 {len(mapped)} 币, 未映射 {unmapped}")
assert not unmapped, f"未映射币: {unmapped}"

def sector_index(sector_coins, s, e):
    """区间内等权赛道指数(每币各自以区间首有效价归一=1, 等均)
       剔除窗口内全为空的币(赛道当时未上市 -> 不参与, 不拖成 nan)"""
    cols = [c for c in sector_coins if c in df.columns]
    sub = df.loc[s:e, cols].ffill().bfill()
    valid = [c for c in cols if sub[c].notna().any()]   # 窗口内有数据的币
    if not valid:
        return None                                     # 整赛道当时未上市
    norm = sub[valid] / sub[valid].iloc[0]
    return norm.mean(axis=1)

# ===================== ② 各周期上行窗: 赛道收益 + RS vs BTC =====================
CYCLES = {
 '2017(partial)': ('2017-08-11','2017-12-31'),
 '2021':          ('2020-05-11','2021-11-05'),
 '2024':          ('2024-04-19','2025-09-26'),
}
btc = df['BTC']
print("\n===== 各周期上行窗: 赛道累计收益 & 对BTC的RS(纯数据, 无手标) =====")
cycle_out = {}
for cname,(s,e) in CYCLES.items():
    rows=[]
    for sec, coins in SECTOR.items():
        idx = sector_index(coins, s, e)
        if idx is None or len(idx)<5:
            rows.append((sec, float('nan'), float('nan')))
            continue
        ret = idx.iloc[-1]/idx.iloc[0]-1
        bret = btc.loc[s:e].iloc[-1]/btc.loc[s:e].iloc[0]-1
        rs = ret - bret
        rows.append((sec, ret, rs))
    rows.sort(key=lambda x: (x[1] if x[1]==x[1] else -1e9), reverse=True)
    print(f"\n[{cname}] {s}~{e}")
    for sec,ret,rs in rows:
        if ret!=ret:
            print(f"   {sec:16s}   N/A (当时未上市)")
        else:
            print(f"   {sec:16s} 收益 {ret*100:+8.1f}%   RS_vs_BTC {rs*100:+7.1f}pp")
    cycle_out[cname] = {sec:([None,None] if ret!=ret else [round(ret*100,1),round(rs*100,1)]) for sec,ret,rs in rows}

# ===================== ③ 当前快照: 各赛道 13w/26w RS vs BTC =====================
last = df.index[-1]
print(f"\n===== 当前快照 @ {last.date()}: 赛道 13w/26w RS vs BTC (正=跑赢) =====")
def rs_vs_btc(series, w):
    s = series/series.shift(w); b = btc/btc.shift(w)
    return (s-b).dropna().iloc[-1]
cur={}
for sec, coins in SECTOR.items():
    idx = sector_index(coins, df.index[0], last)
    cur[sec] = (rs_vs_btc(idx,13), rs_vs_btc(idx,26))
order = sorted(cur, key=lambda x: cur[x][1], reverse=True)
for sec in order:
    r13,r26 = cur[sec]
    print(f"   {sec:16s} 13w {r13*100:+7.1f}pp   26w {r26*100:+7.1f}pp")

# ===================== ④ 下一轮领涨预判 (有限叙事 + 轮动律 + 成熟度) =====================
# 成熟度代理: 当前26w RS 高=正在领涨=趋于饱和(下轮难再领); 低=早期(下轮候选)
# 渗透率(来自 CRYPTO_THEMES, 越低=上行空间越大): 结构护城河/政策尾风 手评
PEN = {'L1 智能合约公链':25,'L2 / 扩容':18,'DeFi / DEX':12,'AI × 加密':3,'DePIN / AI基建':2,
       'GameFi / 元宇宙':8,'隐私 / 匿名':3,'RWA / 真实资产':1,'存储 / 数据':5,
       '模块化 / DA':8,'基础设施':10,'平台币':15,'永续交易所 / Deriv DEX':6}
# 结构护城河/宏观尾风 手评分(1-5): 真实经济连接/机构/政策/十年主题
TAIL = {'L1 智能合约公链':4,'L2 / 扩容':3,'DeFi / DEX':3,'AI × 加密':5,'DePIN / AI基建':5,
        'GameFi / 元宇宙':2,'隐私 / 匿名':2,'RWA / 真实资产':5,'存储 / 数据':3,
        '模块化 / DA':3,'基础设施':4,'平台币':2,'永续交易所 / Deriv DEX':4}
# 轮动律契合: 2024 是否"早期/边缘未领涨" (1=是早期未领涨=下轮候选, 0=已领涨=饱和)
ROT = {'L1 智能合约公链':0.5,'L2 / 扩容':0.2,'DeFi / DEX':0.1,'AI × 加密':0.3,'DePIN / AI基建':1.0,
       'GameFi / 元宇宙':0.4,'隐私 / 匿名':0.6,'RWA / 真实资产':1.0,'存储 / 数据':0.5,
       '模块化 / DA':0.9,'基础设施':0.6,'平台币':0.2,'永续交易所 / Deriv DEX':0.85}

print("\n===== 下一轮(≈2028减半后)领涨赛道 概率排序 =====")
scores=[]
for sec in SECTOR:
    r26 = cur[sec][1]
    maturity = 1/(1+max(r26,0)*3)      # 当前领涨(高RS) -> 成熟度↑ -> 下轮得分↓
    pen_gap = 1 - PEN[sec]/25          # 渗透越低 -> 上行空间越大
    s = 100*(0.34*ROT[sec] + 0.33*maturity + 0.18*pen_gap + 0.15*(TAIL[sec]/5))
    scores.append((sec, s, ROT[sec], maturity, pen_gap, TAIL[sec]/5, r26))
tot = sum(x[1] for x in scores)
scores.sort(key=lambda x:x[1], reverse=True)
pred=[]
for sec,s,rot,mat,pg,tail,r26 in scores:
    pct = s/tot*100
    pred.append((sec, round(pct,1), round(r26*100,1), round(rot,2), round(mat,2), round(pg,2), round(tail,2)))
    print(f"   {sec:16s} 概率 {pct:5.1f}%   当前26wRS {r26*100:+6.1f}pp  轮动 {rot} 成熟度 {mat:.2f} 渗透缺口 {pg:.2f} 尾风 {tail:.2f}")

out = {'sector_map':SECTOR, 'cycle_returns':cycle_out,
       'current_rs':{s:[round(cur[s][0]*100,1),round(cur[s][1]*100,1)] for s in cur},
       'next_round_prediction':[{'sector':p[0],'prob':p[1],'cur26wRS':p[2],'rotation':p[3],
                                 'maturity':p[4],'pen_gap':p[5],'tailwind':p[6]} for p in pred]}
with open('_scratch_sector_consolidate.json','w') as f:
    json.dump(out,f,indent=2,default=str)
print("\n[done] -> _scratch_sector_consolidate.json")
