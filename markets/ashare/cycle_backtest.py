# -*- coding: utf-8 -*-
"""
cycle_backtest.py —— 从 K 线"自己找周期"(类加密 cycle 思路, 严格 ex-ante)
==========================================================================
用户澄清: 不是用基本面选股, 拉 K 线就是要像加密一样, 自己从价格里找周期。

本脚本做三件事, 全部只用价格(无基本面、无未来函数):
  1. 谱分析(FFT) 在 等权篮子净值 / 上证指数 上挖"主导周期"(按月/年报告)。
     —— 这是"找周期"的回答: A股存在哪些可识别的周期性。
     —— 注意: 全样本 FFT 是 in-sample 诊断, 仅用于"看见周期", 不可直接当信号。
  2. 日历季节性: 按自然月统计 40 只池的日均收益, 找出系统性月份。
  3. ex-ante 周期择时(可交易、严格因果):
       - 季节性择时: 每月只用"此前年份同月"均值决定满仓/空仓。
       - 谱周期择时: 每个调仓点只用过去 3 年数据 FFT 取主导周期,
         拟合正弦并看相位是否上行 -> 上行满仓, 否则空仓。
     与 B(等权买持) 对比, 验证"周期择时"到底能不能优化。

铁律: 任何决策点 t 只用 t 之前的数据。
"""
import os, sys, json, math, argparse
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
import data_store as ds

BASE = os.path.dirname(os.path.abspath(__file__))

def load_universe():
    import stock_backtest as sb
    return sb.UNIVERSE

def build_eqw_index(universe, start="2015-06-01"):
    """日频等权价格指数(各股归一后等权平均), 对齐公共交易日。"""
    series = {}
    for code, _, name in universe:
        bars = ds.load_bars(code)
        if not bars:
            continue
        tmp = {}
        for b in bars:
            if b["d"] >= start:
                tmp[b["d"]] = float(b["c"])
        if tmp:
            first = min(tmp.values())
            series[code] = {d: v / first for d, v in tmp.items()}
    if not series:
        return None, None
    dates = sorted(set().union(*[set(s.keys()) for s in series.values()]))
    idx = []
    for d in dates:
        vals = [s[d] for s in series.values() if d in s]
        if vals:
            idx.append((d, sum(vals) / len(vals)))
    return [x[0] for x in idx], np.array([x[1] for x in idx], float)

def detrend(logp, n=250):
    """去趋势: 减去 n 日 MA, 得到周期残差。"""
    ma = np.convolve(logp, np.ones(n) / n, mode="same")
    # 边界用有效窗口
    res = logp - ma
    return res

def spectral_peaks(x, dt=1.0, lo=20, hi=750):
    """FFT 周期图, 返回 (period_days, power) 按功率降序, 限制周期 [lo,hi] 交易日。"""
    x = np.asarray(x, float)
    x = x - x.mean()
    N = len(x)
    fft = np.fft.rfft(x * np.hanning(N))
    power = np.abs(fft) ** 2
    freqs = np.fft.rfftfreq(N, d=dt)
    periods = 1.0 / freqs[1:]
    pw = power[1:]
    mask = (periods >= lo) & (periods <= hi)
    periods = periods[mask]; pw = pw[mask]
    order = np.argsort(pw)[::-1]
    out = []
    for i in order[:6]:
        out.append((float(periods[i]), float(pw[i])))
    return out

def months_of_year(dates):
    return [int(d[5:7]) for d in dates]

def seasonal_table(dates, daily_ret):
    """按自然月聚合日均收益(池级, 已把各股日收益池在一起)。"""
    by_month = {m: [] for m in range(1, 13)}
    for d, r in zip(dates, daily_ret):
        by_month[int(d[5:7])].append(r)
    rows = []
    for m in range(1, 13):
        v = by_month[m]
        rows.append((m, float(np.mean(v)) * 100 if v else float("nan"),
                     len(v)))
    return rows

def metrics(eq):
    eq = np.asarray(eq, float)
    n = len(eq) - 1
    yrs = n / 242.0
    mult = eq[-1] / eq[0]
    cagr = (mult ** (1 / yrs) - 1) if mult > 0 and yrs > 0 else float("nan")
    peak = eq[0]; mdd = 0.0
    for x in eq:
        peak = max(peak, x); mdd = min(mdd, x / peak - 1)
    rets = eq[1:] / eq[:-1] - 1
    sharpe = (rets.mean() / rets.std() * math.sqrt(242)) if rets.std() > 0 else 0.0
    return dict(mult=round(mult, 2), cagr=round(cagr * 100, 1),
                mdd=round(mdd * 100, 1), sharpe=round(sharpe, 2),
                vol=round(rets.std() * math.sqrt(242) * 100, 1))

# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--rebal", type=int, default=21)
    args = ap.parse_args()

    uni = load_universe()
    dates, idx = build_eqw_index(uni, start="2015-06-01")
    # 限定回测窗口
    sel = [i for i, d in enumerate(dates) if d >= args.start]
    dates = [dates[i] for i in sel]; idx = idx[sel]
    logp = np.log(idx)

    print("=" * 70)
    print(f"周期分析: 等权篮子 {len(uni)} 只 | 窗口 {dates[0]}→{dates[-1]} "
          f"({len(dates)} 日)")
    print("=" * 70)

    # ---- 1. 谱分析: 找主导周期 ----
    print("\n【1】谱分析(FFT, in-sample 诊断): 等权篮子的主导周期")
    res = detrend(logp, 250)
    peaks = spectral_peaks(res, lo=20, hi=750)
    trading_days_per_year = 242
    for p, pw in peaks:
        yrs = p / trading_days_per_year
        label = f"{p:.0f}交易日" if p < 200 else f"{yrs:.2f}年"
        print(f"   周期 ≈ {label:>10}  (功率 {pw:.1e})")
    dom = peaks[0][0]
    print(f"   >> 最强主导周期 ≈ {dom:.0f} 交易日 ({dom/trading_days_per_year:.2f}年)")

    # 上证指数对比
    idxbars = ds.load_bars("sh000001")
    idates = [b["d"] for b in idxbars if b["d"] >= args.start]
    iclose = np.array([float(b["c"]) for b in idxbars if b["d"] >= args.start])
    ilog = np.log(iclose)
    ires = detrend(ilog, 250)
    ipeaks = spectral_peaks(ires, lo=20, hi=750)
    print("   上证指数主导周期:")
    for p, pw in ipeaks[:3]:
        yrs = p / trading_days_per_year
        label = f"{p:.0f}交易日" if p < 200 else f"{yrs:.2f}年"
        print(f"     周期 ≈ {label:>10}  (功率 {pw:.1e})")

    # ---- 2. 日历季节性 ----
    print("\n【2】日历季节性(全样本描述): 各自然月池级日均收益(%)")
    daily_ret = idx[1:] / idx[:-1] - 1
    ddates = dates[1:]
    stbl = seasonal_table(ddates, daily_ret)
    for m, r, n in stbl:        print(f"   {m:2d}月: {r:+.3f}%  (n={n})")
    best = [m for m, r, _ in stbl if r == max(x[1] for x in stbl)]
    worst = [m for m, r, _ in stbl if r == min(x[1] for x in stbl)]
    print(f"   最强月: {best}  最弱月: {worst}")

    # ---- 3. ex-ante 季节性择时 ----
    print("\n【3】ex-ante 季节性择时(只用此前年份同月均值决定满仓/空仓)")
    eq = [1.0]
    pos = 1.0
    for i in range(1, len(dates)):
        m = int(dates[i][5:7])
        # 此前年份同月均值
        past = [r for dm, r in zip(ddates, daily_ret) if dm < dates[i] and int(dm[5:7]) == m]
        target = 1.0 if (past and np.mean(past) > 0) else 0.0
        pos = target
        eq.append(eq[-1] * (1 + pos * daily_ret[i - 1]))
    print("   ", metrics(np.array(eq)), "vs B(满仓) 见下")

    # ---- B 基线(满仓等权, 日频再平衡近似) ----
    eqB = idx / idx[0]
    mB = metrics(eqB)
    print(f"\n【B 等权买持(满仓)】 {mB}")

    # ---- 4. ex-ante 谱周期择时(滚动 3 年 FFT) ----
    print("\n【4】ex-ante 谱周期择时(滚动3年 FFT 取主导周期, 看相位上行才满仓)")
    eq2 = [1.0]
    pos2 = 1.0
    win = 242 * 3
    for i in range(1, len(dates)):
        if i >= win:
            hist = detrend(np.log(idx[max(0, i - win):i + 1]), 250)
            pk = spectral_peaks(hist, lo=20, hi=750)
            P = pk[0][0]
            # 用 FFT 主频相位重建正弦, 看 t 处信号斜率
            t = np.arange(len(hist))
            f = 1.0 / P
            # 拟合 a*sin(2π f t)+b*cos(...) 用最小二乘(简单)
            s = np.sin(2 * np.pi * f * t); c = np.cos(2 * np.pi * f * t)
            A = np.linalg.lstsq(np.vstack([s, c, np.ones_like(t)]).T, hist, rcond=None)[0]
            sig_now = A[0] * np.sin(2 * np.pi * f * (len(hist) - 1)) + A[1] * np.cos(2 * np.pi * f * (len(hist) - 1))
            sig_nxt = A[0] * np.sin(2 * np.pi * f * (len(hist))) + A[1] * np.cos(2 * np.pi * f * (len(hist)))
            pos2 = 1.0 if sig_nxt > sig_now else 0.0
        eq2.append(eq2[-1] * (1 + pos2 * daily_ret[i - 1]))
    print("   ", metrics(np.array(eq2)))

    print("\n【对照汇总】")
    print(f"   B 满仓等权        : {mB}")
    print(f"   季节性 ex-ante    : {metrics(np.array(eq))}")
    print(f"   谱周期 ex-ante    : {metrics(np.array(eq2))}")
    print("\n诚实结论见正文。")

if __name__ == "__main__":
    main()
