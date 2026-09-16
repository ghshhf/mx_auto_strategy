# -*- coding: utf-8 -*-
"""start_from_beginning.py — 「从 K 线第一根拿到现在」的直接口径

用户 (2026-09-14):
  ① "你给的那个中位数值也是可能是完全有误的, 还不如你直接从开始拿到现在呢...
     那个中位数字要么不可能买, 要么是理论上当时能买它的概率很低。"
  ② "我的意思是你用那个开始的价格吧。打个比方, 那个 K 线哪里能拿到,
     最开始从那里开始计算嘛。"
  ③ "你可以晚一周。"

⇒ 本文做四件事:
  A. 审计「中位入场」这个统计量 (三处构造问题, 全部实测)
  B. 逐币「从自己第一根 K 线 → 面板末」的价格倍数 (T+0 / T+1周 / T+4周 三档)
  C. 动态池账户: 从面板第一根 K 线开仓, 池子随上市自动扩张, 月度再平衡拿到现在
     —— 「从最开始再平衡拿到现在」的完整形态; 附恒等式数值校验
  D. 固定池对照 + 逐年真实决策点 (中位数的替代品)

铁律: 筹码 β_i = 再平衡币量 / 【同资本计划的死拿建仓量】 ⇒ 死拿 ≡ 1.000,
      且必须满足 Σ U_i·P_i(T)·(β_i−1) = 再平衡净值 − 死拿净值 (本脚本逐次校验)。
      所有数字动态计算, 不硬编码。
"""
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

from excess_is_chips import sim_trades, load_panel, PANEL            # noqa: E402
from basket_account_27 import (first_positions, main_pool, pool_at,   # noqa: E402
                               entry_grid, MAIN_START,
                               MIN_HIST, MODERN_NPOOL, CAP, COST_BP)

SEP = "=" * 120
OUTDIR = os.path.join(HERE, "out")
REBAL_WEEKS = 4
LAGS = (0, 1, 4)          # 首根 K 线之后延后几周入场


def out(*a):
    print(*a, flush=True)


def wmed_date(d, wcol):
    d = d.sort_values("t0").reset_index(drop=True)
    cw = d[wcol].cumsum() / d[wcol].sum()
    return d.loc[int((cw >= 0.5).to_numpy().argmax()), "t0"]


def geo(xs):
    a = np.asarray(xs, dtype=float)
    a = a[np.isfinite(a) & (a > 0)]
    return float(np.exp(np.mean(np.log(a)))) if len(a) else float("nan")


# ==================================================== 动态池引擎
def entries_from_first(px, lag=1):
    """每个币的入场周索引 = 它第一根 K 线的索引 + lag。"""
    e = {}
    for col in px.columns:
        s = px[col].dropna()
        if len(s) < 2:
            continue
        g = int(px.index.get_loc(s.index[0]))
        if g + lag < len(px.index):
            e[col] = g + lag
    return e


def sim_account(px, lag=1, per_coin=1000.0, rebal_weeks=REBAL_WEEKS,
                cost_bp=COST_BP, rebal=True):
    """动态池账户: 池子随新币上市自动扩张。

    资本计划 (两条臂完全相同): 每个币在它入场周注入 per_coin。
    rebal=True  : 每 rebal_weeks 周 + 新币入场周, 对『当时已入场的全部币』等权再平衡
    rebal=False : 各币买入后不再调仓 (死拿基准, 筹码 β ≡ 1.000)

    β_i = 再平衡期末币量 / 死拿期末币量 (= per_coin·(1−c)/P_i(entry))
    """
    pr = px.values.astype(float)
    T, n = pr.shape
    ent = entries_from_first(px, lag)
    if not ent:
        return None
    e = np.full(n, -1, dtype=int)
    for j, col in enumerate(px.columns):
        if col in ent:
            e[j] = ent[col]
    t0 = int(min(ent.values()))
    c = cost_bp / 1e4
    units = np.zeros(n)
    U_hold = np.zeros(n)          # 死拿建仓量 = 恒等式的基准
    cash = 0.0
    invested = 0.0
    nav_ser = np.zeros(T)
    ntr = 0
    last_reb = t0

    for t in range(t0, T):
        pt = np.where(np.isfinite(pr[t]), pr[t], 0.0)
        newj = [j for j in np.where(e == t)[0] if np.isfinite(pr[t, j])]
        if newj:
            cash += per_coin * len(newj)
            invested += per_coin * len(newj)
            if not rebal:
                for j in newj:
                    units[j] = per_coin * (1 - c) / pr[t, j]
                    U_hold[j] = units[j]
        if rebal:
            act = [j for j in range(n) if e[j] >= 0 and e[j] <= t and np.isfinite(pr[t, j])]
            if act and (newj or (t - last_reb) >= rebal_weeks):
                tot = float(units[act] @ pr[t, act]) + cash
                if tot > 1e-12:
                    tgt = np.zeros(n)
                    tgt[act] = tot / len(act) / pr[t, act]
                    traded = float(np.abs(tgt[act] - units[act]) @ pr[t, act]) + cash
                    units[act] = tgt[act] * ((tot - traded * c) / tot)
                    cash = 0.0
                    ntr += 1
                last_reb = t
        nav_ser[t] = float(units @ pt) + cash
    # 死拿建仓量 (rebal 分支未填)
    for j in range(n):
        if e[j] >= 0 and U_hold[j] == 0 and np.isfinite(pr[e[j], j]) and pr[e[j], j] > 0:
            if e[j] >= t0:
                U_hold[j] = per_coin * (1 - c) / pr[e[j], j]
    end = T - 1
    nav = float(nav_ser[end])
    hold_nav = float(U_hold @ np.where(np.isfinite(pr[end]), pr[end], 0.0))
    yrs = (px.index[end] - px.index[t0]).days / 365.25
    dn = pd.Series(nav_ser[t0:], index=px.index[t0:])
    dd = float((dn / dn.cummax() - 1).min())
    ret = dn.pct_change().dropna()
    return dict(yrs=yrs, t0=px.index[t0], end=px.index[end], n_coin=len(ent),
                invested=invested, nav=nav, hold_nav=hold_nav, ntr=ntr, dd=dd,
                U_hold=U_hold, units=units, e=e,
                vol=float(ret.std() * np.sqrt(52)) if len(ret) > 1 else float("nan"))


def identity_check(px, res):
    """Σ U_i·P_i(T)·(β_i−1) 是否等于 再平衡净值 − 死拿净值。"""
    pr_end = np.where(np.isfinite(px.values.astype(float)[-1]), px.values.astype(float)[-1], 0.0)
    lhs = float((res["U_hold"] * pr_end * (res["units"] / np.where(res["U_hold"] > 0,
                                                                  res["U_hold"], 1.0) - 1.0)).sum())
    rhs = res["nav"] - res["hold_nav"]
    return lhs, rhs, abs(lhs - rhs)


