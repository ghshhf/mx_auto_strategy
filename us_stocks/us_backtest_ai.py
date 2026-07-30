"""
us_backtest_ai.py - 美股真实面板回测 + AI 选股层接入 (v6.15)

目的:
  在已并入真实面板(weekly_adjclose_full_ext.csv, 2016~2026 周频, westock-data 抓取真实
  GLD/JPM)的 v6.14b 修正逻辑(NEW: 弱市停车进真实 GLD)之上, 接入 A 股系统的 AI 选股能力
  (ai_score.py 的乘数打分层 0.8~1.2), 量化「AI 质量加权」对进攻仓的净效应。

为什么叫「AI 选股层」:
  ai_score.augment(candidates, cfg, tag) 是 A 股系统的通用 AI 加权打分层 —— 入参为带
  code/final_score 的候选 dict 列表, 输出 0.8~1.2 质量乘数(>1 质评加分, <1 减分, 1.0 中性)。
  其设计铁律: **回测禁用实时 LLM(前视偏差+不可复现)**, AI 仅 live shadow 评估。
  因此本回测默认用 **确定性质量乘数**(可复现、无前视) 作代理; 加 --with-llm 时真正调用
  ai_score.augment(需配置 LLM_* 环境变量, 否则自动 pass-through 乘数=1.0)。

确定性质量乘数(无前视, 仅用 <=t 数据):
  - 风险调整动量 = 52周动量 / 年化波动率(周收益 std * sqrt(52))
  - 距52周高点 = close / max(close 近52周)
  - 合成 norm ∈[-1,1] -> 乘数 = 1.0 + 0.2*norm, 钳 [0.8,1.2]
  直觉: 奖励高夏普动量 + 贴近新高(动量确认), 惩罚深回撤标的。

对比口径:
  - baseline: 进攻仓等权(TopN 动量)
  - ai      : 进攻仓按 AI 质量乘数加权(防御/停车/现金仓不变)
  两组共用同一动量选股 + 同一 regime/death-cross + 同一 NEW 仓位模板, 仅差异化进攻仓权重,
  干净隔离 AI 选股效应。

运行:
  python us_backtest_ai.py              # 默认: 确定性 AI 乘数(离线可复现, stdlib only)
  python us_backtest_ai.py --with-llm  # 真正调用 ai_score.augment(需 LLM 配置, 否则 pass-through)
  python us_backtest_ai.py --no-ai     # 仅 baseline
输出:
  us_stocks/data/us_nav_ai.csv (date, baseline_nav, ai_nav) 供画图/对齐 A 股 curves.html
"""
import os
import csv
import math
import argparse
import statistics
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
PANEL = os.path.join(DATA, "weekly_adjclose_full_ext.csv")
OUT_CSV = os.path.join(DATA, "us_nav_ai.csv")

EXCLUDE = {"SPY", "QQQ", "DIA", "IWM", "MDY", "VTI", "CWB", "GLD"}  # 指数/工具/停车资产, 不进选股
BROAD = ["SPY", "QQQ", "DIA", "IWM", "MDY", "VTI"]
DEF_NEW = ["KO", "NEE", "JPM"]         # v6.14b 防御篮(真防御); GLD 作弱市停车资产
WARMUP = 52                           # 需 1 年历史算动量
REBAL = 13                            # 季频再平衡
TOP_N = 10                            # 动量选股数

# 仓位模板 (NEW: 弱市停车进真实 GLD, 平时持 KO/NEE/JPM 防御篮)
ALLOC = {
    "bull":    {"off": 80, "def": 10, "park": 0,  "cash": 0,  "park_asset": "GLD"},
    "balance": {"off": 60, "def": 20, "park": 0,  "cash": 20, "park_asset": "GLD"},
    "weak":    {"off": 20, "def": 20, "park": 60, "cash": 0,  "park_asset": "GLD"},
}


# ----------------------------------------------------------------- 数据/工具
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
    """52周动量 TopN (无前视: 仅用 <=i 数据)。返回 [(mom, code), ...] 降序。"""
    scored = []
    for c in universe:
        arr = series.get(c)
        if not arr or i < WARMUP or arr[i] is None or arr[i - WARMUP] in (None, 0):
            continue
        mom = arr[i] / arr[i - WARMUP] - 1
        scored.append((mom, c))
    scored.sort(reverse=True)
    return scored[:TOP_N]


