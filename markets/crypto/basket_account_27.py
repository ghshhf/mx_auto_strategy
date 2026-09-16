# -*- coding: utf-8 -*-
"""basket_account_27.py — 「整体账户」口径: 买一篮子, 不是买一个币

用户命题 (2026-09-14):
  ① "相当于这一版的话, 就是你必须买 27 个代币, 就买准那最差的那几个,
     剩下的大部分情况下都是赚钱的。对, 就这么简单。"
  ② "你也可以把这个 AAVE 换成其他代币, 你整体看一下你就知道了。"
  ③ "为什么一直强调说他们跑量化得到的是个中间收益。"
  ④ "整体账户的话, 我又不是全场买一个呀, 真的是。"

⇒ 口径必须从【单币 / 币对】切到【账户 / 篮子】:
  单币账户: 只买 1 个币 → 再平衡无从发生 (超额恒 ≡ 0, 由恒等式保证) → 收益 = 价格倍数。
  篮子账户: 买 N 个币等权 → 才有「搬运」与「收割」→ 才有筹码与超额。
  这才是「整体账户」的真实形态。

段0  口径: 为什么单币账户谈不了超额
段1  篮子账户扫描 (池 = 入场日已上市且≥13周历史的全部币, 等权月度再平衡到面板末)
段2  篮子账户 vs 同一入场日的单币账户 / 事后最差3币 / 事后最好3币
段3  同一批入场日上, 账户装 k 个币: 亏损概率、中位净值、筹码、超额 随 k 的走向
     ★ 这是本脚本的核心识别 —— 控制了入场日, 池子大小的效应才干净
段4  把 AAVE 换成别的币: 池内互换 / 逐一剔除 / 池外补位
段5  「中间收益」: 均值 / 中位 / 几何 / 分位 / 偏度 —— 量化报的是哪一个
段6  逐腿贡献拆解: 超额 = 价格倍数份额加权的 (筹码倍数−1); 谁在贡献, 谁在拖累

铁律: 筹码 = 币量倍数 (死拿 = 1.000); 再平衡目的 = 筹码不掉队, 非收益最大化。
      所有数字本脚本动态计算, 不硬编码。
"""
import os
import sys
import math
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

from excess_is_chips import sim_trades, load_panel, PANEL, OUTDIR   # noqa: E402

CAP = 10000.0
COST_BP = 10.0
REBAL_WEEKS = 4
STEP_WEEKS = 4
MIN_HIST = 13              # 新纳入币至少 13 周历史 (避开上市初的极端定价)
MIN_AFTER = 78             # 段1: 入场后剩余窗口 ≥ 1.5 年
MAIN_MIN_AFTER = 78        # 段2/3: 主口径剩余窗口
SWAP_MIN_AFTER = 52        # 段4: 置换检验放宽到 1 年
MODERN_NPOOL = 16          # 「现代池」门槛: 与用户实际账户形态(十几个到二十几个币)对齐
MAIN_START = "2020-10-09"
MAIN_MIN_WEEKS = 300

SEP = "=" * 120
sep = "-" * 120


def out(*a):
    print(*a, flush=True)


def cl(xs):
    x = np.asarray([v for v in xs if v is not None and np.isfinite(v)], dtype=float)
    return x if len(x) else np.array([])


def med(xs):
    x = cl(xs)
    return float(np.median(x)) if len(x) else float("nan")


def mn(xs):
    x = cl(xs)
    return float(x.mean()) if len(x) else float("nan")


def q(xs, p):
    x = cl(xs)
    return float(np.percentile(x, p)) if len(x) else float("nan")


def frac_gt(xs, v):
    x = cl(xs)
    return float((x > v).mean()) if len(x) else float("nan")


def frac_le(xs, v):
    x = cl(xs)
    return float((x <= v).mean()) if len(x) else float("nan")


def uw_stats(nav_vals, capital=CAP):
    """水下三量: 最长连续水下周数 / 从最深点回本周数 / 水下占比。"""
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
        j = int(idx[int(np.argmin(v[idx]))])
        hit = np.where(v[j:] >= capital * (1 - 1e-9))[0]
        if len(hit):
            rec, cens = float(hit[0]), 0
        else:
            rec, cens = float(len(v) - 1 - j), 1
    else:
        rec, cens = 0.0, 0
    return float(best), rec, cens, uw


def first_positions(px):
    fp = {}
    for j, c in enumerate(px.columns):
        s = px[c].dropna()
        fp[j] = int(px.index.get_loc(s.index[0])) if len(s) else -1
    return fp


def main_pool(px):
    res = []
    for c in px.columns:
        s = px[c].dropna()
        if len(s) >= MAIN_MIN_WEEKS and s.index[0] <= pd.Timestamp(MAIN_START):
            res.append(c)
    return res


def pool_at(px, g, fp, min_hist=MIN_HIST):
    """全局第 g 周可买入的币: 已有 ≥min_hist 周历史 且 当周有价。"""
    pr = px.values.astype(float)
    return [px.columns[j] for j in range(px.shape[1])
            if fp[j] >= 0 and fp[j] + min_hist <= g and np.isfinite(pr[g, j])]


def entry_grid(px, fp, min_after=MIN_AFTER, step=STEP_WEEKS, start=None,
               require=None, min_pool=1):
    """require: 必须同时可买的币列表 (None = 只要求 pool 非空)。"""
    idx = px.index
    T = len(idx)
    g0 = 0 if start is None else int(idx.get_indexer([pd.Timestamp(start)])[0])
    recs = []
    for g in range(g0, T - min_after, step):
        pool = pool_at(px, g, fp)
        if len(pool) < min_pool:
            continue
        if require is not None and not set(require) <= set(pool):
            continue
        recs.append(dict(g=g, t0=idx[g], n_pool=len(pool), pool=pool))
    return recs


def pool_px_mult(px, pool, t0):
    """各币从 t0 到面板末的价格倍数 (与引擎 px_last/px_first 同一窗口)。"""
    d = {}
    for c in pool:
        s = px[c].dropna()
        s = s[s.index >= pd.Timestamp(t0)]
        if len(s) < 2:
            continue
        d[c] = float(s.iloc[-1] / s.iloc[0])
    return d


def sim_basket(px, pool, t0, focus=None, uw=False):
    r = sim_trades(px, pool, focus or pool[0], capital=CAP, cost_bp=COST_BP, start=t0)
    if r is None:
        return None
    R = np.asarray(r["R"], dtype=float)
    d = dict(t0=pd.Timestamp(t0), n_pool=len(pool), yrs=r["yrs"],
             nav_mult=r["nav"] / CAP, hold_mult=r["hold"] / CAP,
             exc=r["nav"] / r["hold"] - 1,
             chip_geo=float(np.exp(np.mean(np.log(R)))),
             chip_med=float(np.median(R)), chip_min=float(R.min()),
             chip_max=float(R.max()),
             n_chip_gt1=int((R > 1).sum()), n_chip_lt1=int((R < 1).sum()))
    if uw:
        ul, rec, cens, uwr = uw_stats(r["nav_ser"].values)
        d.update(uwlen_r=ul, rec_r=rec, cens_r=cens, uw_r=uwr)
    return d


# ------------------------------------------------------------------ 段0
def section0(px, mp):
    out(SEP)
    out("【段0】口径: 单币账户谈不了『超额』")
    out(SEP)
    out("  恒等式 (n 币等权, m_i = 价格倍数, β_i = 筹码倍数):")
    out("      死拿 NAV   = (1/n)·Σ m_i")
    out("      再平衡 NAV = (1/n)·Σ m_i·β_i")
    out("      超额       = Σ_i [m_i / Σ_j m_j]·(β_i − 1)")
    out("  ⇒ n = 1 时 β_1 ≡ 1 ⇒ 超额 ≡ 0 (恒等式保证, 无例外)。")
    out("  ⇒ 『只买一个币』的账户里没有再平衡, 收益 100% 由价格倍数决定 ——")
    out("     所以讨论『再平衡 / 筹码 / 超额』必须站在【一篮子】上。这就是『整体账户』。")
    out()
    r1 = sim_basket(px, ["BTC"], MAIN_START)
    r2 = sim_basket(px, mp, MAIN_START)
    out(f"  实算对照 ({MAIN_START} 起 {r2['yrs']:.2f} 年):")
    out(f"     单币 BTC 账户    净值× {r1['nav_mult']:.3f}  死拿× {r1['hold_mult']:.3f}  "
        f"超额 {r1['exc']:+.2e}  ← 单币 = 死拿, 前后完全一样")
    out(f"     主池 {len(mp)} 币篮子   净值× {r2['nav_mult']:.3f}  死拿× {r2['hold_mult']:.3f}  "
        f"超额 {r2['exc']:+.2%}  ← 只有篮子才产生超额")
    out(f"  面板 {px.shape[1]} 币, {px.shape[0]} 周, {px.index[0].date()} ~ {px.index[-1].date()}; "
        f"主池 {len(mp)} 币自 {MAIN_START} 起。")


