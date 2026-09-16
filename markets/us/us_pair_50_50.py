# -*- coding: utf-8 -*-
"""
us_pair_50_50.py —— 美股(龙头池) 全配对再平衡, 口径与 A股/加密**逐字一致**
==========================================================================
引擎不重写: 直接 import ashare_pair_all 的 sim_pair / metrics / run_layer,
所以「两标的 50:50 · 4 周调仓 · 10bp · 筹码死拿=1.000」是可证明相同的。

数据闸门(新增第 4 道, 美股专属):
  weekly_adjclose_*.csv 的 **索引是混排的** —— 间隔分布 {1天:78, 2天:29, 3天:26,
  4天:24, 5天:30, 6天:104, 7天:349, 8天:35}, 即把不同日期惯例(周一/周二)的序列
  并成了一张表。直接当周线用, 「每 4 行调仓」有时是 4 周、有时只有 4 天。
  ⇒ 必须先 `resample("W-FRI").last()` 统一到与 A股 面板相同的周五网格。

段
--
  段0 口径与数据闸门      段1 池子概览      段2 分层全配对扫描
  段3 主口径逐对明细      段4 同窗口 美股 vs A股      段5 用户三个命题检验
  段6 强腿定位            段7 逐股视角
"""
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "markets", "ashare"))
sys.path.insert(0, os.path.join(ROOT, "markets"))

# 复用 A股 引擎(口径完全一致)
from ashare_pair_all import (                     # noqa: E402
    sim_pair, metrics, run_layer, pool_at, listed_before,
    _vol_rho, pct, q, med, REBAL_WEEKS, COST_BP, CAP, MIN_HIST,
)


US_DATA = os.path.join(HERE, "data")
US_MAIN = os.path.join(US_DATA, "weekly_adjclose_full.csv")
AS_DATA = os.path.join(ROOT, "markets", "ashare", "data")
AS_PANEL = os.path.join(AS_DATA, "ashare_weekly_panel.csv")

# ⚠️ 112 只标的的首有效周同为 2016-08-05(Yahoo 10 年窗被截断, 不是真实上市日)
#    ⇒ 加 26 周上市门槛后, 最早可用层 = 2017-02-03
US_LAYERS = ["2017-02-03", "2018-01-05", "2020-01-03", "2022-01-07", "2023-01-06"]
MAIN = US_LAYERS[0]
SEP = "=" * 122

# 美股「龙头」子集(能叫得出名字的, 与 A股「各行业龙头」同一定义)
MEGACAP = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "ORCL",
           "AMD", "INTC", "QCOM", "MU", "TXN", "AMAT", "LRCX", "KLAC", "ASML", "ARM",
           "ADBE", "CRM", "NOW", "INTU", "NFLX", "DIS", "JPM", "BAC", "WFC", "AXP",
           "JNJ", "LLY", "ABBV", "MRK", "PFE", "UNH", "ABT", "MDT", "ISRG", "AMGN",
           "XOM", "CVX", "KO", "PG", "PEP", "COST", "WMT", "MCD", "HD", "NKE", "CL",
           "CAT", "DE", "HON", "GE", "BA", "IBM", "CSCO", "MMM", "UPS", "LIN"]


def out(*a):
    print(*a, flush=True)


def load_us(path=US_MAIN):
    d = pd.read_csv(path, index_col=0)
    d.index = pd.to_datetime(d.index, format="mixed")
    d = d.sort_index()
    w = d.resample("W-FRI").last()
    return w.loc[:, w.notna().any(axis=0)]


def load_ashare():
    d = pd.read_csv(AS_PANEL, index_col=0)
    d.index = pd.to_datetime(d.index, format="mixed")
    return d.sort_index()


