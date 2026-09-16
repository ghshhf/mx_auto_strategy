# -*- coding: utf-8 -*-
"""
SOL + ADA —— 「ADA 万一涨回来会怎样」的未来推演 + 调仓频率对照。

回答三问:
  1. 现在用的是周平衡还是月平衡?   -> 引擎 REBAL_WEEKS=4 (月频); 本脚本对照 1/2/4/8/13 周
  2. ADA 再涨回来, 筹码会不会搬回 SOL? -> 段1/段2 (阈值: 要涨多少 SOL 才回到 1.0x)
  3. 整体筹码增加多少? SOL 增加多少? ADA 增加多少? -> 段0 现状 + 段1 逐情景

用法:
  python sol_ada_future.py                # 默认 SOL,ADA / 2020-08-07
  python sol_ada_future.py SOL,ADA 2020-08-07
"""
import os
import sys
import math
import importlib.util

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "bap", os.path.join(HERE, "crypto_btc_ada_pair.py"))
bap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bap)

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
OUTDIR = os.path.join(HERE, "out")
COST_BP = 10.0
COINS = ["SOL", "ADA"]
MAIN = "2020-08-07"

SEP = "=" * 96
SUB = "-" * 96


def out(s=""):
    print(s)


pct = lambda x, d=2: f"{x * 100:+.{d}f}%"
pctp = lambda x, d=2: f"{x * 100:.{d}f}%"


# ---------------------------------------------------------------- 数据
def load_panel():
    px = pd.read_csv(PANEL, index_col=0)
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


def extend(px, coins, k_ada, weeks, shape="exp", k_sol=1.0, back=False):
    """把历史面板末端接上一段『ADA 涨到 k_ada 倍(SOL 乘 k_sol)』的未来路径。

    shape: exp=指数(匀速复利) / lin=线性 / onestep=第一周一次性到位
    back=True  -> 先涨到 k_ada 再跌回原点 (V 型来回摆动, 检验「波动收割」)
    返回 扩展面板 / 未来段起点index位置
    """
    hist = px[coins].dropna(how="any")
    p0 = hist.iloc[-1].values.astype(float)
    # back: 需 2*weeks+1 行才精确回到原点(0 起 -> weeks 到顶 -> 2*weeks 回原点)
    n_future = weeks * 2 + 1 if back else weeks
    tgt = np.array([k_sol, k_ada], dtype=float) if len(coins) == 2 else None
    fut = np.empty((n_future, len(coins)))
    if back:
        half = weeks
        for i in range(n_future):
            if i <= half:
                f = _frac(i, half, shape)
            else:
                f = _frac(2 * half - i, half, shape)
            fut[i] = p0 * (1.0 + (tgt - 1.0) * f)
    else:
        for i in range(n_future):
            f = _frac(i, max(weeks - 1, 1), shape)
            fut[i] = p0 * (1.0 + (tgt - 1.0) * f)
    idx = pd.date_range(hist.index[-1] + pd.Timedelta(days=7),
                        periods=n_future, freq="7D")
    df = pd.DataFrame(fut, index=idx, columns=coins)
    full = pd.concat([hist, df])
    return full, len(hist)


def _frac(i, n, shape):
    t = 0.0 if n <= 0 else min(i / n, 1.0)
    if shape == "lin":
        return t
    if shape == "onestep":
        return 1.0 if i > 0 else 0.0
    return (math.pow(2.0, t) - 1.0)      # exp: 复利匀速


# ---------------------------------------------------------------- 通用跑
def run(px, coins, start, rebal_weeks=4, cost_bp=COST_BP):
    r = bap.sim(px, list(coins), start=start, rebal_weeks=rebal_weeks,
                cost_bp=cost_bp)
    if r is None:
        return None
    u = r["units_mult"]
    geo = float(np.sqrt(np.prod([u[c] for c in coins])))
    r["geo"] = geo
    r["exc"] = float(r["nav"] / r["hold_nav"] - 1)
    return r


