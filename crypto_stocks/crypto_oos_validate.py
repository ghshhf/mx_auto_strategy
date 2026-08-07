"""减半周期缩仓参数的过拟合检验: 时间序列切割 + walk-forward。

检验逻辑:
  1. 单次切割: IS1=2014-09~2020-05(1轮减半训练) → OOS1=2020-05~2026-07(下1轮验证)
              IS2=2014-09~2022-01(2轮减半训练) → OOS2=2022-01~2026-07(最后1轮验证)
     在IS上扫参找最优 → 在OOS上跑 → 对比"IS选参" vs "后视镜全局选参"的OOS表现
  2. Walk-forward: 每年初用此前所有数据选参, 下一年用该参跑(拼接得2020-2025真实OOS曲线)

  关键: OOS段用全数据跑(让warmup用历史), 只取OOS段nav算收益。状态延续=实盘场景。
"""
import os, sys, itertools
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
import pandas as pd
from crypto_options_bt import run_bt

# 强制无缓冲输出
sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)

def P(*a, **k):
    print(*a, **k, flush=True)

px_full = pd.read_csv(os.path.join(HERE, 'data', 'weekly_adjclose_crypto50_10y.csv'),
                      index_col=0, parse_dates=True).sort_index()
P(f'数据: {px_full.index[0].date()} ~ {px_full.index[-1].date()} 共 {len(px_full)}周\n')

BASE = dict(
    take_profit_pct=0.80, cooldown_weeks=8, call_strike_otm=1.5,
    enabled_short=True, option_universe_only=True,
    short_proactive_ma=20, short_dte_weeks=4, short_trend_exit_ma=4,
    short_split=True, short_proactive_size=0.50, short_proactive_cooldown=8,
    halving_cycle_enabled=True,
)

# 扫描网格 (相位缩放)
EU_GRID = [1.0, 0.8, 0.6]
CR_GRID = [1.0, 0.7, 0.5, 0.3]
BB_GRID = [1.0, 0.7, 0.5, 0.3]
# Walk-forward精简网格 (eu已证固定1.0最优, 只扫cr/bb关键值, 加速6倍)
WF_GRID = [(1.0, cr, bb) for cr in [1.0, 0.5, 0.3] for bb in [1.0, 0.5]]

# 缓存: 避免重复扫描同一段数据
_scan_cache = {}
def scan(px, sort_by='sharpe'):
    """在px上扫相位缩放, 返回按sort_by排序的所有结果。带缓存。"""
    key = (px.index[0], px.index[-1], len(px))
    if key in _scan_cache:
        rows = _scan_cache[key]
    else:
        rows = []
        for eu, cr, bb in itertools.product(EU_GRID, CR_GRID, BB_GRID):
            c = dict(BASE, halving_euphoria_risk_scale=eu,
                     halving_crash_risk_scale=cr, halving_bear_bottom_risk_scale=bb)
            r = run_bt(px, c, label=f'eu{eu}_cr{cr}_bb{bb}')
            rows.append({'eu':eu,'cr':cr,'bb':bb,
                         'mult':r['multiple'],'cagr':r['cagr'],'mdd':r['mdd'],'sharpe':r['sharpe']})
        _scan_cache[key] = rows
    rows_sorted = sorted(rows, key=lambda x: x[sort_by], reverse=True)
    return rows_sorted

def oos_metrics(px, cfg, oos_start, oos_end):
    """用全数据跑, 只取OOS段[oos_start, oos_end]的nav算收益/MDD/Sharpe。状态延续=实盘。"""
    r = run_bt(px, cfg, label='oos')
    nav = r['nav']
    seg = nav[(nav.index >= pd.Timestamp(oos_start)) & (nav.index <= pd.Timestamp(oos_end))]
    if len(seg) < 2:
        return None
    # 归一化到OOS段起点=1
    seg_n = seg / seg.iloc[0]
    mult = float(seg_n.iloc[-1])
    weeks = len(seg_n) - 1
    cagr = float((seg_n.iloc[-1]) ** (52.0/weeks) - 1.0) if weeks > 0 else 0.0
    peak = np.maximum.accumulate(seg_n.values)
    mdd = float((seg_n.values/peak - 1.0).min())
    rets = pd.Series(np.diff(seg_n.values)/seg_n.values[:-1])
    sharpe = float(rets.mean()/rets.std()*np.sqrt(52)) if rets.std() > 0 else 0.0
    return {'mult':mult, 'cagr':cagr, 'mdd':mdd, 'sharpe':sharpe, 'weeks':weeks}

