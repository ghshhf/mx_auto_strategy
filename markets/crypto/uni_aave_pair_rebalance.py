# -*- coding: utf-8 -*-
"""UNI + AAVE 双币配对再平衡 — 回答用户:"UNI 和 AAVE 再平衡增加多少筹码?"

背景:
  - 已有 crypto_btc_ada_pair.py (BTC+ADA/ETH+ADA)、eth_sol_pair_rebalance.py (ETH+SOL);
  - UNI 与 AAVE 同在数据面板 27 币中, 自然公共窗口 = AAVE 上市日(2020-10-09);
  - 本脚本补这一格, 复用同一引擎(sim/buyhold/solo), 口径与既有结果严格可比。

口径铁律(与全项目一致, 不可混用):
  ① 筹码口径 units_mult          -> 回答"囤了多少币, 掉队没有"(死拿=1.000)  ← 根本答案
  ② 美元口径 nav = Σ w·R·Pnorm   -> 回答"赚几倍"
  再平衡目的 = 筹码不掉队(>=1.0), 非收益最大化。

数据: data/weekly_adjclose_crypto50_10y.csv (周频后复权, 27 列)
"""
import os
import importlib.util

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("bap", os.path.join(HERE, "crypto_btc_ada_pair.py"))
bap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bap)          # main() 在 __main__ 保护下, import 安全

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
OUTDIR = os.path.join(HERE, "out")
COST_BP = 10.0
PAIR = ("UNI", "AAVE")


