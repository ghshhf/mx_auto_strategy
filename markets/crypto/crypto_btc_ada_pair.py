# -*- coding: utf-8 -*-
"""BTC + ADA 双币配对再平衡 — 加密内部配对(不跨资产), 回答两个问题:
   ① 收益多少 (美元口径: 组合净值赚几倍 / CAGR / MDD)
   ② 整体囤了多少币 (筹码口径: 每币币量 vs 死拿 = 1.0)

框架依据:
  - 跨资产含加密 = 灾难(量级差), 加密必须内部配对 → 本脚本是"配对"的最小切片。
  - 口径铁律: 问"赚几倍"用美元 nav = Σ w_c · R_c · Pnorm_c; 币量倍数 ≠ 收益倍数。
  - 再平衡目的 = 筹码不掉队 (币量/基准 >= 1.0), 非收益最大化。

数据: data/weekly_adjclose_crypto50_10y.csv (周频, 后复权 hfq)
窗口: 自然公共窗口 = ADA 上市日 → 面板末日
"""
import os
import importlib.util

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("sam", os.path.join(HERE, "crypto_rebalance_sampler.py"))
sam = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sam)

REBAL_WEEKS = 4          # 月度再平衡
COST_BP = 10.0           # 加密现货单边费率 10bp (taker 量级)


def sim(px, coins, rebal_weeks=REBAL_WEEKS, cost_bp=0.0, start=None, end=None):
    """等权月度再平衡。返回 dict: nav序列/每币币量倍数/换手/统计。"""
    sub = px[list(coins)].dropna(how="any")
    if start is not None:
        sub = sub[sub.index >= start]
    if end is not None:
        sub = sub[sub.index <= end]
    if len(sub) < rebal_weeks * 2:
        return None
    pr = sub.values.astype(float)
    T, n = pr.shape
    Pnorm = pr / pr[0]
    w = np.ones(n) / n
    c = cost_bp / 1e4

    units = w / pr[0]                    # 初始: 1 美元按等权买入
    U0 = units.copy()
    NAV = np.empty(T)
    R_hist = np.empty((T, n))
    NAV[0] = 1.0
    R_hist[0] = 1.0
    # units 只在再平衡点更新 → 逐段盯市; 成本按成交额扣(缩减总仓位)
    turns = []
    seg_start = 0
    for k in list(range(rebal_weeks, T, rebal_weeks)) + [T]:
        for t in range(seg_start, min(k, T)):
            NAV[t] = float((units * pr[t]).sum())
            R_hist[t] = units / U0
        if k < T:
            val = units * pr[k]
            tot = val.sum()
            tgt = tot * w / pr[k]                    # 目标份额
            traded = float(np.abs(tgt - units).dot(pr[k]))   # 该次总成交额
            fee = traded * c
            scale = (tot - fee) / tot if tot > 0 else 1.0    # 扣费后同比例缩减
            units = tgt * scale
            turns.append(traded / tot)               # 换手率(占组合价值)
            seg_start = k

    R = units / U0                        # 期末币量 / 死拿币量
    yrs = (sub.index[-1] - sub.index[0]).days / 365.25
    nav_ser = pd.Series(NAV, index=sub.index)
    units_ser = pd.DataFrame(R_hist, index=sub.index, columns=list(coins))
    ret = nav_ser.pct_change().dropna()
    cagr = nav_ser.iloc[-1] ** (1 / yrs) - 1
    vol = ret.std() * np.sqrt(52)
    dd = (nav_ser / nav_ser.cummax() - 1)
    mdd = dd.min()
    # 死拿(不再平衡)对照
    hold = pd.Series((w * Pnorm).sum(axis=1), index=sub.index)
    return {
        "coins": list(coins), "yrs": yrs,
        "start": sub.index[0], "end": sub.index[-1],
        "nav": float(nav_ser.iloc[-1]), "cagr": float(cagr), "vol": float(vol),
        "mdd": float(mdd), "calmar": float(cagr / abs(mdd)) if mdd < 0 else np.nan,
        "nav_ser": nav_ser, "units_ser": units_ser,
        "hold_ser": hold,
        "hold_nav": float(hold.iloc[-1]), "hold_cagr": float(hold.iloc[-1] ** (1 / yrs) - 1),
        "hold_mdd": float((hold / hold.cummax() - 1).min()),
        "units_mult": {c: float(R[i]) for i, c in enumerate(coins)},
        "turnover_ann": float(np.sum(turns) / yrs) if turns else 0.0,
        "turnover_events": len(turns),
        "px_first": {c: float(pr[0][i]) for i, c in enumerate(coins)},
        "px_last": {c: float(pr[-1][i]) for i, c in enumerate(coins)},
    }


