#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨市场 50/50 再平衡轮动 汇总 (加密3 + A股3 + 美股3@10y + 美股3@20y = 12组)
复用与单组回测完全相同的 50/50 再平衡逻辑, 在此统一重算并补算 CAGR 年化 + 波动率。
仅读取已落盘的缓存 CSV, 不联网。
"""
import csv, os, math, datetime, json

FEE = 0.0010          # 单边费率 0.10% (零售现货 taker)
BAND = 0.01           # 偏离 50% 超过 1% 即再平衡
CAPITAL = 200.0       # 起始本金 (两标的各 100)
CSV_DIR = "data"

# (市场, 配对标签, csv 文件名, 是否加密)
GROUPS = [
    ("加密", "BTC + ETH", "weekly_btc_eth_10y_multisource.csv", True),
    ("加密", "LTC + ETC", "weekly_ltc_etc_10y_multisource.csv", True),
    ("加密", "ZEC + XMR", "weekly_zec_xmr_10y_multisource.csv", True),
    ("A股", "贵州茅台 + 招商银行", "weekly_yahoo_600519_600036_10y.csv", False),
    ("A股", "海康威视 + 格力电器", "weekly_yahoo_002415_000651_10y.csv", False),
    ("A股", "大华股份 + 中国平安", "weekly_yahoo_002236_601318_10y.csv", False),
    ("美股", "微软 + 苹果", "weekly_yahoo_MSFT_AAPL_10y.csv", False),
    ("美股", "英伟达 + 英特尔", "weekly_yahoo_NVDA_INTC_10y.csv", False),
    ("美股", "可口可乐 + 宝洁", "weekly_yahoo_KO_PG_10y.csv", False),
    ("美股", "可口可乐 + 强生 (20y)", "weekly_yahoo_KO_JNJ_20y.csv", False),
    ("美股", "IBM + 高通 (20y)", "weekly_yahoo_IBM_QCOM_20y.csv", False),
    ("美股", "AMD + Salesforce (20y)", "weekly_yahoo_AMD_CRM_20y.csv", False),
]

def load(path):
    with open(path, newline='', encoding='utf-8') as fh:
        rows = list(csv.reader(fh))
    dates = [r[0] for r in rows[1:]]
    a = [float(r[1]) for r in rows[1:] if len(r) > 2 and r[1] not in ('', None)]
    b = [float(r[2]) for r in rows[1:] if len(r) > 2 and r[2] not in ('', None)]
    return dates, a, b

def max_dd(nav):
    peak = nav[0]; mdd = 0.0
    for v in nav:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < mdd: mdd = dd
    return mdd

def backtest(a, b):
    ua = (CAPITAL/2)/a[0]; ub = (CAPITAL/2)/b[0]
    rot = []
    for i in range(len(a)):
        pa, pb = a[i], b[i]
        if i > 0:
            va = ua*pa; vb = ub*pb; tot = va+vb
            if tot > 0 and abs(va/tot - 0.5) > BAND:
                traded = abs(va - tot*0.5)
                tot_after = tot - traded*FEE
                tv = tot_after * 0.5
                ua = tv/pa; ub = tv/pb
        rot.append(ua*pa + ub*pb)
    ha = (CAPITAL/2)/a[0]; hb = (CAPITAL/2)/b[0]
    hold = [ha*pa + hb*pb for pa, pb in zip(a, b)]
    return rot, hold

def ann_vol(prices):
    rets = [math.log(prices[i]/prices[i-1]) for i in range(1, len(prices)) if prices[i-1] > 0]
    if len(rets) < 2: return 0.0
    mu = sum(rets)/len(rets)
    var = sum((x-mu)**2 for x in rets)/len(rets)
    return math.sqrt(var) * math.sqrt(52) * 100

def cagr(end_val, years):
    return (end_val/CAPITAL)**(1/years) - 1

def main():
    rows = []
    for market, label, fn, is_crypto in GROUPS:
        dates, a, b = load(os.path.join(CSV_DIR, fn))
        rot, hold = backtest(a, b)
        d0 = datetime.datetime.strptime(dates[0], "%Y-%m-%d")
        d1 = datetime.datetime.strptime(dates[-1], "%Y-%m-%d")
        years = (d1 - d0).days / 365.25
        r_mult = rot[-1]/CAPITAL; h_mult = hold[-1]/CAPITAL
        r_cagr = cagr(rot[-1], years); h_cagr = cagr(hold[-1], years)
        r_mdd = max_dd(rot); h_mdd = max_dd(hold)
        vol = (ann_vol(a) + ann_vol(b)) / 2
        rows.append(dict(market=market, label=label, years=years,
                         r_mult=r_mult, h_mult=h_mult,
                         r_cagr=r_cagr, h_cagr=h_cagr,
                         r_mdd=r_mdd, h_mdd=h_mdd, vol=vol,
                         excess=r_mult/h_mult - 1))
    # 控制台打印
    print(f"{'市场':5s} {'配对':22s} {'年数':>5s} {'轮动倍数':>9s} {'轮动年化':>8s} "
          f"{'持有倍数':>9s} {'持有年化':>8s} {'超额':>7s} {'波动':>6s}")
    for r in rows:
        print(f"{r['market']:5s} {r['label']:22s} {r['years']:5.1f} "
              f"{r['r_mult']:9.2f} {r['r_cagr']*100:7.1f}% "
              f"{r['h_mult']:9.2f} {r['h_cagr']*100:7.1f}% "
              f"{r['excess']*100:+6.1f}% {r['vol']:6.1f}%")

    # ---------- HTML ----------
    colors = {"加密": "#f39c12", "A股": "#e74c3c", "美股": "#2980b9"}
    table_rows = ""
    for r in rows:
        flag = "✅占优" if r['excess'] > 0 else "❌失效"
        table_rows += (
            f"<tr><td>{r['market']}</td><td>{r['label']}</td><td>{r['years']:.1f}</td>"
            f"<td><b>{r['r_mult']:.2f}x</b><br><span class='sub'>{r['r_cagr']*100:.1f}%/年</span></td>"
            f"<td>{r['h_mult']:.2f}x<br><span class='sub'>{r['h_cagr']*100:.1f}%/年</span></td>"
            f"<td>{r['excess']*100:+.1f}%</td>"
            f"<td>{r['vol']:.0f}%</td>"
            f"<td style='color:{'#1e8449' if r['excess']>0 else '#c0392b'}'>{flag}</td></tr>")

    # 柱状图数据
    bar_labels = [f"{r['market']}<br>{r['label']}" for r in rows]
    bar_rot = [r['r_mult'] for r in rows]
    bar_hold = [r['h_mult'] for r in rows]
    # 散点数据 (波动率 vs 超额)
    scatter = [{"x": r['vol'], "y": r['excess']*100, "market": r['market'],
                "label": r['label'], "years": round(r['years'],1)} for r in rows]

    # highlight: AMD + Salesforce (20y)
    amd = next(r for r in rows if "AMD" in r['label'])
    amd_end = amd['r_mult'] * CAPITAL
    hl = (f"重点 · AMD + Salesforce 20年轮动: 起始 $200 → 终值 <b>${amd_end:.0f}</b> "
          f"({amd['r_mult']:.2f}x), <b>年化复利 {amd['r_cagr']*100:.1f}%</b>; "
          f"买入持有 {amd['h_mult']:.2f}x / {amd['h_cagr']*100:.1f}%/年。 "
          f"轮动年化高出 {(amd['r_cagr']-amd['h_cagr'])*100:.1f} 个百分点。")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>跨市场 50/50 再平衡轮动 汇总 (12组)</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{{font-family:-apple-system,"Segoe UI",sans-serif;margin:0;background:#fff;color:#222}}
.container{{max-width:1120px;margin:24px auto;padding:0 18px}}
h2{{font-size:22px;margin:0 0 4px}} .sub{{color:#888;font-size:12px}}
#hl{{background:linear-gradient(90deg,#fff4e6,#ffe8cc);border-left:4px solid #e67e22;
padding:14px 18px;margin:16px 0;border-radius:6px;font-size:15px;line-height:1.7}}
table{{width:100%;border-collapse:collapse;margin:14px 0;font-size:13px}}
th,td{{padding:8px 6px;border-bottom:1px solid #eee;text-align:center}}
th{{background:#f7f9fb;color:#555}} td:nth-child(2){{text-align:left}}
.sub{{color:#888;font-size:11px}} .box{{background:#f7f9fb;border-radius:6px;padding:8px;margin:10px 0}}
#bar{{width:100%;height:460px}} #sc{{width:100%;height:460px}}</style></head>
<body><div class="container">
<h2>跨市场 50/50 再平衡轮动 · 汇总 (12 组)</h2>
<div class="sub">机制统一: 各 $100 建仓, 偏离 50% 权重 &gt;1% 即再平衡调回, 单边费率 0.10%, 后复权/含分红。加密=Kraken 周线, A股/美股=Yahoo 周线。</div>
<div id="hl">{hl}</div>
<div class="box"><b>统一结论:</b> 50/50 再平衡轮动的优势, 只在 <b>"双强 + 高波动 + 无单一碾压赢家"</b> 结构下稳定兑现; 波动越高该超额越大; 一旦某标的成结构性赢家 (茅台/英伟达), 轮动劣于重仓赢家。三市场 12 组一致。</div>
<table>
<tr><th>市场</th><th>配对</th><th>窗口(年)</th><th>轮动 50/50</th><th>买入持有</th><th>轮动超额</th><th>平均年化波动</th><th>判定</th></tr>
{table_rows}
</table>
<div id="bar"></div>
<div class="sub" style="margin-top:4px">图1 · 轮动 vs 买入持有 终值倍数对比 (纵轴对数刻度)。红色=轮动更高。</div>
<div id="sc"></div>
<div class="sub" style="margin-top:4px">图2 · 平均年化波动 vs 轮动超额%。正相关: 波动越高, 再平衡"低买高卖"收割的波动收益越大。</div>
</div>
<script>
var barLabels={json.dumps(bar_labels, ensure_ascii=False)};
var barRot={json.dumps(bar_rot)};
var barHold={json.dumps(bar_hold)};
Plotly.newPlot('bar',[
 {{x:barLabels,y:barRot,name:'轮动 50/50',type:'bar',marker:{{color:'#e74c3c'}}}},
 {{x:barLabels,y:barHold,name:'买入持有',type:'bar',marker:{{color:'#95a5a6'}}}}
],{{barmode:'group',margin:{{t:20,r:20,b:120,l:60}},
 yaxis:{{title:'终值倍数 (x)',type:'log'}},xaxis:{{tickangle:-35}},
 legend:{{orientation:'h',y:1.08}},plot_bgcolor:'#fff',paper_bgcolor:'#fff'}});

var sc={json.dumps(scatter, ensure_ascii=False)};
var trace={{x:sc.map(d=>d.x),y:sc.map(d=>d.y),mode:'markers+text',type:'scatter',
 text:sc.map(d=>d.label),textposition:'top center',textfont:{{size:10}},
 marker:{{size:sc.map(d=>Math.max(10,Math.min(34,d.y+18))),
 color:sc.map(d=>d.market==='加密'?'#f39c12':(d.market==='A股'?'#e74c3c':'#2980b9')),
 line:{{width:1,color:'#333'}},opacity:0.85}},
 hovertemplate:'%{{text}}<br>波动 %{{x:.0f}}%<br>轮动超额 %{{y:+.1f}}%<extra></extra>'}};
Plotly.newPlot('sc',[trace],{{margin:{{t:20,r:20,b:55,l:60}},
 xaxis:{{title:'平均年化波动 (%)'}},yaxis:{{title:'轮动超额 vs 买入持有 (%)'}},
 plot_bgcolor:'#fff',paper_bgcolor:'#fff'}});
</script></body></html>"""
    out = "rotation_summary.html"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"\n[html] 写出 {out}")

if __name__ == "__main__":
    main()
