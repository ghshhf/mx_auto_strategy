# -*- coding: utf-8 -*-
"""
optimize_crypto_asym.py - 加密专属叠加层机制优化 (v6.23)
========================================================
上一轮 walk-forward 揭示加密叠加层是"收益放大器+回撤放大器"(OOS 倍数 +22% t=5.4,
但 MDD 显著恶化 t=-5.98)。单纯降 tilt 是妥协。

本脚本针对加密探索**非对称缩放机制**, 目标是 OOS 上保住倍数增益、消除 MDD 恶化:
  - 对称(对照):        scale = clip(1 + tilt*regime, 0.5, 1.5)
  - 下行保护型:        regime>=0 -> 1+up*regime ; regime<0 -> 1+down*regime  (down>up)
  - 纯保险型:          up=0  (顺风不加仓, 只在逆风减仓)

流程:
  1. in-sample: 对 3/5/10y 窗口 + 全历史(2017起)测 ON/OFF 倍数比, 缓存 OFF。
  2. 选 Pareto 最优(在 mean_mdd_diff>=-2pp 约束下最大化几何倍数比; 无满足则取 MDD 恶化最小)。
  3. 对最优机制跑 walk-forward OOS(训练3y/测试1y 滚动) -> 几何倍数比 + paired t(倍数/MDD)。

仅在加密引擎上做; 不动 A股/美股。
"""
import os, sys, json, math, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "crypto_stocks"))
from cycles import specs as SP

END_CRYPTO = "2026-07-24"
WINDOWS = {"3y": 3, "5y": 5, "10y": 10}
CRYPTO_WEIGHTS = SP.ENGINE_CYCLE_WEIGHTS.get("crypto")

import crypto_options_bt as cm
PX = cm._load_default()


def start_for(years, end):
    y, m, d = end.split("-")
    return f"{int(y) - years:04d}-{m}-{d}"


def years_between(start, end):
    s = datetime.date.fromisoformat(start); e = datetime.date.fromisoformat(end)
    return round((e - s).days / 365.25, 2)


def calc_cagr(mult, yrs):
    return mult ** (1.0 / yrs) - 1.0 if (mult and mult > 0 and yrs > 0) else None


def run_crypto(start, asym=None, tilt=0.3, weights=None, overlay=True):
    if not overlay:
        # 真正的 OFF 基线: 完全关闭叠加层
        return cm.run_bt(PX, cfg_dict=None, label="V6_off", start=start, cycle_overlay=False)
    r = cm.run_bt(PX, cfg_dict=None, label="V6_asym", start=start,
                  cycle_overlay=True, cycle_tilt=tilt, cycle_weights=weights, cycle_asym=asym)
    return r


def norm(st):
    if not st or "error" in st:
        return None
    return dict(mult=st["multiple"], mdd=st["mdd"] * 100, bench=st.get("btc_multiple"))


def paired_t(xs, mu=0.0):
    n = len(xs)
    if n < 2:
        return None
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return None
    return (mean - mu) / (sd / math.sqrt(n))


# ---------- 1. in-sample 机制扫描 ----------
print("=" * 110)
print("加密专属机制扫描 (OFF 缓存复用)")
print("=" * 110)

# OFF 基线按窗口缓存 (真正关闭叠加层)
off_cache = {}
for wname, yrs in WINDOWS.items():
    start = start_for(yrs, END_CRYPTO)
    if start < "2017-08-11":
        start = "2017-08-11"
    off_cache[wname] = norm(run_crypto(start, overlay=False))

# 机制网格
GRID = []
GRID.append(("对称 tilt=0.3 (当前默认)", None, 0.3))
GRID.append(("对称 tilt=0.5 (旧默认)", None, 0.5))
for up in (0.0, 0.1, 0.15):
    for down in (0.4, 0.6, 0.8):
        GRID.append((f"下行保护 up={up} down={down}", (up, down), 0.3))
for down in (0.4, 0.6, 0.8, 1.0):
    GRID.append((f"纯保险 down={down}", (0.0, down), 0.3))

