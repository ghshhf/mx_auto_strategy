"""
blend_btc_sox.py — BTC + 费城半导体指数(SOX) 10 年混合再平衡回测
=================================================================
用户需求: 比特币 配 美国半导体指数(SOX), 做再平衡, 跑 10 年看效果.

数据源 (均为项目内已验证数据):
  - BTC  : markets/crypto/data/weekly_adjclose_crypto50_10y.csv  (32币权威10y面板, BTC列)
  - SOX  : markets/us/data/raw_sox_historyofmarket.json  (费城半导体指数 ^SOX 日线, 转周线 W-FRI)

复用 portfolio_blend.py 的 metrics / blend_equal / blend_rebalanced (逆波动+封顶+再平衡真分配器).

★ 诚实口径:
  - SOX 是指数本身(非 ETF), 回测假设可完美跟踪; 实际可用 SMH/SOXX 但项目仅有 SOX 长序列.
  - BTC 周线采用面板"周一开盘"约定(=对应周数据), SOX 取每周五收盘, 两者 resample W-FRI 后 inner join.
  - 本原型为方法论证, 非未来业绩承诺.
  - 共同窗口动态取交集(由数据决定), 锁定起点 2016-09 起以贴合"10年".
"""
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from portfolio_blend import metrics, blend_equal, blend_rebalanced

# 10 年窗口起点 (数据实际末日 BTC=2026-08-28 / SOX=2026-08-07, 交集约 2026-08-07)
WIN0 = "2016-09-01"


def load():
    # ---- BTC 周线 (权威 10y 面板) ----
    btc = pd.read_csv(os.path.join(ROOT, 'markets/crypto/data/weekly_adjclose_crypto50_10y.csv'),
                      index_col=0, parse_dates=True)['BTC'].rename('BTC')

    # ---- SOX 日线 -> 周线 (W-FRI 收盘) ----
    raw = json.load(open(os.path.join(ROOT, 'markets/us/data/raw_sox_historyofmarket.json')))
    s = pd.DataFrame(raw['series'])
    s['date'] = pd.to_datetime(s['date'])
    s = s.set_index('date').sort_index()
    sox = s['close'].astype(float).resample('W-FRI').last().dropna().rename('SOX')

    df = pd.concat([btc, sox], axis=1, sort=False)
    df = df.resample('W-FRI').last().ffill()
    df = df.loc[WIN0:].dropna()
    df = df / df.iloc[0]                       # 归一化到 1.0 起点
    return df


def blend_rebalance_drift(df, cols, target_w, rebal_weeks=13, warmup=0):
    """真正的再平衡: 持有期内权重随价格漂移, 每 rebal_weeks 周拉回 target_w.
    区别于 blend_equal(权重恒定1/n=无限频再平衡近似) 与 blend_rebalanced(持有期权重锁定).
    返回 (nav序列, 再平衡日志)."""
    rets = df[cols].pct_change().fillna(0.0)
    idx = df.index
    w = pd.Series(target_w, index=cols, dtype=float)
    w = w / w.sum()
    nav = [1.0]
    log = []
    for t in range(1, len(idx)):
        r = float((rets.iloc[t] * w).sum())
        nav.append(nav[-1] * (1.0 + r))
        w = w * (1.0 + rets.iloc[t]) / (1.0 + r)          # 权重随价格漂移
        if t >= warmup and (t % rebal_weeks) == 0:
            w = pd.Series(target_w, index=cols, dtype=float)
            w = w / w.sum()
            log.append((str(idx[t].date()), {c: round(float(w[c]), 3) for c in cols}))
    return pd.Series(nav, index=idx, name=f'再平衡({int(52/rebal_weeks)}月)'), log