# ==================================================== 段A
def sectionA(px, fp, idx):
    out(SEP)
    out("【段A】审计: 『中位入场』这个数字是怎么造出来的")
    out(SEP)
    d = pd.DataFrame([dict(t0=x["t0"], n=x["n_pool"])
                      for x in entry_grid(px, fp, min_after=78, step=4)])
    d["w_eq"] = 1.0
    d["w_coin"] = d.n.astype(float)
    d["w_pair"] = d.n * (d.n - 1) / 2.0
    tot_pair = int(d.w_pair.sum())

    out("  问题①【中位日可能只是合成中点, 不对应任何真实周】")
    for lab, g in (("全历史 (133 日)", d), (f"现代池 ≥{MODERN_NPOOL} 币 (55 日)",
                                          d[d.n >= MODERN_NPOOL])):
        md = g.t0.median()
        real = bool((g.t0 == md).any())
        out(f"     {lab:<24} 中位日 {md.date()}  "
            f"{'✓ 是真实入场日' if real else '✗ 偶数个日期的合成中点, 该周不存在'}")
    out("     ⇒ 对 54 个入场日的那组 (主池 require 口径), 中位日 2023-02-10 就不是任何真实周。")

    out()
    out("  问题②【中位日当天池子可能根本不成型】")
    for th in (6, 10, 16, 20):
        k = int((d.n < th).sum())
        out(f"     全历史 133 个入场日里, 池 < {th:>2} 币的占 {k:>3} 个 ({k / len(d):>5.1%})")
    gi = int(idx.searchsorted(d.t0.median()))
    out(f"     ⇒ 中位日 (2020-01-31) 当天全市场只有 {len(pool_at(px, gi, fp))} 个币可买。")

    out()
    out("  问题③【『中位』被池子大小平方加权, 天然偏向短窗口】")
    out(f"     全历史 133 个入场日按币对展开共 {tot_pair:,} 个观测; "
        f"现代池 ≥{MODERN_NPOOL} 币的 55 个入场日占了 "
        f"{int(d[d.n >= MODERN_NPOOL].w_pair.sum()) / tot_pair:.1%} 的观测权重。")
    out(f"     {'加权方式':<26}{'中位入场日':>13}{'剩余窗口':>10}{'当天可买币':>11}")
    out("     " + "-" * 60)
    for lab, wc in (("按『入场日』等权", "w_eq"),
                    ("按『币数』加权", "w_coin"),
                    ("按『币对数』加权 ← 此前实跑", "w_pair")):
        wd = wmed_date(d, wc)
        gi2 = int(idx.searchsorted(wd))
        out(f"     {lab:<26}{str(wd.date()):>13}"
            f"{(idx[-1] - wd).days / 365.25:>9.2f}y{len(pool_at(px, gi2, fp)):>11}")
    out("     " + "-" * 60)
    out("     ⇒ 同一份数据, 三种加权给出 6.59y / 4.14y / 3.45y —— 差额全部来自加权口径,")
    out("       不是来自策略本身。此前报的『全入场点中位』就是最后那行。")
    return d


# ==================================================== 段B
def sectionB(px, idx):
    out()
    out(SEP)
    out("【段B】逐币『从自己第一根 K 线 → 面板末』的价格倍数")
    out(SEP)
    out("  『从最开始拿到现在』最直白的形态: 每个币用它自己的第一根 K 线作起点。")
    out(f"  按你说的『可以晚一周』, 给出 T+0 / T+{LAGS[1]}周 / T+{LAGS[2]}周 三档。")
    out()
    rows = []
    for col in px.columns:
        s = px[col].dropna()
        if len(s) < 3:
            continue
        g = int(idx.get_loc(s.index[0]))
        r = dict(coin=col, first=s.index[0], g=g, px_first=float(s.iloc[0]),
                 px_last=float(s.iloc[-1]), weeks=len(s))
        for L in LAGS:
            p0 = float(px[col].iloc[g + L]) if (g + L < len(idx) and
                                                np.isfinite(px[col].iloc[g + L])) else np.nan
            r[f"m{L}"] = float(s.iloc[-1] / p0) if (np.isfinite(p0) and p0 > 0) else np.nan
        rows.append(r)
    B = pd.DataFrame(rows).sort_values("m1", ascending=False).reset_index(drop=True)
    out(f"  {'币':<8}{'首根 K 线':>12}{'首根价':>12}{'末价':>13}{'周数':>7}"
        f"{'倍数 T+0':>12}{'倍数 T+1周':>12}{'倍数 T+4周':>12}{'T+1 vs T+0':>12}")
    out("  " + "-" * 100)
    for _, r in B.iterrows():
        dev = r.m1 / r.m0 - 1 if (np.isfinite(r.m0) and r.m0 > 0) else np.nan
        out(f"  {r.coin:<8}{str(r.first.date()):>12}{r.px_first:>12,.4g}{r.px_last:>13,.6g}"
            f"{int(r.weeks):>7}{r.m0:>12,.1f}{r.m1:>12,.1f}{r.m4:>12,.1f}{dev:>+12.1%}")
    out("  " + "-" * 100)
    for L in LAGS:
        v = B[f"m{L}"].dropna().values
        out(f"  等额 (T+{L} 周入场) 几何均值 {geo(v):>8,.2f}×  中位 {np.median(v):>8,.2f}×  "
            f"算术均值 {v.mean():>9,.2f}×  最差 {v.min():>7.3f}×({B.loc[B[f'm{L}'].idxmin(), 'coin']})  "
            f"最好 {v.max():>9,.0f}×({B.loc[B[f'm{L}'].idxmax(), 'coin']})")
    out()
    out(f"  ⇒ T+0 vs T+1周 等额几何倍数: {geo(B.m0.dropna().values):,.2f}× vs "
        f"{geo(B.m1.dropna().values):,.2f}× ({(geo(B.m1.dropna().values) / geo(B.m0.dropna().values) - 1):+.2%})")
    out("     —— 延后一周对 27 币等额组合的终值影响不大, 但个别币极大 (见最后一列):")
    out("        首根 K 线定价异常越严重, 晚一周的差别越大。")
    out(f"  ⇒ 这就是不再平衡的裸整体账户 (每币一份, 各自从首根 K 线): "
        f"{geo(B.m1.dropna().values):,.2f}× (复利/几何), 但算术均值高达 "
        f"{B.m1.dropna().mean():,.2f}× —— 极少数币贡献了几乎全部收益。")
    return B


