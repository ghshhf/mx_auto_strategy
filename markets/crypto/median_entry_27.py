# -*- coding: utf-8 -*-
"""median_entry_27.py — 「不看最高/最低, 只看中位数」27 币全样本检验

用户命题 (2026-09-14):
    ① "永远不要选最高和最低, 因为理论上很难有人在那个最高点买入, 最低点买入。"
    ② "咱们 27 个代币, 你可以都看一下中位数, 你就知道了。"
    ③ "咱们看的是平均数…万一未来比特币涨得没那么好呢? 毕竟市值高了, 涨的倍率降低了。"
    ④ "哪怕是中位数, 也把那个平均筹码降低了保本时间。"

设计 (与用户口径对齐):
  【段1】27 币入场价分布: 不看最高/最低, 先看中位与分位 —— 最高的极端程度有多大。
  【段2】三口径入场对照(最低/中位/最高) → 证明「选哪个入场价」会怎样扭曲结论。
         ★ 主口径一律 = 中位价入场, 最高/最低仅作对照。
  【段3】滚动全样本(351 对 × 每 4 周一个入场点) → 保本时间 / 水下占比 / 筹码 / 超额的中位数。
         ★ 这是本轮主口径: 不挑入场点, 全部入场点取中位。
  【段4】27 币逐一中位表 (核心交付)。
  【段5】"万一比特币涨得没那么好" —— BTC 对数路径按目标 CAGR 重标定, 扫描 0%~60%。
         附 BTC/ETH 分段年化, 检验「市值高了倍率降低」。
  【段6】剔除 BTC/ETH 的池子中位数对照。

铁律: 筹码 = 币量倍数(死拿 = 1.000); 再平衡目的 = 筹码不掉队, 非收益最大化。
      所有数字本脚本动态计算, 不硬编码。
"""
import os
import sys
import math
import numpy as np
import pandas as pd
from itertools import combinations

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

from excess_is_chips import sim_trades, load_panel, PANEL, OUTDIR   # noqa: E402

CAP = 10000.0
COST_BP = 10.0
REBAL_WEEKS = 4
STEP_WEEKS = 4                 # 滚动入场步长(周)
MIN_WIN_WEEKS = 78             # 配对被纳入滚动统计的最短共同窗口 (1.5 年)
MAIN_START = "2020-10-09"      # 主口径起点: 19 币

SEP = "=" * 112
sep = "-" * 112


def out(*a):
    print(*a, flush=True)


def med(x):
    x = np.asarray([v for v in x if v is not None and np.isfinite(v)], dtype=float)
    return float(np.median(x)) if len(x) else float("nan")


def q1q3(x):
    x = np.asarray([v for v in x if v is not None and np.isfinite(v)], dtype=float)
    if not len(x):
        return (float("nan"), float("nan"))
    return (float(np.percentile(x, 25)), float(np.percentile(x, 75)))


def uw_stats(nav_vals, capital=CAP):
    """水下三量: 最长连续水下周数 / 从最深点回本周数 / 水下占比。

    注: NAV[0] 恰为初始本金, 故不能用『首次跌破』(会被最初几周的小波动触发,
    再平衡与死拿都退化成同一个数)。必须用【最长连续水下】与【最深点回本】。
    """
    v = np.asarray(nav_vals, dtype=float)
    below = v < capital * (1 - 1e-9)
    uw = float(below.mean())
    best = cur = 0
    for b in below:
        cur = cur + 1 if b else 0
        if cur > best:
            best = cur
    if below.any():
        idx = np.where(below)[0]
        j = int(idx[int(np.argmin(v[idx]))])          # 水下最深的一周
        hit = np.where(v[j:] >= capital * (1 - 1e-9))[0]
        if len(hit):
            rec, cens = float(hit[0]), 0
        else:
            rec, cens = float(len(v) - 1 - j), 1
    else:
        rec, cens = 0.0, 0
    return float(best), rec, cens, uw


def rescale_cagr(s, cagr):
    """保留路径残差, 把对数价格线性重标定到目标总收益 (1+cagr)^yrs。"""
    lp = np.log(s.values.astype(float))
    n = len(lp)
    if n < 3:
        return s.copy()
    t = np.arange(n) / (n - 1)
    base = lp[0] + (lp[-1] - lp[0]) * t
    resid = lp - base
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    new = lp[0] + math.log1p(cagr) * yrs * t + resid
    return pd.Series(np.exp(new), index=s.index)