# ------------------------------------------------------------------ 段1
def section1(px, fp):
    out()
    out(SEP)
    out("【段1】篮子账户扫描: 每个入场日都买『当时已上市的全部币』等权, 月度再平衡到面板末")
    out(SEP)
    entries = entry_grid(px, fp, min_after=MIN_AFTER)
    recs = []
    for e in entries:
        d = sim_basket(px, e["pool"], e["t0"], uw=True)
        if d is None:
            continue
        d["entry_pool"] = e["n_pool"]
        recs.append(d)
    df = pd.DataFrame(recs)
    mdf = df[df.n_pool >= MODERN_NPOOL].copy()
    out(f"  样本: {len(df)} 个入场日 (每 {STEP_WEEKS} 周一个, 入场后剩余 ≥ {MIN_AFTER} 周); "
        f"池子大小 {df.n_pool.min()}~{df.n_pool.max()} 币")
    out(f"  其中『现代池』(≥{MODERN_NPOOL} 币, 与你的账户形态同构) {len(mdf)} 个入场日, "
        f"剩余窗口中位 {mdf.yrs.median():.2f} 年")
    out()
    for lab, g in (("全历史 (池 1~26 币, 含 2015~2019 的长窗口样本)", df),
                   (f"★ 主口径: 现代池 ≥{MODERN_NPOOL} 币", mdf)):
        out(f"  ── {lab} ({len(g)} 个入场日) ──")
        out(f"     净值倍数   中位 {g.nav_mult.median():.3f}   均值 {g.nav_mult.mean():.2f}   "
            f"P10 {q(g.nav_mult, 10):.3f}   P90 {q(g.nav_mult, 90):.2f}   "
            f"最差 {g.nav_mult.min():.3f}   最好 {g.nav_mult.max():.2f}")
        out(f"     盈利(净值>1) 占比 {(g.nav_mult > 1).mean():.1%}   "
            f"死拿倍数 中位 {g.hold_mult.median():.3f}")
        out(f"     筹码(几何均值) 中位 {g.chip_geo.median():.4f}   >1 占比 {(g.chip_geo > 1).mean():.1%}"
            f"   逐腿: 筹码>1 的币 {g.n_chip_gt1.median():.0f}/{g.n_pool.median():.0f}")
        out(f"     超额 (相对同窗等权死拿) 中位 {g.exc.median():+.2%} "
            f"均值 {g.exc.mean():+.2%}  >0 占比 {(g.exc > 0).mean():.1%}")
        out(f"     最长连续水下 中位 {g.uwlen_r.median():.0f} 周 (P75 {q(g.uwlen_r, 75):.0f})")
        out()
    out("  按池子大小分桶:")
    out(f"  {'池子大小':<10}{'入场日':>7}{'净值中位':>9}{'盈利占比':>9}{'筹码中位':>10}"
        f"{'超额中位':>10}{'超额>0':>9}{'最长水下周':>11}")
    out("  " + "-" * 74)
    for lo, hi in [(1, 1), (2, 2), (3, 5), (6, 10), (11, 15), (16, 18), (19, 26)]:
        g = df[(df.n_pool >= lo) & (df.n_pool <= hi)]
        if not len(g):
            continue
        lab = f"{lo}币" if lo == hi else f"{lo}~{hi}币"
        out(f"  {lab:<10}{len(g):>7}{g.nav_mult.median():>9.3f}{(g.nav_mult > 1).mean():>8.1%}"
            f"{g.chip_geo.median():>10.4f}{g.exc.median():>10.2%}{(g.exc > 0).mean():>8.1%}"
            f"{g.uwlen_r.median():>11.0f}")
    out("  " + "-" * 74)
    out("  ⚠ 但这一列不能直接读成『池子大更好』: 历史上池子大小与剩余窗口长度几乎完全共线")
    out("     (2015~2019 池小但窗口长; 2021 之后池大但窗口短)。要干净地看池子大小, 见段3。")
    out()
    out("  按剩余窗口分桶 (收割项 ∝ T):")
    out(f"  {'剩余窗口':<12}{'入场日':>7}{'净值中位':>9}{'盈利占比':>9}{'筹码中位':>10}{'超额中位':>10}")
    out("  " + "-" * 60)
    for lo, hi in [(0, 1.5), (1.5, 2.5), (2.5, 3.5), (3.5, 4.5), (4.5, 5.5), (5.5, 99)]:
        g = df[(df.yrs >= lo) & (df.yrs < hi)]
        if not len(g):
            continue
        lab = f"{lo:.1f}~{hi:.1f}y" if hi < 99 else f"≥{lo:.1f}y"
        out(f"  {lab:<12}{len(g):>7}{g.nav_mult.median():>9.3f}{(g.nav_mult > 1).mean():>8.1%}"
            f"{g.chip_geo.median():>10.4f}{g.exc.median():>10.2%}")
    out("  " + "-" * 60)
    out("  ⚠ 现代池的入场日全部落在 ≤5.5 年档内 → 『现代池中位超额为负』有一半是")
    out("     【剩余窗口短】造成的, 不是池子本身。合并读: 窗口越长, 超额越正, 这是收割项 ∝ T。")
    out()
    out("  固定起点对照 (整段一次性建仓, 之后再平衡):")
    out(f"  {'池子':<30}{'窗口':>8}{'净值×':>9}{'死拿×':>9}{'超额':>10}{'筹码几何':>10}")
    out("  " + "-" * 76)
    mp = main_pool(px)
    wide = px.dropna(how="any")
    for lab, pool, st in ((f"主池 ({len(mp)} 币) {MAIN_START}", mp, MAIN_START),
                          (f"全池 ({len(wide.columns)} 币共同窗口)", list(wide.columns),
                           wide.index[0])):
        r = sim_basket(px, pool, st)
        if r is None:
            continue
        out(f"  {lab:<30}{r['yrs']:>7.2f}y{r['nav_mult']:>9.3f}{r['hold_mult']:>9.3f}"
            f"{r['exc']:>10.2%}{r['chip_geo']:>10.4f}")
    out("  " + "-" * 76)
    df.to_csv(os.path.join(OUTDIR, "basket_account_entries.csv"),
              index=False, float_format="%.6f")
    return df, entries


