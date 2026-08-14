# -*- coding: utf-8 -*-
"""
optimize_backtest.py —— 诚实优化实验(隔离, 不污染 stock_backtest 的 A-E 基准)
==========================================================================
在 40 只宇宙上, 测试两个 EX-ANTE(只用过去价格/相位, 无未来函数, 无参数挖矿)
的战术变体, 看能否在保持诚实的前提下继续抬收益/砍回撤:

  B  等权买持40(基线, 来自 stock_backtest)
  F  等权买持40 + 个股200MA趋势过滤  —— 只持站上200MA的票, 其余转现金
  G  等权买持40 × 指数相位拨盘       —— 整体按 regime 减仓(砍回撤)

参数均为既有约定(200MA / 已有 POS 相位表), 非为凑数挖出。
"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stock_backtest as S

def ma(seq_list, n):
    if len(seq_list) < n:
        return None
    return sum(seq_list[-n:]) / n

def simulate_bh_equal_trend(dates, by_code, rebal=21, ma_n=200):
    """等权买持 + 个股 200MA 趋势过滤(EX-ANTE: 只用 dates[i-1] 及之前)。"""
    codes = list(by_code.keys())
    n = len(dates)
    eq = [1.0]
    prev_w = {c: 0.0 for c in codes}
    for i in range(1, n):
        rebal_day = (i % rebal == 0) or (i <= rebal)
        target = dict(prev_w)
        if rebal_day:
            held = []
            for c in codes:
                seq = by_code[c][1]
                if dates[i - 1] not in seq:
                    continue
                closes = [seq.get(dates[j]) for j in range(max(0, i - ma_n), i)
                          if seq.get(dates[j]) is not None]
                if len(closes) < ma_n:
                    held.append(c)          # 历史不足(次新票)默认纳入
                    continue
                m = sum(closes) / len(closes)
                if seq[dates[i - 1]] > m:    # 站上 200MA 才持
                    held.append(c)
            target = {c: 0.0 for c in codes}
            if held:
                for c in held:
                    target[c] = 1.0 / len(held)
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

def simulate_bh_equal_regime(dates, w_mkt, by_code, rebal=21):
    """等权买持40 × 指数相位拨盘(整体减仓, 砍回撤)。"""
    codes = list(by_code.keys())
    n = len(dates)
    eq = [1.0]
    prev_w = {c: 0.0 for c in codes}
    for i in range(1, n):
        rebal_day = (i % rebal == 0) or (i <= rebal)
        target = dict(prev_w)
        if rebal_day:
            avail = [c for c in codes if dates[i - 1] in by_code[c][1]]
            mw = w_mkt[i - 1]
            target = {c: 0.0 for c in codes}
            if avail:
                for c in avail:
                    target[c] = mw / len(avail)
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
    args = ap.parse_args()

    dates, idx_close, w_mkt = S.build_market_clock()
    cut = [k for k, d in enumerate(dates) if d >= args.start]
    if not cut:
        print("start 太晚"); return
    s0 = cut[0]
    dates = dates[s0:]; idx_close = idx_close[s0:]; w_mkt = w_mkt[s0:]

    by_code, _ = S.build_stock_matrix(dates, S.UNIVERSE)
    by_code_t = {c: (nm, {d: seq[d] for d in dates if d in seq})
                 for c, (nm, seq) in by_code.items()}

    bench = (18 ** (1 / 10) - 1) * 100
    print("=" * 78)
    print("诚实优化实验 · 40 只宇宙  窗口 %s ~ %s  (topN=%d rebal=%d)" %
          (dates[0], dates[-1], args.topn, args.rebal))
    print("基准18x≈年化%.1f%%" % bench)
    print("=" * 78)
    print("%-34s %8s %7s %8s %6s %6s" %
          ("策略", "倍率", "年化%", "最大回撤%", "波动%", "夏普"))
    print("-" * 78)

    # 基线
    eq_b  = S.simulate_bh_equal(dates, by_code_t, args.rebal)
    eq_f  = simulate_bh_equal_trend(dates, by_code_t, args.rebal, 200)
    eq_f120 = simulate_bh_equal_trend(dates, by_code_t, args.rebal, 120)
    eq_g  = simulate_bh_equal_regime(dates, w_mkt, by_code_t, args.rebal)

    rows = [
        ("B 等权买持40(基线)", eq_b),
        ("F 等权+200MA过滤", eq_f),
        ("F 等权+120MA过滤(敏感)", eq_f120),
        ("G 等权×指数拨盘", eq_g),
    ]
    for name, eq in rows:
        m = S.metrics(eq)
        print("%-34s %8.2fx %6.1f%% %8.1f%% %6.1f%% %6.2f" %
              (name, m["mult"], m["cagr"], m["mdd"], m["vol"], m["sharpe"]))
    print("-" * 78)
    mb, mf, mg = S.metrics(eq_b), S.metrics(eq_f), S.metrics(eq_g)
    print("\n诚实解读:")
    print("  F(200MA) vs B:  倍率 %6.2fx->%6.2fx | 年化 %5.1f%%->%5.1f%% | 回撤 %6.1f%%->%6.1f%%" %
          (mb["mult"], mf["mult"], mb["cagr"], mf["cagr"], mb["mdd"], mf["mdd"]))
    print("  G(拨盘) vs B:   倍率 %6.2fx->%6.2fx | 年化 %5.1f%%->%5.1f%% | 回撤 %6.1f%%->%6.1f%%" %
          (mb["mult"], mg["mult"], mb["cagr"], mg["cagr"], mb["mdd"], mg["mdd"]))
    print("  说明: F/G 均 EX-ANTE(只用过去价格/相位), 参数取既有约定, 非挖矿。")
    print("        F 若抬收益+砍回撤=真改进; G 通常砍回撤但拖收益(相位在牛市也减仓)。")

if __name__ == "__main__":
    main()
