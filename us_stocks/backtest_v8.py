"""
backtest_v8.py - V8: 扩展宇宙 + 美股自适应防御
=============================================
用户两条指令:
  1) 美股池子才 19 只太少 -> 扩容(对标 A 股 120 只广度)。已扩到 13 题材/~90 只,
     数据文件 weekly_adjclose_full.csv (129 列, 2016-08-01~2026-07-20)。
  2) A 股极端防御(regime_band ±3% + death_cross 清仓转防御)是因为 A 股易崩;
     美股极端崩盘少 -> 防御**自适应放宽**: 宽波段 + weak 不清仓转防御。

设计:
  - 候选池 = 全部个股(剔除指数 SPY/QQQ/IWM/VTI/MDY/DIA 与可转债 CWB)。
  - 动量选股仍锁定 THEME_STOCKS(木头姐"题材驱动"), 但题材已扩到 13/90, 广度足够。
  - 自适应防御两杠杆(可扫参, 用数据证"美股应更轻防御"):
      band      : regime 判定带宽。A 股 ±3%; 美股扫 {3,4,5,6}%。
      weak_clear: weak 期把多少进攻预算转 CWB(类 death_cross 清仓)。
                  A 股=1.0(全清); 美股扫 {0.0,0.5,1.0}(越轻=越多进攻留股市)。
  - ALLOC_US: weak 防御占比降到 50%(A 股 60%); flat/strong 同 V7 正确配置。
  - 永久防御 KO/ABBV 不变(2 个)。
"""
import pandas as pd, numpy as np, os
HERE = os.path.dirname(__file__); DATA = os.path.join(HERE, 'data')
import us_adoption as ua

_PHASE_MULT = {"accelerating": 1.35, "early": 1.15, "mature": 0.8, "saturating": 0.65, "unknown": 1.0, "policy": 1.0}

# 美股自适应配置(def/off/cash)。weak 防御更轻(A 股 weak=60/24/16)。
ALLOC_US = {'weak': (0.50, 0.34, 0.16), 'flat': (0.35, 0.60, 0.05), 'strong': (0.25, 0.70, 0.05)}
# 原始配置(用于引擎自检, 对齐 V7a: weak 60/24/16)
CORRECT_ALLOC = {'weak': (0.60, 0.24, 0.16), 'flat': (0.45, 0.45, 0.10), 'strong': (0.35, 0.60, 0.05)}

EXCLUDE = {'SPY', 'CWB', 'QQQ', 'DIA', 'IWM', 'MDY', 'VTI'}   # 指数/工具, 不进选股池

def load(full=True):
    fn = 'weekly_adjclose_full.csv' if full else 'weekly_adjclose.csv'
    px = pd.read_csv(os.path.join(DATA, fn), index_col=0, parse_dates=True).sort_index()
    px = px[px['SPY'].notna()].copy()
    return px

def stock_momentum(px, as_of, window=52, bench='SPY'):
    i = px.index.get_loc(as_of)
    if i < window: return {}
    bench_ret = (px[bench].iloc[i] / px[bench].iloc[i - window]) - 1
    out = {}
    for s in px.columns:
        if s in EXCLUDE: continue
        ser = px[s].iloc[i - window:i + 1].dropna()
        if len(ser) < window * 0.7: continue
        r = ser.iloc[-1] / ser.iloc[0] - 1
        out[s] = (r + (r - bench_ret)) / 2.0
    return out

def offense_dynamic(px, n, year, valid, as_of, window=52, phase_tilt=True, pool=None):
    """动量(个股 trailing) × 相位乘子 联合打分, Top-n。pool=候选集(剔除防御/指数)。"""
    sm = stock_momentum(px, as_of, window)
    scores = {}
    for th, stocks in ua.THEME_STOCKS.items():
        ph = ua._phase_for(th, year); pm = _PHASE_MULT.get(ph, 1.0)
        for s in stocks:
            if s not in valid: continue
            if pool is not None and s not in pool: continue
            m = sm.get(s, 0.0)
            if phase_tilt:
                adj = pm if ph in ("accelerating", "early") else 1.0
                scores[s] = adj * max(m, 0.0)
            else:
                scores[s] = max(m, 0.0)
    return [s for s in sorted(scores, key=lambda s: scores[s], reverse=True) if scores[s] > 0][:n]

def make_regime(px, band, bench='SPY'):
    b = px[bench]; ma20 = b.rolling(20).mean(); dev = (b - ma20) / ma20
    reg = pd.Series(np.where(dev < -band, 'weak', np.where(dev > band, 'strong', 'flat')), index=px.index)
    reg = reg.where(ma20.notna(), 'flat')
    return reg, dev