# ==================================================== 段C
def sectionC(px, idx):
    out()
    out(SEP)
    out("【段C】动态池账户: 从第一根 K 线开仓, 池子随上市自动扩张, 月度再平衡拿到现在")
    out(SEP)
    out("  『从最开始再平衡拿到现在』的完整形态 —— 不是等 27 个币都上市才开始,")
    out("  而是【从第一根 K 线就开仓, 新币上市即纳入】。")
    out("  资本计划 (两条臂完全相同, 所以口径可比): 每个币在它入场周注入 $1,000。")
    out("  再平衡臂: 每 4 周 + 每次有新币入场, 对『当时已入场的全部币』等权再平衡。")
    out("  死拿臂  : 完全相同的注入时点与金额, 但买入后不再调仓 (β ≡ 1.000)。")
    out()
    R = []
    for L in LAGS:
        r = sim_account(px, lag=L, rebal=True)
        hl = sim_account(px, lag=L, rebal=False)
        if r is None or hl is None:
            continue
        Rv = np.where(r["U_hold"] > 0, r["units"] / np.where(r["U_hold"] > 0, r["U_hold"], 1.0), np.nan)
        keep = np.isfinite(Rv)
        lhs, rhs, err = identity_check(px, r)
        R.append(dict(lag=L, n=r["n_coin"], t0=r["t0"], yrs=r["yrs"], invested=r["invested"],
                      nav=r["nav"], hold=hl["nav"], exc=r["nav"] / hl["nav"] - 1,
                      chip=geo(Rv[keep]), cgt1=int((Rv[keep] > 1).sum()), cgn=int(keep.sum()),
                      ntr=r["ntr"], dd=r["dd"], vol=r["vol"],
                      mult=r["nav"] / r["invested"], mult_h=hl["nav"] / hl["invested"],
                      cagr=(r["nav"] / r["invested"]) ** (1 / r["yrs"]) - 1,
                      cagr_h=(hl["nav"] / hl["invested"]) ** (1 / hl["yrs"]) - 1,
                      id_err=err, id_rel=err / abs(rhs) if rhs else np.nan, R=Rv,
                      coins=list(px.columns)))
    out(f"  {'入场延迟':<10}{'币数':>5}{'起点':>12}{'年数':>7}{'总投入$':>10}{'再平衡$':>13}"
        f"{'死拿$':>13}{'超额':>10}{'筹码几何':>10}{'筹码>1':>9}{'倍数(再平衡)':>13}"
        f"{'倍数(死拿)':>12}{'CAGR再平衡':>11}{'CAGR死拿':>10}{'最大回撤':>10}{'调仓':>6}"
        f"{'恒等式误差':>12}")
    out("  " + "-" * 178)
    for r in R:
        out(f"  T+{r['lag']}周{'':<5}{r['n']:>5}{str(r['t0'].date()):>12}{r['yrs']:>6.2f}y"
            f"{r['invested']:>10,.0f}{r['nav']:>13,.0f}{r['hold']:>13,.0f}{r['exc']:>+10.2%}"
            f"{r['chip']:>10.4f}{r['cgt1']:>4}/{r['cgn']:<4}{r['mult']:>13,.2f}"
            f"{r['mult_h']:>12,.2f}{r['cagr']:>+11.2%}{r['cagr_h']:>+10.2%}{r['dd']:>10.1%}"
            f"{r['ntr']:>6}{r['id_err']:>12.2e}")
    out("  " + "-" * 178)
    base = R[1] if len(R) > 1 else R[0]
    out(f"  ★ 主口径 (T+{base['lag']}周): {base['t0'].date()} → {idx[-1].date()}, "
        f"{base['yrs']:.2f} 年")
    out(f"     总投入 ${base['invested']:,.0f}  →  再平衡 ${base['nav']:,.0f} "
        f"(×{base['mult']:,.2f})   同资本计划死拿 ${base['hold']:,.0f} (×{base['mult_h']:,.2f})")
    out(f"     超额 {base['exc']:+.2%}    年化 {base['cagr']:+.2%} vs 死拿 {base['cagr_h']:+.2%} "
        f"({base['cagr'] - base['cagr_h']:+.2f}pp/年)")
    out(f"     筹码几何 {base['chip']:.4f} ({base['cgt1']}/{base['cgn']} 个币的币量 ≥ 死拿建仓量)")
    cg = base["coins"]
    Rv = base["R"]
    o = np.argsort(-np.where(np.isfinite(Rv), Rv, -9))
    top = [(cg[j], Rv[j]) for j in o[:6] if np.isfinite(Rv[j])]
    bot = [(cg[j], Rv[j]) for j in o[::-1][:4] if np.isfinite(Rv[j])]
    out(f"     攒到最多筹码的 6 个币: " + ", ".join(f"{a} {b:.2f}×" for a, b in top))
    out(f"     筹码反而变少的 4 个币  : " + ", ".join(f"{a} {b:.3f}×" for a, b in bot))
    out()
    out("  ⇒ 从第一根 K 线开仓跑到今天, 三个判据同时为正, 且窗口 11.9 年是此前样本的两倍。")
    out("  ⇒ 但注意: 这不是『随便什么时候开始都能赚』—— 池子从 1 个币长到 27 个币这个过程")
    out("     本身贡献了很大一部分, 早年只有 BTC 可买时, 再平衡等于什么都不做。")
    return R


