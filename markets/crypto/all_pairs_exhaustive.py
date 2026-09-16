# -*- coding: utf-8 -*-
"""全池配对穷举 — 回答用户:"咱们 27 个代币, 你只配对了几个? 全配置一遍"

问题本质: 27 币的"最大公共窗口"被 HYPE(2025-10-31 上市)压到 0.87 年, 无意义。
解法: 按上市时间分层窗口 —— 每层 = "该日已上市的币集合", 层内全组合穷举。
      层内所有币同窗口 -> 可横比; 跨层窗口不同 -> 只看分布不看单行。

两列核心(用户指定):
  ① 筹码年化 %  = 组合几何筹码倍数的几何年化   <- 主口径(纯币量, 不含价格)
  ② 收益 CAGR % = 再平衡净值年化               <- 次口径(含价格/起点价, 仅参考)

铁律: 再平衡目的 = 筹码不掉队(>=1.0), 非收益最大化。
      "组合筹码为正" 是机器产出; "单币筹码 < 1" 是掉队信号, 必须单列。

数据: data/weekly_adjclose_crypto50_10y.csv (27 币)
"""
import os
import math
import random
import importlib.util
from itertools import combinations

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("bap", os.path.join(HERE, "crypto_btc_ada_pair.py"))
bap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bap)

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
OUTDIR = os.path.join(HERE, "out")
COST_BP = 10.0
MIN_COINS = 13          # 至少 13 币可配才成层（否则窗口太长但币太少）
MAIN_START = "2020-10-09"   # 主口径：19 币 / 5.90y，覆盖完整牛熊

# 存储/资源类（用户特别提过"存储代币"）
STORAGE = ["FIL", "RENDER", "GLM"]

geo = lambda x: math.exp(x) - 1


