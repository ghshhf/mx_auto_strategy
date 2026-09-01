# -*- coding: utf-8 -*-
"""
stock_backtest_v2.py —— 个股α引擎 v2 (诚实优化扫描)
=================================================
在 v1(stock_backtest.py) 基础上:
  - 修复 build_market_clock 成交量=0 导致 regime 全"数据不足"的 bug(已在 v1 修)。
  - 把"相位拨盘"做成可调 aggressiveness 的单参数族(保护下行不对称):
      主升满仓; 中间态(震荡/退潮/筑底/赶顶)随 aggr 抬仓; 主跌仍压低。
  - RS 周期化(60/120/250)以缓解世俗熊里的动量崩溃。
  - 可选 regime-gated: 仅主升/筑底做 RS 轮动, 其余现金。
  - 网格扫描, 输出 D 族风险-收益前沿, 诚实标注 in-sample。

诚实约束: 不为了逼近 18x(34%年化) 而过拟合; 只展示"拨盘松紧"的取舍前沿,
真实价值在控回撤而非造倍数。
"""
import os, sys, json, math, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data_store as ds
import analog_core as ac
import stock_backtest as S   # 复用 load_pairs/ma/metrics/矩阵/基准策略

BASE = os.path.dirname(os.path.abspath(__file__))

def load_idx():
    idx = ds.load_bars("sh000001")
    bars = [{"d": b["d"], "c": float(b["c"]), "v": float(b.get("v") or 0)} for b in idx]
    feats = ac.build_features(bars)
    labels = [ac.regime_at(bars, feats, i)[0] for i in range(len(bars))]
    dates = [b["d"] for b in bars]
    return dates, bars, feats, labels

def make_pos(aggr):
    """aggr∈[0,1]: 0=原保守表, 1=全市场暴露(失去防御)。保护下行不对称。"""
    return {
        "主升浪": 1.00,
        "赶顶/收割期": 0.40 + 0.40 * aggr,   # 0.4 -> 0.8
        "筑底":       0.50 + 0.30 * aggr,    # 0.5 -> 0.8
        "震荡":       0.10 + 0.50 * aggr,    # 0.1 -> 0.6
        "退潮期":     0.10 + 0.30 * aggr,    # 0.1 -> 0.4 (仍偏防御)
        "主跌浪":     0.00 + 0.20 * aggr,    # 0.0 -> 0.2 (崩盘仍压低)
        "数据不足":   0.10 + 0.40 * aggr,
    }