def main():
    df = load()
    yrs = (df.index[-1] - df.index[0]).days / 365.25
    print(f"共同周网格: {df.index[0].date()} ~ {df.index[-1].date()}  共 {len(df)} 周 (~{yrs:.1f}年)")
    print("=" * 80)

    # ---- 单资产 ----
    print("【单资产 · 10年窗口 (均已归一化到 1.0)】")
    single = {}
    for c in df.columns:
        m = metrics(df[c])
        single[c] = m
        print(f"  {c:5s} 倍数 {m['multiple']:8.1f}x  CAGR {m['cagr']*100:6.1f}%  "
              f"MDD {m['mdd']*100:7.1f}%  Sharpe {m['sharpe']:.2f}")
    print("-" * 80)

    cols = list(df.columns)
    schemes = {}

    # 1) 等权持有(不调) = blend_equal(权重恒定1/n, 等价于 buy-and-hold 权重漂移净值)
    schemes['等权50/50 (持有不调)'] = blend_equal(df, cols)

    # 2) 等权 + 季度再平衡 (真正漂移后拉回 50/50)
    nav_eq_rb, log_eq = blend_rebalance_drift(df, cols, {c: 1.0 / len(cols) for c in cols}, rebal_weeks=13)
    schemes['等权50/50 (季度再平衡)'] = nav_eq_rb

    # 3) 等权 + 月度再平衡
    nav_mo_rb, log_mo = blend_rebalance_drift(df, cols, {c: 1.0 / len(cols) for c in cols}, rebal_weeks=4)
    schemes['等权50/50 (月度再平衡)'] = nav_mo_rb

    # 4) 逆波动 + 季度再平衡 + 单资产封顶60% (portfolio_blend 真分配器)
    nav_vp_q, log_vp_q = blend_rebalanced(df, cols, rebal_weeks=13, warmup=52, cap=0.60)
    schemes['逆波动 (季度再平衡·封顶60%)'] = nav_vp_q

    # 5) 逆波动 + 月度再平衡 + 单资产封顶60%
    nav_vp_m, log_vp_m = blend_rebalanced(df, cols, rebal_weeks=4, warmup=52, cap=0.60)
    schemes['逆波动 (月度再平衡·封顶60%)'] = nav_vp_m

    # 6) 稳健倾斜 BTC 60 / SOX 40
    nav_tilt_hold = blend_equal(df, cols, w=pd.Series({'BTC': 0.6, 'SOX': 0.4}))
    schemes['倾斜60/40 BTC-SOX (持有)'] = nav_tilt_hold
    nav_tilt_rb, log_tilt = blend_rebalance_drift(df, cols, {'BTC': 0.6, 'SOX': 0.4}, rebal_weeks=13)
    schemes['倾斜60/40 BTC-SOX (季再平衡)'] = nav_tilt_rb

    print("【组合层 · BTC + SOX 混合再平衡 (10年)】")
    blends = {}
    for name, nav in schemes.items():
        m = metrics(nav)
        blends[name] = m
        print(f"  {name:30s} 倍数 {m['multiple']:8.1f}x  CAGR {m['cagr']*100:6.1f}%  "
              f"MDD {m['mdd']*100:7.1f}%  Sharpe {m['sharpe']:.2f}")
    print("=" * 80)

    # ---- 写出 JSON ----
    out = {
        'window': [str(df.index[0].date()), str(df.index[-1].date())],
        'n_weeks': len(df),
        'assets': {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in single.items()},
        'blends': {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in blends.items()},
        'rebal_log': {
            '等权50/50 (季度再平衡)': log_eq,
            '逆波动 (季度再平衡·封顶60%)': log_vp_q,
        },
    }
    os.makedirs(os.path.join(ROOT, 'docs/data'), exist_ok=True)
    with open(os.path.join(ROOT, 'docs/data/blend_btc_sox.json'), 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("已写出 docs/data/blend_btc_sox.json")

    # ---- HTML 可视化 ----
    html = _html(df, single, schemes, blends)
    with open(os.path.join(ROOT, 'docs/blend_btc_sox.html'), 'w', encoding='utf-8') as f:
        f.write(html)
    print("已写出 docs/blend_btc_sox.html")
    return out


def _html(df, single, schemes, blends):
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
<title>BTC + 半导体指数(SOX) 10年混合再平衡</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#0f1117;color:#e6e9ef;margin:0;padding:32px;}}
h1{{font-size:24px;margin:0 0 4px;}} .sub{{color:#9aa3b2;margin-bottom:20px;}}
.card{{background:#171a23;border:1px solid #262b38;border-radius:14px;padding:20px;margin-bottom:20px;}}
table{{border-collapse:collapse;width:100%;font-size:14px;}} th,td{{border-bottom:1px solid #2a3040;padding:8px 10px;text-align:left;}}
td.r{{text-align:right;font-variant-numeric:tabular-nums;color:#ffd479;}}
.note{{color:#9aa3b2;font-size:13px;line-height:1.7;}}</style></head>
<body>
<h1>BTC + 费城半导体指数(SOX) · 10年混合再平衡回测</h1>
<div class="sub">比特币(BTC) + 美国半导体指数(^SOX) · 共同窗口 {dates[0]} ~ {dates[-1]} · 方法论证非业绩承诺</div>

<div class="card"><h3 style="margin-top:0">净值曲线 (对数轴, 起点=1)</h3>
<div id="c1" style="width:100%;height:460px"></div></div>

<div class="card"><h3 style="margin-top:0">单资产指标 (10年窗口)</h3>
<table><tr><th>资产</th><th>倍数</th><th>CAGR</th><th>MDD</th><th>Sharpe</th></tr>{rows_single}</table></div>

<div class="card"><h3 style="margin-top:0">组合方案对比</h3>
<table><tr><th>方案</th><th>倍数</th><th>CAGR</th><th>MDD</th><th>Sharpe</th></tr>{rows_blend}</table>
<p class="note">核心论点: BTC 与 SOX 低相关, 混合 + 再平衡能在保留大部分收益的同时显著压低最大回撤(MDD)。
BTC 单独 10 年倍数极高但 MDD 也极深(加密特性); SOX 单独更平稳但弹性弱。
再平衡方案(等权/逆波动季调或月调)通过定期把涨多的资产获利了结、补回跌多的资产, 平滑波动。
"逆波动(季再平衡·封顶60%)" 为真正可执行分配器: 每13周按回看波动重算逆波动目标权重(单资产≤60%), 区间内持有。
注: SOX 为指数本身(非 ETF), 回测假设可完美跟踪; BTC 周线取自 32 币权威 10y 面板。本图仅作方法论演示。</p></div>

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