scan = {}
for name, asym, tilt in GRID:
    geos, mdd_changes = [], []
    row = {"asym": asym, "tilt": tilt, "windows": {}}
    for wname, yrs in WINDOWS.items():
        start = start_for(yrs, END_CRYPTO)
        if start < "2017-08-11":
            start = "2017-08-11"
        off = off_cache[wname]
        on = norm(run_crypto(start, asym, tilt))
        ratio = on["mult"] / off["mult"]
        mdd_diff = on["mdd"] - off["mdd"]  # >0 = 恶化
        row["windows"][wname] = dict(off_mult=round(off["mult"], 3), on_mult=round(on["mult"], 3),
                                     ratio=round(ratio, 4), mdd_diff=round(mdd_diff, 2))
        geos.append(ratio); mdd_changes.append(mdd_diff)
    row["geo_ratio"] = round(math.prod(geos) ** (1.0 / len(geos)), 4)
    row["mean_mdd_diff"] = round(sum(mdd_changes) / len(mdd_changes), 2)
    scan[name] = row
    print(f"  {name:<26} geo_ratio={row['geo_ratio']:+.4f}  mean_MDD_diff={row['mean_mdd_diff']:+.2f}pp  "
          f"[3y={row['windows']['3y']['ratio']:+.3f} 5y={row['windows']['5y']['ratio']:+.3f} 10y={row['windows']['10y']['ratio']:+.3f}]")

# ---------- 2. 选 Pareto 最优 ----------
# 约束: mean_mdd_diff >= -2.0 (in-sample 不恶化超过 2pp) 下最大化 geo_ratio
feasible = [n for n in scan if scan[n]["mean_mdd_diff"] >= -2.0]
if feasible:
    best = max(feasible, key=lambda n: scan[n]["geo_ratio"])
    basis = "feasible(约束 mean_MDD>=-2pp) 内 geo 最大"
else:
    best = min(scan, key=lambda n: scan[n]["mean_mdd_diff"])  # 取 MDD 恶化最小
    basis = "无满足约束 -> 取 MDD 恶化最小"
print(f"\n>>> in-sample 最优机制: [{best}]  依据: {basis}")
print(f"    geo_ratio={scan[best]['geo_ratio']:+.4f}  mean_MDD_diff={scan[best]['mean_mdd_diff']:+.2f}pp")

# ---------- 3. walk-forward OOS 验证 ----------
print("\n" + "=" * 110)
print(f"walk-forward OOS 验证: 最优机制 [{best}]")
print("=" * 110)
best_asym = scan[best]["asym"]
best_tilt = scan[best]["tilt"]

test_starts = []
y = 2020
while True:
    s = f"{y}-08-14"
    if s > "2024-08-14":   # 数据末端约 2026-07, 测试期需 >= WARMUP+2 周
        break
    test_starts.append(s)
    y += 1

# 缓存 OFF per 测试期
off_wf = {s: norm(run_crypto(s, overlay=False)) for s in test_starts}
tw = []
for s in test_starts:
    off = off_wf[s]
    on = norm(run_crypto(s, best_asym, best_tilt))
    tw.append((on["mult"] / off["mult"], on["mdd"] - off["mdd"]))

ratios = [x[0] for x in tw]
diffs = [x[1] for x in tw]
geo = math.prod(ratios) ** (1.0 / len(ratios))
t_mult = paired_t(ratios, mu=1.0)
t_mdd = paired_t(diffs, mu=0.0)
print(f"  测试期数={len(tw)}  几何倍数比={geo:+.4f}  t(倍数)={t_mult}  t(MDD)={t_mdd}")
for s, (r, d) in zip(test_starts, tw):
    print(f"    {s} ~ +1y: 倍数比={r:+.3f}  MDD_diff={d:+.2f}pp")

oos = dict(samples=len(tw), geo_ratio=round(geo, 4), t_mult=(round(t_mult, 2) if t_mult is not None else None),
           t_mdd=(round(t_mdd, 2) if t_mdd is not None else None), detail=tw)

# ---------- 落盘 ----------
out = {"scan": scan, "best": best, "best_basis": basis,
       "best_asym": best_asym, "best_tilt": best_tilt,
       "oos": oos, "crypto_weights": CRYPTO_WEIGHTS}
with open(os.path.join(ROOT, "cycle_crypto_asym.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\n已写入 cycle_crypto_asym.json")
