# -*- coding: utf-8 -*-
"""
verify_cycle_weights.py - 验证逐引擎精选权重的最终效果
=====================================================
对三引擎 × 3/5/10年窗口, 跑:
  - OFF: cycle_overlay=False
  - ON : cycle_overlay=True (引擎默认会取 specs.ENGINE_CYCLE_WEIGHTS + ENGINE_TILT)
并报告每窗口 倍数 / CAGR / MDD / 基准, 确认:
  - A股/加密 精选周期带来正增益;
  - 美股 精选集为空 -> ON 应==OFF(中性, 安全)。
"""
import os, sys, json, time, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "us_stocks"))
sys.path.insert(0, os.path.join(ROOT, "crypto_stocks"))
from cycles import specs as SP

END = {"A股": "2026-08-06", "美股": "2026-07-20", "加密": "2026-07-24"}
WINDOWS = {"3y": 3, "5y": 5, "10y": 10}


def start_for(years, end):
    y, m, d = end.split("-")
    return f"{int(y) - years:04d}-{m}-{d}"


def years_between(start, end):
    s = datetime.date.fromisoformat(start); e = datetime.date.fromisoformat(end)
    return round((e - s).days / 365.25, 2)


def calc_cagr(mult, yrs):
    return mult ** (1.0 / yrs) - 1.0 if (mult and mult > 0 and yrs > 0) else None


def run_ashare(start, cycle):
    from ashare_backtest.backtest_engine import run
    kw = dict(offense_mode="momentum", momentum_lookback=26, use_tech=False,
              core_satellite=True, core_frac=0.5, death_cross=True,
              use_core_sub=True, costs=True, start_date=start, cycle_overlay=cycle)
    s, nav, st_, plan = run(**kw)
    return s


def run_us(start, cycle):
    import us_backtest_ai as usmod
    from us_backtest_ai import load_panel, load_us_cfg, run_optimized
    dates, series = load_panel(os.path.join(ROOT, "us_stocks", "data", "weekly_adjclose_full_ext.csv"))
    a = next(i for i, d in enumerate(dates) if d >= start)
    sw = {k: v[a:] for k, v in series.items()}; dw = dates[a:]
    usmod.series_proxy.clear(); usmod.series_proxy.update(sw)
    us_cfg = load_us_cfg()
    opt = us_cfg.get("options_sim") if us_cfg.get("options_sim", {}).get("enabled", False) else None
    _, st = run_optimized(sw, dw, use_ai=False, cfg=None, refresh_weeks=4, theme_div=True,
                          max_per_theme=2, us_cfg=us_cfg, options_sim=opt, cycle_overlay=cycle)
    return st


def run_crypto(start, cycle):
    import crypto_options_bt as cm
    px = cm._load_default()
    r = cm.run_bt(px, cfg_dict=None, label="V6_vfy", start=start, cycle_overlay=cycle)
    return r


RUNNERS = {"A股": run_ashare, "美股": run_us, "加密": run_crypto}


def norm(eng, st):
    if not st or "error" in st:
        return None
    if eng == "A股":
        return dict(mult=st["final_multiple"], mdd=st["mdd"], bench=st.get("hs300_multiple"))
    if eng == "美股":
        return dict(mult=st["multiple"], mdd=st["mdd"] * 100, bench=st.get("spy_mult"))
    if eng == "加密":
        return dict(mult=st["multiple"], mdd=st["mdd"] * 100, bench=st.get("btc_multiple"))


print("=" * 110)
print("逐引擎精选权重 ON vs OFF 验证 (ON 用 specs.ENGINE_CYCLE_WEIGHTS + ENGINE_TILT 默认)")
print("=" * 110)
out = {}
for eng in ("A股", "美股", "加密"):
    key = {"A股": "ashare", "美股": "us", "加密": "crypto"}[eng]
    print(f"\n###### {eng} (key={key}) 精选权重 = {SP.ENGINE_CYCLE_WEIGHTS.get(key)}  tilt={SP.ENGINE_TILT[key]} ######")
    out[eng] = {}
    for wname, yrs in WINDOWS.items():
        start = start_for(yrs, END[eng])
        if eng == "加密" and start < "2017-08-11":
            start = "2017-08-11"
        off = norm(eng, RUNNERS[eng](start, False))
        on = norm(eng, RUNNERS[eng](start, True))
        ay = years_between(start, END[eng])
        ro = calc_cagr(off["mult"], ay); rn = calc_cagr(on["mult"], ay)
        ratio = on["mult"] / off["mult"] if off and on else None
        out[eng][wname] = dict(start=start, end=END[eng], actual_years=ay,
                               off=off, on=on, ratio=(round(ratio, 4) if ratio else None))
        print(f"  {wname} OFF 倍数={off['mult']:.3f} CAGR={ro*100:.1f}% MDD={off['mdd']:.1f}% | "
              f"ON 倍数={on['mult']:.3f} CAGR={rn*100:.1f}% MDD={on['mdd']:.1f}% | "
              f"ratio={ratio:.4f} 基准={off.get('bench')}")

with open(os.path.join(ROOT, "cycle_weights_verify.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\n已写入 cycle_weights_verify.json")
