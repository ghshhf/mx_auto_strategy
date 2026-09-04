"""诊断加密回测 -57% 回撤的钱到底亏在哪，并探测防御开关效果。纯本地，无下载。"""
import sys, os, json
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crypto_adoption_v2 as ca2
from crypto_options_bt import run_bt, CryptoOptionsConfig

MAIN = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50.csv')
PANEL_10Y = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50_10y.csv')


def load(path):
    return pd.read_csv(path, index_col=0, parse_dates=True).sort_index()


def find_dd_episodes(nav_series, top=3, min_depth=0.15):
    """返回 (peak_idx, trough_idx, depth) 列表，按深度排序。"""
    nav = nav_series.values
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1.0
    episodes = []
    i = 0
    n = len(nav)
    while i < n:
        if dd[i] < -min_depth:
            start = i
            # 找到连续回撤段终点（回升到前高或回撤收窄到 -5% 内）
            j = i
            while j < n - 1 and nav[j + 1] < peak[j] * 0.95:
                j += 1
            depth = dd[start:j + 1].min()
            trough = start + int(np.argmin(nav[start:j + 1]))
            episodes.append((start, trough, j, depth))
            i = j + 1
        else:
            i += 1
    episodes.sort(key=lambda e: e[3])
    return episodes[:top]


def regime_risky_weight(regimes):
    """用 REGIME_ALLOC 估算每周风险敞口(进攻+防御占比)。"""
    out = []
    for rg in regimes:
        a = ca2.REGIME_ALLOC.get(rg, ca2.REGIME_ALLOC['flat'])
        out.append(a['defense'] + a['offense'])
    return np.array(out)


def analyze(window_label, fpath, start, cfg_dict=None):
    px = load(fpath)
    res = run_bt(px, cfg_dict=cfg_dict, label=window_label, start=start, return_recs=True)
    nav = res['nav'].values
    regimes = res['regimes']
    recs = res['recs'] or []
    print(f"  [debug] len(nav)={len(nav)} len(recs)={len(recs)} len(regimes)={len(regimes)}")
    epi = find_dd_episodes(res['nav'], top=3)
    print(f"\n{'='*78}\n[{window_label}] 总倍数={res['multiple']:.2f}x  CAGR={res['cagr']*100:.1f}%  "
          f"MDD={res['mdd']*100:.1f}%  Sharpe={res['sharpe']:.2f}")
    print(f"事件: {res['events']}")
    rkw = regime_risky_weight(regimes)
    for (s, tr, e, depth) in epi:
        seg = res['nav'].iloc[s:e + 1]
        dates = res['nav'].index
        avg_risky = rkw[s:e + 1].mean()
        # 期权/做空贡献（占期初NAV比例，累加）
        short_c = sum(recs[k].short_pnl for k in range(s, min(e, len(recs) - 1) + 1))
        put_in = sum(recs[k].put_payout_income for k in range(s, min(e, len(recs) - 1) + 1))
        put_cost = sum(recs[k].put_cost_weekly for k in range(s, min(e, len(recs) - 1) + 1))
        call_in = sum(recs[k].call_premium_income for k in range(s, min(e, len(recs) - 1) + 1))
        rg_seq = regimes[s:e + 1]
        print(f"\n  回撤段 {dates[s].date()}~{dates[tr].date()} 深度={depth*100:.1f}% "
              f"({e-s+1}周) | 段内平均风险敞口={avg_risky*100:.0f}%")
        print(f"    期权/做空贡献(占NAV累计): 做空={short_c*100:+.1f}%  保护put赔付={put_in*100:+.1f}%  "
              f"put保费=-{put_cost*100:.1f}%  call收租={call_in*100:+.1f}%")
        # 该段内 regime 分布
        from collections import Counter
        cnt = Counter(rg_seq)
        print(f"    regime分布: " + ", ".join(f"{k}={v}周" for k, v in cnt.most_common()))
    return res


def probe_defenses(window_label, fpath, start):
    """探测不同防御开关对 MDD 的影响。"""
    print(f"\n{'#'*78}\n[探针] {window_label} 防御开关扫描 (看哪个能压住 MDD)")
    configs = {
        'base(现状)': {},
        '+crash_guard': {'crash_guard': {'thr': -0.15, 'floor': 0.40}},
        '+vol_target0.6': {'vol_target': 0.60},
        '+主动做空(MA20,30%)': {'short_proactive_ma': 20, 'short_proactive_size': 0.30},
        '+减半crash减仓0.6': {'halving_crash_risk_scale': 0.6},
        '全开': {'crash_guard': {'thr': -0.15, 'floor': 0.40}, 'vol_target': 0.60,
                 'short_proactive_ma': 20, 'short_proactive_size': 0.30,
                 'halving_crash_risk_scale': 0.6},
    }
    rows = []
    for name, cd in configs.items():
        res = run_bt(load(fpath), cfg_dict=cd, label=name, start=start)
        rows.append((name, res['multiple'], res['cagr'], res['mdd'], res['sharpe']))
    print(f"{'配置':<22}{'倍数':>10}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}")
    for name, m, c, d, s in rows:
        print(f"{name:<22}{m:>9.2f}x{c*100:>8.1f}%{d*100:>8.1f}%{s:>9.2f}")


if __name__ == '__main__':
    print(">>> 诊断加密回测最惨回撤段 (5y 窗口, 本地读, 无下载) <<<")
    analyze('crypto_5y', MAIN, '2021-08-11')
    analyze('crypto_3y', MAIN, '2023-08-11')
    print("\n\n>>> 防御开关探针 (5y) <<<")
    probe_defenses('crypto_5y', MAIN, '2021-08-11')
