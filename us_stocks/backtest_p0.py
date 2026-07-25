"""
backtest_p0.py - P0 硬化: 成本/税务 + 样本外(walk-forward) + 回撤韧性
=========================================================================
用户已批的三刀:
  P0-1  成本/税务建模: 周频再平衡隐含换手率 -> 交易成本(bps); 实现收益 -> 资本利得税。
  P0-2  样本外验证: 滚动 walk-forward(每年初用过去3年定 band/weak_clear, 当年实盘),
         杜绝"全样本调参"过拟合; 同时给 ex-ante(零前视)篮子也上成本, 做诚实下界。
  P0-3  回撤韧性: weak 期转防御力度扫 {0,0.5,1.0} + 波动率目标(vol-target)叠加,
         看 MDD 能否压到 -25% 内而不杀光收益。应对"指数跌70%"的极端崩盘。

复用 backtest_v8.run 的选股/配置逻辑, 但重写为 run_ext:
  - 接受 per-date 的 band_map / wc_map(支撑 walk-forward 动态参数)
  - 内置换手成本 + 可选资本利得税(逐标的成本基准 lot 跟踪)
  - 返回 nav 序列 + 指标, 供绘图/对比
"""
import pandas as pd, numpy as np, os, re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
HERE = os.path.dirname(__file__); DATA = os.path.join(HERE, 'data')
import us_adoption as ua
from backtest_v8 import ALLOC_US, EXCLUDE

_PHASE_MULT = {"accelerating": 1.35, "early": 1.15, "mature": 0.8, "saturating": 0.65,
               "unknown": 1.0, "policy": 1.0}

def load_us50():
    px = pd.read_csv(os.path.join(DATA, 'weekly_adjclose_us50.csv'), index_col=0, parse_dates=True).sort_index()
    return px[px['SPY'].notna()].copy()

def load_exante():
    px = pd.read_csv(os.path.join(DATA, 'weekly_adjclose_exante50.csv'), index_col=0, parse_dates=True).sort_index()
    return px[px['SPY'].notna()].copy()

def offense_dynamic(px, n, year, valid, as_of, window=52, phase_tilt=True, pool=None):
    sm = {}
    i = px.index.get_loc(as_of)
    if i >= window:
        bench_ret = (px['SPY'].iloc[i] / px['SPY'].iloc[i - window]) - 1
        for s in px.columns:
            if s in EXCLUDE: continue
            ser = px[s].iloc[i - window:i + 1].dropna()
            if len(ser) < window * 0.7: continue
            r = ser.iloc[-1] / ser.iloc[0] - 1
            sm[s] = (r + (r - bench_ret)) / 2.0
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

def _precompute_regime(px, band_map):
    b = px['SPY']; ma20 = b.rolling(20).mean(); dev = (b - ma20) / ma20
    return ma20, dev

def _target(px, t, band, wc, alloc, def_list, off_n, core, core_share, window,
            phase_tilt, asof_mode, pool, asof_cache):
    Y = px.index[t].year; r = px.index[t].name if False else None
    dev = px['SPY'].rolling(20).mean()
    return None