def load_panel():
    px = pd.read_csv(PANEL, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


def natural_start(px, coins):
    """自然公共窗口 = 各币首个有效报价日的最大值。"""
    return max(px[c].first_valid_index() for c in coins)


def main():
    px = load_panel()
    a, b = PAIR
    rows = []

    for c in PAIR:
        fd = px[c].first_valid_index()
        print(f"  {c:5s} 面板首日 {fd.date()}  末日 {px[c].last_valid_index().date()}  "
              f"NaN {int(px[c].isna().sum())} 周")

    win0 = natural_start(px, list(PAIR))
    end = px.index[-1]
    print(f"\n{a}+{b} 自然公共窗口: {win0.date()} ~ {end.date()}  "
          f"({(end - win0).days / 365.25:.2f}y)")
    print(f"面板末日: {end.date()}  (数据源: weekly_adjclose_crypto50_10y.csv)")

    # ---------- A. 主结果 ----------
    print(f"\n{'=' * 92}")
    print(f"### A. {a} + {b} 双币配对 (等权月度再平衡 vs 死拿)")
    print("=" * 92)
    base = bap.sim(px, list(PAIR), start=win0, cost_bp=0.0)
    st, en = base["start"], base["end"]
    print(f"  窗口 {st.date()} ~ {en.date()}  ({base['yrs']:.2f}y)")
    print("  [美元口径 — 赚几倍]")
    bap.line(f"{a}+{b} 等权月再平衡 (0bp)", base)
    r10 = bap.sim(px, list(PAIR), start=win0, cost_bp=10.0)
    r30 = bap.sim(px, list(PAIR), start=win0, cost_bp=30.0)
    for cbp, r in ((10.0, r10), (30.0, r30)):
        bap.line(f"{a}+{b} 等权月再平衡 ({cbp:.0f}bp)", r)
    h = bap.buyhold(px, list(PAIR), st, en)
    bap.line(f"{a}+{b} 等权死拿", h)
    bap.line(f"{a} 独家死拿", bap.solo(px, a, st, en))
    bap.line(f"{b} 独家死拿", bap.solo(px, b, st, en))
    print(f"  年化换手 {base['turnover_ann'] * 100:.1f}% / 年   调仓 {base['turnover_events']} 次")

    print(f"  [筹码口径 — 囤了多少币, 死拿该组合 = 1.000]")
    bap.chip_line(f"{a}+{b} 等权月再平衡", base)
    bap.chip_line(f"{a}+{b} 等权月再平衡 (10bp)", r10)
    print(f"  [再平衡超额] 净值比 {base['nav'] / base['hold_nav']:.4f}  "
          f"超额 {(base['nav'] / base['hold_nav'] - 1) * 100:+.2f}%")
    print(f"  [起点价] {a} {base['px_first'][a]:.4f} -> {base['px_last'][a]:.4f}   "
          f"{b} {base['px_first'][b]:.4f} -> {base['px_last'][b]:.4f}")

    for tag, r in [("0bp", base), ("10bp", r10), ("30bp", r30)]:
        if r is None:
            continue
        rows.append(dict(tag=f"{a}+{b} {tag}", window="全窗口", yrs=r["yrs"], nav=r["nav"],
                         cagr=r["cagr"] * 100, mdd=r["mdd"] * 100,
                         hold_nav=r["hold_nav"], excess=(r["nav"] / r["hold_nav"] - 1) * 100,
                         units_a=r["units_mult"][a], units_b=r["units_mult"][b],
                         turnover=r["turnover_ann"] * 100))

    # 筹码随时间轨迹(每 5 个再平衡点抽样)
    us = base["units_ser"]
    print(f"\n  [筹码轨迹 — 每 6 个月抽样]")
    print(f"  {'日期':>12s}{a:>12s}{b:>12s}")
    for dt in us.index[::26]:
        print(f"  {str(dt.date()):>12s}{us.loc[dt, a]:>11.4f}x{us.loc[dt, b]:>11.4f}x")
    print(f"  {str(us.index[-1].date()):>12s}{us.iloc[-1][a]:>11.4f}x{us.iloc[-1][b]:>11.4f}x  <== 期末")

    # ---------- B. 分段 ----------
    windows = [
        ("段1 · 2020-10~2022-11 (上轮牛熊)", (None, "2022-11-11")),
        ("段2 · 2022-11~2024-04 (复苏)", ("2022-11-11", "2024-04-19")),
        ("段3 · 2024-04~今 (本轮)", ("2024-04-19", None)),
        ("近3年", (str((end - pd.Timedelta(days=1095)).date()), None)),
        ("近2年", (str((end - pd.Timedelta(days=730)).date()), None)),
        ("近1年", (str((end - pd.Timedelta(days=365)).date()), None)),
    ]
    print(f"\n{'=' * 92}")
    print(f"### B. {a} + {b} 分段 (公共窗口对齐)")
    print("=" * 92)
    for wtag, (s0, s1) in windows:
        bb = bap.sim(px, list(PAIR), start=s0, end=s1, cost_bp=COST_BP)
        if bb is None:
            print(f"  {wtag}: 数据不足")
            continue
        hh = bap.buyhold(px, list(PAIR), bb["start"], bb["end"])
        print(f"\n-- {wtag}  {bb['start'].date()} ~ {bb['end'].date()} ({bb['yrs']:.2f}y)")
        print(f"   再平衡净值 {bb['nav']:.3f}x (CAGR {bb['cagr'] * 100:+.2f}%, MDD {bb['mdd'] * 100:+.2f}%)   "
              f"死拿 {hh['nav']:.3f}x   超额 {(bb['nav'] / hh['nav'] - 1) * 100:+.2f}%")
        print(f"   筹码 {a} {bb['units_mult'][a]:.4f}x  {b} {bb['units_mult'][b]:.4f}x   "
              f"换手 {bb['turnover_ann'] * 100:.0f}%/年")
        rows.append(dict(tag=f"{a}+{b} 10bp", window=wtag, yrs=bb["yrs"], nav=bb["nav"],
                         cagr=bb["cagr"] * 100, mdd=bb["mdd"] * 100, hold_nav=hh["nav"],
                         excess=(bb["nav"] / hh["nav"] - 1) * 100,
                         units_a=bb["units_mult"][a], units_b=bb["units_mult"][b],
                         turnover=bb["turnover_ann"] * 100))

    # ---------- C. 频率对比(月度 vs 每周, 含相位) ----------
    print(f"\n{'=' * 92}")
    print(f"### C. 调仓频率对比 (0bp; 长窗口需看相位, 见 memory)")
    print("=" * 92)
    for freq, lab in ((1, "每周"), (2, "双周"), (4, "月度"), (8, "双月")):
        r0 = bap.sim(px, list(PAIR), rebal_weeks=freq, start=win0, cost_bp=0.0)
        if r0 is None:
            continue
        print(f"  {lab:5s} 净值 {r0['nav']:>9.3f}x  超额 {(r0['nav'] / r0['hold_nav'] - 1) * 100:>+8.2f}%  "
              f"筹码 {a} {r0['units_mult'][a]:.4f}x / {b} {r0['units_mult'][b]:.4f}x  "
              f"换手 {r0['turnover_ann'] * 100:.0f}%/年")

    # ---------- D. 配对准入检验 ----------
    print(f"\n{'=' * 92}")
    print(f"### D. {a}/{b} 配对准入检验 (相关 / 波动 / 漂移方向)")
    print("=" * 92)
    sub = px.loc[win0:, list(PAIR)].dropna()
    rr = sub.pct_change().dropna()
    print(f"  周收益相关 {rr[a].corr(rr[b]):.3f}")
    print(f"  年化波动 {a} {rr[a].std() * np.sqrt(52) * 100:.1f}%  "
          f"{b} {rr[b].std() * np.sqrt(52) * 100:.1f}%")
    sa = bap.solo(px, a, win0, None)
    sb = bap.solo(px, b, win0, None)
    drift = (sa["cagr"] - sb["cagr"]) * 100
    kind = "双正" if sa["cagr"] > 0 and sb["cagr"] > 0 else ("双负" if sa["cagr"] < 0 and sb["cagr"] < 0 else "一正一负")
    print(f"  全窗口漂移 {a} CAGR {sa['cagr'] * 100:+.2f}%  {b} {sb['cagr'] * 100:+.2f}%  "
          f"漂移差 {drift:+.1f}pp  ->  {kind}")
    print(f"  (准入三条件: 低相关<0.3 / 高波动>20% / 无长期单边赢家; 判据是漂移方向不是波动率)")

    # ---------- 落盘 ----------
    os.makedirs(OUTDIR, exist_ok=True)
    pd.DataFrame(rows).to_csv(os.path.join(OUTDIR, "uni_aave_pair_rebalance.csv"),
                              index=False, encoding="utf-8-sig")
    print(f"\n[落盘] out/uni_aave_pair_rebalance.csv  ({len(rows)} 行)")


if __name__ == "__main__":
    main()
