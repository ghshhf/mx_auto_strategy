# -*- coding: utf-8 -*-
"""QA-04: 港股跳变=0 核验 + 缓存正确性/内存增长 + 性能回归"""
import os
import sys
import csv
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(BT))
sys.path.insert(0, BT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import backtest_engine as E

WK = os.path.join(E.DATA, "ashare_weekly_em")
PANEL = os.path.join(E.DATA, "ashare_panel_close_em.csv")
cfg = json.load(open(os.path.join(ROOT, "strategy_config.json"), encoding="utf-8"))

HK_KNOWN = {"00005", "00175", "00291", "00388", "00700", "00762", "00939", "00941",
            "01024", "01109", "01299", "01810", "01876", "02020", "02318", "02388",
            "03690", "09618", "09888", "09988"}

print("=" * 88)
print("1. 港股周线单周跳变核验 (阈值 +50% / +80%)")
print("=" * 88)
tot = {"hk": 0, "a": 0}
worst = {"hk": [], "a": []}
for fn in sorted(os.listdir(WK)):
    if not fn.endswith(".csv"):
        continue
    code = fn[:-4]
    grp = "hk" if code in HK_KNOWN else "a"
    rows = []
    with open(os.path.join(WK, fn), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                rows.append((r["date"], float(r["close"])))
            except (ValueError, KeyError, TypeError):
                continue
    tot[grp] += 1
    for k in range(1, len(rows)):
        a, b = rows[k - 1][1], rows[k][1]
        if a and a > 0 and b and b > 0:
            worst[grp].append((b / a - 1.0, code, rows[k][0]))

for grp, label in (("hk", "港股"), ("a", "A股")):
    w = sorted(worst[grp], reverse=True)
    n50 = sum(1 for c, _, _ in w if c > 0.50)
    n80 = sum(1 for c, _, _ in w if c > 0.80)
    top = w[0] if w else (0, "-", "-")
    print(f"{label}: {tot[grp]:>3} 只 | >+50% 共 {n50:>2} 处 | >+80% 共 {n80:>2} 处 | "
          f"最大单周 {top[0]:+.1%} ({top[1]} {top[2]})")

hk_n50 = sum(1 for c, _, _ in worst["hk"] if c > 0.50)
print(f"\n=> 港股 >+50% 跳变数 = {hk_n50}  "
      f"{'PASS (与工程师声明一致: 0 处)' if hk_n50 == 0 else 'FAIL'}")

print("\n" + "=" * 88)
print("2. first_listed_index 缓存正确性 (vs 无缓存暴力实现)")
print("=" * 88)
dates, codes, series = E.load_panel(PANEL)


def brute(vals):
    for k, v in enumerate(vals):
        if v is not None and v > 0:
            return k
    return None


E._FIRST_LISTED_CACHE.clear()
bad = []
for c, v in series.items():
    got = E.first_listed_index(v)          # 首次: miss
    got2 = E.first_listed_index(v)         # 二次: hit
    exp = brute(v)
    if got != exp or got2 != exp:
        bad.append((c, exp, got, got2))
print(f"校验 {len(series)} 列: 不一致 {len(bad)} 处 -> {'PASS' if not bad else 'FAIL ' + repr(bad[:5])}")

# 上市索引 -> 日期, 抽查几只已知票
print("\n抽查上市/数据起点:")
for c in ("300750", "603259", "300760", "300308", "300059", "600519"):
    if c in series:
        fi = E.first_listed_index(series[c])
        print(f"  {c}: first_listed_index={fi} -> {dates[fi]} | "
              f"冷却期解禁(lb26): {dates[min(len(dates)-1, fi+26+13)]}")

print("\n" + "=" * 88)
print("3. 缓存跨 load_panel 的内存增长 (id 缓存持有强引用, 永不淘汰)")
print("=" * 88)
E._FIRST_LISTED_CACHE.clear()
for n in range(1, 4):
    d2, c2, s2 = E.load_panel(PANEL)
    for v in s2.values():
        E.first_listed_index(v)
    print(f"  第 {n} 次 load_panel 后 _FIRST_LISTED_CACHE 条目数 = "
          f"{len(E._FIRST_LISTED_CACHE)}")
print("  说明: 每次 load_panel 都产生全新列表对象, 缓存条目线性累积且不释放。")
print("  当前规模(125列×1215周)影响很小, 但长驻进程/多次 run() 会持续膨胀 -> 建议改进(非阻塞)。")

print("\n" + "=" * 88)
print("4. 性能回归 (momentum_select 全窗口耗时)")
print("=" * 88)
pool_meta = {p["code"]: p for p in cfg["auto_select"]["candidate_pool"]
             if p.get("industry") not in E.OFFENSE_BLACKLIST}
i0 = next(i for i, d in enumerate(dates) if d >= "2016-08-05")


def timed(label, use_cache):
    E._FIRST_LISTED_CACHE.clear()
    orig = E.first_listed_index
    if not use_cache:
        E.first_listed_index = brute
    t = time.perf_counter()
    for i in range(i0, len(dates)):
        E.momentum_select(dates, series, pool_meta, i, 26, True,
                          score_mode="plain", trend_filter=True)
    el = time.perf_counter() - t
    E.first_listed_index = orig
    print(f"  {label}: {el:.3f}s  ({len(dates)-i0} 周)")
    return el


t_cache = timed("带缓存 (当前实现)", True)
t_brute = timed("无缓存 (每次线性扫描)", False)
print(f"  => 缓存加速 {t_brute/t_cache:.2f}x  "
      f"{'PASS (缓存有效)' if t_cache <= t_brute else 'WARN (缓存未带来收益)'}")

t_run = time.perf_counter()
E._FIRST_LISTED_CACHE.clear()
E.run(offense_mode="momentum", momentum_lookback=26, use_tech=True,
      core_satellite=True, core_frac=0.5, death_cross=True, grid=False,
      score_mode="plain", panel_path=PANEL, use_core_sub=True, trend_filter=True)
print(f"\n  完整 run() 单次耗时: {time.perf_counter()-t_run:.2f}s "
      f"{'PASS (<10s)' if time.perf_counter()-t_run < 10 else 'WARN'}")
