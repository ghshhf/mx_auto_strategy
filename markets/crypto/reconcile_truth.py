"""
reconcile_truth.py — crypto 倍率真值对齐与统一

历史目标：消除 crypto 10y 倍率在四处碎片化（README 28,092x / param 6.79Mx /
config注释 59,361Kx）。固定面板 + 固定窗口，用 run_bt 跑多档配置，
打印每档 multiple/MDD/Sharpe，并逐腿拆解各层贡献。

2026-09-04 更新（P1 真值统一）:
  - 面板已由 43 币精简为 **34 币**，且三张面板(crypto50/10y/v3)已修复为真值、
    完全对齐（此前 v3 为合成数据、c50 有上线前假历史）
  - **期权三件套已于 2026-08-31 临时关闭**（审计发现 put 保险层被误建模为收益
    引擎，见 crypto_options_bt.py 第 141 行注释）。故所有"期权"相关标签已移除，
    逐腿拆解保留用于验证期权层确无贡献（应恒为 Δ=+0.0%）
  - 新增 **10y 窗口**（2016-08-11 起，与 TRUTH_AUTHORITY.md 同源口径），
    原脚本只跑 12y 全面板，无法与文档数字对齐
  - 修复 reports/ 目录缺失导致的 FileNotFoundError

用法：python reconcile_truth.py
"""
import os, sys, json, time
import pandas as pd, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from crypto_options_bt import run_bt, DEFAULT_CFG  # noqa: E402,F401

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
TEN_Y_START = pd.Timestamp("2016-08-11")   # 与 TRUTH_AUTHORITY.md 同源 10y 窗口

# 窗口定义: name -> 起始日(None=全面板)
WINDOWS = [("12y全面板", None), ("10y窗口", TEN_Y_START)]


def load_panel():
    px = pd.read_csv(PANEL, index_col=0, parse_dates=True).sort_index()
    px = px.loc[:, (px.notna().any()) & ((px != 0).any())]
    return px


def fmt(r):
    return (f"{r['multiple']:>14,.0f}x  MDD={r['mdd']*100:>6.1f}%  "
            f"Sharpe={r['sharpe']:.2f}  CAGR={r['cagr']*100:>6.1f}%")


def main():
    t0 = time.time()
    px_all = load_panel()
    print(f"面板: {px_all.shape[1]} 币, {px_all.shape[0]} 周 "
          f"({px_all.index[0].date()} ~ {px_all.index[-1].date()})")
    print(f"期权三件套状态: 已关闭(2026-08-31) — 逐腿拆解应恒为 Δ=+0.0%")
    print("=" * 92)

    # 配置档位: (key, label, overrides)
    CFGS = [
        ("FULL_default", "FULL(DEFAULT: inv_vol+1.2+周期)", {}),
        ("MULT1.0", "MULT1.0(inv_vol+1.0+周期)", {"alloc_offense_mult": 1.0}),
        ("EQUAL", "EQUAL(等权+1.0+周期)",
         {"offense_weight_mode": "equal", "alloc_offense_mult": 1.0}),
        ("NO_CYCLE", "NO_CYCLE(inv_vol+1.2, 关周期)", {"halving_cycle_enabled": False}),
        ("NO_CYCLE_NOOPTS", "NO_CYCLE_MULT1.0(纯现货轮动)",
         {"halving_cycle_enabled": False, "alloc_offense_mult": 1.0}),
    ]

    out = {}
    for wname, wstart in WINDOWS:
        px = px_all if wstart is None else px_all[px_all.index >= wstart]
        print(f"\n### 窗口: {wname}  ({px.shape[0]} 周, "
              f"{px.index[0].date()} ~ {px.index[-1].date()})")
        print("-" * 92)
        out[wname] = {"weeks": int(px.shape[0]),
                      "start": str(px.index[0].date()),
                      "end": str(px.index[-1].date()), "cfgs": {}}
        for i, (key, label, ov) in enumerate(CFGS, 1):
            cfg = dict(DEFAULT_CFG)
            cfg.update(ov)
            r = run_bt(px, cfg, label=label)
            print(f"  [{i}] {label:<36} {fmt(r)}")
            out[wname]["cfgs"][key] = {
                "multiple": r["multiple"], "mdd": r["mdd"],
                "sharpe": r["sharpe"], "cagr": r["cagr"]}

        # mult 1.2 vs 1.0 放大比
        a = out[wname]["cfgs"]["FULL_default"]["multiple"]
        b = out[wname]["cfgs"]["MULT1.0"]["multiple"]
        print(f"      >>> alloc_offense_mult 1.2 vs 1.0 倍率比 = {a/b:.2f}x")
        out[wname]["mult_ratio"] = a / b

    # ---- 逐腿拆解（验证期权层已彻底关闭）----
    print("\n" + "=" * 92)
    print("逐腿拆解 (10y 窗口, FULL 配置基础上关单腿 — 用于验证期权层无贡献):")
    px = px_all[px_all.index >= TEN_Y_START]
    base = out["10y窗口"]["cfgs"]["FULL_default"]["multiple"]
    leg = {}
    for key, label, ov in [
        ("nocall", "关 covered call", {"enabled_call": False}),
        ("noput", "关 put保险", {"enabled_put": False}),
        ("noshort", "关 做空", {"enabled_short": False}),
    ]:
        cfg = dict(DEFAULT_CFG)
        cfg.update(ov)
        r = run_bt(px, cfg, label=label)
        delta = r["multiple"] / base * 100 - 100
        flag = "✓ 无贡献(符合预期)" if abs(delta) < 0.05 else "⚠ 有贡献(异常)"
        print(f"  {label:<18} -> {r['multiple']:>14,.0f}x  (Δ={delta:+.1f}%)  {flag}")
        leg[key] = r["multiple"]
    out["leg"] = {"full": base, **leg}

    # ---- 写报告 ----
    os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
    path = os.path.join(HERE, "reports", "reconcile_truth_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("=" * 92)
    print(f"总耗时 {time.time()-t0:.0f}s")
    print(f"已写入 {path}")


if __name__ == "__main__":
    main()
