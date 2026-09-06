"""
blend_defense_engine_check.py — 防御 vs 引擎 角色判定 (相关性证据)
=================================================================
用户定 2027 建仓宇宙时混淆了"防御"与"成长引擎". 本脚本用数据钉死:
  - 经典防御(必需消费单名 KO/PEP/PG, 地域 KOSPI) 与 BTC/纳指均低相关 -> 真 ballast
  - 苹果/微软等 mega-cap 与纳指相关 0.73~0.76 -> 本质是纳指克隆, 属引擎非防御
数据源: markets/us/data/raw_{index,name}_daily.csv + BTC 10y 面板. 窗口 2018-06-22~2026-08-28.
"""
import os, sys, json
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, ROOT)
from portfolio_blend import metrics

def lw(fn):
    d = pd.read_csv(fn, parse_dates=['date']).set_index('date').sort_index()['close']
    return d.resample('W-FRI').last().dropna()

def main():
    btc = pd.read_csv('markets/crypto/data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True)['BTC'].resample('W-FRI').last().ffill().rename('BTC')
    ixic = lw('markets/us/data/raw_index_IXIC_daily.csv').rename('纳指')
    names = {'raw_name_KS11_daily.csv':'韩国KOSPI','raw_name_KO_daily.csv':'可口可乐','raw_name_PEP_daily.csv':'百事',
             'raw_name_PG_daily.csv':'宝洁','raw_name_AAPL_daily.csv':'苹果','raw_name_MSFT_daily.csv':'微软'}
    df = pd.concat([btc, ixic] + [lw(f'markets/us/data/{f}').rename(zh) for f, zh in names.items()], axis=1).dropna().loc['2018-06-22':]
    df = df / df.iloc[0]; ret = df.pct_change().fillna(0)
    rows = []
    for c in ['韩国KOSPI','可口可乐','百事','宝洁','苹果','微软','纳指','BTC']:
        cb = ret[c].corr(ret['BTC']); cn = ret[c].corr(ret['纳指'])
        m = metrics(df[c]); vol = ret[c].std()*np.sqrt(52)*100
        role = '真防御' if (cb < 0.05 and vol < 25) else ('引擎克隆' if cn > 0.8 else ('地域分散' if c=='韩国KOSPI' else '引擎'))
        rows.append({'name': c, 'btc_corr': round(float(cb),3), 'nasdaq_corr': round(float(cn),3),
                     'multiple': round(m['multiple'],2), 'mdd': round(m['mdd']*100,1), 'vol': round(float(vol),1), 'role': role})
    out = {'window': [str(df.index[0].date()), str(df.index[-1].date())], 'rows': rows}
    os.makedirs('docs/data', exist_ok=True)
    json.dump(out, open('docs/data/defense_engine_check.json','w'), ensure_ascii=False, indent=2)
    print('已写出 docs/data/defense_engine_check.json')
    html = _html(rows)
    open('docs/defense_engine_check.html','w',encoding='utf-8').write(html)
    print('已写出 docs/defense_engine_check.html')

def _html(rows):
    tr = "".join(f"<tr><td>{r['name']}</td><td class='c'>{r['btc_corr']:+.3f}</td><td>{r['nasdaq_corr']:+.3f}</td>"
                 f"<td class='r'>{r['multiple']:.2f}x</td><td>{r['mdd']:.1f}%</td><td>{r['vol']:.1f}%</td>"
                 f"<td class='{'hl' if '防御' in r['role'] or '分散' in r['role'] else 'warm'}'>{r['role']}</td></tr>" for r in rows)
    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>防御 vs 引擎 角色判定</title>
<style>body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#0f1117;color:#e6e9ef;margin:0;padding:32px;}}
h1{{font-size:22px;margin:0 0 6px;}} .sub{{color:#9aa3b2;margin-bottom:18px;}}
.card{{background:#171a23;border:1px solid #262b38;border-radius:14px;padding:20px;}}
table{{border-collapse:collapse;width:100%;font-size:14px;}} th,td{{border-bottom:1px solid #2a3040;padding:8px 10px;text-align:left;}}
td.r{{text-align:right;font-variant-numeric:tabular-nums;color:#ffd479;}} td.c{{text-align:right;color:#7ee787;}}
.hl{{color:#7ee787;font-weight:600;}} .warm{{color:#ffb86c;}} .note{{color:#9aa3b2;font-size:13px;line-height:1.75;}}</style></head>
<body><h1>防御 vs 引擎 · 角色判定（相关性证据）</h1>
<div class="sub">窗口 2018-06-22~2026-08-28 · vs BTC / vs 纳指 周收益相关系数</div>
<div class="card"><table><tr><th>标的</th><th>vs BTC</th><th>vs 纳指</th><th>10年倍数</th><th>MDD</th><th>年化波动</th><th>真实角色</th></tr>{tr}</table>
<p class="note">判定: <span class="hl">真防御/地域分散</span> = 与 BTC 近零相关且波动&lt;25%；<span class="warm">引擎克隆</span> = 与纳指相关&gt;0.8（即纳指放大组件, 非防御）。<br>
结论: 宝洁/百事/可口可乐是经典防御(低相关+低波动+浅回撤); 韩国KOSPI是地域分散(对BTC微负); 苹果/微软与纳指0.73~0.76, 属引擎, 全买一遍=加倍下注纳指因子, 不构成分散。</p></div></body></html>"""

if __name__ == '__main__':
    main()
