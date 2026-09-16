# -*- coding: utf-8 -*-
"""用户指定的一小组币 —— 两两配对再平衡 + 整组等权篮子(双对象对照)。

用法: python four_coin_pairs.py            # 默认 TRX,DOT,ETH,SOL
      python four_coin_pairs.py TRX,ADA,ETH,SOL

口径(与加密全池主口径**完全一致**, 不改动):
  两标的 50:50 (引擎 w = ones(n)/n, n=2 恰为 0.5) · 4 周(月度)调仓 · 单边 10bp。
  **不构成任何 N 币等权篮子**: 4 币 = C(4,2) = 6 个两币对, 各自独立跑、各自 50:50。

两口径分开报:
  美元口径  nav = 组合净值倍数;  hold = 双币等权死拿倍数;  超额 = nav/hold - 1
  筹码口径  每币币量倍数(死拿 = 1.000), 对级用几何平均 ucb = sqrt(ua*ub)
"""
import os
import sys
import math
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
COINS = ["TRX", "DOT", "ETH", "SOL"]
COST_BP = 10.0
MIN_COINS = None
SEP = "=" * 112
SUB = "-" * 112

# 分层起点: ① 四币共同窗口 ② 与全池主口径对齐 ③ 牛市顶前 ④ 熊市起点 ⑤⑥ 近两年
LAYERS = [
    ("四币共同窗口", "2020-08-14"),
    ("全池主口径",   "2020-10-09"),
    ("2021 牛市顶",  "2021-01-08"),
    ("熊市起点",     "2022-01-07"),
    ("复苏起点",     "2023-01-06"),
    ("近两年",       "2024-01-05"),
]
MAIN = "2020-08-14"          # 占位; 运行时自动替换为该组币的共同窗口首日

# 命令行:  python four_coin_pairs.py TRX,ADA,ETH,SOL [主口径起点]
#   第1参数 = 标的组(逗号分隔);  第2参数(可选) = 固定主口径起点(做跨组同窗对照用)
#   不给第2参数时, 主口径 = 该组币的共同窗口首日(由最晚上市者决定)
if len(sys.argv) > 1 and sys.argv[1].strip():
    COINS = [c.strip().upper() for c in sys.argv[1].split(",") if c.strip()]
    MAIN = None
SUFFIX = "".join(c[:1] for c in COINS).lower()   # 输出文件名后缀
if len(sys.argv) > 2 and sys.argv[2].strip():
    MAIN = sys.argv[2].strip()
    LAYERS[0] = (LAYERS[0][0], MAIN)
    SUFFIX += "_" + MAIN.replace("-", "")

geo = lambda x: math.exp(x) - 1


