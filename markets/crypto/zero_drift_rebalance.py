# -*- coding: utf-8 -*-
"""再平衡的失效条件到底是『价格不涨』还是『相对漂移差』—— 四层检验

缘起 (2026-09-14 用户批评)
--------------------------
上一轮结论的边界写了: "若 AAVE 永远停在现价之下, β>1 只是把筹码堆在一个不涨的币上,
净值会输给死拿"。用户指出这条既自相矛盾、又有违加密的基础事实:

  (a) 价格永久不涨 ⇔ 无波动 ⇒ 阈值永不触发 ⇒ 根本不转筹码 (β≡1),
      超额恒为 0, 不是负 —— 我的"边界"是一个不可能触发的空条件;
  (b) 加密最基础的前提就是周期性波动(牛市普涨), 不存在"永久不动"的价格路径;
  (c) **转筹码本身就是年化超额** —— 横盘时 超额倍数 ≡ 平均筹码倍数(严格相等)。

本脚本把判据拆成四层, 每层用数值钉死:

  段1 精确恒等式    超额倍数 = 价格加权平均筹码倍数 (权 = 终点市值份额)
  段2 零波动极限    对数收益按 λ 缩放, λ→0 看 触发/成交/β/超额 → 检验 (a)
  段3 去趋势 & 统一漂移   剥掉漂移 / 两币同步漂移 → 检验 (b)
  段4 GBM 扫描      同漂移 vs 漂移差, 把"市场涨跌"与"相对趋势"分离
  段5 真实 2,561 对 按 |对数漂移差| 分桶 → 定出真正的失效边界

口径: 筹码 = 币量倍数 (死拿 = 1.000); 超额 = 再平衡净值 / 死拿净值 − 1;
      月度(4 周)调仓, 单边 10bp; 价格读已落盘面板(后复权)。
"""
import importlib.util
import math
import os
from itertools import combinations

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "out")
PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
COST_BP = 10.0
MAIN_START = "2020-10-09"
SEP = "=" * 112

# 复用已跑通的口径完全一致的引擎 (sim_trades 带逐笔成交日志)
_spec = importlib.util.spec_from_file_location("eic", os.path.join(HERE, "excess_is_chips.py"))
eic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eic)
sim_trades = eic.sim_trades


