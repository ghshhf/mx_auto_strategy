# -*- coding: utf-8 -*-
"""
ashare_pair_all.py —— A 股行业龙头池(74 只) 全配对再平衡
=========================================================
口径与加密**完全一致**: 两只标的 · 目标 50:50 · 4 周调仓 · 10bp · 等额本金。
唯一区别: 标的是 A 股而不是币。

数据源: data/ashare_weekly_panel.csv (腾讯 fqkline hfq 后复权周线, 74 只 / 34 行业)
  —— 不用 Yahoo (它系统性缺交易日: 实测 000063 2019-04-26 后直接跳到 05-06,
     中间 4/29、4/30 整段没有, 3 天累积跌幅被记成单日 -15.3%, 会让除权检测误判);
  —— 不用 data/ashare/bars/*.json (未完整复权: 51 只个股里 36 只有共 146 次
     单日跌幅 < -15% 的假暴跌, 最低 -67%)。

段
--
  段0 口径与数据闸门        段1 池子概览(74 只/34 行业/上市分布/波动率)
  段2 分层全配对扫描        段3 主口径逐对明细(TOP/BOTTOM)
  段4 波动率 -> 收割空间    段5 跨行业 vs 同行业
  段6 逐股视角              段7 标的数效应(7 -> 74)
"""
import os
import sys
import importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# 🔒 再平衡核心算法收敛到跨市场唯一引擎 markets/core/rebalance.py (2026-09-15)
#    本文件的 sim_pair() 只保留「A股口径的返回契约」, 数值逻辑一律转发。
#    ⚠️ markets/us/us_pair_50_50.py 直接 import 本文件的 sim_pair ⇒ 美股自动跟随。
_spec_rb = importlib.util.spec_from_file_location(
    "rb_kernel", os.path.join(os.path.dirname(HERE), "core", "rebalance.py"))
_rb = importlib.util.module_from_spec(_spec_rb)
_spec_rb.loader.exec_module(_rb)
OUT = os.path.join(HERE, "out")
PANEL = os.path.join(DATA, "ashare_weekly_panel.csv")

REBAL_WEEKS = 4
COST_BP = 10.0
CAP = 10000.0
MIN_HIST = 26                     # 上市满 26 周(半年)才纳入, 避开新股连板噪声
MAIN_START = "2015-01-09"         # 主口径起点(与既有 7 只蓝筹报告同窗, 便于对账)
LAYERS = ["2005-01-07", "2010-01-08", "2015-01-09", "2018-01-05", "2020-01-03"]
SEP = "=" * 118


def out(*a):
    print(*a, flush=True)


def nm(col):
    return str(col).split("|")[0]


def code_of(col):
    return str(col).split("|")[-1]


def ind_of(name):
    try:
        from ashare_universe_build import NAMES, INDUS
        for c, n in NAMES.items():
            if n == name:
                return INDUS.get(c, "")
    except Exception:               # noqa: BLE001
        pass
    return ""


# ------------------------------------------------------------------ 面板
def load_px():
    px = pd.read_csv(PANEL, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index)
    px = px.sort_index()
    return px.ffill()               # 停牌/缺周 -> 沿用上次价格(无法交易)


def listed_before(px, col, d, min_hist=MIN_HIST):
    s = px[col].dropna()
    return len(s) > 0 and s.index[0] <= d - pd.Timedelta(weeks=min_hist)


def pool_at(px, d, min_hist=MIN_HIST):
    return [c for c in px.columns if listed_before(px, c, d, min_hist)]


# ------------------------------------------------------------------ 引擎
def sim_pair(pr, rebal_weeks=REBAL_WEEKS, cost_bp=COST_BP, capital=CAP):
    """两标的等权(即 50:50)周期再平衡。pr: (T, 2) 价格矩阵。"""
    T, n = pr.shape
    w = np.ones(n) / n
    # 🔒 核心循环 → 唯一引擎 (markets/core/rebalance.py)
    kr = _rb.rebalance_kernel(pr, rebal_weeks=rebal_weeks, cost_bp=cost_bp,
                              capital=capital)
    NAV = kr["NAV"]
    units, U0, ntr = kr["units"], kr["U0"], kr["ntr"]
    m = pr[-1] / pr[0]
    hold_mult = float((w * m).sum())
    nav_mult = float(NAV[-1] / capital)
    beta = units / U0
    return dict(nav_mult=nav_mult, hold_mult=hold_mult, exc=nav_mult / hold_mult - 1.0,
                beta=beta, chip_geo=float(np.exp(np.mean(np.log(beta)))), m=m, ntr=ntr)


