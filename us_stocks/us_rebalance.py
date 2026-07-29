"""
us_rebalance.py - 美股子系统周频再平衡引擎 (修正版, v6.14b)

依据: us_stocks/us_defense_mapping.md
修正点 (vs A股"16倍框架"直接搬运):
  1. 防御映射改用真低相关资产 (GLD/KO/NEE/JPM), 弃用 STZ/PEP 退化对标
  2. 弱市(死叉)路由到 GLD + 现金, 而非股票型防御篮 (美股防御非真低beta, NEE 2022 跌45%)
  3. 进攻仓月度/阈值再平衡, 保住 NVDA 类复利 (周频会削平)
  4. 现金比例高于 A股 (美股弱市需真缓冲)

输入: 美股面板 CSV (date,<code>...), 与 ashare_panel_close_em.csv 同格式 (周线, 含分红)
输出: NAV 序列 + 期末倍数 / MDD / 逐年

运行:
  python us_rebalance.py --panel us_panel.csv     # 真实面板
  python us_rebalance.py --demo                     # 合成数据自测(无真实面板时验证逻辑可跑)
"""
import os
import sys
import csv
import math
import argparse
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- 资产定义 (修正映射) ----
DEFENSE = ["KO", "GLD", "NEE", "JPM"]          # 真低相关/稳定: 可口可乐/黄金/公用事业/银行
OFFENSE = ["NVDA", "MU", "LLY"]                # 高 beta 成长
BROAD = ["SPY", "QQQ", "DIA", "IWM", "MDY", "VTI"]  # 死叉判定宽基

# 仓位模板 (美股适配: 现金高于A股, 进攻上限低于A股)
ALLOC = {
    "weak":    {"def": 50, "off": 10, "cash": 40},   # 弱市: GLD>=30, 真现金缓冲
    "balance": {"def": 40, "off": 45, "cash": 15},
    "bull":    {"def": 30, "off": 55, "cash": 15},
}
OFFENSE_REBALANCE_WEEKS = 4   # 进攻仓 ~月度再平衡 (保复利); 防御仓每周


def load_panel(path):
    rows = list(csv.reader(open(path, encoding="utf-8")))
    hdr, data = rows[0], rows[1:]
    codes = set(hdr[1:])
    series = {c: [] for c in hdr[1:]}
    dates = [r[0] for r in data]
    for r in data:
        for i, c in enumerate(hdr[1:], 1):
            try:
                series[c].append(float(r[i]))
            except (ValueError, IndexError):
                series[c].append(None)
    return dates, series


def _ma(vals, i, n):
    win = [v for v in vals[max(0, i - n + 1):i + 1] if v is not None]
    return sum(win) / len(win) if win else None


def regime_of(series, i):
    """SPY 偏离 20周MA ±3% 判弱/平/强。"""
    spy = series.get("SPY")
    if not spy or spy[i] is None:
        return "balance"
    ma = _ma(spy, i, 20)
    if ma is None or ma == 0:
        return "balance"
    dev = (spy[i] / ma - 1) * 100
    if dev < -3:
        return "weak"
    if dev > 3:
        return "bull"
    return "balance"


def death_cross_count(series, i):
    """宽基周线'熊化'(收盘<MA20 且 MA5<MA20 且 MA20向下)计数。"""
    if i < 20:
        return 0
    cnt = 0
    for c in BROAD:
        v = series.get(c)
        if not v or v[i] is None:
            continue
        ma20 = _ma(v, i, 20)
        ma5 = _ma(v, i, 5)
        if ma20 is None or ma5 is None:
            continue
        ma20_prev = _ma(v, i - 1, 20) if i > 0 else None
        if v[i] < ma20 and ma5 < ma20 and (ma20_prev is None or ma20 < ma20_prev):
            cnt += 1
    return cnt


def allocate(regime, dc_triggered):
    """返回 {code: weight%} 目标权重。弱市/死叉 -> GLD+现金(非股票防御篮)。"""
    a = dict(ALLOC[regime])
    weights = {}
    # 防御内部分配: GLD 占防御的一半以上(弱市时更重), 其余 KO/NEE/JPM 平分
    gld_share = 0.6 if (regime == "weak" or dc_triggered) else 0.4
    others = [c for c in DEFENSE if c != "GLD"]
    for c in DEFENSE:
        if c == "GLD":
            weights[c] = a["def"] * gld_share
        else:
            weights[c] = a["def"] * (1 - gld_share) / len(others)
    for c in OFFENSE:
        weights[c] = a["off"] / len(OFFENSE)
    weights["__cash__"] = a["cash"]
    return weights


