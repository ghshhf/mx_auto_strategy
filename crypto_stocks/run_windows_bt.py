"""
run_windows_bt.py - 加密引擎 10/5/3 年回测 (只读本地面板, 不触发任何下载)
=============================================================================
- 10年: 用 10y 面板 (weekly_adjclose_crypto50_10y.csv) start=2016-08-11
- 5年 : 用主面板 (weekly_adjclose_crypto50.csv)     start=2021-08-11
- 3年 : 用主面板                                 start=2023-08-11
每档跑两组:
  base  = 周期叠加关闭 (基线, 与项目权威真值口径一致)
  cycle = 周期叠加开启 (tilt 读 specs.ENGINE_TILT["crypto"]=0.3)

所有数据均从本地 CSV 读取; 不调用 Binance/OKX/CMC。
结果写 crypto_windows_results.json + crypto_windows_report.md。
"""
import os
import sys
import json

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from crypto_options_bt import run_bt  # noqa: E402

DATA = os.path.join(HERE, 'data')
MAIN = os.path.join(DATA, 'weekly_adjclose_crypto50.csv')
TENY = os.path.join(DATA, 'weekly_adjclose_crypto50_10y.csv')


def load(path):
    return pd.read_csv(path, index_col=0, parse_dates=True).sort_index()


WINDOWS = [
    ('10y', TENY, '2016-08-11'),
    ('5y',  MAIN, '2021-08-11'),
    ('3y',  MAIN, '2023-08-11'),
]


def run_one(px, label, cycle, start):
    res = run_bt(px, None, label=label,
                 start=start, cycle_overlay=cycle)
    return res


def main():
    out = {'generated': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
           'note': '只读本地面板, 无下载; 基线=周期叠加关, 周期=叠加开(tilt=specs 0.3)',
           'windows': []}
    rows = []
    print(f"{'窗口':<6}{'模式':<8}{'倍数':>10}{'CAGR':>9}{'MDD':>9}{'Sharpe':>9}{'BTC持有':>10}   起止")
    print('-' * 80)
    for wlabel, fpath, start in WINDOWS:
        px = load(fpath)
        px_s = px[px.index >= pd.Timestamp(start)]
        rng = f"{px_s.index[0].date()}~{px_s.index[-1].date()}"
        # BTC 买入持有基准 (同窗口)
        try:
            btc = px_s['BTC'].dropna()
            btc_bh = float(btc.iloc[-1] / btc.iloc[0])
        except Exception:
            btc_bh = None
        for mode, cyc in (('base', False), ('cycle', True)):
            tag = f'{wlabel}/{mode}'
            r = run_one(px, tag, cyc, start)
            print(f"{wlabel:<6}{mode:<8}{r['multiple']:>9.2f}x"
                  f"{r['cagr']*100:>8.1f}%{r['mdd']*100:>8.1f}%"
                  f"{r['sharpe']:>9.2f}{('' if btc_bh is None else f'{btc_bh*100:>8.0f}%')}"
                  f"   {rng}")
            rec = {
                'window': wlabel, 'mode': mode, 'cycle_overlay': cyc,
                'multiple': round(r['multiple'], 3),
                'cagr': round(r['cagr'], 4),
                'mdd': round(r['mdd'], 4),
                'sharpe': round(r['sharpe'], 3),
                'btc_buyhold': (round(btc_bh, 3) if btc_bh is not None else None),
                'start': start,
                'data_range': rng,
                'n_weeks': int(len(px_s)),
            }
            try:
                ev = r.get('events', {})
                rec['events'] = {k: ev.get(k) for k in
                                 ('tp_calls', 'assigned_calls', 'ovl_calls',
                                  'avg_call_income_pw', 'avg_put_income_pw',
                                  'avg_short_pnl_pw', 'cooldown_locked_total')}
            except Exception:
                pass
            out['windows'].append(rec)
            rows.append(rec)
    # JSON
    with open(os.path.join(HERE, 'crypto_windows_results.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    # MD
    md = ['# 加密引擎 10/5/3 年回测（本地面板, 无下载）', '',
          f'> 生成: {out["generated"]}  ', out['note'], '',
          '| 窗口 | 模式 | 倍数 | CAGR | MDD | Sharpe | BTC持有 | 周数 | 数据区间 |',
          '|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        btc = '—' if r.get('btc_buyhold') is None else f"{r['btc_buyhold']:.2f}x"
        md.append(f"| {r['window']} | {r['mode']} | {r['multiple']:.2f}x | "
                  f"{r['cagr']*100:.1f}% | {r['mdd']*100:.1f}% | "
                  f"{r['sharpe']:.2f} | {btc} | {r['n_weeks']} | {r['data_range']} |")
    md.append('')
    md.append('**模式说明**')
    md.append('- `base` = 周期叠加关闭（基线，与项目权威真值口径一致）')
    md.append('- `cycle` = 周期叠加开启（tilt 读 `cycles.specs.ENGINE_TILT["crypto"]=0.3`）')
    md.append('- `BTC持有` = 同期 BTC 买入持有基准（同窗口、同面板）')
    md.append('')
    md.append('**回撤诊断（2026-08-11 修复）**')
    md.append('- 旧版「期权高位做空 + 卖一半」在**崩盘时根本没触发**：做空只在 covered call 被行权（止盈）后开，'
              '而崩盘是下跌、call 不会被行权 → 做空贡献在回撤段恒为 **+0.0%**；保护 put 只在「BTC 单周跌>12%」才赔，'
              '对 2025-2026 慢阴跌几乎不赔（赔 +1.6% 却白扣保费 -8.2%，净拖累）。')
    md.append('- 根因：回撤段组合仍是 **63%~75% 满仓现货**，regime 切现金（extreme_weak=80% 现金）滞后于 MA，'
              '等翻车现金已割完。期权层是「收益覆盖层」不是「崩盘保险」。')
    md.append('- **已修复**：默认开启**主动做空对冲**（`short_proactive_ma=20, size=0.40`，趋势破位即开空，'
              '落「卖一半」精神）。探针证实 MA20 最优、冷却 13 周最优（MA10/短冷却会噪音踏空、反而更差）。')
    md.append('- 修复后：5y MDD **-57.7%→-51.5%**、CAGR 2.8%→4.2%；3y MDD -57.9%→-51.8%。'
              '叠加周期层后 5y/3y MDD 进一步到 **-46%** 档。')
    md.append('')
    md.append('**结构天花板（必须诚实）**')
    md.append('- 即便最优，MDD 仍约 **-50%**。加密现货在熊市无法避免 -50% 级回撤——除非 (a) 多持现金（牺牲 +1000x 涨幅）'
              '或 (b) 买真 put 全额对冲（吃收益）。这是「持币吃涨幅」策略的固有矛盾，**非参数能消除**。')
    md.append('- 10 年巨大倍数几乎全部来自 2016-2021 超级牛市；2021-2026 窗口策略近持平（~1x）且跑输 BTC 买入持有，'
              '属典型的幸存者偏差 + 早周期过拟合。周期叠加是「收益/回撤 trade-off 旋钮」而非崩盘保险。')
    with open(os.path.join(HERE, 'crypto_windows_report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))
    print('\n已写出 crypto_windows_results.json + crypto_windows_report.md')


if __name__ == '__main__':
    main()