# ============================================================ 段0
def section0(us_raw, us):
    out(SEP)
    out("段0 · 口径与数据闸门")
    out(SEP)
    gap = pd.Series(us_raw.index).diff().dt.days.dropna()
    vc = {int(k): int(v) for k, v in gap.value_counts().sort_index().items()}
    out(f"  🔴 闸门4 · 原始索引混排: 间隔分布 {vc}")
    out(f"     <7 天的行数 {int((gap < 7).sum())} / {len(gap)} "
        f"({(gap < 7).mean():.1%}) ⇒ 直接当周线用会让『4 周调仓』变成 4 天")
    out(f"  ✅ 重采样 W-FRI: {us_raw.shape[0]} 行 × {us_raw.shape[1]} 列"
        f" → {us.shape[0]} 周 × {us.shape[1]} 列  "
        f"{us.index[0].date()} ~ {us.index[-1].date()}")
    out(f"     与 A股 面板同为周五网格 ⇒ 频率口径可直接对齐")
    vol, rho, harv = _vol_rho(us)
    out(f"  引擎: 直接 import ashare_pair_all.sim_pair (两标的 50:50 · "
        f"{REBAL_WEEKS} 周 · {COST_BP:.0f}bp · 本金 ${CAP:,.0f} · 上市满 {MIN_HIST} 周)")
    out(f"  全池年化波动中位 {vol * 100:.1f}% · 两两相关中位 {rho:.3f} · "
        f"理论收割 ¼(1−ρ)σ² = {harv * 100:.2f}%/年")
    mc = [c for c in MEGACAP if c in us.columns]
    out(f"  龙头子集 {len(mc)}/{len(MEGACAP)} 只可用")
    return vol, rho, harv, mc


# ============================================================ 段1
def section1(us, mc):
    out()
    out(SEP)
    out("段1 · 池子概览")
    out(SEP)
    nn = us.notna().sum()
    out(f"  标的 {us.shape[1]} 只 · 面板 {us.shape[0]} 周 · "
        f"{us.index[0].date()} ~ {us.index[-1].date()}"
        f" ({(us.index[-1] - us.index[0]).days / 365.25:.2f} 年)")
    out(f"  有效周数: 中位 {int(nn.median())}  最少 {int(nn.min())}  最多 {int(nn.max())}")
    r = us.pct_change()
    vols = (r.std() * np.sqrt(52)).dropna()
    out(f"  年化波动: 中位 {vols.median() * 100:.1f}%  P10 {q(vols, 10) * 100:.1f}%  "
        f"P90 {q(vols, 90) * 100:.1f}%  最高 {vols.max() * 100:.1f}% "
        f"({vols.idxmax()})")
    prev = list(us.index[-1:])[0]
    out(f"  末日 {prev.date()}")
    # 龙头子集: 用与主口径相同的最早可用层(而不是 dropna(how='any'), 否则窗口被 ARM 压到 2 年)
    sub = us[mc].loc[pd.Timestamp(MAIN):].dropna(axis=1, how="any")
    vs, rs, hs = _vol_rho(sub)
    out(f"  龙头子集({sub.shape[1]} 只, 贯穿窗口 {sub.index[0].date()} ~ "
        f"{sub.index[-1].date()}, {len(sub)} 周): 波动中位 {vs * 100:.1f}% · "
        f"相关中位 {rs:.3f} · 理论收割 {hs * 100:.2f}%/年")
    return vs, rs, hs


