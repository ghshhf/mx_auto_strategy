# -*- coding: utf-8 -*-
"""
export_nav_us.py — 美股 NAV 导出 docs/data/nav_us.json (数据层, 复用 A股 export_nav.py 窗口逻辑)

产出两条序列(均取自 run_optimized, 确定性, 无 LLM):
  - optimized   : 期权层未启用(us_options.py 空壳 + options_sim=None) -> 真值 22.48x (无杠杆, 稳健)
  - options_sim : 期权模拟层启用(BS LEAPS, call_vol=0.26)              -> 约 100x (假设依赖, 非稳健真值)

数据为渲染分离: docs/index.html 通过 fetch 读取本文件, 页面逻辑不变。
"""
import os, sys, json, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import us_backtest_ai as U

PANEL = os.path.join(HERE, "data", "weekly_adjclose_full_ext.csv")
if not os.path.exists(PANEL):
    print(f"[错误] 找不到面板 {PANEL}"); sys.exit(1)

dates, series = U.load_panel(PANEL)
us_cfg = U.load_us_cfg()
n = len(dates)


def run_one(options_sim):
    hist, st = U.run_optimized(series, dates, use_ai=False, cfg=None,
                               refresh_weeks=4, theme_div=True, max_per_theme=2,
                               us_cfg=us_cfg, options_sim=options_sim)
    return hist, st


opt_hist, opt_st = run_one(None)
sim_cfg = us_cfg.get("options_sim") or {}
sim_hist, sim_st = run_one(sim_cfg if sim_cfg.get("enabled") else None)


def first_valid(hist):
    for i in range(n):
        if hist[i] is not None and hist[i] > 0:
            return i
    return 0


def last_valid(hist):
    for i in range(n - 1, -1, -1):
        if hist[i] is not None and hist[i] > 0:
            return i
    return n - 1


def compute_window(hist, lo, hi):
    w_dates = [dates[i] for i in range(lo, hi + 1)]
    w_nav = [hist[i] for i in range(lo, hi + 1)]
    keep = [k for k in range(len(w_nav)) if w_nav[k] is not None and w_nav[k] > 0]
    w_dates = [w_dates[k] for k in keep]
    w_nav = [w_nav[k] for k in keep]
    n0 = w_nav[0]
    mult = [x / n0 for x in w_nav]
    peak = w_nav[0]
    dd = []
    for x in w_nav:
        peak = max(peak, x)
        dd.append(x / peak - 1.0)
    mdd = min(dd) * 100
    d0 = dt.date.fromisoformat(w_dates[0])
    d1 = dt.date.fromisoformat(w_dates[-1])
    yrs = (d1 - d0).days / 365.25
    cagr = ((w_nav[-1] / n0) ** (1 / yrs) - 1.0) * 100 if yrs > 0 else 0.0
    return dict(dates=w_dates,
                mult=[round(x, 4) for x in mult],
                dd=[round(x, 4) for x in dd],
                stats=dict(final_mult=round(w_nav[-1] / n0, 3), mdd=round(mdd, 1),
                           cagr=round(cagr, 1), n_weeks=len(w_dates),
                           start_d=w_dates[0], end_d=w_dates[-1]))


def windows_for(hist):
    s = first_valid(hist)
    last = last_valid(hist)
    ld = dt.date.fromisoformat(dates[last])

    def lo_for(ny):
        target = ld.replace(year=ld.year - ny)
        t0 = dt.date.fromisoformat(dates[s])
        if target < t0:
            target = t0
        tstr = target.isoformat()
        for i in range(s, last + 1):
            if dates[i] >= tstr:
                return i
        return s

    out = {}
    for ny, tag in [(None, "full"), (10, "10y"), (5, "5y"), (3, "3y")]:
        lo = s if ny is None else lo_for(ny)
        out[tag] = compute_window(hist, lo, last)
    return out


out = dict(
    generated_at=dt.date.today().isoformat(),
    source="美股真实面板(155列, westock-data)",
    last_date=dates[last_valid(opt_hist)],
    windows={
        "optimized": windows_for(opt_hist),
        "options_sim": windows_for(sim_hist),
    },
    truth=dict(
        no_options=dict(final_mult=round(opt_st["multiple"], 3),
                        mdd=round(opt_st["mdd"] * 100, 1),
                        cagr=round(opt_st["cagr"], 1)),
        options_sim=dict(final_mult=round(sim_st["multiple"], 3),
                         mdd=round(sim_st["mdd"] * 100, 1),
                         cagr=round(sim_st["cagr"], 1)),
        note=("options_sim = BS 模型 LEAPS 模拟(假设依赖): call_vol=0.26 锚定市场->约100x; "
              "保守 flat 4.5%->31.7x; IV ±1pp 摆动 93x~131x。非实盘稳健真值，仅供对照。"),
    ),
)

OUT_DIR = os.path.join(os.path.dirname(HERE), "docs", "data")
os.makedirs(OUT_DIR, exist_ok=True)
OUT = os.path.join(OUT_DIR, "nav_us.json")
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

print(f"optimized(无期权):   {opt_st['multiple']:.2f}x | MDD {opt_st['mdd']*100:.1f}% | CAGR {opt_st['cagr']:.1f}%")
print(f"options_sim(期权模拟): {sim_st['multiple']:.2f}x | MDD {sim_st['mdd']*100:.1f}% | CAGR {sim_st['cagr']:.1f}%")
print(f"输出: {OUT} ({os.path.getsize(OUT)} bytes)")