def run_ext(px, band_map, wc_map, cost_bps=0.0, tax_rate=0.0,
            off_n=10, core=3, core_share=0.90, window=52, phase_tilt=True,
            asof_mode='year', alloc=ALLOC_US, def_list=('KO', 'ABBV'),
            vol_target=None, crash_guard=None, label=''):
    """
    crash_guard: None 关闭; 或 dict {'ma':200, 'floor':0.35, 'deep':0.20}
      - SPY 收盘价 < ma周均线 -> 股票仓(进攻+防御)等比缩到 floor, 差额转 CWB(防御可转债)
      - SPY 收盘价 < (1-deep)*ma周均线 -> 股票仓清空(floor=0), 全转 CWB
      用于压住系统性崩盘(2008/2022 式)的损失。ma 需足够历史, 不足时风险开。
    """
    """
    band_map / wc_map: pd.Series 与 px.index 对齐, 逐周给出 regime 带宽 / weak 转防御比例。
    cost_bps: 单边换手成本(如 0.001 = 10bps 单边)。总成本 = 单边换手额 * cost_bps * 2? 
              这里 cost_bps 直接按"单边换手权重"计(即已是 round-trip 折半后的有效费率)。
              例: 周换手单边 0.35, cost_bps=0.002 -> 周成本 ~0.35*0.002=0.07%。
    tax_rate: 已实现收益资本利得税率(0=税优账户; 0.20=应税长持近似)。
    vol_target: 若给定(年化目标波动, 如 0.18), 叠加波动目标: 以 SPY 20 周实现波动为代理,
              当组合实现波动 > 目标时, 把超出部分转入 CWB(防御)。
    """
    dates = px.index; bench = 'SPY'; CONV = 'CWB'
    ma20 = px[bench].rolling(20).mean(); dev = (px[bench] - ma20) / ma20
    ma_long = px[bench].rolling(crash_guard['ma']).mean() if (crash_guard and crash_guard.get('mode','ma')=='ma') else None

    # as_of 缓存(上年末, 年模式)
    asof_cache = {}
    for Y in range(dates[0].year, dates[-1].year + 1):
        yr = px[px.index.year == Y - 1]
        asof_cache[Y] = yr.index[-1] if len(yr) else None
    pool = [c for c in px.columns if c not in EXCLUDE and c not in def_list]

    # 组合实现波动(用于 vol-target): 用 SPY 滚动波动作为 Beta~1 代理
    rets = px[bench].pct_change().fillna(0)
    roll_vol = rets.rolling(20).std() * np.sqrt(52)   # 年化

    nav = pd.Series(10000.0, index=dates)
    held = {}            # 当前持仓权重(已投资部分, 现金=c 隐含)
    basis = {}           # 逐标的成本基准价
    weights = None
    nav0 = 10000.0
    nav_peak = 10000.0   # 策略自身净值峰值(用于 self 模式闸)
    for t in range(1, len(dates)):
        band = band_map.iloc[t]; wc = wc_map.iloc[t]
        d = dev.iloc[t]
        if pd.isna(d) or pd.isna(ma20.iloc[t]):
            regime = 'flat'
        elif d < -band:
            regime = 'weak'
        elif d > band:
            regime = 'strong'
        else:
            regime = 'flat'
        dd, oo, cc = alloc[regime]
        avail = {s for s in px.columns if pd.notna(px[s].iloc[t])}
        ts = {}
        if regime == 'weak' and wc >= 1.0:
            ts[CONV] = oo
        else:
            ao = dates[t - 1] if asof_mode == 'week' else asof_cache[dates[t].year]
            if ao is None: ao = dates[t - 1]
            off = offense_dynamic(px, off_n, dates[t].year, avail, ao, window=window,
                                  phase_tilt=phase_tilt, pool=pool)
            if len(off) < off_n:
                off = (off + pool)[:off_n]
            ob = oo * (wc if regime == 'weak' else 0.0)
            if ob > 0: ts[CONV] = ob
            oe = oo - ob
            if oe > 0:
                wt = ua.offense_weights_for_year(dates[t].year, valid=avail, mode='stock_sum') or {}
                cn = off[:core]; sn = off[core:]
                cwt = sum(wt.get(s, 0) for s in cn) or 1.0
                for s in cn:
                    if pd.notna(px[s].iloc[t]) and pd.notna(px[s].iloc[t - 1]):
                        ts[s] = oe * core_share * wt.get(s, 0) / cwt
                for s in sn:
                    if pd.notna(px[s].iloc[t]) and pd.notna(px[s].iloc[t - 1]):
                        ts[s] = oe * (1 - core_share) / max(1, len(sn))
        for s in def_list: ts[s] = dd / len(def_list)

        # ---- vol-target 叠加: 超额波动转 CWB ----
        if vol_target is not None and t >= 20:
            v = roll_vol.iloc[t]
            if pd.notna(v) and v > vol_target:
                scale = vol_target / v
                scale = min(max(scale, 0.0), 1.0)
                # 把进攻+防御的 equity 部分按比例缩, 差额进 CWB
                eq_keys = [k for k in ts if k != CONV]
                moved = 0.0
                for k in eq_keys:
                    mv = ts[k] * (1 - scale)
                    ts[k] -= mv; moved += mv
                ts[CONV] = ts.get(CONV, 0.0) + moved

        # ---- P1-a 崩盘闸: SPY 破长期均线 / 较高点深回撤 -> 股票仓等比缩到 floor, 差额转 CWB ----
        guard_state = 0   # 0=on, 1=ma下或回撤触发, 2=深层破位
        if crash_guard is not None:
            mode = crash_guard.get('mode', 'ma')
            floor_now = 1.0
            if mode == 'ma':
                if t >= crash_guard['ma']:
                    spy_p = px[bench].iloc[t - 1]; mlong = ma_long.iloc[t - 1]
                    if pd.notna(mlong) and mlong > 0:
                        deep = crash_guard.get('deep', 0.0)
                        if spy_p < (1 - deep) * mlong:
                            floor_now, guard_state = 0.0, 2
                        elif spy_p < mlong:
                            floor_now, guard_state = crash_guard['floor'], 1
            else:  # 'dd': SPY 较 lookback 周高点回撤超 thr 触发
                lb = crash_guard.get('lookback', 52)
                thr = crash_guard.get('thr', -0.20)
                deep = crash_guard.get('deep', 0.0)
                lo = max(0, t - 1 - lb)
                peak = px[bench].iloc[lo:t].max()
                spy_p = px[bench].iloc[t - 1]
                if peak > 0:
                    dd_s = spy_p / peak - 1
                    if deep and dd_s < -abs(deep):
                        floor_now, guard_state = 0.0, 2
                    elif dd_s < thr:
                        floor_now, guard_state = crash_guard['floor'], 1
            if mode == 'self':  # 盯策略自身净值回撤(贴合成长股集中风险)
                thr = crash_guard.get('thr', -0.15)
                deep = crash_guard.get('deep', 0.0)
                nv = nav.iloc[t - 1]
                if nav_peak > 0:
                    dd_n = nv / nav_peak - 1
                    if deep and dd_n < -abs(deep):
                        floor_now, guard_state = 0.0, 2
                    elif dd_n < thr:
                        floor_now, guard_state = crash_guard['floor'], 1
            if floor_now < 1.0:
                eq_keys = [k for k in ts if k != CONV]
                eq_total = sum(ts[k] for k in eq_keys)
                if eq_total > 0:
                    new_eq = eq_total * floor_now
                    moved = eq_total - new_eq
                    for k in eq_keys:
                        ts[k] *= (new_eq / eq_total)
                    ts[CONV] = ts.get(CONV, 0.0) + moved

        # ---- 成本/税务: 基于 held -> ts 的换手 ----
        cost = 0.0; tax = 0.0
        if cost_bps > 0 or tax_rate > 0:
            alls = set(held) | set(ts)
            oneway = 0.0
            for s in alls:
                old = held.get(s, 0.0); new = ts.get(s, 0.0)
                oneway += abs(new - old) / 2.0
                if tax_rate > 0 and new < old and old > 0:
                    p_now = px[s].iloc[t - 1]
                    b0 = basis.get(s, 0.0)
                    if b0 > 0 and p_now > 0:
                        gain = max(0.0, p_now / b0 - 1.0)
                        tax += (old - new) * gain
                # 更新成本基准
                if new > old:
                    p_now = px[s].iloc[t - 1]
                    if old > 0 and basis.get(s, 0.0) > 0:
                        basis[s] = (old * basis[s] + (new - old) * p_now) / new
                    else:
                        basis[s] = p_now
                elif new <= 0:
                    basis.pop(s, None)
            cost = oneway * cost_bps
            tax = tax * tax_rate

        # ---- 用 held(再平衡前) 跑本周收益 ----
        ret = 1.0
        for s, w in held.items():
            if w <= 0: continue
            p0 = px[s].iloc[t - 1]; p1 = px[s].iloc[t]
            if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                ret += w * ((p1 / p0) - 1)
        nav.iloc[t] = nav0 * ret - nav0 * (cost + tax)
        nav0 = nav.iloc[t]
        nav_peak = max(nav_peak, nav.iloc[t])
        held = dict(ts)

    m = nav.iloc[-1] / 10000
    y = (dates[-1] - dates[0]).days / 365.25
    mdd = ((nav - nav.cummax()) / nav.cummax()).min()
    # 最大单周回撤(崩盘周)
    wk_ret = nav.pct_change().min()
    return dict(label=label, multiple=m, cagr=m ** (1 / y) - 1, mdd=mdd, wk_ret=wk_ret,
                nav=nav, vol_target=vol_target, cost_bps=cost_bps, tax_rate=tax_rate)