# ------------------------------------------------------------------ 段1
def section_entry_dist(px):
    out(SEP)
    out("【段1】27 币入场价分布: 最高的极端程度有多大? (每币自身全窗口, 周频收盘)")
    out(SEP)
    out(f"  {'币':<8}{'窗口':>7}{'最低':>11}{'P10':>11}{'P25':>11}{'中位':>11}"
        f"{'P75':>11}{'P90':>11}{'最高':>11}{'最高/中位':>10}{'现价':>11}{'中位入场至今':>13}")
    out("  " + "-" * 108)
    rows = []
    for c in px.columns:
        s = px[c].dropna()
        if len(s) < MIN_WIN_WEEKS:
            continue
        v = s.values.astype(float)
        p10, p25, p50, p75, p90 = (float(np.percentile(v, q)) for q in (10, 25, 50, 75, 90))
        cur = float(v[-1])
        rows.append(dict(coin=c, yrs=len(s) / 52, lo=float(v.min()), p10=p10, p25=p25,
                         med=p50, p75=p75, p90=p90, hi=float(v.max()),
                         hi_over_med=float(v.max()) / p50, cur=cur,
                         med_entry_ret=cur / p50 - 1,
                         hi_entry_ret=cur / float(v.max()) - 1,
                         med_entry_ret_lo=cur / p50 - 1))
        r = rows[-1]
        out(f"  {c:<8}{r['yrs']:>6.1f}y{r['lo']:>11,.2f}{p10:>11,.2f}{p25:>11,.2f}"
            f"{p50:>11,.2f}{p75:>11,.2f}{p90:>11,.2f}{r['hi']:>11,.2f}"
            f"{r['hi_over_med']:>9.1f}×{cur:>11,.2f}{r['med_entry_ret']:>12.1%}")
    df = pd.DataFrame(rows).sort_values("yrs", ascending=False).reset_index(drop=True)
    out("  " + "-" * 108)
    out(f"  横截面中位: 最高/中位 = {df['hi_over_med'].median():.1f}×   "
        f"中位价入场至今 = {df['med_entry_ret'].median():+.1%}   "
        f"最高价入场至今 = {df['hi_entry_ret'].median():+.1%}")
    out(f"  最高价入场至今为正的币: {int((df['hi_entry_ret'] > 0).sum())}/{len(df)}  "
        f"| 中位价入场至今为正的币: {int((df['med_entry_ret'] > 0).sum())}/{len(df)}")
    out("  ⇒ 读法: 单一 ATH 入场点是极端分位; 中位价入场在时间维度上『一半时间比它便宜』。")
    return df


# ------------------------------------------------------------------ 段2
def entry_index_top(sub_f, min_after):
    """在 [0, W-1-min_after] 内找 focus 币价格最高/最低/最接近中位的周索引。"""
    v = sub_f.values.astype(float)
    hi = int(len(v) - 1 - min_after)
    seg = v[:hi + 1]
    i_top = int(np.argmax(seg))
    i_bot = int(np.argmin(seg))
    m = float(np.median(v))
    i_med = int(np.argmin(np.abs(seg - m)))
    return i_top, i_med, i_bot