def simulate_v2(dates, labels, by_code, first_avail, topn=5, rebal=21,
                rs_period=120, trend_filter=True, pos=None, gate=False):
    pos = pos or S.POS
    codes = list(by_code.keys())
    n = len(dates)
    eq = [1.0]
    prev_w = {c: 0.0 for c in codes}
    for i in range(1, n):
        rebal_day = (i % rebal == 0) or (i <= rebal)
        target = dict(prev_w)
        if rebal_day:
            label = labels[i - 1]
            mw = pos.get(label, 0.10)
            target = {c: 0.0 for c in codes}
            if not (gate and label not in ("主升浪", "筑底")):
                cands = []
                for c in codes:
                    seq = by_code[c][1]
                    if dates[i - 1] not in seq:
                        continue
                    lo = max(0, i - rs_period)
                    hist = [seq.get(dates[j]) for j in range(lo, i)
                            if seq.get(dates[j]) is not None]
                    if len(hist) < rs_period:
                        continue
                    c0, c1 = hist[0], hist[-1]
                    if c0 <= 0:
                        continue
                    rs = c1 / c0 - 1
                    # 趋势过滤: 站上 MA250
                    ma250 = S.ma([seq.get(dates[j]) for j in range(max(0, i - 250), i)
                                  if seq.get(dates[j]) is not None],
                                 len([x for x in [seq.get(dates[j]) for j in
                                  range(max(0, i - 250), i)] if x is not None]) - 1, 250) \
                        if (i >= 250) else None
                    above = (ma250 is None) or (c1 > ma250)
                    if trend_filter and not above:
                        continue
                    if rs <= 0:
                        continue
                    cands.append((c, rs))
                cands.sort(key=lambda x: -x[1])
                top = cands[:topn]
                if top and mw > 0:
                    for c, _ in top:
                        target[c] = mw / len(top)
        day_ret = 0.0
        for c in codes:
            w = prev_w[c]
            if w == 0:
                continue
            seq = by_code[c][1]
            c0 = seq.get(dates[i - 1]); c1 = seq.get(dates[i])
            if c0 and c1 and c0 > 0:
                day_ret += w * (c1 / c0 - 1)
        cost = 0.0
        if rebal_day:
            for c in codes:
                cost += S.COST * abs(target.get(c, 0) - prev_w[c])
        eq.append(eq[-1] * (1 + day_ret - cost))
        prev_w = {c: target.get(c, 0.0) for c in codes}
    return eq

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--topn", type=int, default=5)
    ap.add_argument("--rebal", type=int, default=21)
    ap.add_argument("--grid", action="store_true", help="跑 aggr×rs_period×gate 扫描")
    args = ap.parse_args()

    dates_all, bars_all, feats_all, labels_all = load_idx()
    by_code, first_avail = S.build_stock_matrix(dates_all)

    cut = [k for k, d in enumerate(dates_all) if d >= args.start]
    if not cut:
        print("start 太晚"); return
    s0 = cut[0]
    dates = dates_all[s0:]
    labels = labels_all[s0:]
    by_code_t = {c: (nm, {d: sq[d] for d in dates if d in sq})
                 for c, (nm, sq) in by_code.items()}

    # 基准
    idx_pairs = [(b["d"], b["c"]) for b in bars_all]
    idx_close = [c for _, c in idx_pairs if _ in set(dates)]
    # 对齐: 用 dates 顺序取
    idx_map = {d: c for d, c in idx_pairs}
    idx_close = [idx_map[d] for d in dates]
    eq_a = S.simulate_bh_index(dates, idx_close)
    eq_b = S.simulate_bh_equal(dates, by_code_t, args.rebal)
    eq_c = S.simulate_rs_nogate(dates, by_code_t, args.topn, args.rebal)
    eq_e, best_c = S.best_single(dates, by_code_t)

    print("=" * 86)
    print("个股α引擎 v2  窗口 %s~%s  宇宙 %d 只 topN=%d 调仓=%d日" %
          (dates[0], dates[-1], len(by_code_t), args.topn, args.rebal))
    print("=" * 86)
    print("\n--- 基准(不变) ---")
    for name, eq in [("A 买入持有指数", eq_a), ("B 等权买持20", eq_b),
                     ("C RS轮动满仓", eq_c),
                     ("E 事后最佳单只", eq_e)]:
        m = S.metrics(eq)
        tag = ("  <<%s" % best_c[1]) if name.startswith("E") else ""
        print("  %-22s %7.2fx %6.1f%% %8.1f%% %6.1f%% %6.2f%s" %
              (name, m["mult"], m["cagr"], m["mdd"], m["vol"], m["sharpe"], tag))

    if args.grid:
        print("\n--- D 族扫描 (aggr × rs_period × gate) ---")
        print("%-5s %-4s %-5s %8s %7s %8s %6s %6s %6s" %
              ("aggr", "rsP", "gate", "倍率", "年化%", "最大回撤%", "波动%", "夏普", "均仓"))
        print("-" * 86)
        rows = []
        for aggr in [0.0, 0.25, 0.5, 0.75, 1.0]:
            for rsp in [60, 120, 250]:
                for gate in [False, True]:
                    pos = make_pos(aggr)
                    eq = simulate_v2(dates, labels, by_code_t, first_avail,
                                     args.topn, args.rebal, rsp, True, pos, gate)
                    m = S.metrics(eq)
                    avgpos = sum(pos.get(l, 0.1) for l in labels) / len(labels)
                    rows.append((aggr, rsp, gate, m))
                    print("%-5.2f %-4d %-5s %8.2fx %6.1f%% %8.1f%% %6.1f%% %6.2f %6.2f" %
                          (aggr, rsp, "Y" if gate else "N", m["mult"], m["cagr"],
                           m["mdd"], m["vol"], m["sharpe"], avgpos))
        # 推荐: 在 MDD<=30% 约束下取夏普最高
        ok = [r for r in rows if r[3]["mdd"] <= 30]
        best = max(ok, key=lambda r: r[3]["sharpe"]) if ok else max(rows, key=lambda r: r[3]["sharpe"])
        print("\n>> 推荐(约束 MDD<=30%% 取最高夏普): aggr=%.2f rsP=%d gate=%s" %
              (best[0], best[1], "Y" if best[2] else "N"))
        m = best[3]
        print("   %7.2fx %6.1f%% %8.1f%% %6.1f%% %6.2f" %
              (m["mult"], m["cagr"], m["mdd"], m["vol"], m["sharpe"]))
        print("   说明: in-sample 单窗口调参, 真实价值需样本外验证; 非逼近18x。")
    else:
        # 默认: 一个平衡档 aggr=0.5, rsP=120, 不gate
        pos = make_pos(0.5)
        eq = simulate_v2(dates, labels, by_code_t, first_avail, args.topn,
                         args.rebal, 120, True, pos, False)
        m = S.metrics(eq)
        print("\n--- D 默认平衡档 (aggr=0.5, rsP=120, 不gate) ---")
        print("  %-22s %7.2fx %6.1f%% %8.1f%% %6.1f%% %6.2f" %
              ("D 系统(平衡)", m["mult"], m["cagr"], m["mdd"], m["vol"], m["sharpe"]))

if __name__ == "__main__":
    main()