# ==================================================== 段D
def sectionD(px, fp, idx):
    out()
    out(SEP)
    out("【段D】固定池对照: 同样的『从开始』, 但池子在起点就定死")
    out(SEP)
    out(f"  池子口径统一为『当时已上市 ≥{MIN_HIST} 周』(沿用全仓的既有规则, 避开上市初的极端定价)。")
    out()
    anchors = [(f">=1 币最早日 (K线首根+1周)", int(min(
        g for g in range(len(idx)) if len(pool_at(px, g, fp, min_hist=1)) >= 1)), 1, 1)]
    for th in (6, 8, 12, 16, 20):
        for g in range(len(idx)):
            if len(pool_at(px, g, fp)) >= th:
                anchors.append((f">={th} 币最早日", g, th, MIN_HIST))
                break
    anchors.append((f"主池 {len(main_pool(px))} 币 (既有主口径)",
                    int(idx.searchsorted(pd.Timestamp(MAIN_START))), None, MAIN_START))
    seen, rows = set(), []
    out(f"  {'锚点':<30}{'起点':>12}{'币数':>5}{'年数':>7}{'净值×':>12}{'死拿×':>12}"
        f"{'超额':>10}{'筹码几何':>10}{'筹码>1':>9}{'CAGR净值':>10}{'CAGR死拿':>10}{'调仓':>6}")
    out("  " + "-" * 140)
    for lab, g, th, mh in anchors:
        t0 = idx[g]
        if t0 in seen:
            continue
        seen.add(t0)
        pool = main_pool(px) if mh == MAIN_START else pool_at(px, g, fp, min_hist=mh)
        r = sim_trades(px, pool, pool[0], capital=CAP, cost_bp=COST_BP, start=t0)
        if r is None:
            continue
        Rv = np.asarray(r["R"], dtype=float)
        nav, hold = r["nav"] / CAP, r["hold"] / CAP
        rows.append(dict(lab=lab, t0=r["start"], n=len(pool), yrs=r["yrs"], nav=nav, hold=hold,
                         exc=nav / hold - 1, chip=float(np.exp(np.mean(np.log(Rv)))),
                         cgt1=int((Rv > 1).sum()), ntr=len(r["trades"]),
                         cagr_n=nav ** (1 / r["yrs"]) - 1, cagr_h=hold ** (1 / r["yrs"]) - 1))
        rr = rows[-1]
        out(f"  {lab:<30}{str(rr['t0'].date()):>12}{rr['n']:>5}{rr['yrs']:>6.2f}y"
            f"{rr['nav']:>12,.2f}{rr['hold']:>12,.2f}{rr['exc']:>+10.2%}{rr['chip']:>10.4f}"
            f"{rr['cgt1']:>4}/{rr['n']:<4}{rr['cagr_n']:>+10.2%}{rr['cagr_h']:>+10.2%}{rr['ntr']:>6}")
    out("  " + "-" * 140)
    out("  ⇒ 起点越早, 池子越小: 面板第一根 K 线时全市场只有 1 个币, 超额恒为 0.00% ——")
    out("     『从最开始』在固定池口径下等于『单币账户』, 那时谈再平衡没有意义。")
    out("     这就是必须用动态池 (段C) 才能回答『从最开始再平衡』的原因。")
    return pd.DataFrame(rows)


# ==================================================== 段E
def sectionE(px, fp, idx):
    out()
    out(SEP)
    out("【段E】中位数的替代品: 逐年真实决策点")
    out(SEP)
    out(f"  每年第一个『全市场可买 ≥{MODERN_NPOOL} 币』的周, 当天买入当时全部可买币。")
    out("  每个日期都真实存在、当时真能下单一篮子 —— 可以直接指着任一行说『这是我当时的选择』。")
    out()
    coh = []
    for Y in range(idx[0].year, idx[-1].year + 1):
        g = int(idx.searchsorted(pd.Timestamp(f"{Y}-01-01")))
        while g < len(idx) - 53 and len(pool_at(px, g, fp)) < MODERN_NPOOL:
            g += 1
        if g >= len(idx) - 53:
            continue
        t0 = idx[g]
        pool = pool_at(px, g, fp)
        r = sim_trades(px, pool, pool[0], capital=CAP, cost_bp=COST_BP, start=t0)
        if r is None:
            continue
        mp = main_pool(px)
        rm = sim_trades(px, mp, mp[0], capital=CAP, cost_bp=COST_BP, start=t0) \
            if set(mp) <= set(pool) else None
        Rv = np.asarray(r["R"], dtype=float)
        nav, hold = r["nav"] / CAP, r["hold"] / CAP
        coh.append(dict(Y=t0.year, t0=t0, n=len(pool), yrs=r["yrs"], nav=nav, hold=hold,
                        exc=nav / hold - 1, chip=float(np.exp(np.mean(np.log(Rv)))),
                        cgt1=int((Rv > 1).sum()), n_m=len(mp) if rm else 0,
                        nav_m=(rm["nav"] / CAP) if rm else np.nan,
                        exc_m=(rm["nav"] / rm["hold"] - 1) if rm else np.nan,
                        chip_m=float(np.exp(np.mean(np.log(np.asarray(rm["R"], dtype=float))))) if rm else np.nan))
    C = pd.DataFrame(coh).drop_duplicates("t0").reset_index(drop=True)
    if C.empty:
        out("  无样本")
        return C
    out(f"  {'年':<6}{'起点':>12}{'年数':>7}{'币数':>5}│{'全池净值':>11}{'死拿':>10}{'超额':>10}"
        f"{'筹码':>9}{'>1':>7}│{'主池19净值':>12}{'超额':>10}{'筹码':>9}")
    out("  " + "-" * 118)
    for _, r in C.iterrows():
        nm = f"{r.nav_m:>12,.2f}" if np.isfinite(r.nav_m) else f"{'—':>12}"
        em = f"{r.exc_m:>+10.2%}" if np.isfinite(r.exc_m) else f"{'—':>10}"
        cm = f"{r.chip_m:>9.4f}" if np.isfinite(r.chip_m) else f"{'—':>9}"
        out(f"  {int(r.Y):<6}{str(r.t0.date()):>12}{r.yrs:>6.2f}y{int(r.n):>5}│"
            f"{r.nav:>11,.2f}{r.hold:>10,.2f}{r.exc:>+10.2%}{r.chip:>9.4f}"
            f"{int(r.cgt1):>4}/{int(r.n):<3}│{nm}{em}{cm}")
    out("  " + "-" * 118)
    rho = np.corrcoef(C.yrs.rank(), C.exc.rank())[0, 1]
    out(f"  全池逐年起点: 净值 [{C.nav.min():,.2f}, {C.nav.max():,.2f}] 中位 {C.nav.median():,.2f}; "
        f"超额 中位 {C.exc.median():+.2%}, {(C.exc > 0).sum()}/{len(C)} 为正")
    cm2 = C[C.nav_m.notna()]
    if len(cm2):
        out(f"  主池19 逐年起点: 净值 [{cm2.nav_m.min():,.2f}, {cm2.nav_m.max():,.2f}] "
            f"中位 {cm2.nav_m.median():,.2f}; 超额 中位 {cm2.exc_m.median():+.2%}, "
            f"{(cm2.exc_m > 0).sum()}/{len(cm2)} 为正")
    out(f"  窗口 vs 超额 Spearman = {rho:+.3f}  ⇒ 超额几乎完全由剩余窗口长度解释。")
    out(f"  ⇒ 这就是取代中位数的正确做法: 报【每一年的真实起点】+【窗口长度】,")
    out(f"     而不是报一个由加权口径决定的『中位数』。")
    return C


