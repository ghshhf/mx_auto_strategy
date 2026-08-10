# -*- coding: utf-8 -*-
"""
optimize_cycle_params.py - 周期叠加层参数优化 (v6.21)
=================================================================
目的:
  1. tilt 敏感度扫描: cycle_tilt ∈ {0,0.1,0.15,0.2,0.25,0.3,0.4,0.5},
     对 三引擎 × 3/5/10年窗口 找"最不拖累 / 最优"的力度。
  2. 单周期留一法消融(leave-one-out): 在保守候选 tilt=0.2 下,
     把每个周期权重临时置 0, 看该周期净贡献为正还是负,
     回答"是不是有周期在帮倒忙 / buff 加太多"。

复用 run_cycle_windows.py 的引擎封装口径, 保证与上一轮报告可比。
输出:
  - cycle_opt_tilt.json        扫描 + 消融原始结果
  - docs/cycle_opt_report.md   可读报告
前视防护 / 额度守恒 / 优雅降级 均由 cycles.overlay 内部保证。
"""
import os, sys, json, time, datetime, math

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "us_stocks"))
sys.path.insert(0, os.path.join(ROOT, "crypto_stocks"))

from cycles import overlay as ov, specs as specs_mod

END = {"A股": "2026-08-06", "美股": "2026-07-20", "加密": "2026-07-24"}
WINDOWS = {"3y": 3, "5y": 5, "10y": 10}
TILT_GRID = [0.0, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]
ABLATION_TILT = 0.2  # 保守候选, 与估值 overlay 同量级


def start_for(years, end):
    y, m, d = end.split("-")
    return f"{int(y) - years:04d}-{m}-{d}"


def first_index_ge(dates, sd):
    for i, d in enumerate(dates):
        if d >= sd:
            return i
    return None


def years_between(start, end):
    s = datetime.date.fromisoformat(start)
    e = datetime.date.fromisoformat(end)
    return round((e - s).days / 365.25, 2)


# ----------------------------- 引擎封装(参数化 tilt) -----------------------------
def run_ashare(start, cycle, tilt):
    from ashare_backtest.backtest_engine import run
    kw = dict(offense_mode="momentum", momentum_lookback=26, use_tech=False,
              core_satellite=True, core_frac=0.5, death_cross=True,
              use_core_sub=True, costs=True, start_date=start,
              cycle_overlay=cycle, cycle_tilt=tilt)
    s, nav, st_, plan = run(**kw)
    return s


def run_us(start, cycle, tilt):
    import us_backtest_ai as usmod
    from us_backtest_ai import load_panel, load_us_cfg, run_optimized
    PANEL = os.path.join(ROOT, "us_stocks", "data", "weekly_adjclose_full_ext.csv")
    dates, series = load_panel(PANEL)
    a = first_index_ge(dates, start)
    if a is None:
        return None
    dates_w = dates[a:]
    series_w = {k: v[a:] for k, v in series.items()}
    usmod.series_proxy.clear()
    usmod.series_proxy.update(series_w)
    us_cfg = load_us_cfg()
    opt = us_cfg.get("options_sim") if us_cfg.get("options_sim", {}).get("enabled", False) else None
    _, st = run_optimized(series_w, dates_w, use_ai=False, cfg=None,
                          refresh_weeks=4, theme_div=True, max_per_theme=2,
                          us_cfg=us_cfg, options_sim=opt,
                          cycle_overlay=cycle, cycle_tilt=tilt)
    return st


def run_crypto(start, cycle, tilt):
    import crypto_options_bt as cm
    px = cm._load_default()
    r = cm.run_bt(px, cfg_dict=None, label="V6_cycle", start=start,
                  cycle_overlay=cycle, cycle_tilt=tilt)
    pxs = px[px.index >= start]
    btc = pxs["BTC"].dropna()
    r = dict(r)
    r["btc_multiple"] = float(btc.iloc[-1] / btc.iloc[0]) if len(btc) >= 2 else None
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


def calc_cagr(mult, yrs):
    if not mult or mult <= 0 or yrs <= 0:
        return None
    return mult ** (1.0 / yrs) - 1.0


# ----------------------------- 权重补丁(消融用) -----------------------------
_ORIG_WEIGHTS = {c["id"]: c["weight"] for c in specs_mod.CYCLES}


def drop_cycle(cid):
    for c in specs_mod.CYCLES:
        if c["id"] == cid:
            c["weight"] = 0.0


def restore_weights():
    for c in specs_mod.CYCLES:
        c["weight"] = _ORIG_WEIGHTS[c["id"]]


# ----------------------------- 主线 -----------------------------
print("=" * 92)
print("周期叠加层参数优化: tilt 扫描 + 单周期留一法消融")
print("=" * 92)