def const_map(px, val):
    return pd.Series(val, index=px.index)

# ---------- walk-forward: 每年初用过去3年定 (band, weak_clear) ----------
def decide_wf(px, year, grid, cost_bps, tax_rate, **kw):
    """在 [year-3, year-1] 训练窗上, 选使倍数最大的 (band, wc)。"""
    mask = (px.index.year >= year - 3) & (px.index.year <= year - 1)
    sub = px[mask]
    if len(sub) < 104:   # 不足2年, 退回默认
        return (0.05, 0.0)
    best = None; best_m = -1
    for band, wc in grid:
        bm = const_map(sub, band); wcm = const_map(sub, wc)
        r = run_ext(sub, bm, wcm, cost_bps=cost_bps, tax_rate=tax_rate, label='_wf', **kw)
        if r['multiple'] > best_m:
            best_m = r['multiple']; best = (band, wc)
    return best

def run_walkforward(px, grid, cost_bps=0.0, tax_rate=0.0, **kw):
    years = sorted(set(px.index.year))
    band_map = {}; wc_map = {}
    default = (0.05, 0.0)
    # 暖身期(前3年)用默认; 之后逐年决策
    for Y in years:
        if Y < years[0] + 3:
            band_map[Y] = default[0]; wc_map[Y] = default[1]
        else:
            bd, wd = decide_wf(px, Y, grid, cost_bps, tax_rate, **kw)
            band_map[Y] = bd; wc_map[Y] = wd
    bm = pd.Series([band_map[y] for y in px.index.year], index=px.index)
    wcm = pd.Series([wc_map[y] for y in px.index.year], index=px.index)
    r = run_ext(px, bm, wcm, cost_bps=cost_bps, tax_rate=tax_rate, label='walk-forward OOS', **kw)
    # 记录各年采用参数(诊断)
    diag = pd.DataFrame({'year': years,
                         'band%': [int(band_map[y]*100) for y in years],
                         'wc': [wc_map[y] for y in years]})
    return r, diag

