# -*- coding: utf-8 -*-
"""
QA-03 修复前 vs 修复后 三模式 10y/5y/3y 指标对照 (QA 独立实现, 不依赖 run_windows_v2)
=====================================================================================
- 三模式: fused(A+港) / pure_a(纯A) / pure_hk(纯港)
- 两套防火墙参数:
    before = 旧逻辑 (MAX_WEEKLY_JUMP=1.6, 无次新股冷却期)
    after  = 当前代码 (MAX_WEEKLY_JUMP=0.8, IPO_SEASON_WEEKS=13)
- 每种组合跑 baseline(cf=0.6) 与 optimized(cf=0.5+trend_filter) 两配置
- 窗口/指标算法按 run_windows_v2.py 同口径独立重写 (交叉校验其数字)
- 全程 try/finally 保护 strategy_config.json, 结束必还原
"""
import os
import sys
import json
import shutil
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(BT))
sys.path.insert(0, BT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import backtest_engine as E

CFG = os.path.join(ROOT, "strategy_config.json")
SAFE = os.path.join(HERE, "strategy_config.QABACKUP.json")
PANEL = os.path.join(E.DATA, "ashare_panel_close_em.csv")

# run_three_ways.py 里的 15 只扩展港股 (fused/pure_hk 需要与其一致才可比)
NEW_HK = [("00939", "建设银行", "港股金融"), ("01299", "友邦保险", "港股金融"),
          ("00005", "汇丰控股", "港股金融"), ("02318", "中国平安", "港股金融"),
          ("09988", "阿里巴巴", "港股科技"), ("09618", "京东集团", "港股科技"),
          ("01024", "快手", "港股科技"), ("09888", "百度集团", "港股科技"),
          ("02020", "安踏体育", "港股消费"), ("00762", "中国联通", "港股科技"),
          ("02388", "中银香港", "港股金融"), ("01109", "华润置地", "港股消费"),
          ("01876", "百威亚太", "港股消费"), ("00175", "吉利汽车", "港股汽车"),
          ("00291", "华润啤酒", "港股消费")]

COMMON = dict(offense_mode="momentum", momentum_lookback=26, use_tech=True,
              core_satellite=True, death_cross=True, grid=False,
              score_mode="plain", start_capital=1_000_000,
              panel_path=PANEL, use_core_sub=True)
CONFIGS = [("baseline", {**COMMON, "core_frac": 0.6}),
           ("optimized", {**COMMON, "core_frac": 0.5, "trend_filter": True})]

FIREWALLS = {
    "before": dict(MAX_WEEKLY_JUMP=1.6, IPO_SEASON_WEEKS=-10 ** 9, MIN_VALID_PRICE=0.5),
    "after": dict(MAX_WEEKLY_JUMP=0.8, IPO_SEASON_WEEKS=13, MIN_VALID_PRICE=0.5),
}

dates, _codes, _series = E.load_panel(PANEL)


def metrics(nav, start, n_years, last_idx):
    """按 run_windows_v2 同口径: 从 last_date 回推 n 年取窗口, 起点归一。"""
    ld = dt.date.fromisoformat(dates[last_idx])
    target = ld.replace(year=ld.year - n_years)
    t0 = dt.date.fromisoformat(dates[start])
    if target < t0:
        target = t0
    tstr = target.isoformat()
    lo = next((i for i in range(start, last_idx + 1)
               if nav[i] and nav[i] > 0 and dates[i] >= tstr), start)
    w = [nav[i] for i in range(lo, last_idx + 1) if nav[i] and nav[i] > 0]
    n0 = w[0]
    peak, mdd = w[0], 0.0
    for x in w:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1.0)
    d0 = dt.date.fromisoformat(dates[lo])
    yrs = (ld - d0).days / 365.25
    mult = w[-1] / n0
    cagr = (mult ** (1 / yrs) - 1) * 100 if yrs > 0 else 0.0
    return {"mult": mult, "mdd": mdd * 100, "cagr": cagr,
            "start": dates[lo], "end": dates[last_idx]}