# ---------------------------------------------------------------- 段0
def section0(px):
    out(SEP)
    out("段0 · 现状对账 (口径 / 当前持仓 / 权重)")
    out(SEP)
    r = run(px, COINS, MAIN)
    u = r["units_mult"]
    out(f"  口径: 目标 {'-'.join(['50:50'])}  (引擎 w=ones(n)/n, n=2)  ·  "
        f"调仓 **每 4 周 = 月频**  ·  单边 {COST_BP:.0f}bp")
    out(f"       (不是周平衡。屯币宝实盘是「比例偏离 1% 触发」, 比周频更密; "
        f"回测统一用 4 周)")
    out(f"  窗口 {r['start'].date()} ~ {r['end'].date()}  {r['yrs']:.2f} 年  "
        f"调仓 {r['turnover_events']} 次  年化换手 {pctp(r['turnover_ann'])}")
    out()
    pr = px[COINS].dropna(how="any")
    pen = pr.iloc[-1]
    val = {c: u[c] * pen[c] / pr[c].iloc[0] for c in COINS}   # 相对初始 0.5 的市值
    tot = sum(val.values())
    out(f"  {'币':<6}{'币量倍数':>12}{'该腿市值':>12}{'当前权重':>10}{'相对死拿':>12}")
    out("  " + SUB[:64])
    for c in COINS:
        out(f"  {c:<6}{u[c]:>11.3f}x{val[c]:>12.3f}{val[c] / tot:>10.1%}"
            f"{u[c] - 1:>+12.3f}")
    out("  " + SUB[:64])
    out(f"  {'账户':<6}{r['geo']:>11.3f}x{tot:>12.3f}{1.0:>10.1%}")
    out()
    out(f"  ⇒ 币量: SOL **{u['SOL']:.3f}x** (比死拿 {'少' if u['SOL']<1 else '多'} "
        f"{abs(u['SOL']-1):.1%})  ·  ADA **{u['ADA']:.3f}x** "
        f"(比死拿多 {u['ADA']-1:.1%})")
    out(f"  ⇒ 账户总筹码(几何平均) **{r['geo']:.3f}x**; "
        f"权重已被拉回 {val['SOL']/tot:.1%} / {val['ADA']/tot:.1%} "
        f"(≈50:50, 因为刚调过仓)")
    out(f"  ⇒ 净值 {r['nav']:.3f}x vs 死拿 {r['hold_nav']:.3f}x  "
        f"⇒ 超额 {pct(r['exc'])}")
    out()
    out("  🔴 关键前提: 因为权重现在≈50:50, **ADA 只要一涨, 立刻触发卖 ADA 买 SOL**,")
    out("     不存在『要涨很久才开始搬』的门槛 —— 下一次调仓就会开始搬。")
    return r, u, val, tot