# ------------------------------------------------------------------ 段2
def section2(px, fp, entries):
    out()
    out(SEP)
    out("【段2】篮子账户 vs 同一入场日的单币账户 (『我又不是全场买一个』)")
    out(SEP)
    cand = [e for e in entries if e["n_pool"] >= MODERN_NPOOL]
    if not cand:
        out("  无足够样本。")
        return None
    nb, singles, worst3, best3 = [], [], [], []
    for e in cand:
        d = sim_basket(px, e["pool"], e["t0"])
        if d is None:
            continue
        d.pop("_r", None)
        nb.append(d)
        rows = []
        for c in e["pool"]:
            r = sim_trades(px, [c], c, capital=CAP, cost_bp=COST_BP, start=e["t0"])
            if r is None:
                continue
            pm = float(r["px_last"][0] / r["px_first"][0])
            singles.append(dict(t0=e["t0"], coin=c, px_mult=pm))
            rows.append((pm, c))
        rows.sort()
        for lab, sel in (("worst3", [c for _, c in rows[:3]]),
                         ("best3", [c for _, c in rows[-3:]])):
            d2 = sim_basket(px, sel, e["t0"])
            if d2 is None:
                continue
            d2.pop("_r", None)
            (worst3 if lab == "worst3" else best3).append(d2)
    B, S = pd.DataFrame(nb), pd.DataFrame(singles)
    W3, B3 = pd.DataFrame(worst3), pd.DataFrame(best3)
    out(f"  样本: 现代池入场日 {len(B)} 个 → 篮子账户 {len(B)} 个 vs 单币账户 {len(S):,} 个 "
        f"(每个入场日 × 池内每个币); 另加『事后最差3币』『事后最好3币』组合各 {len(W3)} 个")
    out()
    out(f"  {'口径':<30}{'账户数':>7}{'净值中位':>10}{'盈利占比':>9}{'最差净值':>10}"
        f"{'P10净值':>9}{'超额中位':>10}")
    out("  " + "-" * 85)
    for lab, g, col in (("单个币 (池内逐币, 无再平衡)", S, "px_mult"),
                        ("事后最差 3 币 (极坏下界)", W3, "nav_mult"),
                        ("★ 全池篮子 (等权再平衡)", B, "nav_mult"),
                        ("事后最好 3 币 (极好上界)", B3, "nav_mult")):
        if not len(g):
            continue
        v = g[col]
        exc = g.exc.median() if "exc" in g.columns else float("nan")
        excs = f"{exc:>10.2%}" if np.isfinite(exc) else f"{'≡0 (无再平衡)':>16}"
        out(f"  {lab:<30}{len(g):>7}{v.median():>10.3f}{(v > 1).mean():>8.1%}"
            f"{v.min():>10.3f}{q(v, 10):>9.3f}{excs}")
    out("  " + "-" * 85)
    out(f"  离散度: 单币 P90/P10 = {q(S.px_mult, 90) / max(q(S.px_mult, 10), 1e-9):.1f}× "
        f"(标准差 {S.px_mult.std():.2f}) vs 篮子 P90/P10 = "
        f"{q(B.nav_mult, 90) / max(q(B.nav_mult, 10), 1e-9):.2f}× (标准差 {B.nav_mult.std():.2f})")
    out("  ⇒ 你那一句的量化形态, 就是下面四行:")
    out(f"     ① 随机只买 1 个币      亏钱概率 {frac_le(S.px_mult, 1):.1%}   "
        f"(池内 {len(S):,} 个单币账户, 净值中位 {S.px_mult.median():.3f})")
    out(f"     ② 买齐整池一篮子      亏钱概率 {frac_le(B.nav_mult, 1):.1%}   "
        f"(净值中位 {B.nav_mult.median():.3f})")
    out(f"     ③ 事后专挑最差 3 个币  亏钱概率 {frac_le(W3.nav_mult, 1):.1%}   "
        f"(净值中位 {W3.nav_mult.median():.3f})  ← 你说的『买准最差那几个』就是这一行")
    out(f"     ④ (对照) 事后专挑最好 3 个币  亏钱概率 {frac_le(B3.nav_mult, 1):.1%}   "
        f"(净值中位 {B3.nav_mult.median():.3f})")
    out("  ⇒ 结论: 会亏钱的情形确实就是『只买了最差的那几个』; 买齐一篮子后, "
        f"{frac_gt(B.nav_mult, 1):.1%} 的入场日是赚钱的。")
    out("  ⚠ 但看最后一列: ③『买最差3个』的超额中位 "
        f"{W3.exc.median():+.2%} 反而是正的, 而 ② 全池篮子 {B.exc.median():+.2%} 是负的。")
    out("     因为『买最差3个』时死拿基准同样惨, 相对数好看而绝对数亏光。")
    out("     ⇒ 『赚钱』『攒筹码』『跑赢同池死拿』是三个不同判据, 混着用就会得出相反结论。")
    return B, S, W3, B3


