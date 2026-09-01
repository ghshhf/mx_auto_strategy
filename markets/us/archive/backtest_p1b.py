"""
backtest_p1b.py - 网格层叠加: 在主策略 NAV 上叠加波动率 Harvest 网格
==============================================================
原始 mx_auto_strategy/grid_trader.py: 用 16% 现金弹药池, 对高波动进攻票做隔日网格
(格距≈近10日波动率0.8倍, 5层, 价格低于中心买一层/高于中心卖一层, 吃差价)。
但它是日频(依赖实时价/涨跌停), 而 US 回测是周频 -> 这里用周频近似还原网格的"赚差价"机制:
  - 弹药池 = 组合闲置现金(alloc 的 c 部分, 约 5~16%), 不参与主仓位
  - 格距 step = clamp(0.8 * 近2周σ, 2%, 6%)
  - 5 层; 价格低于中心 every step 买一层, 高于中心卖一层(实现差价)
  - 全部清仓且价在中心上方时重置中心(让网格能骑趋势)
验证: 网格 standalone 10年倍数 + 叠加到主策略(self闸47x / 无闸50x)后的总倍数。
"""
import pandas as pd, numpy as np, os
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
HERE = os.path.dirname(__file__); DATA = os.path.join(HERE, 'data')
import backtest_p0 as P

