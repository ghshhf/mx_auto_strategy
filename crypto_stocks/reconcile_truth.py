"""
reconcile_truth.py — crypto 倍率真值对齐（P0-1）

目标：消除 crypto 10y 倍率在四处碎片化（README 28,092x / param 6.79Mx /
config注释 59,361Kx）。固定面板(43币, 10y) + 固定窗口，用 run_bt 跑多档配置，
打印每档 multiple/MDD/Sharpe，并逐腿拆解期权贡献，定位 8.7x 跳变是否 bug。

用法：python reconcile_truth.py
"""
import os, sys, json, time
import pandas as pd, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from crypto_options_bt import run_bt, DEFAULT_CFG, CryptoOptionsConfig

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")

def load_panel():
    px = pd.read_csv(PANEL, index_col=0, parse_dates=True)
    px = px.sort_index()
    # 去全空列
    px = px.loc[:, (px.notna().any()) & ((px != 0).any())]
    return px

def run(label, **overrides):
    cfg = dict(DEFAULT_CFG)
    cfg.update(overrides)
    r = run_bt(px, cfg, label=label)
    return r

def fmt(r):
    return f"multiple={r['multiple']:,.0f}x  MDD={r['mdd']*100:,.1f}%  Sharpe={r['sharpe']:.2f}  CAGR={r['cagr']*100:,.1f}%"

if __name__ == "__main__":
    t0 = time.time()
    px = load_panel()
    print(f"面板: {px.shape[1]} 币, {px.shape[0]} 周 ({px.index[0].date()} ~ {px.index[-1].date()})")
    print("=" * 78)

    out = {}
    # 1) FULL = DEFAULT_CFG（inv_vol + alloc_offense_mult=1.2 + 期权 + 周期）
    r_full = run("FULL(DEFAULT: inv_vol+1.2+期权+周期)")
    print(f"[1] {r_full['label']}\n    {fmt(r_full)}")
    out['FULL_default'] = r_full['multiple']

    # 2) 同 FULL 但 alloc_offense_mult=1.0 —— 验证 8.7x 跳变是否真实
    r_m1 = run("MULT1.0(inv_vol+1.0+期权+周期)", alloc_offense_mult=1.0)
    print(f"[2] {r_m1['label']}\n    {fmt(r_m1)}")
    print(f"    >>> mult=1.2 vs 1.0 倍率比 = {r_full['multiple']/r_m1['multiple']:.2f}x  "
          f"(config注释声称 +774% = 8.74x)")
    out['MULT1.0'] = r_m1['multiple']

    # 3) equal 权重（旧基线口径）+ 期权 + 周期
    r_eq = run("EQUAL(equal+1.0+期权+周期)", offense_weight_mode='equal', alloc_offense_mult=1.0)
    print(f"[3] {r_eq['label']}\n    {fmt(r_eq)}")
    out['EQUAL'] = r_eq['multiple']

    # 4) 纯现货轮动 + 周期（关掉全部期权层）
    r_no = run("NO_OPTS(现货+周期, 关期权)", enabled_call=False, enabled_put=False,
               enabled_short=False, alloc_offense_mult=1.0)
    print(f"[4] {r_no['label']}\n    {fmt(r_no)}")
    out['NO_OPTS'] = r_no['multiple']

    # 5) 关周期（期权+inv_vol，但 halving 关）
    r_nc = run("NO_CYCLE(inv_vol+1.2+期权, 关周期)", halving_cycle_enabled=False)
    print(f"[5] {r_nc['label']}\n    {fmt(r_nc)}")
    out['NO_CYCLE'] = r_nc['multiple']

    # 6) 关周期+关期权（纯现货轮动，最朴素）
    r_ns = run("NO_CYCLE_NOOPTS(纯现货轮动)", halving_cycle_enabled=False,
               enabled_call=False, enabled_put=False, enabled_short=False,
               alloc_offense_mult=1.0)
    print(f"[6] {r_ns['label']}\n    {fmt(r_ns)}")
    out['NO_CYCLE_NOOPTS'] = r_ns['multiple']

    # ---- 逐腿拆解（基于 FULL 配置，依次关掉单腿）----
    print("=" * 78)
    print("逐腿拆解 (FULL 配置基础上关单腿):")
    r_nocall = run("  -covered_call", enabled_call=False)
    r_noput  = run("  -put保险", enabled_put=False)
    r_noshort= run("  -做空", enabled_short=False)
    print(f"  关 covered call -> {r_nocall['multiple']:,.0f}x (Δ={r_nocall['multiple']/r_full['multiple']*100-100:+.1f}%)")
    print(f"  关 put保险      -> {r_noput['multiple']:,.0f}x (Δ={r_noput['multiple']/r_full['multiple']*100-100:+.1f}%)")
    print(f"  关 做空         -> {r_noshort['multiple']:,.0f}x (Δ={r_noshort['multiple']/r_full['multiple']*100-100:+.1f}%)")
    out['leg'] = {'full':r_full['multiple'],'nocall':r_nocall['multiple'],
                  'noput':r_noput['multiple'],'noshort':r_noshort['multiple']}

    print("=" * 78)
    print(f"总耗时 {time.time()-t0:.0f}s")
    with open(os.path.join(HERE, "reconcile_truth_report.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("已写入 reconcile_truth_report.json")