def buyhold(px, coins, start=None, end=None):
    sub = px[list(coins)].dropna(how="any")
    if start is not None:
        sub = sub[sub.index >= start]
    if end is not None:
        sub = sub[sub.index <= end]
    pr = sub.values.astype(float)
    Pnorm = pr / pr[0]
    w = np.ones(len(coins)) / len(coins)
    ser = pd.Series((w * Pnorm).sum(axis=1), index=sub.index)
    yrs = (sub.index[-1] - sub.index[0]).days / 365.25
    dd = (ser / ser.cummax() - 1).min()
    return {"nav": float(ser.iloc[-1]), "cagr": float(ser.iloc[-1] ** (1 / yrs) - 1),
            "mdd": float(dd), "yrs": yrs,
            "calmar": float((ser.iloc[-1] ** (1 / yrs) - 1) / abs(dd)) if dd < 0 else np.nan,
            "ser": ser}


def solo(px, coin, start=None, end=None):
    return buyhold(px, [coin], start, end)


def line(tag, s):
    if s is None:
        print(f"  {tag:34s} 数据不足")
        return
    print(f"  {tag:34s} {s['nav']:9.3f}x  CAGR {s['cagr']*100:+7.2f}%  "
          f"MDD {s['mdd']*100:+7.2f}%  Calmar {s['calmar']:5.2f}  ({s['yrs']:.1f}y)")


def chip_line(tag, s):
    if s is None:
        print(f"  {tag:34s} 数据不足")
        return
    u = s["units_mult"]
    txt = "  ".join(f"{c} {v:7.3f}x" for c, v in u.items())
    yrs = s["yrs"]
    rates = "  ".join(f"{c} {(v**(1/yrs)-1)*100:+7.2f}%/y" for c, v in u.items())
    print(f"  {tag:34s} {txt}   |  {rates}")


def block(title, px, coin_a, coin_b, windows):
    print(f"\n{'=' * 92}")
    print(f"### {title}   币={coin_a}+{coin_b}")
    print("=" * 92)
    for wtag, (s0, s1) in windows:
        print(f"\n-- {wtag}  ({s0 or '自然'} ~ {s1 or '最新'})")
        base = sim(px, [coin_a, coin_b], start=s0, end=s1, cost_bp=0.0)
        if base is None:
            print("  数据不足")
            continue
        st, en = base["start"], base["end"]
        print(f"  窗口: {st.date()} ~ {en.date()}   ({base['yrs']:.2f}y)")
        print("  [美元口径 — 赚几倍]")
        line(f"{coin_a}+{coin_b} 等权月再平衡 (0成本)", base)
        for cbp in (10.0, 30.0):
            line(f"{coin_a}+{coin_b} 等权月再平衡 ({cbp:.0f}bp单边)", sim(px, [coin_a, coin_b], start=s0, end=s1, cost_bp=cbp))
        line(f"{coin_a}+{coin_b} 等权死拿(不再平衡)", buyhold(px, [coin_a, coin_b], st, en))
        line(f"{coin_a} 独家死拿", solo(px, coin_a, st, en))
        line(f"{coin_b} 独家死拿", solo(px, coin_b, st, en))
        print(f"  年化换手(0成本口径): {base['turnover_ann']*100:.1f}% /年   调仓 {base['turnover_events']} 次")
        print("  [筹码口径 — 囤了多少币, 死拿该组合=1.000]")
        chip_line(f"{coin_a}+{coin_b} 等权月再平衡 (0成本)", base)
        for cbp in (10.0, 30.0):
            chip_line(f"{coin_a}+{coin_b} 等权月再平衡 ({cbp:.0f}bp)", sim(px, [coin_a, coin_b], start=s0, end=s1, cost_bp=cbp))
        pa, pb = base["px_last"][coin_a], base["px_last"][coin_b]
        print(f"  期末组合 {base['nav']:.3f} 美元/初始1美元 → 折合 {base['nav']/pa:.8f} {coin_a}  或 {base['nav']/pb:.3f} {coin_b}")
        ua = base["units_mult"][coin_a]
        verdict = "掉队" if ua < 1.0 else "增持"
        print(f"  {coin_a} 币量 = 死拿该组合的 {ua:.4f}x / 「全仓 {coin_a} 死拿」的 {ua * 0.5:.4f}x   → {verdict}")
        print(f"  [再平衡超额] 净值比 = {base['nav'] / base['hold_nav']:.4f}   "
              f"({(base['nav'] / base['hold_nav'] - 1) * 100:+.2f}% 相对死拿; "
              f"扣 10bp 后 {(sim(px, [coin_a, coin_b], start=s0, end=s1, cost_bp=10.0)['nav'] / base['hold_nav'] - 1) * 100:+.2f}%)")


