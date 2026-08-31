# -*- coding: utf-8 -*-

# --- [relocated 2026-08-31] 目录重构引导: 等效于在 crypto_stocks/ 根目录下运行 ---
import os as _os, sys as _sys
_SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))
_d = _SCRIPT_DIR
while _os.path.basename(_d) != 'crypto_stocks' and _d != _os.path.dirname(_d):
    _d = _os.path.dirname(_d)
_CS_ROOT = _d if _os.path.basename(_d) == 'crypto_stocks' else _SCRIPT_DIR
if _CS_ROOT != _SCRIPT_DIR:
    if _CS_ROOT not in _sys.path:
        _sys.path.insert(0, _CS_ROOT)
    _os.chdir(_CS_ROOT)
# --- [relocated] 引导结束 ---
"""归因: 17000x -> 24494x 到底是"数据变多"还是"参数改对"?
严格单变量拆解, 外加"时间线 vs 利好"的实证检验。
"""
import pandas as pd
import crypto_options_bt as m

px10 = pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()
px9  = pd.read_csv('data/weekly_adjclose_crypto50.csv',      index_col=0, parse_dates=True).sort_index()

# 历史各阶段的数据末日
CUTS = {
    '旧旧(2025-12-26)': '2025-12-26',
    '旧  (2026-07-24)': '2026-07-24',
    '今  (2026-08-07)': '2026-08-07',
}

def cfg_old():
    """17000x 记录时的原参数: risk_scale 0.5/0.5, ph=31"""
    c = dict(m.DEFAULT_CFG)
    c['halving_cycle_enabled'] = True
    c['halving_euphoria_risk_scale'] = 1.0
    c['halving_crash_risk_scale'] = 0.5
    c['halving_bear_bottom_risk_scale'] = 0.5
    c['pre_halving_start_month'] = 31.0
    c['short_proactive_ma'] = 0        # 当年没有主动做空
    c['short_cycle_gate'] = False
    return c

def cfg_new():
    """当前新默认"""
    return dict(m.DEFAULT_CFG)

def run(px, cfg, label):
    r = m.run_bt(px, cfg, label=label)
    return r['multiple'], r['cagr'], r['mdd'], r.get('sharpe', 0)

print('=' * 78)
print('实验一: 固定参数(旧 0.5/0.5), 只变数据末日 -> 数据增量的贡献')
print('=' * 78)
print(f"{'数据末日':<20}{'周数':>6}{'倍数':>14}{'CAGR':>9}{'MDD':>9}{'Sharpe':>8}")
base_old = None
for name, cut in CUTS.items():
    p = px10.loc[:cut]
    mu, cg, md, sh = run(p, cfg_old(), name)
    if base_old is None:
        base_old = mu
    delta = (mu / base_old - 1) * 100
    print(f'{name:<20}{len(p):>6}{mu:>13,.1f}x{cg*100:>8.1f}%{md*100:>8.1f}%{sh:>8.2f}   ({delta:+.1f}% vs 旧旧)')

print()
print('=' * 78)
print('实验二: 固定数据(今 2026-08-07), 只变参数 -> 参数改动的贡献')
print('=' * 78)
variants = {
    'a 旧参数 0.5/0.5 无做空': cfg_old(),
}
c = cfg_old(); c['halving_crash_risk_scale'] = 0.3; c['halving_bear_bottom_risk_scale'] = 0.3
variants['b 只把 0.5->0.3'] = c
c2 = dict(c); c2['short_proactive_ma'] = 20; c2['short_proactive_size'] = 0.40; c2['short_cycle_gate'] = True
variants['c 再加门控做空(=新默认)'] = c2

print(f"{'配置':<26}{'倍数':>14}{'CAGR':>9}{'MDD':>9}{'Sharpe':>8}")
prev = None
for name, cfg in variants.items():
    mu, cg, md, sh = run(px10, cfg, name)
    inc = '' if prev is None else f'   (+{(mu/prev-1)*100:.1f}%)'
    print(f'{name:<26}{mu:>13,.1f}x{cg*100:>8.1f}%{md*100:>8.1f}%{sh:>8.2f}{inc}')
    prev = mu

print()
print('=' * 78)
print('实验三: "时间线 vs 利好" — 2024 减半后各相位的实际表现')
print('=' * 78)
btc = px10['BTC'] if 'BTC' in px10.columns else px10.iloc[:, 0]
seg = btc.loc['2024-04-01':]
rows = []
for t in seg.index:
    ph, ms, mn = m.halving_cycle_phase(t, pre_halving_start_month=31.0)
    rows.append((t, ph, ms, seg.loc[t]))
df = pd.DataFrame(rows, columns=['date', 'phase', 'months', 'btc']).set_index('date')

print(f"{'相位':<16}{'区间':<26}{'周数':>5}{'BTC起':>11}{'BTC末':>11}{'涨跌':>9}{'最大回撤':>10}")
for ph in ['post_halving', 'euphoria', 'crash', 'bear_bottom']:
    sub = df[df['phase'] == ph]
    if len(sub) == 0:
        continue
    p0, p1 = sub['btc'].iloc[0], sub['btc'].iloc[-1]
    dd = (sub['btc'] / sub['btc'].cummax() - 1).min()
    rng = f"{sub.index[0].date()}~{sub.index[-1].date()}"
    print(f'{ph:<16}{rng:<26}{len(sub):>5}{p0:>11,.0f}{p1:>11,.0f}{(p1/p0-1)*100:>8.1f}%{dd*100:>9.1f}%')

# 全周期历史: 每一轮减半后 euphoria 段的涨幅
print()
print('历史各轮 euphoria 段(减半后12-18月) BTC 涨幅:')
for hd in ['2016-07-09', '2020-05-11', '2024-04-20']:
    hd = pd.Timestamp(hd)
    s = btc.loc[hd + pd.Timedelta(days=365):hd + pd.Timedelta(days=548)]
    if len(s) > 2:
        print(f'  减半 {hd.date()} -> euphoria {s.index[0].date()}~{s.index[-1].date()}: '
              f'{s.iloc[0]:,.0f} -> {s.iloc[-1]:,.0f}  ({(s.iloc[-1]/s.iloc[0]-1)*100:+.1f}%)')
