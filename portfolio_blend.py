"""
portfolio_blend.py — 跨市场组合层 (mx_auto_strategy)  ·  v6.18 真值刷新版
================================================================
把三个子系统的周度 NAV 回测产出, 对齐到共同周网格, 拼出跨市场组合层,
论证「分散配置」能在不牺牲太多收益的前提下压低整体回撤。

输入 (v6.18 审计后刷新, 均为真实引擎产出):
  - A股 : docs/data/nav.json  windows['full']['optimized']['mult']
          (引擎 export 配置, 端点 ~33x; v6.18 权威头条口径 = 18.185x / CAGR22.31% / MDD-33.31%,
           见 A 股回测章节。nav.json 该序列来自不同 export 配置, 此处如实使用并标注。)
  - 美股 : us_stocks/data/us_nav_ai.csv  optimized_nav  (99.85x, 真实面板 + 公允 BS 期权定价, 头条)
  - 加密 : crypto_stocks/crypto_options_bt.py  run_bt(默认)  (448.6x, 期权三件套 + 封顶4.5x + 减半关, 头条)

★ 诚实口径:
  - 加密真实倍数含幸存者偏差(现存主流币清单, 死币未纳入→偏高); 真实数据仅 2017 起。
  - 美股/加密期权层为公允定价下的可辩护值, 非「更对」的数字 (美股 93-183x 可信带)。
  - 本原型为方法论证, 非未来业绩承诺。
  - 三序列周收盘日不同, 统一 resample 到 W-FRI 再 inner join。
  - 共同窗口 = 三序列交集 (由数据动态决定, 见运行输出)。
"""
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'crypto_stocks'))


def load_series():
    # ---- A股 (nav.json 引擎 export 实序列) ----
    d = json.load(open(os.path.join(ROOT, 'docs/data/nav.json')))
    w = d['windows']['full']['optimized']
    ash = pd.Series(w['mult'], index=pd.to_datetime(w['dates']), name='A股(nav.json)')

    # ---- 美股 (真实面板 + 公允 BS 期权定价, 头条 99.85x) ----
    us = pd.read_csv(os.path.join(ROOT, 'us_stocks/data/us_nav_ai.csv'),
                     parse_dates=['date']).set_index('date')['optimized_nav'].rename('美股(期权增强99.85x)')

    # ---- 加密 (期权三件套引擎, 头条 448.6x) ----
    import crypto_options_bt as m
    px = m._load_default()
    r = m.run_bt(px, dict(m.DEFAULT_CFG), label='crypto_opts')
    cry = pd.Series(r['nav'], index=pd.to_datetime(px.index), name='加密(期权增强448.6x)')
    print(f"  [加密引擎] 448 档实跑: {r['multiple']:.1f}x | CAGR {r['cagr']*100:.1f}% | MDD {r['mdd']*100:.1f}%")

    raw = pd.concat([ash, us, cry], axis=1, sort=False)
    raw = raw.resample('W-FRI').last().ffill()
    df = raw.dropna()
    for c in df.columns:
        df[c] = df[c] / df[c].iloc[0]
    return df


def metrics(nav: pd.Series):
    nav = nav / nav.iloc[0]
    rets = nav.pct_change().dropna()
    weeks = len(rets)
    mult = float(nav.iloc[-1])
    cagr = float(nav.iloc[-1] ** (52.0 / weeks) - 1.0) if weeks > 0 else 0.0
    mdd = float((nav / nav.cummax() - 1.0).min())
    sharpe = float(rets.mean() / rets.std() * np.sqrt(52)) if rets.std() > 0 else 0.0
    return {'multiple': mult, 'cagr': cagr, 'mdd': mdd, 'sharpe': sharpe}


def blend_equal(df, cols, w=None):
    rets = df[cols].pct_change().fillna(0.0)
    if w is None:
        w = pd.Series(1.0 / len(cols), index=cols)
    return (1.0 + (rets * w).sum(axis=1)).cumprod()


def blend_volparity(df, cols, warmup=52):
    rets = df[cols].pct_change().fillna(0.0)
    vol = rets.rolling(warmup).std().shift(1)
    inv = 1.0 / vol
    w = inv.div(inv.sum(axis=1), axis=0).fillna(1.0 / len(cols))
    return (1.0 + (rets * w).sum(axis=1)).cumprod()


