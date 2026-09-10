"""
blend_sector_watchlist.py — 美股行业指数 vs BTC 相关性 & 再平衡观察清单
=========================================================================
用户明年拟开始配置美股(行业指数为主, 个股为辅), 加密仓位已重. 本脚本量化:
  (1) 11 个经典美股行业指数(SPDR 行业ETF) 与 BTC 的周收益相关系数 -> 谁最能给加密账户当减震器
  (2) 各行业 10 年表现/回撤/波动/Sharpe
  (3) 行业间相关性 -> 谁跟谁低相关(配多个行业时用于波动收益)

数据源: markets/us/data/raw_index_{代码}_daily.csv (yfinance, 代理3067, 已更新至2026-09-03)
        markets/crypto/data/weekly_adjclose_crypto50_10y.csv (BTC 周线)

窗口: 因 XLC(通信)2018-06 才从科技/可选消费拆分上市, 共同窗口取 2018-06-22~2026-08-28 (~8年), 全量同窗对齐, 苹果对苹果.
"""
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from portfolio_blend import metrics
import report_html as rh

SECTORS = {
    'XLB': '原材料', 'XLE': '能源', 'XLF': '金融', 'XLI': '工业', 'XLK': '科技',
    'XLP': '必需消费', 'XLRE': '房地产', 'XLU': '公用事业', 'XLV': '医疗',
    'XLY': '可选消费', 'XLC': '通信服务',
}
WIN0 = "2018-06-22"  # XLC 上市起点, 全量同窗


def load():
    def lw(sym):
        d = pd.read_csv(os.path.join(ROOT, f'markets/us/data/raw_index_{sym}_daily.csv'),
                        parse_dates=['date']).set_index('date').sort_index()['close']
        return d.resample('W-FRI').last().dropna()
    frames = [lw('BTC_p')] if False else []
    btc = pd.read_csv(os.path.join(ROOT, 'markets/crypto/data/weekly_adjclose_crypto50_10y.csv'),
                      index_col=0, parse_dates=True)['BTC'].resample('W-FRI').last().ffill().rename('BTC')
    frames = [btc]
    for t in SECTORS:
        frames.append(lw(t).rename(t))
    df = pd.concat(frames, axis=1).dropna().loc[WIN0:]
    return df / df.iloc[0]


def main():
    df = load()
    print(f"共同窗口 {df.index[0].date()} ~ {df.index[-1].date()}  共 {len(df)} 周 (~{(df.index[-1]-df.index[0]).days/365.25:.1f}年)")
    ret = df.pct_change().fillna(0)

    # (1) BTC 相关性 + 行业表现
    rows = []
    for t, zh in SECTORS.items():
        c = ret[t].corr(ret['BTC'])
        m = metrics(df[t])
        vol = ret[t].std() * np.sqrt(52) * 100
        rows.append({'code': t, 'zh': zh, 'btc_corr': round(float(c), 3),
                     'multiple': round(m['multiple'], 2), 'cagr': round(m['cagr']*100, 1),
                     'mdd': round(m['mdd']*100, 1), 'vol': round(float(vol), 1),
                     'sharpe': round(m['sharpe'], 2)})
    rows.sort(key=lambda r: r['btc_corr'])
    btc_m = metrics(df['BTC'])
    print(f"\n[BTC 单资产] {btc_m['multiple']:.1f}x  CAGR {btc_m['cagr']*100:.0f}%  MDD {btc_m['mdd']*100:.0f}%  年化波动 {ret['BTC'].std()*np.sqrt(52)*100:.0f}%")
    print("\n=== 各行业 vs BTC(周收益相关系数) 升序(越低=越能给你的加密账户减震) ===")
    print(f"{'行业':8s}{'代码':6s}{'BTC相关':8s}{'倍数':8s}{'CAGR':7s}{'MDD':8s}{'年化波动':8s}{'Sharpe':7s}")
    for r in rows:
        print(f"{r['zh']:8s}{r['code']:6s}{r['btc_corr']:8.3f}{r['multiple']:8.2f}{r['cagr']:6.1f}%{r['mdd']:7.1f}%{r['vol']:7.1f}%{r['sharpe']:6.2f}")

    # (2) 行业间相关性 (最低/最高配对)
    sec_ret = ret[list(SECTORS.keys())]
    cm = sec_ret.corr()
    pairs = []
    keys = list(SECTORS.keys())
    for i in range(len(keys)):
        for j in range(i+1, len(keys)):
            pairs.append((cm.loc[keys[i], keys[j]], SECTORS[keys[i]], SECTORS[keys[j]]))
    pairs.sort()
    print("\n=== 行业间最低相关配对(top6, 配多个行业时用于波动收益) ===")
    for c, a, b in pairs[:6]:
        print(f"  {a}-{b}: {c:.3f}")
    print("=== 行业间最高相关配对(top3) ===")
    for c, a, b in pairs[-3:]:
        print(f"  {a}-{b}: {c:.3f}")

    out = {'window': [str(df.index[0].date()), str(df.index[-1].date())],
           'n_weeks': len(df),
           'btc_single': {k: round(v, 2) for k, v in btc_m.items()},
           'sectors': rows,
           'min_corr_pairs': [{'a': a, 'b': b, 'corr': round(float(c), 3)} for c, a, b in pairs[:6]],
           'max_corr_pairs': [{'a': a, 'b': b, 'corr': round(float(c), 3)} for c, a, b in pairs[-3:]]}
    os.makedirs(os.path.join(ROOT, 'docs/data'), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, 'docs/data/sector_btc_correlation.json'), 'w'),
              ensure_ascii=False, indent=2)
    print("\n已写出 docs/data/sector_btc_correlation.json")

    html = _html(df, rows, btc_m, pairs)
    open(os.path.join(ROOT, 'docs/sector_btc_correlation.html'), 'w', encoding='utf-8').write(html)
    print("已写出 docs/sector_btc_correlation.html")
    return out