def run(px, band=5.0, weak_clear=0.0, signal_mode='dynamic', def_list=('KO', 'ABBV'),
        off_n=10, core=3, core_share=0.90, window=52, phase_tilt=True,
        asof_mode='year', alloc=ALLOC_US, label=''):
    dates = px.index; bench = 'SPY'; CONV = 'CWB'
    regime, dev = make_regime(px, band)
    nav = pd.Series(10000.0, index=dates); weights = None
    asof_cache = {}
    for Y in range(dates[0].year, dates[-1].year + 1):
        yr = px[px.index.year == Y - 1]
        asof_cache[Y] = yr.index[-1] if len(yr) else None
    pool = [c for c in px.columns if c not in EXCLUDE and c not in def_list]
    for t in range(1, len(dates)):
        Y = dates[t].year; r = regime.iloc[t]; d, o, c = alloc[r]
        avail = {s for s in px.columns if pd.notna(px[s].iloc[t])}
        ts = {}
        if r == 'weak' and weak_clear >= 1.0:
            ts[CONV] = o                      # A 股式: weak 全清进攻转 CWB
        else:
            ao = dates[t - 1] if asof_mode == 'week' else asof_cache[Y]
            if ao is None: ao = dates[t - 1]
            off = offense_dynamic(px, off_n, Y, avail, ao, window=window, phase_tilt=phase_tilt, pool=pool)
            if len(off) < off_n:
                off = (off + pool)[:off_n]   # 回退到篮子本身, 避免引用篮外票
            ob = o * (weak_clear if r == 'weak' else 0.0)   # weak 期转 CWB 的部分
            if ob > 0: ts[CONV] = ob
            oe = o - ob                       # 留在股市的进攻预算
            if oe > 0:
                wt = ua.offense_weights_for_year(Y, valid=avail, mode='stock_sum') or {}
                cn = off[:core]; sn = off[core:]
                cwt = sum(wt.get(s, 0) for s in cn) or 1.0
                for s in cn:
                    if pd.notna(px[s].iloc[t]) and pd.notna(px[s].iloc[t - 1]):
                        ts[s] = oe * core_share * wt.get(s, 0) / cwt
                for s in sn:
                    if pd.notna(px[s].iloc[t]) and pd.notna(px[s].iloc[t - 1]):
                        ts[s] = oe * (1 - core_share) / max(1, len(sn))
        for s in def_list: ts[s] = d / len(def_list)
        if weights is None: weights = dict(ts)
        ret = 1.0
        for s, w in weights.items():
            if w <= 0: continue
            p0 = px[s].iloc[t - 1]; p1 = px[s].iloc[t]
            if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                ret += w * ((p1 / p0) - 1)
        nav.iloc[t] = nav.iloc[t - 1] * ret
        nw = {}
        for s, w in weights.items():
            p0 = px[s].iloc[t - 1]; p1 = px[s].iloc[t]
            nw[s] = w * (p1 / p0) if (pd.notna(p0) and pd.notna(p1) and p0 > 0) else w
        tot = sum(nw.values()) or 1.0
        nw = {s: w / tot for s, w in nw.items()}
        drift = max(abs(nw.get(k, 0) - ts.get(k, 0)) for k in set(nw) | set(ts))
        weights = dict(ts) if drift > 0 else nw
    m = nav.iloc[-1] / 10000; y = (dates[-1] - dates[0]).days / 365.25
    mdd = ((nav - nav.cummax()) / nav.cummax()).min()
    # weak 占比(自适应轻防御的证据)
    weak_frac = (regime == 'weak').mean()
    return dict(label=label, multiple=m, cagr=m ** (1 / y) - 1, mdd=mdd, nav=nav,
                weak_frac=weak_frac, regime=regime)