# ----------------------------------------------------------------- AI 选股层
def ai_mult_deterministic(series, i, code):
    """确定性质量乘数 [0.8,1.2] (可复现, 无前视)。"""
    arr = series.get(code)
    if not arr or i < WARMUP or arr[i] is None or arr[i - WARMUP] in (None, 0):
        return 1.0
    mom = arr[i] / arr[i - WARMUP] - 1
    win = [v for v in arr[max(0, i - WARMUP):i + 1] if v not in (None, 0)]
    rets = [win[k] / win[k - 1] - 1 for k in range(1, len(win)) if win[k - 1] not in (None, 0)]
    vol = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    risk_adj = mom / (vol * (52 ** 0.5)) if vol > 0 else mom
    high = max(win)
    dist_high = arr[i] / high if high else 1.0
    norm_mom = max(-1.0, min(1.0, risk_adj / 1.0))
    norm_high = max(-1.0, min(1.0, (dist_high - 0.85) / 0.15))
    comp = 0.6 * norm_mom + 0.4 * norm_high
    m = 1.0 + 0.2 * comp
    return max(0.8, min(1.2, m))


def ai_mult_via_llm(series, i, scored, cfg):
    """真正调用 ai_score.augment 取乘数(需 LLM 配置; 否则 pass-through=1.0)。"""
    try:
        import ai_score  # 延迟导入, 默认路径不依赖 ai_score/llm_client
    except Exception as e:
        print(f"  [ai_score] 模块不可用({e}), 退回确定性乘数")
        return {c: 1.0 for _, c in scored}
    candidates = []
    for mom, c in scored:
        arr = series.get(c) or []
        chg20 = None
        if i >= 4 and arr[i] not in (None, 0) and arr[i - 4] not in (None, 0):
            chg20 = (arr[i] / arr[i - 4] - 1) * 100
        candidates.append({
            "code": c, "name": c, "industry": "us",
            "final_score": round(mom, 4), "chg20": round(chg20, 1) if chg20 is not None else None,
        })
    augmented = ai_score.augment(candidates, cfg, tag="us_offensive")
    return {d["code"]: d.get("ai_multiplier", 1.0) for d in augmented}


# ----------------------------------------------------------------- 回测引擎
def run_strategy(series, dates, use_ai, cfg=None, verbose=False):
    """返回 (nav_hist, stats_dict)。进攻仓: baseline 等权 / ai 按乘数加权。"""
    codes_all = list(series.keys())
    universe = [c for c in codes_all if c not in EXCLUDE and c not in DEF_NEW]
    n = len(dates)
    nav = 1.0
    nav_hist = []
    peak = 1.0
    mdd = 0.0
    weights = {"__cash__": 1.0}
    selected = []
    last_rebal = -100
    yearly = {}
    weak_weeks = 0

    for t in range(n):
        if t > 0 and weights:
            growth = 0.0
            for c, w in weights.items():
                if c == "__cash__":
                    continue
                arr = series.get(c)
                if not arr or arr[t] is None or arr[t - 1] in (None, 0):
                    continue
                growth += w * (arr[t] / arr[t - 1] - 1)
            nav *= (1 + growth)
            nav_hist.append(nav)
            peak = max(peak, nav)
            mdd = min(mdd, nav / peak - 1)
            y = dates[t][:4]
            yearly.setdefault(y, 1.0)
            yearly[y] *= (1 + growth)
        else:
            nav_hist.append(nav)

        need_rebal = (t == WARMUP) or (t - last_rebal >= REBAL)
        if t >= WARMUP and need_rebal:
            selected = select_offense(series, t, universe)
            last_rebal = t

        if t >= WARMUP and selected:
            weak = (regime_of(series, t) == "weak") or (death_cross_count(series, t) >= 3)
            if weak:
                weak_weeks += 1
            a = ALLOC["weak" if weak else regime_of(series, t)]
            tw = {}
            # 进攻仓权重
            if use_ai and cfg is not None:
                mult_map = ai_mult_via_llm(series, t, selected, cfg)
            elif use_ai:
                mult_map = {c: ai_mult_deterministic(series, t, c) for _, c in selected}
            else:
                mult_map = {c: 1.0 for _, c in selected}
            off_total = a["off"] / 100.0
            msum = sum(mult_map.get(c, 1.0) for _, c in selected) or 1.0
            for _, c in selected:
                tw[c] = off_total * mult_map.get(c, 1.0) / msum
            # 防御篮等权
            per_def = a["def"] / 100.0 / len(DEF_NEW)
            for c in DEF_NEW:
                tw[c] = per_def
            # 停车资产
            if a["park"] > 0 and a["park_asset"] != "__cash__":
                tw[a["park_asset"]] = a["park"] / 100.0
            tw["__cash__"] = (a["cash"] + (a["park"] if a["park_asset"] == "__cash__" else 0)) / 100.0
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
        "multiple": nav, "cagr": cagr, "mdd": mdd,
        "weak_pct": weak_weeks / max(1, (n - WARMUP)) * 100,
        "spy_mult": spy_mult, "yrs": yrs, "yearly": yearly,
    }