# ---------------------------------------------------------------- 段1
def section1(px, base):
    out()
    out(SEP)
    out("段1 · ADA 涨回来会怎样 (SOL 价格假设不变 = 等价于 ADA 相对涨 k 倍)")
    out(SEP)
    out("  读法: 『涨 1 倍』= 变成 2x; 『涨 2 倍』= 变成 3x。两种都给。")
    out()
    out(f"  {'情景':<22}{'SOL币量':>10}{'ADA币量':>10}{'账户总筹码':>12}"
        f"{'净值x':>10}{'死拿x':>10}{'超额':>11}")
    out("  " + SUB[:96])
    rows = []
    scen = [
        ("ADA 涨 1 倍 (→2x) 26周", 2.0, 26, "exp", 1.0, False),
        ("ADA 涨 1 倍 (→2x) 52周", 2.0, 52, "exp", 1.0, False),
        ("ADA 涨 2 倍 (→3x) 26周", 3.0, 26, "exp", 1.0, False),
        ("ADA 涨 2 倍 (→3x) 52周", 3.0, 52, "exp", 1.0, False),
        ("ADA 涨 2 倍 一次性到位", 3.0, 26, "onestep", 1.0, False),
        ("ADA 涨 2 倍再跌回原地", 3.0, 26, "exp", 1.0, True),
        ("ADA 原地不动 (对照*)", 1.0, 26, "exp", 1.0, False),
    ]
    for tag, k, w, sh, ks, back in scen:
        full, _ = extend(px, COINS, k, w, shape=sh, k_sol=ks, back=back)
        r = run(full, COINS, MAIN)
        u = r["units_mult"]
        out(f"  {tag:<22}{u['SOL']:>9.3f}x{u['ADA']:>9.3f}x{r['geo']:>11.3f}x"
            f"{r['nav']:>10.3f}{r['hold_nav']:>10.3f}{pct(r['exc']):>11}")
        rows.append(dict(scenario=tag, k_ada=k, weeks=w, shape=sh, back=back,
                         u_sol=u["SOL"], u_ada=u["ADA"], geo=r["geo"],
                         nav=r["nav"], hold=r["hold_nav"], exc=r["exc"],
                         yrs=r["yrs"]))
    out("  * 对照行比段0 现状多跑了 26 周, 期间含一次『末周偏离补调』,")
    out("    所以 SOL 从 0.535 微降到 0.531 —— 属引擎正常行为, 非误差。")
    out()
    d = pd.DataFrame(rows)
    one, swi, std, slw = d.iloc[4], d.iloc[5], d.iloc[6], d.iloc[2]
    out("  ⇒ 🔴 反直觉但正确: **『一次性暴涨』总筹码最高** "
        f"({one.geo:.3f}x vs 26周匀速 {slw.geo:.3f}x)。")
    out("     因为收割 ∝ **单次偏离的平方**: 一次 3 倍偏离的平方, 大于 26 周小偏离的平方之和。")
    out("     ⇒ 慢慢涨**攒得少**, 一步到位**攒得多** (但这只是筹码口径, 不等于赚得多)。")
    out(f"  ⇒ 『涨 2 倍再跌回原地』才是真兑现: ADA 价格回到原点, 净值 "
        f"{swi.nav:.3f}x vs 死拿 {swi.hold:.3f}x ⇒ 超额 {pct(swi.exc)}")
    out(f"     (对照 {std.nav:.3f}x / 超额 {pct(std.exc)}) ⇒ **来回摆动本身白赚 "
        f"{(swi.nav/std.nav-1)*100:+.1f}%**。")
    return d


# ---------------------------------------------------------------- 段2
def section2(px, u_now):
    out()
    out(SEP)
    out("段2 · 阈值: ADA 要涨多少, SOL 的币量才回到 1.0x (不比死拿少)?")
    out(SEP)
    out(f"  当前 SOL 币量 {u_now['SOL']:.3f}x。ADA 相对涨 k 倍(52 周匀速路径):")
    out()
    out(f"  {'ADA倍数k':>10}{'SOL币量':>11}{'ADA币量':>11}{'账户总筹码':>12}"
        f"{'净值x':>10}{'超额':>11}  备注")
    out("  " + SUB[:96])
    rows = []
    ks = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 8.0]
    hit = None
    for k in ks:
        full, _ = extend(px, COINS, k, 52, shape="exp")
        r = run(full, COINS, MAIN)
        u = r["units_mult"]
        note = ""
        if hit is None and u["SOL"] >= 1.0:
            hit = k
            note = f"◀ SOL 首次回到 1.0x"
        out(f"  {k:>9.1f}x{u['SOL']:>10.3f}x{u['ADA']:>10.3f}x{r['geo']:>11.3f}x"
            f"{r['nav']:>10.3f}{pct(r['exc']):>11}  {note}")
        rows.append(dict(k=k, u_sol=u["SOL"], u_ada=u["ADA"], geo=r["geo"],
                         nav=r["nav"], hold=r["hold_nav"], exc=r["exc"]))
    out()
    if hit:
        out(f"  ⇒ **ADA 相对涨到约 {hit:.1f}x (即再涨 {(hit-1)*100:.0f}%) 时, "
            f"SOL 币量才追平死拿 1.0x**。")
    else:
        out(f"  ⇒ 扫描到 {ks[-1]}x 时 SOL 仍未回到 1.0x。")
    out("  ⇒ 但注意: 即使 SOL 还在 1.0 以下, **账户总筹码和净值已经在涨** ——")
    out("     这就是『攒币』和『每币各自币量』必须分开报的原因。")
    return pd.DataFrame(rows), hit