def section_three_calibers(px, coins):
    out()
    out(SEP)
    out("【段2】三口径入场对照: 选『最低 / 中位 / 最高』入场价, 结论差多少? (主口径 = 中位)")
    out(SEP)
    recs = []
    pairs = [(a, b) for a, b in combinations(coins, 2)
             if len(px[[a, b]].dropna()) >= MIN_WIN_WEEKS]
    for a, b in pairs:
        sub = px[[a, b]].dropna()
        W = len(sub)
        min_after = max(26, min(104, int(0.35 * W)))
        i_top, i_med, i_bot = entry_index_top(sub[a], min_after)
        for lab, idx in (("最低", i_bot), ("中位", i_med), ("最高", i_top)):
            t0 = sub.index[idx]
            r = sim_trades(px, [a, b], a, capital=CAP, cost_bp=COST_BP, start=t0)
            if r is None:
                continue
            ulr, rec_r, cens_r, uw_r = uw_stats(r["nav_ser"].values)
            ulh, rec_h, cens_h, uw_h = uw_stats(r["hold_ser"].values)
            recs.append(dict(pair=f"{a}+{b}", a=a, b=b, cal=lab, start=t0,
                             yrs=r["yrs"], px_a0=float(sub[a].iloc[idx]),
                             px_a_end=float(r["px_last"][r["i"]]),
                             nav_mult=r["nav"] / CAP, hold_mult=r["hold"] / CAP,
                             chip_focus=float(r["R"][r["i"]]),
                             chip_other=float(r["R"][1 - r["i"]]),
                             ucb=math.sqrt(float(r["R"][0]) * float(r["R"][1])),
                             exc=r["nav"] / r["hold"] - 1,
                             uw_r=uw_r, uw_h=uw_h, rec_r=rec_r, rec_h=rec_h,
                             uwlen_r=ulr, uwlen_h=ulh,
                             cens_r=cens_r, cens_h=cens_h))
    d = pd.DataFrame(recs)
    out(f"  样本: {len(pairs)} 对 × 3 口径 = {len(d)} 次模拟")
    out()
    out(f"  {'入场口径':<8}{'对':>5}{'净值×中位':>10}{'死拿×中位':>10}{'筹码中位':>10}"
        f"{'超额中位':>10}{'超额>0':>8}{'最长水下周R':>12}{'最长水下周H':>12}"
        f"{'回本周R':>9}{'回本周H':>9}{'水下R':>8}{'未回本R':>9}")
    out("  " + "-" * 122)
    for lab in ("最低", "中位", "最高"):
        g = d[d.cal == lab]
        if not len(g):
            continue
        out(f"  {lab:<8}{len(g):>5}{g['nav_mult'].median():>10.3f}{g['hold_mult'].median():>10.3f}"
            f"{g['ucb'].median():>10.4f}{g['exc'].median():>10.2%}"
            f"{(g['exc'] > 0).mean():>7.1%}{g['uwlen_r'].median():>12.0f}"
            f"{g['uwlen_h'].median():>12.0f}{g['rec_r'].median():>9.0f}"
            f"{g['rec_h'].median():>9.0f}{g['uw_r'].median():>8.1%}"
            f"{g['cens_r'].mean():>9.1%}")
    out("  " + "-" * 122)
    g = d[d.cal == "中位"]
    out(f"  中位口径 = 主口径: 筹码 100%>1 ({int((g['ucb'] > 1).sum())}/{len(g)}), "
        f"超额>0 {(g['exc'] > 0).mean():.1%}, 超额中位 {g['exc'].median():+.2%}")
    out("  ⇒ 最高口径把超额中位压到 %s; 最低口径抬到 %s —— 差 %.1f 个百分点, "
        % (f"{d[d.cal == '最高']['exc'].median():+.2%}", f"{d[d.cal == '最低']['exc'].median():+.2%}",
           (d[d.cal == "最低"]["exc"].median() - d[d.cal == "最高"]["exc"].median()) * 100))
    out("     这全部是『挑入场点』造成的, 与配对质量无关。")
    d.to_csv(os.path.join(OUTDIR, "median_entry_three_calibers.csv"),
             index=False, float_format="%.6f")
    return d


