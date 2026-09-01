# -*- coding: utf-8 -*-
"""
combo_backtest.py —— 把"动几下"和"崩了减仓"组合, 在 50精选 上诚实测能否既提收益又控回撤
======================================================================================
用户两问:
  1. "50精选里, 真是买持才稳? 还是动几下更赚?"  -> 截面动量轮动(C)确实比 B 收益高(19%->22%),
     但回撤炸到 -57%(集中持5只热门, 2022 一起崩)。
  2. "收益真的不能提高了吗?" -> 本脚本测: 动量轮动(拿收益) + 篮子自身钟减仓(控回撤) 的组合。

机制(全部 ex-ante, 因果无前视, 零杠杆, 未调参):
  - B  : 等权买持全部 50(基准)
  - Ck : 截面动量轮动, 每期按 60 日收益排名持前 k 只满仓(动几下, k=5/10/20)
  - Ck+T: 在 Ck 之上叠加篮子自身 MA250 趋势钟(破位减到防御仓 15%, 站回满仓)
组合层用篮子"自身等权 NAV"当钟(非宽基指数, 见 ⑬ 修正), 避免钟错。
"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stock_backtest as sb
import timing_extreme_backtest as te

def main():
    start = "2016-01-01"; rebal = 21
    dates, idx_close, w_mkt = sb.build_market_clock()
    cut = [k for k, d in enumerate(dates) if d >= start]
    s0 = cut[0]
    dates = dates[s0:]; idx_close = idx_close[s0:]; w_mkt = w_mkt[s0:]
    by_code, fa = sb.build_stock_matrix(dates, sb.UNIVERSE)
    by_code_t = {c: (n, {d: seq[d] for d in dates if d in seq})
                 for c, (n, seq) in by_code.items()}

    eqB  = sb.simulate_bh_equal(dates, by_code_t, rebal)
    eqC5 = sb.simulate_rs_nogate(dates, by_code_t, 5,  rebal)
    eqC10= sb.simulate_rs_nogate(dates, by_code_t, 10, rebal)
    eqC20= sb.simulate_rs_nogate(dates, by_code_t, 20, rebal)

    # 篮子自身等权 NAV + 暴露序列(自身 MA250 二元钟)
    nav_b = te.build_basket_nav(dates, sb.UNIVERSE)
    exp_bin = te.apply_timing_exposure(nav_b, "MA250BIN")   # 破位清仓
    exp_floor = te.apply_timing_exposure(nav_b, "MA250", def_exp=0.15)  # 15%防御仓

    def overlay(eq, E):
        out = [1.0]
        for i in range(1, len(dates)):
            cr = eq[i]/eq[i-1] - 1
            out.append(out[-1] * (1 + cr * E[i-1]))
        return out

    eqC10_bin   = overlay(eqC10, exp_bin)
    eqC10_floor = overlay(eqC10, exp_floor)
    eqC20_floor = overlay(eqC20, exp_floor)

    print("=" * 80)
    print("组合回测: 动量轮动(动几下) + 篮子自身钟减仓(控回撤)  窗口 %s~%s" % (dates[0], dates[-1]))
    print("=" * 80)
    rows = [
        ("B 等权买持全部50(基准)", eqB),
        ("C5 动量轮动前5(满仓)", eqC5),
        ("C10 动量轮动前10(满仓)", eqC10),
        ("C20 动量轮动前20(满仓)", eqC20),
        ("C10+T(清仓) 轮动+自身钟", eqC10_bin),
        ("C10+T(15%仓) 轮动+自身钟", eqC10_floor),
        ("C20+T(15%仓) 轮动+自身钟", eqC20_floor),
    ]
    print("%-30s %8s %7s %9s %6s %6s" % ("策略","倍率","年化%","最大回撤%","波动%","夏普"))
    print("-" * 80)
    res = {}
    for name, eq in rows:
        m = sb.metrics(eq); res[name] = m
        print("%-30s %8.2fx %6.1f%% %8.1f%% %6.1f%% %6.2f" %
              (name, m["mult"], m["cagr"], m["mdd"], m["vol"], m["sharpe"]))
    b = res["B 等权买持全部50(基准)"]
    print("\n诚实判定 (对比 B 基准 %.1f%% / 回撤 %.1f%%):" % (b["cagr"], b["mdd"]))
    for nm in ["C10 动量轮动前10(满仓)","C10+T(15%仓) 轮动+自身钟","C20+T(15%仓) 轮动+自身钟"]:
        m = res[nm]
        tag = "收益↑且回撤↓=严格占优" if (m["cagr"]>b["cagr"] and m["mdd"]>b["mdd"]) else \
              ("收益↑但回撤更炸" if m["cagr"]>b["cagr"] else "回撤↓但收益降")

if __name__ == "__main__":
    main()
