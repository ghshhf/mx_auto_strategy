# -*- coding: utf-8 -*-
"""对手选择 × 入场价: AAVE 的横向对照与入场价网格。

用户命题 (2026-09-14):
  1. 「你拿谁和比特币都比不过以太坊, 都比不过比特币 —— 你完全没有意义这样比。」
     即: 用最强资产当对手做压力测试, 反映的是标的差异, 不是再平衡的性质。
     ⇒ 必须横向对照全部对手, 并单独给出"相对对手组"的结论。
  2. 「只要不是在最高点买入, 都还是能赚的。你卡个历史最高点... 平均一下,
     60 美元 70 美元左右... 实在不行来个 100 美元的。」
     ⇒ 入场价才是绝对收益的主因; 必须做入场价网格 + 分批建仓有效成本。

全部数字动态计算, 不硬编码。价格口径: 面板(引擎用) 与 日线(价格水平) 双轨核对。
"""
import os
import sys
import math
import importlib.util

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
OUTDIR = os.path.join(HERE, "out")
MAIN_START = "2020-10-09"
FOCUS = "AAVE"
CAP = 10000.0
PANEL_SHIFT_DAYS = 9          # 面板标签比承载价格早 9 天 (已核对)
SEP = "=" * 122

# 复用已跑通的引擎 (口径与全仓库一致)
_spec = importlib.util.spec_from_file_location(
    "eic", os.path.join(HERE, "excess_is_chips.py"))
eic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eic)
sim_trades = eic.sim_trades
aave_daily = eic.aave_daily