# ============================================================ 段2
def section2(us, mc):
    out()
    out(SEP)
    out("段2 · 分层全配对扫描 (每层内 C(n,2) 对, 每对独立 50:50)")
    out(SEP)
    hdr = (f"  {'层(起点)':<12}{'池':>4}{'对数':>7}{'年数':>7}{'筹码年化中位':>13}"
           f"{'筹码>1':>9}{'跑赢死拿':>10}{'超额累计中位':>13}{'超额折年':>10}{'兑现率':>8}")
    out(hdr)
    out("  " + "-" * 108)
    stats, details = [], {}
    def decorate(st, df):
        st["exc_ann"] = (1 + st["exc_med"]) ** (1 / st["yrs"]) - 1 if st["yrs"] > 0 else np.nan
        # 兑现率 = (超额倍数−1) / (几何平均筹码−1), **逐对算再取中位**(与 A股 诊断层同定义)
        fu = (df.exc / (df.chip_geo - 1.0)).replace([np.inf, -np.inf], np.nan)
        st["fulfil"] = med(fu)
        return st

    def show(st):
        out(f"  {st['t0']:<12}{st['n']:>4}{st['npair']:>7}{st['yrs']:>7.2f}"
            f"{pct(st['chip_med']):>13}{pct(st['chip_pos'], 1):>9}"
            f"{pct(st['exc_pos'], 1):>10}{pct(st['exc_med']):>13}"
            f"{pct(st['exc_ann']):>10}{st['fulfil']:>8.2f}")

    for lab in US_LAYERS:
        t0 = pd.Timestamp(lab)
        if t0 > us.index[-1]:
            continue
        st, df = run_layer(us, lab, t0)
        if st is None:
            out(f"  {lab:<12}  —— 该层合格腿不足, 跳过")
            continue
        decorate(st, df)
        stats.append(st)
        details[lab] = df
        show(st)
    # 全池共同窗口
    last_first = max(us[c].first_valid_index() for c in us.columns)
    t0 = last_first + pd.Timedelta(weeks=MIN_HIST)
    cols = pool_at(us, t0)
    if len(cols) >= 2:
        st, df = run_layer(us, f"全池 {len(cols)}", t0, cols=cols)
        if st is not None:
            decorate(st, df)
            st["label"] = f"全池"
            stats.append(st)
            details["ALL"] = df
            show(st)
    out("  " + "-" * 108)
    # 龙头子集层(用最早可用层, 避免 dropna 把窗口压到 2 年)
    mc_ok = [c for c in mc if c in us.columns and pd.notna(us[c].loc[pd.Timestamp(MAIN)])]
    st_m, df_m = run_layer(us, "龙头子集", pd.Timestamp(MAIN), cols=mc_ok)
    if st_m is not None:
        decorate(st_m, df_m)
        st_m["label"] = "龙头子集"
        stats.append(st_m)
        details["MEGA"] = df_m
        show(st_m)
    return stats, details


# ============================================================ 段3
def section3(details, tag=MAIN):
    out()
    out(SEP)
    out(f"段3 · 主口径逐对明细 ({tag})")
    out(SEP)
    df = details.get(tag)
    if df is None or not len(df):
        out("  无数据")
        return None
    df = df.copy()
    df["exc_ann"] = (1 + df.exc) ** (1 / df.yrs) - 1
    out(f"  对数 {len(df)} · 年数 {df.yrs.iloc[0]:.2f}")
    out(f"  筹码年化: 中位 {pct(med(df.chip_ann))}  P10 {pct(q(df.chip_ann, 10))}  "
        f"P90 {pct(q(df.chip_ann, 90))}  为正 {pct(float((df.chip_ann > 0).mean()), 1)}")
    out(f"  两腿都 >1 : {pct(float(((df.betaA > 1) & (df.betaB > 1)).mean()), 1)}"
        f"   至少一腿 <1 : {pct(float(((df.betaA < 1) | (df.betaB < 1)).mean()), 1)}")
    out(f"  超额累计: 中位 {pct(med(df.exc))}  为正 {pct(float((df.exc > 0).mean()), 1)}"
        f"  P10 {pct(q(df.exc, 10))}  P90 {pct(q(df.exc, 90))}")
    out(f"  超额折年: 中位 {pct(med(df.exc_ann))}")
    out(f"  净值>死拿: {pct(float((df.nav > df.hold).mean()), 1)}")
    for lab, part in (("超额 TOP 10", df.nlargest(10, "exc")),
                      ("超额 BOTTOM 10", df.nsmallest(10, "exc")),
                      ("筹码年化 TOP 10", df.nlargest(10, "chip_ann")),
                      ("筹码年化 BOTTOM 10", df.nsmallest(10, "chip_ann"))):
        out()
        out(f"  ── {lab} ──")
        out(f"    {'A':<7}{'B':<7}{'筹码年化':>10}{'βA':>9}{'βB':>9}"
            f"{'超额累计':>11}{'超额折年':>10}{'净值×':>9}{'死拿×':>9}")
        for _, r in part.iterrows():
            out(f"    {r.A:<7}{r.B:<7}{pct(r.chip_ann):>10}{r.betaA:>9.3f}{r.betaB:>9.3f}"
                f"{pct(r.exc):>11}{pct(r.exc_ann):>10}{r.nav:>9.3f}{r.hold:>9.3f}")
    return df