def build_pools():
    base = json.load(open(SAFE, encoding="utf-8"))
    cp = list(base["auto_select"]["candidate_pool"])
    have = {p["code"] for p in cp}
    for code, name, ind in NEW_HK:
        if code not in have:
            cp.append({"code": code, "name": name, "industry": ind,
                       "tech": ind == "港股科技", "market": "HK",
                       "_theme": "港股通, 扩展池"})
    hk = [p for p in cp if p.get("market") == "HK"]
    a = [p for p in cp if p.get("market") != "HK"]
    return base, {"fused": cp, "pure_a": a, "pure_hk": hk}


def main():
    base_cfg, pools = build_pools()
    print(f"[pool] fused={len(pools['fused'])} pure_a={len(pools['pure_a'])} "
          f"pure_hk={len(pools['pure_hk'])}")
    results = {}
    for mode in ("fused", "pure_a", "pure_hk"):
        cfg = json.loads(json.dumps(base_cfg))
        cfg["auto_select"]["candidate_pool"] = pools[mode]
        json.dump(cfg, open(CFG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        for fw, params in FIREWALLS.items():
            for k, v in params.items():
                setattr(E, k, v)
            E._FIRST_LISTED_CACHE.clear()
            for cname, kw in CONFIGS:
                stats, nav, start, _ = E.run(**kw)
                li = max(i for i in range(start, len(dates)) if nav[i] and nav[i] > 0)
                for ny in (3, 5, 10):
                    results[(mode, fw, cname, ny)] = metrics(nav, start, ny, li)
                results[(mode, fw, cname, "full")] = {
                    "mult": stats["final_multiple"], "mdd": stats["mdd"],
                    "cagr": stats["cagr"], "start": stats["start"], "end": stats["end"]}
            print(f"  [{mode}/{fw}] done")
    return results


ok = False
try:
    R = main()
    ok = True
finally:
    shutil.copyfile(SAFE, CFG)
    print("[safety] strategy_config.json 已从 QA 备份还原")

print("\n" + "=" * 104)
print("修复前 vs 修复后  ·  优化配置(cf=0.5 + trend_filter)  ·  三模式 × 三窗口")
print("=" * 104)
print(f"{'模式':<10}{'窗口':<7}{'倍数(前)':>11}{'倍数(后)':>11}{'Δ倍数':>10}"
      f"{'MDD(前)':>11}{'MDD(后)':>11}{'ΔMDD':>9}{'CAGR(前)':>11}{'CAGR(后)':>11}")
print("-" * 104)
for mode in ("pure_a", "fused", "pure_hk"):
    for ny in (3, 5, 10, "full"):
        b = R[(mode, "before", "optimized", ny)]
        a = R[(mode, "after", "optimized", ny)]
        tag = f"{ny}y" if ny != "full" else "full"
        print(f"{mode:<10}{tag:<7}{b['mult']:>10.2f}x{a['mult']:>10.2f}x"
              f"{a['mult']-b['mult']:>+9.2f}x{b['mdd']:>10.2f}%{a['mdd']:>10.2f}%"
              f"{a['mdd']-b['mdd']:>+8.2f}{b['cagr']:>10.2f}%{a['cagr']:>10.2f}%")
    print("-" * 104)

print("\n基线配置(cf=0.6, 无 trend_filter) — 10y")
print(f"{'模式':<10}{'倍数(前)':>11}{'倍数(后)':>11}{'MDD(前)':>11}{'MDD(后)':>11}")
print("-" * 56)
for mode in ("pure_a", "fused", "pure_hk"):
    b = R[(mode, "before", "baseline", 10)]
    a = R[(mode, "after", "baseline", 10)]
    print(f"{mode:<10}{b['mult']:>10.2f}x{a['mult']:>10.2f}x{b['mdd']:>10.2f}%{a['mdd']:>10.2f}%")

w = R[("pure_a", "after", "optimized", 10)]
print(f"\n10y 窗口: {w['start']} ~ {w['end']}")

json.dump({f"{k[0]}|{k[1]}|{k[2]}|{k[3]}": v for k, v in R.items()},
          open(os.path.join(HERE, "qa_03_result.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("[done] -> _qa/qa_03_result.json")