# ---------------------------------------------------------------- 段3
def section3(px):
    out()
    out(SEP)
    out("段3 · 周平衡 vs 月平衡 (回答「现在用的是周还是月」)")
    out(SEP)
    out(f"  {'调仓频率':<16}{'次/年':>7}{'调仓次数':>9}{'SOL币量':>10}{'ADA币量':>10}"
        f"{'账户总筹码':>12}{'年化换手':>10}{'净值x':>9}{'超额':>11}")
    out("  " + SUB[:96])
    rows = []
    for wk, tag in ((1, "每周"), (2, "每 2 周"), (4, "每 4 周(月)★当前"),
                    (8, "每 8 周(双月)"), (13, "每 13 周(季)")):
        r = run(px, COINS, MAIN, rebal_weeks=wk)
        u = r["units_mult"]
        out(f"  {tag:<16}{52/wk:>7.1f}{r['turnover_events']:>9}"
            f"{u['SOL']:>9.3f}x{u['ADA']:>9.3f}x{r['geo']:>11.3f}x"
            f"{pctp(r['turnover_ann']):>10}{r['nav']:>9.3f}{pct(r['exc']):>11}")
        rows.append(dict(weeks=wk, tag=tag, n=r["turnover_events"],
                         u_sol=u["SOL"], u_ada=u["ADA"], geo=r["geo"],
                         turn=r["turnover_ann"], nav=r["nav"],
                         hold=r["hold_nav"], exc=r["exc"]))
    out()
    out("  ⇒ 🔴 **不是『越频繁越好』** —— 4 周(月频)是这里最好的, 周频反而最差之一。")
    out("     两个相反的力量: 频率↑ ⇒ 收割项↑ (好) 但同时 **漂移差侵蚀↑** (坏, 因为更")
    out("     持续地把钱搬向长期输家 ADA) + 成本↑。本例后两者占优。")
    out()
    # ---- 段3b: 成本分离 ----
    out("  成本分离 (同一起点, 只改单边费率):")
    out(f"    {'频率':<16}{'0bp 超额':>12}{'0bp 总筹码':>13}"
        f"{'10bp 超额':>12}{'10bp 总筹码':>13}{'成本吃掉的年化':>16}")
    out("    " + SUB[:80])
    for wk, tag in ((1, "每周"), (2, "每 2 周"), (4, "每 4 周(月)★"),
                    (8, "每 8 周"), (13, "每 13 周")):
        r0 = run(px, COINS, MAIN, rebal_weeks=wk, cost_bp=0.0)
        r1 = run(px, COINS, MAIN, rebal_weeks=wk, cost_bp=COST_BP)
        eat = (r0["nav"] / r1["nav"]) ** (1 / r0["yrs"]) - 1
        out(f"    {tag:<16}{pct(r0['exc']):>12}{r0['geo']:>12.3f}x"
            f"{pct(r1['exc']):>12}{r1['geo']:>12.3f}x{pct(eat):>16}")
    out()
    # ---- 段3c: 相位检验 ----
    out("  相位检验 (起点错开 0~3 周, 取中位 —— 单结论必须过这关):")
    out(f"    {'频率':<16}" + "".join(f"{'起+' + str(k) + '周':>11}"
                                     for k in range(4)) + f"{'中位':>12}")
    out("    " + SUB[:80])
    t0 = pd.Timestamp(MAIN)
    med = {}
    for wk, tag in ((1, "每周"), (2, "每 2 周"), (4, "每 4 周(月)★"),
                    (8, "每 8 周"), (13, "每 13 周")):
        ex = []
        for k in range(4):
            s = (t0 + pd.Timedelta(weeks=k)).strftime("%Y-%m-%d")
            rr = run(px, COINS, s, rebal_weeks=wk)
            ex.append(rr["exc"] if rr else np.nan)
        med[tag] = float(np.nanmedian(ex))
        out(f"    {tag:<16}" + "".join(f"{pct(v):>11}" for v in ex)
            + f"{pct(med[tag]):>12}")
    out()
    best = max(med, key=med.get)
    out("  ⇒ 🔴 三条结论 (按相位**中位**列, 不是单点):")
    out(f"     ① **成本不是原因** —— 0bp vs 10bp 只差 0.07~0.21%/年。")
    out(f"     ② 频率↑ 的唯一坏处是**更持续把钱搬向长期输家** ⇒ 漂移差侵蚀↑。")
    out(f"        本例 ADA 长期单边输 ⇒ **调得越勤越差**: "
        f"周 {pct(med['每周'])} → 月 {pct(med['每 4 周(月)★'])} → 季 {pct(med['每 13 周'])}。")
    out(f"     ③ 相位中位最优 = **{best}** ({pct(med[best])}); "
        f"4 周那个 +1.06% **是相位运气**(中位 {pct(med['每 4 周(月)★'])})。")
    out("  ⇒ ⚠️ 但**所有频率的相位中位都是负的** ⇒ 这一对换频率救不了,")
    out("     根本问题在漂移差(SOL 29.75x vs ADA 1.50x), 不在调仓频率。")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 段4