def fmt(r):
    return f"{r['mult']:>8.1f}x {r['cagr']*100:>7.1f}% MDD{r['mdd']*100:>7.1f}% Sharpe{r['sharpe']:>5.2f}"

# ============ 1. 单次切割验证 ============
P('='*80)
P('1. 单次切割验证: IS找最优参 → OOS验证')
P('='*80)

# 全局扫描只做一次 (后视镜基准)
P('\n[预扫描全数据找后视镜基准...]')
full_rows = scan(px_full, sort_by='sharpe')
global_best = full_rows[0]
P(f'  全数据扫描Top3 (后视镜基准):')
P(f"    {'eu':>5}{'cr':>5}{'bb':>5}{'倍数':>9}{'CAGR':>8}{'MDD':>8}{'Sharpe':>8}")
for r in full_rows[:3]:
    P(f"    {r['eu']:>5.1f}{r['cr']:>5.1f}{r['bb']:>5.1f}{r['mult']:>8.1f}x{r['cagr']*100:>7.1f}%{r['mdd']*100:>7.1f}%{r['sharpe']:>8.2f}")

for cut_name, is_end, oos_start, oos_end in [
    ('切割A: 1轮训练→1轮验证', '2020-05-08', '2020-05-08', '2026-07-24'),
    ('切割B: 2轮训练→最后1轮', '2021-12-31', '2022-01-07', '2026-07-24'),
]:
    P(f'\n--- {cut_name} ---')
    is_px = px_full[px_full.index <= pd.Timestamp(is_end)]
    oos_px = px_full[px_full.index >= pd.Timestamp(oos_start)]
    P(f'  IS: {is_px.index[0].date()}~{is_px.index[-1].date()} ({len(is_px)}周)  '
      f'OOS: {oos_px.index[0].date()}~{oos_px.index[-1].date()} ({len(oos_px)}周)')

    # IS扫描
    P(f'  [扫描IS找最优参...]')
    is_rows = scan(is_px, sort_by='sharpe')
    is_best = is_rows[0]
    P(f'  IS扫描Top5 (按Sharpe):')
    P(f"    {'eu':>5}{'cr':>5}{'bb':>5}{'倍数':>9}{'CAGR':>8}{'MDD':>8}{'Sharpe':>8}")
    for r in is_rows[:5]:
        P(f"    {r['eu']:>5.1f}{r['cr']:>5.1f}{r['bb']:>5.1f}{r['mult']:>8.1f}x{r['cagr']*100:>7.1f}%{r['mdd']*100:>7.1f}%{r['sharpe']:>8.2f}")

    # OOS验证
    cfg_is = dict(BASE, halving_euphoria_risk_scale=is_best['eu'],
                  halving_crash_risk_scale=is_best['cr'],
                  halving_bear_bottom_risk_scale=is_best['bb'])
    cfg_global = dict(BASE, halving_euphoria_risk_scale=global_best['eu'],
                      halving_crash_risk_scale=global_best['cr'],
                      halving_bear_bottom_risk_scale=global_best['bb'])
    cfg_doc = dict(BASE, halving_euphoria_risk_scale=1.0,
                   halving_crash_risk_scale=0.5, halving_bear_bottom_risk_scale=0.5)  # 文档默认档

    r_is = oos_metrics(px_full, cfg_is, oos_start, oos_end)
    r_global = oos_metrics(px_full, cfg_global, oos_start, oos_end)
    r_doc = oos_metrics(px_full, cfg_doc, oos_start, oos_end)

    P(f'\n  OOS段验证结果:')
    P(f'    IS选参(eu{is_best["eu"]}/cr{is_best["cr"]}/bb{is_best["bb"]}):  {fmt(r_is)}')
    P(f'    后视镜(eu{global_best["eu"]}/cr{global_best["cr"]}/bb{global_best["bb"]}): {fmt(r_global)}')
    P(f'    文档档(eu1.0/cr0.5/bb0.5):           {fmt(r_doc)}')
    P(f'  → IS选参 vs 后视镜 Sharpe差: {r_is["sharpe"]-r_global["sharpe"]:+.2f}  '
      f'收益差: {r_is["mult"]/r_global["mult"]-1:+.1%}')