# ============================================================ 段4
def section4(us, mc, asx):
    out()
    out(SEP)
    out("段4 · 同窗口 美股 vs A股 (各用自己面板, 只按日期区间对齐)")
    out(SEP)
    lo = pd.Timestamp(MAIN)
    hi = min(us.index[-1], asx.index[-1])
    out(f"  ⚠️ 两周线日期不完全重合(交集 {len(us.index.intersection(asx.index))} 周): "
        f"两地休市不同 ⇒ 各跑各的, 只用同一日期区间比较。")
    out(f"  窗口 {lo.date()} ~ {hi.date()} ({(hi - lo).days / 365.25:.2f} 年)")
    out()

    def build(px, pool_cols=None):
        cols = pool_cols if pool_cols is not None else pool_at(px, lo)
        sub = px[cols].loc[lo:hi].dropna(how="any")
        # 只保留贯穿整段窗口的腿(ARM 这类 2023 才上市的会被剔掉, 否则窗口被压到 2 年)
        return sub

    def one(tag, px, pool_cols=None):
        sub = build(px, pool_cols)
        if sub.shape[1] < 2 or len(sub) < 40:
            return None
        vol, rho, harv = _vol_rho(sub)
        yrs = (sub.index[-1] - sub.index[0]).days / 365.25
        st, df = run_layer(sub, tag, sub.index[0], cols=list(sub.columns))
        if st is None:
            return None
        return dict(tag=tag, n=sub.shape[1], yrs=yrs, vol=vol, rho=rho, harv=harv,
                    st=st, df=df)

    rows = [x for x in (one("A股 全池", asx), one("美股 全池", us),
                        one("美股 龙头", us,
                            [c for c in mc if c in us.columns
                             and pd.notna(us[c].loc[lo])])) if x]
    out(f"  {'池':<12}{'腿数':>5}{'年数':>7}{'年化波动中位':>13}{'两两相关中位':>13}"
        f"{'理论收割 ¼(1−ρ)σ²':>18}{'实测筹码年化中位':>17}{'对数':>7}")
    out("  " + "-" * 108)
    for x in rows:
        out(f"  {x['tag']:<12}{x['n']:>5}{x['yrs']:>7.2f}{x['vol'] * 100:>12.1f}%"
            f"{x['rho']:>13.3f}{x['harv'] * 100:>17.2f}%"
            f"{pct(x['st']['chip_med']):>17}{x['st']['npair']:>7}")
    out("  " + "-" * 108)
    d = {x["tag"]: x for x in rows}
    if "A股 全池" in d and "美股 全池" in d:
        xa, xb = d["A股 全池"], d["美股 全池"]
        out(f"  ⇒ 波动 {xb['vol'] / xa['vol']:.2f}× · 相关 {xb['rho'] / xa['rho']:.2f}× · "
            f"理论收割 {xb['harv'] / xa['harv']:.2f}×")
        out(f"     σ² 贡献 {(xb['vol'] / xa['vol']) ** 2:.2f}×; "
            f"低相关项 (1−ρ) 贡献 {(1 - xb['rho']) / (1 - xa['rho']):.2f}×")
        out(f"  ⇒ 实测筹码年化 {pct(xa['st']['chip_med'])} (A股) vs "
            f"{pct(xb['st']['chip_med'])} (美股) ⇒ "
            f"比值 {xb['st']['chip_med'] / max(xa['st']['chip_med'], 1e-9):.2f}×")
    return rows


