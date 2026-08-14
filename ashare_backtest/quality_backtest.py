# -*- coding: utf-8 -*-
"""
quality_backtest.py —— 个股层选股下沉(质量/估值)概念验证
========================================================
用 tdx_quotes 快照(2026-08-14)的 PE/PB/EPS 做静态质量分层, 测两类"选股下沉":
  1. B-ex-困境: 等权但剔除亏损股(万科 EPS<0) — 不持有基本面破裂的票。
  2. 价值倾斜: 权重 ∝ 1/PE (在盈利为正的票里), 越低估给越多权重。
诚实标注: 用"当前快照"给 2016-2026 组合加权 = 含前视偏差, 仅作方向性概念验证,
不可作为实盘信号。真实无前视版本需逐期历史财务(tdx_api_data 仅 6 年, 不够全窗口)。
"""
import os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data_store as ds
import stock_backtest as S

BASE = os.path.dirname(os.path.abspath(__file__))


def load_fund():
    return json.load(open(os.path.join(BASE, "data/ashare/fundamentals_20260814.json")))["stocks"]


def eq_weight_dates(dates, by_code_t, weight_map, rebal=21):
    """weight_map: {code: 静态权重系数}; 每个 rebal 日按当时已上市 + 系数归一化建仓。"""
    codes = list(by_code_t.keys())
    n = len(dates)
    eq = [1.0]
    prev_w = {c: 0.0 for c in codes}
    for i in range(1, n):
        rebal_day = (i % rebal == 0) or (i <= rebal)
        target = dict(prev_w)
        if rebal_day:
            avail = [c for c in codes if dates[i - 1] in by_code_t[c][1]]
            wsum = sum(weight_map.get(c, 0.0) for c in avail)
            target = {c: 0.0 for c in codes}
            if wsum > 0:
                for c in avail:
                    target[c] = weight_map.get(c, 0.0) / wsum
        day_ret = 0.0
        for c in codes:
            w = prev_w[c]
            if w == 0:
                continue
            seq = by_code_t[c][1]
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
    fund = load_fund()
    dates_all, _, _ = S.build_market_clock()
    by_code, _ = S.build_stock_matrix(dates_all)
    start = "2016-01-01"
    s0 = [k for k, d in enumerate(dates_all) if d >= start][0]
    dates = dates_all[s0:]
    by_code_t = {c: (nm, {d: sq[d] for d in dates if d in sq})
                 for c, (nm, sq) in by_code.items()}

    w_b = {c: 1.0 for c in by_code_t}                                  # B 等权全 20
    w_ex = {c: (1.0 if fund[c]["eps"] > 0 else 0.0) for c in by_code_t}  # 剔除亏损
    w_val = {c: ((1.0 / fund[c]["pe"]) if (fund[c]["pe"] and fund[c]["pe"] > 0) else 0.0)
             for c in by_code_t}                                        # 价值倾斜

    eq_b = eq_weight_dates(dates, by_code_t, w_b)
    eq_ex = eq_weight_dates(dates, by_code_t, w_ex)
    eq_val = eq_weight_dates(dates, by_code_t, w_val)
    eq_e, best_c = S.best_single(dates, by_code_t)

    print("== 选股下沉(质量/估值)概念验证  窗口 %s~%s ==" % (dates[0], dates[-1]))
    print("(注: 用 2026-08-14 财务快照加权 = 含前视偏差, 仅方向性验证)\n")
    print("%-26s %8s %7s %8s %6s %6s" % ("策略", "倍率", "年化%", "最大回撤%", "波动%", "夏普"))
    print("-" * 60)
    for name, eq in [("B 等权买持20(基准)", eq_b),
                     ("B 剔除亏损股(万科)", eq_ex),
                     ("价值倾斜(∝1/PE)", eq_val),
                     ("E 事后最佳单只", eq_e)]:
        m = S.metrics(eq)
        tag = ("  <<%s" % best_c[1]) if name.startswith("E") else ""
        print("%-26s %8.2fx %6.1f%% %8.1f%% %6.1f%% %6.2f%s" %
              (name, m["mult"], m["cagr"], m["mdd"], m["vol"], m["sharpe"], tag))


if __name__ == "__main__":
    main()