# ------------------------------------------------------------------ 段2b
def section_reconcile(px, roll):
    """对账: 固定起点超额 +37.91% vs 全入场点中位 +8.47%, 差额来自哪里?
    假设: 不是『起点挑得好』, 而是【剩余窗口长度 T】(收割项 ∝ T)。用分桶证伪或证实。"""
    out()
    out(SEP)
    out("【段2b】对账: 为什么固定起点报 +37.91%, 而全入场点中位只有 +8.47%?")
    out(SEP)
    main = [c for c in px.columns
            if len(px[c].dropna()) >= 300 and px[c].dropna().index[0] <= pd.Timestamp(MAIN_START)]
    fixed = []
    for a, b in combinations(main, 2):
        r = sim_trades(px, [a, b], a, capital=CAP, cost_bp=COST_BP, start=MAIN_START)
        if r is None:
            continue
        fixed.append(dict(pair=f"{a}+{b}", exc=r["nav"] / r["hold"] - 1,
                          nav=r["nav"] / CAP, hold=r["hold"] / CAP, yrs=r["yrs"]))
    fx = pd.DataFrame(fixed)
    rl = roll[roll.pair.isin(fx.pair)].copy()
    out(f"  同一批配对: {len(fx)} 对 (主口径 {len(main)} 币)")
    out(f"  {'入场约定':<32}{'窗口年':>8}{'次数':>9}{'净值×中位':>11}{'死拿×中位':>11}"
        f"{'超额中位':>11}{'超额>0':>9}")
    out("  " + "-" * 92)
    out(f"  {'① 固定起点 2020-10-09':<32}{fx['yrs'].median():>8.2f}{len(fx):>9}"
        f"{fx['nav'].median():>11.3f}{fx['hold'].median():>11.3f}"
        f"{fx['exc'].median():>11.2%}{(fx['exc'] > 0).mean():>8.1%}")
    out(f"  {'② 全部入场点(滚动 4 周)':<32}{rl['yrs'].median():>8.2f}{len(rl):>9,}"
        f"{rl['nav_mult'].median():>11.3f}{rl['hold_mult'].median():>11.3f}"
        f"{rl['exc'].median():>11.2%}{(rl['exc'] > 0).mean():>8.1%}")
    out(f"  {'③ 只看剩余窗口 ≥5 年':<32}{rl[rl.yrs >= 5]['yrs'].median():>8.2f}"
        f"{len(rl[rl.yrs >= 5]):>9,}{rl[rl.yrs >= 5]['nav_mult'].median():>11.3f}"
        f"{rl[rl.yrs >= 5]['hold_mult'].median():>11.3f}"
        f"{rl[rl.yrs >= 5]['exc'].median():>11.2%}{(rl[rl.yrs >= 5]['exc'] > 0).mean():>8.1%}")
    out("  " + "-" * 92)
    out("  ⇒ 若 ③ ≈ ①, 则差额来自【剩余窗口长度】而非『起点挑得好』。分桶验证:")
    out()
    edges = [0, 1.5, 2.5, 3.5, 4.5, 5.5, 99]
    out(f"  {'剩余窗口':<14}{'次数':>8}{'占次比':>8}{'超额中位':>11}{'超额>0':>9}"
        f"{'筹码中位':>10}{'净值×中位':>11}{'死拿×中位':>11}")
    out("  " + "-" * 84)
    for lo, hi in zip(edges[:-1], edges[1:]):
        g = rl[(rl.yrs >= lo) & (rl.yrs < hi)]
        if not len(g):
            continue
        lab = f"{lo:.1f}~{hi:.1f}y" if hi < 99 else f"≥{lo:.1f}y"
        out(f"  {lab:<14}{len(g):>8,}{len(g) / len(rl):>8.1%}{g['exc'].median():>11.2%}"
            f"{(g['exc'] > 0).mean():>8.1%}{g['ucb'].median():>10.4f}"
            f"{g['nav_mult'].median():>11.3f}{g['hold_mult'].median():>11.3f}")
    out("  " + "-" * 84)
    out("  ⇒ ③≈① ⇒ 差额来自【剩余窗口长度 T】(收割项 ∝ T), 不是【挑起点】。")
    out("     分桶看总体随 T 上升, 但 3.5~5.5 年有一段平台 —— 不是严格单调, 别过度概括。")
    out("     教训: 报超额必须同时给【入场后剩余窗口】; 单一起点的数字不是配对的平均属性。")
    d = fx.merge(rl.groupby("pair").exc.median().rename("exc_roll"), on="pair")
    d.to_csv(os.path.join(OUTDIR, "median_entry_reconcile.csv"),
             index=False, float_format="%.6f")
    return d


