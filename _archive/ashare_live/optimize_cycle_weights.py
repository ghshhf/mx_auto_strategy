# -*- coding: utf-8 -*-
"""
optimize_cycle_weights.py - 逐周期有效性 + 逐引擎精选权重实验
================================================================
目的(回应"12 周期不该一刀切全开/全关, 应该按资产类别分别筛选、按权重作用"):

  1. 单周期有效性: 对每个引擎(A股/美股/加密) × 每个窗口(3y/5y/10y),
     把 12 个周期**单独**接入(composite_regime 只用该周期, 权重=1),
     固定 tilt=0.3, 看 ON/OFF 倍数比。直接回答"哪个周期对哪个引擎真正有用"。

  2. 逐引擎精选: 按三窗口几何均值(ratio)筛选"有用周期"(几何均值>1.0),
     并给有用周期按其有效性强弱赋相对权重(权重越高 -> 在合成 regime 中越主导)。

  3. tilt 扫描: 在精选子集上扫 tilt∈{0,0.1,0.15,0.2,0.3,0.4,0.5},
     选几何均值倍数比最高且 MDD 不恶化的力度, 作为该引擎 ENGINE_TILT 候选。

输出:
  - cycle_weights_experiment.json  (单周期 ratio 矩阵 + 精选子集 + tilt 扫描)
  - 控制台打印逐引擎"有用周期排行榜"与推荐权重/tilt
"""
import os, sys, json, time, datetime, math

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "us_stocks"))
sys.path.insert(0, os.path.join(ROOT, "crypto_stocks"))

from cycles import specs as SP

END = {"A股": "2026-08-06", "美股": "2026-07-20", "加密": "2026-07-24"}
WINDOWS = {"3y": 3, "5y": 5, "10y": 10}
SINGLE_TILT = 0.3          # 单周期测试固定力度
TILT_SCAN = [0.0, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5]
CYCLE_IDS = [c["id"] for c in SP.CYCLES]
CYCLE_NAME = {c["id"]: c["name"] for c in SP.CYCLES}

KEY = {"A股": "ashare", "美股": "us", "加密": "crypto"}


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


def calc_cagr(mult, yrs):
    if not mult or mult <= 0 or yrs <= 0:
        return None
    return mult ** (1.0 / yrs) - 1.0


# ----------------------------- 引擎封装 -----------------------------
def run_ashare(start, cycle, tilt, weights):
    from ashare_backtest.backtest_engine import run
    kw = dict(offense_mode="momentum", momentum_lookback=26, use_tech=False,
              core_satellite=True, core_frac=0.5, death_cross=True,
              use_core_sub=True, costs=True, start_date=start,
              cycle_overlay=cycle, cycle_tilt=tilt)
    if weights is not None:
        kw["cycle_weights"] = weights
    s, nav, st_, plan = run(**kw)
    return s


def run_us(start, cycle, tilt, weights):
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
                          cycle_overlay=cycle, cycle_tilt=tilt,
                          cycle_weights=(weights if weights is not None else None))
    return st


def run_crypto(start, cycle, tilt, weights):
    import crypto_options_bt as cm
    px = cm._load_default()
    pxs = px[px.index >= start]
    kw = dict(px=px, cfg_dict=None, label="V6_wsel", start=start,
              cycle_overlay=cycle, cycle_tilt=tilt)
    if weights is not None:
        kw["cycle_weights"] = weights
    r = cm.run_bt(**kw)
    btc = pxs["BTC"].dropna()
    r = dict(r)
    r["btc_multiple"] = float(btc.iloc[-1] / btc.iloc[0]) if len(btc) >= 2 else None
    return r


RUNNERS = {"A股": run_ashare, "美股": run_us, "加密": run_crypto}


def norm(eng, st):
    if not st or "error" in st:
        return None
    if eng == "A股":
        return dict(mult=st["final_multiple"], cagr=st["cagr"], mdd=st["mdd"],
                    bench=st.get("hs300_multiple"))
    if eng == "美股":
        return dict(mult=st["multiple"], cagr=st["cagr"], mdd=st["mdd"] * 100,
                    bench=st.get("spy_mult"))
    if eng == "加密":
        return dict(mult=st["multiple"], cagr=st["cagr"], mdd=st["mdd"] * 100,
                    bench=st.get("btc_multiple"))


# ----------------------------- 主流程 -----------------------------
print("=" * 90)
print("逐周期有效性实验: 单周期 ON/OFF 倍数比 (tilt=%.2f)" % SINGLE_TILT)
print("=" * 90)

raw = {}          # raw[eng][wname] = {off, single:{cid:{ratio,mult,mdd}}}
for eng in ("A股", "美股", "加密"):
    raw[eng] = {}
    for wname, yrs in WINDOWS.items():
        end = END[eng]
        start = start_for(yrs, end)
        if eng == "加密" and start < "2017-08-11":
            start = "2017-08-11"
        t0 = time.time()
        off = RUNNERS[eng](start, False, 0.0, None)
        off_rec = norm(eng, off)
        row = {"start": start, "end": end, "actual_years": years_between(start, end),
               "off": off_rec, "single": {}}
        for cid in CYCLE_IDS:
            t1 = time.time()
            on = RUNNERS[eng](start, True, SINGLE_TILT, {cid: 1.0})
            onr = norm(eng, on)
            if onr and off_rec:
                ratio = onr["mult"] / off_rec["mult"]
                row["single"][cid] = {"ratio": round(ratio, 4),
                                      "mult_on": round(onr["mult"], 3),
                                      "mdd_on": round(onr["mdd"], 2),
                                      "mdd_off": round(off_rec["mdd"], 2)}
            else:
                row["single"][cid] = {"ratio": None, "error": "no data"}
            print(f"  {eng:>4} {wname} [{cid:<12}] ratio={row['single'][cid].get('ratio')} "
                  f"[{time.time()-t1:.1f}s]")
        raw[eng][wname] = row
        print(f"  >> {eng} {wname} OFF mult={off_rec['mult']:.3f} "
              f"({time.time()-t0:.1f}s total)\n")

