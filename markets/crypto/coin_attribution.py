"""
coin_attribution.py - 逐币边际贡献归因分析 (Leave-One-Out)
=============================================================
对当前选币池中每个进攻币:
1. 跑基线 (全部43币)
2. 逐个删除该币, 跑回测
3. Δ收益 = (删后倍数 / 基线倍数 - 1)
   正值 = 删了反而涨 → 该币拖累收益 (候选删除)
   负值 = 删了跌 → 该币有正贡献 (保留)

同时统计每个币的被选频率、持仓周数等。
输出 coin_attribution_report.md
"""
import os, sys, time, json
import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crypto_options_bt as C
from crypto_options_bt import run_bt
import crypto_adoption_v2 as ca2

# ---- 数据 ----
TENY = pd.read_csv(f'{HERE}/data/weekly_adjclose_crypto50_10y.csv',
                   index_col=0, parse_dates=True).sort_index()
MAIN = pd.read_csv(f'{HERE}/data/weekly_adjclose_crypto50.csv',
                  index_col=0, parse_dates=True).sort_index()

WINDOWS = [('10y', TENY, '2016-08-11'), ('5y', MAIN, '2021-08-11'), ('3y', MAIN, '2023-08-11')]

# 所有进攻币 (非BTC/ETH/STABLE)
ALL_OFFENSE = [c for c in TENY.columns if c not in ['BTC', 'ETH', 'STABLE']]
print(f"进攻币池: {len(ALL_OFFENSE)}个")
print(f"币列表: {ALL_OFFENSE}")

# 赛道映射 (从ca2.THEME_COINS反查)
COIN_THEMES = {}
for theme, coins in ca2.THEME_COINS.items():
    for c in coins:
        if c not in COIN_THEMES:
            COIN_THEMES[c] = []
        COIN_THEMES[c].append(theme)

# 是否有期权市场
OPTION_COINS = C.OPTIONS_AVAILABLE_COINS

def run_window(px, cfg=None):
    """跑单窗口回测, 返回 multiple/mdd/sharpe"""
    if cfg is None:
        cfg = dict(C.DEFAULT_CFG)
    C._ALT_RS_CACHE.clear()
    try:
        r = run_bt(px, cfg)
        return r['multiple'], r['mdd'], r['sharpe']
    except Exception as e:
        print(f"  ERROR: {e}")
        return 0, 0, 0

def delete_coin(px, coin):
    """从数据中删除一个币 (模拟池子里没有该币)"""
    cols = [c for c in px.columns if c != coin]
    return px[cols].copy()

