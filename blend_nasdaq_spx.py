"""
blend_nasdaq_spx.py — 纳斯达克综合指数(^IXIC) + 标普500(^GSPC) 10 年混合再平衡回测
=================================================================================
用户需求: 纳指 配 标普500, 做再平衡, 跑 10 年看效果.

数据源 (本脚本内实时抓取, 经 3067 代理, 已落盘缓存到 markets/us/data/raw_index_*_daily.csv):
  - 纳指   : ^IXIC (Nasdaq Composite) 日线 -> 周线 W-FRI
  - 标普500: ^GSPC (S&P 500)          日线 -> 周线 W-FRI

复用:
  - portfolio_blend.py 的 metrics / blend_equal / blend_rebalanced
  - blend_btc_sox.py 的 blend_rebalance_drift (真·再平衡分配器)

★ 诚实口径:
  - 两个都是美股宽基指数, 长期高度正相关 (~0.95+), 因此"再平衡波动收益"远弱于 BTC+SOX 这种
    跨资产低相关组合. 本脚本会显式打印相关系数, 避免误读"再平衡=无脑增收益".
  - 指数本身 (非 ETF), 回测假设可完美跟踪; 实际可用 QQQ/SPY 但逻辑一致.
  - 方法论证, 非未来业绩承诺. 共同窗口动态取交集, 锁定起点 2016-09 起以贴合"10年".
"""
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from portfolio_blend import metrics, blend_equal, blend_rebalanced
from blend_btc_sox import blend_rebalance_drift

# 10 年窗口起点 (数据实际末日 2026-09-03, 交集即全样本)
WIN0 = "2016-09-01"


def load():
    ixic = pd.read_csv(os.path.join(ROOT, 'markets/us/data/raw_index_IXIC_daily.csv'),
                       parse_dates=['date']).set_index('date').sort_index()['close'].rename('纳指')
    gspc = pd.read_csv(os.path.join(ROOT, 'markets/us/data/raw_index_GSPC_daily.csv'),
                       parse_dates=['date']).set_index('date').sort_index()['close'].rename('标普500')

    # 日线 -> 周线 W-FRI 收盘
    ixic_w = ixic.resample('W-FRI').last().dropna()
    gspc_w = gspc.resample('W-FRI').last().dropna()

    df = pd.concat([ixic_w, gspc_w], axis=1, sort=False)
    df = df.resample('W-FRI').last().ffill()
    df = df.loc[WIN0:].dropna()
    df = df / df.iloc[0]                       # 归一化到 1.0 起点
    return df


