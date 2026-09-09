import pandas as pd, numpy as np

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
df = df.dropna(axis=1, thresh=int(0.5 * len(df)))

MIN_WEEKS = 260

def series_cagr(p):
    p = p.dropna()
    if len(p) < MIN_WEEKS:
        return None
    yrs = (p.index[-1] - p.index[0]).days / 365.25
    if yrs < 5:
        return None
    return (p.iloc[-1] / p.iloc[0]) ** (1 / yrs) - 1

def rebal_vs_cash(p):
    """50/50 stock vs cash(constant 1), monthly(4wk) rebalance. Returns (hold_cagr, reb_cagr)."""
    p = p.dropna()
    if len(p) < MIN_WEEKS:
        return None, None
    yrs = (p.index[-1] - p.index[0]).days / 365.25
    if yrs < 5:
        return None, None
    r = p.pct_change().dropna()
    vs, vc = 0.5, 0.5
    for i in range(len(r)):
        vs *= (1 + r.iloc[i]); vc *= 1.0
        if (i + 1) % 4 == 0:
            tot = vs + vc; vs, vc = tot / 2, tot / 2
    hold = (p.iloc[-1] / p.iloc[0]) - 1
    reb = (vs + vc) - 1
    return (1 + hold) ** (1 / yrs) - 1, (1 + reb) ** (1 / yrs) - 1

def rebal_2stock(a, b):
    """Equal-weight 2-stock portfolio, monthly rebalance vs buy-and-hold(drift). Returns (hold_cagr, reb_cagr)."""
    pa, pb = a.dropna(), b.dropna()
    common = pa.index.intersection(pb.index)
    if len(common) < MIN_WEEKS:
        return None, None
    sa = pa.reindex(common); sb = pb.reindex(common)
    yrs = (common[-1] - common[0]).days / 365.25
    if yrs < 5:
        return None, None
    ra = sa.pct_change().dropna(); rb = sb.pct_change().dropna()
    # hold: start 50/50, weights drift
    val = 1.0; w = np.array([0.5, 0.5]); rv = []
    for i in range(len(ra)):
        val *= (1 + np.dot(w, [ra.iloc[i], rb.iloc[i]])); rv.append(val)
        w = w * (1 + np.array([ra.iloc[i], rb.iloc[i]])); w /= w.sum()
    hold_cagr = rv[-1] ** (1 / yrs) - 1
    # rebal monthly
    val = 1.0; w = np.array([0.5, 0.5]); rv = []
    for i in range(len(ra)):
        val *= (1 + np.dot(w, [ra.iloc[i], rb.iloc[i]])); rv.append(val)
        if (i + 1) % 4 == 0:
            w = np.array([0.5, 0.5])
    reb_cagr = rv[-1] ** (1 / yrs) - 1
    return hold_cagr, reb_cagr

# ---- Part 1: single stock vs cash ----
rows = []
for c in df.columns:
    h, rb = rebal_vs_cash(df[c])
    if h is not None:
        rows.append((c, h * 100, rb * 100, (rb - h) * 100))
res1 = pd.DataFrame(rows, columns=['sym', 'hold', 'rebal', 'excess'])
print("="*70)
print("PART 1 — 单只标的 vs 现金 (50/50 月度再平衡) vs 持有不动")
print("="*70)
print(f"测试标的数: {len(res1)}")
print(f"再平衡跑赢持有 的比例: {(res1.excess>0).mean():.1%}")
print(f"持有CAGR中位: {res1.hold.median():.1f}% | 再平衡CAGR中位: {res1.rebal.median():.1f}% | 超额中位: {res1.excess.median():+.2f}pp")
for sym in ['NVDA', 'NVDA.OQ']:
    if sym in res1['sym'].values:
        print(f"  NVDA: hold={res1[res1.sym==sym].hold.iloc[0]:.1f}% reb={res1[res1.sym==sym].rebal.iloc[0]:.1f}% excess={res1[res1.sym==sym].excess.iloc[0]:+.1f}pp")
print("\n再平衡最赚 TOP8:")
print(res1.sort_values('excess', ascending=False).head(8).to_string(index=False))
print("\n再平衡最亏 BOTTOM8:")
print(res1.sort_values('excess').head(8).to_string(index=False))

# ---- Part 2: 2-stock portfolio rebal vs hold ----
cols = [c for c in df.columns]
rng = np.random.default_rng(7)
pairs = []
n = len(cols)
for _ in range(3000):
    i, j = rng.integers(0, n, 2)
    if i != j:
        pairs.append((cols[i], cols[j]))
rows2 = []
for a, b in pairs:
    h, rb = rebal_2stock(df[a], df[b])
    if h is not None:
        rows2.append((f"{a}+{b}", h * 100, rb * 100, (rb - h) * 100))
res2 = pd.DataFrame(rows2, columns=['pair', 'hold', 'rebal', 'excess'])
print("\n" + "="*70)
print("PART 2 — 双股票等权组合 月度再平衡 vs 持有(权重漂移)")
print("="*70)
print(f"测试组合数: {len(res2)}")
print(f"再平衡跑赢持有 的比例: {(res2.excess>0).mean():.1%}")
print(f"持有CAGR中位: {res2.hold.median():.1f}% | 再平衡CAGR中位: {res2.rebal.median():.1f}% | 超额中位: {res2.excess.median():+.2f}pp")
print("\n双股组合再平衡最赚 TOP5:")
print(res2.sort_values('excess', ascending=False).head(5).to_string(index=False))
print("\n双股组合再平衡最亏 BOTTOM5:")
print(res2.sort_values('excess').head(5).to_string(index=False))