def pct(x, d=2):
    return f"{x * 100:.{d}f}%"


def q(a, p):
    a = np.asarray([v for v in np.asarray(a, float) if np.isfinite(v)])
    return float(np.percentile(a, p)) if len(a) else float("nan")


def med(a):
    a = np.asarray([v for v in np.asarray(a, float) if np.isfinite(v)])
    return float(np.median(a)) if len(a) else float("nan")


def metrics(pr, yrs):
    """跑一对, 返回指标 dict"""
    r = sim_pair(pr)
    r["yrs"] = yrs
    r["chip_ann"] = r["chip_geo"] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    r["nav_cagr"] = r["nav_mult"] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    r["hold_cagr"] = r["hold_mult"] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    return r


def run_layer(px, label, t0, cols=None, min_hist=MIN_HIST):
    """在 t0 起、池内全配对。返回 (层统计 dict, 逐对 DataFrame)"""
    pool = cols if cols is not None else pool_at(px, t0, min_hist)
    if len(pool) < 2:
        return None, None
    sub = px[pool].loc[t0:].dropna(how="any")
    if len(sub) < REBAL_WEEKS * 2:
        return None, None
    yrs = (sub.index[-1] - sub.index[0]).days / 365.25
    arr = sub.values.astype(float)
    cols_l = list(sub.columns)
    rows = []
    for i in range(len(cols_l)):
        for j in range(i + 1, len(cols_l)):
            pr = arr[:, [i, j]]
            if not np.isfinite(pr).all():
                continue
            r = metrics(pr, yrs)
            rows.append(dict(A=nm(cols_l[i]), B=nm(cols_l[j]),
                             Aind=ind_of(nm(cols_l[i])), Bind=ind_of(nm(cols_l[j])),
                             yrs=yrs, chip_geo=r["chip_geo"], chip_ann=r["chip_ann"],
                             betaA=float(r["beta"][0]), betaB=float(r["beta"][1]),
                             exc=r["exc"], nav=r["nav_mult"], hold=r["hold_mult"],
                             nav_cagr=r["nav_cagr"], hold_cagr=r["hold_cagr"],
                             mA=float(r["m"][0]), mB=float(r["m"][1]), ntr=r["ntr"]))
    df = pd.DataFrame(rows)
    if not len(df):
        return None, None
    st = dict(label=label, t0=str(t0)[:10], end=str(sub.index[-1].date()),
              yrs=yrs, n=len(pool), npair=len(df),
              chip_med=float(df.chip_ann.median()), chip_mean=float(df.chip_ann.mean()),
              chip_pos=float((df.chip_geo > 1).mean()),
              exc_med=float(df.exc.median()), exc_mean=float(df.exc.mean()),
              exc_pos=float((df.exc > 0).mean()),
              nav_med=float(df.nav.median()), hold_med=float(df.hold.median()),
              both_gt1=float(((df.betaA > 1) & (df.betaB > 1)).mean()))
    return st, df


# ------------------------------------------------------------------ 段
def section0():
    out(SEP)
    out("段0 · 口径与数据闸门")
    out(SEP)
    out("  口径: 两只标的 · 目标 50:50 · 4 周调仓 · 10bp · 等额本金 —— 与加密完全一致")
    out(f"  标的: A 股行业龙头池 (能叫得出名字的各行业龙头), 上市满 {MIN_HIST} 周才纳入")
    out("  数据源: 腾讯 fqkline hfq 后复权周线 (本土源, 交易日完整)")
    out("  ✗ Yahoo:   系统性缺交易日 —— 000063 中兴 2019-04-26 后直接跳到 05-06,")
    out("              中间 4/29、4/30 整段没有, 3 天累计跌幅记成单日 -15.3%")
    out("              (主板限跌 10%, 不可能), 另 300014 亿纬 2017-05-11 10转10 未复权 -51.3%")
    out("  ✗ 本地K线: data/ashare/bars/*.json 未完整复权 —— 51 只个股中 36 只共 146 次")
    out("             单日跌幅 < -15% 的假暴跌 (最低 -67%)")
    out("  ✓ 质量:   面板复权连续性已验 —— 600519 茅台 2006 股改 10送10 全期连续")
    out("             (174.5 -> 179.4, 无腰斩); 缺失周中位 2.9% (主要是春节/国庆整周休市)")