def simulate_grid(px, basket, ammo=1.0, layers=5, rebalance='year'):
    """对 basket 做等权网格, 返回网格子账户 NAV(起始 ammo) 序列。"""
    dates = px.index
    nav = pd.Series(ammo, index=dates)
    # 每标的分配弹药
    sub = {s: {'cash': ammo/len(basket), 'shares': 0.0, 'center': None, 'avg': 0.0} for s in basket}
    for t in range(1, len(dates)):
        for s in basket:
            st = sub[s]; p = px[s].iloc[t]; p0 = px[s].iloc[t-1]
            if pd.isna(p) or pd.isna(p0) or p <= 0: 
                continue
            if st['center'] is None:
                st['center'] = p
            # 近2周σ(用过去10周收益估计)
            rets = px[s].iloc[max(0,t-10):t].pct_change().dropna()
            sig = rets.std() if len(rets) > 1 else 0.03
            step = max(0.02, min(0.06, 0.8 * sig))
            dev = p / st['center'] - 1.0
            if dev <= 0:
                target = min(layers, int((-dev) // step) + (1 if (-dev) % step > 0 else 0))
            else:
                target = 0  # 高于中心: 清空(落袋差价)
            held = st['shares']
            # 当前持有层数
            held_layers = (held * st['center'] / (ammo/len(basket)/layers)) if (ammo/len(basket)/layers)>0 else 0
            held_layers = int(round(held_layers))
            delta = target - held_layers
            if delta > 0:  # 买
                cost = delta * (ammo/len(basket)/layers)
                if st['cash'] >= cost and p > 0:
                    qty = cost / p
                    st['shares'] += qty
                    # 更新均价
                    old_val = held * st['avg'] if st['avg']>0 else 0
                    st['avg'] = (old_val + cost) / (held + qty) if (held+qty)>0 else p
                    st['cash'] -= cost
            elif delta < 0:  # 卖
                sell_layers = -delta
                qty = sell_layers * (ammo/len(basket)/layers) / p
                qty = min(qty, st['shares'])
                if qty > 0:
                    proceeds = qty * p
                    st['cash'] += proceeds
                    st['shares'] -= qty
                    # 差价已实现(已在 cash 里)
                if st['shares'] <= 1e-9:  # 清空且价在中心上 -> 重置中心骑趋势
                    st['shares'] = 0.0
                    if p > st['center']:
                        st['center'] = p
        # 周末记账
        tot = sum(st['cash'] + st['shares']*px[s].iloc[t] for s,st in sub.items() if not pd.isna(px[s].iloc[t]))
        nav.iloc[t] = tot
    return nav

def main():
    px = P.load_us50()
    bm = P.const_map(px, 0.04); wcm = P.const_map(px, 0.0)
    print("=== P1-b 网格层叠加 (US50, band4%/wc=0/year) ===\n")

    # 主策略(无闸 / self闸)
    r_none = P.run_ext(px, bm, wcm, cost_bps=0, tax_rate=0, label='none')
    r_self = P.run_ext(px, bm, wcm, cost_bps=0, tax_rate=0, crash_guard={'mode':'self','thr':-0.20,'floor':0.35}, label='self')
    # 闲置现金占比(alloc c 部分, 按 regime 频率加权近似)
    idle = 0.16*0.075 + 0.05*0.80 + 0.05*0.125  # weak7.5%/flat80%/strong12.5%
    print(f"主策略无闸: {r_none['multiple']:.2f}x | self闸: {r_self['multiple']:.2f}x | 组合闲置现金≈{idle*100:.1f}%\n")

    # 网格篮子: 高波动进攻票(代表性)
    baskets = {
        '高波动5(NVDA/TSLA/PLTR/COIN/AMD)': ['NVDA','TSLA','PLTR','COIN','AMD'],
        '进攻前10': None,  # 用 run 的 offense 近似: 取动量top10
    }
    # 用动量top10近似进攻池
    off10 = P.offense_dynamic(px, 10, 2026, set(px.columns), px.index[-1], pool=[c for c in px.columns if c not in P.EXCLUDE and c not in ('KO','ABBV')])
    baskets['进攻前10'] = off10
    print(f"进攻前10(2026视角): {off10}\n")

    print(f"{'网格篮子':<34}{'网格10y倍数':>12}{'叠加无闸':>10}{'叠加self闸':>11}")
    print('-'*67)
    navs = {}
    for name, b in baskets.items():
        gnav = simulate_grid(px, b, ammo=1.0, layers=5)
        gm = gnav.iloc[-1]
        # 叠加: 主NAV + 闲置现金部署网格后的增量
        # 主NAV用满100%, 其中 idle 比例原本0收益; 改为网格 -> 增量 = idle*(网格倍数-1)*主初值
        comb_none = r_none['nav'].iloc[-1] + idle*(gm-1)*10000
        comb_self = r_self['nav'].iloc[-1] + idle*(gm-1)*10000
        navs[name] = (r_none['nav'], gnav, comb_none)
        print(f"{name:<34}{gm:>11.2f}x{comb_none/10000:>9.2f}x{comb_self/10000:>10.2f}x")
    print(f"{'SPY买持有':<34}{'':>12}{spy_stats_x(px):>10}")
    print("\n注: 网格为周频近似(原系统日频); 叠加假设网格只动用组合闲置现金, 不侵蚀主仓位。")

    # 图
    os.makedirs(os.path.join(HERE,'figs'), exist_ok=True)
    plt.figure(figsize=(10,5.5))
    plt.plot(r_none['nav'].index, r_none['nav']/10000, 'b-', lw=1.2, label=f'momentum {r_none["multiple"]:.0f}x')
    for name,(mn,gn,cb) in navs.items():
        plt.plot(gn.index, gn/1.0, 'm--', lw=1.0, label=f'grid({name}) {gn.iloc[-1]:.1f}x')
    plt.plot(r_self['nav'].index, r_self['nav']/10000, 'g-', lw=1.2, label=f'momentum+self {r_self["multiple"]:.0f}x')
    plt.yscale('log'); plt.title('P1-b Grid overlay (weekly approx)')
    plt.legend(fontsize=7); plt.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(os.path.join(HERE,'figs','p1b_grid.png'), dpi=130); plt.close()
    print('saved figs/p1b_grid.png')

def spy_stats_x(px):
    s=px['SPY']; return f"{s.iloc[-1]/s.iloc[0]:.2f}x"

if __name__ == '__main__':
    main()