def main():
    t0 = time.time()

    # ---- 1. 基线 ----
    print("\n" + "="*80)
    print("逐币 Leave-One-Out 归因分析")
    print("="*80)

    print("\n[1] 基线 (全部币):")
    base = {}
    for name, pnl, st in WINDOWS:
        px = pnl[pnl.index >= pd.Timestamp(st)]
        m, d, s = run_window(px)
        base[name] = (m, d, s)
        print(f"  {name}: {m/1000:.1f}Kx  MDD={d*100:.1f}%  Sharpe={s:.2f}")

    # ---- 2. 逐币删除 ----
    print(f"\n[2] 逐币 Leave-One-Out ({len(ALL_OFFENSE)}个币):")
    results = []
    for i, coin in enumerate(ALL_OFFENSE):
        themes = COIN_THEMES.get(coin, ['?'])
        has_opt = 'Y' if coin in OPTION_COINS else 'N'
        # 数据覆盖
        s_data = TENY[coin].dropna()
        data_start = s_data.index[0].strftime('%Y-%m') if len(s_data) > 0 else '?'
        data_weeks = len(s_data)

        # 删币后回测
        loo = {}
        for name, pnl, st in WINDOWS:
            px = pnl[pnl.index >= pd.Timestamp(st)]
            px_del = delete_coin(px, coin)
            m, d, s = run_window(px_del)
            loo[name] = (m, d, s)

        # 边际贡献 (删除后变化)
        delta_10y = (loo['10y'][0] / max(base['10y'][0], 1) - 1) * 100
        delta_5y = (loo['5y'][0] / max(base['5y'][0], 1) - 1) * 100
        delta_3y = (loo['3y'][0] / max(base['3y'][0], 1) - 1) * 100
        delta_mdd = (loo['10y'][1] - base['10y'][1]) * 100  # 正=删后MDD更好(改善)

        results.append({
            'coin': coin,
            'themes': '/'.join(themes),
            'has_opt': has_opt,
            'data_start': data_start,
            'data_weeks': data_weeks,
            'loo_10y': loo['10y'],
            'loo_5y': loo['5y'],
            'loo_3y': loo['3y'],
            'delta_10y': delta_10y,
            'delta_5y': delta_5y,
            'delta_3y': delta_3y,
            'delta_mdd': delta_mdd,
        })

        opt_mark = 'O' if has_opt == 'Y' else ' '
        print(f"  [{i+1:2d}/{len(ALL_OFFENSE)}] {coin:7s} [{opt_mark}] {data_start} "
              f"10y: {loo['10y'][0]/1000:>8.1f}Kx ({delta_10y:+6.0f}%)  "
              f"5y: {loo['5y'][0]:>7.1f}x ({delta_5y:+5.0f}%)  "
              f"3y: {loo['3y'][0]:>5.1f}x ({delta_3y:+5.0f}%)  "
              f"MDD: {loo['10y'][1]*100:>5.1f}% ({delta_mdd:+5.1f}pp)")

    # ---- 3. 排序: delta_10y > 0 = 删了反而涨 = 拖累币 ----
    print("\n[3] 排序 (Δ10y正=拖累, 负=有贡献):")
    sorted_res = sorted(results, key=lambda x: -x['delta_10y'])
    for rank, r in enumerate(sorted_res):
        flag = 'DRAG' if r['delta_10y'] > 5 else ('NEUT' if abs(r['delta_10y']) <= 5 else 'KEEP')
        opt = 'O' if r['has_opt'] == 'Y' else ' '
        print(f"  {rank+1:2d}. {r['coin']:7s} [{opt}] {r['delta_10y']:+7.0f}%  "
              f"5y:{r['delta_5y']:+5.0f}%  3y:{r['delta_3y']:+5.0f}%  "
              f"MDD:{r['delta_mdd']:+5.1f}pp  {flag}  ({r['themes']})")

    # ---- 4. 删除候选 ----
    drag_coins = [r for r in results if r['delta_10y'] > 5]
    print(f"\n[4] 拖累币 (Δ10y > +5%): {len(drag_coins)}个")
    for r in sorted(drag_coins, key=lambda x: -x['delta_10y']):
        print(f"  {r['coin']:7s} Δ10y={r['delta_10y']:+.0f}%  5y={r['delta_5y']:+.0f}%  3y={r['delta_3y']:+.0f}%  "
              f"MDD={r['delta_mdd']:+.1f}pp  ({r['themes']})")

    # ---- 5. 批量删除测试 ----
    print(f"\n[5] 批量删除测试 (同时删所有Δ10y>+5%的币):")
    del_coins = [r['coin'] for r in drag_coins]
    if del_coins:
        for name, pnl, st in WINDOWS:
            px = pnl[pnl.index >= pd.Timestamp(st)]
            for c in del_coins:
                if c in px.columns:
                    px = px.drop(columns=[c])
            m, d, s = run_window(px)
            bm, bd, bs = base[name]
            print(f"  {name}: {m/1000 if m>=1000 else m:>8.1f}{'Kx' if m>=1000 else 'x':2s}  "
                  f"MDD={d*100:.1f}%  Sharpe={s:.2f}  "
                  f"(基线: {bm/1000 if bm>=1000 else bm:.1f}{'Kx' if bm>=1000 else 'x'}  "
                  f"MDD={bd*100:.1f}%  Sharpe={bs:.2f})")
    else:
        print("  无拖累币")

    # ---- 6. 更激进的删除: Δ5y和Δ3y也>0的币 ----
    drag_multi = [r for r in results if r['delta_10y'] > 0 and r['delta_5y'] > 0 and r['delta_3y'] > 0]
    print(f"\n[6] 多窗口拖累币 (10y/5y/3y全为正): {len(drag_multi)}个")
    for r in sorted(drag_multi, key=lambda x: -(x['delta_10y'] + x['delta_5y'] + x['delta_3y'])):
        print(f"  {r['coin']:7s} 10y={r['delta_10y']:+.0f}%  5y={r['delta_5y']:+.0f}%  3y={r['delta_3y']:+.0f}%  ({r['themes']})")

    if drag_multi:
        print(f"\n  批量删除 {len(drag_multi)} 个多窗口拖累币:")
        del_coins2 = [r['coin'] for r in drag_multi]
        for name, pnl, st in WINDOWS:
            px = pnl[pnl.index >= pd.Timestamp(st)]
            for c in del_coins2:
                if c in px.columns:
                    px = px.drop(columns=[c])
            m, d, s = run_window(px)
            bm, bd, bs = base[name]
            print(f"  {name}: {m/1000 if m>=1000 else m:>8.1f}{'Kx' if m>=1000 else 'x':2s}  "
                  f"MDD={d*100:.1f}%  Sharpe={s:.2f}  "
                  f"(基线: {bm/1000 if bm>=1000 else bm:.1f}{'Kx' if bm>=1000 else 'x'}  "
                  f"MDD={bd*100:.1f}%  Sharpe={bs:.2f})")

    # ---- 7. 生成报告 ----
    lines = []
    lines.append("# 逐币 Leave-One-Out 归因报告\n\n")
    lines.append(f"> 生成时间: 2026-08-13  |  方法: 逐个删除进攻币, 跑三窗口回测\n")
    lines.append(f"> Δ收益% = (删后倍数 / 基线倍数 - 1) × 100\n")
    lines.append(f"> 正值 = 删了反而涨 → 该币拖累收益 (删除候选)\n")
    lines.append(f"> 负值 = 删了跌 → 该币有正贡献 (保留)\n\n")

    lines.append("## 基线表现\n\n")
    lines.append("| 窗口 | 倍数 | MDD | Sharpe |\n")
    lines.append("|------|------|-----|--------|\n")
    for name, pnl, st in WINDOWS:
        m, d, s = base[name]
        mult_str = f"{m/1000:.1f}Kx" if m >= 1000 else f"{m:.1f}x"
        lines.append(f"| {name} | {mult_str} | {d*100:.1f}% | {s:.2f} |\n")
    lines.append("\n")

    lines.append("## 逐币归因 (按10年边际贡献排序)\n\n")
    lines.append("| 排名 | 币种 | 期权 | 赛道 | 数据起 | 10y倍数 | Δ10y% | Δ5y% | Δ3y% | ΔMDD(pp) | 判定 |\n")
    lines.append("|------|------|------|------|--------|---------|-------|------|------|----------|------|\n")
    for rank, r in enumerate(sorted_res):
        m = r['loo_10y'][0]
        mult_str = f"{m/1000:.1f}Kx" if m >= 1000 else f"{m:.1f}x"
        flag = 'DRAG' if r['delta_10y'] > 5 else ('NEUT' if abs(r['delta_10y']) <= 5 else 'KEEP')
        opt = '有' if r['has_opt'] == 'Y' else '无'
        lines.append(f"| {rank+1} | `{r['coin']}` | {opt} | {r['themes'][:15]} | {r['data_start']} | "
                     f"{mult_str} | {r['delta_10y']:+.0f}% | {r['delta_5y']:+.0f}% | {r['delta_3y']:+.0f}% | "
                     f"{r['delta_mdd']:+.1f} | {flag} |\n")
    lines.append("\n")

    if drag_coins:
        lines.append("## 删除候选 (Δ10y > +5%)\n\n")
        lines.append("| 币种 | Δ10y% | Δ5y% | Δ3y% | ΔMDD(pp) | 赛道 |\n")
        lines.append("|------|-------|------|------|----------|------|\n")
        for r in sorted(drag_coins, key=lambda x: -x['delta_10y']):
            lines.append(f"| `{r['coin']}` | {r['delta_10y']:+.0f}% | {r['delta_5y']:+.0f}% | "
                         f"{r['delta_3y']:+.0f}% | {r['delta_mdd']:+.1f} | {r['themes']} |\n")
        lines.append("\n")

    if drag_multi:
        lines.append("## 多窗口拖累币 (10y/5y/3y全为正)\n\n")
        for r in sorted(drag_multi, key=lambda x: -(x['delta_10y'] + x['delta_5y'] + x['delta_3y'])):
            lines.append(f"- `{r['coin']}`: 10y={r['delta_10y']:+.0f}%  5y={r['delta_5y']:+.0f}%  3y={r['delta_3y']:+.0f}%  ({r['themes']})\n")
        lines.append("\n")

    report = ''.join(lines)
    report_path = os.path.join(HERE, 'coin_attribution_report.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n报告: {report_path}")
    print(f"耗时: {time.time()-t0:.0f}s")

    # JSON
    json_data = {
        'base': {name: {'multiple': base[name][0], 'mdd': base[name][1], 'sharpe': base[name][2]} for name in ['10y', '5y', '3y']},
        'coins': [{
            'coin': r['coin'],
            'themes': r['themes'],
            'has_option': r['has_opt'] == 'Y',
            'data_start': r['data_start'],
            'delta_10y': r['delta_10y'],
            'delta_5y': r['delta_5y'],
            'delta_3y': r['delta_3y'],
            'delta_mdd': r['delta_mdd'],
            'loo_10y': {'multiple': r['loo_10y'][0], 'mdd': r['loo_10y'][1], 'sharpe': r['loo_10y'][2]},
        } for r in sorted(results, key=lambda x: -x['delta_10y'])],
    }
    json_path = os.path.join(HERE, 'coin_attribution.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    print(f"JSON: {json_path}")


if __name__ == '__main__':
    main()
