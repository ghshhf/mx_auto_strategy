# -*- coding: utf-8 -*-
"""
quality_backtest_exante.py —— EX-ANTE 质量选股回测(40 只, 严格无未来函数)
================================================================================
在每个调仓日, 只用"当时已对外发布的年报"(available_year_asof 铁律)的 ROE + 营收增速,
对当日在市的股票做横截面质量排名, 测试三种诚实用法:

  B   等权买持40(基线, 无质量)
  Q1  质量过滤: 仅持 roe>0 且 revg>0 的票, 等权
  Q2  质量加权: 权重 ∝ (rank(roe)+rank(revg)), 仅持有效数据票
  Q3  质量Top-K: 取质量前 K 只等权(K=10 / 15)
  Q4  纯ROE加权: 权重 ∝ rank(roe)  (看营收增速是增益还是噪声)

质量数据: fundamentals_hist.py (2014-2025 年报, EX-ANTE 边界已内置)。
"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stock_backtest as S
import fundamentals_hist as F

def rank_map(vals):
    """vals: {code: x} -> {code: rank 1..n}(升序, 越大越好, 并列取平均)。"""
    items = sorted(vals.items(), key=lambda kv: (kv[1] is None, kv[1] if kv[1] is not None else -1e9))
    n = len(items)
    r = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            r[items[k][0]] = avg
        i = j + 1
    return r

def quality_pool(codes, seq_by_code, dates, i, asof_year):
    """返回 {code: (roe, revg)} 仅含当日已上市且数据有效的票。"""
    out = {}
    for c in codes:
        seq = seq_by_code[c][1]
        if dates[i - 1] not in seq:
            continue
        roe, revg = F.get_fund(c, asof_year)
        if roe is None or revg is None:
            continue
        out[c] = (roe, revg)
    return out

def simulate_quality(dates, seq_by_code, codes, rebal, mode, K=10, w_roe=1.0, w_revg=1.0):
    n = len(dates)
    eq = [1.0]
    prev_w = {c: 0.0 for c in codes}
    for i in range(1, n):
        rebal_day = (i % rebal == 0) or (i <= rebal)
        target = dict(prev_w)
        if rebal_day:
            asof = F.available_year_asof(dates[i - 1])
            pool = quality_pool(codes, seq_by_code, dates, i, asof)
            target = {c: 0.0 for c in codes}
            if pool:
                roe_r = rank_map({c: v[0] for c, v in pool.items()})
                revg_r = rank_map({c: v[1] for c, v in pool.items()})
                comp = {c: w_roe * roe_r[c] + w_revg * revg_r[c] for c in pool}
                valid = pool  # 全部有效
                if mode == "Q1":
                    # 仅持 roe>0 且 revg>0
                    elig = [c for c in pool if pool[c][0] > 0 and pool[c][1] > 0]
                    if elig:
                        for c in elig:
                            target[c] = 1.0 / len(elig)
                elif mode == "Q2":
                    tot = sum(comp.values())
                    if tot > 0:
                        for c in pool:
                            target[c] = comp[c] / tot
                elif mode == "Q3":
                    top = sorted(comp, key=lambda c: -comp[c])[:K]
                    if top:
                        for c in top:
                            target[c] = 1.0 / len(top)
                elif mode == "Q4":
                    tot = sum(roe_r.values())
                    if tot > 0:
                        for c in pool:
                            target[c] = roe_r[c] / tot
        day_ret = 0.0
        for c in codes:
            w = prev_w[c]
            if w == 0:
                continue
            seq = seq_by_code[c][1]
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
    ap.add_argument("--rebal", type=int, default=21)
    args = ap.parse_args()
    dates, idx_close, w_mkt = S.build_market_clock()
    cut = [k for k, d in enumerate(dates) if d >= args.start]
    s0 = cut[0]
    dates = dates[s0:]; idx_close = idx_close[s0:]
    by_code, _ = S.build_stock_matrix(dates, S.UNIVERSE)
    seq_by_code = {c: (nm, {d: seq[d] for d in dates if d in seq})
                   for c, (nm, seq) in by_code.items()}
    codes = list(seq_by_code.keys())

    bench = (18 ** (1 / 10) - 1) * 100
    print("=" * 80)
    print("EX-ANTE 质量选股回测 · 40 只  窗口 %s ~ %s  (rebal=%d)" %
          (dates[0], dates[-1], args.rebal))
    print("基准18x≈年化%.1f%%  质量数据: fundamentals_hist(2014-2025年报, 严格EX-ANTE)" % bench)
    print("=" * 80)
    print("%-30s %8s %7s %8s %6s %6s" %
          ("策略", "倍率", "年化%", "最大回撤%", "波动%", "夏普"))
    print("-" * 80)

    eq_b = S.simulate_bh_equal(dates, seq_by_code, args.rebal)
    variants = [
        ("B 等权买持40(基线)", eq_b),
        ("Q1 质量过滤(roe>0&revg>0)", simulate_quality(dates, seq_by_code, codes, args.rebal, "Q1")),
        ("Q2 质量加权(roe+revg)", simulate_quality(dates, seq_by_code, codes, args.rebal, "Q2")),
        ("Q3 质量Top10等权", simulate_quality(dates, seq_by_code, codes, args.rebal, "Q3", K=10)),
        ("Q3 质量Top15等权", simulate_quality(dates, seq_by_code, codes, args.rebal, "Q3", K=15)),
        ("Q4 纯ROE加权", simulate_quality(dates, seq_by_code, codes, args.rebal, "Q4")),
    ]
    for name, eq in variants:
        m = S.metrics(eq)
        print("%-30s %8.2fx %6.1f%% %8.1f%% %6.1f%% %6.2f" %
              (name, m["mult"], m["cagr"], m["mdd"], m["vol"], m["sharpe"]))
    print("-" * 80)
    mb = S.metrics(eq_b)
    print("\n诚实解读: EX-ANTE 质量层(ROE+营收增速)能否突破 B=20.6% 的诚实上限?")
    print("  若 Q2/Q3 年化 > B 且回撤不恶化 = 真改进; 若仅回撤变化而收益不增 = 无效。")

if __name__ == "__main__":
    main()
