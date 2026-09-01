"""
portfolio_blend.py — 跨市场组合层 (mx_auto_strategy)  ·  v6.18 真值刷新版
================================================================
把三个子系统的周度 NAV 回测产出, 对齐到共同周网格, 拼出跨市场组合层,
论证「分散配置」能在不牺牲太多收益的前提下压低整体回撤。

输入 (v6.18 审计后刷新, 均为真实引擎产出):
  - A股 : docs/data/nav.json  windows['full']['optimized']['mult']
          (v6.18 权威口径: 腾讯后复权 + momentum26 + 核心卫星0.5 + 死叉 + use_tech=False + trend_filter=False
           = 18.185x / CAGR22.31% / MDD-33.31%; export_nav.py 已对齐此配置, nav.json 与头条自洽。)
  - 美股 : markets/us/data/us_nav_ai.csv  optimized_nav  (99.85x, 真实面板 + 公允 BS 期权定价, 头条)
  - 加密 : markets/crypto/crypto_options_bt.py  run_bt(默认)  (448.6x, 期权三件套 + 封顶4.5x + 减半关, 头条)

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
sys.path.insert(0, os.path.join(ROOT, 'markets', 'crypto'))

# 共同窗口锁定为 v6.18 官方真值窗口: 三市场对齐到 [2017-08-11, 2026-08-14] (471 周周五网格).
# 原因: 各子面板数据会随刷新向前/向后延伸, 若任由 inner-join 动态决定起点, 共同窗口会漂移,
# 导致组合端值静默改变(既定"真值"被改写)。锁定窗口后 CI 重算必然零差异、站点稳定。
WIN0, WIN1 = "2017-08-11", "2026-08-14"


def load_series():
    # ---- A股 (nav.json 引擎 export 实序列) ----
    d = json.load(open(os.path.join(ROOT, 'docs/data/nav.json')))
    w = d['windows']['full']['optimized']
    ash = pd.Series(w['mult'], index=pd.to_datetime(w['dates']), name='A股(nav.json)')

    # ---- 美股 (真实面板 + 公允 BS 期权定价, 头条 99.85x) ----
    us = pd.read_csv(os.path.join(ROOT, 'markets', 'us', 'data', 'us_nav_ai.csv'),
                     parse_dates=['date']).set_index('date')['optimized_nav'].rename('美股(期权增强99.85x)')

    # ---- 加密 (期权三件套引擎, 头条 448.6x) ----
    from markets.crypto import crypto_options_bt as m
    px = m._load_default()
    r = m.run_bt(px, dict(m.DEFAULT_CFG), label='crypto_opts')
    cry = pd.Series(r['nav'], index=pd.to_datetime(px.index), name='加密(期权增强448.6x)')
    print(f"  [加密引擎] 448 档实跑: {r['multiple']:.1f}x | CAGR {r['cagr']*100:.1f}% | MDD {r['mdd']*100:.1f}%")

    raw = pd.concat([ash, us, cry], axis=1, sort=False)
    raw = raw.resample('W-FRI').last().ffill()
    # 锁定共同窗口(见 WIN0/WIN1 注释), 防止数据刷新导致组合端值漂移
    raw = raw.loc[WIN0:WIN1]
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


def blend_rebalanced(df, cols, rebal_weeks=13, warmup=52, cap=0.60):
    """真分配器 (区别于每日漂移的 volparity):
    用回看波动算目标权重 = 逆波动, 单市场封顶 cap (防单市场独大),
    每 rebal_weeks 周(默认13=季度)再平衡回目标权重; 区间内含息持有, 权重恒定。
    返回 (nav序列, 再平衡日志[(日期, 权重dict)])。
    """
    rets = df[cols].pct_change().fillna(0.0)
    n = len(cols)
    idx = df.index
    w = pd.Series(1.0 / n, index=cols)
    nav = [1.0]
    rebal_log = []
    for t in range(1, len(idx)):
        r = (rets.iloc[t] * w).sum()
        nav.append(nav[-1] * (1.0 + r))
        if t >= warmup and (t % rebal_weeks) == 0:
            vol = rets.iloc[max(0, t - warmup):t].std().replace(0, np.nan)
            inv = 1.0 / vol
            wt = (inv / inv.sum()).clip(upper=cap).fillna(1.0 / n)
            wt = wt / wt.sum()
            rebal_log.append((str(idx[t].date()),
                              {c: round(float(wt[c]), 3) for c in cols}))
            w = wt
    out = pd.Series(nav, index=idx,
                    name=f'波动平价(季再平衡·封顶{int(cap*100)}%)')
    return out, rebal_log


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

    # ---- 真分配器: 季度再平衡 + 逆波动目标权重 + 单市场封顶 ----
    rebal_nav, rebal_log = blend_rebalanced(df, list(df.columns))
    schemes = {
        '等权(1/3)':        blend_equal(df, list(df.columns)),
        '波动平价(逆波动)':  blend_volparity(df, list(df.columns)),
        '稳健倾斜(.4/.4/.2 加密)': blend_equal(df, list(df.columns),
                                   w=pd.Series({df.columns[0]: .4, df.columns[1]: .4, df.columns[2]: .2})),
        '波动平价(季再平衡·封顶60%)': rebal_nav,
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
        'rebal_log': rebal_log,
    }
    print("\n【再平衡日志 (季度 · 逆波动目标权重 · 单市场封顶60%)】")
    for d, w in rebal_log:
        print("  " + d + ": " + "  ".join(f"{k} {v:.2f}" for k, v in w.items()))
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
「波动平价(季再平衡·封顶60%)」为真正可执行分配器: 每13周按回看波动重算逆波动目标权重(单市场≤60%), 区间内含息持有。
A股序列来自 nav.json (v6.18 权威配置, 已与头条 18.185x 对齐)。本图仅作方法论演示, 非业绩承诺。</p></div>

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