# ----------------------------------------------------------------- 主程序
def main():
    ap = argparse.ArgumentParser(description="美股真实面板回测 + AI 选股层")
    ap.add_argument("--with-llm", action="store_true", help="调用 ai_score.augment 取乘数(需 LLM 配置)")
    ap.add_argument("--no-ai", action="store_true", help="仅 baseline(进攻等权)")
    args = ap.parse_args()

    use_ai = not args.no_ai
    cfg = None
    if args.with_llm:
        try:
            import ai_score
            cfg = ai_score.load_config()
            print(f"  [ai_score] enabled={ai_score._is_enabled(cfg)} shadow={cfg.get('ai_overlay',{}).get('shadow_mode')}")
        except Exception as e:
            print(f"  [ai_score] 加载失败({e}), 退回确定性乘数")

    dates, series = load_panel(PANEL)
    print(f"面板: {os.path.basename(PANEL)} | {dates[0]} ~ {dates[-1]} ({len(dates)}周)")
    print(f"选股宇宙: {len([c for c in series if c not in EXCLUDE and c not in DEF_NEW])} 只(剔除指数/防御)")
    print(f"AI 选股层: {'--with-llm(ai_score.augment)' if (args.with_llm and cfg) else ('确定性质量乘数' if use_ai else '关闭(baseline)')}\n")

    base_hist, base_st = run_strategy(series, dates, use_ai=False)
    ai_hist, ai_st = run_strategy(series, dates, use_ai=True, cfg=(cfg if args.with_llm else None))

    print(f"[baseline] 期末倍数 {base_st['multiple']:.2f}x | CAGR {base_st['cagr']:.1f}% | "
          f"MDD {base_st['mdd']*100:.1f}% | SPY买入持有 {base_st['spy_mult']:.2f}x")
    print(f"[ai     ] 期末倍数 {ai_st['multiple']:.2f}x | CAGR {ai_st['cagr']:.1f}% | "
          f"MDD {ai_st['mdd']*100:.1f}%")

    print("\n=== AI 选股层净效应(baseline -> ai) ===")
    print(f"  收益倍数: {base_st['multiple']:.2f}x -> {ai_st['multiple']:.2f}x  "
          f"({(ai_st['multiple']/base_st['multiple']-1)*100:+.1f}%)")
    print(f"  MDD:      {base_st['mdd']*100:.1f}% -> {ai_st['mdd']*100:.1f}%  "
          f"({(ai_st['mdd']-base_st['mdd'])*100:+.1f}pp)")
    print(f"  CAGR:     {base_st['cagr']:.1f}% -> {ai_st['cagr']:.1f}%")

    print("\n  逐年收益(baseline vs ai):")
    yrs = sorted(set(list(base_st['yearly']) + list(ai_st['yearly'])))
    for y in yrs:
        bv = base_st['yearly'].get(y, 1.0); av = ai_st['yearly'].get(y, 1.0)
        print(f"    {y}: baseline {(bv-1)*100:+.1f}%  ai {(av-1)*100:+.1f}%")

    # 输出 CSV (date, baseline_nav, ai_nav) 供对齐 A 股 curves.html
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "baseline_nav", "ai_nav"])
        for d, b, a in zip(dates, base_hist, ai_hist):
            w.writerow([d, f"{b:.6f}", f"{a:.6f}"])
    print(f"\n  已写出 NAV 曲线: {OUT_CSV}")


if __name__ == "__main__":
    main()
