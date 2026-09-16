# -*- coding: utf-8 -*-
"""ETH + SOL 双币配对 — 1 / 3 / 5 年窗口的「死拿 vs 再平衡」

调仓频率: 主口径 **每周**(用户 2026-09-13 指定), 附月度对照。
口径(与全项目一致, 不可混用):
  ① 美元口径 nav = mean(Pnorm)  → "赚几倍"
  ② 筹码口径 units_mult         → "囤了多少币, 掉队没有"(死拿该组合 = 1.000)
  再平衡相对死拿的"跑赢" = nav_rb / nav_hold - 1
另含: 起点敏感性(±6 周) —— 检验"1 年窗口几乎无差异"是不是起点巧合。
数据: data/weekly_adjclose_crypto50_10y.csv (周频后复权, 27 列)
"""
import os
import io
import json
import importlib.util

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("bap", os.path.join(HERE, "crypto_btc_ada_pair.py"))
bap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bap)

# 🔒 调仓数学收敛到跨市场唯一引擎 markets/core/rebalance.py (2026-09-15)
_spec_rb = importlib.util.spec_from_file_location(
    "rb_kernel", os.path.join(os.path.dirname(HERE), "core", "rebalance.py"))
_rb = importlib.util.module_from_spec(_spec_rb)
_spec_rb.loader.exec_module(_rb)

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
OUTDIR = os.path.join(HERE, "out")
COINS = ["ETH", "SOL"]
COST_BP = 10.0
WEEKLY, MONTHLY = 1, 4
DAYS = {"1 年": 365, "3 年": 1095, "5 年": 1826}