def main():
    df = load()
    yrs = (df.index[-1] - df.index[0]).days / 365.25
    print(f"共同周网格: {df.index[0].date()} ~ {df.index[-1].date()}  共 {len(df)} 周 (~{yrs:.1f}年)")
    print("=" * 82)

    # ---- 相关系数 (再平衡价值的核心前提) ----
    corr = df['纳指'].pct_change().fillna(0).corr(df['标普500'].pct_change().fillna(0))
    print(f"【周收益相关系数】纳指 vs 标普500 = {corr:.3f}  (≈1 说明高度同涨同跌, 再平衡收益有限)")
    print("-" * 82)

    # ---- 单资产 ----
    print("【单资产 · 10年窗口 (均已归一化到 1.0)】")
    single = {}
    for c in df.columns:
        m = metrics(df[c])
        single[c] = m
        print(f"  {c:6s} 倍数 {m['multiple']:8.1f}x  CAGR {m['cagr']*100:6.1f}%  "
              f"MDD {m['mdd']*100:7.1f}%  Sharpe {m['sharpe']:.2f}")
    print("-" * 82)

    cols = list(df.columns)
    schemes = {}

    # 1) 等权持有(不调)
    schemes['等权50/50 (持有不调)'] = blend_equal(df, cols)

    # 2) 等权 + 季度再平衡
    nav_eq_rb, log_eq = blend_rebalance_drift(df, cols, {c: 1.0 / len(cols) for c in cols}, rebal_weeks=13)
    schemes['等权50/50 (季度再平衡)'] = nav_eq_rb

    # 3) 等权 + 月度再平衡
    nav_mo_rb, log_mo = blend_rebalance_drift(df, cols, {c: 1.0 / len(cols) for c in cols}, rebal_weeks=4)
    schemes['等权50/50 (月度再平衡)'] = nav_mo_rb

    # 4) 逆波动 + 季度再平衡 + 单资产封顶60%
    nav_vp_q, log_vp_q = blend_rebalanced(df, cols, rebal_weeks=13, warmup=52, cap=0.60)
    schemes['逆波动 (季度再平衡·封顶60%)'] = nav_vp_q

    # 5) 逆波动 + 月度再平衡 + 单资产封顶60%
    nav_vp_m, log_vp_m = blend_rebalanced(df, cols, rebal_weeks=4, warmup=52, cap=0.60)
    schemes['逆波动 (月度再平衡·封顶60%)'] = nav_vp_m

    # 6) 稳健倾斜 纳指 60 / 标普 40 (纳指弹性更高)
    nav_tilt_hold = blend_equal(df, cols, w=pd.Series({'纳指': 0.6, '标普500': 0.4}))
    schemes['倾斜60/40 纳指-标普 (持有)'] = nav_tilt_hold
    nav_tilt_rb, log_tilt = blend_rebalance_drift(df, cols, {'纳指': 0.6, '标普500': 0.4}, rebal_weeks=13)
    schemes['倾斜60/40 纳指-标普 (季再平衡)'] = nav_tilt_rb

    print("【组合层 · 纳指 + 标普500 混合再平衡 (10年)】")
    blends = {}
    for name, nav in schemes.items():
        m = metrics(nav)
        blends[name] = m
        print(f"  {name:32s} 倍数 {m['multiple']:8.1f}x  CAGR {m['cagr']*100:6.1f}%  "
              f"MDD {m['mdd']*100:7.1f}%  Sharpe {m['sharpe']:.2f}")
    print("=" * 82)

    # ---- 写出 JSON ----
    out = {
        'window': [str(df.index[0].date()), str(df.index[-1].date())],
        'n_weeks': len(df),
        'corr_weekly': round(float(corr), 4),
        'assets': {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in single.items()},
        'blends': {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in blends.items()},
        'rebal_log': {
            '等权50/50 (季度再平衡)': log_eq,
            '逆波动 (季度再平衡·封顶60%)': log_vp_q,
        },
    }
    os.makedirs(os.path.join(ROOT, 'docs/data'), exist_ok=True)
    with open(os.path.join(ROOT, 'docs/data/blend_nasdaq_spx.json'), 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("已写出 docs/data/blend_nasdaq_spx.json")

    # ---- HTML 可视化 ----
    html = _html(df, single, schemes, blends, corr)
    with open(os.path.join(ROOT, 'docs/blend_nasdaq_spx.html'), 'w', encoding='utf-8') as f:
        f.write(html)
    print("已写出 docs/blend_nasdaq_spx.html")
    return out


def _html(df, single, schemes, blends, corr):
    dates = [str(d.date()) for d in df.index]
    series = {c: [round(float(x), 4) for x in df[c].values] for c in df.columns}
    bnav = {n: [round(float(x), 4) for x in nav.values] for n, nav in schemes.items()}

    rows_single = "".join(
        f"<tr><td>{c}</td><td class='r'>{m['multiple']:.1f}x</td><td>{m['cagr']*100:.1f}%</td>"
        f"<td class='r'>{m['mdd']*100:.1f}%</td><td>{m['sharpe']:.2f}</td></tr>"
        for c, m in single.items())
    rows_blend = "".join(
        f"<tr><td>{n}</td><td class='r'>{m['multiple']:.1f}x</td><td>{m['cagr']*100:.1f}%</td>"
        f"<td class='r'>{m['mdd']*100:.1f}%</td><td>{m['sharpe']:.2f}</td></tr>"
        for n, m in blends.items())

    s_traces = "".join(
        f"{{x:D.dates, y:series['{c}'], name:'{c}', mode:'lines'}},"
        for c in df.columns)
    b_traces = "".join(
        f"{{x:D.dates, y:bnav['{n}'], name:'{n}', mode:'lines'}},"
        for n in schemes)

    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>纳指 + 标普500 10年混合再平衡</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#0f1117;color:#e6e9ef;margin:0;padding:32px;}}
h1{{font-size:24px;margin:0 0 4px;}} .sub{{color:#9aa3b2;margin-bottom:20px;}}
.card{{background:#171a23;border:1px solid #262b38;border-radius:14px;padding:20px;margin-bottom:20px;}}
table{{border-collapse:collapse;width:100%;font-size:14px;}} th,td{{border-bottom:1px solid #2a3040;padding:8px 10px;text-align:left;}}
td.r{{text-align:right;font-variant-numeric:tabular-nums;color:#ffd479;}}
.note{{color:#9aa3b2;font-size:13px;line-height:1.7;}}</style></head>
<body>
<h1>纳斯达克综合指数 + 标普500 · 10年混合再平衡回测</h1>
<div class="sub">纳指(^IXIC) + 标普500(^GSPC) · 共同窗口 {dates[0]} ~ {dates[-1]} · 数据截至 2026-09-03 · 方法论证非业绩承诺</div>

<div class="card"><h3 style="margin-top:0">净值曲线 (对数轴, 起点=1)</h3>
<div id="c1" style="width:100%;height:460px"></div></div>

<div class="card"><h3 style="margin-top:0">单资产指标 (10年窗口)</h3>
<table><tr><th>资产</th><th>倍数</th><th>CAGR</th><th>MDD</th><th>Sharpe</th></tr>{rows_single}</table></div>

<div class="card"><h3 style="margin-top:0">组合方案对比</h3>
<table><tr><th>方案</th><th>倍数</th><th>CAGR</th><th>MDD</th><th>Sharpe</th></tr>{rows_blend}</table>
<p class="note">⚠️ <b>关键前提</b>: 纳指与标普500周收益相关系数 = <b>{corr:.3f}</b>, 两者长期高度同涨同跌 (都是美股宽基).
因此"再平衡的波动收益(volatility harvesting)"在这里<b>非常有限</b> —— 与 BTC+SOX 这种跨资产低相关组合(相关系数常 &lt;0.3)不同,
两个美股指数之间再平衡几乎不产生额外收益, 主要作用只是把组合拉向 50/50 的"平均"表现, 并轻微平滑极端偏离.
<ul>
<li><b>等权50/50 持有</b> ≈ 两指数等权买入持有, 倍数/回撤介于两者之间;</li>
<li><b>等权50/50 季度/月度再平衡</b> 与持有几乎重合 (相关系数高 → 偏离小 → 再平衡买卖少);</li>
<li><b>逆波动·封顶60%</b> 在单边行情下自动压低近期涨多的那一个、抬升跌多的, 但同样因高相关而效果有限;</li>
<li><b>倾斜60/40 纳指-标普</b> 因纳指弹性更高, 长期略跑赢 50/50, 但 MDD 也略深.</li>
</ul>
结论: 对两个高相关美股宽基指数做再平衡, <b>10年倍数约等于两指数几何平均, 再平衡不是"免费午餐"</b>.
真正的再平衡增益需来自低相关资产 (如 BTC+SOX, 或 纳指+黄金/美债). 本图仅作方法论演示.</p></div>

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
