import csv, datetime as dt
import crypto_adoption_v2 as ca2

CSV = "data/weekly_adjclose_crypto50_10y.csv"
HALV = [dt.date(2012,11,28), dt.date(2016,7,9), dt.date(2020,5,11), dt.date(2024,4,20)]
WINDOWS = [("C1", HALV[1], HALV[2]), ("C2", HALV[2], HALV[3]), ("C3", HALV[3], dt.date(2026,8,7))]

# 读取
rows = []
with open(CSV) as f:
    r = csv.reader(f); hdr = next(r)
    for line in r:
        rows.append(line)
dates = [dt.date.fromisoformat(x[0]) for x in rows]
idx = {c:i for i,c in enumerate(hdr)}

def series(coin):
    if coin not in idx: return None
    out = []
    for d, line in zip(dates, rows):
        v = line[idx[coin]]
        out.append((d, float(v) if v not in ("", "nan", "None") else None))
    return out

def peak_ratio(s, a, b):
    seg = [v for d,v in s if a <= d <= b and v is not None]
    if len(seg) < 3: return None
    start = seg[0]
    peak = max(seg)
    return peak/start if start > 0 else None

res = {}
for coin in ca2.OFFENSE_COINS + ca2.DEFENSE_COINS:
    s = series(coin)
    if s is None:
        res[coin] = (None, "10y面板无数据"); continue
    ratios = []
    for name, a, b in WINDOWS:
        ratios.append(peak_ratio(s, a, b))
    n_pass = sum(1 for rr in ratios if rr is not None and rr >= 3)
    res[coin] = (n_pass, ratios)

# launch year to flag recently-added
launch = getattr(ca2, "COIN_META", {})
recent = {"LTC","RON","XRP","GLM","SKY","BCH","GRAM"}  # 近期手工加的

print(f"{'COIN':6} {'档':4} {'C1':>7} {'C2':>7} {'C3':>7}  备注")
print("-"*60)
for coin in ca2.DEFENSE_COINS + ca2.OFFENSE_COINS:
    n, ratios = res[coin]
    if ratios == "10y面板无数据":
        print(f"{coin:6} {'?':4}   {'无数据':>18}  {'近期加' if coin in recent else ''}")
        continue
    def fmt(x): return f"{x:6.1f}x" if x is not None else "  n/a "
    tier = "涨2轮" if n>=2 else ("涨1轮" if n==1 else "从未涨")
    note = "防御" if coin in ca2.DEFENSE_COINS else ("近期加" if coin in recent else "")
    print(f"{coin:6} {tier:4} {fmt(ratios[0])} {fmt(ratios[1])} {fmt(ratios[2])}  {note}")

print()
# 汇总分档
from collections import defaultdict
tiers = defaultdict(list)
for coin in ca2.OFFENSE_COINS:
    n, ratios = res[coin]
    if isinstance(ratios, str): continue
    tier = "涨2轮" if n>=2 else ("涨1轮" if n==1 else "从未涨")
    tiers[tier].append(coin)
for t in ["涨2轮","涨1轮","从未涨"]:
    print(f"{t} ({len(tiers[t])}): {sorted(tiers[t])}")
print()
print("近期手工加(别轻易prune):", sorted(c for c in ca2.DEFENSE_COINS+ca2.OFFENSE_COINS if c in recent))
print("ONDO 是RWA核心仓(不可删): 在池")