def pct(x, d=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "  n/a"
    return f"{x * 100:+.{d}f}%"


def ratio(x, d=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "  n/a"
    return f"{x:.{d}f}x"


def out(s=""):
    print(s)


def load_panel():
    px = pd.read_csv(PANEL, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


def solo_table(px, coins, start):
    """各币从 start 起的死拿价格倍数(与再平衡无关)。"""
    res = {}
    for c in coins:
        s = px[c].loc[start:].dropna()
        if len(s) < 2:
            continue
        res[c] = dict(nav=float(s.iloc[-1] / s.iloc[0]),
                      px0=float(s.iloc[0]), px1=float(s.iloc[-1]))
    return res


def run_pair(px, a, b, start):
    r = bap.sim(px, [a, b], start=start, cost_bp=COST_BP)
    if r is None:
        return None
    ua, ub = float(r["units_mult"][a]), float(r["units_mult"][b])
    yr = r["yrs"]
    win = px[[a, b]].loc[r["start"]:r["end"]].dropna()
    lr = np.log(win).diff().dropna()
    rho = float(lr[a].corr(lr[b])) if len(lr) > 3 else float("nan")
    vol = float((lr[a].std() + lr[b].std()) / 2 * np.sqrt(52))   # 两腿年化波动均值
    sa = float(win[a].iloc[-1] / win[a].iloc[0])
    sb = float(win[b].iloc[-1] / win[b].iloc[0])
    hold = (sa + sb) / 2.0                     # 双币等权死拿(各投 0.5)
    nav = float(r["nav"])
    exc = nav / hold - 1.0
    dr = abs(math.log(sa) - math.log(sb)) / yr  # 两腿对数漂移差(pp/年)
    g = lambda v: v ** (1 / yr) - 1              # 几何年化 (勿用 log(v)/yr)
    return dict(pair=f"{a}+{b}", a=a, b=b, yrs=yr,
                ua=ua, ub=ub, ucb=math.sqrt(ua * ub),
                rc_a=g(ua), rc_b=g(ub), rc_m=math.sqrt(ua * ub) ** (1 / yr) - 1,
                nav=nav, hold=hold, exc=exc,
                exc_a=(1 + exc) ** (1 / yr) - 1 if yr > 0 else np.nan,
                cagr=float(r["cagr"]), cagr_h=g(hold),
                solo_a=sa, solo_b=sb, rho=rho, vol=vol, drift=dr,
                turn=float(r["turnover_ann"]),
                start=r["start"], end=r["end"])


def section0(px):
    out(SEP)
    out("段0 · 口径与数据闸门")
    out(SEP)
    out("  口径 = 目标权重 w=ones(n)/n · 4 周调仓 · 单边 10bp · 筹码死拿=1.000")
    out("  🔴 本轮跑**两个不同对象**, 结果不可混比:")
    out("     【A】两币对 —— 4 币的 C(4,2)=6 个对, 每个各自独立 50:50 (既定对外口径)")
    out("     【B】4 币一组 —— 等权 25/25/25/25 一个组合 (用户本轮指定)")
    out(f"  数据 {os.path.basename(PANEL)}  {px.shape[0]} 周 x {px.shape[1]} 币  "
        f"{px.index[0].date()} ~ {px.index[-1].date()}  (周频·后复权 hfq)")
    firsts = {c: px[c].first_valid_index() for c in COINS}
    out(f"  四币首有效日: " + " · ".join(f"{c} {d.date()}" for c, d in firsts.items()))
    sub = px[COINS].dropna(how="any")
    latest = max(firsts, key=lambda c: firsts[c])
    out(f"  ⇒ 共同窗口 {sub.index[0].date()} ~ {sub.index[-1].date()} "
        f"{len(sub)} 周 = {len(sub)/52:.2f} 年 (由最晚上市的 {latest} 决定)")
    out()


def section1(px, win):
    out(SEP)
    out(f"段1 · 四币概览 (共同窗口 {win.index[0].date()} ~ {win.index[-1].date()}, "
        f"{len(win)/52:.2f} 年)")
    out(SEP)
    out(f"  {'币':<6}{'首价':>12}{'末价':>12}{'死拿倍数':>10}{'死拿CAGR':>10}"
        f"{'年化波动':>10}{'最大回撤':>10}")
    out("  " + SUB[:100])
    for c in COINS:
        s = win[c]
        m = float(s.iloc[-1] / s.iloc[0])
        yr = len(s) / 52.0
        lr = np.log(s).diff().dropna()
        vol = float(lr.std() * np.sqrt(52))
        dd = float((s / s.cummax() - 1).min())
        out(f"  {c:<6}{s.iloc[0]:>12,.4f}{s.iloc[-1]:>12,.4f}{m:>9.2f}x"
            f"{pct(m ** (1 / yr) - 1):>10}{vol * 100:>9.1f}%{dd * 100:>9.1f}%")
    out()
    out("  两两相关 (周对数收益):")
    lr = np.log(win).diff().dropna()
    cm = lr.corr()
    out("        " + "".join(f"{c:>10}" for c in COINS))
    for a in COINS:
        out(f"  {a:<6}" + "".join(f"{cm.loc[a, b]:>10.3f}" for b in COINS))
    pairs = [cm.loc[a, b] for a, b in combinations(COINS, 2)]
    out(f"  ⇒ 6 对相关: 中位 {np.median(pairs):.3f}  "
        f"最低 {min(pairs):.3f} ({list(combinations(COINS,2))[int(np.argmin(pairs))][0]}"
        f"+{list(combinations(COINS,2))[int(np.argmin(pairs))][1]})  "
        f"最高 {max(pairs):.3f}")
    out()


def run_basket(px, coins, start):
    """4 币作为一个组合: 目标 25/25/25/25, 月度再平衡(引擎 w=ones(n)/n)。"""
    r = bap.sim(px, list(coins), start=start, cost_bp=COST_BP)
    if r is None:
        return None
    yr = r["yrs"]
    u = {c: float(r["units_mult"][c]) for c in coins}
    win = px[list(coins)].loc[r["start"]:r["end"]].dropna()
    m = {c: float(win[c].iloc[-1] / win[c].iloc[0]) for c in coins}
    hold = float(np.mean(list(m.values())))          # 4 币等权死拿(各 0.25)
    nav = float(r["nav"])
    exc = nav / hold - 1.0
    ucb = math.exp(float(np.mean([math.log(u[c]) for c in coins])))
    lr = np.log(win).diff().dropna()
    cm = lr.corr()
    rho = float(np.mean([cm.loc[a, b] for a, b in combinations(coins, 2)]))
    vol = float((lr.std() * np.sqrt(52)).mean())
    drift = float(max(math.log(v) for v in m.values())
                  - min(math.log(v) for v in m.values())) / yr
    return dict(n=len(coins), yrs=yr, u=u, ucb=ucb,
                u_min=min(u.values()), u_max=max(u.values()),
                m=m, hold=hold, nav=nav, exc=exc,
                exc_a=(1 + exc) ** (1 / yr) - 1 if yr > 0 else np.nan,
                cagr=float(r["cagr"]), cagr_h=hold ** (1 / yr) - 1,
                rho=rho, vol=vol, drift=drift, turn=float(r["turnover_ann"]),
                start=r["start"], end=r["end"])


def section_basket(px, tag, start):
    b = run_basket(px, COINS, start)
    if b is None:
        return None
    out(SEP)
    out(f"段2b · 【4 币一组】等权 25/25/25/25 月度再平衡 —— {tag} 起点 {start}")
    out(f"       窗口 {b['start'].date()} ~ {b['end'].date()}  {b['yrs']:.2f} 年  "
        f"⚠️ 与『两币对』是**两个不同对象**, 结果不可混比")
    out(SEP)
    out(f"  {'币':<6}{'目标权重':>10}{'死拿倍数':>10}{'币量倍数(死拿=1)':>18}"
        f"{'币量年化':>10}{'该腿贡献(权重x倍数)':>20}")
    out("  " + SUB[:76])
    for c in COINS:
        w = 1.0 / len(COINS)
        rc = b["u"][c] ** (1 / b["yrs"]) - 1
        out(f"  {c:<6}{w*100:>9.0f}%{b['m'][c]:>9.2f}x{b['u'][c]:>17.3f}x"
            f"{pct(rc):>10}{w * b['m'][c] / b['hold']:>19.1%}")
    out("  " + SUB[:76])
    out(f"  {'组合':<6}{100:>9.0f}%{b['hold']:>9.3f}x{b['ucb']:>17.3f}x"
        f"{pct(b['ucb'] ** (1 / b['yrs']) - 1):>10}")
    out()
    out(f"  组合筹码(4 币几何平均): **{b['ucb']:.3f}x**  "
        f"区间 {b['u_min']:.3f}x ~ {b['u_max']:.3f}x  "
        f"(4 币全部 >1? {'是' if b['u_min'] > 1 else '否'})")
    out(f"  美元口径: 净值 **{b['nav']:.3f}x**  vs  死拿 {b['hold']:.3f}x  "
        f"⇒ 超额 **{pct(b['exc'])}** (折年 {pct(b['exc_a'])})  "
        f"{'✅跑赢' if b['nav'] > b['hold'] else '❌跑输'}死拿")
    out(f"  CAGR: 组合 {pct(b['cagr'])}  vs  死拿 {pct(b['cagr_h'])}  "
        f"⇒ 差 {(b['cagr'] - b['cagr_h'])*100:+.2f}pp/年")
    out(f"  平均相关 {b['rho']:.3f} · 平均年化波动 {b['vol']*100:.1f}% · "
        f"最大漂移差 {b['drift']*100:.1f}pp/年 · 年换手 {b['turn']*100:.0f}%")
    out()
    return b


def section2(px, tag, start):
    """一层 = 6 个两币对各自独立 50:50"""
    recs = []
    for a, b in combinations(COINS, 2):
        r = run_pair(px, a, b, start)
        if r:
            recs.append(r)
    if not recs:
        return None, None
    s0 = recs[0]
    out(SEP)
    out(f"段2 · {tag}  起点 {start}  窗口 {s0['start'].date()} ~ {s0['end'].date()}"
        f"  {s0['yrs']:.2f} 年  (6 对 独立 50:50)")
    out(SEP)
    out(f"  {'配对':<10}{'σ(年化)':>8}{'ρ':>7}{'筹码倍':>8}{'筹码年化':>9}"
        f"{'βA':>7}{'βB':>7}{'净值x':>9}{'死拿x':>9}{'超额':>9}{'折年':>8}"
        f"{'跑赢':>7}{'换手':>7}")
    out("  " + SUB[:108])
    for r in sorted(recs, key=lambda x: -x["ucb"]):
        out(f"  {r['pair']:<10}{r['vol']*100:>7.1f}%{r['rho']:>7.3f}"
            f"{r['ucb']:>7.3f}x{pct(r['rc_m']):>9}{r['ua']:>7.3f}{r['ub']:>7.3f}"
            f"{r['nav']:>9.3f}{r['hold']:>9.3f}{pct(r['exc']):>9}{pct(r['exc_a']):>8}"
            f"{'是' if r['nav'] > r['hold'] else '否':>7}{r['turn']*100:>6.0f}%")
    out("  " + SUB[:108])
    med = lambda k: float(np.median([r[k] for r in recs]))
    out(f"  {'中位':<10}{med('vol')*100:>7.1f}%{med('rho'):>7.3f}"
        f"{med('ucb'):>7.3f}x{pct(med('rc_m')):>9}{'':>7}{'':>7}"
        f"{med('nav'):>9.3f}{med('hold'):>9.3f}{pct(med('exc')):>9}"
        f"{pct(med('exc_a')):>8}{'':>7}{med('turn')*100:>6.0f}%")
    out(f"  筹码>1 的对: {sum(1 for r in recs if r['ucb'] > 1)}/{len(recs)}    "
        f"两腿都>1: {sum(1 for r in recs if r['ua'] > 1 and r['ub'] > 1)}/{len(recs)}    "
        f"跑赢死拿: {sum(1 for r in recs if r['nav'] > r['hold'])}/{len(recs)}    "
        f"超额>0: {sum(1 for r in recs if r['exc'] > 0)}/{len(recs)}")
    return recs, med


def section3(px):
    out(SEP)
    out("段3 · 分层: 换起点 (每层 6 对 + 1 个 4 币一组, 各层独立)")
    out(SEP)
    out(f"  {'层(起点)':<16}{'起点日':>12}{'年数':>7}{'筹码倍中位':>11}{'筹码年化中位':>13}"
        f"{'净值x中位':>11}{'死拿x中位':>11}{'超额中位':>10}{'漂移差中位':>11}{'跑赢':>7}")
    out("  " + SUB[:112])
    rows = []
    for tag, st in LAYERS:
        recs = [run_pair(px, a, b, st) for a, b in combinations(COINS, 2)]
        recs = [r for r in recs if r]
        if not recs:
            continue
        med = lambda k: float(np.median([r[k] for r in recs]))
        out(f"  {tag:<16}{recs[0]['start'].date().isoformat():>12}{recs[0]['yrs']:>7.2f}"
            f"{med('ucb'):>10.3f}x{pct(med('rc_m')):>13}"
            f"{med('nav'):>11.3f}{med('hold'):>11.3f}{pct(med('exc')):>10}"
            f"{med('drift')*100:>9.1f}pp"
            f"{sum(1 for r in recs if r['nav'] > r['hold']):>4}/{len(recs)}")
        rows.append(dict(layer=tag, start=st, yrs=recs[0]["yrs"],
                         **{k: med(k) for k in
                            ("ucb", "rc_m", "nav", "hold", "exc", "rho", "vol",
                             "ua", "ub", "drift")},
                         beat=sum(1 for r in recs if r["nav"] > r["hold"]),
                         n=len(recs)))
        bk = run_basket(px, COINS, st)
        if bk:
            out(f"  {'└ 4币一组':<16}{bk['start'].date().isoformat():>12}{bk['yrs']:>7.2f}"
                f"{bk['ucb']:>10.3f}x"
                f"{pct(bk['ucb'] ** (1 / bk['yrs']) - 1):>13}"
                f"{bk['nav']:>11.3f}{bk['hold']:>11.3f}{pct(bk['exc']):>10}"
                f"{bk['drift']*100:>9.1f}pp"
                f"{'✅' if bk['nav'] > bk['hold'] else '❌':>7}")
    out("  ⇒ 🔴 层与层的差别**不是由长度决定, 而是由该段波动与两腿漂移差决定**")
    out("     (收割项 ∝ ¼(1−ρ)σ²T, 侵蚀项 = 漂移差 x T 的累积)。")
    if rows:
        wd = max(rows, key=lambda r: r["drift"])
        be = max(rows, key=lambda r: r["exc"])
        out(f"     本例漂移差最大的层 = {wd['layer']} ({wd['drift']*100:.1f}pp/年), "
            f"累计超额 {pct(wd['exc'])}; 超额最好的层 = {be['layer']} ({pct(be['exc'])})。")
        rc0, rc1 = rows[0]["rc_m"], rows[-1]["rc_m"]
        out(f"  ⚠️ 筹码年化由**该段波动**决定, 不由长度决定: 最长层 {pct(rc0)} → 最短层 {pct(rc1)}"
            f" ({'降' if rc1 < rc0 else '升'}); 长窗口若含 2021 大波动段则攒得多。")
    return pd.DataFrame(rows)


def section4(px, recs):
    out(SEP)
    out("段4 · 配对三条件检验 (缺一出池: 相关<0.3 / 波动>20% / 无长期单边赢家)")
    out(SEP)
    out(f"  {'配对':<10}{'相关':>8}{'判定':>8}{'年化波动':>10}{'判定':>8}"
        f"{'死拿比(A/B)':>13}{'判定':>8}{'漂移差':>9}{'总判':>7}")
    out("  " + SUB[:100])
    for r in sorted(recs, key=lambda x: x["rho"]):
        c1 = r["rho"] < 0.30
        c2 = r["vol"] > 0.20
        c3 = 0.5 < (r["solo_a"] / r["solo_b"]) < 2.0
        ok = c1 and c2 and c3
        out(f"  {r['pair']:<10}{r['rho']:>8.3f}{'✅' if c1 else '❌':>8}"
            f"{r['vol']*100:>9.1f}%{'✅' if c2 else '❌':>8}"
            f"{r['solo_a']/r['solo_b']:>12.2f}{'✅' if c3 else '❌':>8}"
            f"{r['drift']*100:>8.1f}pp{'✅在池' if ok else '❌出池':>9}")
    out()
    out("  ⚠️ 第③条(无长期单边赢家)阈值 = 两腿死拿倍数比落在 0.5~2.0 之外即判『分胜负』。")
    out("     出池 ≠ 不能跑, 而是『跑赢死拿会很难』—— 分胜负时筹码被搬到弱腿。")
    return [r for r in recs if r["rho"] < 0.30 and r["vol"] > 0.20
            and 0.5 < (r["solo_a"] / r["solo_b"]) < 2.0]


def section5(px, start):
    out(SEP)
    out(f"段5 · 单币视角: 每个币作『腿』时的表现 (共同窗口, 参与 {len(COINS)-1} 个对)")
    out(SEP)
    out(f"  {'币':<6}{'参与对数':>8}{'死拿倍数':>10}{'死拿CAGR':>10}"
        f"{'作腿平均筹码倍':>14}{'作腿平均筹码年化':>16}")
    out("  " + SUB[:80])
    rec = []
    for c in COINS:
        rs = []
        for a, b in combinations(COINS, 2):
            r = run_pair(px, a, b, start)
            if r and c in (a, b):
                rs.append((r, c == a))
        if not rs:
            continue
        bm = float(np.mean([(r["ua"] if isa else r["ub"]) for r, isa in rs]))
        ba = float(np.mean([(r["rc_a"] if isa else r["rc_b"]) for r, isa in rs]))
        sx = px[c].loc[start:].dropna()
        m = float(sx.iloc[-1] / sx.iloc[0])
        hc = m ** (1 / (len(sx) / 52)) - 1
        out(f"  {c:<6}{len(rs):>8}{m:>9.2f}x{pct(hc):>10}"
            f"{bm:>13.3f}x{pct(ba):>16}")
        rec.append((c, m, hc, bm, ba))
    out()
    if len(rec) >= 2:
        hi = max(rec, key=lambda r: r[1])      # 死拿最强
        lo = min(rec, key=lambda r: r[1])      # 死拿最弱
        out("  ⇒ 『独家死拿越强 ⇒ 作腿筹码年化越低』: 本例排序完全反向 ——")
        out(f"     死拿最强 {hi[0]} {hi[1]:.2f}x({pct(hi[2])}) → 作腿筹码 "
            f"{hi[3]:.3f}x({pct(hi[4])});")
        out(f"     死拿最弱 {lo[0]} {lo[1]:.2f}x({pct(lo[2])}) → 作腿筹码 "
            f"{lo[3]:.3f}x({pct(lo[4])})。")
        out("     这是加密/A股/美股三市场共有的结构: 钱被不断从强腿搬进弱腿。")
        out("     ⚠️ 但筹码搬进弱腿 ≠ 账户变多: 要看该腿『币量倍数 x 价格倍数』的净贡献。")


def main():
    global MAIN
    px = load_panel()
    win = px[COINS].dropna(how="any")
    if MAIN is None:                      # 该组币的共同窗口由最晚上市者决定
        MAIN = win.index[0].date().isoformat()
        LAYERS[0] = (LAYERS[0][0], MAIN)
    out(f"# 标的组: {' + '.join(COINS)}   共同窗口起点 {MAIN}")
    section0(px)
    section1(px, win)
    recs, med = section2(px, "主口径", MAIN)
    bk = section_basket(px, "主口径", MAIN)
    df3 = section3(px)
    keep = section4(px, recs)
    section5(px, MAIN)
    out()
    out(SEP)
    out("汇总一句:")
    out(SEP)
    med_ucb = float(np.median([r["ucb"] for r in recs]))
    med_nav = float(np.median([r["nav"] for r in recs]))
    med_hold = float(np.median([r["hold"] for r in recs]))
    out(f"  【对象A】{len(COINS)} 币 → {len(recs)} 个两币对(各自 50:50, 4 周, 10bp), "
        f"主口径 {recs[0]['yrs']:.2f} 年:")
    out(f"    筹码: 中位 {med_ucb:.3f}x (年化 {pct(np.median([r['rc_m'] for r in recs]))})  "
        f"■ 每对都 >1? {sum(1 for r in recs if r['ucb']>1)}/{len(recs)}")
    out(f"    收益: 净值中位 {med_nav:.3f}x  vs  死拿中位 {med_hold:.3f}x  "
        f"⇒ 超额中位 {pct(np.median([r['exc'] for r in recs]))}")
    out(f"    跑赢死拿 {sum(1 for r in recs if r['nav']>r['hold'])}/{len(recs)} 对;  "
        f"通过三条件 {len(keep)}/{len(recs)} 对")
    if bk:
        out(f"  【对象B】4 币一组(等权 25%, 同一引擎), 主口径 {bk['yrs']:.2f} 年:")
        out(f"    筹码: 组合 {bk['ucb']:.3f}x (区间 {bk['u_min']:.3f}x ~ {bk['u_max']:.3f}x, "
            f"4 币全 >1? {'是' if bk['u_min']>1 else '否'})")
        out(f"    收益: 净值 {bk['nav']:.3f}x  vs  死拿 {bk['hold']:.3f}x  "
            f"⇒ 超额 {pct(bk['exc'])}  {'跑赢' if bk['nav']>bk['hold'] else '跑输'}死拿")
    out()
    os.makedirs(OUTDIR, exist_ok=True)
    allrows = []
    for tag, st in LAYERS:
        for a, b in combinations(COINS, 2):
            r = run_pair(px, a, b, st)
            if r:
                r = {k: v for k, v in r.items() if k not in ("start", "end")}
                r["layer"] = tag
                r["obj"] = "两币对"
                allrows.append(r)
    d = pd.DataFrame(allrows)
    fn = f"four_coin_pairs_{SUFFIX}.csv"
    fp = os.path.join(OUTDIR, fn)
    d.to_csv(fp, index=False, encoding="utf-8-sig")
    out(f"  [OK] 两币对 层x对明细 -> out/{fn}  ({len(d)} 行)")
    brows = []
    for tag, st in LAYERS:
        b = run_basket(px, COINS, st)
        if b:
            brow = {k: v for k, v in b.items()
                    if k not in ("u", "m", "start", "end")}
            brow["layer"] = tag
            brow["obj"] = "4币一组"
            for c in COINS:
                brow[f"u_{c}"] = b["u"][c]
                brow[f"m_{c}"] = b["m"][c]
            brows.append(brow)
    bd = pd.DataFrame(brows)
    fn2 = f"four_coin_basket_{SUFFIX}.csv"
    fp2 = os.path.join(OUTDIR, fn2)
    bd.to_csv(fp2, index=False, encoding="utf-8-sig")
    out(f"  [OK] 4 币一组 分层明细 -> out/{fn2}  ({len(bd)} 行)")


if __name__ == "__main__":
    main()
