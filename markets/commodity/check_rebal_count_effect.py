import pandas as pd, numpy as np
import itertools

FILES = [
    "data/us_universe_weekly_adjclose.csv",
    "data/hk_leaders_weekly_adjclose.csv",
    "data/equities_weekly_adjclose.csv",
    "data/us_etf_weekly_adjclose.csv",
]
frames = []
for f in FILES:
    d = pd.read_csv(f, index_col=0, parse_dates=True).apply(pd.to_numeric, errors='coerce')
    frames.append(d)
df = pd.concat(frames, axis=1)
df = df.loc[:, ~df.columns.duplicated()]

# 成熟标的: 首值早于 2005-06-01 且尾值晚于 2025-06-01 (覆盖整个窗口, 排除近期IPO/MARA类)
WIN0, WIN1 = "2005-06-01", "2025-06-01"
first = df.apply(lambda s: s.first_valid_index())
last = df.apply(lambda s: s.last_valid_index())
mature = df.columns[(first <= WIN0) & (last >= WIN1)]
P = df[mature]
print(f"成熟标的宇宙: {len(P.columns)} 个 (覆盖 2005~2025 全窗口)")
print("样例:", list(P.columns[:15]))

R = P.pct_change()
N_FULL = len(P)

def excess_for_cols(cols):
    sub = P.iloc[:, cols]
    sub = sub.dropna(how='any')            # 该组合自身有效日期交集
    if len(sub) < 520:                     # 至少 ~10 年
        return None
    r = sub.pct_change().dropna(how='any')
    if len(r) < 500:
        return None
    yrs = len(r) / 52.0
    reb = (1 + r.mean(axis=1)).prod()
    hld = (1 + r).prod(axis=0).mean()
    asset_growth = (1 + r).prod(axis=0)
    asset_growth = np.where(asset_growth <= 0, np.nan, asset_growth)  # 跌到0/负价的标的不参与(避免CAGR溢出)
    reb_c = reb ** (1 / yrs) - 1
    hld_c = hld ** (1 / yrs) - 1
    if not (np.isfinite(reb_c) and np.isfinite(hld_c)):
        return None
    ag = asset_growth ** (1 / yrs) - 1
    dom = np.nanmax(ag) - np.nanmedian(ag)   # 赢家浓度(忽略崩溃标的)
    if not np.isfinite(dom):
        return None
    return hld_c * 100, reb_c * 100, (reb_c - hld_c) * 100, dom * 100

# ---- 2 配对: 全枚举 ----
cols_idx = list(range(len(P.columns)))
pairs = list(itertools.combinations(cols_idx, 2))
ex2, d2 = [], []
for a, b in pairs:
    r = excess_for_cols([a, b])
    if r:
        ex2.append(r[2]); d2.append(r[3])
ex2, d2 = np.array(ex2), np.array(d2)
print("\n" + "="*72)
print(f"2 配对 (全枚举 {len(ex2)} 对) 再平衡超额中位: {np.median(ex2):+.2f}pp | 跑赢占比: {(ex2>0).mean():.1%}")

# ---- 4 配对: 随机抽样 ----
rng = np.random.default_rng(42)
quads = [tuple(rng.choice(cols_idx, 4, replace=False)) for _ in range(60000)]
ex4, dom4 = [], []
for q in quads:
    r = excess_for_cols(list(q))
    if r:
        ex4.append(r[2]); dom4.append(r[3])
ex4, dom4 = np.array(ex4), np.array(dom4)
print(f"4 配对 (抽样 {len(ex4)} 组) 再平衡超额中位: {np.median(ex4):+.2f}pp | 跑赢占比: {(ex4>0).mean():.1%}")

print("\n" + "="*72)
print("对照: 同一批股票, 4 配对是否比 2 配对更能'触发波动'?")
print(f"  波动触发论预期 4>>2; 实测 4 配对 {np.median(ex4):+.2f}pp vs 2 配对 {np.median(ex2):+.2f}pp")

# ---- 赢家浓度归因: 4 配对按浓度四分位 ----
print("\n" + "="*72)
print("赢家浓度归因: 4 配对按'最佳-中位单名CAGR差'四分位拆分")
qb = pd.qcut(dom4, 4, labels=['Q1低','Q2','Q3','Q4高'])
for lab in ['Q1低','Q2','Q3','Q4高']:
    m = qb == lab
    print(f"  {lab} (dom中位 {np.median(dom4[m])*100:+.0f}pp): 4配对超额中位 {np.median(ex4[m]):+.2f}pp, 跑赢占比 {(ex4[m]>0).mean():.1%}")

low = dom4 <= np.quantile(dom4, 0.25)
print("\n" + "="*72)
print("结论性对照 — 低赢家浓度子集(前25%):")
print(f"  低浓度 4 配对 超额中位 {np.median(ex4[low]):+.2f}pp, 跑赢占比 {(ex4[low]>0).mean():.1%}")
print(f"  (对照) 2 配对 全样本    超额中位 {np.median(ex2):+.2f}pp, 跑赢占比 {(ex2>0).mean():.1%}")
print("  => 若低浓度4配对 ≈ 或 > 2配对, 则'4配对触发不了波动'是误诊, 真凶=赢家浓度")
