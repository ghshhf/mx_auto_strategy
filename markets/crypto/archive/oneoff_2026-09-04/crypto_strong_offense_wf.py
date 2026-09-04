"""strong 档进攻 cap (65%->85%) 的 walk-forward 泛化验证。

目的: 审计发现 strong 档进攻 65%->85%(保留崩盘切换) in-sample 跃到 1059.9x 且 MDD 不变(-57.9%),
单参数 2.4x 高度疑似过拟合。本脚本用与头条 448.6x 相同的 468 周面板 + 默认配置(tp=2.0/减半关),
对 strong offense cap 做 in-sample + 单次切割 + walk-forward 三重验证, 判定 1059.9x 是否真实泛化。

方法: 直接 monkeypatch ca2.REGIME_ALLOC['strong']['offense'], 其余配置(防御/稳定/崩盘切换)保持 v6.18 默认。
复用 crypto_oos_validate 的 oos_metrics 切片法(全数据跑, 只取OOS段算收益, 状态延续=实盘)。
run_bt 返回键: multiple / cagr / mdd / sharpe / nav。
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
import pandas as pd
import crypto_options_bt as C
import crypto_adoption_v2 as ca2
from crypto_options_bt import run_bt

sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)
def P(*a, **k): print(*a, **k, flush=True)

px = C._load_default()
P(f'面板: {px.index[0].date()} ~ {px.index[-1].date()} 共 {len(px)}周 (与头条448.6x同面板)\n')

OFFENSE_GRID = [0.50, 0.65, 0.80, 0.85, 0.90]

def run_with_offense(off, panel):
    saved = ca2.REGIME_ALLOC['strong']['offense']
    ca2.REGIME_ALLOC['strong']['offense'] = off
    try:
        return run_bt(panel)  # 默认 cfg: tp=2.0, halving OFF = 头条口径
    finally:
        ca2.REGIME_ALLOC['strong']['offense'] = saved

def oos_metrics(panel, off, start, end):
    r = run_with_offense(off, panel)
    nav = r['nav']
    seg = nav[(nav.index >= pd.Timestamp(start)) & (nav.index <= pd.Timestamp(end))]
    if len(seg) < 2:
        return None
    seg_n = seg / seg.iloc[0]
    weeks = len(seg_n) - 1
    m = float(seg_n.iloc[-1])
    cagr = float(seg_n.iloc[-1] ** (52.0/weeks) - 1.0) if weeks > 0 else 0.0
    peak = np.maximum.accumulate(seg_n.values)
    mdd = float((seg_n.values/peak - 1.0).min())
    rets = pd.Series(np.diff(seg_n.values)/seg_n.values[:-1])
    sharpe = float(rets.mean()/rets.std()*np.sqrt(52)) if rets.std() > 0 else 0.0
    return {'multiple':m,'cagr':cagr,'mdd':mdd,'sharpe':sharpe,'weeks':weeks}

def fmt(r):
    return f"{r['multiple']:>8.1f}x CAGR{r['cagr']*100:>7.1f}% MDD{r['mdd']*100:>7.1f}% Sharpe{r['sharpe']:>5.2f}"

# ============ 1. In-sample (全面板) ============
P('='*78)
P('1. In-sample (全 468周面板): strong 进攻 cap 扫描')
P('='*78)
ins = {}
for off in OFFENSE_GRID:
    r = run_with_offense(off, px)
    ins[off] = r
    P(f'  offense={off:.2f}: {fmt(r)}')
base_065 = ins[0.65]['multiple']
P(f'\n  头条基准(offense=0.65) = {base_065:.1f}x ; offense=0.85 = {ins[0.85]["multiple"]:.1f}x '
  f'(×{ins[0.85]["multiple"]/base_065:.2f} vs 头条)')

# ============ 2. 单次切割 ============
P('\n' + '='*78)
P('2. 单次切割: IS 选最优 cap -> OOS 验证')
P('='*78)
for cut_name, is_end, oos_start, oos_end in [
    ('切割A: 2014~2020训练 -> 2020~2026验证', '2020-05-08', '2020-05-08', '2026-07-24'),
    ('切割B: 2014~2022训练 -> 2022~2026验证', '2022-01-07', '2022-01-07', '2026-07-24'),
]:
    is_px = px[px.index <= pd.Timestamp(is_end)]
    P(f'\n--- {cut_name} ---')
    P(f'  IS: {is_px.index[0].date()}~{is_px.index[-1].date()} ({len(is_px)}周)')
    is_rows = [(off, run_with_offense(off, is_px)) for off in OFFENSE_GRID]
    is_rows.sort(key=lambda x: x[1]['sharpe'], reverse=True)
    best_off = is_rows[0][0]
    P(f'  IS 最优 cap = {best_off:.2f} (Sharpe {is_rows[0][1]["sharpe"]:.2f})')
    r_is = oos_metrics(px, best_off, oos_start, oos_end)
    r_065 = oos_metrics(px, 0.65, oos_start, oos_end)
    P(f'  OOS(IS选参 cap={best_off:.2f}): {fmt(r_is)}')
    P(f'  OOS(头条 cap=0.65):      {fmt(r_065)}')
    P(f'  -> IS选参={r_is["multiple"]:.1f}x vs 头条={r_065["multiple"]:.1f}x 比={r_is["multiple"]/r_065["multiple"]:.3f}')

# ============ 3. Walk-forward ============
P('\n' + '='*78)
P('3. Walk-forward: 每年初用此前数据选最优 cap, 当年用该 cap 跑 (2020-2025)')
P('='*78)
wf_rows = []
year_starts = ['2020-01','2021-01','2022-01','2023-01','2024-01','2025-01']
year_ends   = ['2020-12-31','2021-12-31','2022-12-31','2023-12-31','2024-12-31','2025-12-31']
for ys, ye in zip(year_starts, year_ends):
    is_end_date = pd.Timestamp(ys) - pd.Timedelta(days=1)
    is_px = px[px.index <= is_end_date]
    if len(is_px) < 60:
        continue
    is_rows = [(off, run_with_offense(off, is_px)) for off in OFFENSE_GRID]
    is_rows.sort(key=lambda x: x[1]['sharpe'], reverse=True)
    best_off = is_rows[0][0]
    r = oos_metrics(px, best_off, ys + '-01', ye)
    wf_rows.append({'year':ys[:4],'cap':best_off, **r})
    P(f"  {ys[:4]}: IS选cap={best_off:.2f} OOS {fmt(r)}")

cum_mult = 1.0
for w in wf_rows:
    cum_mult *= w['multiple']
total_weeks = sum(w['weeks'] for w in wf_rows)
total_years = total_weeks / 52
cum_cagr = float(cum_mult ** (1/total_years) - 1) if total_years > 0 else 0
P(f'\n  Walk-forward 累积(2020-2025纯OOS): {cum_mult:.1f}x / CAGR {cum_cagr*100:.1f}%')

r_085_oos = oos_metrics(px, 0.85, '2020-01-01', '2025-12-31')
r_065_oos = oos_metrics(px, 0.65, '2020-01-01', '2025-12-31')
P(f'  in-sample 0.85 同期(2020-2025): {fmt(r_085_oos)}')
P(f'  in-sample 0.65 同期(2020-2025): {fmt(r_065_oos)}')
P(f'\n  => Walk-forward vs in-sample 0.85 同期: {cum_mult/r_085_oos["multiple"]:.1%} 保留率')
P(f'  => Walk-forward vs in-sample 0.65 同期: {cum_mult/r_065_oos["multiple"]:.1%} 保留率')
P(f'  => in-sample 0.85 vs 0.65 同期倍数比: {r_085_oos["multiple"]/r_065_oos["multiple"]:.2f}x')

P(f'\n  结论判定:')
P(f'    若 WF≈in-sample 0.85 (保留率~100%) -> 0.85 真实泛化, 可解锁~{r_085_oos["multiple"]:.0f}x')
P(f'    若 WF≈in-sample 0.65 (保留率~65%)  -> 0.85 是过拟合, 头条维持448.6x')