def load_panel():
    px = pd.read_csv(PANEL, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


def sim_phase(sub: pd.DataFrame, freq: int, phase: int, cost_bp: float = 10.0):
    """带相位的等权再平衡: 调仓日 = phase, phase+freq, ...

    用途: 检验"每周 vs 每月"的差异是**频率效应**还是**调仓日历运气**。
    同一频率换相位即换日历; 若同频率不同相位的极差 >= 频率间差异,
    则该比较无意义 —— 必须用相位中位或蒙特卡洛。
    """
    pr = sub.values.astype(float)
    # 🔒 核心循环 → 唯一引擎 (phase 参数即原版「调仓日 = phase, phase+freq, ...」)
    kr = _rb.rebalance_kernel(pr, rebal_weeks=freq, cost_bp=cost_bp,
                              capital=1.0, phase=phase)
    units, U0 = kr["units"], kr["U0"]
    yrs = (sub.index[-1] - sub.index[0]).days / 365.25
    return (float(kr["NAV"][-1]),
            {co: float(units[i] / U0[i]) for i, co in enumerate(sub.columns)},
            sum(kr["turns"]) / yrs * 100)


def main():
    px = load_panel()
    end = px.index[-1]
    w0_all = max(px[c].first_valid_index() for c in COINS)
    print(f"面板末周 {end.date()}   ETH/SOL 公共可用起点 {w0_all.date()}  "
          f"(全窗口 {(end - w0_all).days / 365.25:.2f}y)")
    print(f"主口径: 每周调仓 (rebal_weeks={WEEKLY})   对照: 月度 (rebal_weeks={MONTHLY})")

    rows = []
    windows = [(t, end - pd.Timedelta(days=d)) for t, d in DAYS.items()]
    windows.append(("全窗口", w0_all))

    for tag, cut in windows:
        rw = bap.sim(px, COINS, rebal_weeks=WEEKLY, cost_bp=COST_BP, start=cut, end=None)
        rw0 = bap.sim(px, COINS, rebal_weeks=WEEKLY, cost_bp=0.0, start=cut, end=None)
        rm = bap.sim(px, COINS, rebal_weeks=MONTHLY, cost_bp=COST_BP, start=cut, end=None)
        if rw is None:
            print(f"\n{tag}: 数据不足")
            continue
        h = bap.buyhold(px, COINS, rw["start"], rw["end"])
        se = bap.solo(px, "ETH", rw["start"], rw["end"])
        ss = bap.solo(px, "SOL", rw["start"], rw["end"])

        exc_w = (rw["nav"] / h["nav"] - 1) * 100
        exc_w0 = (rw0["nav"] / h["nav"] - 1) * 100
        exc_m = (rm["nav"] / h["nav"] - 1) * 100
        cost_w = (rw["nav"] / rw0["nav"] - 1) * 100
        cal = lambda r: r["cagr"] / abs(r["mdd"]) if r["mdd"] < 0 else np.nan
        ddb_w = (abs(h["mdd"]) - abs(rw["mdd"])) * 100
        ddb_m = (abs(h["mdd"]) - abs(rm["mdd"])) * 100

        print(f"\n{'=' * 112}")
        print(f"### {tag}   {rw['start'].date()} ~ {rw['end'].date()}   ({rw['yrs']:.2f}y, "
              f"{len(px.loc[rw['start']:rw['end']])} 周)")
        print("=" * 112)
        print(f"  {'口径':26s}{'净值':>11s}{'CAGR':>10s}{'MDD':>10s}{'Calmar':>9s}{'换手':>9s}{'调仓':>6s}")
        print(f"  {'再平衡·每周 (10bp)':26s}{rw['nav']:>10.4f}x{rw['cagr'] * 100:>9.2f}%"
              f"{rw['mdd'] * 100:>9.2f}%{cal(rw):>9.2f}{rw['turnover_ann'] * 100:>8.0f}%"
              f"{rw['turnover_events']:>6d}")
        print(f"  {'再平衡·每周 (0bp)':26s}{rw0['nav']:>10.4f}x{rw0['cagr'] * 100:>9.2f}%"
              f"{rw0['mdd'] * 100:>9.2f}%{cal(rw0):>9.2f}")
        print(f"  {'再平衡·每月 (10bp)':26s}{rm['nav']:>10.4f}x{rm['cagr'] * 100:>9.2f}%"
              f"{rm['mdd'] * 100:>9.2f}%{cal(rm):>9.2f}{rm['turnover_ann'] * 100:>8.0f}%"
              f"{rm['turnover_events']:>6d}")
        print(f"  {'死拿 (等权,不调仓)':26s}{h['nav']:>10.4f}x{h['cagr'] * 100:>9.2f}%"
              f"{h['mdd'] * 100:>9.2f}%{cal(h):>9.2f}")
        print(f"  {'ETH 独家死拿':26s}{se['nav']:>10.4f}x{se['cagr'] * 100:>9.2f}%"
              f"{se['mdd'] * 100:>9.2f}%")
        print(f"  {'SOL 独家死拿':26s}{ss['nav']:>10.4f}x{ss['cagr'] * 100:>9.2f}%"
              f"{ss['mdd'] * 100:>9.2f}%")
        print(f"  --> 【每周】跑赢死拿 {exc_w:+.3f}%  (0bp {exc_w0:+.3f}%, 成本拖累 {cost_w:+.3f}%)")
        print(f"      【每月】跑赢死拿 {exc_m:+.3f}%   周-月 差 {exc_w - exc_m:+.3f}%")
        print(f"      筹码(死拿该组合=1, 每周): ETH {rw['units_mult']['ETH']:.4f}x  "
              f"SOL {rw['units_mult']['SOL']:.4f}x")
        print(f"      回撤改善 每周 {ddb_w:+.2f}pp / 每月 {ddb_m:+.2f}pp   "
              f"Calmar 死拿 {cal(h):.2f} -> 每周 {cal(rw):.2f}")

        rows.append(dict(
            window=tag, start=str(rw["start"].date()), end=str(rw["end"].date()),
            yrs=round(rw["yrs"], 2), weeks=len(px.loc[rw["start"]:rw["end"]]),
            nav_w=rw["nav"], nav_w0=rw0["nav"], nav_m=rm["nav"], nav_hold=h["nav"],
            nav_eth=se["nav"], nav_sol=ss["nav"],
            cagr_w=rw["cagr"] * 100, cagr_m=rm["cagr"] * 100, cagr_hold=h["cagr"] * 100,
            mdd_w=rw["mdd"] * 100, mdd_m=rm["mdd"] * 100, mdd_hold=h["mdd"] * 100,
            dd_better_w=ddb_w, dd_better_m=ddb_m,
            calmar_w=cal(rw), calmar_m=cal(rm), calmar_hold=cal(h),
            excess_w=exc_w, excess_w0=exc_w0, excess_m=exc_m, cost_w=cost_w,
            turn_w=rw["turnover_ann"] * 100, turn_m=rm["turnover_ann"] * 100,
            ev_w=rw["turnover_events"], ev_m=rm["turnover_events"],
            units_eth_w=rw["units_mult"]["ETH"], units_sol_w=rw["units_mult"]["SOL"],
            units_eth_m=rm["units_mult"]["ETH"], units_sol_m=rm["units_mult"]["SOL"]))

    # ---------- 起点敏感性 (±6 周, 1 年窗口) ----------
    print(f"\n{'=' * 112}")
    print("### 起点敏感性: 1 年窗口起点挪动 ±6 周 (每周调仓 10bp)")
    print("=" * 112)
    print(f"  {'起点':>12s}{'再平衡':>11s}{'死拿':>11s}{'跑赢':>10s}{'筹码ETH':>10s}"
          f"{'筹码SOL':>10s}{'相关':>8s}{'漂移差':>9s}")
    sens = []
    for k in range(-6, 7):
        cut = end - pd.Timedelta(days=365) + pd.Timedelta(weeks=k)
        r = bap.sim(px, COINS, rebal_weeks=WEEKLY, cost_bp=COST_BP, start=cut, end=None)
        if r is None:
            continue
        hh = bap.buyhold(px, COINS, r["start"], r["end"])
        rr = px.loc[r["start"]:r["end"], COINS].pct_change().dropna()
        se = bap.solo(px, "ETH", r["start"], r["end"])
        ss = bap.solo(px, "SOL", r["start"], r["end"])
        exc = (r["nav"] / hh["nav"] - 1) * 100
        dd = (se["cagr"] - ss["cagr"]) * 100
        print(f"  {str(r['start'].date()):>12s}{r['nav']:>10.4f}x{hh['nav']:>10.4f}x"
              f"{exc:>9.3f}%{r['units_mult']['ETH']:>10.4f}{r['units_mult']['SOL']:>10.4f}"
              f"{rr['ETH'].corr(rr['SOL']):>8.3f}{dd:>8.1f}pp")
        sens.append(dict(k=k, start=str(r["start"].date()), excess=exc,
                         corr=float(rr["ETH"].corr(rr["SOL"])), drift=dd,
                         units_eth=r["units_mult"]["ETH"], units_sol=r["units_mult"]["SOL"]))
    sd = pd.DataFrame(sens)
    print(f"\n  超额区间 {sd['excess'].min():+.3f}% ~ {sd['excess'].max():+.3f}%   "
          f"中位 {sd['excess'].median():+.3f}%   标准差 {sd['excess'].std():.3f}pp   "
          f"正超额 {int((sd['excess'] > 0).sum())}/{len(sd)}")

    # ---------- 波动率² 理论收割量 ----------
    print(f"\n{'=' * 112}")
    print("### 理论上限: 波动率² 收割量 (无成本、无削峰)")
    print("=" * 112)
    ther = []
    for tag, cut in [("1 年", end - pd.Timedelta(days=365)),
                     ("3 年", end - pd.Timedelta(days=1095)),
                     ("5 年", end - pd.Timedelta(days=1826)),
                     ("全窗口", w0_all)]:
        sub = px.loc[cut:, COINS].dropna()
        rr = sub.pct_change().dropna().values
        cov = np.cov(rr.T) * 52
        w = np.array([0.5, 0.5])
        harvest = 0.5 * (np.mean(np.diag(cov)) - float(w @ cov @ w))
        cr = cov[0, 1] / np.sqrt(cov[0, 0] * cov[1, 1])
        print(f"  {tag:6s} σ_ETH {np.sqrt(cov[0,0])*100:5.1f}%  σ_SOL {np.sqrt(cov[1,1])*100:5.1f}%  "
              f"相关 {cr:.3f}   理论收割 ≈ {harvest*100:+.2f}%/年")
        ther.append(dict(window=tag, vol_eth=np.sqrt(cov[0, 0]) * 100,
                         vol_sol=np.sqrt(cov[1, 1]) * 100, corr=float(cr), harvest=harvest * 100))

    # ---------- 相位检验: 频率效应 vs 调仓日历运气 ----------
    print(f"\n{'=' * 112}")
    print("### 🔴 相位检验: 同频率换调仓日历 (相位), 看净值分布宽度")
    print("=" * 112)
    phase_rec = []
    print(f"  {'窗口':>8s}{'频率':>6s}{'相位n':>7s}{'净值 min':>12s}{'净值 max':>12s}"
          f"{'极差':>9s}{'中位':>11s}{'每周净值':>11s}{'每周vs中位':>12s}")
    for tag, cut in windows:
        sub = px.loc[cut:, COINS].dropna()
        for freq in (1, 2, 4, 8):
            phs = 1 if freq == 1 else min(freq, 8)
            vals, sols = [], []
            for ph in range(phs):
                nav, um, tu = sim_phase(sub, freq, ph, COST_BP)
                vals.append(nav)
                sols.append(um["SOL"])
                phase_rec.append(dict(window=tag, freq=freq, phase=ph, nav=nav,
                                      units_sol=um["SOL"], units_eth=um["ETH"],
                                      turnover=tu))
            v = np.array(vals)
            med = float(np.median(v))
            wk = v[0] if freq == 1 else np.nan
            rel = f"{(wk / med - 1) * 100:+.1f}%" if freq == 1 else ""
            print(f"  {tag:>8s}{freq:>5d}周{phs:>7d}{v.min():>11.4f}x{v.max():>11.4f}x"
                  f"{(v.max() / v.min() - 1) * 100:>8.1f}%{med:>10.4f}x"
                  f"{(f'{wk:.4f}' if freq == 1 else ''):>11s}{rel:>12s}")
    phdf = pd.DataFrame(phase_rec)

    print(f"\n  {'窗口':>8s}{'月(4周)相位极差':>16s}{'8周相位极差':>14s}"
          f"{'每周 vs 月相位0':>16s}{'每周 vs 月中位':>15s}")
    for tag, _ in windows:
        d = phdf[phdf.window == tag]
        m4, m8 = d[d.freq == 4], d[d.freq == 8]
        w1 = float(d[d.freq == 1]["nav"].iloc[0])
        print(f"  {tag:>8s}{(m4.nav.max() / m4.nav.min() - 1) * 100:>15.1f}%"
              f"{(m8.nav.max() / m8.nav.min() - 1) * 100:>13.1f}%"
              f"{(w1 / float(m4[m4.phase == 0]['nav'].iloc[0]) - 1) * 100:>15.1f}%"
              f"{(w1 / m4.nav.median() - 1) * 100:>14.1f}%")
    print("  读法: 最后一列接近 0 → 每周与月度之间没有频率上的系统差异;")
    print("        第二列若与'每周vs月相位0'同量级 → 那个差异只是挑了一个有利的日历。")


    ser = {}
    for tag, cut in [("1 年", end - pd.Timedelta(days=365)),
                     ("3 年", end - pd.Timedelta(days=1095)),
                     ("5 年", end - pd.Timedelta(days=1826))]:
        r = bap.sim(px, COINS, rebal_weeks=WEEKLY, cost_bp=COST_BP, start=cut, end=None)
        m = r["nav_ser"].resample("MS").last().dropna()
        mh = r["hold_ser"].resample("MS").last().dropna().reindex(m.index)
        ser[tag] = dict(dates=[d.strftime("%Y-%m") for d in m.index],
                        rb=[round(v, 4) for v in m.values],
                        hold=[round(v, 4) for v in mh.values])
    json.dump(ser, io.open(os.path.join(OUTDIR, "eth_sol_weekly_series.json"), "w",
                           encoding="utf-8"), ensure_ascii=False)

    os.makedirs(OUTDIR, exist_ok=True)
    pd.DataFrame(rows).to_csv(os.path.join(OUTDIR, "eth_sol_pair_windows.csv"),
                              index=False, encoding="utf-8-sig")
    sd.to_csv(os.path.join(OUTDIR, "eth_sol_pair_start_sens.csv"),
              index=False, encoding="utf-8-sig")
    pd.DataFrame(ther).to_csv(os.path.join(OUTDIR, "eth_sol_pair_theory.csv"),
                              index=False, encoding="utf-8-sig")
    phdf.to_csv(os.path.join(OUTDIR, "eth_sol_phase_audit.csv"),
                index=False, encoding="utf-8-sig")
    print(f"\n[落盘] out/eth_sol_pair_windows.csv ({len(rows)} 行) / "
          f"eth_sol_pair_start_sens.csv ({len(sd)} 行) / eth_sol_pair_theory.csv ({len(ther)} 行) / "
          f"eth_sol_phase_audit.csv ({len(phdf)} 行)")


if __name__ == "__main__":
    main()