def load_panel():
    px = pd.read_csv(PANEL, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


# ---------- 单币死拿（价格倍数）预计算：与再平衡无关，可跨组复用 ----------
def solo_table(px, coins, start):
    out = {}
    for c in coins:
        s = px[c].loc[start:].dropna()
        if len(s) < 2:
            continue
        out[c] = dict(nav=float(s.iloc[-1] / s.iloc[0]), yrs=len(s) / 52.0,
                      px0=float(s.iloc[0]), px1=float(s.iloc[-1]))
    return out


def run_pair(px, a, b, start, solo):
    r = bap.sim(px, [a, b], start=start, cost_bp=COST_BP)
    if r is None:
        return None
    ua, ub = r["units_mult"][a], r["units_mult"][b]
    ucb = math.sqrt(ua * ub)
    rca, rcb = math.log(ua) / r["yrs"], math.log(ub) / r["yrs"]
    sa, sb = solo[a], solo[b]
    win = px[[a, b]].loc[r["start"]:r["end"]].dropna()
    lr = np.log(win).diff().dropna()
    rho = float(lr[a].corr(lr[b])) if len(lr) > 3 else float("nan")
    hold = (sa["nav"] + sb["nav"]) / 2.0          # 双币等权死拿（各投 0.5）

    def _geo(v, yrs):
        """几何年化 v**(1/yrs)-1（与 r["cagr"] 同口径）。
        2026-09-16 修正: 原实现为 math.log(v)/yrs（对数年化），与同一张表的
        cagr 列（几何）不一致 —— 例如 AAVE 6.08y 的 3.0x 会写成 18.1% 而真值
        20.1%。引擎/展示层其余部分一律几何，见 memory 的 CAGR 纪律。"""
        try:
            if yrs and v and v > 0:
                return v ** (1.0 / yrs) - 1.0
        except (TypeError, ValueError, ZeroDivisionError):
            pass
        return float("nan")

    return dict(pair=f"{a}+{b}", a=a, b=b, yrs=r["yrs"], ua=ua, ub=ub, ucb=ucb,
                rcm=(rca + rcb) / 2, rca=rca, rcb=rcb,
                nav=r["nav"], hold=hold, cagr=r["cagr"], cagr_h=_geo(hold, r["yrs"]),
                cagr_a=_geo(sa["nav"], r["yrs"]),
                cagr_b=_geo(sb["nav"], r["yrs"]),
                drift=math.log(sa["nav"]) / r["yrs"] - math.log(sb["nav"]) / r["yrs"],
                solo_a=sa["nav"], solo_b=sb["nav"], rho=rho, turn=r["turnover_ann"])


def layer_defs(px):
    """按首有效日分层，每层 = 该日已上市的全部币；返回 [(start, coins, yrs)]"""
    firsts = {c: px[c].first_valid_index() for c in px.columns}
    layers, prev_n = [], 0
    for d in sorted(set(firsts.values())):
        cs = sorted(c for c, v in firsts.items() if v <= d)
        if len(cs) > prev_n:
            layers.append((d, cs))
            prev_n = len(cs)
    return [L for L in layers if len(L[1]) >= MIN_COINS]


def summarize(recs, label, out_rows):
    if not recs:
        return None
    rcm = np.array([r["rcm"] for r in recs])
    rca = np.array([r["rca"] for r in recs])
    rcb = np.array([r["rcb"] for r in recs])
    cg = np.array([r["cagr"] for r in recs])
    ch = np.array([r["cagr_h"] for r in recs])
    yrs = recs[0]["yrs"]
    s = dict(label=label, n=len(recs), yrs=yrs,
             rcm_med=geo(float(np.median(rcm))), rcm_avg=geo(float(rcm.mean())),
             rcm_lo=geo(float(rcm.min())), rcm_hi=geo(float(rcm.max())),
             rcm_pos=int((rcm > 0).sum()),
             cagr_med=float(np.median(cg)), cagr_avg=float(cg.mean()),
             hold_med=float(np.median(ch)),
             beat=int((cg > ch).sum()),
             both_pos=int(((rca > 0) & (rcb > 0)).sum()),
             any_neg=int(((rca < 0) | (rcb < 0)).sum()),
             worst_a=geo(float(rca.min())), worst_b=geo(float(rcb.min())))
    out_rows.append(s)
    print(f"  {label}  N={len(recs):4d}  窗口 {yrs:5.2f}y  "
          f"筹码年化 中位 {s['rcm_med'] * 100:+6.2f}%  平均 {s['rcm_avg'] * 100:+6.2f}%  "
          f"区间 {s['rcm_lo'] * 100:+6.2f}% ~ {s['rcm_hi'] * 100:+6.2f}%  "
          f"为正 {s['rcm_pos']}/{len(recs)}")
    return s


def main():
    px = load_panel()
    random.seed(20260913)
    print(f"面板 {os.path.basename(PANEL)}  {px.shape[1]} 币  {px.index[0].date()} ~ {px.index[-1].date()}")
    print(f"（面板日期标签比承载价格早约 9 天，对所有币一致，不影响筹码/收益序列）\n")

    layers = layer_defs(px)
    print("=" * 118)
    print("一、分层穷举（层 = 该日起已上市的币；层内同窗口可横比，跨层窗口不同只看分布）")
    print("=" * 118)
    all_recs, sum_rows = [], []
    for d, cs in layers:
        solo = solo_table(px, cs, d)
        cs = [c for c in cs if c in solo]
        recs = [x for x in (run_pair(px, a, b, d, solo) for a, b in combinations(cs, 2)) if x]
        for r in recs:
            r["layer"] = f"{d.date()}/{len(cs)}币"
        all_recs += recs
        summarize(recs, f"层 {d.date()} ({len(cs)} 币)", sum_rows)

    # ---------- 主口径 ----------
    print("\n" + "=" * 118)
    print(f"二、主口径 {MAIN_START} 起（19 币 / 5.90y，覆盖完整牛熊）— 全部 171 组")
    print("=" * 118)
    main_layer = [L for L in layers if str(L[0].date()) == MAIN_START]
    if not main_layer:
        main_layer = [max(layers, key=lambda L: len(L[1]))]
    md, mcs = main_layer[0]
    msolo = solo_table(px, mcs, md)
    mcs = [c for c in mcs if c in msolo]
    mrecs = [x for x in (run_pair(px, a, b, md, msolo) for a, b in combinations(mcs, 2)) if x]
    for r in mrecs:
        r["layer"] = f"{md.date()}/{len(mcs)}币"
    summarize(mrecs, f"主口径 {md.date()} ({len(mcs)} 币)", sum_rows)

    hdr = (f"{'#':>3s} {'配对':14s} {'筹码A':>7s} {'筹码B':>7s} {'组合':>7s} "
           f"{'筹码年化':>8s} {'再平衡净值':>10s} {'死拿净值':>9s} {'CAGR':>7s} "
           f"{'死拿CAGR':>8s} {'漂移差':>7s} {'相关':>5s}")
    order = sorted(mrecs, key=lambda r: -r["rcm"])
    print("\n  [2.1] TOP 20（筹码年化最高）")
    print("  " + hdr)
    for i, r in enumerate(order[:20], 1):
        print(f"  {i:3d} {r['pair']:14s} {r['ua']:7.4f} {r['ub']:7.4f} {r['ucb']:7.4f} "
              f"{geo(r['rcm']) * 100:+7.2f}% {r['nav']:10.3f} {r['hold']:9.3f} "
              f"{r['cagr'] * 100:+6.2f}% {r['cagr_h'] * 100:+7.2f}% "
              f"{r['drift'] * 100:+6.1f}pp {r['rho']:5.3f}")
    print("\n  [2.2] BOTTOM 15（筹码年化最低 = 最不该配）")
    print("  " + hdr)
    for i, r in enumerate(order[-15:], len(order) - 14):
        print(f"  {i:3d} {r['pair']:14s} {r['ua']:7.4f} {r['ub']:7.4f} {r['ucb']:7.4f} "
              f"{geo(r['rcm']) * 100:+7.2f}% {r['nav']:10.3f} {r['hold']:9.3f} "
              f"{r['cagr'] * 100:+6.2f}% {r['cagr_h'] * 100:+7.2f}% "
              f"{r['drift'] * 100:+6.1f}pp {r['rho']:5.3f}")

    # ---------- 逐币视角 ----------
    print("\n" + "=" * 118)
    print("三、逐币视角（主口径）— 每个币参与到其余 18 币的全部配对的统计")
    print("=" * 118)
    print(f"  {'币':7s} {'配对数':>6s} {'本币筹码年化中位':>15s} {'区间':>20s} "
          f"{'不掉队(>=1x)比例':>16s} {'独家死拿CAGR':>13s} {'组合筹码年化中位':>15s}")
    coin_rows = []
    for c in mcs:
        sub = [r for r in mrecs if c in (r["a"], r["b"])]
        own = np.array([math.log(r["ua"] if r["a"] == c else r["ub"]) / r["yrs"] for r in sub])
        comb = np.array([r["rcm"] for r in sub])
        keep = float((own > 0).mean())
        sc = geo(math.log(msolo[c]["nav"]) / msolo[c]["yrs"])   # 几何年化(勿混对数年化)
        coin_rows.append(dict(coin=c, n=len(sub), own_med=geo(float(np.median(own))),
                              own_lo=geo(float(own.min())), own_hi=geo(float(own.max())),
                              keep=keep, solo=sc, comb_med=geo(float(np.median(comb)))))
        print(f"  {c:7s} {len(sub):6d} {geo(float(np.median(own))) * 100:+14.2f}% "
              f"{geo(float(own.min())) * 100:+8.2f}% ~ {geo(float(own.max())) * 100:+7.2f}% "
              f"{keep * 100:15.1f}% {sc * 100:+12.2f}% {geo(float(np.median(comb))) * 100:+14.2f}%")
    coin_rows.sort(key=lambda r: -r["keep"])
    print("\n  → 按「不掉队比例」排序（最稳 → 最易掉队）：")
    for i, r in enumerate(coin_rows, 1):
        tag = "  ★存储/资源" if r["coin"] in STORAGE else ""
        print(f"    {i:2d}. {r['coin']:6s} 不掉队 {r['keep'] * 100:5.1f}%  "
              f"本币筹码年化中位 {r['own_med'] * 100:+7.2f}%  独家死拿 {r['solo'] * 100:+7.2f}%/年{tag}")

    # ---------- 全池篮子规模梯度 ----------
    print("\n" + "=" * 118)
    print("四、全池「都配上」—— 篮子规模梯度（主口径 19 币，每规模随机 1500 组合取中位）")
    print("=" * 118)
    print(f"  {'币数':>4s} {'组合数':>7s} {'组合筹码年化中位':>16s} {'区间P5~P95':>20s} "
          f"{'单币筹码最低中位':>16s} {'再平衡CAGR中位':>14s} {'死拿CAGR中位':>13s}")
    basket_rows = []
    for k in range(2, len(mcs) + 1):
        tot = math.comb(len(mcs), k)
        sample = (list(combinations(mcs, k)) if tot <= 1500
                  else [tuple(random.sample(mcs, k)) for _ in range(1500)])
        vals, lows, cgs, hgs = [], [], [], []
        for cs in sample:
            r = bap.sim(px, list(cs), start=md, cost_bp=COST_BP)
            if r is None:
                continue
            us = [r["units_mult"][c] for c in cs]
            # ⚠️ 必须年化（除以窗口年数），否则得到的是全窗口总倍数而非年化
            vals.append(sum(math.log(u) for u in us) / len(us) / r["yrs"])
            lows.append(min(math.log(u) for u in us) / r["yrs"])
            cgs.append(r["cagr"])
            hg = sum(msolo[c]["nav"] for c in cs) / len(cs)
            hgs.append(math.log(hg) / r["yrs"])
        if not vals:
            continue
        v = np.array(vals)
        lo, hi = np.percentile(v, [5, 95])
        basket_rows.append(dict(k=k, combos=tot, med=geo(float(np.median(v))),
                                p5=geo(float(lo)), p95=geo(float(hi)),
                                low_med=geo(float(np.median(lows))),
                                cagr_med=float(np.median(cgs)), hold_med=float(np.median(hgs))))
        print(f"  {k:4d} {tot:7d} {geo(float(np.median(v))) * 100:+15.2f}% "
              f"{geo(float(lo)) * 100:+8.2f}% ~ {geo(float(hi)) * 100:+7.2f}% "
              f"{geo(float(np.median(lows))) * 100:+15.2f}% "
              f"{float(np.median(cgs)) * 100:+13.2f}% {float(np.median(hgs)) * 100:+12.2f}%")

    # ---------- 存储/资源类专节 ----------
    print("\n" + "=" * 118)
    print("五、存储/资源类（FIL / RENDER / GLM）— 全配对明细")
    print("=" * 118)
    for s in STORAGE:
        sub = [r for r in all_recs if s in (r["a"], r["b"])]
        if not sub:
            print(f"  {s}: 无可用配对"); continue
        sub.sort(key=lambda r: -r["rcm"])
        print(f"\n  {s} 共 {len(sub)} 组（按筹码年化排序，前 8 / 后 4）")
        print("  " + hdr)
        show = sub[:8] + ([None] + sub[-4:] if len(sub) > 12 else [])
        for r in show:
            if r is None:
                print("  ..."); continue
            own = "A" if r["a"] == s else "B"
            print(f"      {r['pair']:14s} {r['ua']:7.4f} {r['ub']:7.4f} {r['ucb']:7.4f} "
                  f"{geo(r['rcm']) * 100:+7.2f}% {r['nav']:10.3f} {r['hold']:9.3f} "
                  f"{r['cagr'] * 100:+6.2f}% {r['cagr_h'] * 100:+7.2f}% "
                  f"{r['drift'] * 100:+6.1f}pp {r['rho']:5.3f}  [{r['layer']}] {s}={own}")

    # ---------- 落盘 ----------
    os.makedirs(OUTDIR, exist_ok=True)
    df = pd.DataFrame(all_recs).drop(columns=["a", "b"])
    p1 = os.path.join(OUTDIR, "all_pairs_exhaustive.csv")
    df.to_csv(p1, index=False, float_format="%.6f")
    p2 = os.path.join(OUTDIR, "all_pairs_layers.csv")
    pd.DataFrame(sum_rows).to_csv(p2, index=False, float_format="%.6f")
    p3 = os.path.join(OUTDIR, "all_pairs_coin_view.csv")
    pd.DataFrame(coin_rows).to_csv(p3, index=False, float_format="%.6f")
    p4 = os.path.join(OUTDIR, "all_pairs_basket_scale.csv")
    pd.DataFrame(basket_rows).to_csv(p4, index=False, float_format="%.6f")
    print(f"\n明细 -> {p1}")
    print(f"       {p2}")
    print(f"       {p3}")
    print(f"       {p4}")


if __name__ == "__main__":
    main()