# ----------------- 逐引擎精选: 几何均值 ratio -----------------
print("=" * 90)
print("逐引擎精选周期 (三窗口几何均值 ratio>1.0 入选, 权重∝有效性强弱)")
print("=" * 90)

selection = {}    # selection[eng] = {cid: weight}
GEO = {}           # GEO[eng] = {cid: geo_ratio}  (三窗口几何均值, 用于报告)
for eng in ("A股", "美股", "加密"):
    geo = {}
    for cid in CYCLE_IDS:
        rs = []
        for wname in WINDOWS:
            r = raw[eng][wname]["single"].get(cid, {}).get("ratio")
            if r and r > 0:
                rs.append(r)
        geo[cid] = (math.prod(rs) ** (1.0 / len(rs))) if rs else 0.0
    # 入选: 几何均值 > 1.0
    kept = {c: g for c, g in geo.items() if g > 1.0}
    # 权重: 按有效性强弱(几何均值)赋值, 下限 0.5 避免过弱; 归一化到 sum=1 便于阅读
    if kept:
        raw_w = {c: max(0.5, g) for c, g in kept.items()}
        s = sum(raw_w.values())
        weights = {c: round(v / s, 3) for c, v in raw_w.items()}
    else:
        weights = {}
    selection[eng] = weights
    print(f"\n  === {eng} (key={KEY[eng]}) ===")
    ranked = sorted(geo.items(), key=lambda kv: kv[1], reverse=True)
    for cid, g in ranked:
        tag = "✓入选" if cid in weights else "✗剔除"
        print(f"    {cid:<12} geo_ratio={g:+.4f}  {tag}")
    if weights:
        print("    推荐权重:", {c: weights[c] for c in weights})
    else:
        print("    无周期几何均值>1.0 -> 精选集为空(默认回退全周期)")
    GEO[eng] = geo

# ----------------- 在精选子集上扫 tilt -----------------
print("\n" + "=" * 90)
print("精选子集 tilt 扫描 (各引擎 ON/OFF 几何倍数比 + MDD)")
print("=" * 90)

tilt_scan_result = {}
for eng in ("A股", "美股", "加密"):
    w_dict = selection[eng]
    tilt_scan_result[eng] = {}
    print(f"\n  === {eng} 精选={list(w_dict.keys()) or '全周期'} ===")
    for tilt in TILT_SCAN:
        ratios, mdds_on, mdds_off = [], [], []
        for wname, yrs in WINDOWS.items():
            end = END[eng]
            start = start_for(yrs, end)
            if eng == "加密" and start < "2017-08-11":
                start = "2017-08-11"
            off = RUNNERS[eng](start, False, 0.0, None)
            offr = norm(eng, off)
            on = RUNNERS[eng](start, True, tilt, (w_dict if w_dict else None))
            onr = norm(eng, on)
            if onr and offr:
                ratios.append(onr["mult"] / offr["mult"])
                mdds_on.append(onr["mdd"]); mdds_off.append(offr["mdd"])
        geo_r = (math.prod(ratios) ** (1.0 / len(ratios))) if ratios else 0.0
        worst_mdd_on = max(mdds_on) if mdds_on else None
        worst_mdd_off = max(mdds_off) if mdds_off else None
        tilt_scan_result[eng][str(tilt)] = {
            "geo_ratio": round(geo_r, 4),
            "worst_mdd_on": round(worst_mdd_on, 2) if worst_mdd_on is not None else None,
            "worst_mdd_off": round(worst_mdd_off, 2) if worst_mdd_off is not None else None,
        }
        print(f"    tilt={tilt:<4} geo_ratio={geo_r:+.4f}  worstMDD_on={worst_mdd_on}  off={worst_mdd_off}")

# ----------------- 选最优 tilt (几何倍数比最高, MDD 不比 off 差太多) -----------------
best_tilt = {}
for eng in ("A股", "美股", "加密"):
    best, best_score = 0.0, -1e9
    for tilt in TILT_SCAN:
        r = tilt_scan_result[eng][str(tilt)]
        # 评分: 几何倍数比为主, MDD 恶化(更负)按比例惩罚
        mdd_penalty = 0.0
        if r["worst_mdd_on"] is not None and r["worst_mdd_off"] is not None:
            mdd_penalty = max(0.0, (r["worst_mdd_off"] - r["worst_mdd_on"])) * 0.02
        score = r["geo_ratio"] - mdd_penalty
        if score > best_score:
            best_score, best = score, tilt
    best_tilt[eng] = best

print("\n" + "=" * 90)
print("推荐结果汇总")
print("=" * 90)
for eng in ("A股", "美股", "加密"):
    print(f"  {eng:<4} key={KEY[eng]}")
    print(f"     精选周期: {selection[eng] or '（空 -> 回退全周期等权）'}")
    print(f"     推荐 tilt: {best_tilt[eng]}")

out = {
    "single_tilt": SINGLE_TILT,
    "raw": raw,
    "geo_ratio": {eng: {c: round(g, 4) for c, g in GEO[eng].items()}
               for eng in ("A股", "美股", "加密")},
    "selection": selection,
    "tilt_scan": tilt_scan_result,
    "best_tilt": best_tilt,
    "engine_key": KEY,
}
with open(os.path.join(ROOT, "cycle_weights_experiment.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\n已写入 cycle_weights_experiment.json")