def section1(px):
    out()
    out(SEP)
    out("段1 · 池子概览")
    out(SEP)
    try:
        from ashare_universe_build import INDUS, NAMES
        inds = sorted({INDUS.get(code_of(c), "") for c in px.columns} - {""})
    except Exception:               # noqa: BLE001
        inds = []
    out(f"  标的 {px.shape[1]} 只 · 行业 {len(inds)} 个 · 面板 {px.shape[0]} 周 "
        f"{px.index[0].date()} ~ {px.index[-1].date()}")
    out(f"  行业: {' / '.join(inds)}")
    w = px.pct_change()
    vol = (w.std() * np.sqrt(52)).dropna()
    vol = vol[vol > 0]
    out()
    out(f"  年化波动率(周频) 中位 {vol.median() * 100:.1f}%  P10 {q(vol, 10) * 100:.1f}%  "
        f"P90 {q(vol, 90) * 100:.1f}%  最高 {nm(vol.idxmax())} {vol.max() * 100:.1f}%")
    out(f"  两两相关系数(周收益) 中位 {_corr_med(px):.3f}")
    out()
    first = {c: px[c].first_valid_index() for c in px.columns}
    f = pd.Series(first).sort_values()
    out("  上市时间分层(可用于长窗口的标的数):")
    for y in (2005, 2008, 2010, 2013, 2016, 2019, 2022):
        n = int((f <= pd.Timestamp(f"{y}-01-01")).sum())
        out(f"    {y} 年前已上市: {n:>3} 只")
    return dict(vol_med=float(vol.median()), vol_p90=float(q(vol, 90)),
                corr_med=float(_corr_med(px)),
                n_coin=px.shape[1], n_ind=len(inds))


def _corr_med(px):
    r = px.pct_change()
    cm = r.corr()
    v = cm.values[np.triu_indices_from(cm.values, 1)]
    v = v[np.isfinite(v)]
    return float(np.median(v)) if len(v) else float("nan")


def section2(px, layers):
    out()
    out(SEP)
    out("段2 · 分层全配对扫描 (每层内 C(n,2) 对, 每对独立 50:50)")
    out(SEP)
    out(f"  {'层(起点)':<12}{'池':>4}{'对数':>7}{'年数':>7}{'筹码年化中位':>13}{'算术均值':>11}"
        f"{'筹码>1':>9}{'跑赢死拿':>10}{'超额中位':>10}{'超额均值':>10}{'两腿都>1':>10}")
    out("  " + "-" * 108)
    stats, details = [], {}
    for lab in layers:
        t0 = pd.Timestamp(lab)
        if t0 > px.index[-1]:
            continue
        st, df = run_layer(px, lab, t0)
        if st is None:
            continue
        stats.append(st)
        details[lab] = df
        out(f"  {st['t0']:<12}{st['n']:>4}{st['npair']:>7}{st['yrs']:>7.2f}"
            f"{pct(st['chip_med']):>13}{pct(st['chip_mean']):>11}"
            f"{pct(st['chip_pos'], 1):>9}{pct(st['exc_pos'], 1):>10}"
            f"{pct(st['exc_med']):>10}{pct(st['exc_mean']):>10}{pct(st['both_gt1'], 1):>10}")
    # 全池(共同窗口)
    last_first = max(px[c].first_valid_index() for c in px.columns)
    t0 = last_first + pd.Timedelta(weeks=MIN_HIST)
    cols = pool_at(px, t0)
    if len(cols) >= 2:
        st, df = run_layer(px, f"全池 {len(cols)} 只", t0, cols=cols)
        if st is not None:
            stats.append(st)
            details["ALL"] = df
            out(f"  {st['t0']:<12}{st['n']:>4}{st['npair']:>7}{st['yrs']:>7.2f}"
                f"{pct(st['chip_med']):>13}{pct(st['chip_mean']):>11}"
                f"{pct(st['chip_pos'], 1):>9}{pct(st['exc_pos'], 1):>10}"
                f"{pct(st['exc_med']):>10}{pct(st['exc_mean']):>10}{pct(st['both_gt1'], 1):>10}")
    out("  " + "-" * 108)
    out("  ⇒ ①『筹码>1』几乎每层满格 = 再平衡后两腿合计股数没变少 (用户命题的形态);")
    out("     ②『跑赢死拿』不是满格 —— 两个判据必须分开报;")
    out("     ③ 筹码年化随窗口拉长而上升 (收割项 ∝ T)。")
    return stats, details


