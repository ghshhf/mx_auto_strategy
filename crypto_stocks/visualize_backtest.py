# -*- coding: utf-8 -*-
"""可视化 Crypto50 V6 回测 (复用 crypto_options_bt 引擎, 期权已临时关闭).

生成交互式 HTML:
  - 主动策略: 纯现货轮动 + 减半减仓 (期权四开关全关)
  - 被动策略 A: 买入整个代币池 + 每月再平衡 + 等权
  - 被动策略 B: 买入整个代币池 + 每月再平衡 + 市值加权 (当前市值快照)
  - 基准: BTC / ETH 买入持有
含净值曲线(对数) + 回撤对比 + 年度收益 + 结果对比表.
用法: python visualize_backtest.py
"""
import os
import sys
import json
import urllib.request
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))  # 仓库根, 供 net_config
import net_config  # noqa: E402
import crypto_adoption_v2 as c  # noqa: E402
import crypto_options_bt as eng  # noqa: E402

DATA = os.path.join(HERE, 'data', 'weekly_adjclose_crypto50.csv')
# 报告统一出口: docs/reports/crypto/ (门户 Pages 只发布 docs/, 报告中心自动扫描该目录)
_REPORTS = os.path.join(os.path.dirname(HERE), 'docs', 'reports', 'crypto')
os.makedirs(_REPORTS, exist_ok=True)
OUT = os.path.join(_REPORTS, 'backtest_report.html')

# 池子 → CoinGecko id 映射 (覆盖全部 35 币)
CG = {
    'BTC': 'bitcoin', 'ETH': 'ethereum', 'SOL': 'solana', 'BNB': 'binancecoin',
    'ADA': 'cardano', 'AVAX': 'avalanche-2', 'DOT': 'polkadot', 'LINK': 'chainlink',
    'POL': 'polygon-ecosystem-token', 'TRX': 'tron', 'UNI': 'uniswap', 'NEAR': 'near',
    'APT': 'aptos', 'GLM': 'golem', 'AAVE': 'aave', 'FIL': 'filecoin',
    'BCH': 'bitcoin-cash', 'DYDX': 'dydx', 'ZEC': 'zcash', 'JUP': 'jupiter',
    'ONDO': 'ondo-finance', 'GRAM': 'the-open-network', 'XLM': 'stellar',
    'LTC': 'litecoin', 'ICP': 'internet-computer', 'RENDER': 'render-token',
    'XRP': 'ripple', 'PENDLE': 'pendle', 'OKB': 'okb', 'INJ': 'injective-protocol',
    'RAY': 'raydium', 'HYPE': 'hyperliquid', 'GT': 'gatechain-token',
    'HBAR': 'hedera-hashgraph', 'ETHFI': 'ether-fi',
}


def fetch_mcap():
    """当前市值快照 (走 3067 代理). 失败返回 None."""
    try:
        ids = ','.join(CG[s] for s in c.ALL_COINS if s in CG)
        url = ('https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids='
               + ids + '&order=market_cap_desc&per_page=250&page=1&sparkline=false')
        # 代理统一走 net_config 解析 (存活探测 + 回退默认 3067)
        opener = net_config.proxy_opener()
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = json.load(opener.open(req, timeout=40))
        rev = {d['id']: d for d in data}
        out = {}
        for sym, cid in CG.items():
            if cid in rev and rev[cid].get('market_cap'):
                out[sym] = float(rev[cid]['market_cap'])
        print(f'[mcap] 取到 {len(out)}/{len(c.ALL_COINS)} 币市值')
        return out
    except Exception as e:
        print('[mcap] 拉取失败, 跳过市值加权:', repr(e))
        return None


def metrics(nav):
    r = nav.pct_change().dropna()
    mult = float(nav.iloc[-1])
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = mult ** (1 / yrs) - 1 if yrs > 0 and mult > 0 else 0.0
    dd = nav / nav.cummax() - 1.0
    mdd = float(dd.min())
    sharpe = float(r.mean() / r.std() * (52 ** 0.5)) if r.std() > 0 else 0.0
    return mult, cagr, mdd, sharpe


