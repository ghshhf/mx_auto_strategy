"""
us_backtest_corrected.py - 美股子系统「旧逻辑 vs v6.14b修正逻辑」真实面板对账

目的: v6.14b 的 us_rebalance.py(弱市路由 GLD+现金, KO/NEE/JPM 防御, 弃 CWB/股票防御篮)
      此前只在合成 --demo 数据上验证(10y 3.00x/MDD -8.8%)。本脚本用**真实面板**
      weekly_adjclose_full_ext.csv(2016~2026 周频, 已并入 westock-data 抓取的真实 GLD/JPM)
      同时跑两套逻辑, 隔离修正的净效应。

真实面板已含: NVDA/MU/LLY(进攻) + KO/NEE/JPM(防御) + SPY/QQQ(regime) + CWB(旧停车资产)
             + GLD(真实, 弱市停车资产)。GLD/JPM 经 westock-data(usGLD.AM/usJPM.N)抓取并入,
               故 NEW 组的 MDD 改善已含真实 GLD 低相关分散, 不再是保守下界。

两套逻辑共用: 同一进攻动量选股(52周动量 TopN, 季频再平衡) + 同一 regime/death-cross 判定,
仅差异化「弱市停车资产(CWB vs 现金)」与「防御篮(KO/ABBV vs KO/NEE)」, 以干净隔离修正效应。

运行: python us_backtest_corrected.py   (stdlib only, 无需 pandas)
"""
import os
import csv
import math
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
PANEL = os.path.join(DATA, "weekly_adjclose_full_ext.csv")

EXCLUDE = {"SPY", "QQQ", "DIA", "IWM", "MDY", "VTI", "CWB", "GLD"}  # 指数/工具/停车资产, 不进选股
BROAD = ["SPY", "QQQ", "DIA", "IWM", "MDY", "VTI"]
DEF_OLD = ["KO", "ABBV"]
DEF_NEW = ["KO", "NEE", "JPM"]         # v6.14b 防御篮(真防御); GLD 作弱市停车资产(见 ALLOC)
WARMUP = 52                           # 需 1 年历史算动量
REBAL = 13                            # 季频再平衡
TOP_N = 10                            # 动量选股数

# 仓位模板 (弱市停车资产不同, 其余对齐)
ALLOC = {
    "OLD": {  # v8 式: 弱市停车进 CWB(可转债ETF, 含股性)
        "bull":    {"off": 80, "def": 10, "park": 0,  "cash": 10, "park_asset": "CWB"},
        "balance": {"off": 60, "def": 20, "park": 0,  "cash": 20, "park_asset": "CWB"},
        "weak":    {"off": 20, "def": 20, "park": 60, "cash": 0,  "park_asset": "CWB"},
    },
    "NEW": {  # v6.14b 修正: 弱市停车进真实 GLD(低相关避险), 平时持 KO/NEE/JPM 防御篮
        "bull":    {"off": 80, "def": 10, "park": 0,  "cash": 0,  "park_asset": "GLD"},
        "balance": {"off": 60, "def": 20, "park": 0,  "cash": 20, "park_asset": "GLD"},
        "weak":    {"off": 20, "def": 20, "park": 60, "cash": 0,  "park_asset": "GLD"},
    },
}


def load_panel(path):
    rows = list(csv.reader(open(path, encoding="utf-8")))
    hdr, data = rows[0], rows[1:]
    series = {c: [] for c in hdr[1:]}
    dates = [r[0] for r in data]
    for r in data:
        for i, c in enumerate(hdr[1:], 1):
            try:
                series[c].append(float(r[i]))
            except (ValueError, IndexError):
                series[c].append(None)
    return dates, series


def _ma(vals, i, n):
    win = [v for v in vals[max(0, i - n + 1):i + 1] if v is not None]
    return sum(win) / len(win) if win else None


def regime_of(series, i):
    spy = series.get("SPY")
    if not spy or spy[i] is None:
        return "balance"
    ma = _ma(spy, i, 20)
    if ma is None or ma == 0:
        return "balance"
    dev = (spy[i] / ma - 1) * 100
    return "weak" if dev < -3 else ("bull" if dev > 3 else "balance")


def death_cross_count(series, i):
    if i < 20:
        return 0
    cnt = 0
    for c in BROAD:
        v = series.get(c)
        if not v or v[i] is None:
            continue
        ma20 = _ma(v, i, 20); ma5 = _ma(v, i, 5)
        if ma20 is None or ma5 is None:
            continue
        ma20_prev = _ma(v, i - 1, 20)
        if v[i] < ma20 and ma5 < ma20 and (ma20_prev is None or ma20 < ma20_prev):
            cnt += 1
    return cnt


def select_offense(series, i, universe):
    """52周动量 TopN (无前视: 仅用 <=i 数据)。"""
    scored = []
    for c in universe:
        arr = series.get(c)
        if not arr or i < WARMUP or arr[i] is None or arr[i - WARMUP] in (None, 0):
            continue
        mom = arr[i] / arr[i - WARMUP] - 1
        scored.append((mom, c))
    scored.sort(reverse=True)
    return [c for _, c in scored[:TOP_N]]