def multi_pool(px, window_start):
    """固定窗口下的多币池对照(只取该窗口内(补缺后)全程有数据的币, 避免被短历史币压扁窗口)。"""
    pxf = px.ffill()
    sub = pxf.loc[window_start:]
    avail = [c for c in px.columns if not sub[c].isna().any()]
    print(f"\n{'=' * 92}")
    print(f"### C. 对照: 同一窗口({window_start}~最新, {len(sub)} 周)下加币数的效果")
    print(f"    可用老币 {len(avail)} 个: {avail}")
    print("=" * 92)
    groups = [
        ("BTC+ADA (2币)", ["BTC", "ADA"]),
        ("BTC+ETH+ADA (3币)", ["BTC", "ETH", "ADA"]),
    ]
    old = [c for c in avail if c not in ("BTC", "ETH")]
    groups.append((f"BTC+ETH+其余{len(old)}老币 ({len(old) + 2}币)", ["BTC", "ETH"] + old))
    rows = []
    for tag, cs in groups:
        cs = [c for c in cs if c in pxf.columns]
        s = sim(pxf, cs, start=window_start, cost_bp=0.0)
        h = buyhold(pxf, cs, window_start, None)
        if s is None:
            continue
        rows.append((tag, s, h))
        line(f"{tag} 等权月再平衡", s)
        line(f"{tag} 等权死拿", h)
        chip_line(f"{tag} 筹码", s)
        print(f"  → 再平衡净值/死拿净值 = {s['nav'] / h['nav']:.4f}   年化换手 {s['turnover_ann']*100:.0f}%\n")
    return rows


def pair_scan(px, coins, start):
    """同窗口下全部双币配对横向对照, 并按"再平衡超额"排序。
    输出超额 vs (组合波动、相关系数、两币长期漂移差) 的对照, 用于检验
    "波动都大 → 收割更多" 这一直觉是否成立。
    """
    from itertools import combinations
    print(f"\n{'=' * 100}")
    print(f"### E. 全部双币配对横向对照 (同窗口 {start} 起, 月度等权再平衡)")
    print(f"    候选币 {len(coins)} 个 → C({len(coins)},2)={len(list(combinations(coins, 2)))} 组")
    print("=" * 100)
    rows = []
    for a, b in combinations(coins, 2):
        r0 = sim(px, [a, b], start=start, cost_bp=0.0)
        r10 = sim(px, [a, b], start=start, cost_bp=10.0)
        if r0 is None or len(r0["nav_ser"]) < 60:
            continue
        h = buyhold(px, [a, b], r0["start"], r0["end"])
        sa = solo(px, a, r0["start"], r0["end"])
        sb = solo(px, b, r0["start"], r0["end"])
        rr = px.loc[r0["start"]:r0["end"], [a, b]].pct_change().dropna()
        w = np.array([0.5, 0.5])
        C = rr.cov().values * 52
        pvol = float(np.sqrt(w @ C @ w))          # 等权组合年化波动
        rows.append({
            "pair": f"{a}+{b}", "nav": r10["nav"], "cagr": r10["cagr"], "mdd": r0["mdd"],
            "hold": h["nav"], "ex": r10["nav"] / h["nav"] - 1,
            "turn": r0["turnover_ann"], "corr": float(rr[a].corr(rr[b])),
            "vol": pvol, "drift": sa["cagr"] - sb["cagr"],
            "ca": sa["cagr"], "cb": sb["cagr"],
            "chip": dict(r10["units_mult"]), "yrs": r0["yrs"],
        })
    rows.sort(key=lambda x: -x["ex"])
    print(f"  {'币对':14s}{'再平衡':>10s}{'CAGR':>9s}{'MDD':>9s}{'死拿':>10s}{'超额':>9s}"
          f"{'组合波动':>9s}{'相关':>7s}{'漂移差':>9s}{'换手':>7s}   筹码(/死拿)")
    for r in rows:
        chip = "  ".join(f"{c} {v:.3f}x" for c, v in r["chip"].items())
        print(f"  {r['pair']:14s}{r['nav']:9.3f}x{r['cagr'] * 100:+8.2f}%{r['mdd'] * 100:+8.2f}%"
              f"{r['hold']:9.3f}x{r['ex'] * 100:+8.2f}%{r['vol'] * 100:8.1f}%{r['corr']:7.3f}"
              f"{r['drift'] * 100:+8.1f}pp{r['turn'] * 100:6.0f}%   {chip}")
    print()
    print("  [单变量相关] 超额 ~ 组合波动: "
          f"{np.corrcoef([r['ex'] for r in rows], [r['vol'] for r in rows])[0, 1]:+.3f}   "
          "超额 ~ |漂移差|: "
          f"{np.corrcoef([r['ex'] for r in rows], [abs(r['drift']) for r in rows])[0, 1]:+.3f}")
    # 按"两币漂移方向是否一致"分组 —— 真正的分界
    groups = {"双正(都涨)": [], "双负(都跌)": [], "一正一负": []}
    for r in rows:
        if r["ca"] > 0 and r["cb"] > 0:
            groups["双正(都涨)"].append(r)
        elif r["ca"] <= 0 and r["cb"] <= 0:
            groups["双负(都跌)"].append(r)
        else:
            groups["一正一负"].append(r)
    print("\n  [分组统计] 按两币 8.4 年独立死拿 CAGR 的符号分组:")
    for g, sub in groups.items():
        if not sub:
            continue
        exs = [x["ex"] for x in sub]
        print(f"    {g:10s} n={len(sub):2d}  平均超额 {np.mean(exs) * 100:+7.2f}%  "
              f"中位 {np.median(exs) * 100:+7.2f}%  区间 [{min(exs) * 100:+.2f}%, {max(exs) * 100:+.2f}%]"
              f"   平均组合波动 {np.mean([x['vol'] for x in sub]) * 100:.1f}%")
    return rows


