"""
generate_final_curve.py - V5.1 最终收益曲线图
=============================================
生成 V5.1 在 V2(理想) vs V3(真实摩擦+滑点) 上的 10 年收益对比曲线
"""
import pandas as pd
import numpy as np
import os, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
FIGS = os.path.join(HERE, 'figs')
os.makedirs(FIGS, exist_ok=True)

sys.path.insert(0, HERE)
import backtest_v2 as bt
import crypto_adoption_v2 as ca2


def main():
    # 加载数据
    v2 = bt.load_crypto50()
    v3 = pd.read_csv(os.path.join(DATA, 'weekly_adjclose_crypto50_v3.csv'),
                     index_col=0, parse_dates=True).sort_index()

    # V5.1 回测
    r_v2 = bt.run_backtest(v2, label='V5.1 理想数据')
    r_v3 = bt.run_backtest(v3, label='V5.1 真实摩擦')
    r_slip = bt.run_backtest(v3, cost_bps=0.0012, label='V5.1 真实+滑点12bps')

    # BTC benchmark
    r_btc = bt.btc_buyhold(v2)

    # ===== 1. 主收益曲线 (log scale) =====
    fig, ax = plt.subplots(figsize=(14, 7))

    navs = [
        (r_btc['nav'], f"BTC Buy&Hold ({r_btc['multiple']:.0f}x)", '#888888', '--', 1.2),
        (r_v2['nav'], f"V5.1 理想 ({r_v2['multiple']:.0f}x, MDD {r_v2['mdd']*100:.0f}%)", '#2196f3', '-', 2.0),
        (r_v3['nav'], f"V5.1 真实摩擦 ({r_v3['multiple']:.0f}x, MDD {r_v3['mdd']*100:.0f}%)", '#4caf50', '-', 2.0),
        (r_slip['nav'], f"V5.1 真实+滑点 ({r_slip['multiple']:.0f}x, MDD {r_slip['mdd']*100:.0f}%)", '#ff9800', '-', 2.0),
    ]

    for nav, label, color, ls, lw in navs:
        nv = nav / nav.iloc[0]
        ax.plot(nv.index, nv.values, label=label, color=color, linestyle=ls, lw=lw)

    ax.set_yscale('log')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:,.0f}x'))
    ax.set_title('V5.1 Crypto Strategy — 10 Year NAV (1万起步)', fontsize=14, fontweight='bold')
    ax.set_xlabel('Date', fontsize=11)
    ax.set_ylabel('NAV (log scale)', fontsize=11)
    ax.legend(fontsize=9, loc='upper left', framealpha=0.9)
    ax.grid(alpha=0.3, which='both')
    ax.axhline(y=1, color='black', linestyle=':', alpha=0.3)

    # 标注关键事件
    events = [
        ('2017-12', '2017 牛市顶'),
        ('2020-03', '312 暴跌'),
        ('2021-11', '2021 牛市顶'),
        ('2022-11', 'FTX 暴雷'),
        ('2024-03', 'BTC ETF'),
    ]
    for date_str, text in events:
        try:
            dt = pd.Timestamp(date_str)
            ax.axvline(x=dt, color='red', alpha=0.15, linestyle=':')
        except:
            pass

    plt.tight_layout()
    out1 = os.path.join(FIGS, 'v51_final_nav.png')
    plt.savefig(out1, dpi=150)
    plt.close()
    print(f"  fig: {out1}")

    # ===== 2. 回撤曲线 =====
    fig, ax = plt.subplots(figsize=(14, 4))

    for nav, label, color in [
        (r_v2['nav'], 'V5.1 理想', '#2196f3'),
        (r_v3['nav'], 'V5.1 真实摩擦', '#4caf50'),
        (r_slip['nav'], 'V5.1 真实+滑点', '#ff9800'),
    ]:
        dd = (nav - nav.cummax()) / nav.cummax() * 100
        ax.plot(dd.index, dd.values, label=label, color=color, lw=1.5, alpha=0.8)
        ax.fill_between(dd.index, dd.values, 0, alpha=0.1, color=color)

    ax.set_title('V5.1 Drawdown — 回撤控制', fontsize=13, fontweight='bold')
    ax.set_xlabel('Date', fontsize=11)
    ax.set_ylabel('Drawdown (%)', fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    ax.axhline(y=-15, color='red', linestyle=':', alpha=0.5, label='Crash Guard -15%')

    plt.tight_layout()
    out2 = os.path.join(FIGS, 'v51_final_drawdown.png')
    plt.savefig(out2, dpi=150)
    plt.close()
    print(f"  fig: {out2}")

    # ===== 3. Walk-Forward 验证曲线 =====
    train = v3[v3.index <= '2020-12-31']
    test = v3[v3.index > '2020-12-31']

    r_tr = bt.run_backtest(train, cost_bps=0.0012, label='Train 2016-2020')
    r_te = bt.run_backtest(test, cost_bps=0.0012, label='Test 2021-2025')

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8))

    # Train
    nv = r_tr['nav'] / r_tr['nav'].iloc[0]
    ax1.plot(nv.index, nv.values, 'b-', lw=2)
    ax1.set_title(f'Train Period (2016-2020): {r_tr["multiple"]:.0f}x | MDD {r_tr["mdd"]*100:.1f}% | Sharpe {r_tr.get("sharpe",0):.2f}',
                  fontsize=12, fontweight='bold')
    ax1.set_ylabel('NAV (x)', fontsize=11)
    ax1.legend([f'V5.1 Train ({r_tr["multiple"]:.0f}x)'], fontsize=10)
    ax1.grid(alpha=0.3)
    ax1.set_yscale('log')

    # Test
    nv = r_te['nav'] / r_te['nav'].iloc[0]
    ax2.plot(nv.index, nv.values, 'g-', lw=2)
    ax2.set_title(f'Test Period (2021-2025): {r_te["multiple"]:.0f}x | MDD {r_te["mdd"]*100:.1f}% | Sharpe {r_te.get("sharpe",0):.2f}',
                  fontsize=12, fontweight='bold')
    ax2.set_xlabel('Date', fontsize=11)
    ax2.set_ylabel('NAV (x)', fontsize=11)
    ax2.legend([f'V5.1 Test ({r_te["multiple"]:.0f}x)'], fontsize=10)
    ax2.grid(alpha=0.3)
    ax2.set_yscale('log')

    plt.tight_layout()
    out3 = os.path.join(FIGS, 'v51_final_walkforward.png')
    plt.savefig(out3, dpi=150)
    plt.close()
    print(f"  fig: {out3}")

    # ===== 打印结果 =====
    print(f"\n{'='*70}")
    print(f"  V5.1 最终结果 (1万起步, 10年)")
    print(f"{'='*70}")
    print(f"  {'场景':<25}{'收益':>12}{'MDD':>10}{'Sharpe':>10}")
    print(f"  {'-'*55}")
    for r in [r_btc, r_v2, r_v3, r_slip]:
        money = r['multiple'] * 10000
        print(f"  {r['label']:<25}{money:>12,.0f}元{r['mdd']*100:>9.1f}%{r.get('sharpe',0):>9.2f}")
    print(f"\n  Walk-Forward (滑点12bps):")
    print(f"    Train: {r_tr['multiple']*10000:,.0f}元 (Sharpe {r_tr.get('sharpe',0):.2f})")
    print(f"    Test:  {r_te['multiple']*10000:,.0f}元 (Sharpe {r_te.get('sharpe',0):.2f})")
    print(f"\n  图表: {FIGS}/")


if __name__ == '__main__':
    main()