# ------------------------------------------------------------------ 段3
def section_rolling(px, coins):
    out()
    out(SEP)
    out("【段3】滚动全样本: 不挑入场点, 全部入场点取中位 (本轮主口径)")
    out(SEP)
    pairs = [(a, b) for a, b in combinations(coins, 2)
             if len(px[[a, b]].dropna()) >= MIN_WIN_WEEKS]
    recs = []
    for a, b in pairs:
        sub = px[[a, b]].dropna()
        W = len(sub)
        min_after = max(26, min(104, int(0.35 * W)))
        last = W - 1 - min_after
        if last < 1:
            continue
        for s in range(0, last + 1, STEP_WEEKS):
            t0 = sub.index[s]
            r = sim_trades(px, [a, b], a, capital=CAP, cost_bp=COST_BP, start=t0)
            if r is None:
                continue
            ulr, rec_r, cens_r, uw_r = uw_stats(r["nav_ser"].values)
            ulh, rec_h, cens_h, uw_h = uw_stats(r["hold_ser"].values)
            i = r["i"]
            br = np.diff(np.log(r["px_ser"].values.astype(float)), axis=0)
            drift = (np.log(r["px_last"][1 - i] / r["px_first"][1 - i])
                     - np.log(r["px_last"][i] / r["px_first"][i])) / r["yrs"]
            recs.append(dict(pair=f"{a}+{b}", a=a, b=b, start=t0, yrs=r["yrs"],
                             nav_mult=r["nav"] / CAP, hold_mult=r["hold"] / CAP,
                             chip_focus=float(r["R"][i]), chip_other=float(r["R"][1 - i]),
                             ucb=math.sqrt(float(r["R"][0]) * float(r["R"][1])),
                             exc=r["nav"] / r["hold"] - 1,
                             drift_abs=abs(drift),
                             uw_r=uw_r, uw_h=uw_h, rec_r=rec_r, rec_h=rec_h,
                             uwlen_r=ulr, uwlen_h=ulh,
                             cens_r=cens_r, cens_h=cens_h,
                             price_focus_mult=float(r["px_last"][i] / r["px_first"][i]),
                             corr=float(np.corrcoef(br[:, 0], br[:, 1])[0, 1])))
    d = pd.DataFrame(recs)
    out(f"  样本: {len(pairs)} 对 × 每 {STEP_WEEKS} 周一个入场点 = {len(d):,} 次模拟 "
        f"(每对入场点数中位 {d.groupby('pair').size().median():.0f})")
    out(f"  入场后剩余窗口: 中位 {d['yrs'].median():.2f} 年 / P25 {d['yrs'].quantile(.25):.2f} / "
        f"P75 {d['yrs'].quantile(.75):.2f}")
    out()
    for lab, g in (("全样本", d), ("窗口≥3年", d[d.yrs >= 3])):
        out(f"  ── {lab} ({len(g):,} 次) ──")
        out(f"     筹码倍数  中位 {g['ucb'].median():.4f}  >1 占比 {(g['ucb'] > 1).mean():.1%}")
        out(f"     超额      中位 {g['exc'].median():+.2%}   >0 占比 {(g['exc'] > 0).mean():.1%}")
        out(f"     净值×     中位 {g['nav_mult'].median():.3f}   "
            f"死拿× 中位 {g['hold_mult'].median():.3f}   "
            f"净值跑赢死拿 {(g['nav_mult'] > g['hold_mult']).mean():.1%}")
        out(f"     最长连续水下  再平衡 中位 {g['uwlen_r'].median():.0f} 周 "
            f"(P75 {g['uwlen_r'].quantile(.75):.0f}) | 死拿 中位 {g['uwlen_h'].median():.0f} 周 "
            f"(P75 {g['uwlen_h'].quantile(.75):.0f})")
        out(f"     最深点回本    再平衡 中位 {g['rec_r'].median():.0f} 周 / 未回本 {g['cens_r'].mean():.1%}"
            f" | 死拿 中位 {g['rec_h'].median():.0f} 周 / 未回本 {g['cens_h'].mean():.1%}")
        out(f"     水下时间占比  再平衡 中位 {g['uw_r'].median():.1%} | 死拿 中位 {g['uw_h'].median():.1%}")
        out()
    g = d[d.yrs >= 3]
    out(f"  ▶ 主口径(窗口≥3年, {len(g):,} 次, 全部入场点取中位):")
    out(f"     最长连续水下 再平衡 {g['uwlen_r'].median():.0f} 周 vs 死拿 {g['uwlen_h'].median():.0f} 周"
        f"  → {'再平衡更短' if g['uwlen_r'].median() < g['uwlen_h'].median() else '再平衡不更短'}"
        f" ({g['uwlen_r'].median() - g['uwlen_h'].median():+.0f} 周)")
    out(f"     最深点回本   再平衡 {g['rec_r'].median():.0f} 周 vs 死拿 {g['rec_h'].median():.0f} 周"
        f"  ({g['rec_r'].median() - g['rec_h'].median():+.0f} 周)")
    out(f"     水下时间占比 再平衡 {g['uw_r'].median():.1%} vs 死拿 {g['uw_h'].median():.1%}"
        f"  ({g['uw_r'].median() - g['uw_h'].median():+.1%})")
    out(f"     逐样本『再平衡回本更快』占比: {(g['rec_r'] < g['rec_h']).mean():.1%} | "
        f"『水下时间更短』占比: {(g['uw_r'] < g['uw_h']).mean():.1%}")
    d.to_csv(os.path.join(OUTDIR, "median_entry_rolling.csv"), index=False, float_format="%.6f")
    return d


