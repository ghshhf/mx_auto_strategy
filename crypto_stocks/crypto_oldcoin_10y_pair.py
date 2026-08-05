# -*- coding: utf-8 -*-
"""
任意两币 10年轮动 vs 买入持有 (多平台交叉验证, 参数化)
默认: LTC + ETC (Kraken 上唯一两个满足满10年周线覆盖的老币)
平台: Kraken(主源) + OKX(校验) + Coinbase(尽力)
用法: 改 PAIR_A/PAIR_B/NAME_A/NAME_B 后 python crypto_oldcoin_10y_pair.py
"""
import csv
import os
import json
import time
import datetime
import urllib.request

PROXY = "http://127.0.0.1:3067"
UTC = datetime.timezone.utc
START_DATE = "2016-07-21"
END_DATE = "2026-08-01"
INIT_CAP = 200.0
FEE = 0.0010      # 0.10% 真实零售吃单费率
BAND = 0.01       # 再平衡触发阈值: 任一侧偏离50%超过1%即调回

# ===== 被测两币 (Kraken 交易对) =====
PAIR_A, NAME_A = "ZECUSD", "ZEC"
PAIR_B, NAME_B = "XMRUSD", "XMR"
# ====================================

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", f"weekly_{NAME_A.lower()}_{NAME_B.lower()}_10y_multisource.csv")
OUT_HTML = os.path.join(HERE, f"{NAME_A.lower()}_{NAME_B.lower()}_10y_curve.html")

_op = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def _get(url, headers=None, timeout=60, tries=3):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    for _ in range(tries):
        try:
            r = _op.open(req, timeout=timeout)
            return r.status, r.read()
        except Exception as e:
            last = e
            time.sleep(2)
    raise last


def kraken(pair):
    url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval=10080"
    s, d = _get(url)
    j = json.loads(d)
    arr = j["result"][[k for k in j["result"] if k != "last"][0]]
    return {datetime.datetime.fromtimestamp(int(c[0]), UTC).strftime("%Y-%m-%d"): float(c[4]) for c in arr}


def okx(pair):
    inst = pair.replace("USD", "-USDT")
    out, after = {}, None
    target = int(datetime.datetime(2016, 8, 1, tzinfo=UTC).timestamp() * 1000)
    for _ in range(20):
        url = f"https://www.okx.com/api/v5/market/candles?instId={inst}&bar=1W&limit=100"
        if after:
            url += f"&after={after}"
        s, d = _get(url)
        data = json.loads(d).get("data") or []
        if not data:
            break
        for c in data:
            out[datetime.datetime.fromtimestamp(int(c[0]) / 1000, UTC).strftime("%Y-%m-%d")] = float(c[4])
        earliest = int(data[-1][0])
        if earliest <= target:
            break
        after = earliest
    return out


def coinbase(pair):
    product = pair.replace("USD", "-USD")
    out = {}
    start = datetime.datetime(2016, 8, 1, tzinfo=UTC)
    end = datetime.datetime(2026, 8, 1, tzinfo=UTC)
    step = datetime.timedelta(days=300 * 7)
    cur = start
    while cur < end:
        nxt = min(cur + step, end)
        url = (f"https://api.exchange.coinbase.com/products/{product}/candles"
               f"?granularity=604800&start={cur.isoformat().replace('+00:00','Z')}"
               f"&end={nxt.isoformat().replace('+00:00','Z')}")
        try:
            s, d = _get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            for c in json.loads(d):
                out[datetime.datetime.fromtimestamp(int(c[0]), UTC).strftime("%Y-%m-%d")] = float(c[4])
        except Exception as e:
            print(f"  [coinbase {product}] 跳过: {e}")
            break
        cur = nxt
    return out


def nearest(date, dct, within=7):
    if date in dct:
        return dct[date]
    base = datetime.datetime.strptime(date, "%Y-%m-%d")
    for off in range(1, within + 1):
        for sign in (1, -1):
            cand = (base + datetime.timedelta(days=sign * off)).strftime("%Y-%m-%d")
            if cand in dct:
                return dct[cand]
    return None


