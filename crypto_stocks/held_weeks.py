"""统计当前池子每个币在最终回测中被持有的周数(held weeks).
held weeks≈0 的币是'指数敏感/纯占位'币: 删了几乎不影响回测, 仅改选股相位.
held weeks 高的币是真被选中的, 删了会动 needle."""
import sys, json
sys.path.insert(0, '.')
import pandas as pd
import crypto_options_bt as bt
import crypto_adoption_v2 as ca2

STABLE = getattr(bt, 'STABLE', 'STABLE')
_orig = bt._build_target
_held = {}  # sym -> weeks held (weight>0)

def _wrap(px, t_idx, cfg, coin_state, sectors, *a, **k):
    built = _orig(px, t_idx, cfg, coin_state, sectors, *a, **k)
    if built is None:
        return None
    target, regime = built
    for c, w in target.items():
        if c == STABLE or w is None or w <= 0:
            continue
        _held[c] = _held.get(c, 0) + 1
    return target, regime

bt._build_target = _wrap

px = pd.read_csv('data/weekly_adjclose_crypto50.csv', index_col=0, parse_dates=True)
cfg = dict(bt.DEFAULT_CFG)
r = bt.run_bt(px, cfg_dict=cfg, label='held', return_recs=False)

# 合并市值快照
snap = {}
try:
    with open('mcap_snapshot.json', encoding='utf-8') as f:
        for d in json.load(f):
            snap[d['sym']] = d.get('mcap')
except Exception:
    pass
# 修正 5 个异常币 (WebSearch 核实)
snap.update({'MKR': 1.2e9, 'CFG': 8.0e7, 'JUP': 6.2e8, 'DYDX': 1.0e8, 'PHB': 2.5e5})

# 赛道映射
sector_of = {}
for th, coins in ca2.THEME_COINS.items():
    for c in coins:
        sector_of.setdefault(c, th)

def yi(mc):
    return mc/1e8 if mc else None

rows = []
for c in ca2.ALL_COINS:
    rows.append((c, _held.get(c, 0), yi(snap.get(c)), sector_of.get(c, '防御')))

# 按 held weeks 降序, 同 held 按市值升序(低市值优先)
rows.sort(key=lambda x: (-x[1], (x[2] if x[2] is not None else 1e12)))
print(f"{'SYM':<7}{'held周':>7}{'市值(亿$)':>12}  {'赛道':<12}  备注")
print("-"*70)
for c, h, m, sec in rows:
    if m is None:
        ms = "N/A"
    elif m >= 1:
        ms = f"{m:,.1f}"
    else:
        ms = f"{m*100:.1f}¢"  # 小于1亿用'分'
    note = ""
    if h == 0: note = "← 纯占位(删了只动相位)"
    elif h < 10: note = "← 极少持有"
    print(f"{c:<7}{h:>7}{ms:>12}  {sec:<12}  {note}")

print(f"\n总周数={r['weeks']}  总币数={len(rows)}  held>0 的币={sum(1 for _,h,_,_ in rows if h>0)}")
# 输出 JSON 供后续
out = [{'sym':c,'held':h,'mcap_usd':snap.get(c),'sector':sec} for c,h,m,sec in rows]
with open('held_weeks.json','w',encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("[*] 已写出 held_weeks.json")
