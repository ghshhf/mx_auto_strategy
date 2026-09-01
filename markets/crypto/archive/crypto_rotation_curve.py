# -*- coding: utf-8 -*-
"""
CRV / TRX 轮动 vs 买入持有 —— 净值曲线 (HTML, plotly CDN)
真实交易所费率: Binance/OKX 现货吃单(taker) 0.10%, BNB抵扣后 0.075%
用法: python crypto_rotation_curve.py
"""
import csv
import os
import json

CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "weekly_adjclose_crypto50.csv")
START_DATE = "2021-08-05"
INIT_CAP = 200.0
FEE = 0.0010      # 0.10% 真实零售吃单费率 (Binance/OKX taker)
BAND = 0.01       # 再平衡触发阈值: 任一侧偏离50%超过1%即调回
OUT_HTML = os.path.join(os.path.dirname(__file__), "rotation_curve.html")

def load():
    with open(CSV_PATH, newline='', encoding='utf-8-sig') as fh:
        r = csv.reader(fh); header = next(r); rows = list(r)
    iC, iT = header.index("CRV"), header.index("TRX")
    dates, pC, pT = [], [], []
    for row in rows:
        if row[0] < START_DATE:
            continue
        if row[iC] in ("", None) or row[iT] in ("", None):
            continue
        dates.append(row[0]); pC.append(float(row[iC])); pT.append(float(row[iT]))
    return dates, pC, pT

def main():
    dates, pC, pT = load()
    n = len(dates)
    half = INIT_CAP / 2.0

    # 买入持有 50/50
    bh = [half * pC[t] / pC[0] + half * pT[t] / pT[0] for t in range(n)]

    # 轮动 50/50 再平衡
    vC, vT = half, half
    rot, rebal, fees = [], 0, 0.0
    for t in range(n):
        if t > 0:
            vC *= pC[t] / pC[t - 1]
            vT *= pT[t] / pT[t - 1]
            total = vC + vT
            if abs(vC / total - 0.5) > BAND:
                traded = abs(vC - total / 2.0)
                fee = traded * FEE
                total -= fee
                vC = vT = total / 2.0
                rebal += 1; fees += fee
        rot.append(vC + vT)

    # 单币参考
    crv_only = [INIT_CAP * pC[t] / pC[0] for t in range(n)]
    trx_only = [INIT_CAP * pT[t] / pT[0] for t in range(n)]

    rot_f, bh_f = rot[-1], bh[-1]
    print(f"窗口 {dates[0]} ~ {dates[-1]} ({n}周)")
    print(f"买入持有 50/50 : ${INIT_CAP} -> ${bh_f:.2f}  ({bh_f/INIT_CAP:.2f}x)")
    print(f"轮动   50/50   : ${INIT_CAP} -> ${rot_f:.2f}  ({rot_f/INIT_CAP:.2f}x)  [调仓{rebal}次, 手续费${fees:.2f}]")

    # 生成 HTML
    html = TEMPLATE
    html = html.replace("__TITLE__", "CRV / TRX 轮动 vs 买入持有 (5年, 真实0.10%费率)")
    html = html.replace("__SUB__",
        f"区间 {dates[0]} ~ {dates[-1]} ({n}周, 约{n/52:.1f}年) ｜ 起始 $200 = CRV $100 + TRX $100 ｜ "
        f"轮动: 50/50再平衡, 偏离>1%调回, 费率0.10%")
    html = html.replace("__DATES__", json.dumps(dates))
    html = html.replace("__ROT__", json.dumps([round(x, 2) for x in rot]))
    html = html.replace("__BH__", json.dumps([round(x, 2) for x in bh]))
    html = html.replace("__CRV__", json.dumps([round(x, 2) for x in crv_only]))
    html = html.replace("__TRX__", json.dumps([round(x, 2) for x in trx_only]))
    html = html.replace("__ROT_F__", f"${rot_f:.2f}")
    html = html.replace("__BH_F__", f"${bh_f:.2f}")
    html = html.replace("__ROT_X__", f"{rot_f/INIT_CAP:.2f}x")
    html = html.replace("__BH_X__", f"{bh_f/INIT_CAP:.2f}x")
    html = html.replace("__REBAL__", str(rebal))
    html = html.replace("__FEES__", f"${fees:.2f}")
    with open(OUT_HTML, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"曲线已写出: {OUT_HTML}")

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>__TITLE__</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
 body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;margin:24px;background:#fafafa;color:#222}
 h2{margin:0 0 4px} .sub{color:#666;font-size:13px;margin-bottom:12px}
 #chart{width:100%;height:560px;background:#fff;border:1px solid #eee;border-radius:8px}
 .cards{display:flex;gap:14px;margin:14px 0}
 .card{flex:1;background:#fff;border:1px solid #eee;border-radius:8px;padding:14px}
 .card .k{font-size:13px;color:#888} .card .v{font-size:24px;font-weight:700;margin-top:4px}
 .up{color:#d62728} .down{color:#2ca02c}
 .note{font-size:12px;color:#888;margin-top:10px;line-height:1.6}
</style>
</head>
<body>
<h2>__TITLE__</h2>
<div class="sub">__SUB__</div>
<div class="cards">
  <div class="card"><div class="k">轮动 50/50 (0.10%费率)</div><div class="v">__ROT_F__ <span style="font-size:14px">__ROT_X__</span></div></div>
  <div class="card"><div class="k">买入持有 50/50</div><div class="v">__BH_F__ <span style="font-size:14px">__BH_X__</span></div></div>
</div>
<div id="chart"></div>
<div class="note">
 假设: 轮动 = 每周检查, 任一侧权重偏离50%超过1%即调回50/50, 每次调仓对成交金额收0.10%吃单费 (Binance/OKX零售taker; BNB抵扣后0.075%)。
 5年共调仓 __REBAL__ 次, 累计手续费 __FEES__。虚线为单币参考(全仓CRV / 全仓TRX), 解释为何买入持有占优——TRX是持续赢家。
 数据: markets/crypto/data/weekly_adjclose_crypto50.csv (真实Binance/OKX周线)。
</div>
<script>
var DATES=__DATES__, ROT=__ROT__, BH=__BH__, CRV=__CRV__, TRX=__TRX__;
var traces=[
 {x:DATES,y:BH,name:"买入持有 50/50",mode:"lines",line:{color:"#ff7f0e",width:2.5}},
 {x:DATES,y:ROT,name:"轮动 50/50 (0.10%费率)",mode:"lines",line:{color:"#1f77b4",width:2.5}},
 {x:DATES,y:TRX,name:"全仓 TRX (参考)",mode:"lines",line:{color:"#d62728",width:1,dash:"dot"},opacity:0.55},
 {x:DATES,y:CRV,name:"全仓 CRV (参考)",mode:"lines",line:{color:"#2ca02c",width:1,dash:"dot"},opacity:0.55}
];
var layout={
 margin:{l:60,r:20,t:20,b:40},
 xaxis:{title:"",rangeslider:{}},
 yaxis:{title:"组合净值 (USD)",tickformat:"$.0f"},
 legend:{orientation:"h",y:-0.18},
 hovermode:"x unified",
 shapes:[{type:"line",x0:DATES[0],x1:DATES[DATES.length-1],y0:200,y1:200,
          line:{color:"#999",width:1,dash:"dash"}}],
 annotations:[{x:DATES[0],y:200,text:"起始 $200",showarrow:false,xanchor:"left",yanchor:"bottom",font:{size:11,color:"#999"}}]
};
Plotly.newPlot("chart",traces,layout,{responsive:true,displayModeBar:false});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