sweep = {}        # sweep[eng][wname][tilt] = rec
off_cache = {}    # off_cache[eng][wname] = rec
ablation = {}     # ablation[eng][wname][cycle_id] = mult (drop 后)

for eng in ("A股", "美股", "加密"):
    sweep[eng] = {}
    off_cache[eng] = {}
    ablation[eng] = {}
    for wname, yrs in WINDOWS.items():
        end = END[eng]
        start = start_for(yrs, end)
        if eng == "加密" and start < "2017-08-11":
            start = "2017-08-11"
        yrs_act = years_between(start, end)

        # OFF 基线(跑一次, 各 tilt 共用)
        t0 = time.time()
        try:
            off = norm(eng, RUNNERS[eng](start, False, 0.0))
        except Exception as e:
            off = {"error": f"{type(e).__name__}: {e}"[:200]}
        off_cache[eng][wname] = off
        if off and "mult" in off:
            off["cagr_calc"] = calc_cagr(off["mult"], yrs_act)
        print(f"  {eng:>4} {wname:>3} OFF  倍数 {off.get('mult'):>8.3f}x  "
              f"MDD {off.get('mdd'):>7.2f}%  [{time.time()-t0:.1f}s]")

        # ON 扫描
        sweepp = {}
        for tilt in TILT_GRID:
            t0 = time.time()
            try:
                st = norm(eng, RUNNERS[eng](start, True, tilt))
            except Exception as e:
                st = {"error": f"{type(e).__name__}: {e}"[:200]}
            if st and "mult" in st:
                st["cagr_calc"] = calc_cagr(st["mult"], yrs_act)
                st["ratio"] = st["mult"] / off["mult"] if off and "mult" in off else None
            sweepp[tilt] = st
            dt = time.time() - t0
            if st and "mult" in st:
                print(f"  {eng:>4} {wname:>3} ON t={tilt:<4} 倍数 {st['mult']:>8.3f}x  "
                      f"MDD {st['mdd']:>7.2f}%  ON/OFF {st.get('ratio'):>6.3f}  [{dt:.1f}s]")
            else:
                print(f"  {eng:>4} {wname:>3} ON t={tilt:<4} ERR {st.get('error')}  [{dt:.1f}s]")
        sweep[eng][wname] = {"start": start, "end": end, "actual_years": yrs_act,
                             "off": off, "on": sweepp}

        # 留一法消融(在 ABLATION_TILT 下)
        full = sweepp.get(ABLATION_TILT)
        abl = {}
        for c in specs_mod.CYCLES:
            cid = c["id"]
            drop_cycle(cid)
            t0 = time.time()
            try:
                st = norm(eng, RUNNERS[eng](start, True, ABLATION_TILT))
                m = st.get("mult") if st else None
            except Exception:
                m = None
            restore_weights()
            abl[cid] = m
            print(f"    消融 {eng:>4} {wname:>3} 去[{cid:<12}] -> 倍数 {m if m is not None else 'ERR'}")
        ablation[eng][wname] = abl

# ----------------------------- 找最优 tilt -----------------------------
print("\n" + "=" * 92)
print("各引擎最优 tilt (按 ON/OFF 比率的几何平均最大化)")
print("=" * 92)
opt_tilt = {}
for eng in ("A股", "美股", "加密"):
    best_t, best_score = None, -1e9
    for tilt in TILT_GRID:
        ratios = []
        for wname in WINDOWS:
            r = sweep[eng][wname]["on"].get(tilt, {}).get("ratio")
            if r and r > 0:
                ratios.append(math.log(r))
        if ratios:
            score = sum(ratios) / len(ratios)  # 几何平均的对数
            if score > best_score:
                best_score, best_t = score, tilt
    opt_tilt[eng] = best_t
    print(f"  {eng}: 最优 tilt = {best_t}  (log-几何平均比率 = {best_score:+.4f})")

# ----------------------------- 落盘 -----------------------------
out = {"tilt_grid": TILT_GRID, "ablation_tilt": ABLATION_TILT,
       "sweep": sweep, "off_cache": off_cache, "ablation": ablation,
       "opt_tilt": opt_tilt}
with open(os.path.join(ROOT, "cycle_opt_tilt.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\n已写入 cycle_opt_tilt.json")

# ----------------------------- 报告 -----------------------------
from build_cycle_opt_report import build_opt_report
build_opt_report(out, os.path.join(ROOT, "docs", "cycle_opt_report.md"),
                 os.path.join(ROOT, "cycle_opt_report.html"))
print("已生成 cycle_opt_report.html / docs/cycle_opt_report.md")
