# -*- coding: utf-8 -*-
"""波动率 x 趋势 分层验证: 高波动股(如半导体周期股)是否像加密一样能4配对吃肉?
直接检验用户挑战: '超级赢家只有少数(NVDA/PLUG), 高波动股(Samsung/Hynix类)很多, 你说的太窄'
"""
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

WIN0, WIN1 = "2005-06-01", "2025-06-01"
first = df.apply(lambda s: s.first_valid_index())
last = df.apply(lambda s: s.last_valid_index())
mature = df.columns[(first <= WIN0) & (last >= WIN1)]
P = df[mature]
print(f"成熟标的宇宙: {len(P.columns)} 个 (覆盖 2005~2025 全窗口)")

def metrics(s):
    s = s.dropna()
    if len(s) < 520: return None
    yrs = (s.index[-1]-s.index[0]).days/365.25
    r = s.pct_change().dropna()
    if len(r) < 500: return None
    cagr = (s.iloc[-1]/s.iloc[0])**(1/yrs)-1
    vol = r.std()*np.sqrt(52)
    if vol <= 0: return None
    trend_ratio = cagr/vol                      # 高=平滑上行(低波动趋势赢家签名)
    t = np.arange(len(s))
    A = np.polyfit(t, s.values, 1)
    pred = np.polyval(A, t)
    ss_res = ((s.values-pred)**2).sum()
    ss_tot = ((s.values-s.values.mean())**2).sum()
    r2 = 1-ss_res/ss_tot if ss_tot > 0 else 0  # 线性趋势平滑度
    return dict(cagr=cagr*100, vol=vol*100, trend_ratio=trend_ratio, r2=r2)

M = {c: metrics(P[c]) for c in P.columns}
M = {c: m for c, m in M.items() if m}
syms = list(M.keys())
print(f"有效指标标的: {len(syms)}")

idx = {c: i for i, c in enumerate(P.columns)}

def excess(cols):
    sub = P.iloc[:, cols].dropna(how='any')
    if len(sub) < 520: return None
    r = sub.pct_change().dropna(how='any')
    if len(r) < 500: return None
    yrs = len(r)/52.0
    reb = (1+r.mean(axis=1)).prod()
    hld = (1+r).prod(axis=0).mean()
    if not (np.isfinite(reb) and np.isfinite(hld)): return None
    return (reb**(1/yrs)-1 - hld**(1/yrs)-1)*100

# ---- 全宇宙基线 (复算, 与旧脚本对照) ----
rng = np.random.default_rng(42)
ci_all = [idx[c] for c in syms]
ex2 = [excess(list(p)) for p in itertools.combinations(ci_all, 2)]
ex2 = np.array([x for x in ex2 if x is not None])
quads = [tuple(rng.choice(ci_all, 4, replace=False)) for _ in range(60000)]
ex4 = [excess(list(q)) for q in quads]; ex4 = np.array([x for x in ex4 if x is not None])
print("\n"+"="*72)
print(f"基线 2配对(全枚举 {len(ex2)}): 超额中位 {np.median(ex2):+.2f}pp | 跑赢 {(ex2>0).mean():.1%}")
print(f"基线 4配对(抽样 {len(ex4)}): 超额中位 {np.median(ex4):+.2f}pp | 跑赢 {(ex4>0).mean():.1%}")

# ---- 波动率 x 趋势 分层 ----
vols = np.array([M[c]['vol'] for c in syms])
trs  = np.array([M[c]['trend_ratio'] for c in syms])
vmed, tmed = np.median(vols), np.median(trs)
def cell(name):
    return [c for c in syms if
            (name.startswith('H') == (M[c]['vol'] > vmed)) and
            (name.endswith('H') == (M[c]['trend_ratio'] > tmed))]
cells = {
 'HV-HT': cell('HVHT'),   # 高波动高趋势 (Samsung/Hynix 类)
 'HV-LT': cell('HVLT'),   # 高波动低趋势 (均值回归型)
 'LV-HT': cell('LVHT'),   # 低波动高趋势 (NVDA/PLUG 类赢家)
 'LV-LT': cell('LVLT'),   # 低波动低趋势
}

print("\n"+"="*72)
print("分层 4配对再平衡 (每格抽样 40000 组, 仅同格内战)")
print(f"{'象限':<10}{'n':>4}{'中位vol':>9}{'中位trend':>11}{'4配对超额':>12}{'跑赢':>9}")
res = {}
for name, cell_syms in cells.items():
    if len(cell_syms) < 4:
        print(f"{name:<10} 样本不足 {len(cell_syms)}"); continue
    ci = [idx[c] for c in cell_syms]
    qs = [tuple(rng.choice(ci, 4, replace=False)) for _ in range(40000)]
    ex = np.array([x for x in (excess(list(q)) for q in qs) if x is not None])
    res[name] = (np.median(ex), (ex > 0).mean())
    print(f"{name:<10}{len(cell_syms):>4}{np.median(vols[np.isin(syms,cell_syms)]):>8.0f}%{np.median(trs[np.isin(syms,cell_syms)]):>11.2f}{np.median(ex):>+11.2f}pp{(ex>0).mean():>8.1%}")

# ---- 高波动子集 vs 全宇宙: 4配对 ----
hv_syms = [c for c in syms if M[c]['vol'] > vmed]
ci_hv = [idx[c] for c in hv_syms]
qs = [tuple(rng.choice(ci_hv, 4, replace=False)) for _ in range(60000)]
ex_hv = np.array([x for x in (excess(list(q)) for q in qs) if x is not None])
print("\n"+"="*72)
print(f"高波动子集(>中位vol, n={len(hv_syms)}) 4配对: 超额中位 {np.median(ex_hv):+.2f}pp | 跑赢 {(ex_hv>0).mean():.1%}")
print(f"对照 全宇宙 4配对: {np.median(ex4):+.2f}pp / {(ex4>0).mean():.1%}")
print(f"=> 高波动股是否像加密一样能4配对吃肉: {'是' if np.median(ex_hv) > np.median(ex4)+0.3 else '否'}")

# ---- 具体案例: 高波动股里哪些4配对表现好 (回应 Samsung/Hynix 类) ----
print("\n"+"="*72)
print("高波动股(HV)内部 2配对 超额 TOP8 (举例 Samsung/Hynix 类高波动能否吃肉):")
hv_pairs = [(a, b) for a, b in itertools.combinations([idx[c] for c in hv_syms], 2)]
samp = rng.choice(len(hv_pairs), min(20000, len(hv_pairs)), replace=False)
res2 = []
for i in samp:
    e = excess(list(hv_pairs[i]))
    if e is not None: res2.append((e, hv_pairs[i]))
res2.sort(reverse=True)
for e, (a, b) in res2[:8]:
    print(f"  {P.columns[a]:<10}+{P.columns[b]:<10} 超额 {e:+.2f}pp  (vol {M[P.columns[a]]['vol']:.0f}%/{M[P.columns[b]]['vol']:.0f}%)")
print("高波动股 2配对 超额中位:", f"{np.median([e for e,_ in res2]):+.2f}pp", " 跑赢:", f"{(np.array([e for e,_ in res2])>0).mean():.1%}")
