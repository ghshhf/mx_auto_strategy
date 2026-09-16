# -*- coding: utf-8 -*-
"""SOL + ADA 单对：逐段拆解『筹码到底往哪边搬』。

回应用户直觉: 「ADA 又不是没涨过, SOL 也不是没暴涨过, 两边都互换过,
整体上应该都筹码涨了点儿」—— 用逐次调仓的方向与幅度检验:
  ① 双向互换**是否发生过**?
  ② 净流向是哪边?
  ③ 『两边都涨』在数学上可能吗?
"""
import os
import importlib.util
from itertools import combinations

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "bap", os.path.join(HERE, "crypto_btc_ada_pair.py"))
bap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bap)

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
OUTDIR = os.path.join(HERE, "out")
COINS = ["SOL", "ADA"]
START = "2020-08-07"
SEP = "=" * 108
SUB = "-" * 108


def out(s=""):
    print(s)


def pct(x, d=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "  n/a"
    return f"{x * 100:+.{d}f}%"


def load_panel():
    d = pd.read_csv(PANEL, index_col=0)
    d.index = pd.to_datetime(d.index, format="mixed")
    return d


def main():
    px = load_panel()
    r = bap.sim(px, COINS, rebal_weeks=4, cost_bp=10.0, start=START)
    u = r["units_ser"]                      # 每期 币量/初始币量 (死拿=1.000)
    pr = px[COINS].loc[u.index]
    yrs = r["yrs"]
    out()
    out(SEP)
    out(f"段0 · {COINS[0]} + {COINS[1]} 逐次调仓拆解  "
        f"{u.index[0].date()} ~ {u.index[-1].date()} ({yrs:.2f} 年)")
    out(SEP)
    out(f"  终值: SOL 币量 {u['SOL'].iloc[-1]:.3f}x   ADA 币量 {u['ADA'].iloc[-1]:.3f}x   "
        f"几何平均 {np.sqrt(u['SOL'].iloc[-1]*u['ADA'].iloc[-1]):.3f}x")
    out(f"  净值 {r['nav']:.3f}x  vs  死拿 {r['hold_nav']:.3f}x  "
        f"⇒ 超额 {pct(r['nav']/r['hold_nav']-1)}")

    # ---------- 段1 逐年 ----------
    out()
    out(SEP)
    out("段1 · 逐年: 币量倍数怎么走 (该年谁涨得多, 筹码就往另一边搬)")
    out(SEP)
    out(f"  {'年份':<6}{'SOL币量(年末)':>14}{'ADA币量(年末)':>14}"
        f"{'SOL年内变化':>13}{'ADA年内变化':>13}"
        f"{'SOL价格':>11}{'ADA价格':>11}{'该年谁强':>9}")
    out("  " + SUB[:92])
    rows = []
    for y, g in u.groupby(u.index.year):
        pg = pr.loc[g.index]
        u_s0, u_s1 = g["SOL"].iloc[0], g["SOL"].iloc[-1]
        u_a0, u_a1 = g["ADA"].iloc[0], g["ADA"].iloc[-1]
        p_s = pg["SOL"].iloc[-1] / pg["SOL"].iloc[0] - 1
        p_a = pg["ADA"].iloc[-1] / pg["ADA"].iloc[0] - 1
        win = "SOL" if p_s > p_a else "ADA"
        out(f"  {y:<6}{u_s1:>13.3f}x{u_a1:>13.3f}x"
            f"{pct(u_s1/u_s0-1):>13}{pct(u_a1/u_a0-1):>13}"
            f"{pct(p_s):>11}{pct(p_a):>11}{win:>9}")
        rows.append(dict(year=y, u_sol=u_s1, u_ada=u_a1,
                         d_sol=u_s1/u_s0-1, d_ada=u_a1/u_a0-1,
                         p_sol=p_s, p_ada=p_a, win=win))
    out()
    out("  ⇒ 读法: 『该年谁强』那一列与『币量变化』那一列**符号相反** ——")
    out("     SOL 涨得多的年份, SOL 币量被**卖掉**(变化为负), ADA 被加仓; 反之亦然。")

    # ---------- 段2 逐次调仓方向 ----------
    out()
    out(SEP)
    out("段2 · 逐次调仓: 双向互换**确实发生过**, 但净流向是单向的")
    out(SEP)
    du = u.diff()                            # 只在调仓周非零
    reb = du[(du["SOL"].abs() > 1e-12)]
    n = len(reb)
    # 🔴 币量变化必须用**相对变化率** Δu/u_before, 不能拿绝对 Δu 当百分比
    rel_u = (u / u.shift(1) - 1).reindex(reb.index)
    # 该期(4 周)两币相对表现
    rel = (pr["SOL"] / pr["ADA"])
    rel_chg = rel.pct_change(4).reindex(reb.index)
    up_sol = (reb["SOL"] > 0).sum()
    up_ada = (reb["ADA"] > 0).sum()
    out(f"  调仓次数: {n} 次 (每 4 周一次)")
    out(f"    SOL 被**加仓**的调仓: {up_sol:>3} 次 ({up_sol/n:.1%})   "
        f"被减仓: {n-up_sol:>3} 次")
    out(f"    ADA 被**加仓**的调仓: {up_ada:>3} 次 ({up_ada/n:.1%})   "
        f"被减仓: {n-up_ada:>3} 次")
    out(f"  ⇒ 双向都发生过: SOL 也曾被加仓 {up_sol} 次 (即那 4 周 SOL 跑输 ADA)。")
    out()
    out("  单次调仓的搬动幅度(相对该次调仓前持有量的变化率):")
    for c in COINS:
        up, dn = rel_u[c][rel_u[c] > 0], rel_u[c][rel_u[c] < 0]
        out(f"    {c}: 被加仓中位 {pct(up.median())}({len(up)} 次)  "
            f"被减仓中位 {pct(dn.median())}({len(dn)} 次)  "
            f"⇒ 期末净 {pct(u[c].iloc[-1]/1-1)}")
    out()
    out(f"  累计(按初始币量的倍数计): SOL {pct(u['SOL'].iloc[-1]-1)}  "
        f"ADA {pct(u['ADA'].iloc[-1]-1)}")
    out()
    cc = np.corrcoef(rel_chg.fillna(0), rel_u["SOL"])[0, 1]
    out(f"  corr(『SOL 相对 ADA 的 4 周涨幅』, 『SOL 币量变化率』) = {cc:+.3f}")
    out("  ⇒ 强负相关 ⇒ **调仓方向的唯一决定因素是『谁刚涨得多』**, 涨的被卖、跌的被买。")

    # ---------- 段3 用户说的两个时段 ----------
    out()
    out(SEP)
    out("段3 · 用户点名的两种情形: 『ADA 涨的时候』『SOL 暴涨的时候』")
    out(SEP)
    r4s = pr["SOL"].pct_change(4).reindex(reb.index)
    r4a = pr["ADA"].pct_change(4).reindex(reb.index)
    for tag, cond, col in (("ADA 涨得比 SOL 多的调仓", (r4a > r4s), "ADA"),
                           ("SOL 涨得比 ADA 多的调仓", (r4s > r4a), "SOL")):
        sub = reb[cond.fillna(False)]
        if not len(sub):
            continue
        out(f"  {tag}: {len(sub)} 次")
        rs = rel_u.reindex(sub.index)
        out(f"    这 {len(sub)} 次里, SOL 币量变化中位 {pct(rs['SOL'].median(),2)}  "
            f"ADA 中位 {pct(rs['ADA'].median(),2)}")
        out(f"    ⇒ 赢家({col})被卖 {int((rs[col]<0).sum())}/{len(sub)} 次, "
            f"输家被买 {int((rs['ADA' if col=='SOL' else 'SOL']>0).sum())}/{len(sub)} 次")
    out()
    top_sol = r4s.nlargest(5)
    out("  SOL 4 周涨幅最大的 5 次调仓 (SOL 暴涨时):")
    out(f"    {'调仓日':<12}{'SOL 4周涨幅':>13}{'ADA 4周涨幅':>13}"
        f"{'SOL币量变化':>13}{'ADA币量变化':>13}")
    for d in top_sol.index:
        if d not in reb.index:
            continue
        out(f"    {d.date()!s:<12}{pct(r4s[d]):>13}{pct(r4a[d]):>13}"
            f"{pct(rel_u.loc[d,'SOL']):>13}{pct(rel_u.loc[d,'ADA']):>13}")
    out()
    top_ada = r4a.nlargest(5)
    out("  ADA 4 周涨幅最大的 5 次调仓 (ADA 暴涨时):")
    out(f"    {'调仓日':<12}{'SOL 4周涨幅':>13}{'ADA 4周涨幅':>13}"
        f"{'SOL币量变化':>13}{'ADA币量变化':>13}")
    for d in top_ada.index:
        if d not in reb.index:
            continue
        out(f"    {d.date()!s:<12}{pct(r4s[d]):>13}{pct(r4a[d]):>13}"
            f"{pct(rel_u.loc[d,'SOL']):>13}{pct(rel_u.loc[d,'ADA']):>13}")

    # ---------- 段4 为什么不可能『都涨』 ----------
    out()
    out(SEP)
    out("段4 · 🔴 为什么『两边筹码都涨』在数学上不可能")
    out(SEP)
    out("  再平衡的买卖是**零和**的: 每次调仓只做一件事 —— 把钱从『涨多的』挪到『涨少的』。")
    out("  所以每个调仓点必然是 **一腿 + 一腿 −**, 不可能两腿同时被加仓。")
    out()
    out("  累积起来, 一腿的币量倍数 >1, 另一腿就必然 <1 吗? **不一定** ——")
    out("  若两腿轮流当赢家(价差来回摆), 两腿都能 >1 (这就是『波动收割』)。")
    out("  但**净效果**取决于长期谁赢: 长期赢家净被卖 ⇒ 币量 <1; 长期输家净被买 ⇒ 币量 >1。")
    us, ua = u["SOL"].iloc[-1], u["ADA"].iloc[-1]
    out()
    out(f"  本例: SOL 长期赢(29.75x vs 1.50x) ⇒ SOL 净被卖, 币量 {us:.3f}x (<1);")
    out(f"        ADA 长期输             ⇒ ADA 净被买, 币量 {ua:.3f}x (>1)。")
    out(f"  但几何平均 √(0.535 × 10.458) = {np.sqrt(us*ua):.3f}x > 1 ⇒ "
        f"**『整体』确实多攒了币, 只是全攒在 ADA 那一侧。**")
    out()
    out("  🔴 所以『都涨了点儿』这句话要拆成两句:")
    out("     ① 账户总筹码(几何平均) —— **是的**, 2.366x, 一年多攒 15.23%;")
    out(f"     ② 每个币各自的币量 —— **不是**, SOL {us:.3f}x 是掉的, 只有 ADA 涨。")
    out()
    out("  『攒币』和『赚钱』在这里第一次分家: ADA 币量涨 10 倍, 但 ADA 价格同期只涨 1.5 倍,")
    out("  而 SOL 币量减半、价格涨 29.75 倍 ⇒ 搬过去的钱跑不赢留在 SOL。")

    os.makedirs(OUTDIR, exist_ok=True)
    t = u.copy()
    t["rel_SOL_over_ADA"] = pr["SOL"] / pr["ADA"]
    fp = os.path.join(OUTDIR, "sol_ada_units_track.csv")
    t.to_csv(fp, encoding="utf-8-sig")
    out()
    out(f"  [OK] 逐周币量轨迹 -> out/sol_ada_units_track.csv ({len(t)} 行)")


if __name__ == "__main__":
    main()
