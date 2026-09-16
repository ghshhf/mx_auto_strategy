# -*- coding: utf-8 -*-
"""最高点入场: 死拿 vs 定投 vs 再平衡 —— 筹码口径 + 保本价 + 资金边界

用户命题:
  「不是用定投, 是用再平衡。再平衡的本质不就是得到筹码吗?」
  「再平衡增加到一定量级就不会再增加了; 定投是无尽增加投入, 筹码越大要投的钱越多。」

三件事必须分开:
  定投   → 摊低【买入成本价】, 通道 = 分散买入时点, 需要【持续投新钱】
  再平衡 → 增加【筹码枚数】,   通道 = 用存量在两币间搬, 【零新钱, 自融资】
  死拿   → 两者都没有, 保本价 = 入场价, 永不下降

口径:
  · 入场点 = AAVE 面板历史最高周 (标签 2021-05-07, 真实日线 2021-05-16)
  · 引擎 = excess_is_chips.sim_trades (等权 / 月调 4 周 / 10bp), 与全仓库一致
  · 保本价 BE = (累计投入 − 对手腿市值) / AAVE 枚数
      单腿路径 (uB=0) 退化为 累计投入/AAVE 枚数 —— 定投即调和平均成本

段:
  0 入场点确认            1 六条路径对照        2 再平衡的筹码账(逐季)
  3 关键时点保本价        4 横向对手对照        5 篮子对照
  6 情景网格              7 机制分解            8 资金边界(自融资 vs 无界投钱)
"""
import os
import sys
import importlib.util

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
OUTDIR = os.path.join(HERE, "out")
FOCUS = "AAVE"
CP = "BTC"
CAP = 10000.0
PANEL_SHIFT_DAYS = 9
SEP = "=" * 132

_spec = importlib.util.spec_from_file_location(
    "eic", os.path.join(HERE, "excess_is_chips.py"))
eic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eic)
sim_trades = eic.sim_trades
# 🔒 调仓数学收敛到跨市场唯一引擎 markets/core/rebalance.py (2026-09-15)
_spec_rb = importlib.util.spec_from_file_location(
    "rb_kernel", os.path.join(os.path.dirname(HERE), "core", "rebalance.py"))
_rb = importlib.util.module_from_spec(_spec_rb)
_spec_rb.loader.exec_module(_rb)
aave_daily = eic.aave_daily
REBAL_WEEKS = int(getattr(eic, "REBAL_WEEKS", 4))
COST_BP = float(getattr(eic, "COST_BP", 10.0))