if __name__ == '__main__':
    full = load(full=True)
    y = (full.index[-1] - full.index[0]).days / 365.25
    print(f"=== V8 扩展宇宙回测 ===")
    print(f"窗口: {full.index[0].date()} ~ {full.index[-1].date()} ({y:.2f} 年) | 13 题材/~90 只 | 10 仓位\n")

    # ---- 引擎自检: 旧 31 列宇宙 + band=0.03 + weak_clear=1.0(全清) + 原始配置 应复现 V7a=16.54x ----
    # 注: 早期报告里的 24.55x 是更早数据/代码状态的旧值, 当前可复现 V7a=16.54x。
    old = load(full=False)
    chk = run(old, band=0.03, weak_clear=1.0, off_n=8, core=3, core_share=0.90,
              window=52, phase_tilt=True, asof_mode='year', alloc=CORRECT_ALLOC,
              label='[自检] 旧宇宙 band3% 全清(应=V7a 16.54x)')
    print(f"{chk['label']:<44}{chk['multiple']:>8.2f}x  CAGR {chk['cagr']*100:5.1f}%  MDD {chk['mdd']*100:6.1f}%  weak% {chk['weak_frac']*100:4.1f}\n")

    # ---- 扫参: band {3,4,5,6}% × weak_clear {0.0,0.5,1.0} ----
    print(f"{'band%':>5} {'weak_clear':>10} {'倍数':>9} {'年化':>8} {'MDD':>9} {'weak%':>7}")
    print('-' * 54)
    grid = []
    for band in (0.03, 0.04, 0.05, 0.06):
        for wc in (0.0, 0.5, 1.0):
            r = run(full, band=band, weak_clear=wc, off_n=10, core=3, core_share=0.90,
                    window=52, phase_tilt=True, asof_mode='year',
                    label=f'band{int(band*100)} wc{wc:.1f}')
            grid.append(r)
            print(f"{int(band*100):>5} {wc:>10.1f} {r['multiple']:>8.2f}x {r['cagr']*100:>7.1f}% {r['mdd']*100:>8.1f}% {r['weak_frac']*100:>6.1f}%")
    best = max(grid, key=lambda r: r['multiple'])
    v7a = 16.54  # 当前可复现 V7a 基准(旧 31 列宇宙, band3% 全清)
    print(f"\n[最优] {best['label']}: {best['multiple']:.2f}x | V7a 基准 {v7a}x | 提升 {(best['multiple']/v7a-1)*100:+.1f}%")

    # ---- 效应分解: 宇宙扩容 vs 自适应防御 各自贡献(统一 off_n=10, band=3%) ----
    print('\n=== 效应分解 (off_n=10, band=3%) ===')
    dec = {
        '旧宇宙+全防御(A股式)': run(old,  band=0.03, weak_clear=1.0, off_n=10, core=3, core_share=0.90, window=52, phase_tilt=True, asof_mode='year', label='d1'),
        '旧宇宙+轻防御(美股式)': run(old,  band=0.03, weak_clear=0.0, off_n=10, core=3, core_share=0.90, window=52, phase_tilt=True, asof_mode='year', label='d2'),
        '新宇宙+全防御(A股式)': run(full, band=0.03, weak_clear=1.0, off_n=10, core=3, core_share=0.90, window=52, phase_tilt=True, asof_mode='year', label='d3'),
        '新宇宙+轻防御(美股式)': run(full, band=0.03, weak_clear=0.0, off_n=10, core=3, core_share=0.90, window=52, phase_tilt=True, asof_mode='year', label='d4'),
    }
    for k, r in dec.items():
        print(f"  {k:<22}{r['multiple']:>8.2f}x  CAGR {r['cagr']*100:5.1f}%  MDD {r['mdd']*100:6.1f}%")
    u_eff = dec['新宇宙+全防御(A股式)']['multiple'] / dec['旧宇宙+全防御(A股式)']['multiple'] - 1
    d_eff = dec['新宇宙+轻防御(美股式)']['multiple'] / dec['新宇宙+全防御(A股式)']['multiple'] - 1
    print(f"  -> 宇宙扩容贡献: {u_eff*100:+.1f}% | 自适应防御贡献: {d_eff*100:+.1f}%")


    # ---- 最优组别的"逐周无前视"诚实版 ----
    import re
    m = re.match(r'band(\d+) wc([\d.]+)', best['label'])
    bb, bw = float(m.group(1)) / 100, float(m.group(2))
    wk = run(full, band=bb, weak_clear=bw, off_n=10, core=3, core_share=0.90,
             window=52, phase_tilt=True, asof_mode='week', label=f'最优 逐周无前视')
    print(f"{wk['label']:<44}{wk['multiple']:>8.2f}x  CAGR {wk['cagr']*100:5.1f}%  MDD {wk['mdd']*100:6.1f}%")

    bh = 10000 * full['SPY'].iloc[-1] / full['SPY'].iloc[0]
    spy_mult = bh / 10000
    print(f"{'买入持有 SPY':<44}{spy_mult:>8.2f}x  CAGR {spy_mult**(1/y)*100-100:5.1f}%")

    # ---- 逐年动态核心(最优组) ----
    asof_cache = {}
    for Y in range(full.index[0].year, full.index[-1].year + 1):
        yr = full[full.index.year == Y - 1]
        asof_cache[Y] = yr.index[-1] if len(yr) else None
    pool = [c for c in full.columns if c not in EXCLUDE and c not in ('KO', 'ABBV')]
    print('\n逐年动态核心3(扩展宇宙, 动量+相位, 12mo, 年初):')
    print('  ', [f"{Y}:{offense_dynamic(full, 3, Y, set(full.columns), asof_cache.get(Y) or full.index[0], window=52, phase_tilt=True, pool=pool)}" for Y in range(2017, 2027)])

    out = pd.DataFrame({r['label']: r['nav'] for r in grid + [wk]})
    out['SPY_buyhold'] = 10000 * full['SPY'] / full['SPY'].iloc[0]
    out.to_csv(os.path.join(DATA, 'us_nav_v8.csv'))
    print('\nsaved us_nav_v8.csv')
