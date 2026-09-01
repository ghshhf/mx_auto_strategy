"""
backtest_p1.py - P1-a 崩盘保护: 趋势闸(双模式)
==============================================
用户拍板: 篮子问题不是问题(选最大/最新/最热=前向明显), 直接做崩盘保护。
实现 run_ext(crash_guard=...):
  mode='ma' : SPY 收 < ma周均线 -> 股票仓缩到 floor, 差额转 CWB; 深层破位(1-deep)清空。
              (用户原话"破200周MA"; 但2020-2026牛市 SPY 从未跌破200周MA -> 窗口内测不到, 仅外推)
  mode='dd' : SPY 较 lookback 周高点回撤 > thr(-20%熊市标准) -> 减仓。窗口内会触发(2022), 可实测。
验证:
  1) 减仓档位扫描 -> MDD/收益/风险关闭时长
  2) 实盘崩盘窗口(COVID/2022)有闸 vs 无闸
  3) -70% 系统性崩盘外推(用 CWB 实测 beta)
"""
import pandas as pd, numpy as np, os
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
HERE = os.path.dirname(__file__); DATA = os.path.join(HERE, 'data')
import backtest_p0 as P

def main():
    px = P.load_us50()
    bm = P.const_map(px, 0.04); wcm = P.const_map(px, 0.0)
    spy_m, spy_c, spy_d = P.spy_stats(px)
    print(f"=== P1-a 崩盘保护 (US50, band4%/wc=0/year) ===\n")

    # 1) 减仓档位扫描 (两种模式)
    print("【减仓档位】 floor=风险关时股票仓保留比例")
    print(f"{'config':<34}{'mult':>9}{'CAGR':>8}{'MDD':>9}{'worstWk':>9}{'riskOff%':>9}")
    print('-'*70)
    variants = [
        ('无闸 (baseline)', None),
        ('MA200 floor=0.35', {'mode':'ma','ma':200,'floor':0.35,'deep':0.20}),
        ('DD(-20%) floor=0.35', {'mode':'dd','lookback':52,'thr':-0.20,'floor':0.35}),
        ('self(-15%) floor=0.50', {'mode':'self','thr':-0.15,'floor':0.50}),
        ('self(-15%) floor=0.35', {'mode':'self','thr':-0.15,'floor':0.35}),
        ('self(-20%) floor=0.35', {'mode':'self','thr':-0.20,'floor':0.35}),
    ]
    res = {}
    for name, cg in variants:
        r = P.run_ext(px, bm, wcm, cost_bps=0.0, tax_rate=0.0, crash_guard=cg, label=name)
        roff = 0.0
        if cg is not None and cg['mode'] in ('ma', 'dd'):
            bench = px['SPY']
            if cg['mode'] == 'ma':
                mlong = bench.rolling(cg['ma']).mean(); deep = cg.get('deep',0.0)
                off = ((bench < mlong) | (bench < (1-deep)*mlong)).where(mlong.notna(), False)
            else:
                lb=cg['lookback']; thr=cg['thr']
                peak = bench.rolling(lb).max(); dd = bench/peak - 1
                off = (dd < thr).fillna(False)
            roff = off.mean()*100
        elif cg is not None:
            roff = float('nan')   # self 模式 riskOff 由 run_ext 内部决定, 此处不重算
        res[name] = r
        roff_s = f"{roff:>8.1f}%" if not (isinstance(roff,float) and np.isnan(roff)) else f"{'n/a':>8}"
        print(f"{name:<34}{r['multiple']:>8.2f}x{r['cagr']*100:>7.1f}%{r['mdd']*100:>8.1f}%{r['wk_ret']*100:>8.1f}%{roff_s}")
    print(f"{'SPY buyhold':<34}{spy_m:>8.2f}x{spy_c*100:>7.1f}%{spy_d*100:>8.1f}%")

    # 2) 实盘崩盘窗口对比 (用 DD 模式, 会触发)
    print("\n【实盘崩盘窗口】 有闸(DD-20% floor0.35) vs 无闸")
    rg = res['DD(-20%) floor=0.35']; nav_n, nav_g, spy = res['无闸 (baseline)']['nav'], rg['nav'], px['SPY']
    def dd_in(nav, s, e):
        x = nav[(nav.index>=s)&(nav.index<=e)]; return (x/x.cummax()-1).min()*100
    def dd_spy(s,e):
        x = spy[(spy.index>=s)&(spy.index<=e)]; return (x/x.cummax()-1).min()*100
    print(f"{'window':<12}{'SPY_DD':>9}{'无闸_DD':>9}{'有闸_DD':>9}{'减亏':>9}")
    print('-'*48)
    for n,s,e in [('COVID','2020-02-19','2020-03-23'),('2022 bear','2022-01-03','2022-10-12')]:
        sd=dd_spy(s,e); nn=dd_in(nav_n,s,e); gg=dd_in(nav_g,s,e)
        print(f"{n:<12}{sd:>8.1f}%{nn:>8.1f}%{gg:>8.1f}%{(nn-gg):>8.1f}%")

    # 3) -70% 崩盘外推
    print("\n【-70% 系统性崩盘外推】 (CWB 实测 beta 假设)")
    cwb_ret = px['CWB'].pct_change().fillna(0); sr = px['SPY'].pct_change().fillna(0)
    cwb_beta = np.cov(cwb_ret, sr)[0,1]/np.var(sr)
    strat_beta = np.cov(nav_n.pct_change().fillna(0), sr)[0,1]/np.var(sr)
    print(f"  策略全仓 beta(SPY)= {strat_beta:.2f} | CWB beta(SPY)= {cwb_beta:.2f}")
    print(f"  无闸: 若 SPY -70% -> 策略≈ {strat_beta*70:.0f}%")
    for fl in (0.50, 0.35, 0.0):
        eff = fl*strat_beta + (1-fl)*cwb_beta
        print(f"  有闸 floor={fl}: 风险关时组合 beta≈ {eff:.2f} -> SPY -70% 策略≈ {eff*70:.0f}%")
    print("  注: 简化线性外推; 真实崩盘闸滞后触发(先吃一小段), 但关后组合以 CWB 为主, 损失远小于无闸。")

    # 绘图
    os.makedirs(os.path.join(HERE,'figs'), exist_ok=True)
    fig, ax = plt.subplots(figsize=(10,5.5))
    ax.plot(nav_n.index, nav_n/10000, 'b-', lw=1.2, label=f'no guard {nav_n.iloc[-1]/10000:.0f}x')
    ax.plot(nav_g.index, nav_g/10000, 'g-', lw=1.5, label=f'crash guard(DD) {nav_g.iloc[-1]/10000:.0f}x')
    ax.plot(spy.index, spy/spy.iloc[0], 'k--', lw=1.3, label='SPY')
    bench=px['SPY']; peak=bench.rolling(52).max(); dd=bench/peak-1
    off = (dd < -0.20).fillna(False)
    for idx in px.index[off]:
        ax.axvline(idx, color='red', alpha=0.05, lw=0.5)
    ax.set_yscale('log'); ax.set_title('P1-a Crash Guard (DD-20% de-risk, red=risk-off)')
    ax.legend(fontsize=8); ax.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(os.path.join(HERE,'figs','p1_crashguard.png'), dpi=130); plt.close()
    print('\nsaved figs/p1_crashguard.png')

if __name__ == '__main__':
    main()
