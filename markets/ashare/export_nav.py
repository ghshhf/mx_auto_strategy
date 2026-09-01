# -*- coding: utf-8 -*-
"""
export_nav.py — 把回测结果导出为 docs/data/nav.json (数据层)

设计原则: 数据与渲染分离。本脚本只产出「数据文件」, 渲染交给 docs/curves.html。
未来更新流程:
  1. 改 strategy_config.json / 本脚本 CONFIGS (改几个关键参数)
  2. 运行 python export_nav.py  ->  重算并重写 docs/data/nav.json
  3. docs/curves.html 通过 fetch 自动读取新数据, 页面逻辑不变, 无需重生成整页

基线:   cf=0.6, lb=26, plain, core_satellite, 死叉 (v6.18 权威口径)
优化:   cf=0.5, lb=26, plain, core_satellite, 死叉, use_tech=False, trend_filter=False
       (v6.18 权威真值 = 18.185x / CAGR 22.31% / MDD -33.31%; 趋势过滤被证为损害已移除)
面板:   腾讯后复权周线 ashare_panel_close_em.csv (tencent_hfq_rebuild.py)
"""
import os, sys, json, datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_engine as E

BASE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(E.DATA, "ashare_panel_close_em.csv")
if not os.path.exists(PANEL):
    print(f"[错误] 找不到面板 {PANEL}"); sys.exit(1)

# v6.18 权威口径: use_tech=False + trend_filter=False (趋势过滤经 v6.18 实证为损害, 已移除)
COMMON = dict(
    offense_mode="momentum", momentum_lookback=26, use_tech=False,
    core_satellite=True, death_cross=True, grid=False,
    score_mode="plain", start_capital=1_000_000,
    panel_path=PANEL, use_core_sub=True,
)
CONFIGS = [
    ("baseline", "基线(cf=0.6, v6.18)", {**COMMON, "core_frac": 0.6,
        "trend_filter": False, "industry_diversify": False, "rel_strength": False}),
    ("optimized", "优化(cf=0.5, v6.18权威18.185x)", {**COMMON, "core_frac": 0.5,
        "trend_filter": False, "industry_diversify": False, "rel_strength": False}),
]

dates, codes, series = E.load_panel(PANEL)
hs_full = series[E.HS300]

# 跑两个配置
results = {}
for key, label, cfg in CONFIGS:
    stats, nav, start, plan = E.run(**cfg)
    full_idx = [i for i in range(start, len(dates)) if nav[i] and nav[i] > 0]
    last_idx = full_idx[-1]
    results[key] = {"label": label, "nav": nav, "start": start, "stats": stats,
                    "full_idx": full_idx, "last_idx": last_idx, "cfg": cfg}
    print(f"[{label}] 全量: {dates[start]} ~ {dates[last_idx]} | "
          f"{stats['final_multiple']:.2f}x | MDD {stats['mdd']:.1f}%")

last_idx = min(r["last_idx"] for r in results.values())
last_date = dates[last_idx]


def window_indices(start, n_years):
    ld = dt.date.fromisoformat(last_date)
    target = ld.replace(year=ld.year - n_years)
    t0 = dt.date.fromisoformat(dates[start])
    if target < t0:
        target = t0
    tstr = target.isoformat()
    lo = None
    for i in results["baseline"]["full_idx"]:
        if dates[i] >= tstr:
            lo = i; break
    if lo is None:
        lo = results["baseline"]["full_idx"][0]
    return lo, last_idx