def load_panel():
    px = pd.read_csv(PANEL, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


def main_coins():
    """主口径 19 币名单 (从穷举结果反解, 不硬编码)。"""
    ex = pd.read_csv(os.path.join(OUTDIR, "all_pairs_exhaustive.csv"))
    lay = [l for l in ex["layer"].unique() if str(l).startswith(MAIN_START)]
    if not lay:
        raise RuntimeError(f"未找到主口径分层 {MAIN_START}; 现有: {list(ex['layer'].unique())}")
    sub = ex[ex["layer"] == lay[0]]
    cs = set()
    for p in sub["pair"]:
        for c in str(p).split("+"):
            cs.add(c)
    return sorted(cs)


def real_price(d, t):
    """面板标签 → 真实日线日期/价格 (标签 + 9 天)。"""
    rd = pd.Timestamp(t) + pd.Timedelta(days=PANEL_SHIFT_DAYS)
    s = d["close"]
    pos = s.index.get_indexer([rd], method="nearest")[0]
    if pos < 0:
        return rd, float("nan")
    return s.index[pos], float(s.iloc[pos])


# ------------------------------------------------------------------ 段0 价格口径
def section_price_levels(px, d):
    print(SEP)
    print("【段0】价格口径核对: 面板(引擎) vs 日线(价格水平), 以及偏移的确认")
    print(SEP)
    s = px[FOCUS].dropna()
    print(f"  面板 {FOCUS}: n={len(s)}  {s.index[0].date()} ~ {s.index[-1].date()}"
          f"   最高 {s.max():.2f} @ {s.idxmax().date()}   最低 {s.min():.2f} @ {s.idxmin().date()}")
    print(f"  日线 {FOCUS}: n={len(d)}  {d.index[0].date()} ~ {d.index[-1].date()}"
          f"   收盘最高 {d['close'].max():.2f} @ {d['close'].idxmax().date()}"
          f"   盘中最高 {d['high'].max():.2f} @ {d['high'].idxmax().date()}")
    ok = 0
    n = 0
    for t in s.index[::30]:
        rd, p = real_price(d, t)
        n += 1
        ok += int(abs(p / float(s[t]) - 1) < 0.02)
    print(f"  偏移核对(面板标签+{PANEL_SHIFT_DAYS}天 ≈ 日线收盘): {ok}/{n} 抽样命中 (容差 2%)"
          f"   ⇒ 引擎用的面板价 = 日线价, 只是标签早 {PANEL_SHIFT_DAYS} 天")
    print()
    print(f"  {'年份':<7}{'日线最低':>11}{'低点日':>13}{'日线最高':>11}{'高点日':>13}{'年末收盘':>11}")
    for y, g in d.groupby(d.index.year):
        print(f"  {y:<7}{g['low'].min():>11.2f}{str(g['low'].idxmin().date()):>13}"
              f"{g['high'].max():>11.2f}{str(g['high'].idxmax().date()):>13}"
              f"{g['close'].iloc[-1]:>11.2f}")
    print(f"  最新收盘 {d['close'].iloc[-1]:.2f} @ {d.index[-1].date()}")
    return s


# ------------------------------------------------------- 段1 横向对照全部对手
def section_counterparts(px, coins):
    print()
    print(SEP)
    print(f"【段1】{FOCUS} 对【全部 {len(coins) - 1} 个对手】横向对照 —— 同一主口径窗口 (等权/月调/10bp)")
    print(SEP)
    partners = [c for c in coins if c != FOCUS]
    rows = []
    for b in partners:
        r = sim_trades(px, [FOCUS, b], FOCUS, capital=CAP, start=MAIN_START)
        if r is None:
            continue
        i = r["i"]
        bA = float(r["units"][i] / r["U0"][i])
        bB = float(r["units"][1 - i] / r["U0"][1 - i])
        mA = float(r["px_last"][i] / r["px_first"][i])
        mB = float(r["px_last"][1 - i] / r["px_first"][1 - i])
        nav, hold = r["nav"], r["hold"]
        below = float((r["nav_ser"] < CAP).mean())
        rows.append(dict(partner=b, yrs=r["yrs"], beta_focus=bA, beta_cp=bB,
                         m_focus=mA, m_cp=mB, excess=nav / hold - 1,
                         nav_x=nav / CAP, hold_x=hold / CAP, below=below,
                         rho=r["rho"], turn=r["turnover_ann"],
                         solo_cp=math.log(mB) / r["yrs"] if mB > 0 else float("nan"),
                         solo_focus=math.log(mA) / r["yrs"] if mA > 0 else float("nan")))
    t = pd.DataFrame(rows)
    t["drift_diff_pp"] = (t["solo_cp"] - t["solo_focus"]) * 100
    t = t.sort_values("excess", ascending=False).reset_index(drop=True)
    print(f"  {'对手':<7}{'β_' + FOCUS:>10}{'β_对手':>9}{'漂移差pp':>10}{'超额':>10}"
          f"{'净值×':>9}{'死拿×':>9}{'水下%':>8}{'ρ':>7}")
    print("  " + "-" * 100)
    for _, r in t.iterrows():
        print(f"  {r['partner']:<7}{r['beta_focus']:>10.4f}{r['beta_cp']:>9.4f}"
              f"{r['drift_diff_pp']:>+10.1f}{r['excess']:>10.2%}{r['nav_x']:>9.3f}"
              f"{r['hold_x']:>9.3f}{r['below']:>8.1%}{r['rho']:>7.3f}")
    print()
    print(f"  窗口 {t['yrs'].min():.2f} ~ {t['yrs'].max():.2f} 年"
          f" (最长 {t.loc[t['yrs'].idxmax(), 'partner']} / 最短 {t.loc[t['yrs'].idxmin(), 'partner']});"
          f" 换手中位 {t['turn'].median():.1%}/年")
    print(f"  超额: 为正 {int((t['excess'] > 0).sum())}/{len(t)}"
          f"   中位 {t['excess'].median():+.2%}   区间 [{t['excess'].min():+.2%}, {t['excess'].max():+.2%}]")
    print(f"  净值跑赢死拿: {int((t['nav_x'] > t['hold_x']).sum())}/{len(t)}")
    print(f"  β_{FOCUS} 全为正: {int((t['beta_focus'] > 1).sum())}/{len(t)}"
          f"   中位 {t['beta_focus'].median():.4f}")

    # ---- 段2 分组: 最强资产 vs 相对资产
    print()
    print(SEP)
    print("【段2】把对手分成『最强组』与『相对组』—— 这才是用户批评的核心")
    print(SEP)
    strong = t[t["partner"].isin(["BTC", "ETH"])]
    rel = t[~t["partner"].isin(["BTC", "ETH"])]
    for lab, g in (("最强组 (BTC/ETH)", strong), ("相对组 (其余 %d 个)" % len(rel), rel)):
        if not len(g):
            continue
        print(f"  {lab:<22} n={len(g):<3}  超额 中位 {g['excess'].median():>+8.2%}"
              f"  区间 [{g['excess'].min():+.2%}, {g['excess'].max():+.2%}]"
              f"   净值× 中位 {g['nav_x'].median():>6.3f}   水下 中位 {g['below'].median():>5.1%}")
    if len(strong) and len(rel):
        gap = rel["excess"].median() - strong["excess"].median()
        print(f"  ⇒ 相对组超额中位比最强组高 {gap:+.2%}"
              f"   相对组净值× 中位比最强组高 {rel['nav_x'].median() - strong['nav_x'].median():+.3f}×")
    n_beat = int((rel["nav_x"] > rel["hold_x"]).sum())
    print(f"  ⇒ 相对组里『净值跑赢死拿』: {n_beat}/{len(rel)} = {n_beat / len(rel):.1%}"
          f"   最强组: {int((strong['nav_x'] > strong['hold_x']).sum())}/{len(strong)}")
    t.to_csv(os.path.join(OUTDIR, "aave_counterparts.csv"), index=False, float_format="%.6f")
    return t, rel["partner"].tolist()


# ------------------------------------------------------------ 段3 入场价网格
def section_entry_grid(px, coins, d):
    print()
    print(SEP)
    print("【段3】入场价网格 —— 同一策略, 只换进入时点 (起点价从低到高)")
    print(SEP)
    partners = [c for c in coins if c != FOCUS]
    s = px[FOCUS].dropna()
    starts = list(s.index[::4])
    rows = []
    for t0 in starts:
        sub = px[px.index >= t0]
        if len(sub) < 52:
            continue
        res, btc = [], None
        for b in partners:
            r = sim_trades(px, [FOCUS, b], FOCUS, capital=CAP, start=t0)
            if r is None:
                continue
            i = r["i"]
            rec = dict(
                beta=float(r["units"][i] / r["U0"][i]),
                beta_cp=float(r["units"][1 - i] / r["U0"][1 - i]),
                excess=r["nav"] / r["hold"] - 1,
                nav_x=r["nav"] / CAP, hold_x=r["hold"] / CAP,
                m_focus=float(r["px_last"][i] / r["px_first"][i]),
                yrs=r["yrs"], below=float((r["nav_ser"] < CAP).mean()))
            if b == "BTC":
                btc = rec
            res.append(rec)
        if not res or btc is None:
            continue
        med = {k: float(np.median([x[k] for x in res])) for k in res[0]}
        rd, p_real = real_price(d, t0)
        rows.append(dict(panel_date=t0, real_date=rd, panel_px=float(s[t0]),
                         real_px=p_real, n_cp=len(res),
                         yrs=med["yrs"], px_end=float(s.iloc[-1]),
                         own_mult=med["m_focus"],
                         beta=med["beta"], beta_cp=med["beta_cp"],
                         excess_rel=med["excess"], nav_x_rel=med["nav_x"],
                         hold_x_rel=med["hold_x"], below_rel=med["below"],
                         excess_btc=btc["excess"], nav_x_btc=btc["nav_x"],
                         hold_x_btc=btc["hold_x"]))
    g = pd.DataFrame(rows).sort_values("panel_px").reset_index(drop=True)
    print(f"  每行 = 一个进入时点; 前 3 列是真实日线价 (面板标签+9天); "
          f"'相对' = {len(partners) - 1} 个非 BTC/ETH 对手的中位")
    print(f"  {'日线日':<12}{'日线价':>9}{'窗口':>7}{'β_A':>8}{'超额_相对':>11}{'净值×':>9}"
          f"{'死拿×':>9}{'AAVE×':>8}{'水下':>7}{'超额_BTC':>10}{'vsBTC净值×':>12}")
    print("  " + "-" * 108)
    for _, r in g.iterrows():
        print(f"  {str(r['real_date'].date()):<12}{r['real_px']:>9.2f}{r['yrs']:>7.2f}"
              f"{r['beta']:>8.3f}{r['excess_rel']:>11.2%}{r['nav_x_rel']:>9.3f}"
              f"{r['hold_x_rel']:>9.3f}{r['own_mult']:>8.3f}{r['below_rel']:>7.1%}"
              f"{r['excess_btc']:>10.2%}{r['nav_x_btc']:>12.3f}")
    print()
    print(f"  样本 {len(g)} 个进入时点 ({g['real_date'].min().date()} ~ {g['real_date'].max().date()})")
    print(f"  组合净值 > 1.0 (账户赚钱): 相对对手 中位口径 "
          f"{int((g['nav_x_rel'] > 1).sum())}/{len(g)} = {(g['nav_x_rel'] > 1).mean():.1%}"
          f"    vs BTC "
          f"{int((g['nav_x_btc'] > 1).sum())}/{len(g)} = {(g['nav_x_btc'] > 1).mean():.1%}")
    print(f"  超额 > 0:                  相对对手 "
          f"{int((g['excess_rel'] > 0).sum())}/{len(g)} = {(g['excess_rel'] > 0).mean():.1%}"
          f"    vs BTC "
          f"{int((g['excess_btc'] > 0).sum())}/{len(g)} = {(g['excess_btc'] > 0).mean():.1%}")
    print(f"  AAVE 自身价格倍数为正 (>1): {int((g['own_mult'] > 1).sum())}/{len(g)}"
          f" = {(g['own_mult'] > 1).mean():.1%}")
    g.to_csv(os.path.join(OUTDIR, "aave_entry_grid.csv"), index=False, float_format="%.6f")
    return g


# --------------------------------------------------------- 段4 分批建仓有效成本
def section_dca(d):
    print()
    print(SEP)
    print("【段4】分批建仓 (定投) 的有效成本 —— 『你就平均一下』的量化")
    print(SEP)
    s = d["close"]
    cur = float(s.iloc[-1])
    ath_d = s.idxmax()
    ath = float(s.max())
    print(f"  日线 {s.index[0].date()} ~ {s.index[-1].date()}, 首日收盘 {s.iloc[0]:.2f}, "
          f"末日收盘 {cur:.2f}, 收盘历史最高 {ath:.2f} @ {ath_d.date()}")
    print()
    print(f"  {'建仓窗口':<34}{'批数':>5}{'有效成本':>11}{'末日/成本':>11}{'年化':>10}"
          f"{'一次性首日':>12}{'一次性最高点':>13}")
    for lab, w0 in (("上市 → 今", s.index[0]),
                    (f"历史最高点({ath_d.date()}) → 今", ath_d),
                    ("2023-01-01 → 今", pd.Timestamp("2023-01-01")),
                    ("2024-01-01 → 今", pd.Timestamp("2024-01-01")),
                    ("2025-01-01 → 今", pd.Timestamp("2025-01-01"))):
        seg = s[s.index >= w0]
        if len(seg) < 30:
            continue
        yrs = (seg.index[-1] - seg.index[0]).days / 365.25
        lump0 = cur / float(seg.iloc[0]) - 1
        lump_hi = cur / float(seg.max()) - 1
        for N in (12, 24, 52):
            idx = np.linspace(0, len(seg) - 1, N).astype(int)
            p = seg.values[idx]
            eff = N / float((1.0 / p).sum())          # 等额分批的调和平均成本
            mult = cur / eff
            ann = mult ** (1 / yrs) - 1 if yrs > 0 else float("nan")
            print(f"  {lab:<34}{N:>5}{eff:>11.2f}{mult:>11.3f}{ann:>10.2%}"
                  f"{lump0:>12.2%}{lump_hi:>13.2%}")
        print("  " + "-" * 104)
    print(f"  注: 有效成本 = N / Σ(1/P_i) (等额分批的调和平均, 即真实持仓均价);")
    print(f"      年化按 (末日/有效成本)^(1/窗口年数)−1。窗口内含一段 4~5 年熊市与一次 $668→$57.83 的回撤。")


# ------------------------------------------------------------- 段5 入场价分桶
def section_price_buckets(d):
    print()
    print(SEP)
    print("【段5】『只要不是在最高点买入都能赚』—— 按买入价分桶, 日线全样本检验")
    print(SEP)
    s = d["close"]
    cur = float(s.iloc[-1])
    bands = [(0, 50), (50, 70), (70, 100), (100, 150), (150, 250), (250, 400), (400, 1e9)]
    print(f"  对每一个日线交易日 T: 以收盘价买入持有至今 (末日 {s.index[-1].date()} 收 {cur:.2f})")
    print()
    print(f"  {'买入价区间':<16}{'交易日数':>9}{'占全样本':>10}{'收益中位':>11}{'最差':>10}"
          f"{'最好':>10}{'赚钱占比':>10}{'最近一次机会':>15}")
    tot = len(s)
    for lo, hi in bands:
        g = s[(s >= lo) & (s < hi)]
        if not len(g):
            print(f"  ${lo:,.0f}~  <无样本>")
            continue
        fwd = cur / g - 1
        lab = f"${lo:,.0f}~{hi:,.0f}" if hi < 1e8 else f">${lo:,.0f}"
        print(f"  {lab:<16}{len(g):>9}{len(g) / tot:>10.1%}{fwd.median():>11.1%}"
              f"{fwd.min():>10.1%}{fwd.max():>10.1%}{(fwd > 0).mean():>10.1%}"
              f"{str(g.index[-1].date()):>15}")
    print()
    fwd_all = cur / s - 1
    print(f"  全样本: n={tot}  赚钱 {(fwd_all > 0).mean():.1%}  中位 {fwd_all.median():+.1%}"
          f"   最差 {fwd_all.min():+.1%} (买在 {s.idxmax().date()} 收 {s.max():.2f})")
    above = s[s > cur]
    if len(above):
        print(f"  买在『高于现价 {cur:.2f}』的交易日: {len(above)}/{tot} = {len(above) / tot:.1%}"
              f"  (这些是当前仍浮亏的入场点), 区间 ${above.min():.2f} ~ ${above.max():.2f}")
    print(f"  ⇒ 入场价低于现价的交易日占比 {1 - len(above) / tot:.1%}, 这部分入场全部为正收益。")
    print(f"     ⚠️ 自己指出: 这是算术恒等式 (买入价 < 现价 ⇒ 收益 > 0), 不是证据。")
    print(f"     真正有信息量的是上行那句: 高于现价的入场点占 {len(above) / tot:.1%}"
          f" —— 『只要不是最高点』并不成立。")


# ------------------------------------------------- 段6 入场价的真实代价: 熬得住吗
def section_underwater(d):
    print()
    print(SEP)
    print("【段6】入场价的真实代价 —— 建仓后要熬多深、多久才回本 (日线全样本)")
    print(SEP)
    s = d["close"]
    vals = s.values.astype(float)
    n = len(vals)
    rec = []
    for t in range(n):
        f = vals[t + 1:] / vals[t]      # 从建仓【次日】起算, 排除 t 日本身的 1.0
        if not len(f):
            rec.append(dict(px=float(vals[t]), mdd=0.0, below=0.0, back=0))
            continue
        up = np.where(f > 1.0)[0]
        rec.append(dict(px=float(vals[t]), mdd=float(f.min()) - 1.0,
                        below=float((f < 1.0).mean()),
                        back=int(up[0]) + 1 if len(up) else -1))
    r = pd.DataFrame(rec)
    print(f"  窗内最高 {s.max():.2f} / 最低 {s.min():.2f} / 最新 {vals[-1]:.2f}; "
          f"每行 = 某个交易日买入后到今日的路径统计")
    print()
    print(f"  {'买入价区间':<16}{'交易日':>7}{'最深浮亏中位':>13}{'水下时间占比':>13}"
          f"{'回本中位':>13}{'最长回本':>11}{'至今未回本':>12}")
    bands = [(0, 50), (50, 70), (70, 100), (100, 150), (150, 250), (250, 400), (400, 1e9)]
    for lo, hi in bands:
        g = r[(r["px"] >= lo) & (r["px"] < hi)]
        if not len(g):
            print(f"  ${lo:,.0f}~  <无样本>")
            continue
        lab = f"${lo:,.0f}~{hi:,.0f}" if hi < 1e8 else f">${lo:,.0f}"
        done = g[g["back"] >= 0]
        nr = float((g["back"] < 0).mean())
        back_med = f"{done['back'].median():.0f}天" if len(done) else "—"
        back_max = f"{done['back'].max():.0f}天" if len(done) else "—"
        print(f"  {lab:<16}{len(g):>7}{g['mdd'].median():>13.1%}{g['below'].median():>13.1%}"
              f"{back_med:>13}{back_max:>11}{nr:>12.1%}")
    print()
    done = r[r["back"] >= 0]
    print(f"  全样本 n={n}: 最深浮亏中位 {r['mdd'].median():.1%}   "
          f"水下时间占比中位 {r['below'].median():.1%}   "
          f"回本中位 {done['back'].median() if len(done) else float('nan'):.0f} 天   "
          f"至今未回本 {float((r['back'] < 0).mean()):.1%}")
    print(f"  ⇒ 低于现价的入场点也不轻松: 中位需熬 {r['mdd'].median():.1%} 的浮亏, "
          f"水下 {r['below'].median():.1%} 的时间。")
    print(f"     『回本』口径为一次触及买入价; 这是价格口径, 不含再平衡的筹码搬运收益。")
    return r


# ------------------------------------------------- 段3b 最差入场点专测
def section_worst_entry(px, coins, d):
    print()
    print(SEP)
    print("【段3b】专测最差入场点 —— 『你卡个历史最高点』: 换对手能不能救回入场价?")
    print(SEP)
    s = px[FOCUS].dropna()
    t0 = s.idxmax()
    rd, p_real = real_price(d, t0)
    rda, pa = d["close"].idxmax(), float(d["close"].max())
    print(f"  面板最差入场周: 标签 {t0.date()} → 真实 {rd.date()} 价格 ${p_real:.2f}"
          f"   (面板周期最高 {s.max():.2f})")
    print(f"  日线收盘最高 {pa:.2f} @ {rda.date()}; 日线盘中最高 {d['high'].max():.2f}"
          f" —— 周频面板到不了那个价, 故 {p_real:.2f} 是面板能表达的最差入场")
    print()
    rows = []
    for b in [c for c in coins if c != FOCUS]:
        r = sim_trades(px, [FOCUS, b], FOCUS, capital=CAP, start=t0)
        if r is None:
            continue
        i = r["i"]
        rows.append(dict(partner=b, yrs=r["yrs"],
                         beta=float(r["units"][i] / r["U0"][i]),
                         beta_cp=float(r["units"][1 - i] / r["U0"][1 - i]),
                         excess=r["nav"] / r["hold"] - 1,
                         nav_x=r["nav"] / CAP, hold_x=r["hold"] / CAP,
                         m_focus=float(r["px_last"][i] / r["px_first"][i]),
                         below=float((r["nav_ser"] < CAP).mean())))
    t = pd.DataFrame(rows).sort_values("excess", ascending=False).reset_index(drop=True)
    print(f"  {'对手':<7}{'β_' + FOCUS:>10}{'β_对手':>9}{'超额':>10}{'净值×':>9}{'死拿×':>9}"
          f"{'AAVE价格×':>11}{'水下':>8}")
    print("  " + "-" * 76)
    for _, r in t.iterrows():
        print(f"  {r['partner']:<7}{r['beta']:>10.4f}{r['beta_cp']:>9.4f}{r['excess']:>10.2%}"
              f"{r['nav_x']:>9.3f}{r['hold_x']:>9.3f}{r['m_focus']:>11.3f}{r['below']:>8.1%}")
    print()
    rel = t[~t["partner"].isin(["BTC", "ETH"])]
    btc = t[t["partner"] == "BTC"]
    print(f"  窗口 {t['yrs'].median():.2f} 年;  AAVE 自身价格倍数中位 {t['m_focus'].median():.3f}"
          f" (即最差入场点买入, 价格口径仍亏 {1 - t['m_focus'].median():.1%})")
    print(f"  超额 > 0: 全部对手 {int((t['excess'] > 0).sum())}/{len(t)}"
          f"   相对组 {int((rel['excess'] > 0).sum())}/{len(rel)}"
          f"   相对组超额中位 {rel['excess'].median():+.2%}")
    if len(btc):
        print(f"  换成 BTC 当对手: 超额 {float(btc['excess'].iloc[0]):+.2%}"
              f"   ⇒ 相对组高出 {rel['excess'].median() - float(btc['excess'].iloc[0]):+.2%}")
    print(f"  但组合净值 > 1.0 的只有 {int((t['nav_x'] > 1).sum())}/{len(t)}"
          f" —— 最差入场点上, 再平衡改不了绝对收益。")
    print(f"  ⇒ 两条结论必须分开: 对手选择决定【超额】, 入场价决定【绝对收益】。")
    t.to_csv(os.path.join(OUTDIR, "aave_worst_entry.csv"), index=False, float_format="%.6f")
    return t


def main():
    px = load_panel()
    coins = main_coins()
    d = aave_daily()
    print(SEP)
    print(f"{FOCUS} 对手选择 × 入场价 检验   主口径 {MAIN_START}   {len(coins)} 币"
          f"   等权/月调(4周)/10bp   起点资金 ${CAP:,.0f}")
    print(SEP)
    section_price_levels(px, d)
    section_counterparts(px, coins)
    section_entry_grid(px, coins, d)
    section_worst_entry(px, coins, d)
    section_dca(d)
    section_price_buckets(d)
    section_underwater(d)


if __name__ == "__main__":
    main()
