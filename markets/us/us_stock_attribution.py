"""
us_stock_attribution.py - 美股逐股 Leave-One-Out 归因分析
============================================================
对US50池子中每只进攻股:
1. 跑基线 (全部48只)
2. 逐个删除该股, 跑回测
3. Δ收益 = (删后倍数 / 基线倍数 - 1)
   正值 = 删了反而涨 → 该股拖累收益
   负值 = 删了跌 → 该股有正贡献

同时统计每只股票的被选频率、年度表现、波动率等。
"""
import os, sys, time, json, math, statistics
import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from us_backtest_ai import (
    load_panel, load_us_cfg, run_optimized,
    select_optimized, eligible_universe, regime_of, death_cross_count,
    pick_defense_lowvol, _ma, WARMUP, EXCLUDE, PANEL, series_proxy
)
import us_backtest_ai as usb

# 加载面板
dates, series = load_panel(PANEL)
series_proxy.clear()
series_proxy.update(series)
us_cfg = load_us_cfg()
opt_sim_cfg = us_cfg.get("options_sim", {})
options_sim = opt_sim_cfg if opt_sim_cfg.get("enabled", False) else None

# 美股进攻池 (从 us_adoption.py)
from us_adoption import THEME_STOCKS

ALL_OFFENSE = []
for theme, stocks in THEME_STOCKS.items():
    for s in stocks:
        if s not in ALL_OFFENSE:
            ALL_OFFENSE.append(s)

# 赛道映射
COIN_THEMES = {}
for theme, stocks in THEME_STOCKS.items():
    for s in stocks:
        if s not in COIN_THEMES:
            COIN_THEMES[s] = []
        COIN_THEMES[s].append(theme)

print(f"美股进攻池: {len(ALL_OFFENSE)}只")
print(f"股票列表: {ALL_OFFENSE}")

def run_baseline():
    """跑基线"""
    hist, st = run_optimized(series, dates, use_ai=False, cfg=None, refresh_weeks=4,
                             theme_div=True, max_per_theme=2, us_cfg=us_cfg, options_sim=options_sim)
    yr_rets = list(st['yearly'].values())
    avg = statistics.mean([r-1 for r in yr_rets])
    sd = statistics.pstdev([r-1 for r in yr_rets])
    sh = (avg/sd*(52**0.5)) if sd > 0 else 0
    return st['multiple'], st['mdd'], sh, st

def delete_stock(stock):
    """从面板中删除一只股票"""
    s2 = {k: v for k, v in series.items() if k != stock}
    return s2

def run_with_panel(panel_series):
    """用指定面板跑回测"""
    global series_proxy
    old_proxy = dict(series_proxy)
    series_proxy.clear()
    series_proxy.update(panel_series)
    hist, st = run_optimized(panel_series, dates, use_ai=False, cfg=None, refresh_weeks=4,
                             theme_div=True, max_per_theme=2, us_cfg=us_cfg, options_sim=options_sim)
    yr_rets = list(st['yearly'].values())
    avg = statistics.mean([r-1 for r in yr_rets])
    sd = statistics.pstdev([r-1 for r in yr_rets])
    sh = (avg/sd*(52**0.5)) if sd > 0 else 0
    series_proxy.clear()
    series_proxy.update(old_proxy)
    return st['multiple'], st['mdd'], sh, st

t0 = time.time()
print("\n" + "="*100)
print("美股逐股 Leave-One-Out 归因分析")
print("="*100)

# ---- 1. 基线 ----
print("\n[1] 基线:")
base_m, base_d, base_s, base_st = run_baseline()
print(f"  10y: {base_m:.1f}x  MDD={base_d*100:.1f}%  Sharpe={base_s:.2f}")