def section3(df, lab):
    out()
    out(SEP)
    out(f"段3 · 主口径逐对明细 —— {lab}")
    out(SEP)
    if df is None or not len(df):
        out("  无样本")
        return
    out(f"  对数 {len(df)} · 筹码年化 中位 {pct(df.chip_ann.median())} / "
        f"均值 {pct(df.chip_ann.mean())} / P10 {pct(q(df.chip_ann, 10))} / "
        f"P90 {pct(q(df.chip_ann, 90))}")
    out(f"  超额 中位 {pct(df.exc.median())} / 均值 {pct(df.exc.mean())} / "
        f"跑赢死拿 {pct((df.exc > 0).mean(), 1)}")
    out()
    show = ["A", "B", "Aind", "chip_ann", "chip_geo", "betaA", "betaB", "exc", "nav", "hold"]
    hdr = f"  {'A':<7}{'B':<7}{'行业A':<7}{'行业B':<7}{'筹码年化':>10}{'筹码几何':>10}" \
          f"{'筹码A':>8}{'筹码B':>8}{'超额':>9}{'再平衡×':>9}{'死拿×':>8}"
    for title, d in (("跑赢死拿 最好 10 对", df.nlargest(10, "exc")),
                     ("跑赢死拿 最差 8 对", df.nsmallest(8, "exc"))):
        out(f"  ── {title} ──")
        out(hdr)
        for _, r in d.iterrows():
            out(f"  {r.A:<7}{r.B:<7}{r.Aind:<7}{r.Bind:<7}{pct(r.chip_ann):>10}"
                f"{r.chip_geo:>10.3f}{r.betaA:>8.3f}{r.betaB:>8.3f}{pct(r.exc):>9}"
                f"{r.nav:>9.3f}{r.hold:>8.3f}")
        out()


def _vol_rho(sub):
    r = sub.pct_change()
    vol = float((r.std() * np.sqrt(52)).median())
    cm = r.corr().values
    rho = float(np.median(cm[np.triu_indices_from(cm, 1)]))
    return vol, rho, 0.25 * (1 - rho) * vol ** 2


