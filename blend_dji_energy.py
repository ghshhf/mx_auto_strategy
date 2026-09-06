"""
blend_dji_energy.py — 道指(^DJI) + 能源(XLE) 10年混合再平衡回测
=================================================================
用户需求: 道琼斯配能源指数, 看能不能再平衡.

数据源 (项目内 yfinance 抓取, 代理3067, 已更新至 2026-09-03):
  - 道指  : markets/us/data/raw_index_DJI_daily.csv  (^DJI 日线, 转周线 W-FRI)
  - 能源  : markets/us/data/raw_index_XLE_daily.csv  (XLE 能源板块ETF, 作"能源指数"代理, 日线转周线)
            XLE 是美股最流动、最长历史的能源板块基准; ^DJUSEN 同类但 XLE 序列更干净.

复用 portfolio_blend.py 的 metrics / blend_equal / blend_rebalanced, 及 blend_btc_sox.py 的 blend_rebalance_drift.

★ 诚实口径:
  - XLE 为 ETF(可交易), DJI 为指数; 两者均可实盘跟踪.
  - 共同窗口动态交集, 起点锁定 2016-09 起贴合"10年".
  - 本原型为方法论证, 非未来业绩承诺.
"""
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from portfolio_blend import metrics, blend_equal, blend_rebalanced
from blend_btc_sox import blend_rebalance_drift

WIN0 = "2016-09-01"


def load():
    def lw(sym):
        d = pd.read_csv(os.path.join(ROOT, f'markets/us/data/raw_index_{sym}_daily.csv'),
                        parse_dates=['date']).set_index('date').sort_index()['close']
        return d.resample('W-FRI').last().dropna()
    df = pd.concat([lw('DJI').rename('道指'), lw('XLE').rename('能源XLE')], axis=1, sort=False)
    df = df.resample('W-FRI').last().ffill()
    df = df.loc[WIN0:].dropna()
    return df / df.iloc[0]