# ---- 2. 每只股票的统计信息 ----
print("\n[2] 各股票统计:")
stock_stats = []
for i, stock in enumerate(ALL_OFFENSE):
    arr = series.get(stock)
    if not arr:
        continue
    # 数据覆盖
    vals = [v for v in arr if v is not None and v > 0]
    if len(vals) < 52:
        stock_stats.append({'stock': stock, 'skip': True, 'reason': '数据不足'})
        continue
    # 年化波动率
    rets = []
    for k in range(1, len(arr)):
        if arr[k] and arr[k-1] and arr[k-1] > 0:
            r = arr[k] / arr[k-1] - 1
            if r is not None:
                rets.append(r)
    vol = statistics.pstdev(rets) * (52**0.5) if len(rets) > 10 else 0
    # 10年总收益
    first_valid = None
    last_valid = None
    for k in range(len(arr)):
        if arr[k] and arr[k] > 0:
            if first_valid is None:
                first_valid = (k, arr[k])
            last_valid = (k, arr[k])
    total_ret = (last_valid[1] / first_valid[1] - 1) * 100 if first_valid and last_valid else 0
    # 2026 YTD
    ytd_start = None
    ytd_end = None
    for k in range(len(arr)):
        if dates[k][:4] == '2026' and arr[k] and arr[k] > 0:
            if ytd_start is None:
                ytd_start = arr[k]
            ytd_end = arr[k]
    ytd = (ytd_end / ytd_start - 1) * 100 if ytd_start and ytd_end else 0
    # 最大回撤
    peak = 0
    max_dd = 0
    for v in arr:
        if v and v > 0:
            peak = max(peak, v)
            dd = v / peak - 1
            if dd < max_dd:
                max_dd = dd

    themes = COIN_THEMES.get(stock, ['?'])
    stock_stats.append({
        'stock': stock, 'themes': '/'.join(themes),
        'vol': vol, 'total_ret': total_ret, 'ytd': ytd,
        'max_dd': max_dd * 100, 'data_weeks': len(vals),
        'skip': False
    })
    print(f"  [{i+1:2d}/{len(ALL_OFFENSE)}] {stock:6s} vol={vol*100:>5.1f}%  "
          f"10y_ret={total_ret:>+8.0f}%  YTD={ytd:>+7.1f}%  MDD={max_dd*100:>6.1f}%  "
          f"({themes[0]})")

# ---- 3. 逐股 Leave-One-Out ----
print(f"\n[3] 逐股 Leave-One-Out ({len(ALL_OFFENSE)}只):")
results = []
for i, stock in enumerate(ALL_OFFENSE):
    # 删除该股后面板
    panel_del = delete_stock(stock)
    try:
        m, d, s, st = run_with_panel(panel_del)
    except Exception as e:
        print(f"  [{i+1:2d}] {stock:6s} ERROR: {e}")
        continue
    delta = (m / max(base_m, 1) - 1) * 100
    delta_mdd = (d - base_d) * 100  # 正=删后MDD更好(改善)
    themes = COIN_THEMES.get(stock, ['?'])

    results.append({
        'stock': stock, 'themes': '/'.join(themes),
        'loo_mult': m, 'loo_mdd': d, 'loo_sharpe': s,
        'delta_mult': delta, 'delta_mdd': delta_mdd,
    })
    flag = 'DRAG' if delta > 5 else ('NEUT' if abs(delta) <= 5 else 'KEEP')
    print(f"  [{i+1:2d}/{len(ALL_OFFENSE)}] {stock:6s} {m:>8.1f}x ({delta:>+6.0f}%)  "
          f"MDD={d*100:>5.1f}% ({delta_mdd:>+5.1f}pp)  {flag}  ({themes[0]})")

# ---- 4. 排序 ----
print("\n[4] 排序 (Δ正=拖累, 负=有贡献):")
sorted_res = sorted(results, key=lambda x: -x['delta_mult'])
for rank, r in enumerate(sorted_res):
    flag = 'DRAG' if r['delta_mult'] > 5 else ('NEUT' if abs(r['delta_mult']) <= 5 else 'KEEP')
    print(f"  {rank+1:2d}. {r['stock']:6s} Δ={r['delta_mult']:>+7.0f}%  "
          f"MDD={r['loo_mdd']*100:>5.1f}% ({r['delta_mdd']:>+5.1f}pp)  "
          f"{flag}  ({r['themes']})")

# ---- 5. 删除候选 ----
drag = [r for r in results if r['delta_mult'] > 5]
print(f"\n[5] 拖累股 (Δ > +5%): {len(drag)}只")
for r in sorted(drag, key=lambda x: -x['delta_mult']):
    # 找对应的stats
    stats = next((s for s in stock_stats if s['stock'] == r['stock']), {})
    vol = stats.get('vol', 0)
    total_ret = stats.get('total_ret', 0)
    ytd = stats.get('ytd', 0)
    print(f"  {r['stock']:6s}  Δ={r['delta_mult']:>+6.0f}%  vol={vol*100:>5.1f}%  "
          f"10y={total_ret:>+7.0f}%  YTD={ytd:>+6.1f}%  ({r['themes']})")