def section4(px, S1, stats):
    out()
    out(SEP)
    out("段4 · 波动率到底有多大 / 收割空间 A 股 vs 加密")
    out(SEP)

    # ---- (a) A 股主口径
    t0 = pd.Timestamp(MAIN_START)
    cols = pool_at(px, t0)
    sub = px[cols].loc[t0:].dropna(how="any")
    yrs = (sub.index[-1] - sub.index[0]).days / 365.25
    va, ra, ha = _vol_rho(sub)
    st_main = next((s for s in stats if s["t0"] == MAIN_START), None)
    out(f"  (a) A 股主口径 {len(cols)} 只 · {sub.index[0].date()} ~ "
        f"{sub.index[-1].date()} ({yrs:.2f} 年)")
    out(f"      年化波动 中位 {va * 100:.1f}% · 两两相关 中位 {ra:.3f} · "
        f"理论收割 ¼(1−ρ)σ² = {ha * 100:.2f}%/年")
    if st_main:
        out(f"      实测筹码年化 中位 {pct(st_main['chip_med'])} "
            f"(理论 {pct(ha)} → 兑现率 {st_main['chip_med'] / ha:.0%})")
    out(f"      注: 全池 74 只波动率中位 {S1['vol_med'] * 100:.1f}%、"
        f"P90 {S1.get('vol_p90', float('nan')) * 100:.1f}% —— "
        f"比旧的 7 只蓝筹口径(28%)高一截")

    # ---- (b) 同窗口 5.90 年 (加密主口径)
    TW = pd.Timestamp("2020-10-09")
    sa = px[pool_at(px, TW)].loc[TW:].dropna(how="any")
    if len(sa) > 50:
        ya = (sa.index[-1] - sa.index[0]).days / 365.25
        va2, ra2, ha2 = _vol_rho(sa)
        st_same, _ = run_layer(px, "same-window", TW)   # 同一窗口同一池, 口径严格对齐
        out()
        out(f"  (b) 同窗口对照 {sa.index[0].date()} ~ {sa.index[-1].date()} ({ya:.2f} 年)")
        out(f"      {'':<10}{'标的数':>7}{'年化波动中位':>14}{'两两相关中位':>14}"
            f"{'理论收割':>11}{'实测筹码年化':>14}")
        out("      " + "-" * 70)
        out(f"      {'A 股':<10}{sa.shape[1]:>7}{va2 * 100:>13.1f}%{ra2:>14.3f}"
            f"{ha2 * 100:>10.2f}%{pct(st_same['chip_med']) if st_same else '—':>14}")

        CROOT = os.path.dirname(HERE)          # markets/
        cp = None
        for cand in (os.path.join(CROOT, "crypto", "data",
                                  "weekly_adjclose_crypto50_10y.csv"),):
            if os.path.exists(cand):
                cp = pd.read_csv(cand, index_col=0, encoding="utf-8-sig")
                cp.index = pd.to_datetime(cp.index, format="mixed")
                cp = cp.sort_index()
                break
        if cp is not None:
            C = cp[(cp.index >= sa.index[0]) & (cp.index <= sa.index[-1])]
            C = C.dropna(axis=1, how="any")
            if C.shape[1] >= 5:
                vc, rc, hc = _vol_rho(C)
                # 加密实测: 该窗口内全配对筹码年化中位
                cc = C.values.astype(float)
                ys = (C.index[-1] - C.index[0]).days / 365.25
                ann = []
                for i in range(len(C.columns)):
                    for j in range(i + 1, len(C.columns)):
                        rr = sim_pair(cc[:, [i, j]])
                        ann.append(rr["chip_geo"] ** (1 / ys) - 1)
                mc = float(np.median(ann))
                out(f"      {'加密':<10}{C.shape[1]:>7}{vc * 100:>13.1f}%{rc:>14.3f}"
                    f"{hc * 100:>10.2f}%{pct(mc):>14}")
                out("      " + "-" * 70)
                out(f"      ⇒ 波动 {vc / va2:.1f}× · σ² 贡献 {(vc / va2) ** 2:.1f}× · "
                    f"相关 {ra2:.2f} vs {rc:.2f} (A股更低, 挽回 "
                    f"{(1 - ra2) / (1 - rc):.2f}×) · 净差 {hc / ha2:.1f}×")
                out(f"      ⇒ 实测比 {mc / st_same['chip_med']:.1f}× "
                    f"—— A 股不是『不能』, 是可收割空间只到加密的 "
                    f"约 1/{mc / st_same['chip_med']:.1f}")
                return dict(vol=va2, rho=ra2, harvest=ha2, vol_c=vc, rho_c=rc,
                            harvest_c=hc, chip_a=st_same["chip_med"], chip_c=mc)
    out("  (未找到同窗口加密面板, 跳过对比)")
    return dict(vol=va, rho=ra, harvest=ha)


def section5(df):
    out()
    out(SEP)
    out("段5 · 跨行业配对 vs 同行业配对")
    out(SEP)
    if df is None or not len(df):
        return None
    same = df[df.Aind == df.Bind]
    cross = df[df.Aind != df.Bind]
    out(f"  {'组':<12}{'对数':>7}{'筹码年化中位':>13}{'筹码>1':>9}{'超额中位':>10}"
        f"{'跑赢死拿':>10}{'波动中位':>10}")
    out("  " + "-" * 72)
    for lab, g in (("同行业", same), ("跨行业", cross), ("全部", df)):
        if not len(g):
            continue
        out(f"  {lab:<12}{len(g):>7}{pct(g.chip_ann.median()):>13}"
            f"{pct((g.chip_geo > 1).mean(), 1):>9}{pct(g.exc.median()):>10}"
            f"{pct((g.exc > 0).mean(), 1):>10}{'—':>10}")
    out("  " + "-" * 72)
    out("  ⇒ 同行业股票走势同步(相关高) => 可收割空间小; 跨行业才是分散化的来源。")
    return same, cross


