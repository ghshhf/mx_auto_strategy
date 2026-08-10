# -*- coding: utf-8 -*-
"""
run_cycle_windows.py - 三引擎 × 3/5/10年窗口 × 周期叠加层(ON/OFF) 对比回测
=========================================================================
目的: 把 cycles 模块的 12 层 composite_regime 作为统一风险叠加层, 接入
      A股 / 美股 / 加密 三个回测引擎, 在 3年 / 5年 / 10年 滚动窗口上定量评估
      它的"顺风加进攻 / 逆风减进攻"效果。

每个 (引擎, 窗口) 跑两组:
  - OFF: cycle_overlay=False  (引擎原基线, 与历史真值口径一致)
  - ON : cycle_overlay=True, cycle_tilt=0.5 (乘数∈[0.5,1.5], 无隐性杠杆)

输出:
  - cycle_windows_results.json  原始指标
  - docs/cycle_windows_report.md 可读报告(三引擎 × 三窗口对照表 + 解读)
  - cycle_windows_report.html    自包含可视化(表格 + 倍数对比条形图)

免责声明: 周期叠加层仅反映市场观点, 非投资建议。
"""
import os, sys, json, time, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "us_stocks"))
sys.path.insert(0, os.path.join(ROOT, "crypto_stocks"))

# 各引擎数据最新周(窗口终点锚)
END = {"A股": "2026-08-06", "美股": "2026-07-20", "加密": "2026-07-24"}
WINDOWS = {"3y": 3, "5y": 5, "10y": 10}
TILT = 0.5


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


# ----------------------------- 引擎封装 -----------------------------
def run_ashare(start, cycle):
    from ashare_backtest.backtest_engine import run
    kw = dict(offense_mode="momentum", momentum_lookback=26, use_tech=False,
              core_satellite=True, core_frac=0.5, death_cross=True,
              use_core_sub=True, costs=True, start_date=start,
              cycle_overlay=cycle, cycle_tilt=TILT)
    s, nav, st_, plan = run(**kw)
    return s


def run_us(start, cycle):
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
                          cycle_overlay=cycle, cycle_tilt=TILT)
    return st


def run_crypto(start, cycle):
    import crypto_options_bt as cm
    px = cm._load_default()
    r = cm.run_bt(px, cfg_dict=None, label="V6_cycle", start=start,
                  cycle_overlay=cycle, cycle_tilt=TILT)
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
        return dict(mult=st["final_multiple"], cagr=st["cagr"], mdd=st["mdd"],
                    bench=st.get("hs300_multiple"))
    if eng == "美股":
        return dict(mult=st["multiple"], cagr=st["cagr"], mdd=st["mdd"] * 100,
                    bench=st.get("spy_mult"))
    if eng == "加密":
        return dict(mult=st["multiple"], cagr=st["cagr"], mdd=st["mdd"] * 100,
                    bench=st.get("btc_multiple"))


# ----------------------------- 主流程 -----------------------------
def calc_cagr(mult, yrs):
    """统一用 倍数^(1/年数)-1 重算年化, 保证三引擎口径一致(不依赖各引擎自报字段)。"""
    if not mult or mult <= 0 or yrs <= 0:
        return None
    return mult ** (1.0 / yrs) - 1.0


results = {}
print("=" * 90)
print("三引擎 × 3/5/10年窗口 × 周期叠加层(ON/OFF) 回测")
print("=" * 90)

for eng in ("A股", "美股", "加密"):
    results[eng] = {}
    for wname, yrs in WINDOWS.items():
        end = END[eng]
        start = start_for(yrs, end)
        # crypto 10y 数据起点 2017-08-11, 早于起点则夹紧
        if eng == "加密" and start < "2017-08-11":
            start = "2017-08-11"
        row = {"requested": f"{yrs}y", "start": start, "end": end,
               "actual_years": years_between(start, end), "off": None, "on": None}
        for label, cyc in (("off", False), ("on", True)):
            t0 = time.time()
            try:
                st = RUNNERS[eng](start, cyc)
                rec = norm(eng, st)
                if rec is None:
                    rec = {"error": "no data / run failed", "raw": str(st)[:200]}
            except Exception as e:
                rec = {"error": f"{type(e).__name__}: {e}"[:300]}
            if rec and "mult" in rec:
                rec["cagr_calc"] = calc_cagr(rec["mult"], row["actual_years"])
            row[label] = rec
            dt = time.time() - t0
            tag = f"{eng:>4} {wname:>3} {label.upper():>3}"
            if rec and "mult" in rec:
                cg = rec.get("cagr_calc")
                print(f"  {tag}  倍数 {rec['mult']:>8.3f}x  CAGR {(cg*100 if cg is not None else float('nan')):>6.2f}%  "
                      f"MDD {rec['mdd']:>7.2f}%  基准 {rec.get('bench')}  [{dt:.1f}s]")
            else:
                print(f"  {tag}  ERROR {rec.get('error')}  [{dt:.1f}s]")
        results[eng][wname] = row

# ----------------------------- 落盘 JSON -----------------------------
with open(os.path.join(ROOT, "cycle_windows_results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("\n已写入 cycle_windows_results.json")

# ----------------------------- 报告生成 -----------------------------
from build_cycle_report import build_reports
build_reports(results, os.path.join(ROOT, "docs", "cycle_windows_report.md"),
              os.path.join(ROOT, "cycle_windows_report.html"))