def passive_nav(px, weight_fn):
    """买入整个池 + 每月再平衡. weight_fn(avail_syms, date) -> {sym: w} 求和为1."""
    dates = px.index
    cols = list(px.columns)
    nav = pd.Series(index=dates, dtype=float)
    nav.iloc[0] = 1.0
    holdings = None
    prev = dates[0]
    for i in range(1, len(dates)):
        cur = dates[i]
        ret = px.iloc[i] / px.iloc[i - 1] - 1.0
        if holdings is None:
            avail = [s for s in cols if pd.notna(px.iloc[i - 1][s])]
            w = weight_fn(avail, dates[i - 1])
            holdings = {s: w.get(s, 0.0) for s in cols}
        wk = 0.0
        for s in cols:
            h = holdings.get(s, 0.0)
            if h != 0 and pd.notna(ret[s]):
                wk += h * ret[s]
        nav.iloc[i] = nav.iloc[i - 1] * (1.0 + wk)
        if cur.month != prev.month or cur.year != prev.year:
            avail = [s for s in cols if pd.notna(px.iloc[i][s])]
            w = weight_fn(avail, cur)
            holdings = {s: w.get(s, 0.0) for s in cols}
        prev = cur
    return nav


def main():
    px = pd.read_csv(DATA, index_col=0, parse_dates=True).sort_index().dropna(how='all')
    pool = [s for s in c.ALL_COINS if s in px.columns]
    print(f'[pool] 参与回测 {len(pool)} 币: {pool}')

    # ---- 主动策略 ----
    res = eng.run_bt(px, label='Crypto50 V6 (期权关·纯现货+减半减仓)')
    nav_act = res['nav']
    common = nav_act.index

    # ---- 基准 ----
    btc = (px['BTC'] / px['BTC'].iloc[0]).reindex(common)
    eth = (px['ETH'] / px['ETH'].iloc[0]).reindex(common)

    # ---- 被动: 等权 ----
    def w_equal(avail, d):
        n = len(avail)
        return {s: 1.0 / n for s in avail}
    nav_eq = passive_nav(px, w_equal).reindex(common)

    # ---- 被动: 市值加权 ----
    mcap = fetch_mcap()
    nav_mc = None
    if mcap:
        def w_mcap(avail, d):
            vals = {s: mcap[s] for s in avail if s in mcap}
            tot = sum(vals.values())
            if tot <= 0:
                n = len(avail)
                return {s: 1.0 / n for s in avail}
            return {s: v / tot for s, v in vals.items()}
        nav_mc = passive_nav(px, w_mcap).reindex(common)

    # ---- 指标 ----
    m_act = metrics(nav_act)
    m_eq = metrics(nav_eq)
    m_mc = metrics(nav_mc) if nav_mc is not None else None
    btc_mult = float(btc.dropna().iloc[-1])
    eth_mult = float(eth.dropna().iloc[-1])
    weeks = len(common)

    # ---- 绘图 ----
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.5, 0.25, 0.25],
        subplot_titles=('净值曲线 (对数轴)', '回撤对比', '年度收益率 % (主动)'),
        vertical_spacing=0.07,
    )
    fig.add_trace(go.Scatter(x=common, y=nav_act, name='主动(现货+减半减仓)',
                             line=dict(color='#d62728', width=2.4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=common, y=nav_eq, name='被动·等权',
                             line=dict(color='#1f77b4', width=1.6)), row=1, col=1)
    if nav_mc is not None:
        fig.add_trace(go.Scatter(x=common, y=nav_mc, name='被动·市值加权',
                                 line=dict(color='#2ca02c', width=1.6)), row=1, col=1)
    fig.add_trace(go.Scatter(x=common, y=btc, name='BTC 持有',
                             line=dict(color='#7f7f7f', width=1.2, dash='dot')), row=1, col=1)
    fig.add_trace(go.Scatter(x=common, y=eth, name='ETH 持有',
                             line=dict(color='#bcbcbc', width=1.2, dash='dot')), row=1, col=1)
    fig.update_yaxes(type='log', row=1, col=1)

    dd_act = nav_act / nav_act.cummax() - 1.0
    dd_eq = nav_eq / nav_eq.cummax() - 1.0
    fig.add_trace(go.Scatter(x=common, y=dd_act * 100, name='主动 回撤%',
                             fill='tozeroy', line=dict(color='#d62728', width=1)), row=2, col=1)
    fig.add_trace(go.Scatter(x=common, y=dd_eq * 100, name='被动·等权 回撤%',
                             line=dict(color='#1f77b4', width=1)), row=2, col=1)

    yr = nav_act.groupby(nav_act.index.year).last()
    yearly = (yr.pct_change().dropna() * 100).round(1)
    fig.add_trace(go.Bar(x=yearly.index.astype(str), y=yearly.values, name='年度 %',
                         marker_color=np.where(yearly.values >= 0, '#2ca02c', '#d62728')),
                  row=3, col=1)
    fig.update_layout(
        height=960, hovermode='x unified',
        title='Crypto50 V6 回测可视化 (期权模块已临时关闭) · 主动 vs 被动买入全池',
        legend=dict(orientation='h', y=1.02, x=0),
        margin=dict(t=60, l=60, r=30, b=40),
    )
    fig.update_yaxes(title_text='倍数', row=1, col=1)
    fig.update_yaxes(title_text='%', row=2, col=1)
    fig.update_yaxes(title_text='%', row=3, col=1)

    plot_div = fig.to_html(include_plotlyjs=True, full_html=False)

    # ---- 对比表 ----
    def row(name, m):
        return (f"<tr><td style='text-align:left;font-weight:600;'>{name}</td>"
                f"<td>{m[0]:,.1f}x</td><td>{m[1]*100:,.1f}%</td>"
                f"<td>{m[2]*100:,.1f}%</td><td>{m[3]:,.2f}</td></tr>")
    mcap_note = ('当前市值快照作权重目标(历史市值序列未取得)' if mcap
                 else '市值拉取失败, 未计算')
    table = f"""
    <table style="border-collapse:collapse;width:100%;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:13px;margin:0 0 6px;">
      <thead><tr style="background:#f7fafc;">
        <th style="border:1px solid #e2e8f0;padding:8px;text-align:left;">策略</th>
        <th style="border:1px solid #e2e8f0;padding:8px;">总倍数</th>
        <th style="border:1px solid #e2e8f0;padding:8px;">CAGR</th>
        <th style="border:1px solid #e2e8f0;padding:8px;">最大回撤</th>
        <th style="border:1px solid #e2e8f0;padding:8px;">Sharpe</th>
      </tr></thead>
      <tbody>
        {row('主动 (现货轮动+减半减仓, 期权关)', m_act)}
        {row('被动·等权 (买全池/月平衡)', m_eq)}
        {row('被动·市值加权 (买全池/月平衡)', m_mc) if m_mc else ''}
        <tr style="background:#f7fafc;"><td style="border:1px solid #e2e8f0;padding:8px;text-align:left;font-weight:600;">BTC 持有</td><td colspan="4" style="border:1px solid #e2e8f0;padding:8px;text-align:left;">{btc_mult:,.1f}x</td></tr>
        <tr style="background:#f7fafc;"><td style="border:1px solid #e2e8f0;padding:8px;text-align:left;font-weight:600;">ETH 持有</td><td colspan="4" style="border:1px solid #e2e8f0;padding:8px;text-align:left;">{eth_mult:,.1f}x</td></tr>
      </tbody>
    </table>
    <p style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:12px;color:#a0aec0;margin:0 0 10px;">
      样本 {common[0].date()} ~ {common[-1].date()} · {weeks} 周 · 池子 {len(pool)} 币 · 被动策略每月首个交易日再平衡, 新上线代币于下个再平衡日纳入 · 市值加权: {mcap_note}
    </p>
    """

    html = (
        '<!doctype html><html lang="zh"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Crypto50 V6 回测可视化</title></head><body style="margin:16px;">'
        + table + plot_div + '</body></html>'
    )
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(html)
    print('saved ->', OUT)
    print(f'主动 {m_act[0]:,.1f}x | 等权 {m_eq[0]:,.1f}x'
          + (f' | 市值加权 {m_mc[0]:,.1f}x' if m_mc else '')
          + f' | BTC {btc_mult:,.1f}x | ETH {eth_mult:,.1f}x')


if __name__ == '__main__':
    main()