def section6(df):
    out()
    out(SEP)
    out("段6 · 逐股视角 (该股作为 A 腿, 与其他所有股票配对的中位)")
    out(SEP)
    if df is None or not len(df):
        return None
    recs = []
    for name in sorted(set(df.A) | set(df.B)):
        g = df[(df.A == name) | (df.B == name)]
        if len(g) < 5:
            continue
        recs.append(dict(name=name, ind=ind_of(name), n=len(g),
                         chip_med=float(g.chip_ann.median()),
                         exc_med=float(g.exc.median()),
                         exc_pos=float((g.exc > 0).mean()),
                         nav_med=float(g.nav.median())))
    p = pd.DataFrame(recs).sort_values("chip_med", ascending=False)
    out(f"  横截面: {len(p)} 只 · 筹码年化中位 {pct(p.chip_med.median())} · "
        f"其中 {int((p.chip_med > 0).sum())}/{len(p)} 只中位为正")
    out()
    out(f"  {'股票':<9}{'行业':<7}{'配对数':>7}{'筹码年化中位':>13}{'超额中位':>10}"
        f"{'跑赢死拿':>10}{'净值中位':>10}")
    out("  " + "-" * 72)
    for _, r in pd.concat([p.head(8), p.tail(6)]).iterrows():
        out(f"  {r['name']:<9}{r['ind']:<7}{int(r['n']):>7}{pct(r.chip_med):>13}"
            f"{pct(r.exc_med):>10}{pct(r.exc_pos, 1):>10}{r.nav_med:>10.3f}")
    out("  " + "-" * 72)
    return p


def section7(stats):
    out()
    out(SEP)
    out("段7 · 标的数效应: 7 只蓝筹 -> 74 只龙头")
    out(SEP)
    if not stats:
        return
    out(f"  {'层':<12}{'池':>4}{'年数':>7}{'筹码年化中位':>13}{'超额中位':>10}"
        f"{'超额均值':>10}{'两腿都>1':>10}")
    out("  " + "-" * 74)
    for st in stats:
        out(f"  {st['t0']:<12}{st['n']:>4}{st['yrs']:>7.2f}{pct(st['chip_med']):>13}"
            f"{pct(st['exc_med']):>10}{pct(st['exc_mean']):>10}{pct(st['both_gt1'], 1):>10}")
    out("  " + "-" * 74)
    out("  ⇒ 池子越大, 能配出的『低相关对』越多, 筹码年化中位随之抬升;")
    out("     但单币/单股层面仍是重尾分布 —— 分散化是账户层的事。")


def main():
    os.makedirs(OUT, exist_ok=True)
    px = load_px()
    section0()
    S1 = section1(px)
    stats, details = section2(px, LAYERS)
    main_df = None
    for k in (MAIN_START,):
        if k in details:
            main_df = details[k]
    if main_df is None and details:
        k0 = sorted(details.keys(), key=lambda x: str(x))[-1]
        main_df = details[k0]
    section3(main_df, f"起点 {MAIN_START} · 池 {len(pool_at(px, pd.Timestamp(MAIN_START)))} 只")
    S4 = section4(px, S1, stats)
    sc = section5(main_df)
    same, cross = sc if sc else (None, None)
    per = section6(main_df)
    section7(stats)

    # 落盘
    for lab, d in details.items():
        fn = "ashare_pair_layer_all.csv" if lab == "ALL" else f"ashare_pair_layer_{str(lab)[:10]}.csv"
        d.to_csv(os.path.join(OUT, fn), index=False, encoding="utf-8-sig")
    if main_df is not None:
        main_df.to_csv(os.path.join(OUT, "ashare_pair_detail.csv"), index=False,
                       encoding="utf-8-sig")
    if per is not None:
        per.to_csv(os.path.join(OUT, "ashare_pair_per_stock.csv"), index=False,
                   encoding="utf-8-sig")
    pd.DataFrame(stats).to_csv(os.path.join(OUT, "ashare_pair_layers.csv"),
                               index=False, encoding="utf-8-sig")
    out()
    out(SEP)
    out("完成。产物: out/ashare_pair_{layers,detail,per_stock}.csv + 逐层明细")
    out(SEP)


if __name__ == "__main__":
    main()
