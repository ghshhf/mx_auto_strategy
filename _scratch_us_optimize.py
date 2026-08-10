import numpy as np, pandas as pd, sys, os, copy, time
sys.path.insert(0, 'us_stocks'); sys.path.insert(0, '.')
import us_backtest_ai as U

PANEL = r'E:/项目改变/mx_auto_strategy/us_stocks/data/weekly_adjclose_full_ext.csv'
dates, series = U.load_panel(PANEL)
us_cfg = U.load_us_cfg()
W = len(dates) - 1

def run(opt_over=None, cfg_over=None, use_ai=False):
    opt = dict(us_cfg['options_sim'])
    if opt_over: opt.update(opt_over)
    cfg = copy.deepcopy(us_cfg)
    if cfg_over: cfg.update(cfg_over)
    nav, st = U.run_optimized(series, dates, use_ai=use_ai, cfg=cfg,
                              theme_div=True, max_per_theme=2, us_cfg=cfg,
                              options_sim=opt)
    m = st['multiple']; cagr = m ** (52 / W) - 1
    return dict(mult=m, cagr=cagr * 100, mdd=st['mdd'] * 100,
                onet=st['options_net'] * 100, cp=st['call_premium'] * 100,
                pc=st['put_cost'] * 100, ph=st['put_hedge'] * 100,
                sp=st['short_pnl'] * 100)

BASE = {'stock_put_enabled': False}  # 新配置(个股只做卖出期权)

print('=== ① 直接对照: 关掉个股put后, 收益是否更高? ===')
r_on = run({'stock_put_enabled': True})
r_off = run(BASE)
print('  个股put ON  (旧): %.2fx | CAGR %.1f%% | MDD %.1f%% | 期权净%.1f%%' % (r_on['mult'], r_on['cagr'], r_on['mdd'], r_on['onet']))
print('  个股put OFF (新): %.2fx | CAGR %.1f%% | MDD %.1f%% | 期权净%.1f%%' % (r_off['mult'], r_off['cagr'], r_off['mdd'], r_off['onet']))
print('  >> 关个股put: %.2fx -> %.2fx (%+.1f%%)  [注: 反降, 个股put在公允价下是净正贡献]' % (r_on['mult'], r_off['mult'], (r_off['mult']/r_on['mult']-1)*100))

print()
print('=== ② short_underlying 消融 (疑点: 注释称TECH胜, 但列QQQ=123x) ===')
for su in ['TECH_INDEX', 'QQQ', 'SPY', 'SOX']:
    r = run({**BASE, 'short_underlying': su})
    print('  %-12s %.2fx | CAGR %.1f%% | MDD %.1f%% | 做空%.1f%% | 期权净%.1f%%' % (su, r['mult'], r['cagr'], r['mdd'], r['sp'], r['onet']))

print()
print('=== ③ short_by_sector (按行业精准空 vs 固定TECH) ===')
for sbs in [False, True]:
    r = run({**BASE, 'short_by_sector': sbs})
    print('  short_by_sector=%-5s %.2fx | CAGR %.1f%% | MDD %.1f%% | 做空%.1f%%' % (sbs, r['mult'], r['cagr'], r['mdd'], r['sp']))

print()
print('=== ④ put_hedge_ratio (大盘put赔付率, 当前0.5) ===')
for hr in [0.5, 1.0]:
    r = run({**BASE, 'put_hedge_ratio': hr})
    print('  hedge=%.1f %.2fx | CAGR %.1f%% | MDD %.1f%% | put对冲+%.1f%%' % (hr, r['mult'], r['cagr'], r['mdd'], r['ph']))

print()
print('=== ⑤ take_profit_pct (covered call行权价=止盈, 当前0.5) ===')
for tp in [0.3, 0.7]:
    r = run(BASE, cfg_over={'take_profit_pct': tp})
    print('  tp=%.1f  %.2fx | CAGR %.1f%% | MDD %.1f%% | call权+%.1f%%' % (tp, r['mult'], r['cagr'], r['mdd'], r['cp']))

print()
print('=== ⑥ short_size_ratio / short_dte (做空仓位与持有期) ===')
for sz in [0.7, 1.0]:
    r = run({**BASE, 'short_size_ratio': sz})
    print('  sz=%.1f %.2fx | CAGR %.1f%% | MDD %.1f%% | 做空%.1f%%' % (sz, r['mult'], r['cagr'], r['mdd'], r['sp']))
for dte in [26, 52]:
    r = run({**BASE, 'short_dte_weeks': dte})
    print('  dte=%2d %.2fx | CAGR %.1f%% | MDD %.1f%% | 做空%.1f%%' % (dte, r['mult'], r['cagr'], r['mdd'], r['sp']))
print()
print('DONE')