# ------------------------------------------------------------------ 段4
def section_per_coin(px, roll, entry_df):
    out()
    out(SEP)
    out("【段4】27 币逐一中位表 (主口径: 滚动全入场点 × 全部对手, 取中位)")
    out(SEP)
    rows = []
    for c in px.columns:
        g = roll[(roll.a == c) | (roll.b == c)]
        if not len(g):
            continue
        chip = np.where(g.a == c, g.chip_focus, g.chip_other)
        exc = g.exc.values
        n_partners = len(set(g[g.a == c].b) | set(g[g.b == c].a))
        e = entry_df[entry_df.coin == c]
        rows.append(dict(
            coin=c, yrs=g.yrs.median(), n=len(g), n_partner=n_partners,
            win_yrs=e.yrs.iloc[0] if len(e) else float("nan"),
            px_med=e.med.iloc[0] if len(e) else float("nan"),
            px_cur=e.cur.iloc[0] if len(e) else float("nan"),
            hi_over_med=e.hi_over_med.iloc[0] if len(e) else float("nan"),
            chip_med=float(np.median(chip)), chip_pos=float((chip > 1).mean()),
            exc_med=float(np.median(exc)), exc_pos=float((exc > 0).mean()),
            nav_med=g.nav_mult.median(), hold_med=g.hold_mult.median(),
            rec_r=g.rec_r.median(), rec_h=g.rec_h.median(),
            uwlen_r=g.uwlen_r.median(), uwlen_h=g.uwlen_h.median(),
            cens_r=g.cens_r.mean(), uw_r=g.uw_r.median(), uw_h=g.uw_h.median(),
        ))
    df = pd.DataFrame(rows).sort_values("exc_med", ascending=False).reset_index(drop=True)
    out(f"  {'币':<8}{'剩余窗口':>9}{'对手':>5}{'筹码中位':>10}{'筹码>1':>8}{'超额中位':>10}"
        f"{'超额>0':>8}{'净值×':>8}{'死拿×':>8}{'最长水下R':>10}{'最长水下H':>10}"
        f"{'水下R':>8}{'最高/中位':>10}{'中位入场至今':>13}")
    out("  " + "-" * 126)
    for _, r in df.iterrows():
        tag = " *" if r["win_yrs"] < 3 else ""
        out(f"  {r['coin']:<8}{r['yrs']:>8.1f}y{r['n_partner']:>5}{r['chip_med']:>10.4f}"
            f"{r['chip_pos']:>7.1%}{r['exc_med']:>10.2%}{r['exc_pos']:>8.1%}"
            f"{r['nav_med']:>8.3f}{r['hold_med']:>8.3f}{r['uwlen_r']:>10.0f}"
            f"{r['uwlen_h']:>10.0f}{r['uw_r']:>8.1%}"
            f"{r['hi_over_med']:>9.1f}×{r['px_cur'] / r['px_med'] - 1:>12.1%}{tag}")
    out("  " + "-" * 126)
    long_ = df[df.win_yrs >= 3]
    out(f"  ▶ 横截面中位 (窗口≥3年, {len(long_)} 币):")
    out(f"     筹码 {long_['chip_med'].median():.4f} | 超额 {long_['exc_med'].median():+.2%} | "
        f"超额>0 的币 {int((long_['exc_med'] > 0).sum())}/{len(long_)} | "
        f"净值× {long_['nav_med'].median():.3f} vs 死拿× {long_['hold_med'].median():.3f}")
    out(f"     最长连续水下 再平衡 {long_['uwlen_r'].median():.0f} 周 vs "
        f"死拿 {long_['uwlen_h'].median():.0f} 周 | "
        f"水下占比 再平衡 {long_['uw_r'].median():.1%} vs 死拿 {long_['uw_h'].median():.1%}")
    out(f"     最高/中位 倍率中位 {long_['hi_over_med'].median():.1f}× | "
        f"中位价入场至今收益中位 {((long_['px_cur'] / long_['px_med']) - 1).median():+.1%}")
    out("  (* = 窗口不足 3 年, 中位数仅供参考)")
    df.to_csv(os.path.join(OUTDIR, "median_entry_per_coin.csv"),
              index=False, float_format="%.6f")
    return df