def main():
    px = sam.load()
    print(f"面板: {px.index[0].date()} ~ {px.index[-1].date()}  {px.shape[1]} 币")
    # 自然公共窗口
    fd = sam.first_dates(px)
    nat0 = max(fd["BTC"], fd["ADA"])
    end = px.index[-1]
    print(f"BTC 起 {fd['BTC'].date()} / ADA 起 {fd['ADA'].date()} → 公共窗口起点 {nat0.date()}  ({(end-nat0).days/365.25:.2f}y)")

    windows = [
        ("全窗口", (None, None)),
        ("段1 · 2018-04~2020-05 (熊/吸筹)", (None, "2020-05-11")),
        ("段2 · 2020-05~2024-04 (上轮周期)", ("2020-05-11", "2024-04-19")),
        ("段3 · 2024-04~2026-09 (本轮)", ("2024-04-19", None)),
    ]
    block("A. 比特币 + ADA 双币配对", px, "BTC", "ADA", windows)
    block("A2. 以太坊 + ADA 双币配对 (两币波动都大)", px, "ETH", "ADA", windows)

    print(f"\n{'=' * 92}")
    print("### B. 三组主力配对速览 (同窗口, 扣 10bp)")
    print("=" * 92)
    for a, b in (("BTC", "ETH"), ("BTC", "ADA"), ("ETH", "ADA")):
        r10 = sim(px, [a, b], start=nat0, cost_bp=10.0)
        h = buyhold(px, [a, b], nat0, None)
        line(f"{a}+{b} 等权月再平衡 (10bp)", r10)
        line(f"{a}+{b} 等权死拿", h)
        chip_line(f"{a}+{b} 筹码", r10)
        print(f"  再平衡净值 / 死拿净值 = {r10['nav'] / h['nav']:.4f}   "
              f"换手 {r10['turnover_ann'] * 100:.0f}%/年\n")

    multi_pool(px, str(nat0.date()))

    # 相关矩阵
    print(f"\n{'=' * 92}")
    print("### D. 相关性与波动 (配对准入检验)")
    print("=" * 92)
    sub = px.loc[nat0:, ["BTC", "ETH", "ADA", "SOL"]].dropna()
    r = sub.pct_change().dropna()
    print("  周收益相关系数:")
    print(r.corr().round(3).to_string())
    print(f"\n  年化波动: " + "  ".join(f"{c} {r[c].std()*np.sqrt(52)*100:.1f}%" for c in r.columns))

    # 全部双币配对横向对照(只用在公共窗口内全程有数据的币, 保证窗口一致)
    pxf = px.ffill()
    avail = [c for c in px.columns if not pxf.loc[nat0:, c].isna().any()]
    pair_scan(px, avail, str(nat0.date()))


if __name__ == "__main__":
    main()