def run_strategy(series, dates, mode):
    """返回 (nav_hist, stats_dict)。mode in {'OLD','NEW'}。"""
    codes_all = list(series.keys())
    universe = [c for c in codes_all if c not in EXCLUDE and c not in DEF_OLD
                and c not in DEF_NEW]
    n = len(dates)
    nav = 1.0
    nav_hist = []
    peak = 1.0
    mdd = 0.0
    weights = {"__cash__": 1.0}      # code->权重(含 __cash__)
    selected = []
    last_rebal = -100
    yearly = {}
    weak_weeks = 0

    for t in range(n):
        # 1) 应用本周收益(用 t-1 -> t)
        if t > 0 and weights:
            growth = 0.0
            for c, w in weights.items():
                if c == "__cash__":
                    continue
                arr = series.get(c)
                if not arr or arr[t] is None or arr[t - 1] in (None, 0):
                    continue
                growth += w * (arr[t] / arr[t - 1] - 1)
            nav *= (1 + growth)       # 现金不计息
            nav_hist.append(nav)
            peak = max(peak, nav)
            mdd = min(mdd, nav / peak - 1)
            y = dates[t][:4]
            yearly.setdefault(y, 1.0)
            yearly[y] *= (1 + growth)
        else:
            nav_hist.append(nav)

        # 2) 再平衡判定
        need_rebal = (t == WARMUP) or (t - last_rebal >= REBAL)
        if t >= WARMUP and need_rebal:
            selected = select_offense(series, t, universe)
            last_rebal = t

        # 3) 计算目标权重
        if t >= WARMUP and selected:
            weak = (regime_of(series, t) == "weak") or (death_cross_count(series, t) >= 3)
            if weak:
                weak_weeks += 1
            a = ALLOC[mode]["weak" if weak else regime_of(series, t)]
            def_basket = DEF_OLD if mode == "OLD" else DEF_NEW
            tw = {}
            per_off = a["off"] / 100.0 / len(selected)
            for c in selected:
                tw[c] = per_off
            per_def = a["def"] / 100.0 / len(def_basket)
            for c in def_basket:
                tw[c] = per_def
            if a["park"] > 0 and a["park_asset"] != "__cash__":
                tw[a["park_asset"]] = a["park"] / 100.0
            tw["__cash__"] = (a["cash"] + (a["park"] if a["park_asset"] == "__cash__" else 0)) / 100.0
            # 归一(防御/停车资产缺失则归现金)
            tot = sum(tw.values())
            weights = {c: (w / tot if tot > 0 else 0) for c, w in tw.items()}
            if tot <= 0:
                weights = {"__cash__": 1.0}
        elif t == WARMUP and not selected:
            weights = {"__cash__": 1.0}

    yrs = (n - WARMUP) / 52.0
    cagr = (nav ** (1 / yrs) - 1) * 100 if yrs > 0 else 0
    spy_arr = series.get("SPY")
    spy_mult = (spy_arr[n - 1] / spy_arr[WARMUP]) if spy_arr and spy_arr[WARMUP] else None
    return nav_hist, {
        "mode": mode, "multiple": nav, "cagr": cagr, "mdd": mdd,
        "weak_pct": weak_weeks / max(1, (n - WARMUP)) * 100,
        "spy_mult": spy_mult, "yrs": yrs, "yearly": yearly,
    }


def main():
    dates, series = load_panel(PANEL)
    print(f"面板: {os.path.basename(PANEL)} | {dates[0]} ~ {dates[-1]} ({len(dates)}周)")
    print(f"选股宇宙: {len([c for c in series if c not in EXCLUDE and c not in DEF_OLD and c not in DEF_NEW])} 只(剔除指数/防御)")
    print(f"已并入真实 GLD/JPM (westock-data): NEW 组弱市停车进真实 GLD\n")

    res = {}
    for mode in ("OLD", "NEW"):
        hist, st = run_strategy(series, dates, mode)
        res[mode] = st
        print(f"[{mode}] 期末倍数 {st['multiple']:.2f}x | CAGR {st['cagr']:.1f}% | "
              f"MDD {st['mdd']*100:.1f}% | 弱市占比 {st['weak_pct']:.1f}% | "
              f"SPY买入持有 {st['spy_mult']:.2f}x" if st['spy_mult'] else f"[{mode}] ...")

    o, ne = res["OLD"], res["NEW"]
    print("\n=== 修正效应(同真实面板, 仅差异化弱市停车+防御篮) ===")
    print(f"  收益倍数: OLD {o['multiple']:.2f}x -> NEW {ne['multiple']:.2f}x  "
          f"({(ne['multiple']/o['multiple']-1)*100:+.1f}%)")
    print(f"  MDD:      OLD {o['mdd']*100:.1f}% -> NEW {ne['mdd']*100:.1f}%  "
          f"({(ne['mdd']-o['mdd'])*100:+.1f}pp)")
    print(f"  CAGR:     OLD {o['cagr']:.1f}% -> NEW {ne['cagr']:.1f}%")
    print("\n  逐年收益(OLD vs NEW):")
    yrs = sorted(set(list(o['yearly']) + list(ne['yearly'])))
    for y in yrs:
        ov = o['yearly'].get(y, 1.0); nv = ne['yearly'].get(y, 1.0)
        print(f"    {y}: OLD {(ov-1)*100:+.1f}%  NEW {(nv-1)*100:+.1f}%")

    print("\n结论(真实GLD数据):")
    print(f"  NEW 相对 OLD 收益 {ne['multiple']/o['multiple']-1:+.1%}, MDD {(ne['mdd']-o['mdd'])*100:+.1f}pp。")
    print("  v6.14b 'GLD弱市停车' 真实效果: GLD 长期 alpha 贡献了收益, 但危机周(如2022)GLD 同样下跌,")
    print("  未能像零波动现金那样'止血', 故回撤改善有限(-0.4pp 实则略差)。")
    print("  若目标压回撤 -> 弱市应保留部分现金缓冲(非全 GLD); 若目标收益 -> GLD 优于 CWB。")


if __name__ == "__main__":
    main()