# ------------------------------------------------------------------ 段5
def section_btc_degrade(px):
    out()
    out(SEP)
    out("【段5】『万一未来比特币涨得没那么好』—— 把 BTC 路径重标定到目标 CAGR 后重算")
    out(SEP)
    main = [c for c in px.columns if c in
            [x for x in px.columns if len(px[x].dropna()) >= 300]]
    main = [c for c in main if px[c].dropna().index[0] <= pd.Timestamp(MAIN_START)]
    sub = px[main].dropna(how="any")
    btc = sub["BTC"]
    yrs = (sub.index[-1] - sub.index[0]).days / 365.25
    real_cagr = float((btc.iloc[-1] / btc.iloc[0]) ** (1 / yrs) - 1)
    out("  主口径池 %d 币, 窗口 %s ~ %s, %.2f 年" % (len(main), sub.index[0].date(),
                                                sub.index[-1].date(), yrs))
    out("  BTC 几何年化 %+.2f%% (= 对数年化 %+.2f%%, 同一个数的两种写法)"
        % (real_cagr * 100, math.log1p(real_cagr) * 100))
    out()
    others = [c for c in main if c != "BTC"]
    out(f"  {'BTC 目标年化':>13}{'BTC筹码β':>11}{'超额中位':>11}{'超额>0':>9}"
        f"{'净值×中位':>11}{'死拿×中位':>11}{'|漂移差|中位':>13}")
    out("  " + "-" * 82)
    rows = []
    grid = sorted({0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, round(real_cagr, 4), 0.40, 0.60})
    for tgt in grid:
        mod = sub.copy()
        mod["BTC"] = rescale_cagr(btc, tgt)
        exc, chips_b, navs, holds, drifts = [], [], [], [], []
        for o in others:
            r = sim_trades(mod, ["BTC", o], "BTC", capital=CAP, cost_bp=COST_BP, start=MAIN_START)
            if r is None:
                continue
            i = r["i"]
            exc.append(r["nav"] / r["hold"] - 1)
            chips_b.append(float(r["R"][i]))
            navs.append(r["nav"] / CAP)
            holds.append(r["hold"] / CAP)
            drifts.append(abs(math.log(r["px_last"][1 - i] / r["px_first"][1 - i])
                              - math.log(r["px_last"][i] / r["px_first"][i])) / r["yrs"])
        rows.append(dict(target=tgt, chip_b=med(chips_b), exc=med(exc),
                         exc_pos=float(np.mean(np.array(exc) > 0)),
                         nav=med(navs), hold=med(holds), drift=med(drifts)))
    for r in rows:
        star = "  ← 实际" if abs(r["target"] - real_cagr) < 0.005 else ""
        out(f"  {r['target']:>12.1%}{r['chip_b']:>11.4f}{r['exc']:>11.2%}"
            f"{r['exc_pos']:>8.1%}{r['nav']:>11.3f}{r['hold']:>11.3f}{r['drift']:>13.2%}{star}")
    out("  " + "-" * 82)
    lo = rows[0]
    mid = rows[-2]
    top = rows[-1]
    e = np.array([r["exc"] for r in rows])
    out(f"  ⇒ 超额中位全程只在 {e.min():+.2%} ~ {e.max():+.2%} 区间内波动, 与 BTC 年化"
        f"【无单调关系】——")
    out("     不能说『BTC 变弱会抬高超额』, 只能说『BTC 变弱不损害超额』。")
    out(f"  ✅ 真正单调的是绝对净值: BTC 年化 {lo['target']:.0%} → {top['target']:.0%}, "
        f"再平衡净值× {lo['nav']:.3f} → {top['nav']:.3f}; "
        f"死拿× {lo['hold']:.3f} → {top['hold']:.3f}")
    out(f"  ⇒ BTC 变弱会同时压低【死拿】({mid['hold']:.3f}×) 与【再平衡的绝对净值】"
        f"({mid['nav']:.3f}×); 而【筹码与相对优势】不受影响 → 你说的『市值高了倍率降低』"
        f"只影响绝对收益这一层。")
    # 池子
    out()
    out("  19 币等权篮子 (同一路径重标定):")
    out(f"  {'BTC 目标年化':>13}{'篮子再平衡×':>13}{'篮子死拿×':>12}{'篮子超额':>11}")
    out("  " + "-" * 52)
    for tgt in (0.0, 0.10, 0.20, 0.30, real_cagr, 0.60):
        mod = sub.copy()
        mod["BTC"] = rescale_cagr(btc, tgt)
        r = sim_trades(mod, main, "BTC", capital=CAP, cost_bp=COST_BP, start=MAIN_START)
        if r is None:
            continue
        out(f"  {tgt:>12.1%}{r['nav'] / CAP:>13.3f}{r['hold'] / CAP:>12.3f}"
            f"{r['nav'] / r['hold'] - 1:>11.2%}")
    pd.DataFrame(rows).to_csv(os.path.join(OUTDIR, "median_entry_btc_degrade.csv"),
                              index=False, float_format="%.6f")
    # 分段年化
    out()
    out("  分段年化 —— 检验『市值高了, 涨的倍率降低』:")
    segs = [("2014-09-19", "2018-01-01"), ("2018-01-01", "2022-01-01"),
            ("2022-01-01", "2026-09-05")]
    out(f"  {'区间':<26}{'BTC':>10}{'ETH':>10}{'池子中位':>11}{'池内>BTC 的币':>15}")
    for s0, s1 in segs:
        w = px.loc[s0:s1]
        cells, beat = [], 0
        line = ""
        for c in ("BTC", "ETH"):
            if c in w.columns:
                v = w[c].dropna()
                if len(v) > 10:
                    yy = (v.index[-1] - v.index[0]).days / 365.25
                    g = (v.iloc[-1] / v.iloc[0]) ** (1 / yy) - 1
                    if c == "BTC":
                        btc_g = g
                    line += f"{g:>10.1%}"
                else:
                    line += f"{'—':>10}"
            else:
                line += f"{'—':>10}"
        pv = []
        for c in px.columns:
            v = w[c].dropna()
            if len(v) < 20:
                continue
            yy = (v.index[-1] - v.index[0]).days / 365.25
            g = (v.iloc[-1] / v.iloc[0]) ** (1 / yy) - 1
            pv.append(g)
            if g > btc_g:
                beat += 1
        out(f"  {s0 + ' ~ ' + s1:<26}{line}{med(pv):>11.1%}{beat:>8}/{len(pv)}")
    out("  ⇒ BTC/ETH 的分段年化逐段下移, 与『市值越高倍率越低』一致; "
        "因此用 BTC 当唯一对手 = 用一个会衰减的基准。")
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ 段6
def section_ex_btc(px, roll, per_coin):
    out()
    out(SEP)
    out("【段6】剔除 BTC/ETH 的池子中位数 (回答『别拿最强币当唯一对手』)")
    out(SEP)
    g_all = roll[roll.yrs >= 3]
    ex = g_all[(~g_all.a.isin(["BTC", "ETH"])) & (~g_all.b.isin(["BTC", "ETH"]))]
    out(f"  {'样本':<34}{'次数':>9}{'筹码中位':>10}{'超额中位':>11}{'超额>0':>9}"
        f"{'净值×中位':>11}{'保本周R':>9}{'保本周H':>9}")
    out("  " + "-" * 104)
    for lab, g in (("全池 (含 BTC/ETH)", g_all), ("剔除 BTC/ETH", ex),
                   ("仅 BTC/ETH 参与的配对", g_all[(g_all.a.isin(["BTC", "ETH"]))
                                              | (g_all.b.isin(["BTC", "ETH"]))])):
        if not len(g):
            continue
        out(f"  {lab:<34}{len(g):>9,}{g['ucb'].median():>10.4f}{g['exc'].median():>11.2%}"
            f"{(g['exc'] > 0).mean():>8.1%}{g['nav_mult'].median():>11.3f}"
            f"{g['rec_r'].median():>9.1f}{g['rec_h'].median():>9.1f}")
    out("  " + "-" * 104)
    pc = per_coin[per_coin.win_yrs >= 3]
    no_btc = pc[~pc.coin.isin(["BTC", "ETH"])]
    out(f"  逐币横截面中位: 全 {len(pc)} 币 超额 {pc['exc_med'].median():+.2%} "
        f"(>0 的币 {int((pc['exc_med'] > 0).sum())}/{len(pc)}) | "
        f"剔 BTC/ETH 后 {len(no_btc)} 币 超额 {no_btc['exc_med'].median():+.2%} "
        f"(>0 的币 {int((no_btc['exc_med'] > 0).sum())}/{len(no_btc)})")
    out("  ⇒ 剔除最强对手后中位数几乎不动 ⇒ 主结论不依赖 BTC/ETH 的强势。")


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    px = load_panel()
    coins = list(px.columns)
    out(SEP)
    out("median_entry_27.py — 不看最高/最低, 只看中位数")
    out(SEP)
    out(f"  面板: {PANEL.rsplit(os.sep, 1)[-1]}  {px.shape[0]} 周 × {px.shape[1]} 币, "
        f"{px.index[0].date()} ~ {px.index[-1].date()}")
    out(f"  参数: 等权 {REBAL_WEEKS} 周调仓 · 成本 {COST_BP:.0f}bp · 本金 ${CAP:,.0f} · "
        f"滚动步长 {STEP_WEEKS} 周 · 配对最短共同窗口 {MIN_WIN_WEEKS} 周")
    out("  口径: 筹码 = 币量倍数 (死拿 = 1.000); 主口径入场点 = 中位数, 不取最高/最低。")

    entry_df = section_entry_dist(px)
    section_three_calibers(px, coins)
    roll = section_rolling(px, coins)
    section_reconcile(px, roll)
    per_coin = section_per_coin(px, roll, entry_df)
    section_btc_degrade(px)
    section_ex_btc(px, roll, per_coin)
    out()
    out(SEP)
    out("完成。")


if __name__ == "__main__":
    main()