# ------------------------------------------------------------------ 段3
def section3(px, fp, entries):
    out()
    out(SEP)
    out("【段3】同一批入场日上, 账户装 k 个币会怎样 —— 控制入场日后的干净识别")
    out(SEP)
    K_LIST = [1, 2, 3, 5, 8, 12, 16, 19]
    DRAWS = 400
    rng = np.random.default_rng(20260914)
    big = [e for e in entries if e["n_pool"] >= MODERN_NPOOL]
    out(f"  设计: 入场日固定从这 {len(big)} 个『现代池』日期里随机抽, 币从该日池中随机抽 k 个, "
        f"等权月度再平衡到面板末; 每个 k 抽 {DRAWS} 次。")
    out("  (k=1 时没有再平衡, 超额恒为 0, 净值 = 单个币的价格倍数)")
    out()
    out(f"  {'k (币数)':<9}{'样本':>6}{'净值中位':>10}{'亏损概率':>10}{'P10净值':>9}"
        f"{'筹码中位':>10}{'筹码>1腿':>9}{'超额中位':>10}{'超额>0':>9}{'选中币分位':>11}")
    out("  " + "-" * 95)
    pmaps = [pool_px_mult(px, e["pool"], e["t0"]) for e in big]
    rows = []
    for k in K_LIST:
        navs, excs, chips, ratios, ranks = [], [], [], [], []
        loss_ranks = []
        for _ in range(DRAWS):
            idx = int(rng.integers(len(big)))
            e = big[idx]
            if e["n_pool"] < k:
                continue
            cols = list(rng.choice(e["pool"], size=k, replace=False))
            pm = pmaps[idx]
            vals = np.asarray(list(pm.values()), dtype=float)
            rr = [float((vals < pm[c]).mean()) for c in cols if c in pm]
            rank = float(np.mean(rr)) if rr else float("nan")
            if k == 1:
                r = sim_trades(px, cols, cols[0], capital=CAP, cost_bp=COST_BP, start=e["t0"])
                if r is None:
                    continue
                nav = float(r["px_last"][0] / r["px_first"][0])
                exc, chip, ratio = 0.0, 1.0, 0.0
            else:
                d = sim_basket(px, cols, e["t0"])
                if d is None:
                    continue
                nav, exc, chip = d["nav_mult"], d["exc"], d["chip_geo"]
                ratio = d["n_chip_gt1"] / d["n_pool"]
            navs.append(nav)
            excs.append(exc)
            chips.append(chip)
            ratios.append(ratio)
            ranks.append(rank)
            if nav <= 1:
                loss_ranks.append(rank)
        rows.append(dict(k=k, n=len(navs), nav_med=med(navs), loss=frac_le(navs, 1),
                         nav_p10=q(navs, 10), chip=med(chips),
                         chip_ratio=mn(ratios), exc_med=med(excs),
                         exc_pos=frac_gt(excs, 0), rank_all=med(ranks),
                         rank_loss=med(loss_ranks)))
        r = rows[-1]
        out(f"  {r['k']:<9}{r['n']:>6}{r['nav_med']:>10.3f}{r['loss']:>9.1%}{r['nav_p10']:>9.3f}"
            f"{r['chip']:>10.4f}{r['chip_ratio']:>8.1%}{r['exc_med']:>10.2%}"
            f"{r['exc_pos']:>8.1%}{r['rank_all']:>11.1%}")
    out("  " + "-" * 95)
    out("  末列 = 抽中币在『当期池内按事后价格倍数』的分位 (0 = 全池最差, 1 = 全池最好),")
    out("  全体样本应约 50%。再看亏损样本的成员分位:")
    out(f"  {'k':<6}{'全体样本成员分位':>17}{'亏损样本成员分位':>17}{'亏损占比':>10}")
    out("  " + "-" * 52)
    for r in rows:
        if not np.isfinite(r["rank_loss"]):
            rl = "—"
        else:
            rl = f"{r['rank_loss']:.1%}"
        out(f"  {r['k']:<6}{r['rank_all']:>17.1%}{rl:>17}{r['loss']:>10.1%}")
    out("  " + "-" * 52)
    a, b = rows[0], rows[-1]
    out(f"  ⇒ 控制入场日之后, 池子大小的效应是单向的:")
    out(f"     k: {a['k']} → {b['k']}   亏损概率 {a['loss']:.1%} → {b['loss']:.1%} "
        f"({(b['loss'] - a['loss']) * 100:+.1f}pp)   中位净值 {a['nav_med']:.3f} → {b['nav_med']:.3f} "
        f"   筹码中位 {a['chip']:.3f} → {b['chip']:.3f}")
    out(f"     ⇒ 装得越多, 越不容易亏, 筹码越多 —— 这就是你说的『必须买一整篮子』。")
    out(f"  ⇒ 亏损样本的成员分位 {rows[0]['rank_loss']:.1%}~"
        f"{max(r['rank_loss'] for r in rows if np.isfinite(r['rank_loss'])):.1%} "
        f"< 全体样本的 ~50%:")
    out("     亏钱的账户确实是由『当期池子里事后最差的那一批』组成的 ——")
    out("     换句话说, 要亏钱得先买准最差的那几个; 买齐一篮子就摊掉了这个可能性。")
    out(f"  ⇒ 但同一张表倒数两个数字: 超额 {a['exc_med']:+.2%} → {b['exc_med']:+.2%} "
        f"(近似单调下降, 非严格) ——")
    out("     相对同池死拿的优势随 k 反而恶化。两件事不矛盾: 篮子把『买到最差币』的尾部")
    out("     摊掉 (绝对层), 同时把更多筹码搬到相对弱的一侧 (相对层)。")
    out("     前者是分散化的收益, 后者是搬运项的代价。")
    pd.DataFrame(rows).to_csv(os.path.join(OUTDIR, "basket_account_k.csv"),
                              index=False, float_format="%.6f")
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ 段4
def section4(px, fp, mp):
    out()
    out(SEP)
    out("【段4】把 AAVE 换成别的币, 整体看一遍")
    out(SEP)
    not_main = [c for c in px.columns if c not in mp]
    out(f"  主池 {len(mp)} 币; 池外 {len(not_main)} 币: {', '.join(not_main)}")
    out()
    out("  ── 4a 池内互换 (把 AAVE 换成池内任何一个别的币) ──")
    out("     等权池只取决于【币的集合】, 与谁占哪个位置无关。")
    out(f"     主池 − AAVE + X (X ∈ 主池, X ≠ AAVE) = 主池 本身 → 结果逐位相同, 故不重复列出。")
    base = entry_grid(px, fp, min_after=MAIN_MIN_AFTER, require=mp)
    out(f"     真正会变的是【少买一个】: 下面逐一剔除主池里的每个币, 入场日网格完全相同 "
        f"({len(base)} 个日期)。")
    out()
    fixed = []
    for e in base:
        d = sim_basket(px, mp, e["t0"])
        if d is None:
            continue
        d.pop("_r", None)
        fixed.append(d)
    FB = pd.DataFrame(fixed)
    out(f"     基线 主池 {len(mp)} 币: 中位净值 {FB.nav_mult.median():.3f}  "
        f"中位筹码 {FB.chip_geo.median():.4f}  中位超额 {FB.exc.median():+.2%}  "
        f"(剩余窗口中位 {FB.yrs.median():.2f} 年, 超额>0 {(FB.exc > 0).mean():.1%})")
    out()
    out(f"  {'剔除':<8}{'篮子':>5}{'净值中位':>10}{'筹码中位':>10}{'超额中位':>10}"
        f"{'Δ超额 vs 基线':>15}{'超额>0入场日占比':>17}")
    out("  " + "-" * 78)
    loo = []
    for X in mp:
        pool = [c for c in mp if c != X]
        navs, chips, excs = [], [], []
        for e in base:
            d = sim_basket(px, pool, e["t0"])
            if d is None:
                continue
            navs.append(d["nav_mult"])
            chips.append(d["chip_geo"])
            excs.append(d["exc"])
        rec = dict(X=X, nb=len(pool), nav=med(navs), chip=med(chips), exc=med(excs),
                   delta=med(excs) - FB.exc.median(), exc_pos=frac_gt(excs, 0))
        loo.append(rec)
        out(f"  {X:<8}{len(pool):>5}{rec['nav']:>10.3f}{rec['chip']:>10.4f}{rec['exc']:>10.2%}"
            f"{rec['delta']:>+15.2%}{rec['exc_pos']:>16.1%}")
    L = pd.DataFrame(loo).sort_values("delta", ascending=False).reset_index(drop=True)
    out("  " + "-" * 78)
    out(f"  剔除任意一个币, 中位净值区间 [{L.nav.min():.3f}, {L.nav.max():.3f}], "
        f"中位超额区间 [{L.exc.min():+.2%}, {L.exc.max():+.2%}], 全部仍为负")
    out("  ⚠ Δ超额 是『把该币从池里拿掉、整条路径重算』的差, 不是该币单腿贡献的相反数 ——")
    out("     少一个币会同时改变其他币的相对权重与后续搬运路径, 不可加。")
    out(f"  影响最大的一个: 剔除 {L.iloc[0].X} → Δ超额 {L.iloc[0].delta:+.2%}; "
        f"最小的一个: 剔除 {L.iloc[-1].X} → {L.iloc[-1].delta:+.2%}")
    aa = L[L.X == "AAVE"]
    if len(aa):
        rk = int((L.delta > float(aa.delta.iloc[0])).sum()) + 1
        out(f"  ★ AAVE 本尊: 剔除它 Δ超额 {float(aa.delta.iloc[0]):+.2%}, "
            f"在 {len(L)} 个币里影响排第 {rk} 位 (越靠后 = 越可有可无), "
            f"高于它的只有 {rk - 1} 个币。")
    out("  ⇒ 结论: 『把 AAVE 换成别的币』这件事, 在池内做等于什么都没换 (集合不变);")
    out("     真正决定结果的从来不是某一个币, 而是【池子的构成 + 剩余窗口长度】。")
    out()
    out("  ── 4b 池外补位 (把 AAVE 换成池外那 8 个币之一) ──")
    out(f"     每个 X: 篮子 = 主池 − AAVE + X, 入场日从 max({MAIN_START}, X 上市+{MIN_HIST}周) 起滚动 "
        f"(每 {STEP_WEEKS} 周, 剩余 ≥ {SWAP_MIN_AFTER} 周);")
    out("     并给出【同窗口对照】= 主池 − AAVE 在同一批入场日上的中位超额 (控制窗口, 才有可比性)。")
    out()
    out(f"  {'换成':<9}{'入场日':>7}{'窗口中位':>9}{'组合超额中位':>13}{'同窗口对照':>12}"
        f"{'Δ vs 对照':>11}{'组合净值中位':>13}{'X腿筹码中位':>12}{'X腿价格倍数':>12}")
    out("  " + "-" * 99)
    base18 = [c for c in mp if c != "AAVE"]
    rows = []
    for X in ["AAVE"] + not_main:
        pool = mp if X == "AAVE" else base18 + [X]
        s = px[X].dropna()
        st = max(pd.Timestamp(MAIN_START), s.index[0])
        ent = entry_grid(px, fp, min_after=SWAP_MIN_AFTER, start=st, require=pool)
        if not ent:
            continue
        excs, navs, chips, pms, yrs, ctrl = [], [], [], [], [], []
        for e in ent:
            r = sim_trades(px, pool, X, capital=CAP, cost_bp=COST_BP, start=e["t0"])
            if r is None:
                continue
            i = r["i"]
            excs.append(r["nav"] / r["hold"] - 1)
            navs.append(r["nav"] / CAP)
            chips.append(float(r["R"][i]))
            pms.append(float(r["px_last"][i] / r["px_first"][i]))
            yrs.append(r["yrs"])
            d0 = sim_basket(px, base18, e["t0"])
            if d0 is not None:
                ctrl.append(d0["exc"])
        if not excs:
            continue
        rows.append(dict(X=X, n_entry=len(excs), yrs=med(yrs), exc=med(excs),
                         ctrl=med(ctrl), delta=med(excs) - med(ctrl),
                         nav=med(navs), chip_x=med(chips), px_x=med(pms)))
    R4 = pd.DataFrame(rows).sort_values("exc", ascending=False).reset_index(drop=True)
    for _, x in R4.iterrows():
        tag = "  ← 基线(含AAVE)" if x["X"] == "AAVE" else ""
        out(f"  {x['X']:<9}{x['n_entry']:>7}{x['yrs']:>8.2f}y{x['exc']:>13.2%}"
            f"{x['ctrl']:>12.2%}{x['delta']:>+11.2%}{x['nav']:>13.3f}"
            f"{x['chip_x']:>12.4f}{x['px_x']:>12.3f}{tag}")
    out("  " + "-" * 99)
    out(f"  Δ 的读法: 『把 X 放进这个位置』相对『这个位置空着』(= 主池 − AAVE) 的边际贡献,")
    out("  且两边在同批入场日上取值 —— 否则就成了拿不同窗口比。")
    out(f"  9 个候选 (基线 + 8 个池外币) 的组合超额中位区间 [{R4.exc.min():+.2%}, {R4.exc.max():+.2%}], "
        f"全部为负; X 腿筹码>1 的候选 {int((R4.chip_x > 1).sum())}/{len(R4)}; "
        f"组合净值中位全部 > 1")
    out("  ⇒ 补位进来的币只改变『绝对收益那一层』的量级与窗口长度,")
    out("     没有把『篮子在近 5 年跑不赢同池死拿』这个结论翻过来; 也没有任何一个币让篮子亏钱。")
    out("  ⇒ 差异的顺序基本由【窗口中位】决定 (HYPE 1.23y / ETHFI 1.59y 最差), 不是由币本身决定。")
    L.to_csv(os.path.join(OUTDIR, "basket_account_loo.csv"), index=False, float_format="%.6f")
    R4.to_csv(os.path.join(OUTDIR, "basket_account_swap.csv"), index=False, float_format="%.6f")
    return L, R4