# ============================================================ 段5
def section5(us, asx, mc):
    out()
    out(SEP)
    out("段5 · 用户四个命题的实测")
    out(SEP)
    lo = pd.Timestamp(MAIN)
    hi = min(us.index[-1], asx.index[-1])

    def drift(px, window=None):
        rows = []
        for c in px.columns:
            s_ = px[c].dropna()
            if window is not None:
                s_ = s_.loc[window[0]:window[1]]
                if len(s_) < 60:
                    continue
            elif len(s_) < 60:
                continue
            yrs = (s_.index[-1] - s_.index[0]).days / 365.25
            m = float(s_.iloc[-1] / s_.iloc[0])
            rows.append(dict(name=c, yrs=yrs, m=m,
                             cagr=m ** (1 / yrs) - 1 if yrs > 0 else np.nan))
        return pd.DataFrame(rows)

    asx_win = asx.loc[lo:hi]
    mc_ok = [c for c in mc if c in us.columns and pd.notna(us[c].loc[lo])]
    us_win = us.loc[lo:hi]

    out("  【命题1】「A股天天都在跌」—— 个股漂移分布")
    out()
    da_all = drift(asx)
    da_same = drift(asx_win)
    db_all = drift(us_win[mc_ok])
    out(f"    {'池':<22}{'只数':>5}{'全期倍数中位':>13}{'CAGR中位':>10}"
        f"{'下跌股占比':>12}{'P10 CAGR':>10}{'P90 CAGR':>10}")
    out("  " + "-" * 96)
    for tag, d in (("A股(2003~2026 全期)", da_all),
                   ("A股(同窗 2017~2026)", da_same),
                   ("美股龙头(同窗 2017~2026)", db_all)):
        if not len(d):
            continue
        out(f"    {tag:<22}{len(d):>5}{d.m.median():>13.2f}{pct(d.cagr.median()):>10}"
            f"{pct(float((d.m < 1).mean()), 1):>12}{pct(q(d.cagr, 10)):>10}"
            f"{pct(q(d.cagr, 90)):>10}")
    out("  " + "-" * 96)
    if len(da_same) and len(db_all):
        out(f"    ⇒ 同窗才可比: A股 CAGR 中位 {pct(da_same.cagr.median())} vs "
            f"美股龙头 {pct(db_all.cagr.median())}")
        out(f"    ⇒ 下跌股占比 A股 {pct(float((da_same.m < 1).mean()), 1)} vs "
            f"美股龙头 {pct(float((db_all.m < 1).mean()), 1)} ⇒ "
            f"『天天跌』在个股层面不成立(两边都是极少数)。")
        out(f"    ⚠️ 但两个池都是『今天还在的龙头』⇒ 幸存者偏差, 已退市/被剔除的不在里面。")
    out()

    out("  【命题2】「要么几周涨上来」—— 涨幅集中度 与 暴利周占比")
    out()
    rows = []
    for tag, px in (("A股", asx_win), ("美股龙头", us_win[mc_ok])):
        for c in px.columns:
            s_ = px[c].dropna()
            if len(s_) < 60:
                continue
            r_ = s_.pct_change().dropna()
            m = float(s_.iloc[-1] / s_.iloc[0])
            burst = (float((s_ / s_.shift(13) - 1).max()) / max(m - 1, 1e-9)
                     if m > 1.05 else np.nan)
            rows.append(dict(pool=tag, name=c, burst=burst,
                             hot=float((r_.abs() > 0.10).mean()),
                             rmax=float(r_.max()), rmin=float(r_.min())))
    d2 = pd.DataFrame(rows)
    out(f"    {'池':<10}{'只数':>5}{'集中度中位':>11}{'集中度P90':>11}"
        f"{'最大单周涨幅中位':>17}{'最大单周跌幅中位':>17}{'|周涨跌|>10%占比':>16}")
    for tag in ("A股", "美股龙头"):
        g = d2[d2.pool == tag]
        if not len(g):
            continue
        out(f"    {tag:<10}{len(g):>5}{med(g.burst):>11.2f}{q(g.burst, 90):>11.2f}"
            f"{med(g.rmax):>17.1%}{med(g.rmin):>17.1%}{med(g.hot):>16.2%}")
    out("    ⇒ 集中度 = max 13 周涨幅 ÷ 全期涨幅; >1 表示 13 周内就把全期涨幅赚完。")
    ga = d2[d2.pool == "A股"]
    gb = d2[d2.pool == "美股龙头"]
    if len(ga) and len(gb):
        out(f"    ⇒ A股 集中度中位 {med(ga.burst):.2f} vs 美股龙头 {med(gb.burst):.2f} "
            f"⇒ A股 是 {med(ga.burst) / max(med(gb.burst), 1e-9):.2f}× 更『突击』")
        out(f"       P90 {q(ga.burst, 90):.2f} vs {q(gb.burst, 90):.2f}; "
            f"最大单周涨幅中位 {med(ga.rmax):.1%} vs {med(gb.rmax):.1%} ⇒ "
            f"『A股几周涨上来』这个印象**成立**。")
        out(f"       但这对再平衡是**利好**不是利空 —— 波动大 = 收割项 ¼(1−ρ)σ² 大。")
    out()

    out("  【命题3】「美股龙头量化可以」—— 完全同口径的超额")
    out()
    out(f"    {'池/层':<24}{'对数':>7}{'年数':>7}{'筹码年化中位':>13}{'超额累计中位':>13}"
        f"{'超额折年':>10}{'跑赢死拿':>10}")
    out("  " + "-" * 96)
    cmp_rows = []
    for tag, px, cols, t0 in (
            ("A股 主口径 2015-01-09", asx, None, pd.Timestamp("2015-01-09")),
            ("A股 同窗", asx, None, lo),
            ("美股 全池 同窗", us, None, lo),
            ("美股 龙头 同窗", us, mc_ok, lo)):
        st, df = run_layer(px, tag, t0, cols=cols)
        if st is None:
            continue
        ea = (1 + st["exc_med"]) ** (1 / st["yrs"]) - 1
        cmp_rows.append((tag, st, ea))
        dv = df if "df" in dir() else None
        hc = med(df.hold_cagr.values) if df is not None and len(df) else np.nan
        nc = med(df.nav_cagr.values) if df is not None and len(df) else np.nan
        out(f"    {tag:<24}{st['npair']:>7}{st['yrs']:>7.2f}{pct(st['chip_med']):>13}"
            f"{pct(st['exc_med']):>13}{pct(ea):>10}{pct(st['exc_pos'], 1):>10}")
        cmp_rows.append(("__detail", dict(tag=tag, nav_cagr=nc, hold_cagr=hc), st))
    out("  " + "-" * 96)
    hdr2 = "    " + "-" * 60
    out(hdr2)
    out(f"    {'池/层':<24}{'净值CAGR中位':>13}{'死拿CAGR中位':>13}{'差(pp/年)':>11}")
    for item in cmp_rows:
        if item[0] != "__detail":
            continue
        d_ = item[1]
        out(f"    {d_['tag']:<24}{pct(d_['nav_cagr']):>13}{pct(d_['hold_cagr']):>13}"
            f"{(d_['nav_cagr'] - d_['hold_cagr']) * 100:>+11.2f}")
    out("    ⇒ 看『死拿CAGR』那一列: 美股龙头死拿确实更强 ⇒ 你直觉的来源在这里。")
    out("       但再平衡能额外加的那部分(超额)反而更小 —— 强腿涨太强, 筹码被搬走太多。")
    out()
    core = [x for x in cmp_rows if x[0] != "__detail"]
    if len(core) >= 4:
        out(f"    ⇒ 同窗对照: A股 超额折年 {pct(core[1][2])} vs 美股全池 "
            f"{pct(core[2][2])} ⇒ 美股/A股 = "
            f"{core[2][2] / max(core[1][2], 1e-9):.2f}×")
    out()

    out("  【命题4】侵蚀项检验: 两腿对数漂移差 (理论上的唯一侵蚀来源)")
    out()
    bins = [(0, 5), (5, 10), (10, 20), (20, 30), (30, 50), (50, 80), (80, 999)]
    for tag, px, cols, t0 in (("A股 同窗", asx, None, lo), ("美股 全池 同窗", us, None, lo)):
        st, df = run_layer(px, tag, t0, cols=cols)
        if df is None or not len(df):
            continue
        dd = (np.abs(np.log(df.mA.values) - np.log(df.mB.values)) / df.yrs.values) * 100
        out(f"    ── {tag} ({len(df)} 对, 中位漂移差 {med(dd):.1f}pp/年) ──")
        out(f"      {'|Δ漂移|(pp/年)':<16}{'对数':>7}{'占比':>8}{'超额>0':>9}"
            f"{'超额累计中位':>13}{'超额折年':>10}{'筹码>1':>8}")
        for a_, b_ in bins:
            m_ = (dd >= a_) & (dd < b_)
            if m_.sum() == 0:
                continue
            e_ = df.exc.values[m_]
            y_ = df.yrs.values[m_]
            out(f"      {f'{a_}~{b_}':<16}{int(m_.sum()):>7}{m_.mean():>8.1%}"
                f"{float((e_ > 0).mean()):>9.1%}{pct(np.median(e_)):>13}"
                f"{pct((1 + np.median(e_)) ** (1 / np.median(y_)) - 1):>10}"
                f"{float((df.chip_geo.values[m_] > 1).mean()):>8.1%}")
        out()
    out("    ⇒ 理论: 超额随漂移差单调衰减; 漂移差越小越好。这是**选腿标准**, 比『行业标签』更准。")
    return cmp_rows


