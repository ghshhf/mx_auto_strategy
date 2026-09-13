# -*- coding: utf-8 -*-
"""ETH + SOL 双币配对再平衡 — 回答用户:"数据里有没有以太坊和SOL的再平衡"

背景:
  - 已有 `crypto_btc_ada_pair.py` 跑了 BTC+ADA / ETH+ADA, 但**没有 ETH+SOL**;
  - `crypto_rebalance_exhaustive.py` 的穷举池 27 币里**不含 ETH**(池按"买旧不买新+熊市
    幸存"筛出, BTC/ETH 作为基准币单列), 所以穷举结果里也查不到 ETH+SOL。
  → 本脚本补这一格: 复用同一引擎(sim/buyhold/solo), 保证口径与既有结果可比。

口径铁律(与全项目一致, 不可混用):
  ① 美元口径 nav = Σ w·R·Pnorm  → 回答"赚几倍"
  ② 筹码口径 units_mult          → 回答"囤了多少币, 掉队没有"
  再平衡目的 = 筹码不掉队(>=1.0), 非收益最大化。

数据: data/weekly_adjclose_crypto50_10y.csv (周频后复权, 27 列, 至 2026-09-04)
"""
import os
import importlib.util
import io

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("bap", os.path.join(HERE, "crypto_btc_ada_pair.py"))
bap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bap)          # main() 在 __main__ 保护下, import 安全

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
OUTDIR = os.path.join(HERE, "out")
REBAL_WEEKS = bap.REBAL_WEEKS
COST_BP = 10.0