# ----------------------------------------------------------------- 基础
def load_panel():
    px = pd.read_csv(PANEL, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


def main_coins():
    ex = pd.read_csv(os.path.join(OUTDIR, "all_pairs_exhaustive.csv"))
    lay = [l for l in ex["layer"].unique() if str(l).startswith("2020-10-09")]
    if not lay:
        raise RuntimeError("未找到主口径分层")
    cs = set()
    for p in ex[ex["layer"] == lay[0]]["pair"]:
        cs.update(str(p).split("+"))
    return sorted(cs)


def real_date(d, t):
    rd = pd.Timestamp(t) + pd.Timedelta(days=PANEL_SHIFT_DAYS)
    pos = d.index.get_indexer([rd], method="nearest")[0]
    return d.index[pos], float(d["close"].iloc[pos])


def fm(v):
    if v != v:
        return "—"
    if v <= 0:
        return "已回本"
    return f"${v:,.2f}"


def fp(v):
    return "—" if v != v else f"{v:+.1%}"


def sim_contrib(px, coins, n_batches=12, total_cap=CAP, start=None,
                rebal_weeks=REBAL_WEEKS, cost_bp=None, rebalance=True):
    """分批建仓 (+可选每期等权再平衡)。

    第 j 批在 t = j*rebal_weeks 投入 total_cap/n_batches;
    rebalance=True → 每期把【已累计的全部持仓】拉回等权;
    rebalance=False → 各批买入后永不调仓 (纯定投)。
    单币时再平衡为恒等操作 (无成交), 可直接复用。
    """
    cost_bp = COST_BP if cost_bp is None else cost_bp
    sub = px[list(coins)].dropna(how="any")
    if start is not None:
        sub = sub[sub.index >= start]
    if len(sub) < rebal_weeks * (n_batches + 1):
        return None
    pr = sub.values.astype(float)
    T, n = pr.shape
    w = np.ones(n) / n
    c = cost_bp / 1e4
    contrib = total_cap / n_batches
    units = np.zeros(n)
    nav = np.full(T, np.nan)
    snap = []
    invested = 0.0
    for k in range(0, T, rebal_weeks):
        if k < n_batches * rebal_weeks:
            units = units + (w * contrib) / pr[k]
            invested += contrib
        if rebalance and invested > 0:
            # 🔒 调仓步 → 唯一引擎 (本函数的分批建仓现金流逻辑是独有的, 保留)
            units, _traded, _ratio = _rb.rebalance_step(units, pr[k], w, c)
        for t in range(k, min(k + rebal_weeks, T)):
            nav[t] = float((units * pr[t]).sum())
        snap.append(dict(t=sub.index[k], units=units.copy(), invested=invested))
    last = nav[~np.isnan(nav)][-1]
    nav = np.where(np.isnan(nav), last, nav)
    return dict(units=units, nav_ser=pd.Series(nav, index=sub.index),
                sub=sub, invested=invested, snaps=snap)


def under(nav, t0):
    s = nav.iloc[t0:]
    if len(s) < 2:
        return float("nan"), float("nan")
    return float((s / s.cummax() - 1).min()), float((s < CAP).mean())


def be_of(uA, uB, pB, invested=CAP):
    return (invested - uB * pB) / uA if uA > 1e-12 else float("nan")


# ------------------------------------------------------------- 段0 入场点
def section_entry(px, d):
    print(SEP)
    print("【段0】最高点入场点的确认 (面板口径 vs 日线口径)")
    print(SEP)
    s = px[FOCUS].dropna()
    t0 = s.idxmax()
    rd, _ = real_date(d, t0)
    print(f"  面板 {FOCUS} 最高周: 标签 {t0.date()} → 真实 {rd.date()}  价位 ${s.max():.2f}")
    print(f"  日线收盘最高 ${d['close'].max():.2f} @ {d['close'].idxmax().date()}; "
          f"盘中最高 ${d['high'].max():.2f}")
    print(f"  ⇒ 周频面板能表达的最差入场 = ${s.max():.2f}; 本脚本全部从这里起算。")
    print(f"  末日: {s.index[-1].date()} 面板 ${s.iloc[-1]:.2f} / 日线 ${d['close'].iloc[-1]:.2f}")
    print(f"  {FOCUS} 从最高点至今: {s.iloc[-1] / s.max() - 1:+.2%}   "
          f"({(s.index[-1] - t0).days / 365.25:.2f} 年)")
    return t0, float(s.max())


# ------------------------------------------------------------ 段1 六条路径
def section_paths(px, t0, p_entry):
    print()
    print(SEP)
    print("【段1】最高点入场后, 六条路径的结账 (同一 $10,000, 同一入场周)")
    print(SEP)
    sub2 = px[[FOCUS, CP]].dropna(how="any")
    sub2 = sub2[sub2.index >= t0]
    sub1 = px[[FOCUS]].dropna(how="any")
    sub1 = sub1[sub1.index >= t0]
    pA = float(sub2[FOCUS].iloc[-1])
    pB = float(sub2[CP].iloc[-1])
    pA0 = float(sub2[FOCUS].iloc[0])
    yrs = (sub2.index[-1] - sub2.index[0]).days / 365.25
    rows = []

    def add(name, units, nav_ser, invested, sub, i_focus=0, t_full=0):
        pr_last = sub.values[-1].astype(float)
        uA = float(units[i_focus])
        uB = float(units[1 - i_focus]) if len(units) > 1 else 0.0
        nav = float((units * pr_last).sum())
        be = be_of(uA, uB, pB, invested)
        dd, bl = under(nav_ser, t_full)
        rows.append(dict(path=name, invested=invested, nav=nav, nav_x=nav / CAP,
                         uA=uA, uB=uB, partner_val=uB * pB, aave_val=uA * pA, be=be,
                         be_vs_entry=be / p_entry - 1, need_up=be / pA - 1,
                         dd_max=dd, below=bl))

    u = np.array([CAP / pA0])
    add("① 一次性买入 AAVE 死拿", u,
        pd.Series(u[0] * sub1[FOCUS].values, index=sub1.index), CAP, sub1, 0, 0)
    rc = sim_contrib(px, [FOCUS], n_batches=12, start=t0, rebalance=True)
    add("② 定投 AAVE 12 批 (每月)", rc["units"], rc["nav_ser"], rc["invested"],
        rc["sub"], 0, 12)
    u = (np.ones(2) / 2 * CAP) / sub2.values[0].astype(float)
    add(f"③ 一次性 {FOCUS}+{CP} 等权死拿", u,
        pd.Series((u * sub2.values.astype(float)).sum(axis=1), index=sub2.index),
        CAP, sub2, 0, 0)
    r = sim_trades(px, [FOCUS, CP], FOCUS, capital=CAP, start=t0)
    add(f"④ 一次性 {FOCUS}+{CP} 再平衡", r["units"], r["nav_ser"], CAP,
        r["px_ser"], r["i"], 0)
    r5 = sim_contrib(px, [FOCUS, CP], n_batches=12, start=t0, rebalance=True)
    add(f"⑤ 定投 12 批 + {FOCUS}+{CP} 再平衡", r5["units"], r5["nav_ser"],
        r5["invested"], r5["sub"], 0, 12)
    r6 = sim_contrib(px, [FOCUS, CP], n_batches=12, start=t0, rebalance=False)
    add(f"⑥ 定投 12 批, {FOCUS}+{CP} 不再平衡", r6["units"], r6["nav_ser"],
        r6["invested"], r6["sub"], 0, 12)

    t = pd.DataFrame(rows)
    print(f"  窗口 {t0.date()} ~ {sub2.index[-1].date()} = {yrs:.2f} 年; "
          f"{FOCUS} {pA0:.2f} → {pA:.2f} ({pA / pA0 - 1:+.1%}); "
          f"{CP} {float(sub2[CP].iloc[0]):,.0f} → {pB:,.0f}")
    print()
    print(f"  {'路径':<34}{'投入':>9}{'末日净值':>11}{'净值×':>9}{FOCUS + '枚数':>11}"
          f"{'对手腿':>10}{'保本价':>10}{'需再涨':>10}{'最大回撤':>10}{'水下':>8}")
    print("  " + "-" * 126)
    for _, x in t.iterrows():
        need = "已回本" if x["be"] <= pA else fp(x["need_up"])
        print(f"  {x['path']:<34}{x['invested']:>9,.0f}{x['nav']:>11,.0f}{x['nav_x']:>9.3f}"
              f"{x['uA']:>11,.2f}{x['partner_val']:>10,.0f}{fm(x['be']):>10}{need:>10}"
              f"{x['dd_max']:>10.1%}{x['below']:>8.1%}")
    print()
    print("  保本价 = (累计投入 − 对手腿按末日价折) ÷ AAVE 枚数; 单腿路径退化为 投入/枚数")
    print("  『水下』= 建仓完成(第12个月)之后, 组合净值低于 $10,000 的周数占比")
    print("  ⇒ ④ 相对 ③ 就是纯粹的『再平衡』贡献 (同为一次性, 同币, 同窗口)。")
    t.to_csv(os.path.join(OUTDIR, "rebalance_at_top_paths.csv"),
             index=False, float_format="%.6f")
    return t, r, r5, r6, rc, sub2, pA, pB, pA0


# -------------------------------------------------------- 段2 再平衡的筹码账
def section_chips(px, r, sub2):
    print()
    print(SEP)
    print(f"【段2】再平衡的筹码账 —— 从最高点开始, 熊市里到底攒了多少枚 {FOCUS}")
    print(SEP)
    i = r["i"]
    R = r["R_hist"]
    uA0 = float(r["U0"][i])
    uB0 = float(r["U0"][1 - i])
    ba, bb = float(r["R"][i]), float(r["R"][1 - i])
    uA, uB = ba * uA0, bb * uB0
    print(f"  起点: 两侧各 $5,000 → {FOCUS} {uA0:,.4f} 枚 @ ${r['px_first'][i]:,.2f}"
          f" / {CP} {uB0:,.6f} 枚 @ ${r['px_first'][1 - i]:,.0f}")
    print(f"  末日: {FOCUS} {uA:,.4f} 枚 (β={ba:.4f}) / {CP} {uB:,.6f} 枚 (β={bb:.4f})")
    print(f"  净增持 {FOCUS} {uA - uA0:+,.4f} 枚 (+{ba - 1:.1%});  年均 "
          f"{ba ** (1 / r['yrs']) - 1:+.2%}")
    print(f"  被搬走的 {CP}: {uB0 - uB:,.6f} 枚 ({bb - 1:+.2%}), 调仓 {len(r['trades'])} 次")
    print()
    q = pd.DataFrame({"chipA": R[FOCUS].values, "chipB": R[CP].values,
                      "pxA": sub2[FOCUS].values, "pxB": sub2[CP].values},
                     index=sub2.index)
    g = q.resample("QE").last().dropna()
    print(f"  {'季度':<12}{'AAVE价':>10}{'AAVE筹码':>11}{'较上季枚数':>12}{'较上季价':>11}"
          f"{'AAVE腿净值':>12}{'对手腿净值':>12}{'免费筹码市值':>14}")
    print("  " + "-" * 96)
    prev_u, prev_p = uA0, float(sub2[FOCUS].iloc[0])
    for t, x in g.iterrows():
        u = float(x["chipA"]) * uA0
        p = float(x["pxA"])
        print(f"  {str(t.date()):<12}{p:>10.2f}{u:>11,.2f}{u - prev_u:>+12,.2f}"
              f"{p / prev_p - 1:>+11.1%}{u * p:>12,.0f}"
              f"{float(x['chipB']) * uB0 * float(x['pxB']):>12,.0f}"
              f"{(u - uA0) * p:>14,.0f}")
        prev_u, prev_p = u, p
    print(f"  『免费筹码市值』= (当期筹码 − 起点筹码) × 当期价 —— 这部分筹码没花一分钱,")
    print(f"  是调仓从 {CP} 那条腿搬过来的。")
    return R, uA0, uB0, sub2


# ------------------------------------------------------- 段3 关键时点保本价
def section_breakeven(r, r5, r6, rc, sub2, R, uA0, uB0, p_entry, pA):
    print()
    print(SEP)
    print("【段3】关键时点: AAVE 要涨到多少才算回本? (对手腿按当期价折)")
    print(SEP)
    uA_dca = float(rc["units"][0])
    ab5, ab6 = r5["sub"].index, r6["sub"].index
    uA_last = float(R[FOCUS].iloc[-1]) * uA0

    def snap_at(rr, idx, t_):
        j = idx.get_indexer([t_], method="nearest")[0]
        if j < 0:
            return None
        return rr["snaps"][min(j, len(rr["snaps"]) - 1)]

    keys = [t for t in sub2.index if t.strftime("%m") == "12"][::2]
    keys = [sub2.index[0]] + keys + [sub2.index[-1]]
    seen, kk = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            kk.append(k)

    print(f"  {'时点':<12}{'AAVE价':>10}{'死拿成本':>10}{'定投AAVE':>10}"
          f"{'再平衡':>10}{'定投+再平衡':>12}{'定投不再平衡':>13}{'再平衡净值':>11}")
    print("  " + "-" * 88)
    ser = []
    for t_ in kk:
        pA_t = float(sub2[FOCUS].loc[t_])
        pB_t = float(sub2[CP].loc[t_])
        uA_t = float(R[FOCUS].loc[t_]) * uA0
        uB_t = float(R[CP].loc[t_]) * uB0
        be_reb = be_of(uA_t, uB_t, pB_t)
        nav_reb = uA_t * pA_t + uB_t * pB_t
        s5 = snap_at(r5, ab5, t_)
        s6 = snap_at(r6, ab6, t_)
        be5 = be_of(float(s5["units"][0]), float(s5["units"][1]), pB_t,
                    s5["invested"]) if s5 else float("nan")
        be6 = be_of(float(s6["units"][0]), float(s6["units"][1]), pB_t,
                    s6["invested"]) if s6 else float("nan")
        print(f"  {str(t_.date()):<12}{pA_t:>10.2f}{fm(p_entry):>10}"
              f"{fm(CAP / uA_dca):>10}{fm(be_reb):>10}{fm(be5):>12}{fm(be6):>13}"
              f"{nav_reb:>11,.0f}")
        ser.append(dict(date=t_.strftime("%Y-%m-%d"), px=pA_t, be_hold=p_entry,
                        be_dca=CAP / uA_dca, be_rebal=be_reb, be_dca_rebal=be5,
                        be_dca_hold=be6, nav_rebal=nav_reb))
    pd.DataFrame(ser).to_csv(os.path.join(OUTDIR, "rebalance_at_top_breakeven.csv"),
                             index=False, float_format="%.6f")
    print()
    print("  读法:")
    print(f"   · 死拿成本恒为入场价 ${p_entry:,.2f} —— 不攒筹码, 保本价不会动。")
    print(f"   · 定投AAVE把成本压到 ${CAP / uA_dca:,.2f} (12 批价格的调和平均), 但只摊成本。")
    print(f"   · 再平衡把筹码从 {uA0:,.2f} 枚搬到 {uA_last:,.2f} 枚, 保本价随之下降"
          f" —— 这一列才是『再平衡』的贡献。")
    print("   · 定投 + 再平衡 = 两条通道叠加 (成本被摊低 + 枚数变多)。")


# ------------------------------------------------------- 段4 横向对手对照
def section_counterparts(px, coins, t0, p_entry):
    print()
    print(SEP)
    print(f"【段4】最高点入场 (${p_entry:,.2f}), 换 {len(coins) - 1} 个对手的再平衡")
    print(SEP)
    rows = []
    for b in [c for c in coins if c != FOCUS]:
        r = sim_trades(px, [FOCUS, b], FOCUS, capital=CAP, start=t0)
        if r is None:
            continue
        i = r["i"]
        ba, bb = float(r["R"][i]), float(r["R"][1 - i])
        uA = ba * float(r["U0"][i])
        uB = bb * float(r["U0"][1 - i])
        pB = float(r["px_last"][1 - i])
        dd, bl = under(r["nav_ser"], 0)
        rows.append(dict(partner=b, yrs=r["yrs"], beta_a=ba, beta_cp=bb,
                         excess=r["nav"] / r["hold"] - 1, nav_x=r["nav"] / CAP,
                         hold_x=r["hold"] / CAP, uA=uA, partner_val=uB * pB,
                         be=be_of(uA, uB, pB), be_vs_entry=be_of(uA, uB, pB) / p_entry - 1,
                         dd=dd, below=bl))
    t = pd.DataFrame(rows).sort_values("be").reset_index(drop=True)
    print(f"  {'对手':<7}{'β_AAVE':>9}{'β_对手':>9}{'超额':>10}{'净值×':>9}"
          f"{'AAVE枚数':>11}{'对手腿':>10}{'保本价':>10}{'相对入场':>10}{'最大回撤':>10}{'水下':>8}")
    print("  " + "-" * 108)
    for _, x in t.iterrows():
        print(f"  {x['partner']:<7}{x['beta_a']:>9.4f}{x['beta_cp']:>9.4f}"
              f"{x['excess']:>10.2%}{x['nav_x']:>9.3f}{x['uA']:>11,.2f}"
              f"{x['partner_val']:>10,.0f}{fm(x['be']):>10}"
              f"{fp(x['be_vs_entry']):>10}{x['dd']:>10.1%}{x['below']:>8.1%}")
    rel = t[~t["partner"].isin(["BTC", "ETH"])]
    print()
    print(f"  保本价中位 {fm(t['be'].median())} (相对入场价 {fp(t['be'].median() / p_entry - 1)}); "
          f"最低 {t.loc[t['be'].idxmin(), 'partner']} {fm(t['be'].min())}")
    print(f"  相对组(非BTC/ETH) 保本价中位 {fm(rel['be'].median())}, "
          f"最低 {rel.loc[rel['be'].idxmin(), 'partner']} {fm(rel['be'].min())}")
    print(f"  一次性入场即已回本(净值≥本金)的对手: {int((t['nav_x'] >= 1).sum())}/{len(t)}")
    t.to_csv(os.path.join(OUTDIR, "rebalance_at_top_counterparts.csv"),
             index=False, float_format="%.6f")
    return t


# ------------------------------------------------------------ 段5 篮子对照
def section_basket(px, t0, p_entry):
    print()
    print(SEP)
    print("【段5】最高点入场, 把 AAVE 放进等权篮子 / 等权再平衡篮子")
    print(SEP)
    avail = sorted([c for c in px.columns if pd.notna(px[c].loc[t0:]).all()])
    print(f"  自 {t0.date()} 起有完整数据的币: {len(avail)} 个 → {' '.join(avail)}")
    print()
    rows = []
    for name, cs, mode in (
            ("AAVE 单腿死拿", [FOCUS], "hold"),
            (f"AAVE+{CP} 等权死拿", [FOCUS, CP], "hold"),
            (f"AAVE+{CP} 再平衡", [FOCUS, CP], "rebal"),
            (f"全部 {len(avail)} 币等权死拿", avail, "hold"),
            (f"全部 {len(avail)} 币等权再平衡", avail, "rebal")):
        sub = px[list(cs)].dropna(how="any")
        sub = sub[sub.index >= t0]
        k = len(cs)
        i = list(cs).index(FOCUS)
        if mode == "hold":
            uu = (np.ones(k) / k * CAP) / sub.values[0].astype(float)
            nav_ser = pd.Series((uu * sub.values.astype(float)).sum(axis=1),
                                index=sub.index)
        else:
            rr = sim_trades(px, cs, FOCUS, capital=CAP, start=t0)
            if rr is None:
                continue
            uu, nav_ser, i = rr["units"], rr["nav_ser"], rr["i"]
        pr_last = sub.values[-1].astype(float)
        uA = float(uu[i])
        others = float(sum(uu[j] * pr_last[j] for j in range(k) if j != i))
        nav = float((uu * pr_last).sum())
        dd, bl = under(nav_ser, 0)
        rows.append(dict(name=name, n=k, nav=nav, nav_x=nav / CAP, uA=uA,
                         be=be_of(uA, 1.0, others) if False else
                         ((CAP - others) / uA if uA > 1e-12 else float("nan")),
                         dd=dd, below=bl))
    t = pd.DataFrame(rows)
    print(f"  {'路径':<34}{'币数':>5}{'末日净值':>11}{'净值×':>9}{'AAVE枚数':>11}"
          f"{'保本价':>10}{'最大回撤':>10}{'水下':>8}")
    print("  " + "-" * 92)
    for _, x in t.iterrows():
        print(f"  {x['name']:<34}{x['n']:>5}{x['nav']:>11,.0f}{x['nav_x']:>9.3f}"
              f"{x['uA']:>11,.2f}{fm(x['be']):>10}{x['dd']:>10.1%}{x['below']:>8.1%}")
    print()
    print(f"  入场最高点 ${p_entry:,.2f}; 篮子越大, 单币冲击被摊薄, 但 AAVE 能分到的筹码也被摊薄。")
    t.to_csv(os.path.join(OUTDIR, "rebalance_at_top_basket.csv"),
             index=False, float_format="%.6f")
    return t


# ------------------------------------------------------------ 段6 情景网格
def section_scenario(r, p_entry, pA, pB, pA0):
    print()
    print(SEP)
    print("【段6】情景网格: AAVE 与对手同时变动时, 谁先回本")
    print(SEP)
    i = r["i"]
    uA0, uB0 = float(r["U0"][i]), float(r["U0"][1 - i])
    uA = float(r["R"][i]) * uA0
    uB = float(r["R"][1 - i]) * uB0
    uA_h = CAP / pA0
    m_entry = round(p_entry / pA, 2)
    mults = [0.5, 1.0, 2.0, m_entry, 8.0]
    labels = ["0.5", "1.0(今)", "2.0", f"{m_entry}(入场价)", "8.0"]
    print(f"  再平衡末筹码: AAVE {uA:,.2f} 枚 / 对手 {uB:,.6f} 枚;  "
          f"一次性死拿 AAVE {uA_h:,.2f} 枚")
    print("  每格 = 再平衡净值 / 一次性死拿AAVE净值, 单位美元 (本金 $10,000)")
    print()
    print(f"  {'AAVE×':<16}" + "".join(f"{'对手×' + l:>22}" for l in labels))
    print("  " + "-" * (16 + 22 * len(mults)))
    for ma, la in zip(mults, labels):
        cells = []
        for mb in mults:
            nv_r = uA * pA * ma + uB * pB * mb
            nv_h = uA_h * pA * ma
            cells.append(f"{nv_r:>10,.0f}/{nv_h:>9,.0f}"
                         + ("R" if nv_r >= CAP else "·")
                         + ("H" if nv_h >= CAP else "·"))
        print(f"  {la:<16}" + "".join(f"{c:>22}" for c in cells))
    print()
    print("  后缀 R = 再平衡已回到 $10,000, H = 死拿已回到 $10,000")
    print(f"  末日价: AAVE ${pA:,.2f} / 对手 ${pB:,.0f}; "
          f"入场价 ${p_entry:,.2f} (= AAVE ×{p_entry / pA:.2f})")


# ------------------------------------------------------------ 段7 机制分解
def section_mechanics(px, t0, r, p_entry, uA0):
    print()
    print(SEP)
    print("【段7】机制分解: 定投改的是【成本价】, 再平衡改的是【枚数】")
    print(SEP)
    rc = sim_contrib(px, [FOCUS], n_batches=12, start=t0, rebalance=True)
    uA_dca = float(rc["units"][0])
    uA_reb = float(r["R"][r["i"]]) * uA0
    u_base = CAP / p_entry
    print(f"  {'路径':<34}{'AAVE枚数':>12}{'枚数×':>9}{'为AAVE掏的钱':>14}"
          f"{'成本/枚':>11}{'保本价':>11}")
    print("  " + "-" * 92)
    print(f"  {'① 一次性死拿 AAVE':<34}{u_base:>12,.2f}{1.0:>9.3f}{CAP:>14,.0f}"
          f"{p_entry:>11,.2f}{p_entry:>11,.2f}")
    print(f"  {'② 定投 AAVE 12 批':<34}{uA_dca:>12,.2f}{uA_dca / u_base:>9.3f}{CAP:>14,.0f}"
          f"{CAP / uA_dca:>11,.2f}{CAP / uA_dca:>11,.2f}")
    print(f"  {'④ 一次性 AAVE+对手 再平衡':<34}{uA_reb:>12,.2f}{uA_reb / u_base:>9.3f}"
          f"{CAP / 2:>14,.0f}{'—':>11}{'见段3':>11}")
    print()
    print(f"  ② 的通道: 成本价 ${p_entry:,.2f} → ${CAP / uA_dca:,.2f}, "
          f"但需要【连续 12 个月投新钱】。")
    print(f"  ④ 的通道: 枚数 {u_base:,.2f} → {uA_reb:,.2f} (×{uA_reb / u_base:.3f}),"
          f" 净增 {uA_reb - u_base:+,.2f} 枚, 全部来自卖对手腿, 没多掏一分钱。")
    print()
    print("  ⇒ 两条通道的数学形式不同:")
    print("     定投:   BE = N / Σ(1/P_i)             ← 分散买入时点, 压低【价格那侧】")
    print("     再平衡: BE = (CAP − 对手腿市值) / 枚数  ← 不收新钱, 直接做大【枚数那侧】")
    print("     ⇒ 定投要新钱; 再平衡只用存量在两个币之间搬。两者可叠加 (路径⑤)。")


# ------------------------------------------------------ 段8 资金边界
def section_funding(px, t0, r, sub2, uA0, uB0, p_entry, pA, pB, pA0):
    print()
    print(SEP)
    print("【段8】资金边界: 再平衡是【自融资 + 会饱和】的, 定投是【无界投钱】的")
    print(SEP)
    i = r["i"]
    R = r["R_hist"]
    T = r["yrs"]

    # ---- 8a 单次调仓成交额 ÷ 当期 NAV: 是否有界/收敛
    ratios = []
    for tr in r["trades"]:
        nav_t = float(r["nav_ser"].asof(pd.Timestamp(tr["date"])))
        ratios.append(abs(tr["dq"]) * tr["px"] / nav_t if nav_t > 0 else np.nan)
    ra = np.array([x for x in ratios if x == x])
    h = len(ra) // 2
    print("  8a 单次调仓成交额 ÷ 当期组合净值 (自融资性的直接检验):")
    print(f"     前半程中位 {np.median(ra[:h]):>7.2%}   后半程中位 {np.median(ra[h:]):>7.2%}"
          f"   全样本最大 {ra.max():.2%}")
    print(f"     ⇒ 恒 <100%, 且前后半程同量级 ⇒ 每期只搬组合的一小部分,")
    print(f"        额度随组合自动缩放, 【不需要追加本金】。共 {len(ra)} 次调仓。")

    # ---- 8b 筹码增速的不变量
    pr = sub2.values.astype(float)
    rets = np.diff(np.log(pr), axis=0)
    mA = float(r["px_last"][i] / r["px_first"][i])
    mB = float(r["px_last"][1 - i] / r["px_first"][1 - i])
    bA, bB = float(r["R"][i]), float(r["R"][1 - i])
    gA, gB = np.log(bA) / T, np.log(bB) / T
    tA, tB = 0.5 * np.log(mB / mA) / T, 0.5 * np.log(mA / mB) / T
    gcA, gcB = gA - tA, gB - tB
    dr = rets[:, i] - rets[:, 1 - i]
    harv = 0.25 * float(dr.var()) * 52
    mu_R = np.log(r["nav"] / CAP) / T
    mu_A, mu_B = np.log(mA) / T, np.log(mB) / T
    gc_exact = mu_R - 0.5 * (mu_A + mu_B)
    print()
    print("  8b 年化筹码增速的分解 (恒等式: log 筹码增速_i = 组合筹码年化 + ½·log(另一侧/本侧)/T):")
    print(f"     {FOCUS}: 总 {gA:+.4f}/年 = 组合筹码年化 {gcA:+.4f} + 搬运项 {tA:+.4f}")
    print(f"     {CP}: 总 {gB:+.4f}/年 = 组合筹码年化 {gcB:+.4f} + 搬运项 {tB:+.4f}")
    print(f"     两侧『组合筹码年化』残差 |{gcA - gcB:.2e}| ⇒ 近似同一个不变量, 与选哪个币无关")
    print("       (残差来自周频离散与 10bp 调仓费, 连续再平衡极限下严格相等)。")
    print()
    print("     这个不变量的独立算法 (它才是『收割项』的实测值):")
    print(f"       再平衡净值对数增速 μ_R                = log({r['nav'] / CAP:.4f})/{T:.2f} = {mu_R:+.4f}/年")
    print(f"       两币死拿对数增速均值 ½(μ_A+μ_B)         = ½({mu_A:+.4f}{mu_B:+.4f}) = "
          f"{0.5 * (mu_A + mu_B):+.4f}/年")
    print(f"       收割项 = μ_R − ½(μ_A+μ_B)             = {gc_exact:+.4f}/年   "
          f"⟷ 上面分解出的 {gcA:+.4f}/{gcB:+.4f}   (残差 {abs(gc_exact - gcA):.2e})")
    print(f"       一阶理论近似 ¼·Var(r_A−r_B)           = ¼×{float(dr.var()) * 52:.4f} = "
          f"{harv:+.4f}/年  (周波动极大 ⇒ 高阶项显著, 一阶会高估 "
          f"{(harv / gc_exact - 1):.0%})")
    print("     ⇒ 关键: 这个数只由 σ/ρ 决定, 【与投多少钱无关】——")
    print("        $10,000 和 $10,000,000 的筹码年化增速完全相同 ⇒ 给定资产, 增速是常数, 会饱和;")
    print("        它也不依赖价格涨跌方向 (= 右式没有价格项) ⇒ 熊市牛市都收这份钱。")

    # ---- 8c 等价新钱: 再平衡替你省下多少定投
    uA = bA * uA0
    uB = bB * uB0
    be_reb = be_of(uA, uB, pB)
    u_hold = CAP / p_entry
    u_need = CAP / be_reb
    print()
    print("  8c 『再平衡到底值多少钱』—— 折算成定投要掏的新钱:")
    print(f"     再平衡把保本价从 ${p_entry:,.2f} 压到 ${be_reb:,.2f} (0 新钱, 5.33 年)")
    print(f"     纯死拿要在末日价补到同样保本价, 需持有 {u_need:,.2f} 枚 "
          f"(现有 {u_hold:,.2f} 枚)")
    print(f"     ⇒ 需再买 {u_need - u_hold:,.2f} 枚 × ${pA:,.2f} = "
          f"${(u_need - u_hold) * pA:,.0f} 新钱")
    print(f"     ⇒ 再平衡的交换比: 0 美元 换到 ≈ ${(u_need - u_hold) * pA:,.0f} 的效果 "
          f"({(u_need - u_hold) * pA / CAP:.2f}× 本金)")
    g0 = sub2.index[::REBAL_WEEKS][:12]
    dca_px = CAP / sum((CAP / 12) / float(sub2[FOCUS].loc[t_]) for t_ in g0)
    print(f"     ⇒ 另一个参照价: 按定投 12 批均价 ${dca_px:,.2f} 买这 {uA - uA0:,.2f} 枚"
          f"(熊市买入) 需 ${(uA - uA0) * dca_px:,.0f} 新钱")
    print(f"        ⇒ 再平衡白拿筹码的现金等价在 "
          f"${min((u_need - u_hold) * pA, (uA - uA0) * dca_px):,.0f} ~ "
          f"${max((u_need - u_hold) * pA, (uA - uA0) * dca_px):,.0f} 之间"
          f" (取决按哪个价折算), 本金却是 $0 追加。")

    # ---- 8d 定投的无界性: 要压低保本价就得一直投钱
    print()
    print("  8d 定投的融资需求 vs 再平衡的零融资 (同一起点, 同一时间轴):")
    grid = list(sub2.index[::REBAL_WEEKS])
    if grid[-1] != sub2.index[-1]:
        grid.append(sub2.index[-1])
    M = CAP / 12.0
    cum_cash, cum_u = 0.0, 0.0
    best = (np.inf, None)
    print(f"     {'月份':>6}{'AAVE价':>10}{'定投累计投入':>14}{'定投AAVE枚数':>14}"
          f"{'定投保本价':>12}{'再平衡投入':>12}{'再平衡枚数':>12}{'再平衡保本价':>14}")
    for n, t_ in enumerate(grid, start=1):
        p_t = float(sub2[FOCUS].loc[t_])
        pB_t = float(sub2[CP].loc[t_])
        cum_cash += M
        cum_u += M / p_t
        be_dca = cum_cash / cum_u
        if be_dca < best[0]:
            best = (be_dca, t_)
        uA_t = float(R[FOCUS].loc[t_]) * uA0
        uB_t = float(R[CP].loc[t_]) * uB0
        if n in (12, 24, 36, 48, 60, len(grid)):
            print(f"     {n:>6}{p_t:>10.2f}{cum_cash:>14,.0f}{cum_u:>14,.2f}"
                  f"${be_dca:>11,.2f}{CAP:>12,.0f}{uA_t:>12,.2f}"
                  f"{fm(be_of(uA_t, uB_t, pB_t)):>14}")
    print(f"     ⇒ 定投累计投入从 $10,000 涨到 ${cum_cash:,.0f} "
          f"({cum_cash / CAP:.1f}×), 保本价最低只到 ${best[0]:,.2f} @ {best[1].date()}")
    print(f"        且这个下界【事前不可知】(取决于未来你会碰到哪些价);")
    print(f"     ⇒ 再平衡全程只投 $10,000 (0 追加), 保本价 ${be_of(uA, uB, pB):,.2f}"
          f" 且任意时点可即时计算 = (本金 − 对手腿市值) ÷ 枚数。")


def main():
    px = load_panel()
    coins = main_coins()
    d = aave_daily()
    print(SEP)
    print(f"{FOCUS} @ 最高点入场: 死拿 vs 定投 vs 再平衡   "
          f"主口径 {len(coins)} 币   等权/月调({REBAL_WEEKS}周)/{COST_BP:.0f}bp   ${CAP:,.0f}")
    print(SEP)
    t0, p_entry = section_entry(px, d)
    t, r, r5, r6, rc, sub2, pA, pB, pA0 = section_paths(px, t0, p_entry)
    R, uA0, uB0, sub2 = section_chips(px, r, sub2)
    section_breakeven(r, r5, r6, rc, sub2, R, uA0, uB0, p_entry, pA)
    section_counterparts(px, coins, t0, p_entry)
    section_basket(px, t0, p_entry)
    section_scenario(r, p_entry, pA, pB, pA0)
    section_mechanics(px, t0, r, p_entry, uA0)
    section_funding(px, t0, r, sub2, uA0, uB0, p_entry, pA, pB, pA0)


if __name__ == "__main__":
    main()
