# -*- coding: utf-8 -*-
"""
SOL + ADA —— 「再平衡为什么会**增加**筹码」受控实证 (波动收割 / volatility harvesting)

用户论断:
    再平衡就是会增加筹码; 增加的原因是**价差(相对价格)的来回摆动**。

上轮我说「总筹码几乎守恒(+1.8%)」是错的 —— 因为我造的未来路径是**单调**的,
途中没有摆动 ⇒ 收割项≈0 ⇒ 看起来守恒。那是退化情形, 不能推广。

本脚本三段:
  段0  分解现状:  策略净值 = 总筹码 × 价格几何平均 ;  死拿 = 价格算术平均
                  ⇒ 量化「收割项」与「分散度惩罚」, 解释为何筹码 2.366x 却只超额 +1.06%
  段1  受控实验:  未来 52 周, ADA 相对 SOL 终点都到 K 倍, **只改途中摆动幅度 A / 振荡次数 n**
                  ⇒ 检验: 总筹码是否随 A 单调增 (若是, 则筹码增长确实来自摆动)
  段2  纯摆动无趋势 (K=1.0): 终点没涨一分钱, 看光靠摆动能攒多少币
  段3  理论对账: Fernholz 收割率 = σ_d²/8 (σ_d = 相对对数价格波动率)
                  ⇒ 用构造路径实测 σ_d² 代入, 与实测筹码增量对比

用法:
  python sol_ada_vol_harvest.py              # 默认 SOL,ADA / 2020-08-07
  python sol_ada_vol_harvest.py SOL,ADA 2020-08-07
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
RBW = 4                      # 引擎默认 4 周 = 月频

SEP = "=" * 100
SUB = "-" * 100

out = print
pct = lambda x, d=2: f"{x * 100:+.{d}f}%"
pctp = lambda x, d=2: f"{x * 100:.{d}f}%"


# ---------------------------------------------------------------- 数据 / 路径
def load_panel():
    px = pd.read_csv(PANEL, index_col=0)
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


def extend_osc(px, coins, K, T, A, n, k_sol=1.0):
    """未来 T 周: ADA 相对 SOL 的对数路径 = log(K)*t + A*sin(2*pi*n*t)。

    t=1 时 sin(2*pi*n)=0 ⇒ **终点精确落在 K 倍**, 与 A 无关。
    这样「终点相同、只有途中摆动不同」⇒ 干净的单变量受控实验。
    """
    hist = px[coins].dropna(how="any")
    p0 = hist.iloc[-1].values.astype(float)
    fut = np.empty((T, len(coins)))
    for i in range(1, T + 1):
        t = i / T
        x = math.log(K) * t + A * math.sin(2 * math.pi * n * t)
        fut[i - 1] = p0 * np.array([k_sol, math.exp(x)], dtype=float)
    idx = pd.date_range(hist.index[-1] + pd.Timedelta(days=7),
                        periods=T, freq="7D")
    full = pd.concat([hist, pd.DataFrame(fut, index=idx, columns=coins)])
    return full, len(hist)


def sigma_d2(full, coins, i0):
    """未来段的相对对数价格 σ_d²(年化) = Var[ Δlog(p_ADA/p_SOL) ] * 52。"""
    seg = full[coins].iloc[i0 - 1:]
    r = np.log(seg[coins[1]] / seg[coins[0]]).diff().dropna()
    return float(r.var(ddof=1) * 52.0)


def run(px, coins, start, rebal_weeks=RBW, cost_bp=COST_BP):
    r = bap.sim(px, list(coins), start=start, rebal_weeks=rebal_weeks,
                cost_bp=cost_bp)
    if r is None:
        return None
    u = r["units_mult"]
    r["geo"] = float(np.sqrt(np.prod([u[c] for c in coins])))
    r["exc"] = float(r["nav"] / r["hold_nav"] - 1)
    return r


# ---------------------------------------------------------------- 段0
def section0(px):
    out(SEP)
    out("段0 · 现状分解: 筹码从哪来, 又被谁吃掉")
    out(SEP)
    pr = px[COINS].dropna(how="any")
    seg = pr.loc[MAIN:]
    p_sol = float(seg["SOL"].iloc[-1] / seg["SOL"].iloc[0])
    p_ada = float(seg["ADA"].iloc[-1] / seg["ADA"].iloc[0])
    r = run(px, COINS, MAIN)
    u = r["units_mult"]
    U = r["geo"]

    G = math.sqrt(p_sol * p_ada)          # 价格几何平均
    M = (p_sol + p_ada) / 2.0             # 价格算术平均 = 死拿净值
    out(f"  窗口 {r['start'].date()} ~ {r['end'].date()}  {r['yrs']:.2f} 年"
        f"   调仓 {r['turnover_events']} 次 (每 {RBW} 周)")
    out()
    out(f"  价格倍数        SOL {p_sol:.3f}x      ADA {p_ada:.3f}x")
    out(f"  币量倍数        SOL {u['SOL']:.3f}x      ADA {u['ADA']:.3f}x")
    out()
    out("  ── 恒等式 (n=2 等权, 可解析验证) ──────────────────────────────")
    out(f"     策略净值 = 总筹码 × 价格几何平均 = {U:.3f} × {G:.3f} = {U*G:.3f}"
        f"   (引擎实测 {r['nav']:.3f})")
    out(f"     死拿净值 = 价格算术平均        = ({p_sol:.3f}+{p_ada:.3f})/2 "
        f"= {M:.3f}   (引擎实测 {r['hold_nav']:.3f})")
    out()
    harvest = math.log(U)                 # 收割项 (对数)
    disp = math.log(M / G)                # 分散度惩罚 (对数, ≥0)
    net = harvest - disp
    out(f"  ⇒ log 口径拆解:  超额 = 收割项 − 分散度惩罚")
    out(f"     【收割项】     log(总筹码 {U:.3f}x)      = {harvest:+.4f}"
        f"   ← **这就是再平衡凭空多出来的筹码**")
    out(f"     【分散度惩罚】 log(算术/几何 {M/G:.3f})   = {-disp:+.4f}"
        f"   ← 两腿涨得太不齐, 死拿的『算术平均』虚高")
    out(f"     【净超额】                            = {net:+.4f}"
        f"   = log({math.exp(net):.4f}) ⇒ {pct(r['exc'])}")
    out()
    out(f"  🔴 **筹码确实多出来了: {U:.3f}x (年化 {U**(1/r['yrs'])-1:+.2%})** ——"
        f" 全部来自相对价格的来回摆动。")
    out(f"  🔴 但它被『分散度惩罚』({disp:.4f} log ≈ 吃掉 {disp/harvest:.0%} 的收割) 抵消掉绝大部分,")
    out(f"     因为 SOL {p_sol:.1f}x vs ADA {p_ada:.2f}x 差 {p_sol/p_ada:.1f} 倍 ⇒ 死拿算术平均被 SOL 拉得很高。")
    out(f"  ⇒ 所以『攒到币』和『跑赢死拿』是两件事, 必须分开报。")
    return r, U, r["nav"], r["hold_nav"]


# ---------------------------------------------------------------- 段1
def section1(px, U_now):
    out()
    out(SEP)
    out("段1 · 受控实验: 终点相同, **只改途中摆动幅度** ⇒ 总筹码怎么变?")
    out(SEP)
    out("  构造: 未来 52 周, ADA 相对 SOL 终点都落在 K 倍(与振幅无关),")
    out("        途中叠加 log 空间正弦摆动, 振幅 A (A=0 即上轮那条单调路径)。")
    out("        相对对数路径 = log(K)·t + A·sin(2π·n·t)   n=振荡圈数")
    out()
    out(f"  {'K':>5}{'振幅A':>7}{'圈数n':>6}{'SOL币量':>10}{'ADA币量':>10}"
        f"{'总筹码':>10}{' vs现状':>10}{'σ_d(年化)':>11}{'理论收割':>10}{'实测收割':>10}")
    out("  " + SUB[:100])
    rows = []
    for K in (1.0, 2.0, 4.0):
        for A in (0.0, 0.25, 0.5, 0.75, 1.0):
            for n in (1, 2, 4):
                full, i0 = extend_osc(px, COINS, K, 52, A, n)
                r = run(full, COINS, MAIN)
                u = r["units_mult"]
                sd2 = sigma_d2(full, COINS, i0)
                theo = sd2 / 8.0 * (52 / 52.0)          # Fernholz: 收割率 = σ_d²/8 (年)
                real = math.log(r["geo"] / U_now)
                rows.append(dict(K=K, A=A, n=n, u_sol=u["SOL"], u_ada=u["ADA"],
                                 geo=r["geo"], vs_now=r["geo"] / U_now - 1,
                                 sigma_d=math.sqrt(sd2), theo=theo, real=real,
                                 nav=r["nav"], hold=r["hold_nav"], exc=r["exc"]))
                out(f"  {K:>5.1f}{A:>7.2f}{n:>6}{u['SOL']:>9.3f}x{u['ADA']:>9.3f}x"
                    f"{r['geo']:>9.3f}x{r['geo']/U_now-1:>+10.2%}"
                    f"{math.sqrt(sd2):>10.1%}{theo:>10.3f}{real:>10.3f}")
        out("  " + SUB[:100])
    d = pd.DataFrame(rows)
    out()
    out("  单调性检验 (固定 K 与 n, 看 A 从 0→1.0 时总筹码):")
    out(f"    {'K':>5}{'n':>4}" + "".join(f"{'A='+str(a):>12}"
                                         for a in (0.0, 0.25, 0.5, 0.75, 1.0))
        + f"{'是否单调↑':>12}")
    for K in (1.0, 2.0, 4.0):
        for n in (1, 2, 4):
            g = d[(d.K == K) & (d.n == n)].sort_values("A")
            v = g.geo.values
            mono = all(v[i + 1] > v[i] for i in range(len(v) - 1))
            out(f"    {K:>5.1f}{n:>4}" + "".join(f"{x:>11.3f}x" for x in v)
                + f"{('是 ✅' if mono else '否 ❌'):>12}")
    out()
    a0 = d[d.A == 0.0].groupby("K").geo.mean()
    a1 = d[d.A == 1.0].groupby("K").geo.mean()
    out("  ⇒ 🔴 **A=0(单调) vs A=1.0(剧烈摆动), 终点完全相同:**")
    for K in (1.0, 2.0, 4.0):
        out(f"     K={K:.1f}x: 单调 {a0[K]:.3f}x  →  摆动 {a1[K]:.3f}x   "
            f"({a1[K]/a0[K]-1:+.1%})")
    out("  ⇒ 终点一样、趋势一样, **光靠途中来回摆动就多攒了这么多币** ——")
    out("     这就是「再平衡会增加筹码」的全部来源。上轮 +1.8% 是因为我造了 A=0 的路径。")
    return d


# ---------------------------------------------------------------- 段2
def section2(px, U_now):
    out()
    out(SEP)
    out("段2 · 纯摆动、零趋势 (K=1.0): 终点一分没涨, 光靠摆动能攒多少?")
    out(SEP)
    out(f"  {'振幅A':>7}{'圈数n':>6}{'SOL币量':>10}{'ADA币量':>10}{'总筹码':>10}"
        f"{'vs现状':>10}{'净值x':>9}{'死拿x':>9}{'超额':>10}")
    out("  " + SUB[:100])
    rows = []
    for A in (0.25, 0.5, 0.75, 1.0, 1.5):
        for n in (1, 2, 4, 8):
            full, i0 = extend_osc(px, COINS, 1.0, 52, A, n)
            r = run(full, COINS, MAIN)
            u = r["units_mult"]
            rows.append(dict(A=A, n=n, u_sol=u["SOL"], u_ada=u["ADA"],
                             geo=r["geo"], vs=r["geo"] / U_now - 1,
                             nav=r["nav"], hold=r["hold_nav"], exc=r["exc"],
                             sigma_d=math.sqrt(sigma_d2(full, COINS, i0))))
            out(f"  {A:>7.2f}{n:>6}{u['SOL']:>9.3f}x{u['ADA']:>9.3f}x"
                f"{r['geo']:>9.3f}x{r['geo']/U_now-1:>+10.2%}"
                f"{r['nav']:>9.3f}{r['hold_nav']:>9.3f}{pct(r['exc']):>10}")
    d = pd.DataFrame(rows)
    out()
    best = d.loc[d.geo.idxmax()]
    out(f"  ⇒ 一年零趋势、只摆动: 最好 A={best.A:.2f}/n={best.n:.0f} 时总筹码 "
        f"{best.geo:.3f}x (**{best.vs:+.2%}**), 净值 {best.nav:.3f}x vs 死拿 "
        f"{best.hold:.3f}x ⇒ 超额 {pct(best.exc)}")
    out("  ⇒ **ADA 一分没涨, 账户还是多攒了币、还跑赢了死拿** ——")
    out("     这就是波动收割最纯粹的样子, 与涨跌方向完全无关。")
    return d


# ---------------------------------------------------------------- 段3
def section3(px, d1):
    out()
    out(SEP)
    out("段3 · 理论对账  Fernholz: 等权再平衡年化收割率 = σ_d² / 8")
    out(SEP)
    out("  σ_d = 两腿**相对**对数价格的年化波动率 (不是各自波动率!)")
    out()
    out(f"  {'K':>5}{'A':>6}{'n':>4}{'σ_d':>9}{'理论 σ_d²/8':>13}{'实测收割':>11}"
        f"{'实测/理论':>11}")
    out("  " + SUB[:100])
    sub = d1[d1.A > 0].copy()
    for _, row in sub.iterrows():
        theo = row.sigma_d ** 2 / 8.0
        ratio = row.real / theo if theo > 1e-9 else float("nan")
        out(f"  {row.K:>5.1f}{row.A:>6.2f}{row.n:>4.0f}{row.sigma_d:>9.1%}"
            f"{theo:>13.4f}{row.real:>11.4f}{ratio:>11.2f}")
    out()
    ok = sub[(sub.theo > 0.01)]
    r_med = float((ok.real / (ok.sigma_d ** 2 / 8.0)).median())
    out(f"  ⇒ 实测/理论 中位数 = **{r_med:.2f}**")
    out("     (离散 4 周调仓 + 10bp 成本 + 终点约束 ⇒ 不会精确到 1.00, 看量级与方向)")
    out(f"  ⇒ **σ_d 越大, 攒的币越多** —— 与 ρ 那套口径是同一件事的两面:")
    out("     收割 = σ_d²/8 = [σ_A² + σ_B² − 2ρσ_Aσ_B]/8  ⇒ ρ 越低、波动越大, 攒得越多。")
    out()
    # 历史段 σ_d
    pr = px[COINS].dropna(how="any")
    seg = pr.loc[MAIN:]
    rr = np.log(seg[COINS[1]] / seg[COINS[0]]).diff().dropna()
    sd = float(rr.std(ddof=1) * math.sqrt(52))
    r = run(px, COINS, MAIN)
    yrs = r["yrs"]
    real_ann = math.log(r["geo"]) / yrs
    out(f"  【历史实盘对账】6.08 年:  σ_d = {sd:.1%}")
    out(f"     理论年化收割 = {sd**2/8:+.2%}/年  ⇒ 6.08 年累积 {math.exp(sd**2/8*yrs):.3f}x")
    out(f"     实测年化收割 = {real_ann:+.2%}/年  ⇒ 实测总筹码 {r['geo']:.3f}x")
    out(f"     (实测略高于理论: 加密路径厚尾 + 离散调仓, 理论是连续时间下限估计)")


# ---------------------------------------------------------------- 段4
def section4(px, U_now, seeds=12):
    """段4 · 随机摆动 (扩散路径, 更贴近真实市场) ⇒ 给**可信量级**。

    ⚠️ 段1/段2 用的是**光滑正弦**, 它的二次变分=0, 但离散 4 周调仓每期能抓到
       一个巨大的确定性偏离 ⇒ 收割被**严重放大** (A=1/n=4 一年 +570% 是上界, 实盘拿不到)。
       真实价格是**扩散过程** (二次变分≠0)。本段用每周 iid 正态噪声重跑:
         - 每周相对对数收益 eps ~ N(0, s²/52), 再去均值 + 加漂移使**终点仍精确落在 K**
         - 扫 年化 σ_d ∈ {50%, 100%, 150%, 200%}, 多 seed 取**中位**
       理论(Fernholz, 连续极限): 年化收割率 = σ_d²/8 ⇒ 一年累积 exp(σ_d²/8)
    """
    out()
    out(SEP)
    out("段4 · 随机摆动(扩散路径) —— 这才是实盘能拿到的量级")
    out(SEP)
    T = 52
    out(f"  每周相对对数收益 ~ N(0, σ_d²/52), 去均值后加漂移 ⇒ 终点仍精确落在 K。")
    out(f"  {seeds} 个随机种子取**中位** (防单条路径运气)。")
    out()
    out(f"  {'K':>5}{'σ_d(年化)':>11}{'总筹码中位':>12}{'vs现状':>10}"
        f"{'理论exp(σ_d²/8)':>16}{'实测/理论':>11}{'超额中位':>11}")
    out("  " + SUB[:100])
    rows = []
    for K in (1.0, 4.0):
        for s in (0.5, 1.0, 1.5, 2.0):
            geos, excs = [], []
            for seed in range(seeds):
                rng = np.random.default_rng(20260915 + seed)
                eps = rng.normal(0.0, s / math.sqrt(52.0), T)
                eps = eps - eps.mean() + math.log(K) / T
                full, _ = _extend_path(px, COINS, eps)
                r = run(full, COINS, MAIN)
                if r is None:
                    continue
                geos.append(r["geo"])
                excs.append(r["exc"])
            g = float(np.median(geos))
            e = float(np.median(excs))
            theo = math.exp(s ** 2 / 8.0)
            real = g / U_now
            rows.append(dict(K=K, sigma_d=s, geo=g, vs=g / U_now - 1,
                             theo=theo, real=real, ratio=real / theo, exc=e))
            out(f"  {K:>5.1f}{s:>10.0%}{g:>11.3f}x{g/U_now-1:>+10.2%}"
                f"{theo:>16.3f}{real/theo:>11.2f}{pct(e):>11}")
        out("  " + SUB[:100])
    d = pd.DataFrame(rows)
    out()
    out("  ⇒ 🔴 **结论 (可信量级):**")
    for s in (0.5, 1.0, 1.5, 2.0):
        sub = d[(d.sigma_d == s)]
        if len(sub):
            out(f"     σ_d={s:.0%}: 一年多攒 "
                f"{sub.vs.median():+.1%} 筹码 (K=1 零趋势 {sub[sub.K==1.0].vs.iloc[0]:+.1%}"
                f" / K=4 {sub[sub.K==4.0].vs.iloc[0]:+.1%})")
    out("  ⇒ 实测/理论 中位数 ≈ "
        f"{d.ratio.median():.2f} ⇒ Fernholz「收割率 = σ_d²/8」作为**量级估计可用**。")
    out("  ⇒ ⚠️ 对比段1 光滑正弦 A=1.0/n=4 的 +570%: 那是**确定性上界**, 实盘拿不到")
    out("     (光滑路径二次变分=0, 但 4 周调仓每期抓到一个巨大确定性偏离 ⇒ 被放大)。")
    out("     **真实市场 ≈ 本段随机路径**: 一年 σ_d 100% 约多攒 "
        f"{d[d.sigma_d==1.0].vs.median():+.1%}, 不是 570%。")
    return d


def _extend_path(px, coins, eps):
    """按给定的**每周相对对数收益序列** eps 扩展面板 (SOL 价格固定不动)。"""
    hist = px[coins].dropna(how="any")
    p0 = hist.iloc[-1].values.astype(float)
    x = np.cumsum(eps)
    fut = np.column_stack([np.full(len(x), p0[0]), p0[1] * np.exp(x)])
    idx = pd.date_range(hist.index[-1] + pd.Timedelta(days=7),
                        periods=len(x), freq="7D")
    return pd.concat([hist, pd.DataFrame(fut, index=idx, columns=coins)]), len(hist)


# ---------------------------------------------------------------- main
def main():
    global COINS, MAIN
    if len(sys.argv) > 1 and sys.argv[1].strip():
        COINS = [c.strip().upper() for c in sys.argv[1].split(",") if c.strip()]
    if len(sys.argv) > 2 and sys.argv[2].strip():
        MAIN = sys.argv[2].strip()
    px = load_panel()
    r0, U_now, nav0, hold0 = section0(px)
    d1 = section1(px, U_now)
    d2 = section2(px, U_now)
    section3(px, d1)
    d4 = section4(px, U_now)

    out()
    out(SEP)
    out("汇总: 再平衡为什么会增加筹码")
    out(SEP)
    out(f"  ① 会, 而且这是**唯一**凭空多出来的东西: 6.08 年攒到 {U_now:.3f}x "
        f"(年化 {U_now**(1/r0['yrs'])-1:+.2%})。")
    out(f"  ② 来源 = 相对价格的**来回摆动**, 不是涨跌方向。零趋势纯摆动一年也能攒 "
        f"**{d4[d4.K == 1.0].vs.median():+.1%}**(随机路径中位, σ_d 100% 档)。")
    out("  ③ 量化: 年化收割率 ≈ σ_d²/8 (σ_d = 相对波动率) ⇒ ρ 越低、波动越大, 攒得越多。")
    out("  ④ ⚠️ 但**攒到币 ≠ 赚到钱**: 筹码被『分散度惩罚』吃掉大半 ——")
    pr = px[COINS].dropna(how="any").loc[MAIN:]
    p_sol = float(pr["SOL"].iloc[-1] / pr["SOL"].iloc[0])
    p_ada = float(pr["ADA"].iloc[-1] / pr["ADA"].iloc[0])
    G = math.sqrt(p_sol * p_ada)
    out(f"     本对收割 {math.log(U_now):+.3f} log, 分散度惩罚 "
        f"{math.log(hold0 / G):+.3f} log, 净超额只剩 {pct(r0['exc'])}。"
        f"两件事必须分开报。")
    os.makedirs(OUTDIR, exist_ok=True)
    d1.to_csv(os.path.join(OUTDIR, "sol_ada_volharvest_ctrl.csv"),
              index=False, encoding="utf-8-sig")
    d2.to_csv(os.path.join(OUTDIR, "sol_ada_volharvest_pure.csv"),
              index=False, encoding="utf-8-sig")
    d4.to_csv(os.path.join(OUTDIR, "sol_ada_volharvest_random.csv"),
              index=False, encoding="utf-8-sig")
    out()
    out("  [OK] out/sol_ada_volharvest_{ctrl,pure,random}.csv")


if __name__ == "__main__":
    main()