# ============ 2. Walk-forward ============
P('\n' + '='*80)
P('2. Walk-forward: 每年初用此前所有数据选参, 下一年用该参跑')
P('='*80)

wf_rows = []
year_starts = ['2020-01','2021-01','2022-01','2023-01','2024-01','2025-01']
year_ends   = ['2020-12','2021-12','2022-12','2023-12','2024-12','2025-12']

for ys, ye in zip(year_starts, year_ends):
    is_end_date = pd.Timestamp(ys) - pd.Timedelta(days=1)  # 截至上年末
    is_px = px_full[px_full.index <= is_end_date]
    if len(is_px) < 60:
        continue
    P(f'  [{ys[:4]}年 扫描IS(截至{is_end_date.date()}, {len(is_px)}周)选参...]')
    # Walk-forward用精简网格(6组), 不用完整48组
    wf_rows_tmp = []
    for eu, cr, bb in WF_GRID:
        c = dict(BASE, halving_euphoria_risk_scale=eu,
                 halving_crash_risk_scale=cr, halving_bear_bottom_risk_scale=bb)
        r = run_bt(is_px, c, label=f'wf{eu}_{cr}_{bb}')
        wf_rows_tmp.append({'eu':eu,'cr':cr,'bb':bb,
                            'mult':r['multiple'],'cagr':r['cagr'],'mdd':r['mdd'],'sharpe':r['sharpe']})
    wf_rows_tmp.sort(key=lambda x: x['sharpe'], reverse=True)
    best = wf_rows_tmp[0]
    cfg = dict(BASE, halving_euphoria_risk_scale=best['eu'],
               halving_crash_risk_scale=best['cr'],
               halving_bear_bottom_risk_scale=best['bb'])
    oos_start = pd.Timestamp(ys)
    oos_end = pd.Timestamp(ye) + pd.offsets.MonthEnd(0)
    r = oos_metrics(px_full, cfg, oos_start, oos_end)
    wf_rows.append({'year':ys[:4], 'is_param':f"eu{best['eu']}/cr{best['cr']}/bb{best['bb']}", **r})
    P(f"  {ys[:4]}: IS参={wf_rows[-1]['is_param']:<18} OOS {fmt(r)}")

# 拼接walk-forward各年收益 (几何累积)
P('\n  Walk-forward 累积 (2020-2025各年几何累积, 无后视镜):')
cum_mult = 1.0
for w in wf_rows:
    cum_mult *= w['mult']
    P(f"    {w['year']}: 当年{w['mult']:.2f}x → 累积{cum_mult:.1f}x")
total_years = sum(w['weeks'] for w in wf_rows) / 52
cum_cagr = float(cum_mult ** (1/total_years) - 1) if total_years > 0 else 0
P(f"\n  Walk-forward 总计: {cum_mult:.1f}x / CAGR {cum_cagr*100:.1f}% (6年纯OOS)")

# 对比: 全数据后视镜最优在2020-2025同期的表现
r_full_oos = oos_metrics(px_full, dict(BASE, halving_euphoria_risk_scale=global_best['eu'],
                         halving_crash_risk_scale=global_best['cr'],
                         halving_bear_bottom_risk_scale=global_best['bb']),
                         '2020-01-01', '2025-12-31')
P(f"  后视镜基准同期(2020-2025): {fmt(r_full_oos)}")
P(f"\n  → Walk-forward vs 后视镜 收益比: {cum_mult/r_full_oos['mult']:.2%}")
P(f"  → (越接近100% = 过拟合越轻; 大幅低于100% = 过拟合严重)")