def load_or_fetch():
    if os.path.exists(CACHE):
        with open(CACHE, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        hdr = rows[0]
        data = {h: [] for h in hdr[1:]}
        dates = [r[0] for r in rows[1:]]
        for r in rows[1:]:
            for i, h in enumerate(hdr[1:], 1):
                data[h].append(float(r[i]))
        print(f"[cache] 载入 {len(dates)} 周")
        return dates, data
    print("[fetch] Kraken (主源) ...")
    k_a, k_b = kraken(PAIR_A), kraken(PAIR_B)
    print(f"  Kraken {NAME_A} {len(k_a)}周 首{list(k_a)[0]}  末{list(k_a)[-1]}")
    print(f"  Kraken {NAME_B} {len(k_b)}周 首{list(k_b)[0]}  末{list(k_b)[-1]}")
    print("[fetch] OKX (校验) ...")
    o_a, o_b = okx(PAIR_A), okx(PAIR_B)
    print(f"  OKX {NAME_A} {len(o_a)}周 首{list(o_a)[0] if o_a else '-'}  末{list(o_a)[-1] if o_a else '-'}")
    print(f"  OKX {NAME_B} {len(o_b)}周 首{list(o_b)[0] if o_b else '-'}  末{list(o_b)[-1] if o_b else '-'}")
    print("[fetch] Coinbase (尽力) ...")
    cb_a, cb_b = coinbase(PAIR_A), coinbase(PAIR_B)

    dates = [d for d in k_a if d in k_b and d >= START_DATE and d < END_DATE]
    dates.sort()
    data = {
        f"{NAME_A}_kraken": [k_a[d] for d in dates],
        f"{NAME_B}_kraken": [k_b[d] for d in dates],
        f"{NAME_A}_okx": [nearest(d, o_a) or k_a[d] for d in dates],
        f"{NAME_B}_okx": [nearest(d, o_b) or k_b[d] for d in dates],
    }
    with open(CACHE, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", f"{NAME_A}_kraken", f"{NAME_B}_kraken", f"{NAME_A}_okx", f"{NAME_B}_okx"])
        for i, d in enumerate(dates):
            w.writerow([d, data[f"{NAME_A}_kraken"][i], data[f"{NAME_B}_kraken"][i],
                        data[f"{NAME_A}_okx"][i], data[f"{NAME_B}_okx"][i]])
    diffs = []
    for i, d in enumerate(dates):
        a, b = data[f"{NAME_A}_kraken"][i], data[f"{NAME_A}_okx"][i]
        if a and b:
            diffs.append(abs(a - b) / a)
    if diffs:
        print(f"[校验] {NAME_A} Kraken vs OKX: 中位偏差 {sorted(diffs)[len(diffs)//2]*100:.2f}%  最大偏差 {max(diffs)*100:.2f}%")
    return dates, data


def mdd(series):
    peak = series[0]; m = 0.0
    for x in series:
        peak = max(peak, x)
        m = min(m, x / peak - 1)
    return m


def main():
    dates, data = load_or_fetch()
    n = len(dates)
    pA, pB = data[f"{NAME_A}_kraken"], data[f"{NAME_B}_kraken"]
    half = INIT_CAP / 2.0

    bh = [half * pA[t] / pA[0] + half * pB[t] / pB[0] for t in range(n)]
    vA, vB = half, half
    rot, rebal, fees = [], 0, 0.0
    for t in range(n):
        if t > 0:
            vA *= pA[t] / pA[t - 1]
            vB *= pB[t] / pB[t - 1]
            total = vA + vB
            if abs(vA / total - 0.5) > BAND:
                traded = abs(vA - total / 2.0)
                fee = traded * FEE
                total -= fee
                vA = vB = total / 2.0
                rebal += 1; fees += fee
        rot.append(vA + vB)
    a_only = [INIT_CAP * pA[t] / pA[0] for t in range(n)]
    b_only = [INIT_CAP * pB[t] / pB[0] for t in range(n)]

    rot_f, bh_f = rot[-1], bh[-1]
    print(f"\n窗口 {dates[0]} ~ {dates[-1]} ({n}周, 约{n/52:.1f}年)  [{NAME_A} vs {NAME_B}]")
    print(f"买入持有 50/50 : ${INIT_CAP} -> ${bh_f:.2f}  ({bh_f/INIT_CAP:.2f}x)  MDD {mdd(bh)*100:.1f}%")
    print(f"轮动   50/50   : ${INIT_CAP} -> ${rot_f:.2f}  ({rot_f/INIT_CAP:.2f}x)  MDD {mdd(rot)*100:.1f}%  [调仓{rebal}次, 手续费${fees:.2f}]")
    print(f"全仓 {NAME_A}     : ${INIT_CAP} -> ${a_only[-1]:.2f}  ({a_only[-1]/INIT_CAP:.2f}x)")
    print(f"全仓 {NAME_B}     : ${INIT_CAP} -> ${b_only[-1]:.2f}  ({b_only[-1]/INIT_CAP:.2f}x)")

    html = TEMPLATE
    html = html.replace("__TITLE__", f"{NAME_A} / {NAME_B} 轮动 vs 买入持有 (10年, 多平台交叉验证)")
    html = html.replace("__SUB__",
        f"区间 {dates[0]} ~ {dates[-1]} ({n}周, 约{n/52:.1f}年) ｜ 起始 $200 = {NAME_A} $100 + {NAME_B} $100 ｜ "
        f"轮动: 50/50再平衡, 偏离>1%调回, 费率0.10% ｜ 主源 Kraken, OKX 校验")
    html = html.replace("__DATES__", json.dumps(dates))
    html = html.replace("__ROT__", json.dumps([round(x, 2) for x in rot]))
    html = html.replace("__BH__", json.dumps([round(x, 2) for x in bh]))
    html = html.replace("__A__", json.dumps([round(x, 2) for x in a_only]))
    html = html.replace("__B__", json.dumps([round(x, 2) for x in b_only]))
    html = html.replace("__ANAME__", NAME_A)
    html = html.replace("__BNAME__", NAME_B)
    html = html.replace("__ROT_F__", f"${rot_f:.2f}")
    html = html.replace("__BH_F__", f"${bh_f:.2f}")
    html = html.replace("__ROT_X__", f"{rot_f/INIT_CAP:.2f}x")
    html = html.replace("__BH_X__", f"{bh_f/INIT_CAP:.2f}x")
    html = html.replace("__ROT_MDD__", f"{mdd(rot)*100:.1f}%")
    html = html.replace("__BH_MDD__", f"{mdd(bh)*100:.1f}%")
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
 #chart{width:100%;height:580px;background:#fff;border:1px solid #eee;border-radius:8px}
 .cards{display:flex;gap:14px;margin:14px 0;flex-wrap:wrap}
 .card{flex:1;min-width:200px;background:#fff;border:1px solid #eee;border-radius:8px;padding:14px}
 .card .k{font-size:13px;color:#888} .card .v{font-size:24px;font-weight:700;margin-top:4px}
 .note{font-size:12px;color:#888;margin-top:10px;line-height:1.7}
</style>
</head>
<body>
<h2>__TITLE__</h2>
<div class="sub">__SUB__</div>
<div class="cards">
  <div class="card"><div class="k">轮动 50/50 (0.10%费率)</div><div class="v">__ROT_F__ <span style="font-size:14px">__ROT_X__</span></div><div class="k" style="margin-top:4px">MDD __ROT_MDD__</div></div>
  <div class="card"><div class="k">买入持有 50/50</div><div class="v">__BH_F__ <span style="font-size:14px">__BH_X__</span></div><div class="k" style="margin-top:4px">MDD __BH_MDD__</div></div>
</div>
<div id="chart"></div>
<div class="note">
 假设: 轮动 = 每周检查, 任一侧权重偏离50%超过1%即调回50/50, 每次调仓对成交金额收0.10%吃单费。
 10年共调仓 __REBAL__ 次, 累计手续费 __FEES__。虚线为单币参考(全仓__ANAME__ / 全仓__BNAME__)。
 数据: Kraken 周线(主源) + OKX 交叉校验, 经本地代理 127.0.0.1:3067 拉取。
</div>
<script>
var DATES=__DATES__, ROT=__ROT__, BH=__BH__, A=__A__, B=__B__;
var traces=[
 {x:DATES,y:BH,name:"买入持有 50/50",mode:"lines",line:{color:"#ff7f0e",width:2.5}},
 {x:DATES,y:ROT,name:"轮动 50/50 (0.10%费率)",mode:"lines",line:{color:"#1f77b4",width:2.5}},
 {x:DATES,y:B,name:"全仓 __BNAME__ (参考)",mode:"lines",line:{color:"#d62728",width:1,dash:"dot"},opacity:0.55},
 {x:DATES,y:A,name:"全仓 __ANAME__ (参考)",mode:"lines",line:{color:"#2ca02c",width:1,dash:"dot"},opacity:0.55}
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