def spy_stats(px, start=None, end=None):
    s = px['SPY']
    if start is not None: s = s[s.index >= start]
    if end is not None: s = s[s.index <= end]
    m = s.iloc[-1] / s.iloc[0]; y = (s.index[-1]-s.index[0]).days/365.25
    mdd = ((s - s.cummax())/s.cummax()).min()
    return m, m**(1/y)-1, mdd

if __name__ == '__main__':
    px = load_us50()
    y_all = (px.index[-1]-px.index[0]).days/365.25
    # 可复现基准: 报告引用配置 band4% / wc=0 / year (原引擎实测 50.44x, 非报告旧值58.39x)
    BAND0, WC0 = 0.04, 0.0
    print(f"=== P0 硬化: US50 ({px.index[0].date()}~{px.index[-1].date()}, {y_all:.1f}年) ===")
    print(f"可复现基准 = 报告引用配置 band4%/wc=0/year (当前引擎=50.4x, 旧报告58.39x已不可复现)\n")

    grid = [(0.04, 0.0), (0.05, 0.0), (0.06, 0.0),
            (0.04, 0.5), (0.05, 0.5), (0.06, 0.5),
            (0.04, 1.0), (0.05, 1.0), (0.06, 1.0)]

    # ---- P0-1: 成本/税务建模 ----
    print("【P0-1 成本/税务】 band4% / wc=0 (year)")
    print(f"{'scenario':<30}{'mult':>9}{'CAGR':>8}{'MDD':>9}")
    print('-'*56)
    base_bm = const_map(px, BAND0); base_wcm = const_map(px, WC0)
    scenarios = [
        ('no-cost (baseline)', 0.0, 0.0),
        ('cost 10bps / tax-exempt', 0.001, 0.0),
        ('cost 20bps / tax-exempt', 0.002, 0.0),
        ('cost 10bps / taxable20%', 0.001, 0.20),
        ('cost 20bps / taxable20%', 0.002, 0.20),
    ]
    sc_navs = {}
    for name, cps, tr in scenarios:
        r = run_ext(px, base_bm, base_wcm, cost_bps=cps, tax_rate=tr, label=name)
        sc_navs[name] = r['nav']
        print(f"{name:<30}{r['multiple']:>8.2f}x{r['cagr']*100:>7.1f}%{r['mdd']*100:>8.1f}%")
    m0 = run_ext(px, base_bm, base_wcm, 0, 0)['multiple']
    mc = run_ext(px, base_bm, base_wcm, 0.002, 0.0)['multiple']
    mt = run_ext(px, base_bm, base_wcm, 0.002, 0.20)['multiple']
    spy_m, spy_c, spy_d = spy_stats(px)
    print(f"{'SPY buyhold':<30}{spy_m:>8.2f}x{spy_c*100:>7.1f}%{spy_d*100:>8.1f}%")
    print(f"  -> 税优账户成本侵蚀: {m0/mc-1:.1%} | 应税账户税+本侵蚀: {m0/mt-1:.1%} (周频再平衡税务低效)")

    # ---- ex-ante 诚实下界也上成本 ----
    print("\n【P0-1b ex-ante (zero-hindsight) basket, with cost】 honest floor")
    ex = load_exante()
    r_ex0 = run_ext(ex, base_bm, base_wcm, 0.0, 0.0)
    r_ex1 = run_ext(ex, base_bm, base_wcm, 0.002, 0.0)
    print(f"  ex-ante no-cost: {r_ex0['multiple']:.2f}x | +cost20bps: {r_ex1['multiple']:.2f}x | SPY {spy_m:.2f}x")

    # ---- P0-2: walk-forward OOS ----
    print("\n【P0-2 walk-forward OOS】 each Jan use prior-3yr to pick (band,wc), trade that year (no hindsight)")
    r_wf, diag = run_walkforward(px, grid, cost_bps=0.0, tax_rate=0.0)
    print(diag.to_string(index=False))
    print(f"  walk-forward OOS: {r_wf['multiple']:.2f}x | CAGR {r_wf['cagr']*100:.1f}% | MDD {r_wf['mdd']*100:.1f}%")
    print(f"  (vs in-sample {m0:.1f}x / ex-ante {r_ex0['multiple']:.1f}x / SPY {spy_m:.1f}x)")
    r_wfc, _ = run_walkforward(px, grid, cost_bps=0.002, tax_rate=0.0)
    print(f"  walk-forward OOS + cost20bps: {r_wfc['multiple']:.2f}x | MDD {r_wfc['mdd']*100:.1f}%")

    # ---- P0-3: 回撤韧性 ----
    print("\n【P0-3 drawdown resilience】 band4% fixed, sweep weak->defense + vol-target (no cost)")
    print(f"{'config':<32}{'mult':>9}{'CAGR':>8}{'MDD':>9}{'worstWk':>9}")
    print('-'*59)
    dd_navs = {}
    variants = [
        ('wc=0 (US light defense, current)', 0.0, None),
        ('wc=0.5 (weak half->CWB)', 0.5, None),
        ('wc=1.0 (A-share full clear)', 1.0, None),
        ('vol-target 18%', 0.0, 0.18),
        ('vol-target 15%', 0.0, 0.15),
        ('wc=0.5 + vol15%', 0.5, 0.15),
    ]
    for name, wc, vt in variants:
        r = run_ext(px, base_bm, const_map(px, wc), cost_bps=0.0, tax_rate=0.0, vol_target=vt, label=name)
        dd_navs[name] = r['nav']
        print(f"{name:<32}{r['multiple']:>8.2f}x{r['cagr']*100:>7.1f}%{r['mdd']*100:>8.1f}%{r['wk_ret']*100:>8.1f}%")
    print(f"{'SPY buyhold':<32}{spy_m:>8.2f}x{spy_c*100:>7.1f}%{spy_d*100:>8.1f}%")

    # ---- 绘图 (ASCII labels 避免中文字体缺失) ----
    os.makedirs(os.path.join(HERE, 'figs'), exist_ok=True)
    plt.figure(figsize=(9,5))
    for name, nav in sc_navs.items():
        plt.plot(nav.index, nav/10000, label=name, lw=1.2)
    plt.plot(px.index, px['SPY']/px['SPY'].iloc[0], 'k--', lw=1.4, label='SPY')
    plt.yscale('log'); plt.title('P0-1 Cost/Tax (US50)'); plt.legend(fontsize=8); plt.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(os.path.join(HERE,'figs','p0_cost.png'), dpi=130); plt.close()

    plt.figure(figsize=(9,5))
    plt.plot(r_wf['nav'].index, r_wf['nav']/10000, 'g-', lw=1.6, label=f'walk-forward OOS {r_wf["multiple"]:.1f}x')
    plt.plot(sc_navs['no-cost (baseline)'].index, sc_navs['no-cost (baseline)']/10000, 'b-', lw=1.2, label=f'in-sample {m0:.1f}x')
    plt.plot(px.index, px['SPY']/px['SPY'].iloc[0], 'k--', lw=1.4, label='SPY')
    plt.yscale('log'); plt.title('P0-2 Walk-forward vs In-sample'); plt.legend(fontsize=8); plt.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(os.path.join(HERE,'figs','p0_walkforward.png'), dpi=130); plt.close()

    plt.figure(figsize=(9,5))
    cmap = plt.cm.viridis(np.linspace(0,1,len(dd_navs)))
    for (name,nav),c in zip(dd_navs.items(), cmap):
        plt.plot(nav.index, nav/10000, color=c, lw=1.3, label=f'{name} {nav.iloc[-1]/10000:.1f}x')
    plt.plot(px.index, px['SPY']/px['SPY'].iloc[0], 'k--', lw=1.4, label='SPY')
    plt.yscale('log'); plt.title('P0-3 Drawdown Resilience'); plt.legend(fontsize=7); plt.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(os.path.join(HERE,'figs','p0_drawdown.png'), dpi=130); plt.close()

    print('\nsaved figs: p0_cost.png, p0_walkforward.png, p0_drawdown.png')