def load_panel():
    px = pd.read_csv(PANEL, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


def natural_start(px, coins):
    """自然公共窗口 = 各币首个有效报价日的最大值。"""
    return max(px[c].first_valid_index() for c in coins)


def main():
    px = load_panel()
    rows = []

    for c in ("ETH", "SOL"):
        fd = px[c].first_valid_index()
        print(f"  {c:4s} 面板首日 {fd.date()}  末日 {px[c].last_valid_index().date()}  "
              f"NaN {int(px[c].isna().sum())} 周")

    win0 = natural_start(px, ["ETH", "SOL"])
    end = px.index[-1]
    print(f"\nETH+SOL 自然公共窗口: {win0.date()} ~ {end.date()}  "
          f"({(end - win0).days / 365.25:.2f}y)")

    # ---------- A. ETH+SOL 主结果(全窗口, 三档成本) ----------
    print(f"\n{'=' * 96}")
    print("### A. ETH + SOL 双币配对 (等权月度再平衡 vs 死拿)")
    print("=" * 96)
    base = bap.sim(px, ["ETH", "SOL"], start=win0, cost_bp=0.0)
    st, en = base["start"], base["end"]
    print(f"  窗口 {st.date()} ~ {en.date()}  ({base['yrs']:.2f}y)")
    print("  [美元口径 — 赚几倍]")
    bap.line("ETH+SOL 等权月再平衡 (0bp)", base)
    for cbp in (10.0, 30.0):
        r = bap.sim(px, ["ETH", "SOL"], start=win0, cost_bp=cbp)
        bap.line(f"ETH+SOL 等权月再平衡 ({cbp:.0f}bp)", r)
    h = bap.buyhold(px, ["ETH", "SOL"], st, en)
    bap.line("ETH+SOL 等权死拿", h)
    bap.line("ETH 独家死拿", bap.solo(px, "ETH", st, en))
    bap.line("SOL 独家死拿", bap.solo(px, "SOL", st, en))
    print(f"  年化换手 {base['turnover_ann'] * 100:.1f}% / 年   调仓 {base['turnover_events']} 次")
    print("  [筹码口径 — 囤了多少币, 死拿该组合 = 1.000]")
    bap.chip_line("ETH+SOL 等权月再平衡", base)
    r10 = bap.sim(px, ["ETH", "SOL"], start=win0, cost_bp=10.0)
    bap.chip_line("ETH+SOL 等权月再平衡 (10bp)", r10)
    print(f"  [再平衡超额] 净值比 {base['nav'] / base['hold_nav']:.4f}  "
          f"超额 {(base['nav'] / base['hold_nav'] - 1) * 100:+.2f}%")

    for tag, r in [("0bp", base), ("10bp", r10), ("30bp", bap.sim(px, ["ETH", "SOL"], start=win0, cost_bp=30.0))]:
        if r is None:
            continue
        rows.append(dict(tag=f"ETH+SOL {tag}", window="全窗口", yrs=r["yrs"], nav=r["nav"],
                         cagr=r["cagr"] * 100, mdd=r["mdd"] * 100,
                         hold_nav=r["hold_nav"], excess=(r["nav"] / r["hold_nav"] - 1) * 100,
                         units_eth=r["units_mult"]["ETH"], units_sol=r["units_mult"]["SOL"],
                         turnover=r["turnover_ann"] * 100))

    # ---------- B. 分段 ----------
    windows = [
        ("段1 · 2020-04~2022-11 (上轮牛熊)", (None, "2022-11-11")),
        ("段2 · 2022-11~2024-04 (复苏)", ("2022-11-11", "2024-04-19")),
        ("段3 · 2024-04~2026-09 (本轮)", ("2024-04-19", None)),
        ("近3年", (str((end - pd.Timedelta(days=1095)).date()), None)),
        ("近2年", (str((end - pd.Timedelta(days=730)).date()), None)),
        ("近1年", (str((end - pd.Timedelta(days=365)).date()), None)),
    ]
    print(f"\n{'=' * 96}")
    print("### B. ETH + SOL 分段 (ETH 起点最早, 与 SOL 公共窗口对齐)")
    print("=" * 96)
    for wtag, (s0, s1) in windows:
        b = bap.sim(px, ["ETH", "SOL"], start=s0, end=s1, cost_bp=0.0)
        if b is None:
            print(f"  {wtag}: 数据不足")
            continue
        r = bap.sim(px, ["ETH", "SOL"], start=s0, end=s1, cost_bp=COST_BP)
        hh = bap.buyhold(px, ["ETH", "SOL"], b["start"], b["end"])
        print(f"\n-- {wtag}  {b['start'].date()} ~ {b['end'].date()} ({b['yrs']:.2f}y)")
        print(f"   再平衡净值 {b['nav']:.3f}x (CAGR {b['cagr'] * 100:+.2f}%, MDD {b['mdd'] * 100:+.2f}%)   "
              f"死拿 {hh['nav']:.3f}x   超额 {(b['nav'] / hh['nav'] - 1) * 100:+.2f}%")
        print(f"   筹码 ETH {b['units_mult']['ETH']:.4f}x  SOL {b['units_mult']['SOL']:.4f}x   "
              f"换手 {b['turnover_ann'] * 100:.0f}%/年")
        rows.append(dict(tag="ETH+SOL 0bp", window=wtag, yrs=b["yrs"], nav=b["nav"],
                         cagr=b["cagr"] * 100, mdd=b["mdd"] * 100, hold_nav=hh["nav"],
                         excess=(b["nav"] / hh["nav"] - 1) * 100,
                         units_eth=b["units_mult"]["ETH"], units_sol=b["units_mult"]["SOL"],
                         turnover=b["turnover_ann"] * 100))

    # ---------- C. 对照组合(同窗口, 扣10bp) ----------
    print(f"\n{'=' * 96}")
    print("### C. 同窗口对照组合 (扣 10bp, 排序按再平衡超额)")
    print("=" * 96)
    combos = [("ETH", "SOL"), ("BTC", "ETH"), ("BTC", "SOL"), ("ETH", "ADA"),
              ("SOL", "ADA"), ("BTC", "ADA"), ("ETH", "DOT"), ("SOL", "DOT"),
              ("ETH", "LINK"), ("SOL", "LINK")]
    cres = []
    for a, b in combos:
        w0 = natural_start(px, [a, b])
        r = bap.sim(px, [a, b], start=w0, cost_bp=COST_BP)
        if r is None:
            continue
        hh = bap.buyhold(px, [a, b], r["start"], r["end"])
        rr = px.loc[r["start"]:r["end"], [a, b]].pct_change().dropna()
        w = np.array([0.5, 0.5])
        pvol = float(np.sqrt(w @ (rr.cov().values * 52) @ w))
        sa = bap.solo(px, a, r["start"], r["end"])
        sb = bap.solo(px, b, r["start"], r["end"])
        cres.append(dict(pair=f"{a}+{b}", start=w0, yrs=r["yrs"], nav=r["nav"],
                         cagr=r["cagr"] * 100, mdd=r["mdd"] * 100, hold=hh["nav"],
                         excess=(r["nav"] / hh["nav"] - 1) * 100,
                         vol=pvol * 100, corr=float(rr[a].corr(rr[b])),
                         drift=(sa["cagr"] - sb["cagr"]) * 100,
                         ua=r["units_mult"][a], ub=r["units_mult"][b],
                         turn=r["turnover_ann"] * 100))
    cres.sort(key=lambda x: -x["excess"])
    print(f"  {'币对':12s}{'窗口起':>12s}{'年数':>6s}{'再平衡':>10s}{'CAGR':>9s}{'MDD':>9s}"
          f"{'死拿':>9s}{'超额':>9s}{'组合波动':>9s}{'相关':>7s}{'漂移差':>9s}{'换手':>7s}")
    for r in cres:
        print(f"  {r['pair']:12s}{str(r['start'].date()):>12s}{r['yrs']:>6.2f}{r['nav']:>9.3f}x"
              f"{r['cagr']:>8.2f}%{r['mdd']:>8.2f}%{r['hold']:>8.3f}x{r['excess']:>8.2f}%"
              f"{r['vol']:>8.1f}%{r['corr']:>7.3f}{r['drift']:>8.1f}pp{r['turn']:>6.0f}%")

    # ---------- D. 配对准入检验 ----------
    print(f"\n{'=' * 96}")
    print("### D. ETH/SOL 配对准入检验 (相关 / 波动 / 漂移方向)")
    print("=" * 96)
    sub = px.loc[win0:, ["ETH", "SOL"]].dropna()
    rr = sub.pct_change().dropna()
    print(f"  周收益相关 {rr['ETH'].corr(rr['SOL']):.3f}")
    print(f"  年化波动 ETH {rr['ETH'].std() * np.sqrt(52) * 100:.1f}%  "
          f"SOL {rr['SOL'].std() * np.sqrt(52) * 100:.1f}%")
    se = bap.solo(px, "ETH", win0, None)
    ss = bap.solo(px, "SOL", win0, None)
    print(f"  全窗口漂移 ETH CAGR {se['cagr'] * 100:+.2f}%  SOL {ss['cagr'] * 100:+.2f}%  "
          f"漂移差 {(se['cagr'] - ss['cagr']) * 100:+.1f}pp  → "
          f"{'双正' if se['cagr'] > 0 and ss['cagr'] > 0 else ('双负' if se['cagr'] < 0 and ss['cagr'] < 0 else '一正一负')}")

    # ---------- 落盘 ----------
    os.makedirs(OUTDIR, exist_ok=True)
    pd.DataFrame(rows).to_csv(os.path.join(OUTDIR, "eth_sol_pair_rebalance.csv"),
                              index=False, encoding="utf-8-sig")
    pd.DataFrame(cres).to_csv(os.path.join(OUTDIR, "eth_sol_pair_compare.csv"),
                              index=False, encoding="utf-8-sig")
    print(f"\n[落盘] out/eth_sol_pair_rebalance.csv  ({len(rows)} 行)")
    print(f"[落盘] out/eth_sol_pair_compare.csv    ({len(cres)} 行)")


if __name__ == "__main__":
    main()