def main():
    df = load_series()
    print(f"共同周网格: {df.index[0].date()} ~ {df.index[-1].date()}  共 {len(df)} 周")
    print("=" * 78)

    print("【单市场 · 共同窗口 (均已归一化到 1.0 起点)】")
    single = {}
    for c in df.columns:
        m = metrics(df[c]); single[c] = m
        print(f"  {c:22s} 倍数 {m['multiple']:7.2f}x  CAGR {m['cagr']*100:5.1f}%  "
              f"MDD {m['mdd']*100:6.1f}%  Sharpe {m['sharpe']:.2f}")
    print("-" * 78)

    schemes = {
        '等权(1/3)':        blend_equal(df, list(df.columns)),
        '波动平价(逆波动)':  blend_volparity(df, list(df.columns)),
        '稳健倾斜(.4/.4/.2 加密)': blend_equal(df, list(df.columns),
                                   w=pd.Series({df.columns[0]: .4, df.columns[1]: .4, df.columns[2]: .2})),
    }
    print("【组合层 · 跨市场分散 (v6.18 真值刷新)】")
    blends = {}
    for name, nav in schemes.items():
        m = metrics(nav); blends[name] = m
        print(f"  {name:22s} 倍数 {m['multiple']:7.2f}x  CAGR {m['cagr']*100:5.1f}%  "
              f"MDD {m['mdd']*100:6.1f}%  Sharpe {m['sharpe']:.2f}")
    print("=" * 78)

    out = {
        'common_window': [str(df.index[0].date()), str(df.index[-1].date())],
        'n_weeks': len(df),
        'single': {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in single.items()},
        'blends': {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in blends.items()},
    }
    os.makedirs(os.path.join(ROOT, 'docs/data'), exist_ok=True)
    with open(os.path.join(ROOT, 'docs/data/portfolio_blend.json'), 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("已写出 docs/data/portfolio_blend.json")

    # ---- HTML 可视化 ----
    html = _html(df, single, schemes, blends)
    with open(os.path.join(ROOT, 'docs/portfolio_blend.html'), 'w', encoding='utf-8') as f:
        f.write(html)
    print("已写出 docs/portfolio_blend.html")
    return out


def _html(df, single, schemes, blends):
    dates = [str(d.date()) for d in df.index]
    series = {c: [round(float(x), 4) for x in df[c].values] for c in df.columns}
    bnav = {n: [round(float(x), 4) for x in nav.values] for n, nav in schemes.items()}

    rows_single = "".join(
        f"<tr><td>{c}</td><td>{m['multiple']:.2f}x</td><td>{m['cagr']*100:.1f}%</td>"
        f"<td>{m['mdd']*100:.1f}%</td><td>{m['sharpe']:.2f}</td></tr>"
        for c, m in single.items())
    rows_blend = "".join(
        f"<tr><td>{n}</td><td>{m['multiple']:.2f}x</td><td>{m['cagr']*100:.1f}%</td>"
        f"<td>{m['mdd']*100:.1f}%</td><td>{m['sharpe']:.2f}</td></tr>"
        for n, m in blends.items())

    s_traces = "".join(
        f"{{x:D.dates, y:series['{c}'], name:'{c}', mode:'lines'}},"
        for c in df.columns)
    b_traces = "".join(
        f"{{x:D.dates, y:bnav['{n}'], name:'{n}', mode:'lines'}},"
        for n in schemes)

    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>跨市场组合 · v6.18 真值刷新</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#0f1117;color:#e6e9ef;margin:0;padding:32px;}}
h1{{font-size:24px;margin:0 0 4px;}} .sub{{color:#9aa3b2;margin-bottom:20px;}}
.card{{background:#171a23;border:1px solid #262b38;border-radius:14px;padding:20px;margin-bottom:20px;}}
table{{border-collapse:collapse;width:100%;font-size:14px;}} th,td{{border-bottom:1px solid #2a3040;padding:8px 10px;text-align:left;}}
td.r{{text-align:right;font-variant-numeric:tabular-nums;color:#ffd479;}}
.note{{color:#9aa3b2;font-size:13px;line-height:1.7;}}</style></head>
<body>
<h1>跨市场组合层 · v6.18 真值刷新</h1>
<div class="sub">A股(nav.json) + 美股(期权增强99.85x) + 加密(期权增强448.6x) · 共同窗口 {dates[0]} ~ {dates[-1]} · 方法论证非承诺</div>

<div class="card"><h3 style="margin-top:0">单市场 vs 组合 (对数轴净值)</h3>
<div id="c1" style="width:100%;height:420px"></div></div>

<div class="card"><h3 style="margin-top:0">单市场指标 (共同窗口)</h3>
<table><tr><th>市场</th><th>倍数</th><th>CAGR</th><th>MDD</th><th>Sharpe</th></tr>{rows_single}</table></div>

<div class="card"><h3 style="margin-top:0">跨市场组合方案</h3>
<table><tr><th>方案</th><th>倍数</th><th>CAGR</th><th>MDD</th><th>Sharpe</th></tr>{rows_blend}</table>
<p class="note">组合层的核心论点: 三市场低相关, 等权/波动平价能在不牺牲太多倍数的前提下显著压低 MDD。
本图仅作方法论演示; A股序列取自 nav.json (引擎 export 配置, 端点与 v6.18 头条 18.185x 因配置不同而有差异, 如实标注)。</p></div>

<script>
const D = {{dates:D.dates, series:{series}, bnav:{bnav}}};
Plotly.newPlot('c1', [
  {s_traces}
  {b_traces}
], {{paper_bgcolor:'#171a23',plot_bgcolor:'#171a23',font:{{color:'#e6e9ef'}},
  yaxis:{{type:'log',title:'净值(对数,起点=1)'}}, xaxis:{{title:''}},
  legend:{{orientation:'h',y:1.08}}, margin:{{t:20,b:40,l:60,r:20}}}}, {{responsive:true}});
</script></body></html>"""


if __name__ == '__main__':
    main()