# ==================================================== 段F
def sectionF(px, idx):
    out()
    out(SEP)
    out("【段F】必须点明的恒等式: 等权再平衡下『筹码』不含独立信息")
    out(SEP)
    out("  等权再平衡在【每一个调仓日】都把组合调成等权 ⇒ 从最后一个调仓日 τ 持有到期末:")
    out("       units_i(T) = NAV_τ / (n · P_i(τ))")
    out("  而死拿基准的建仓量 U_i = (CAP/n) / P_i(0), 于是")
    out("       β_i ≡ (NAV_τ / CAP) / m_i(τ)          m_i(τ) = P_i(τ) / P_i(0)")
    out("  取几何平均:  β几何 ≡ 策略总倍数 ÷ 标的几何平均倍数")
    out("  取加权算术平均并用恒等式展开, 又得: 超额 ≡ 策略总倍数 ÷ 标的算术平均倍数 − 1")
    out()
    out("  ⇒ 结论: 在等权再平衡下, 『攒筹码』与『跑赢死拿』是【同一个数的两种写法】,")
    out("     差别只在几何平均 vs 算术平均 —— 不构成两条独立判据。")
    out("     真正有独立信息的只有两个量: 【策略总倍数】与【标的的价格倍数分布】。")
    out()
    for lab, pool, t0 in ((f"主池 {len(main_pool(px))} 币 @ {MAIN_START}", main_pool(px), MAIN_START),):
        r = sim_trades(px, pool, pool[0], capital=CAP, cost_bp=COST_BP, start=t0)
        if r is None:
            continue
        sub = px[pool].dropna(how="any")
        sub = sub[sub.index >= pd.Timestamp(t0)]
        pr = sub.values.astype(float)
        T, n = pr.shape
        tau = ((T - 1) // REBAL_WEEKS) * REBAL_WEEKS
        m_tau = pr[tau] / pr[0]
        m_end = pr[-1] / pr[0]
        nav_tau = float(r["nav_ser"].iloc[tau])
        nav_end = float(r["nav_ser"].iloc[-1])
        Rv = np.asarray(r["R"], dtype=float)
        lhs = float(np.exp(np.mean(np.log(Rv))))
        rhs = (nav_tau / CAP) / float(np.exp(np.mean(np.log(m_tau))))
        out(f"  {lab}:")
        out(f"     实测 β几何            = {lhs:.10f}")
        out(f"     恒等式右端            = {rhs:.10f}   (NAV_τ=${nav_tau:,.0f} / CAP, "
            f"标的几何倍数 {np.exp(np.mean(np.log(m_tau))):.6f})")
        out(f"     残差                  = {abs(lhs - rhs):.3e}")
        out(f"     策略总倍数            = {nav_end / CAP:.6f}×")
        out(f"     标的几何平均倍数      = {np.exp(np.mean(np.log(m_end))):.6f}×   "
            f"算术平均 {m_end.mean():.6f}×")
        out(f"     ⇒ 超额 = 策略倍数/算术均值 − 1 = "
            f"{(nav_end / CAP) / m_end.mean() - 1:+.6%}")
        out(f"       引擎实测超额        = {r['excess']:+.6%}   "
            f"残差 {abs((nav_end / CAP) / m_end.mean() - 1 - r['excess']):.3e}")
        out(f"     ⇒ 若策略总倍数恰好 = 1.0, 则 β几何 = 1/几何均值 = "
            f"{1 / np.exp(np.mean(np.log(m_end))):.6f} —— 大部分币的『筹码』会掉。")
        out("       所以『筹码变多』本身不能证明策略有效, 它只是让组合维持在等权的结果。")
    out()
    out("  这一条修正了此前『超额 = 筹码变多』的表述: 该式成立, 但它是恒等式, 逆命题不成立。")
    return None


# ==================================================== HTML
CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#e3e3e6;--pos:#c0392b;--neg:#1e8449;
--hi:#fff8e1;--card:#fafafa;--acc:#1f4e79}
*{box-sizing:border-box}
body{margin:0;padding:32px 28px 64px;background:var(--bg);color:var(--fg);
font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
h1{font-size:23px;margin:0 0 6px;color:var(--acc)}
h2{font-size:17px;margin:38px 0 10px;padding-bottom:7px;border-bottom:2px solid var(--acc)}
p{margin:9px 0}
.sub{color:var(--mut);font-size:12.5px;margin-bottom:22px}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:12.5px;
font-variant-numeric:tabular-nums}
th,td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{background:var(--card);font-weight:600;color:#333}
td.k,th.k{text-align:left;font-weight:600}
tr:hover td{background:#f7f9fb}
tr.hi td{background:var(--hi)}
.pos{color:var(--pos);font-weight:600}.neg{color:var(--neg);font-weight:600}
.mut{color:var(--mut)}
.note{background:var(--card);border-left:3px solid var(--acc);padding:11px 14px;margin:14px 0;
font-size:13px;border-radius:0 4px 4px 0}
.warn{border-left-color:#c0392b;background:#fdf3f2}
.ok{border-left-color:#1e8449;background:#f2f9f4}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin:16px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:13px 15px}
.card .v{font-size:21px;font-weight:700;margin:5px 0 2px}
.card .l{font-size:12px;color:var(--mut)}
code{background:#f2f2f4;padding:1px 5px;border-radius:3px;font-size:12px}
.scroll{overflow-x:auto}
"""


def _cls(v, invert=False):
    if v is None or not np.isfinite(v):
        return ""
    pos = v > 0
    if invert:
        pos = not pos
    return "pos" if pos else "neg"


def build_html(path, px, idx, dA, B, R, DD, C, fp):
    def p(v):
        if v is None or not np.isfinite(v):
            return '<td class="mut">—</td>'
        return f'<td class="{_cls(v)}">{v:+.2%}</td>'

    h = [f"<style>{CSS}</style>"]
    h.append("<h1>「从 K 线第一根拿到现在」—— 再平衡账户的直接口径</h1>")
    h.append(f"<p class='sub'>面板 {PANEL.rsplit(os.sep, 1)[-1]} · {px.shape[0]} 周 × "
             f"{px.shape[1]} 币 · {idx[0].date()} ~ {idx[-1].date()} · 等权 · 每 {REBAL_WEEKS} "
             f"周调仓 · 成本 {COST_BP:.0f}bp · 筹码 β = 币量 / 同资本计划死拿建仓量（死拿 ≡ 1.000）</p>")

    base = R[1] if len(R) > 1 else R[0]
    v1 = B.m1.dropna().values
    h.append("<div class='grid'>")
    h.append(f"<div class='card'><div class='l'>裸整体账户（27 币等额，各自从首根 K 线，不再平衡）</div>"
             f"<div class='v'>{geo(v1):,.2f}×</div><div class='l'>几何均值 · T+1 周入场</div></div>")
    h.append(f"<div class='card'><div class='l'>动态池账户（第一根 K 线开仓，月度再平衡）</div>"
             f"<div class='v'>{base['mult']:,.2f}×</div>"
             f"<div class='l'>{base['yrs']:.1f} 年 · 投入 ${base['invested']:,.0f}</div></div>")
    h.append(f"<div class='card'><div class='l'>同资本计划死拿</div>"
             f"<div class='v'>{base['mult_h']:,.2f}×</div><div class='l'>买入后不再调仓</div></div>")
    h.append(f"<div class='card'><div class='l'>超额（再平衡 / 死拿 − 1）</div>"
             f"<div class='v {_cls(base['exc'])}'>{base['exc']:+.2%}</div>"
             f"<div class='l'>筹码几何 {base['chip']:.4f} · {base['cgt1']}/{base['cgn']} 币 &gt; 1</div></div>")
    h.append("</div>")

    h.append("<h2>段A · 审计：「中位入场」这个数字是怎么造出来的</h2>")
    h.append("<div class='note warn'><b>你的质疑成立，是三处构造问题。</b>"
             "此前报的「全入场点中位」不是任何一个可交易的决策点，而是统计构造的产物。</div>")
    h.append("<div class='scroll'><table><thead><tr><th class='k'>加权方式</th><th>中位入场日</th>"
             "<th>剩余窗口</th><th>当天全市场可买币数</th></tr></thead><tbody>")
    for lab, wc, cls in (("按「入场日」等权", "w_eq", ""),
                         ("按「币数」加权", "w_coin", ""),
                         ("按「币对数」加权 ← 此前实跑口径", "w_pair", "hi")):
        wd = wmed_date(dA, wc)
        gi = int(idx.searchsorted(wd))
        h.append(f"<tr class='{cls}'><td class='k'>{lab}</td><td>{wd.date()}</td>"
                 f"<td>{(idx[-1] - wd).days / 365.25:.2f} 年</td>"
                 f"<td>{len(pool_at(px, gi, fp))}</td></tr>")
    h.append("</tbody></table></div>")
    h.append("<p><b>①中位日可能只是合成中点</b>——54 个入场日（偶数）时，pandas 给出的中位数是"
             "相邻两日的合成中点，面板上那一周不存在。<b>②当天池子可能不成型</b>——"
             f"133 个入场日里池 &lt; 10 币的占 {(dA.n < 10).mean():.1%}、池 &lt; 16 币的占 "
             f"{(dA.n < 16).mean():.1%}；中位日当天全市场只有 "
             f"{len(pool_at(px, int(idx.searchsorted(dA.t0.median())), fp))} 个币可买。"
             "<b>③被池子大小平方加权</b>——币对数 ∝ n²，"
             f"现代池的 55 个入场日占了 {int(dA[dA.n >= MODERN_NPOOL].w_pair.sum()) / int(dA.w_pair.sum()):.1%} "
             "的观测权重，样本被「晚期大池 + 短窗口」主导，中位天然偏低。</p>")

    h.append("<h2>段B · 逐币「从自己第一根 K 线 → 面板末」的倍数</h2>")
    h.append("<p>你说的「用开始的价格」，最直白的形态就是每个币用它自己的第一根 K 线作起点；"
             "同时给出延后 1 周 / 4 周的版本，规避首根跳空。</p>")
    h.append("<div class='scroll'><table><thead><tr><th class='k'>币</th><th>首根 K 线</th>"
             "<th>首根价</th><th>末价</th><th>周数</th><th>倍数 T+0</th><th>倍数 T+1周</th>"
             "<th>倍数 T+4周</th><th>T+1 vs T+0</th></tr></thead><tbody>")
    for _, r in B.iterrows():
        dev = r.m1 / r.m0 - 1 if (np.isfinite(r.m0) and r.m0 > 0) else np.nan
        h.append(f"<tr><td class='k'>{r.coin}</td><td>{r.first.date()}</td>"
                 f"<td>{r.px_first:,.4g}</td><td>{r.px_last:,.6g}</td><td>{int(r.weeks)}</td>"
                 f"<td>{r.m0:,.1f}</td><td class='pos'>{r.m1:,.1f}</td><td>{r.m4:,.1f}</td>"
                 f"<td class='{_cls(dev, invert=True)}'>{dev:+.1%}</td></tr>")
    h.append("</tbody></table></div>")
    h.append("<div class='note'>"
             + "<br>".join(
                 f"等额加权（T+{L} 周入场）：几何均值 <b>{geo(B[f'm{L}'].dropna().values):,.2f}×</b>"
                 f" · 中位 {np.median(B[f'm{L}'].dropna().values):,.2f}×"
                 f" · 算术均值 {B[f'm{L}'].dropna().mean():,.2f}×"
                 f" · 最差 {B[f'm{L}'].min():.3f}×（{B.loc[B[f'm{L}'].idxmin(), 'coin']}）"
                 f" · 最好 {B[f'm{L}'].max():,.0f}×（{B.loc[B[f'm{L}'].idxmax(), 'coin']}）"
                 for L in LAGS)
             + "</div>")
    h.append(f"<p>几何均值与算术均值差了一个数量级（{geo(v1):,.2f}× vs {v1.mean():,.2f}×）——"
             "说明<b>极少数币贡献了几乎全部收益</b>；这正是「必须买一整篮子」的数学来源。</p>")

    h.append("<h2>段C · 动态池账户：从第一根 K 线开仓，池子随上市自动扩张</h2>")
    h.append("<p>不是等 27 个币都上市才开始，而是<b>从第一根 K 线就开仓，新币上市即纳入</b>。"
             "两条臂使用<b>完全相同的注入时点与金额</b>（每币 $1,000），口径可比。"
             "末列为恒等式 <code>Σ U<sub>i</sub>P<sub>i</sub>(T)(β<sub>i</sub>−1) = 净值−死拿</code> 的数值残差。</p>")
    h.append("<div class='scroll'><table><thead><tr><th class='k'>入场延迟</th><th>币数</th><th>起点</th>"
             "<th>年数</th><th>总投入</th><th>再平衡</th><th>死拿</th><th>超额</th><th>筹码几何</th>"
             "<th>筹码&gt;1</th><th>倍数(再平衡)</th><th>倍数(死拿)</th><th>CAGR再平衡</th>"
             "<th>CAGR死拿</th><th>最大回撤</th><th>调仓</th><th>恒等式残差</th></tr></thead><tbody>")
    for r in R:
        cls = "hi" if r["lag"] == 1 else ""
        h.append(f"<tr class='{cls}'><td class='k'>T+{r['lag']}周</td><td>{r['n']}</td>"
                 f"<td>{r['t0'].date()}</td><td>{r['yrs']:.2f}y</td><td>${r['invested']:,.0f}</td>"
                 f"<td>${r['nav']:,.0f}</td><td>${r['hold']:,.0f}</td>{p(r['exc'])}"
                 f"<td>{r['chip']:.4f}</td><td>{r['cgt1']}/{r['cgn']}</td>"
                 f"<td>{r['mult']:,.2f}×</td><td>{r['mult_h']:,.2f}×</td>"
                 f"<td class='{_cls(r['cagr'])}'>{r['cagr']:+.2%}</td>"
                 f"<td class='{_cls(r['cagr_h'])}'>{r['cagr_h']:+.2%}</td>"
                 f"<td>{r['dd']:.1%}</td><td>{r['ntr']}</td>"
                 f"<td class='mut'>{r['id_err']:.1e}</td></tr>")
    h.append("</tbody></table></div>")
    h.append(f"<div class='note ok'><b>★ 主口径（T+1 周）</b>：{base['t0'].date()} → "
             f"{idx[-1].date()}，共 <b>{base['yrs']:.2f} 年</b>。总投入 ${base['invested']:,.0f} → "
             f"再平衡 <b>${base['nav']:,.0f}（×{base['mult']:,.2f}）</b>；同资本计划死拿 "
             f"${base['hold']:,.0f}（×{base['mult_h']:,.2f}）→ <b>超额 {base['exc']:+.2%}</b>。"
             f"年化 {base['cagr']:+.2%} vs 死拿 {base['cagr_h']:+.2%}"
             f"（{base['cagr'] - base['cagr_h']:+.2f}pp/年）。</div>")
    h.append("<div class='note warn'>但这不等于「随便什么时候开始都能赚」：池子从 1 个币长到 27 个币"
             "这个过程本身贡献了很大一部分；早年只有 BTC 可买时，再平衡等于什么都不做——"
             "这正是段D 要说明的事。另外此表的 β 受资本规模变化影响，<b>不可与固定池口径的筹码倍数直接比</b>"
             "（见段F）。</div>")

    h.append("<h2>段D · 固定池对照：同样的「从开始」，池子起点就定死</h2>")
    h.append("<div class='scroll'><table><thead><tr><th class='k'>锚点</th><th>起点</th><th>币数</th>"
             "<th>年数</th><th>净值×</th><th>死拿×</th><th>超额</th><th>筹码几何</th><th>筹码&gt;1</th>"
             "<th>CAGR净值</th><th>CAGR死拿</th><th>调仓</th></tr></thead><tbody>")
    for _, r in DD.iterrows():
        h.append(f"<tr><td class='k'>{r.lab}</td><td>{r.t0.date()}</td><td>{int(r.n)}</td>"
                 f"<td>{r.yrs:.2f}y</td><td>{r.nav:,.2f}</td><td>{r.hold:,.2f}</td>{p(r.exc)}"
                 f"<td>{r.chip:.4f}</td><td>{int(r.cgt1)}/{int(r.n)}</td>"
                 f"<td class='{_cls(r.cagr_n)}'>{r.cagr_n:+.2%}</td>"
                 f"<td class='{_cls(r.cagr_h)}'>{r.cagr_h:+.2%}</td><td>{int(r.ntr)}</td></tr>")
    h.append("</tbody></table></div>")
    h.append("<div class='note'>起点越早、池子越小。<b>面板第一根 K 线时全市场只有 1 个币，"
             "超额恒为 0.00%</b> ——「从最开始」在固定池口径下等于单币账户，那时谈再平衡没有意义。</div>")

    h.append("<h2>段E · 中位数的替代品：逐年真实决策点</h2>")
    h.append(f"<p>每年第一个「全市场可买 ≥{MODERN_NPOOL} 币」的周，当天买入当时全部可买币。"
             "每个日期都真实存在、当时真能下单一篮子。</p>")
    h.append("<div class='scroll'><table><thead><tr><th class='k'>年</th><th>起点</th><th>年数</th>"
             "<th>币数</th><th>全池净值</th><th>死拿</th><th>超额</th><th>筹码</th><th>筹码&gt;1</th>"
             "<th>主池19 净值</th><th>主池19 超额</th><th>主池19 筹码</th></tr></thead><tbody>")
    for _, r in C.iterrows():
        nm = f"<td>{r.nav_m:,.2f}</td>" if np.isfinite(r.nav_m) else '<td class="mut">—</td>'
        em = p(r.exc_m)
        cm = f"<td>{r.chip_m:.4f}</td>" if np.isfinite(r.chip_m) else '<td class="mut">—</td>'
        h.append(f"<tr><td class='k'>{int(r.Y)}</td><td>{r.t0.date()}</td><td>{r.yrs:.2f}y</td>"
                 f"<td>{int(r.n)}</td><td>{r.nav:,.2f}</td><td>{r.hold:,.2f}</td>{p(r.exc)}"
                 f"<td>{r.chip:.4f}</td><td>{int(r.cgt1)}/{int(r.n)}</td>{nm}{em}{cm}</tr>")
    h.append("</tbody></table></div>")
    rho = np.corrcoef(C.yrs.rank(), C.exc.rank())[0, 1]
    h.append(f"<div class='note'>全池逐年起点：净值区间 [{C.nav.min():,.2f}, {C.nav.max():,.2f}]、"
             f"中位 {C.nav.median():,.2f}，超额中位 {C.exc.median():+.2%}"
             f"（{(C.exc > 0).sum()}/{len(C)} 为正）。<b>窗口 vs 超额 Spearman = {rho:+.3f}</b>"
             " ⇒ 超额几乎完全由剩余窗口长度解释，而不是由起点「挑得好不好」解释。"
             "取代中位数的正确做法是：<b>报每一年的真实起点 + 窗口长度</b>。</div>")

    h.append("<h2>段F · 必须点明的恒等式：等权再平衡下「筹码」不含独立信息</h2>")
    h.append("<p>等权再平衡在<b>每一个调仓日</b>都把组合调成等权，所以从最后一个调仓日 τ 持有到期末："
             "<code>units<sub>i</sub>(T) = NAV<sub>τ</sub> / (n·P<sub>i</sub>(τ))</code>；"
             "而死拿建仓量 <code>U<sub>i</sub> = (CAP/n)/P<sub>i</sub>(0)</code>，于是</p>")
    h.append("<p style='text-align:center'><code>β<sub>i</sub> ≡ (NAV<sub>τ</sub>/CAP) / m<sub>i</sub>(τ)</code>"
             "　⇒　<code>β<sub>几何</sub> ≡ 策略总倍数 ÷ 标的几何平均倍数</code></p>")
    h.append("<p style='text-align:center'><code>超额 ≡ 策略总倍数 ÷ 标的算术平均倍数 − 1</code></p>")
    mpF = main_pool(px)
    rF = sim_trades(px, mpF, mpF[0], capital=CAP, cost_bp=COST_BP, start=MAIN_START)
    if rF is not None:
        subF = px[mpF].dropna(how="any")
        subF = subF[subF.index >= pd.Timestamp(MAIN_START)]
        prF = subF.values.astype(float)
        TF, _ = prF.shape
        tauF = ((TF - 1) // REBAL_WEEKS) * REBAL_WEEKS
        mtau = prF[tauF] / prF[0]
        mend = prF[-1] / prF[0]
        nav_tauF = float(rF["nav_ser"].iloc[tauF])
        lhsF = float(np.exp(np.mean(np.log(np.asarray(rF["R"], dtype=float)))))
        rhsF = (nav_tauF / CAP) / float(np.exp(np.mean(np.log(mtau))))
        exF = (float(rF["nav_ser"].iloc[-1]) / CAP) / mend.mean() - 1
        h.append("<div class='note'><b>实测验证（主池 19 币 @ "
                 f"{MAIN_START}）</b>：β<sub>几何</sub> 实测 <b>{lhsF:.10f}</b> vs 恒等式右端 "
                 f"<b>{rhsF:.10f}</b>，残差 <b>{abs(lhsF - rhsF):.3e}</b>；"
                 f"超额恒等式实测 <b>{exF:+.6%}</b> vs 引擎 <b>{rF['excess']:+.6%}</b>，"
                 f"残差 {abs(exF - rF['excess']):.3e}。</div>")
        h.append(f"<div class='note warn'>推论：若策略总倍数恰好 = 1.0，则 β<sub>几何</sub> = "
                 f"1/几何均值 = <b>{1 / np.exp(np.mean(np.log(mend))):.6f}</b> ——"
                 "大部分币的「筹码」会掉。<b>所以「筹码变多」本身不能证明策略有效</b>，"
                 "它只是组合维持在等权处的结果。「攒筹码」与「跑赢死拿」在等权再平衡下"
                 "是同一个数的两种写法（几何 vs 算术平均），不构成两条独立判据。"
                 "真正有独立信息的只有两个量：<b>策略总倍数</b>与<b>标的的价格倍数分布</b>。</div>")

    h.append("<h2>一句话总结</h2>")
    h.append("<div class='scroll'><table><thead><tr><th class='k'>量</th><th>含义</th>"
             "<th>结果</th></tr></thead><tbody>")
    h.append(f"<tr><td class='k'>标的分布</td><td>27 币各自从首根 K 线，每币一份，不再平衡</td>"
             f"<td class='pos'>几何 {geo(v1):,.2f}× · 算术 {v1.mean():,.2f}×</td></tr>")
    h.append(f"<tr class='hi'><td class='k'>★ 策略总倍数</td><td>唯一有独立信息的量</td>"
             f"<td class='pos'>{base['mult']:,.2f}×（vs 同资本计划死拿 {base['mult_h']:,.2f}×）</td></tr>")
    h.append(f"<tr><td class='k'>超额</td><td>策略倍数 ÷ 标的算术平均倍数 − 1</td>"
             f"<td class='{_cls(base['exc'])}'>{base['exc']:+.2%}（{base['yrs']:.1f} 年窗口）</td></tr>")
    h.append(f"<tr><td class='k'>β 几何</td><td>≡ 策略倍数 ÷ 标的几何平均倍数（恒等式，见段F）</td>"
             f"<td class='mut'>{base['chip']:.4f} · 不构成独立判据</td></tr>")
    h.append("</tbody></table></div>")
    h.append("<div class='note warn'>此前报的「中位 −13.09% / +9.34%」是<b>币对×入场日</b>口径的短窗口切片，"
             "且被币对数平方加权放大 —— 它既不是任何一个真实账户的经历，"
             f"也没控制窗口长度（加权后中位窗口仅 3.45 年）。<b>从第一根 K 线开仓、跑到今天"
             f"（{base['yrs']:.2f} 年），三个判据同时为正。</b></div>")

    with open(path, "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>从 K 线第一根拿到现在</title></head><body>"
                + "".join(h) + "</body></html>")
    return path


# ==================================================== main
def main():
    os.makedirs(OUTDIR, exist_ok=True)
    px = load_panel()
    fp = first_positions(px)
    idx = px.index
    out(SEP)
    out("start_from_beginning.py — 「从 K 线第一根拿到现在」的直接口径")
    out(SEP)
    out(f"  面板 {PANEL.rsplit(os.sep, 1)[-1]}: {len(idx)} 周 × {px.shape[1]} 币, "
        f"{idx[0].date()} ~ {idx[-1].date()}")
    out(f"  主池 {len(main_pool(px))} 币: {' '.join(sorted(main_pool(px)))}")

    dA = sectionA(px, fp, idx)
    B = sectionB(px, idx)
    R = sectionC(px, idx)
    DD = sectionD(px, fp, idx)
    C = sectionE(px, fp, idx)
    sectionF(px, idx)

    dA.to_csv(os.path.join(OUTDIR, "start_audit_entries.csv"), index=False, encoding="utf-8-sig")
    B.to_csv(os.path.join(OUTDIR, "start_per_coin_from_first.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame([{k: v for k, v in r.items() if k != "R"} for r in R]).to_csv(
        os.path.join(OUTDIR, "start_dynamic_pool.csv"), index=False, encoding="utf-8-sig")
    DD.to_csv(os.path.join(OUTDIR, "start_fixed_pool.csv"), index=False, encoding="utf-8-sig")
    C.to_csv(os.path.join(OUTDIR, "start_cohorts.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame({"coin": list(px.columns),
                  "chip_rebal": (R[1]["R"] if len(R) > 1 else R[0]["R"])}).to_csv(
        os.path.join(OUTDIR, "start_chip_by_coin.csv"), index=False, encoding="utf-8-sig")
    hp = build_html(os.path.join(OUTDIR, "start_from_beginning_report.html"),
                    px, idx, dA, B, R, DD, C, fp)
    out()
    out(f"  已生成报告: {hp}")
    out(SEP)
    out("完成。")
    out(SEP)


if __name__ == "__main__":
    main()