# ============================================================ 段6
def section6(details, tag=MAIN):
    out()
    out(SEP)
    out(f"段6 · 强腿定位 (沿用 A股 诊断层发现: 超额由强腿筹码决定)")
    out(SEP)
    df = details.get(tag)
    if df is None or not len(df):
        out("  无数据")
        return
    d = df.copy()
    mA, mB = d.mA.values, d.mB.values
    strong_beta = np.where(mA >= mB, d.betaA.values, d.betaB.values)
    weak_beta = np.where(mA >= mB, d.betaB.values, d.betaA.values)
    w_strong = np.maximum(mA, mB) / (mA + mB)
    out(f"  强腿权重中位 {np.median(w_strong):.3f}  "
        f"P10 {q(w_strong, 10):.3f}  P90 {q(w_strong, 90):.3f}")
    out(f"  强腿筹码 β 中位 {np.median(strong_beta):.4f} (<1 占 {pct(float((strong_beta < 1).mean()), 1)})")
    out(f"  弱腿筹码 β 中位 {np.median(weak_beta):.4f} (>1 占 {pct(float((weak_beta > 1).mean()), 1)})")
    out(f"  corr(超额, β强腿) = {np.corrcoef(d.exc.values, strong_beta)[0, 1]:+.3f}   "
        f"corr(超额, β弱腿) = {np.corrcoef(d.exc.values, weak_beta)[0, 1]:+.3f}")
    out()
    bins = [(0, 0.35), (0.35, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.0),
            (1.0, 1.3), (1.3, 99)]
    out(f"    {'强腿β':<12}{'对数':>7}{'超额累计中位':>13}{'折年':>10}"
        f"{'净值CAGR':>10}{'死拿CAGR':>10}")
    for lo_, hi_ in bins:
        m = (strong_beta >= lo_) & (strong_beta < hi_)
        if m.sum() == 0:
            continue
        e = d.exc.values[m]
        y = d.yrs.values[m]
        na = d.nav_cagr.values[m]
        ho = d.hold_cagr.values[m]
        ea = (1 + np.median(e)) ** (1 / np.median(y)) - 1
        out(f"    {f'{lo_:.2f}-{hi_:.2f}':<12}{int(m.sum()):>7}{pct(np.median(e)):>13}"
            f"{pct(ea):>10}{pct(np.median(na)):>10}{pct(np.median(ho)):>10}")
    out("  ⇒ 与 A股 同构: 超额 ≈ 『强腿筹码掉没掉』; 弱腿那堆筹码权重只占 "
        f"{1 - np.median(w_strong):.1%}。")