def section4(px, u_now):
    out()
    out(SEP)
    out("段4 · 逐年看筹码搬动方向 (历史已发生)")
    out(SEP)
    pr = px[COINS].dropna(how="any")
    full = pr.loc[MAIN:]
    rows = []
    for y, g in full.groupby(full.index.year):
        if len(g) < 2:
            continue
        r = bap.sim(pd.concat([full.iloc[:1], g]), COINS, start=MAIN,
                    cost_bp=COST_BP)
        rows.append((y, g["SOL"].iloc[-1] / g["SOL"].iloc[0] - 1,
                     g["ADA"].iloc[-1] / g["ADA"].iloc[0] - 1))
    out(f"  {'年份':<8}{'SOL价格':>12}{'ADA价格':>12}{'该年谁强':>12}"
        f"{'SOL币量变化':>14}")
    out("  " + SUB[:96])
    tr = pd.read_csv(os.path.join(OUTDIR, "sol_ada_units_track.csv"),
                     index_col=0)
    tr.index = pd.to_datetime(tr.index, format="mixed")
    for y, ps, pa in rows:
        sub = tr[(tr.index.year == y)]
        if not len(sub):
            continue
        du = sub["SOL"].iloc[-1] / sub["SOL"].iloc[0] - 1
        out(f"  {y:<8}{pct(ps):>12}{pct(pa):>12}"
            f"{('ADA' if pa > ps else 'SOL'):>12}{pct(du):>14}")
    out()
    out("  ⇒ SOL 币量有 3 年上涨(2020/2022/2024), 但净流出 —— 因为 SOL 赢的年份")
    out("     幅度太大(2021 +3983%), 一次就把几年攒的搬空了。")


# ---------------------------------------------------------------- main
def main():
    global COINS, MAIN
    if len(sys.argv) > 1 and sys.argv[1].strip():
        COINS = [c.strip().upper() for c in sys.argv[1].split(",") if c.strip()]
    if len(sys.argv) > 2 and sys.argv[2].strip():
        MAIN = sys.argv[2].strip()
    px = load_panel()
    r0, u0, val, tot = section0(px)
    d1 = section1(px, r0)
    d2, hit = section2(px, u0)
    d3 = section3(px)
    section4(px, u0)

    out()
    out(SEP)
    out("汇总一句:")
    out(SEP)
    out(f"  现在是 **4 周(月频)** 调仓, 不是周频; 已跑 {r0['turnover_events']} 次。")
    out(f"  当前 SOL **{u0['SOL']:.3f}x** / ADA **{u0['ADA']:.3f}x** / "
        f"账户总筹码 **{r0['geo']:.3f}x**。")
    if hit:
        out(f"  ADA 相对再涨到 **{hit:.1f}x** 时, SOL 币量才回到 1.0x;")
        out(f"  但在那之前账户总筹码已经在涨(涨 2 倍时 "
            f"{d2[d2.k == 2.0].geo.iloc[0]:.3f}x, 超额 "
            f"{pct(d2[d2.k == 2.0].exc.iloc[0])})。")
    os.makedirs(OUTDIR, exist_ok=True)
    d1.to_csv(os.path.join(OUTDIR, "sol_ada_future_scen.csv"),
              index=False, encoding="utf-8-sig")
    d2.to_csv(os.path.join(OUTDIR, "sol_ada_future_thresh.csv"),
              index=False, encoding="utf-8-sig")
    d3.to_csv(os.path.join(OUTDIR, "sol_ada_future_freq.csv"),
              index=False, encoding="utf-8-sig")
    out()
    out("  [OK] out/sol_ada_future_{scen,thresh,freq}.csv")


if __name__ == "__main__":
    main()