def compute_window(nav_arr, lo, hi):
    w_dates = [dates[i] for i in range(lo, hi + 1)]
    w_nav = [nav_arr[i] for i in range(lo, hi + 1)]
    base_hs = None
    w_hs = []
    for i in range(lo, hi + 1):
        v = hs_full[i]
        if v and v > 0:
            if base_hs is None:
                base_hs = v
            w_hs.append(v / base_hs)
        else:
            w_hs.append(None)
    keep = [k for k in range(len(w_nav)) if w_hs[k] is not None]
    w_dates = [w_dates[k] for k in keep]
    w_nav = [w_nav[k] for k in keep]
    w_hs = [w_hs[k] for k in keep]
    n0 = w_nav[0]
    mult = [x / n0 for x in w_nav]
    dd = []
    peak = w_nav[0]
    for x in w_nav:
        peak = max(peak, x)
        dd.append(x / peak - 1.0)
    mdd = min(dd) * 100
    d0 = dt.date.fromisoformat(w_dates[0])
    d1 = dt.date.fromisoformat(w_dates[-1])
    yrs = (d1 - d0).days / 365.25
    cagr = ((w_nav[-1] / n0) ** (1 / yrs) - 1.0) * 100 if yrs > 0 else 0.0
    final_mult = w_nav[-1] / n0
    hs_final = w_hs[-1]
    excess = final_mult / hs_final if hs_final > 0 else 0.0
    years = {}
    for idx, d in enumerate(w_dates):
        years.setdefault(d[:4], []).append(idx)
    rows = []
    prev_end = w_nav[0]
    for y in sorted(years):
        idxs = years[y]
        first, last = idxs[0], idxs[-1]
        base = prev_end if rows else w_nav[first]
        yr_ret = w_nav[last] / base - 1.0
        pk = w_nav[first]; mx = 0.0
        for k in idxs:
            pk = max(pk, w_nav[k])
            mx = min(mx, w_nav[k] / pk - 1.0)
        prev_end = w_nav[last]
        rows.append([y, round(yr_ret * 100, 1), round(mx * 100, 1),
                     round(w_nav[last] / n0, 3)])
    return dict(dates=w_dates, nav=[round(x, 2) for x in w_nav],
                mult=[round(x, 4) for x in mult], dd=[round(x, 4) for x in dd],
                hs_mult=[round(x, 4) for x in w_hs],
                stats=dict(final_mult=round(final_mult, 3), mdd=round(mdd, 1),
                           cagr=round(cagr, 1), hs_mult_final=round(hs_final, 3),
                           excess=round(excess, 3), n_weeks=len(w_dates),
                           start_d=w_dates[0], end_d=w_dates[-1]),
                rows=rows)


WINDOWS = [(3, "3y"), (5, "5y"), (10, "10y")]
windows = {}
for ny, wtag in WINDOWS:
    lo, hi = window_indices(results["baseline"]["start"], ny)
    windows[wtag] = {}
    for key, label, _ in CONFIGS:
        windows[wtag][key] = compute_window(results[key]["nav"], lo, hi)
    b = windows[wtag]["baseline"]
    o = windows[wtag]["optimized"]
    print(f"[{wtag}] {b['stats']['start_d']}~{b['stats']['end_d']} | "
          f"基线 {b['stats']['final_mult']:.2f}x/{b['stats']['mdd']:.1f}% -> "
          f"优化 {o['stats']['final_mult']:.2f}x/{o['stats']['mdd']:.1f}%")

# 全量窗口
windows["full"] = {}
for key, label, _ in CONFIGS:
    windows["full"][key] = compute_window(
        results[key]["nav"], results[key]["start"], results[key]["last_idx"])
b = windows["full"]["baseline"]; o = windows["full"]["optimized"]
print(f"[full] {b['stats']['start_d']}~{b['stats']['end_d']} | "
      f"基线 {b['stats']['final_mult']:.2f}x/{b['stats']['mdd']:.1f}% -> "
      f"优化 {o['stats']['final_mult']:.2f}x/{o['stats']['mdd']:.1f}%")

# 配置元数据
configs_meta = {}
for key, label, cfg in CONFIGS:
    configs_meta[key] = dict(
        label=label,
        core_frac=cfg["core_frac"],
        momentum_lookback=cfg["momentum_lookback"],
        trend_filter=cfg["trend_filter"],
        industry_diversify=cfg["industry_diversify"],
        rel_strength=cfg["rel_strength"],
        death_cross=cfg["death_cross"],
        core_satellite=cfg["core_satellite"],
        score_mode=cfg["score_mode"],
    )

out = dict(
    generated_at=dt.date.today().isoformat(),
    source="东方财富后复权(金标准)",
    last_date=last_date,
    version="v6.14b",
    configs=configs_meta,
    windows=windows,
)

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(BASE)), "docs", "data")
os.makedirs(OUT_DIR, exist_ok=True)
OUT = os.path.join(OUT_DIR, "nav.json")
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

print(f"\n输出: {OUT}  ({os.path.getsize(OUT)} bytes)")
print("完成。docs/curves.html 已通过 fetch 自动读取此文件。")