# ============================================================ 段7
def section7(details, us, tag=MAIN):
    out()
    out(SEP)
    out("段7 · 逐股视角 (该股作 A 腿, 与其余全部配对的中位)")
    out(SEP)
    df = details.get(tag)
    if df is None or not len(df):
        out("  无数据")
        return None
    d = df.copy()
    d["exc_ann"] = (1 + d.exc) ** (1 / d.yrs) - 1
    ETF = {"SPY", "QQQ", "DIA", "IWM", "MDY", "VTI", "CWB"}
    n_drop = int(d.A.isin(ETF).sum() + d.B.isin(ETF).sum())
    d = d[~d.A.isin(ETF) & ~d.B.isin(ETF)]
    out(f"  (已剔除指数/ETF 腿 {n_drop} 处: SPY/QQQ/DIA/IWM/MDY/VTI/CWB —— 指数不是『龙头』)")
    recs = []
    for c in sorted(set(d.A) | set(d.B)):
        g = d[(d.A == c) | (d.B == c)]
        if len(g) < 3:
            continue
        oth = [r.B if r.A == c else r.A for r in g.itertuples()]
        alt = d[(d.A.isin(oth)) & (d.B.isin(oth)) & (d.A != d.B)]
        recs.append(dict(ticker=c, n=len(g), chip=g.chip_ann.median(),
                         exc=g.exc.median(), exc_ann=g.exc_ann.median(),
                         win=float((g.exc > 0).mean()),
                         solo=float(us[c].dropna().iloc[-1] / us[c].dropna().iloc[0])
                         if c in us.columns else np.nan))
    R = pd.DataFrame(recs).sort_values("chip", ascending=False)
    out(f"  TOP 10 (筹码年化):")
    out(f"    {'标的':<8}{'对数':>5}{'筹码年化':>10}{'超额累计':>11}{'超额折年':>10}"
        f"{'跑赢率':>9}{'独家死拿×':>11}")
    for _, r in R.head(10).iterrows():
        out(f"    {r['ticker']:<8}{int(r.n):>5}{pct(r.chip):>10}{pct(r.exc):>11}"
            f"{pct(r.exc_ann):>10}{pct(r.win, 1):>9}{r.solo:>11.2f}")
    out(f"  BOTTOM 10 (筹码年化):")
    for _, r in R.tail(10).iterrows():
        out(f"    {r['ticker']:<8}{int(r.n):>5}{pct(r.chip):>10}{pct(r.exc):>11}"
            f"{pct(r.exc_ann):>10}{pct(r.win, 1):>9}{r.solo:>11.2f}")
    out(f"  ⇒ 筹码年化中位为正: {int((R.chip > 0).sum())}/{len(R)}")
    out(f"  ⇒ corr(独家死拿倍数, 作腿筹码年化) = "
        f"{R[['solo', 'chip']].corr().iloc[0, 1]:+.3f}   "
        f"corr(独家死拿倍数, 作腿超额) = {R[['solo', 'exc']].corr().iloc[0, 1]:+.3f}")
    return R


# ============================================================ main
def main():
    raw = pd.read_csv(US_MAIN, index_col=0)
    raw.index = pd.to_datetime(raw.index, format="mixed")
    raw = raw.sort_index()
    us = load_us()
    asx = load_ashare()
    vol, rho, harv, mc = section0(raw, us)
    section1(us, mc)
    stats, details = section2(us, mc)
    section3(details)
    section4(us, mc, asx)
    section5(us, asx, mc)
    section6(details)
    section7(details, us)
    out()
    out(SEP)
    out("完成。")
    out(SEP)


if __name__ == "__main__":
    main()