# ---- 6. 生成报告 ----
lines = []
lines.append("# 美股逐股 Leave-One-Out 归因报告\n\n")
lines.append(f"> 生成时间: 2026-08-13  |  方法: 逐个删除进攻股, 跑10年回测\n")
lines.append(f"> Δ收益% = (删后倍数 / 基线倍数 - 1) × 100\n")
lines.append(f"> 正值 = 删了反而涨 → 该股拖累收益\n")
lines.append(f"> 负值 = 删了跌 → 该股有正贡献\n\n")

lines.append("## 基线\n\n")
lines.append(f"| 倍数 | MDD | Sharpe |\n")
lines.append(f"|------|-----|--------|\n")
lines.append(f"| {base_m:.1f}x | {base_d*100:.1f}% | {base_s:.2f} |\n\n")

# 合并stats和loo
merged = []
for r in results:
    stats = next((s for s in stock_stats if s['stock'] == r['stock']), {})
    merged.append({**r, **stats})

lines.append("## 逐股归因 (按边际贡献排序)\n\n")
lines.append("| 排名 | 股票 | 赛道 | 年化波动 | 10年收益 | 2026YTD | 删后倍数 | Δ收益% | ΔMDD(pp) | 判定 |\n")
lines.append("|------|------|------|---------|---------|---------|---------|--------|----------|------|\n")
for rank, r in enumerate(sorted_res):
    stats = next((s for s in stock_stats if s['stock'] == r['stock']), {})
    vol = stats.get('vol', 0)
    total_ret = stats.get('total_ret', 0)
    ytd = stats.get('ytd', 0)
    flag = 'DRAG' if r['delta_mult'] > 5 else ('NEUT' if abs(r['delta_mult']) <= 5 else 'KEEP')
    lines.append(f"| {rank+1} | `{r['stock']}` | {r['themes'][:15]} | {vol*100:.1f}% | "
                 f"{total_ret:+.0f}% | {ytd:+.1f}% | {r['loo_mult']:.1f}x | "
                 f"{r['delta_mult']:+.0f}% | {r['delta_mdd']:+.1f} | {flag} |\n")
lines.append("\n")

# 删除推荐
lines.append("## 删除推荐 (Δ > +5%)\n\n")
lines.append("| 股票 | Δ收益% | 年化波动 | 10年收益 | 2026YTD | 赛道 | 删除理由 |\n")
lines.append("|------|--------|---------|---------|---------|------|----------|\n")
for r in sorted(drag, key=lambda x: -x['delta_mult']):
    stats = next((s for s in stock_stats if s['stock'] == r['stock']), {})
    vol = stats.get('vol', 0)
    total_ret = stats.get('total_ret', 0)
    ytd = stats.get('ytd', 0)
    # 生成删除理由
    reasons = []
    if r['delta_mult'] > 20:
        reasons.append("删后收益大幅提升")
    if r['delta_mdd'] > 2:
        reasons.append("删后MDD改善")
    if vol > 0.6:
        reasons.append(f"年化波动{vol*100:.0f}%过高")
    if total_ret < 0:
        reasons.append("10年总收益为负")
    if ytd < -20:
        reasons.append(f"2026 YTD {ytd:.0f}%")
    if r['delta_mdd'] > 0 and r['delta_mult'] > 5:
        reasons.append("收益+风险双拖累")
    reason = "; ".join(reasons) if reasons else "整体边际贡献为负"
    lines.append(f"| `{r['stock']}` | {r['delta_mult']:+.0f}% | {vol*100:.1f}% | "
                 f"{total_ret:+.0f}% | {ytd:+.1f}% | {r['themes']} | {reason} |\n")
lines.append("\n")

# 全部股票stats表
lines.append("## 全部股票统计\n\n")
lines.append("| 股票 | 赛道 | 年化波动 | 10年收益 | 2026YTD | 最大回撤 | 数据周数 |\n")
lines.append("|------|------|---------|---------|---------|---------|----------|\n")
for s in sorted(stock_stats, key=lambda x: x.get('vol', 0), reverse=True):
    if s.get('skip'):
        continue
    lines.append(f"| `{s['stock']}` | {s['themes']} | {s['vol']*100:.1f}% | "
                 f"{s['total_ret']:+.0f}% | {s['ytd']:+.1f}% | {s['max_dd']:.1f}% | {s['data_weeks']} |\n")

report = ''.join(lines)
report_path = os.path.join(HERE, 'us_stock_attribution_report.md')
with open(report_path, 'w', encoding='utf-8') as f:
    f.write(report)
print(f"\n报告: {report_path}")
print(f"耗时: {time.time()-t0:.0f}s")