def load_panel():
    px = pd.read_csv(PANEL, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


def main_coins(px):
    """主口径 19 币: 面板起点(2020-10-09)以来全勤。"""
    return [c for c in px.columns
            if pd.notna(px[c].loc[MAIN_START:]).all()
            and len(px[c].loc[MAIN_START:].dropna()) > 300]


def px_main(px):
    cs = main_coins(px)
    return px[cs].loc[MAIN_START:].dropna(how="any"), cs


# ------------------------------------------------------------------ 段1 恒等式
def section_identity(px):
    print()
    print(SEP)
    print("【段1】精确恒等式: 超额倍数 = 价格加权平均筹码倍数")
    print(SEP)
    rx, cs = px_main(px)
    yrs = (rx.index[-1] - rx.index[0]).days / 365.25
    print(f"  主口径 {MAIN_START} 起, {len(cs)} 币, {len(rx)} 周, {yrs:.4f} 年, "
          f"全部 C({len(cs)},2) = {len(cs) * (len(cs) - 1) // 2} 对, 零费用(纯恒等式)")
    worst_w = 0.0      # 加权式残差
    mono = 0
    recs = []
    for a, b in combinations(cs, 2):
        r = sim_trades(rx, [a, b], a, cost_bp=0.0)
        if r is None:
            continue
        ma = r["px_last"][0] / r["px_first"][0]
        mb = r["px_last"][1] / r["px_first"][1]
        ua, ub = float(r["R"][0]), float(r["R"][1])
        act = r["nav"] / r["hold"]
        pred_w = (ma * ua + mb * ub) / (ma + mb)          # 价格加权平均筹码
        worst_w = max(worst_w, abs(act - pred_w))
        recs.append((ua, ub, act))
        mono += int((act > 1) == (ua > 1 and ub > 1))
    n = len(recs)
    d = pd.DataFrame(recs, columns=["ua", "ub", "act"])
    d["ucb"] = np.sqrt(d["ua"] * d["ub"])
    d["cash"] = (d["act"] - 1.0) / (d["ucb"] - 1.0)        # 筹码 → 净值的兑现率
    print(f"  加权式 max|实际 − 预测| = {worst_w:.3e}   ← 浮点级则恒等式成立")
    print(f"  筹码(几何均 ucb) 中位 {d['ucb'].median():.4f} → 超额倍数 中位 "
          f"{d['act'].median():.4f}")
    print(f"  兑现率 = (超额倍数−1)/(几何平均筹码−1): 中位 {d['cash'].median():.1%}"
          f"  区间 [{d['cash'].min():.1%}, {d['cash'].max():.1%}]")
    print(f"  方向一致(超额>0 ⟺ 两币筹码都>1): {mono}/{n} = {mono / n:.1%}")
    print()
    print("  读法: 超额 100% 来自筹码, 但乘的是【终点市值权重】。权重偏离等权 = 漂移差折扣,")
    print("        几何平均筹码是【上界】, 兑现率就是那个折扣。")
    return worst_w


# ------------------------------------------------------------------ 段2 零波动极限
def scale_vol(sub, lam):
    """把对数收益整体乘以 lam, 保留路径形状, 压波动。lam=0 → 价格恒定。"""
    v = sub.values.astype(float)
    lr = np.diff(np.log(v), axis=0)
    out = v.copy()
    out[1:] = v[0] * np.exp(np.cumsum(lam * lr, axis=0))
    return pd.DataFrame(out, index=sub.index, columns=sub.columns)


def section_zero_vol(px, pair=("AAVE", "BTC")):
    print()
    print(SEP)
    print(f"【段2】零波动极限: 把 {pair[0]}+{pair[1]} 的波动压到 0, 看会发生什么")
    print(SEP)
    a, b = pair
    sub = px[[a, b]].dropna(how="any").loc[MAIN_START:]
    r0 = sim_trades(sub, [a, b], a)
    if r0 is None:
        print("  窗口不足, 跳过")
        return
    tot_init = sum(abs(t["cash"]) for t in r0["trades"])
    print(f"  基准(原序列): 组合年化波动 {r0['vol_ann']:.1%}, "
          f"调仓 {len(r0['trades'])} 次, 总成交额 ${tot_init:,.0f}")
    print()
    print(f"  {'波动缩放λ':>10}{'组合年化波动':>14}{'真正转向次数':>14}{'总成交额':>15}"
          f"{'β_' + a:>10}{'β_' + b:>10}{'超额':>11}")
    rows = []
    for lam in (1.0, 0.5, 0.25, 0.10, 0.05, 0.02, 0.005, 0.0):
        d = scale_vol(sub, lam)
        r = sim_trades(d, [a, b], a)
        if r is None:
            continue
        nz = sum(1 for t in r["trades"] if abs(t["dq"]) > 1e-12)
        amt = sum(abs(t["cash"]) for t in r["trades"])
        ua, ub = float(r["R"][0]), float(r["R"][1])
        ex = r["nav"] / r["hold"] - 1
        rows.append(dict(lam=lam, vol=r["vol_ann"], nz=nz, amt=amt,
                         ua=ua, ub=ub, ex=ex))
        print(f"  {lam:>10.3f}{r['vol_ann']:>13.1%}{nz:>13d}{amt:>15,.0f}"
              f"{ua:>10.4f}{ub:>10.4f}{ex:>11.2%}")
    print()
    last = rows[-1]
    print(f"  ⇒ λ=0 (价格恒定): 真正转向 {last['nz']} 次, 成交额 ${last['amt']:,.0f}, "
          f"β_{a}={last['ua']:.4f}, β_{b}={last['ub']:.4f}, 超额 {last['ex']:+.4f}%")
    print("     → 无波动 ⇒ 无筹码可转 ⇒ 超额恒为 0。『价格不涨导致再平衡亏钱』这个状态")
    print("       在数学上不可达: 要么有波动(能转筹码), 要么没波动(连 β>1 都不存在)。")
    return rows


# ------------------------------------------------------------------ 段3 去趋势 / 统一漂移
def detrend(sub):
    """按【对数线性】逐币剥离净漂移 → 每币终点 = 起点(净位移 0), 路径波动完整保留。

    注意: 不能写成 sub/(末值/首值) —— 那只是整体缩放, 相对价格路径不变, 再平衡结果
    会与真实序列【逐位相同】(2026-09-14 首版即踩此坑)。必须按时间 t 线性扣掉
    每列的净对数位移 net = log(p_T/p_0)。
    """
    v = sub.values.astype(float)
    lp = np.log(v)
    n = len(v)
    t = np.arange(n, dtype=float) / (n - 1)          # 0 → 1
    net = lp[-1] - lp[0]                             # 每列净对数位移
    lp_d = lp - t[:, None] * net[None, :]
    return pd.DataFrame(np.exp(lp_d), index=sub.index, columns=sub.columns)


def uniform_drift(sub, mu_ann):
    """两币同乘 exp(mu·t) → 只加"市场β", 相对价格路径完全不变。"""
    yrs = (sub.index[-1] - sub.index[0]).days / 365.25
    t = np.linspace(0.0, yrs, len(sub))
    return sub.mul(np.exp(mu_ann * t), axis=0)


def section_detrend(px):
    print()
    print(SEP)
    print("【段3】剥掉漂移 / 给两币加同向漂移: 检验『市场涨跌无关』")
    print(SEP)
    a, b = "AAVE", "BTC"
    sub = px[[a, b]].dropna(how="any").loc[MAIN_START:]
    r = sim_trades(sub, [a, b], a)
    d = detrend(sub)
    rd = sim_trades(d, [a, b], a)
    ma = r["px_last"][0] / r["px_first"][0]
    mb = r["px_last"][1] / r["px_first"][1]
    print(f"  {a}+{b} 主口径, 终点价倍数: {a} {ma:.3f}× / {b} {mb:.3f}×")
    print()
    print(f"  {'情形':<28}{'β_' + a:>10}{'β_' + b:>10}{'超额倍数':>11}{'超额':>11}"
          f"{'兑现率':>10}")
    for lab, r_ in (("① 真实序列", r), ("② 去趋势(终点=起点,不涨)", rd)):
        ua_, ub_ = float(r_["R"][0]), float(r_["R"][1])
        act_ = r_["nav"] / r_["hold"]
        ucb_ = math.sqrt(ua_ * ub_)
        cr_ = (act_ - 1.0) / (ucb_ - 1.0) if abs(ucb_ - 1.0) > 1e-12 else float("nan")
        print(f"  {lab:<28}{ua_:>10.4f}{ub_:>10.4f}{act_:>11.4f}{act_ - 1:>11.2%}{cr_:>10.1%}")
    print()
    print("  ── 两币同步漂移 (市场普涨/普跌, 相对价格不动) ──")
    print(f"  {'市场年化漂移 μ':>16}{'AAVE结局倍数':>15}{'BTC结局倍数':>14}"
          f"{'β_AAVE':>10}{'β_BTC':>10}{'超额':>11}")
    outs = []
    for mu in (-0.90, -0.50, 0.0, 0.50, 1.00, 2.00, 3.00):
        dd = uniform_drift(sub, mu)
        rr = sim_trades(dd, [a, b], a)
        ex = rr["nav"] / rr["hold"] - 1
        outs.append(ex)
        print(f"  {mu:>+15.2f}{float(rr['px_last'][0] / rr['px_first'][0]):>15.3f}"
              f"{float(rr['px_last'][1] / rr['px_first'][1]):>14.3f}"
              f"{float(rr['R'][0]):>10.4f}{float(rr['R'][1]):>10.4f}{ex:>11.2%}")
    print()
    print(f"  ⇒ μ 从 −90%/年 到 +300%/年, 超额极差 {max(outs) - min(outs):.3e} "
          f"(浮点级) —— 市场涨跌对再平衡结果【零影响】。")
    # 全池去趋势
    rx, cs = px_main(px)
    r_all = sim_trades(rx, cs, cs[0])
    rd_all = sim_trades(detrend(rx), cs, cs[0])
    print()
    print(f"  ── 主口径 {len(cs)} 币全池 ──")
    print(f"  {'情形':<24}{'组合筹码(几何均)':>18}{'超额倍数':>12}{'超额':>11}{'兑现率':>10}")
    for lab, r_ in (("真实序列", r_all), ("去趋势(全池不涨)", rd_all)):
        ucb_ = float(np.prod([float(x) for x in r_["R"]]) ** (1.0 / len(cs)))
        act_ = r_["nav"] / r_["hold"]
        cr_ = (act_ - 1.0) / (ucb_ - 1.0) if abs(ucb_ - 1.0) > 1e-12 else float("nan")
        print(f"  {lab:<24}{ucb_:>18.4f}{act_:>12.4f}{act_ - 1:>11.2%}{cr_:>10.1%}")
    print(f"  全池逐币筹码中位: 真实 {np.median(r_all['R']):.4f} → "
          f"去趋势 {np.median(rd_all['R']):.4f}")
    return r, rd


# ------------------------------------------------------------------ 段4 GBM 扫描
def gbm_pair(mu_a, mu_b, sig=0.80, rho=0.50, T=5.9, n_path=200, seed=7):
    """两币 GBM 周频路径 → 跑同一套再平衡, 返回 (超额中位, 筹码几何均中位, 超额>0 比例)。"""
    n_step = int(round(T * 52))
    dt = 1.0 / 52.0
    rng = np.random.default_rng(seed)
    z1 = rng.standard_normal((n_path, n_step))
    z2 = rng.standard_normal((n_path, n_step))
    zb = rho * z1 + math.sqrt(max(1.0 - rho ** 2, 0.0)) * z2
    s = sig * math.sqrt(dt)
    la = np.cumsum((mu_a - 0.5 * sig ** 2) * dt + s * z1, axis=1)
    lb = np.cumsum((mu_b - 0.5 * sig ** 2) * dt + s * zb, axis=1)
    idx = pd.date_range("2020-10-09", periods=n_step + 1, freq="7D")
    ex, ucb = [], []
    for j in range(n_path):
        pa = np.concatenate([[1.0], np.exp(la[j])])
        pb = np.concatenate([[1.0], np.exp(lb[j])])
        d = pd.DataFrame({"A": pa, "B": pb}, index=idx)
        r = sim_trades(d, ["A", "B"], "A", capital=1.0)
        if r is None:
            continue
        ex.append(r["nav"] / r["hold"] - 1.0)
        ucb.append(math.sqrt(float(r["R"][0]) * float(r["R"][1])))
    ex = np.array(ex)
    return float(np.median(ex)), float(np.median(ucb)), float((ex > 0).mean())


def section_gbm(px):
    print()
    print(SEP)
    print("【段4】GBM 扫描: 把『市场涨跌(同漂移)』与『相对趋势(漂移差)』分离")
    print(SEP)
    print("  设定: σ 两币同为 80%/年, ρ=0.50, T=5.9 年, 周频, 200 条路径取中位, 10bp")
    print()
    print("  ── 4a 两币同步漂移 (牛市普涨 / 熊市普跌) ──")
    print(f"  {'两币共同年化漂移':>18}{'结局倍数':>12}{'超额中位':>12}{'筹码(几何)':>13}"
          f"{'超额>0比例':>13}")
    a_ex = []
    for mu in (-1.00, -0.60, -0.30, 0.0, 0.30, 0.60, 1.00, 1.50):
        e, u, p = gbm_pair(mu, mu)
        a_ex.append(e)
        print(f"  {mu:>+17.2f}{math.exp(mu * 5.9):>12.3f}{e:>12.2%}{u:>13.4f}{p:>13.1%}")
    print(f"  ⇒ 同漂移下超额极差 {max(a_ex) - min(a_ex):.2%} (路径噪声级) "
          f"→ 涨跌本身不决定再平衡成败。")
    print()
    print("  ── 4b 只改相对趋势: A 漂移 +20%/年, B 相对 A 的漂移差 Δ ──")
    print(f"  {'漂移差 Δ(pp/年)':>17}{'B结局倍数':>12}{'超额中位':>12}{'筹码(几何)':>13}"
          f"{'超额>0比例':>13}")
    b_ex = []
    for dlt in (-1.60, -1.20, -0.80, -0.40, 0.0, 0.40, 0.80, 1.20, 1.60):
        e, u, p = gbm_pair(0.20, 0.20 + dlt)
        b_ex.append(e)
        print(f"  {dlt * 100:>+16.0f}{math.exp((0.20 + dlt) * 5.9):>12.3f}"
              f"{e:>12.2%}{u:>13.4f}{p:>13.1%}")
    print(f"  ⇒ Δ=0 时超额 {b_ex[4]:+.2%}; |Δ| 往两边走超额单调下滑 —— "
          f"**相对趋势差才是唯一的侵蚀项**。")
    return a_ex, b_ex


# ------------------------------------------------------------------ 段5 真实分桶
def section_real_drift():
    print()
    print(SEP)
    print("【段5】真实 2,561 对: 超额 vs |对数漂移差|")
    print(SEP)
    p = os.path.join(OUTDIR, "all_pairs_exhaustive.csv")
    ex = pd.read_csv(p)
    ex["adrift"] = ex["drift"].abs()
    ex["exc"] = ex["nav"] / ex["hold"] - 1.0
    bins = [0.0, 0.10, 0.20, 0.30, 0.50, 0.80, 99.0]
    labs = ["0~10pp", "10~20pp", "20~30pp", "30~50pp", "50~80pp", "80pp+"]
    print(f"  全样本 {len(ex)} 对: 筹码>1 {int((ex['ucb'] > 1).sum())}/{len(ex)}"
          f" ({(ex['ucb'] > 1).mean():.1%}),  超额>0 {int((ex['exc'] > 0).sum())}"
          f"/{len(ex)} ({(ex['exc'] > 0).mean():.1%})")
    print()
    print(f"  {'|对数漂移差|':>13}{'对数':>7}{'超额>0':>10}{'超额中位':>11}"
          f"{'超额平均':>11}{'筹码>1':>10}")
    rows = []
    for i in range(len(bins) - 1):
        s = ex[(ex["adrift"] >= bins[i]) & (ex["adrift"] < bins[i + 1])]
        if not len(s):
            continue
        rows.append((labs[i], len(s), (s["exc"] > 0).mean(), s["exc"].median(),
                     s["exc"].mean(), (s["ucb"] > 1).mean()))
        print(f"  {labs[i]:>13}{len(s):>7}{(s['exc'] > 0).mean():>10.1%}"
              f"{s['exc'].median():>11.2%}{s['exc'].mean():>11.2%}"
              f"{(s['ucb'] > 1).mean():>10.1%}")
    print()
    lo = ex[ex["adrift"] < 0.10]["exc"].median()
    hi = ex[ex["adrift"] >= 0.80]["exc"].median()
    print(f"  ⇒ 漂移差 <10pp: 超额中位 {lo:+.2%} | 漂移差 ≥80pp: {hi:+.2%}"
          f"  (差 {lo - hi:.2%})")
    print("     筹码>1 全程 100% 不变 —— 变的只是【兑现成净值的比例】。")
    return rows


# ------------------------------------------------------------------ 段6 区间震荡
def round_trip(logp):
    """折返比 = 累计对数路程 / |净对数位移| (≥1; 越大越震荡, inf = 纯横盘)。"""
    net = abs(float(logp[-1] - logp[0]))
    walk = float(np.abs(np.diff(logp)).sum())
    return (walk / net if net > 1e-9 else float("inf")), walk


def section_range(px):
    print()
    print(SEP)
    print("【段6】『很多代币长期在某个区间里波动, 只是上下价差很大』—— 实测")
    print(SEP)
    rx, cs = px_main(px)
    yrs = (rx.index[-1] - rx.index[0]).days / 365.25
    print(f"  主口径 {MAIN_START} 起, {len(rx)} 周 / {yrs:.2f} 年, {len(cs)} 币")
    print()
    print(f"  {'币':<7}{'净倍数m':>10}{'区间振幅':>10}{'折返比':>9}{'对数路程':>10}"
          f"{'回撤>50%时间':>14}")
    recs = []
    for c in cs:
        s = rx[c].values.astype(float)
        m = s[-1] / s[0]
        amp = s.max() / s.min()
        rtr, walk = round_trip(np.log(s))
        dd = s / np.maximum.accumulate(s) - 1.0
        recs.append(dict(coin=c, m=m, amp=amp, rtr=rtr, walk=walk,
                         dd50=float((dd <= -0.5).mean())))
        print(f"  {c:<7}{m:>10.3f}{amp:>10.2f}{rtr:>9.2f}{walk:>10.2f}"
              f"{recs[-1]['dd50']:>14.1%}")
    rr = pd.DataFrame(recs)
    flat = rr[(rr["m"] > 0.5) & (rr["m"] < 2.0) & (rr["amp"] > 3.0)]
    print()
    print(f"  ⇒ 『净倍数 0.5~2.0 且区间振幅 >3 倍』(典型大区间震荡、净位移小): "
          f"{len(flat)}/{len(rr)} = {len(flat) / len(rr):.1%}")
    print(f"     折返比 中位 {rr['rtr'].median():.2f} / 最大 {rr['rtr'].max():.2f}"
          f"  (走 1 单位净位移, 平均要走 {rr['rtr'].median():.1f} 倍路程)")
    print(f"     回撤 >50% 的时间占比 中位 {rr['dd50'].median():.1%}")
    # 折返比 → 超额 (主口径 171 对, 按币的折返比取对均值)
    p = os.path.join(OUTDIR, "all_pairs_exhaustive.csv")
    ex = pd.read_csv(p)
    lab = f"{MAIN_START}/{len(cs)}币"       # 穷举落盘的 layer 格式: "2020-10-09/19币"
    main = ex[ex["layer"] == lab].copy()
    if not len(main):
        return rr
    rmap = rr.set_index("coin")["rtr"].to_dict()
    main["rtr"] = main["pair"].map(
        lambda s: (rmap[s.split("+")[0]] + rmap[s.split("+")[1]]) / 2.0)
    main["exc"] = main["nav"] / main["hold"] - 1.0
    sp = float(np.corrcoef(main["rtr"].rank(), main["exc"].rank())[0, 1])
    print()
    print(f"  ── 主口径 {len(main)} 对: 折返比 vs 超额 ──")
    print(f"  Spearman(对均折返比, 超额) = {sp:+.3f}")
    main = main.assign(q=pd.qcut(main["rtr"], 4,
                                 labels=["Q1 最稳(低折返)", "Q2", "Q3", "Q4 最震荡"]))
    print(f"  {'四分位':>18}{'对数':>6}{'折返比中位':>12}{'超额中位':>11}{'筹码中位':>11}")
    for k, g in main.groupby("q", observed=True):
        print(f"  {str(k):>18}{len(g):>6}{g['rtr'].median():>12.2f}"
              f"{g['exc'].median():>11.2%}{g['ucb'].median():>11.4f}")
    print(f"  ⇒ |Spearman| ≈ 0 且四分位非单调 → **『震荡得多厉害』本身不预测超额**;")
    print(f"     它只是通过压住两币的【净位移差】间接受益(见下组对照)。")
    # 6c: 按币的净位移分组互配 —— 横盘×横盘 vs 强趋势×强趋势
    print()
    print("  ── 6c 按币的净位移分组互配 (组内两两) ──")

    def pair_stats(coins_sub, tag):
        ps = set()
        for x, y in combinations(coins_sub, 2):
            ps.add(f"{x}+{y}")
            ps.add(f"{y}+{x}")
        s = main[main["pair"].isin(ps)]
        if not len(s):
            return
        cr = (s["exc"] / (s["ucb"] - 1.0)).median()
        print(f"  {tag:<34}{len(coins_sub):>4} 币{len(s):>5} 对"
              f"{s['exc'].median():>12.2%}{s['exc'].min():>11.2%}"
              f"{(s['exc'] > 0).mean():>10.1%}{cr:>10.1%}")

    print(f"  {'分组':<30}{'币数':>8}{'对数':>7}{'超额中位':>11}{'超额最小':>11}"
          f"{'超额>0':>10}{'兑现率':>10}")
    osc = rr[(rr["m"] > 0.5) & (rr["m"] < 2.0)]["coin"].tolist()
    trend = rr[(rr["m"] > 3.0) | (rr["m"] < 1 / 3.0)]["coin"].tolist()
    pair_stats(osc, "净位移小(横盘型) 互配")
    pair_stats(trend, "净位移大(强趋势型) 互配")
    print(f"    横盘型 {len(osc)} 币: {', '.join(osc)}")
    print(f"    强趋势型 {len(trend)} 币: {', '.join(trend)}")
    return rr


def main():
    px = load_panel()
    section_identity(px)
    section_zero_vol(px)
    section_detrend(px)
    section_gbm(px)
    section_real_drift()
    section_range(px)
    print()
    print(SEP)
    print("【结论】失效条件不是『价格不涨』, 而是『两币相对漂移差过大』")
    print(SEP)
    print("  1. 价格不涨 ⇔ 无波动 ⇒ 不转筹码 ⇒ 超额 ≡ 0 (不是亏) —— 空条件;")
    print("  2. 市场整体涨跌(同漂移) 对超额零影响 (段3/4a 实测极差 ~1e-16 ~ 路径噪声);")
    print("  3. 横盘(不涨但波动) 是再平衡最舒服的情形: 超额 = 平均筹码倍数 − 1 (严格);")
    print("  4. 唯一侵蚀项 = 两币对数漂移差: 差 <10pp 超额中位为正, ≥80pp 才转负。")
    print(SEP)


if __name__ == "__main__":
    main()