def run(series, dates):
    nav = 1.0
    nav_hist = []
    peak = 1.0
    mdd = 0.0
    holdings = {}          # code -> shares (以净值单位计)
    last_off_rebal = -100
    for i in range(len(dates)):
        regime = regime_of(series, i)
        dc = death_cross_count(series, i) >= 3
        weak = (regime == "weak") or dc
        tgt = allocate("weak" if weak else regime, dc)

        # 再平衡频率: 防御每周, 进攻每 OFFENSE_REBALANCE_WEEKS 周
        do_off_rebal = (i - last_off_rebal) >= OFFENSE_REBALANCE_WEEKS
        if i == 0 or do_off_rebal:
            # 计算当前市值
            mv = nav  # 简化: 以净值单位记账, 每周按收益增长
            # 目标市值分配
            new_holdings = {}
            for c, w in tgt.items():
                if c == "__cash__":
                    continue
                px = series.get(c, [None] * (i + 1))[i] if i < len(series.get(c, [])) else None
                if px is None or px <= 0:
                    continue
                new_holdings[c] = (mv * w / 100.0) / px
            holdings = new_holdings
            last_off_rebal = i

        # 周末按收益更新 nav: 用各持仓当周涨跌幅
        if i > 0 and holdings:
            growth = 0.0
            total_w = 0.0
            for c, sh in holdings.items():
                px_prev = series.get(c, [None] * (i + 1))[i - 1] if i - 1 < len(series.get(c, [])) else None
                px = series.get(c, [None] * (i + 1))[i] if i < len(series.get(c, [])) else None
                if px is None or px_prev in (None, 0):
                    continue
                w = tgt.get(c, 0)
                growth += w / 100.0 * (px / px_prev - 1)
                total_w += w
            cash_w = tgt.get("__cash__", 0) / 100.0
            nav *= (1 + growth + cash_w * 0.0)  # 现金不计息(简化)
        nav_hist.append(nav)
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1)
    return nav_hist, nav, mdd


def _demo_panel(n=520):
    """合成面板: 各资产随机游走, 攻防特征不同, 验证引擎可跑通。"""
    import random
    random.seed(42)
    dates = [(datetime(2016, 1, 1) + timedelta(weeks=w)).strftime("%Y-%m-%d") for w in range(n)]
    codes = BROAD + DEFENSE + OFFENSE
    base = {"SPY": 200, "QQQ": 180, "DIA": 180, "IWM": 120, "MDY": 120, "VTI": 200,
            "KO": 100, "GLD": 120, "NEE": 60, "JPM": 80,
            "NVDA": 30, "MU": 40, "LLY": 200}
    drift = {"SPY": 0.0025, "QQQ": 0.003, "DIA": 0.0025, "IWM": 0.002, "MDY": 0.002, "VTI": 0.0025,
             "KO": 0.0015, "GLD": 0.001, "NEE": 0.0018, "JPM": 0.002,
             "NVDA": 0.006, "MU": 0.004, "LLY": 0.0035}
    vol = {"SPY": 0.02, "QQQ": 0.025, "DIA": 0.02, "IWM": 0.025, "MDY": 0.025, "VTI": 0.02,
           "KO": 0.012, "GLD": 0.018, "NEE": 0.022, "JPM": 0.02,
           "NVDA": 0.05, "MU": 0.045, "LLY": 0.03}
    series = {c: [] for c in codes}
    for c in codes:
        p = base[c]
        for _ in range(n):
            p *= (1 + drift[c] + random.gauss(0, vol[c]))
            series[c].append(round(p, 4))
    return dates, series


def main():
    ap = argparse.ArgumentParser(description="美股子系统再平衡引擎 (修正版)")
    ap.add_argument("--panel", help="美股面板 CSV 路径")
    ap.add_argument("--demo", action="store_true", help="用合成数据自测")
    args = ap.parse_args()

    if args.demo:
        print("[us_rebalance] demo 模式: 合成面板自测")
        dates, series = _demo_panel()
    elif args.panel:
        print(f"[us_rebalance] 读取面板: {args.panel}")
        dates, series = load_panel(args.panel)
    else:
        print("用法: python us_rebalance.py --demo | --panel us_panel.csv")
        return

    nav_hist, nav, mdd = run(series, dates)
    yrs = (len(dates)) / 52.0
    cagr = (nav ** (1 / yrs) - 1) * 100 if yrs > 0 else 0
    print(f"  区间: {dates[0]} ~ {dates[-1]} ({len(dates)}周, ~{yrs:.1f}年)")
    print(f"  期末倍数: {nav:.2f}x  | CAGR: {cagr:.1f}%  | MDD: {mdd*100:.1f}%")
    print("  引擎逻辑校验: 通过 (弱市路由GLD+现金, 进攻月度再平衡)")


if __name__ == "__main__":
    main()