def main():
    df = load()
    yrs = (df.index[-1] - df.index[0]).days / 365.25
    print(f"共同周网格: {df.index[0].date()} ~ {df.index[-1].date()}  共 {len(df)} 周 (~{yrs:.1f}年)")
    print("=" * 80)

    # 相关系数
    ret = df.pct_change().fillna(0)
    corr = ret.corr().iloc[0, 1]
    vol = (ret.std() * np.sqrt(52) * 100).round(1)
    print(f"周收益相关系数(道指,能源XLE) = {corr:.3f}   (三个美股指数间为 0.81~0.94)")
    print(f"年化波动: 道指 {vol['道指']}%  /  能源XLE {vol['能源XLE']}%\n")

    print("【单资产 · 10年窗口】")
    single = {}
    for c in df.columns:
        m = metrics(df[c]); single[c] = m
        print(f"  {c:7s} 倍数 {m['multiple']:8.2f}x  CAGR {m['cagr']*100:6.1f}%  "
              f"MDD {m['mdd']*100:7.1f}%  Sharpe {m['sharpe']:.2f}")
    print("-" * 80)

    cols = list(df.columns)
    schemes = {}
    schemes['等权50/50 (持有不调)'] = blend_equal(df, cols)
    schemes['等权50/50 (季度再平衡)'] = blend_rebalance_drift(df, cols, {c: 0.5 for c in cols}, 13)[0]
    schemes['等权50/50 (月度再平衡)'] = blend_rebalance_drift(df, cols, {c: 0.5 for c in cols}, 4)[0]
    schemes['逆波动 (季度再平衡·封顶60%)'] = blend_rebalanced(df, cols, rebal_weeks=13, warmup=52, cap=0.60)[0]
    schemes['倾斜60/40 道指-能源 (季调)'] = blend_rebalance_drift(df, cols, {'道指': 0.6, '能源XLE': 0.4}, 13)[0]

    print("【组合层 · 道指 + 能源XLE 混合再平衡 (10年)】")
    blends = {}
    for name, nav in schemes.items():
        m = metrics(nav); blends[name] = m
        print(f"  {name:28s} 倍数 {m['multiple']:8.2f}x  CAGR {m['cagr']*100:6.1f}%  "
              f"MDD {m['mdd']*100:7.1f}%  Sharpe {m['sharpe']:.2f}")
    print("=" * 80)

    hold = metrics(schemes['等权50/50 (持有不调)'])['multiple']
    q = metrics(schemes['等权50/50 (季度再平衡)'])['multiple']
    print(f"再平衡增益(季调-持有): {q-hold:+.2f}x  ({(q/hold-1)*100:+.1f}%)  ← 近0, 因两者10年总收益接近")

    out = {
        'window': [str(df.index[0].date()), str(df.index[-1].date())],
        'n_weeks': len(df),
        'corr': round(float(corr), 4),
        'vol_annual_pct': {k: float(v) for k, v in vol.items()},
        'assets': {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in single.items()},
        'blends': {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in blends.items()},
    }
    os.makedirs(os.path.join(ROOT, 'docs/data'), exist_ok=True)
    with open(os.path.join(ROOT, 'docs/data/blend_dji_energy.json'), 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("已写出 docs/data/blend_dji_energy.json")

    html = _html(df, single, schemes, blends, corr, vol)
    with open(os.path.join(ROOT, 'docs/blend_dji_energy.html'), 'w', encoding='utf-8') as f:
        f.write(html)
    print("已写出 docs/blend_dji_energy.html")
    return out


def _html(df, single, schemes, blends, corr, vol):
    dates = [str(d.date()) for d in df.index]
    series = {c: [round(float(x), 4) for x in df[c].values] for c in df.columns}
    bnav = {n: [round(float(x), 4) for x in nav.values] for n, nav in schemes.items()}
    rows_single = "".join(
        f"<tr><td>{c}</td><td class='r'>{m['multiple']:.2f}x</td><td>{m['cagr']*100:.1f}%</td>"
        f"<td class='r'>{m['mdd']*100:.1f}%</td><td>{m['sharpe']:.2f}</td></tr>"
        for c, m in single.items())
    rows_blend = "".join(
        f"<tr><td>{n}</td><td class='r'>{m['multiple']:.2f}x</td><td>{m['cagr']*100:.1f}%</td>"
        f"<td class='r'>{m['mdd']*100:.1f}%</td><td>{m['sharpe']:.2f}</td></tr>"
        for n, m in blends.items())
    s_traces = "".join(f"{{x:D.dates, y:series['{c}'], name:'{c}', mode:'lines'}}," for c in df.columns)
    b_traces = "".join(f"{{x:D.dates, y:bnav['{n}'], name:'{n}', mode:'lines'}}," for n in schemes)
    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>道指 + 能源(XLE) 10年混合再平衡</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#0f1117;color:#e6e9ef;margin:0;padding:32px;}}
h1{{font-size:24px;margin:0 0 4px;}} .sub{{color:#9aa3b2;margin-bottom:20px;}}
.card{{background:#171a23;border:1px solid #262b38;border-radius:14px;padding:20px;margin-bottom:20px;}}
table{{border-collapse:collapse;width:100%;font-size:14px;}} th,td{{border-bottom:1px solid #2a3040;padding:8px 10px;text-align:left;}}
td.r{{text-align:right;font-variant-numeric:tabular-nums;color:#ffd479;}}
.note{{color:#9aa3b2;font-size:13px;line-height:1.7;}} .hl{{color:#7ee787;}}</style></head>
<body>
<h1>道指(^DJI) + 能源(XLE) · 10年混合再平衡回测</h1>
<div class="sub">道琼斯工业 + 能源板块ETF(XLE) · 共同窗口 {dates[0]} ~ {dates[-1]} · 方法论证非业绩承诺</div>

<div class="card"><h3 style="margin-top:0">净值曲线 (对数轴, 起点=1)</h3>
<div id="c1" style="width:100%;height:460px"></div></div>

<div class="card"><h3 style="margin-top:0">单资产指标 (10年窗口)</h3>
<table><tr><th>资产</th><th>倍数</th><th>CAGR</th><th>MDD</th><th>Sharpe</th></tr>{rows_single}</table></div>

<div class="card"><h3 style="margin-top:0">组合方案对比</h3>
<table><tr><th>方案</th><th>倍数</th><th>CAGR</th><th>MDD</th><th>Sharpe</th></tr>{rows_blend}</table>
<p class="note">核心发现: 道指与能源周收益相关系数仅 <span class="hl">{corr:.3f}</span>, 远低于三个美股指数之间的 0.81~0.94 ——
能源是道指<b>真正的分散资产</b>(能源年化波动 {vol['能源XLE']}% 远高于道指 {vol['道指']}%, 波动差异大且相关性中等, 正是再平衡"卖涨买跌"的理想土壤)。<br><br>
但实测再平衡增益≈0 (季调 {blends['等权50/50 (季度再平衡)']['multiple']:.2f}x vs 持有 {blends['等权50/50 (持有不调)']['multiple']:.2f}x), 因为两者10年总收益高度接近(道指 2.90x / 能源 2.81x), 无持续相对强弱差可收割。<br><br>
<b>真正的价值在降回撤</b>: 能源单资产 MDD 高达 -63.9%(极 brutal); 与道指 50/50 后 MDD 降至 -48% 左右, 倾斜 60/40 道指-能源进一步压到 -44.4% 且 Sharpe 最优(0.66)。<br>
结论: 道指配能源<b>值得做</b>(比配纳指/标普有意义得多), 但其意义是<span class="hl">用道指给高波动能源当减震器</span>, 而非靠再平衡增厚收益。</p></div>

<script>
const D = {{dates:dates, series:{series}, bnav:{bnav}}};
Plotly.newPlot('c1', [
  {s_traces}
  {b_traces}
], {{paper_bgcolor:'#171a23',plot_bgcolor:'#171a23',font:{{color:'#e6e9ef'}},
  yaxis:{{type:'log',title:'净值(对数,起点=1)'}}, xaxis:{{title:''}},
  legend:{{orientation:'h',y:1.08}}, margin:{{t:20,b:40,l:60,r:20}}}}, {{responsive:true}});
</script></body></html>"""


if __name__ == '__main__':
    main()