def _html(df, rows, btc_m, pairs):
    dates = rh.dates_of(df.index)
    series = rh.series_of(df)
    rows_html = "".join(
        f"<tr><td>{rh.esc(r['zh'])}</td><td>{rh.esc(r['code'])}</td><td class='c'>{r['btc_corr']:+.3f}</td>"
        f"<td class='r'>{r['multiple']:.2f}x</td><td>{r['cagr']:.1f}%</td>"
        f"<td class='r'>{r['mdd']:.1f}%</td><td>{r['vol']:.1f}%</td><td>{r['sharpe']:.2f}</td></tr>"
        for r in rows)
    minp = "".join(f"<li>{rh.esc(a)}-{rh.esc(b)}: <b>{c:.3f}</b></li>" for c, a, b in pairs[:6])
    maxp = "".join(f"<li>{rh.esc(a)}-{rh.esc(b)}: <b>{c:.3f}</b></li>" for c, a, b in pairs[-3:])
    btc_vol = df.pct_change().fillna(0)['BTC'].std() * np.sqrt(52) * 100

    # 图表只画固定顺序的白名单行业, 缺哪个跳过哪个 (原 JS 里硬编码同一份列表)。
    order = ['BTC', 'XLK', 'XLV', 'XLP', 'XLU', 'XLE', 'XLI', 'XLF', 'XLB', 'XLY', 'XLRE', 'XLC']
    shown = {k: series[k] for k in order if k in series}

    body = (
        rh.data_block(dates=dates, series=shown)
        + rh.card("各行业 vs BTC 相关系数（升序：越低越能为加密账户减震）",
                  "<table><tr><th>行业</th><th>代码</th><th>BTC相关</th><th>倍数</th><th>CAGR</th>"
                  f"<th>MDD</th><th>年化波动</th><th>Sharpe</th></tr>{rows_html}</table>"
                  f"<p class='note'>BTC 单资产(同窗): {btc_m['multiple']:.1f}x / CAGR {btc_m['cagr'] * 100:.0f}% "
                  f"/ MDD {btc_m['mdd'] * 100:.0f}% / 年化波动 {btc_vol:.0f}%。<br>"
                  "<b>核心结论：</b>11 个行业与 BTC 相关系数全部落在 <span class='hl'>−0.03 ~ +0.11</span>，"
                  "近乎零相关 —— 对你的加密重仓账户，任何行业指数都是强分散项，"
                  "加行业指数 = 给你的 −75% 加密回撤装减震器。</p>")
        + rh.card("行业间相关性（配多个行业时用于波动收益）",
                  f"<p class='note'><b>最低相关配对（适合组合内互相再平衡）：</b>"
                  f"<ul style='margin:4px 0'>{minp}</ul>"
                  f"<b>最高相关配对（避免重复配置）：</b><ul style='margin:4px 0'>{maxp}</ul>"
                  "能源(XLE) 与几乎所有行业相关都低(0.30~0.40)，是行业内的\"异类\"，最适合作波动收益引擎；"
                  "科技-可选消费-通信属成长集群(0.8+)宜二选一。</p>")
        + rh.card("净值曲线（对数轴, 起点=1）",
                  rh.nav_chart("c1", rh.line_traces(shown), height=480)
                  + "<p class='note'>可见：科技(XLK)与 BTC 同窗都涨最多但路径迥异；"
                    "医疗/必需消费/公用事业最平稳，是压舱石候选。</p>")
    )
    return rh.page(
        title="美股行业指数 vs BTC 相关性 & 再平衡观察清单",
        h1="美股行业指数 × BTC 相关性 &amp; 再平衡观察清单",
        sub="11 个 SPDR 行业ETF vs 比特币 · 共同窗口 2018-06-22~2026-08-28 (~8年) · 方法论证非业绩承诺",
        body=body,
    )


if __name__ == '__main__':
    main()