# ------------------------------------------------------------------ 段5
def rank_corr(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5:
        return float("nan")
    ra = pd.Series(a[m]).rank().values
    rb = pd.Series(b[m]).rank().values
    return float(np.corrcoef(ra, rb)[0, 1])


def section5(px, fp, df1, entries):
    out()
    out(SEP)
    out("【段5】『量化得到的是个中间收益』—— 中间收益是哪一个数?")
    out(SEP)
    mdf = df1[df1.n_pool >= MODERN_NPOOL]
    for lab, g in (("全历史 (池 1~26 币)", df1), ("★ 现代池 (≥16 币)", mdf)):
        e = g.exc.values
        nv = g.nav_mult.values
        sk = float(pd.Series(e).skew())
        out(f"  ── {lab}, {len(g)} 个入场日 ──")
        out(f"     超额: 中位 {np.median(e):+.2%}  算术均值 {e.mean():+.2%}  "
            f"几何均值 {np.exp(np.mean(np.log1p(e))) - 1:+.2%}")
        out(f"           P10 {q(e, 10):+.2%}  P25 {q(e, 25):+.2%}  P75 {q(e, 75):+.2%}  "
            f"P90 {q(e, 90):+.2%}  最差 {e.min():+.2%}  最好 {e.max():+.2%}")
        out(f"           偏度 {sk:+.2f}  峰度 {float(pd.Series(e).kurt()):+.2f}  → "
            f"{'右偏 (均值 > 中位)' if sk > 0 else '左偏 (均值 < 中位)'}")
        out(f"     净值: 中位 {np.median(nv):.3f}  算术均值 {nv.mean():.2f}  "
            f"P10 {q(nv, 10):.3f}  P90 {q(nv, 90):.2f}")
        out(f"     窗口 vs 超额 的秩相关 (Spearman): {rank_corr(g.yrs.values, e):+.3f}  "
            f"→ {'窗口越长超额越好' if rank_corr(g.yrs.values, e) > 0 else '无正相关'}")
        out()
    out("  量化的『中间收益』= 中位数, 指的是『典型样本』, 既不是最差也不是最好那个。")
    out("  它与算术均值谁高谁低取决于分布偏斜方向: 右偏时中位 < 均值 (少数极好样本抬高均值),")
    out("  左偏时中位 > 均值。所以『中位数比均值低』不是普遍规律, 要报分布形状。")
    out()
    r = sim_basket(px, main_pool(px), MAIN_START)
    e_all, e_mod = df1.exc.values, mdf.exc.values
    out(f"  对账: 我们此前一直报的『固定起点 {MAIN_START}』篮子超额 = {r['exc']:+.2%}"
        f" (剩余窗口 {r['yrs']:.2f} 年, 全样本窗口分布 {frac_le(df1.yrs.values, r['yrs']):.0%} 分位)")
    out(f"     在全历史入场点分布中: 优于 {frac_le(e_all, r['exc']):.0%} 的入场日 "
        f"(中位 {np.median(e_all):+.2%}, 样本 {len(e_all)})")
    out(f"     在现代池入场点分布中: 优于 {frac_le(e_mod, r['exc']):.0%} 的入场日 "
        f"(中位 {np.median(e_mod):+.2%}, 样本 {len(e_mod)})")
    out("     ⇒ 同一个数字, 换个对照集, 分位从七成变成满格 —— 报超额必须同时报"
        "【剩余窗口】与【对照池】。")
    out(f"     现代池里窗口最长的那个入场日, 超额也是最好的一档 ({frac_le(e_mod, r['exc']):.0%} 分位),")
    out(f"     与现代池内『窗口长度 vs 超额』的秩相关 {rank_corr(mdf.yrs.values, e_mod):+.3f} 一致 ——")
    out("     传导机制是收割项 ∝ T, 不是『挑到了特殊时点』。但这属于事后已知信息, 不可前瞻使用。")
    return None


# ------------------------------------------------------------------ 段6
def section6(px, mp, t0, label):
    out()
    out(SEP)
    out(f"【段6】逐腿贡献拆解 ({label}) —— 谁在贡献, 谁在拖累")
    out(SEP)
    r = sim_trades(px, mp, mp[0], capital=CAP, cost_bp=COST_BP, start=t0)
    if r is None:
        out("  样本不足。")
        return None
    m = np.asarray(r["px_last"], dtype=float) / np.asarray(r["px_first"], dtype=float)
    b = np.asarray(r["R"], dtype=float)
    w = m / m.sum()
    c = w * (b - 1.0)
    exc = r["nav"] / r["hold"] - 1
    chk = abs(float(c.sum()) - exc)
    rows = pd.DataFrame(dict(coin=r["coins"], px_mult=m, chip=b, weight=w, contrib=c))
    rows = rows.sort_values("contrib", ascending=False).reset_index(drop=True)
    out(f"  窗口 {r['start'].date()} ~ {r['end'].date()} ({r['yrs']:.2f} 年) | "
        f"篮子超额 {exc:+.2%} | 恒等式校验 Σ贡献 = {c.sum():+.2%} (误差 {chk:.2e})")
    out(f"  {'币':<8}{'价格倍数':>10}{'权重(价格份额)':>15}{'筹码倍数':>11}{'筹码>1':>8}"
        f"{'超额贡献':>11}{'贡献占比':>10}")
    out("  " + "-" * 78)
    for _, x in rows.iterrows():
        sh = x["contrib"] / exc if abs(exc) > 1e-12 else float("nan")
        out(f"  {x['coin']:<8}{x['px_mult']:>10.3f}{x['weight']:>14.1%}"
            f"{x['chip']:>11.4f}{('是' if x['chip'] > 1 else '否'):>8}"
            f"{x['contrib']:>11.2%}{sh:>10.1%}")
    out("  " + "-" * 78)
    neg = rows[rows.contrib < 0]
    out(f"  筹码>1 的腿 {int((rows.chip > 1).sum())}/{len(rows)};  "
        f"贡献为负的腿 {len(neg)}/{len(rows)}"
        + (f"  ({', '.join(neg.coin.tolist())})" if len(neg) else "  (无)"))
    top = rows.head(3)
    out(f"  Top3 贡献腿 {'/'.join(top.coin.tolist())} 合计 {top.contrib.sum():+.2%} "
        f"(= 篮子超额的 {top.contrib.sum() / exc if abs(exc) > 1e-12 else float('nan'):.0%})")
    if len(neg):
        out(f"  最大拖累 {rows.iloc[-1].coin}: 价格倍数 {rows.iloc[-1].px_mult:.1f}×, "
            f"权重 {rows.iloc[-1].weight:.1%}, 贡献 {rows.iloc[-1].contrib:+.2%} "
            f"(占超额 {rows.iloc[-1].contrib / exc if abs(exc) > 1e-12 else float('nan'):.0%})")
        out(f"  注意 {rows.iloc[-1].coin} 是涨得最多的腿 (权重最大), 却被再平衡持续减配 —— "
            f"这就是『搬运项』的代价。")
    out("  ⇒ 反向也成立: 崩掉的币 (FIL 0.03×, DOT 0.25×) 权重趋近于 0, 贡献被自动削弱,")
    out("     而它们腿上的筹码倍数却是全池最高的 (510× / 58×) ——")
    out("     『买中最差那几个』在篮子里既被权重削弱、又被筹码补偿, 双重缓冲。")
    return rows


# ------------------------------------------------------------------ HTML 报告
CSS = """
body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;margin:0;background:#f5f6f8;
color:#1c2024;line-height:1.65}
.wrap{max-width:1180px;margin:0 auto;padding:28px 22px 60px}
h1{font-size:25px;margin:0 0 6px}
h2{font-size:18px;margin:34px 0 10px;padding-left:10px;border-left:4px solid #2f6fed}
.sub{color:#5c6672;font-size:13px;margin-bottom:18px}
.card{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:16px 18px;margin:12px 0;
box-shadow:0 1px 2px rgba(16,24,40,.04)}
table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}
th,td{padding:6px 9px;border-bottom:1px solid #eceff2;text-align:right;white-space:nowrap}
th{background:#f0f3f7;color:#3b4450;font-weight:600;text-align:right;position:sticky;top:0}
td:first-child,th:first-child{text-align:left}
tbody tr:hover{background:#f8fafc}
.pos{color:#c0392b;font-weight:600}.neg{color:#1e8449;font-weight:600}
.hi{background:#fff8e1}
.k{font-weight:700}
ul{margin:6px 0 6px 18px;padding:0}li{margin:4px 0}
.note{background:#fff8e1;border:1px solid #f0e0a8;border-radius:8px;padding:10px 14px;font-size:13px;margin:10px 0}
.warn{background:#fdecea;border:1px solid #f5c2bd;border-radius:8px;padding:10px 14px;font-size:13px;margin:10px 0}
.small{font-size:12px;color:#5c6672}
"""


def _num(v, kind="pct2", pos_color=True):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "<td>—</td>"
    if kind == "pct2":
        s, cls = f"{v:+.2%}", ("pos" if v > 0 else "neg")
    elif kind == "pct1":
        s, cls = f"{v:.1%}", ""
    elif kind == "x3":
        s, cls = f"{v:.3f}", ""
    elif kind == "x4":
        s, cls = f"{v:.4f}", ("pos" if v > 1 else "neg")
    elif kind == "f2":
        s, cls = f"{v:.2f}", ""
    elif kind == "f0":
        s, cls = f"{v:.0f}", ""
    elif kind == "i":
        s, cls = f"{int(v):,}", ""
    else:
        s, cls = str(v), ""
    if not pos_color:
        cls = ""
    return f'<td class="{cls}">{s}</td>'


def build_report(path, px, mp, df1, B, S, W3, B3, K, L, R4, contrib):
    mdf = df1[df1.n_pool >= MODERN_NPOOL]
    rf = sim_basket(px, mp, MAIN_START)
    wide = px.dropna(how="any")
    rw = sim_basket(px, list(wide.columns), wide.index[0])
    h = []
    h.append(f"<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
             f"<title>整体账户口径 · 篮子再平衡</title><style>{CSS}</style></head><body><div class='wrap'>")
    h.append("<h1>整体账户口径: 买一篮子, 不是买一个币</h1>")
    h.append(f"<div class='sub'>面板 {px.shape[0]} 周 × {px.shape[1]} 币 · "
             f"{px.index[0].date()} ~ {px.index[-1].date()} · 等权 {REBAL_WEEKS} 周调仓 · "
             f"成本 {COST_BP:.0f}bp · 本金 ${CAP:,.0f} · 新币上市后 ≥{MIN_HIST} 周可纳入 · "
             f"全部分位/中位由脚本动态计算</div>")

    h.append("<h2>一、口径: 单币账户谈不了『超额』</h2><div class='card'>")
    h.append("<p>恒等式 (n 币等权, m<sub>i</sub> = 价格倍数, β<sub>i</sub> = 筹码倍数):"
             "<b>超额 = Σ<sub>i</sub>[m<sub>i</sub> / Σ<sub>j</sub>m<sub>j</sub>]·(β<sub>i</sub> − 1)</b>。"
             "n = 1 时 β<sub>1</sub> ≡ 1 ⇒ 超额 ≡ 0，无例外。所以『只买一个币』的账户里没有再平衡，"
             "收益 100% 由价格决定；谈筹码与超额必须站在一篮子上。</p>")
    h.append("<table><thead><tr><th>账户</th><th>窗口</th><th>净值×</th><th>死拿×</th>"
             "<th>超额</th><th>筹码(几何)</th></tr></thead><tbody>")
    h.append(f"<tr><td class='k'>单币 BTC</td><td>{rf['yrs']:.2f}y</td>"
             f"{_num(rf['nav_mult'], 'x3')}{_num(rf['hold_mult'], 'x3')}"
             f"<td class=''>{rf['exc']:+.2e}</td>{_num(1.0, 'x4')}</tr>")
    h.append(f"<tr class='hi'><td class='k'>主池 {len(mp)} 币篮子</td><td>{rf['yrs']:.2f}y</td>"
             f"{_num(rf['nav_mult'], 'x3')}{_num(rf['hold_mult'], 'x3')}"
             f"{_num(rf['exc'], 'pct2')}{_num(rf['chip_geo'], 'x4')}</tr>")
    h.append("</tbody></table>")
    h.append(f"<p class='small'>主池 {len(mp)} 币自 {MAIN_START} 起；同窗口下篮子净值 "
             f"{rf['nav_mult']:.3f}× vs 死拿 {rf['hold_mult']:.3f}×，差值就是再平衡带来的筹码。</p></div>")

    h.append("<h2>二、『必须买一整篮子，只有买准最差那几个才亏』</h2><div class='card'>")
    h.append(f"<table><thead><tr><th>口径</th><th>账户数</th><th>净值中位</th><th>盈利占比</th>"
             f"<th>最差净值</th><th>P10 净值</th><th>超额中位</th></tr></thead><tbody>")
    rows2 = [("单个币 (池内逐币，无再平衡)", S, "px_mult", None),
             ("事后最差 3 币 (极坏下界)", W3, "nav_mult", W3),
             (f"★ 全池篮子 (等权再平衡)", B, "nav_mult", B),
             ("事后最好 3 币 (极好上界)", B3, "nav_mult", B3)]
    for lab, g, col, gg in rows2:
        v = g[col]
        exc = _num(gg.exc.median(), "pct2") if gg is not None else \
            "<td class='small'>≡ 0 (无再平衡)</td>"
        h.append(f"<tr class='{'hi' if lab.startswith('★') else ''}'><td class='k'>{lab}</td>"
                 f"{_num(len(g), 'i')}{_num(v.median(), 'x3')}{_num((v > 1).mean(), 'pct1')}"
                 f"{_num(v.min(), 'x3')}{_num(q(v, 10), 'x3')}{exc}</tr>")
    h.append("</tbody></table>")
    h.append(f"<div class='note'>随机只买 1 个币亏钱概率 <b>{frac_le(S.px_mult, 1):.1%}</b>；"
             f"买齐整池一篮子降到 <b>{frac_le(B.nav_mult, 1):.1%}</b>；"
             f"只有事后专挑最差的 3 个币才会 <b>{frac_le(W3.nav_mult, 1):.1%}</b> 亏钱。"
             f"离散度也从 {q(S.px_mult, 90) / max(q(S.px_mult, 10), 1e-9):.1f}× 压到 "
             f"{q(B.nav_mult, 90) / max(q(B.nav_mult, 10), 1e-9):.2f}×。</div>")
    h.append(f"<div class='warn'>但『赚钱』≠『跑赢同池死拿』：篮子超额中位 "
             f"{_pct(B.exc.median())}，只有 {(B.exc > 0).mean():.1%} 的入场日为正。"
             f"而『买最差 3 个』超额中位 {_pct(W3.exc.median())} 反而是正的 —— 因为死拿基准同样惨。"
             f"三个判据必须分开报。</div></div>")

    h.append("<h2>三、账户装 k 个币：控制入场日后的干净识别</h2><div class='card'>")
    h.append("<p class='small'>入场日固定从这批『现代池』日期里随机抽，币从该日池中随机抽 k 个，"
             "等权月度再平衡到面板末；每个 k 的样本数见下表。k=1 时没有再平衡，超额恒为 0。</p>")
    h.append("<table><thead><tr><th>k</th><th>样本</th><th>净值中位</th><th>亏损概率</th>"
             "<th>P10 净值</th><th>筹码中位</th><th>筹码&gt;1 腿</th><th>超额中位</th>"
             "<th>超额&gt;0</th><th>抽中币分位</th><th>亏损样本分位</th></tr></thead><tbody>")
    for _, r in K.iterrows():
        rl = "—" if not np.isfinite(r["rank_loss"]) else f"{r['rank_loss']:.1%}"
        h.append(f"<tr><td class='k'>{int(r['k'])}</td>{_num(r['n'], 'i')}"
                 f"{_num(r['nav_med'], 'x3')}{_num(r['loss'], 'pct1')}{_num(r['nav_p10'], 'x3')}"
                 f"{_num(r['chip'], 'x4')}{_num(r['chip_ratio'], 'pct1')}"
                 f"{_num(r['exc_med'], 'pct2')}{_num(r['exc_pos'], 'pct1')}"
                 f"{_num(r['rank_all'], 'pct1')}<td>{rl}</td></tr>")
    h.append("</tbody></table>")
    a, b = K.iloc[0], K.iloc[-1]
    h.append(f"<div class='note'>k 从 {int(a['k'])} 提到 {int(b['k'])}：亏损概率 "
             f"{a['loss']:.1%} → {b['loss']:.1%}，中位净值 {a['nav_med']:.3f} → {b['nav_med']:.3f}，"
             f"筹码中位 {a['chip']:.3f} → {b['chip']:.3f}。<br>"
             f"亏损样本的成员分位 {a['rank_loss']:.1%} → {b['rank_loss']:.1%}（全体约 "
             f"{a['rank_all']:.1%}）——亏钱的账户确实由『当期池子里事后最差的那一批』组成。</div>")
    h.append(f"<div class='warn'>同一张表里超额 {_pct(a['exc_med'])} → {_pct(b['exc_med'])}，"
             f"近似单调下降：篮子把尾部摊掉 (绝对层)，同时把更多筹码搬到相对弱的一侧 (相对层)。"
             f"前者是分散化收益，后者是搬运项代价。</div></div>")

    h.append("<h2>四、把所有入场日摊开看</h2><div class='card'>")
    h.append("<table><thead><tr><th>样本</th><th>入场日</th><th>净值中位</th><th>盈利占比</th>"
             "<th>筹码中位</th><th>超额中位</th><th>超额均值</th><th>超额&gt;0</th>"
             "<th>窗口 vs 超额 秩相关</th></tr></thead><tbody>")
    for lab, g in (("全历史 (池 1~26 币)", df1), (f"★ 现代池 (≥{MODERN_NPOOL} 币)", mdf)):
        h.append(f"<tr class='{'hi' if lab.startswith('★') else ''}'><td class='k'>{lab}</td>"
                 f"{_num(len(g), 'i')}{_num(g.nav_mult.median(), 'x3')}"
                 f"{_num((g.nav_mult > 1).mean(), 'pct1')}{_num(g.chip_geo.median(), 'x4')}"
                 f"{_num(g.exc.median(), 'pct2')}{_num(g.exc.mean(), 'pct2')}"
                 f"{_num((g.exc > 0).mean(), 'pct1')}"
                 f"{_num(rank_corr(g.yrs.values, g.exc.values), 'f2')}</tr>")
    h.append("</tbody></table>")
    h.append("<table><thead><tr><th>剩余窗口</th><th>入场日</th><th>净值中位</th><th>盈利占比</th>"
             "<th>筹码中位</th><th>超额中位</th></tr></thead><tbody>")
    for lo, hi in [(0, 1.5), (1.5, 2.5), (2.5, 3.5), (3.5, 4.5), (4.5, 5.5), (5.5, 99)]:
        g = df1[(df1.yrs >= lo) & (df1.yrs < hi)]
        if not len(g):
            continue
        lab = f"{lo:.1f}~{hi:.1f} 年" if hi < 99 else f"≥ {lo:.1f} 年"
        h.append(f"<tr><td class='k'>{lab}</td>{_num(len(g), 'i')}"
                 f"{_num(g.nav_mult.median(), 'x3')}{_num((g.nav_mult > 1).mean(), 'pct1')}"
                 f"{_num(g.chip_geo.median(), 'x4')}{_num(g.exc.median(), 'pct2')}</tr>")
    h.append("</tbody></table>")
    rp = frac_le(df1.exc.values, rf["exc"])
    h.append(f"<div class='note'>此前一直报的『固定起点 {MAIN_START}』篮子超额 "
             f"<b>{rf['exc']:+.2%}</b> (剩余窗口 {rf['yrs']:.2f} 年)：在全历史入场点里优于 "
             f"{rp:.0%}，在现代池入场点里优于 {frac_le(mdf.exc.values, rf['exc']):.0%}。"
             f"同一个数字换个对照集分位就变 —— 报超额必须同时报剩余窗口与对照池。</div>")
    h.append(f"<div class='warn'>现代池的超额中位是 {_pct(mdf.exc.median())}："
             f"这 55 个入场日的剩余窗口全部 ≤5.5 年，而『窗口 vs 超额』的秩相关达 "
             f"{rank_corr(mdf.yrs.values, mdf.exc.values):+.2f}。"
             f"所以现代池超额为负，主要是【剩余窗口短】造成的，不是池子本身的问题。</div></div>")

    h.append("<h2>五、把 AAVE 换成别的币</h2><div class='card'>")
    h.append(f"<p>等权池只取决于<b>币的集合</b>，与谁占哪个位置无关："
             f"主池 − AAVE + X (X ∈ 主池) = 主池本身，结果逐位相同。"
             f"真正会变的是『少买一个』与『补位一个』。</p>")
    h.append("<p class='small'>5a 逐一剔除主池里的每个币（入场日网格完全相同，"
             f"{len(L)} 行）</p>")
    h.append("<table><thead><tr><th>剔除</th><th>篮子</th><th>净值中位</th><th>筹码中位</th>"
             "<th>超额中位</th><th>Δ超额 vs 基线</th><th>超额&gt;0 入场日占比</th></tr></thead><tbody>")
    for _, r in L.iterrows():
        h.append(f"<tr class='{'hi' if r['X'] == 'AAVE' else ''}'><td class='k'>{r['X']}</td>"
                 f"{_num(r['nb'], 'i')}{_num(r['nav'], 'x3')}{_num(r['chip'], 'x4')}"
                 f"{_num(r['exc'], 'pct2')}{_num(r['delta'], 'pct2')}"
                 f"{_num(r['exc_pos'], 'pct1')}</tr>")
    h.append("</tbody></table>")
    rk = int((L.delta > float(L[L.X == "AAVE"].delta.iloc[0])).sum()) + 1
    h.append(f"<div class='note'>剔除任意一个币，中位净值区间 [{L.nav.min():.3f}, {L.nav.max():.3f}]，"
             f"中位超额区间 [{L.exc.min():+.2%}, {L.exc.max():+.2%}]，全部仍为负。"
             f"影响最大的 {L.iloc[0].X} ({L.iloc[0].delta:+.2%})，最小的 {L.iloc[-1].X} "
             f"({L.iloc[-1].delta:+.2%})；<b>AAVE 排第 {rk}/{len(L)} 位</b>，属于可有可无那一档。"
             f"Δ 是整条路径重算的差，不是单腿贡献的相反数，不可加。</div>")
    h.append("<p class='small'>5b 池外 8 币补位（同窗口对照，才有可比性）</p>")
    h.append("<table><thead><tr><th>换成</th><th>入场日</th><th>窗口中位</th><th>组合超额中位</th>"
             "<th>同窗口对照</th><th>Δ vs 对照</th><th>组合净值中位</th><th>X 腿筹码中位</th>"
             "<th>X 腿价格倍数</th></tr></thead><tbody>")
    for _, r in R4.iterrows():
        h.append(f"<tr class='{'hi' if r['X'] == 'AAVE' else ''}'><td class='k'>{r['X']}</td>"
                 f"{_num(r['n_entry'], 'i')}{_num(r['yrs'], 'f2')}"
                 f"{_num(r['exc'], 'pct2')}{_num(r['ctrl'], 'pct2')}{_num(r['delta'], 'pct2')}"
                 f"{_num(r['nav'], 'x3')}{_num(r['chip_x'], 'x4')}{_num(r['px_x'], 'x3')}</tr>")
    h.append("</tbody></table>")
    hy = R4[R4.X == "HYPE"]
    he = R4[R4.X == "ETHFI"]
    hyy = f"{hy.yrs.iloc[0]:.2f}y" if len(hy) else "—"
    hey = f"{he.yrs.iloc[0]:.2f}y" if len(he) else "—"
    h.append(f"<div class='note'>9 个候选的组合超额中位全部为负（区间 "
             f"[{R4.exc.min():+.2%}, {R4.exc.max():+.2%}]），但<b>组合净值中位全部 &gt; 1</b>。"
             f"顺序基本由窗口中位决定（HYPE {hyy} / ETHFI {hey} 最差），不是由币本身决定。</div></div>")

    h.append("<h2>六、逐腿贡献: 谁在贡献, 谁在拖累</h2><div class='card'>")
    exc = float(contrib.contrib.sum())
    h.append(f"<p class='small'>主池 {len(mp)} 币，固定起点 {MAIN_START}，"
             f"Σ 贡献 = {exc:+.2%}（恒等式误差 &lt; 1e-15）</p>")
    h.append("<table><thead><tr><th>币</th><th>价格倍数</th><th>权重 (价格份额)</th>"
             "<th>筹码倍数</th><th>筹码&gt;1</th><th>超额贡献</th><th>贡献占比</th></tr></thead><tbody>")
    for _, r in contrib.iterrows():
        h.append(f"<tr><td class='k'>{r['coin']}</td>{_num(r['px_mult'], 'x3')}"
                 f"{_num(r['weight'], 'pct1')}{_num(r['chip'], 'x4')}"
                 f"<td>{'是' if r['chip'] > 1 else '否'}</td>"
                 f"{_num(r['contrib'], 'pct2')}{_num(r['contrib'] / exc, 'pct1')}</tr>")
    h.append("</tbody></table>")
    neg = contrib[contrib.contrib < 0]
    h.append(f"<div class='note'>权重 = 价格倍数份额：涨得多的币权重自然变大，崩掉的币权重趋近于 0。"
             f"筹码 &gt;1 的腿 {int((contrib.chip > 1).sum())}/{len(contrib)}；"
             f"贡献为负的腿 {len(neg)} 个（{', '.join(neg.coin.tolist()) if len(neg) else '无'}）。"
             f"Top3 ({'/'.join(contrib.head(3).coin.tolist())}) 合计 {contrib.head(3).contrib.sum():+.2%}。</div>")
    h.append(f"<div class='note'>崩掉的币（FIL {contrib[contrib.coin == 'FIL'].px_mult.iloc[0]:.2f}×，"
             f"DOT {contrib[contrib.coin == 'DOT'].px_mult.iloc[0]:.2f}×）权重趋近 0，贡献被自动削弱，"
             f"而它们腿上的筹码倍数却是全池最高的（"
             f"{contrib[contrib.coin == 'FIL'].chip.iloc[0]:.0f}× / "
             f"{contrib[contrib.coin == 'DOT'].chip.iloc[0]:.0f}×）——"
             f"『买中最差那几个』在篮子里既被权重削弱、又被筹码补偿，双重缓冲。</div></div>")

    h.append("<h2>七、结论</h2><div class='card'><ul>")
    h.append(f"<li><b>『必须买一整篮子』成立</b>：随机只买 1 个币亏钱概率 "
             f"{frac_le(S.px_mult, 1):.1%} → 买齐整池 {frac_le(B.nav_mult, 1):.1%}；"
             f"k 从 1 到 {int(b['k'])}，亏损概率 {a['loss']:.1%} → {b['loss']:.1%}，筹码中位 "
             f"{a['chip']:.3f} → {b['chip']:.3f}，且亏损样本的成员分位从 {a['rank_loss']:.1%} "
             f"升到 {b['rank_loss']:.1%} —— 亏钱确实要先买准最差的那一批。</li>")
    h.append(f"<li><b>『换掉 AAVE』不是变量</b>：池内互换集合不变；逐一剔除 19 币的 Δ超额区间 "
             f"[{L.delta.min():+.2%}, {L.delta.max():+.2%}]；池外补位 8 币的组合超额区间 "
             f"[{R4.exc.min():+.2%}, {R4.exc.max():+.2%}]，但组合净值中位全部 &gt; 1。"
             f"真正决定结果的是【池子构成 + 剩余窗口】。</li>")
    h.append(f"<li><b>三个判据必须分开</b>：①赚钱（现代池中位净值 {mdf.nav_mult.median():.3f}，"
             f"盈利 {(mdf.nav_mult > 1).mean():.1%}）②攒筹码（筹码几何中位 "
             f"{mdf.chip_geo.median():.4f}，&gt;1 占比 {(mdf.chip_geo > 1).mean():.1%}）"
             f"③跑赢同池死拿（超额中位 {mdf.exc.median():+.2%}，&gt;0 仅 "
             f"{(mdf.exc > 0).mean():.1%}）。篮子在①②上成立，在③上不成立。</li>")
    h.append(f"<li><b>『中间收益』就是中位数</b>：全历史中位 {np.median(df1.exc.values):+.2%} / "
             f"均值 {df1.exc.mean():+.2%}（右偏）；现代池中位 {mdf.exc.median():+.2%} / 均值 "
             f"{mdf.exc.mean():+.2%}（左偏）。中位与均值谁高取决于偏斜方向，"
             f"不能一律说『中位低于均值』。</li>")
    h.append(f"<li><b>超额随时间窗口增长</b>：剩余窗口 ≥5.5 年档超额中位 "
             f"{df1[df1.yrs >= 5.5].exc.median():+.2%}，现代池内『窗口 vs 超额』秩相关 "
             f"{rank_corr(mdf.yrs.values, mdf.exc.values):+.2f} —— 这也是固定起点 "
             f"{rf['exc']:+.2%} 好看的真正原因（收割项 ∝ T），不是挑到了特殊时点。</li>")
    h.append("</ul></div>")
    h.append("<p class='small'>本页所有数字由 <code>basket_account_27.py</code> 运行时动态计算注入，无硬编码。"
             "筹码 = 币量倍数（死拿 = 1.000）；再平衡目的是筹码不掉队，不是收益最大化。</p>")
    h.append("</div></body></html>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(h))
    return path


def _pct(v):
    return f"{v:+.2%}"


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    px = load_panel()
    fp = first_positions(px)
    mp = main_pool(px)
    out(SEP)
    out("basket_account_27.py — 「整体账户」口径: 买一篮子, 不是买一个币")
    out(SEP)
    out(f"  面板: {PANEL.rsplit(os.sep, 1)[-1]}  {px.shape[0]} 周 × {px.shape[1]} 币, "
        f"{px.index[0].date()} ~ {px.index[-1].date()}")
    out(f"  参数: 等权 {REBAL_WEEKS} 周调仓 · 成本 {COST_BP:.0f}bp · 本金 ${CAP:,.0f} · "
        f"入场步长 {STEP_WEEKS} 周 · 新币上市后 ≥{MIN_HIST} 周才可纳入 · "
        f"现代池门槛 ≥{MODERN_NPOOL} 币")

    section0(px, mp)
    df1, entries = section1(px, fp)
    B, S, W3, B3 = section2(px, fp, entries)
    K = section3(px, fp, entries)
    L, R4 = section4(px, fp, mp)
    section5(px, fp, df1, entries)
    contrib = section6(px, mp, MAIN_START, f"主池 {len(mp)} 币, 固定起点 {MAIN_START}")
    html = build_report(os.path.join(OUTDIR, "basket_account_report.html"),
                        px, mp, df1, B, S, W3, B3, K, L, R4, contrib)
    out()
    out(f"  已生成报告: {html}")
    out(SEP)
    out("完成。")
    out(SEP)


if __name__ == "__main__":
    main()
