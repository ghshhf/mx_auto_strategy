# -*- coding: utf-8 -*-
"""
BTC / ETH 轮动 vs 买入持有 —— 10年净值曲线 (多平台交叉验证)
平台: Kraken(主源, 历史最长) + OKX(校验) + Coinbase(尽力)
真实交易所费率: 现货吃单(taker) 0.10%
用法: python crypto_oldcoin_10y_multi.py
"""
import csv
import os
import json
import time
import datetime
import urllib.request

PROXY = "http://127.0.0.1:3067"
UTC = datetime.timezone.utc
START_DATE = "2016-08-01"
END_DATE = "2026-08-01"
INIT_CAP = 200.0
FEE = 0.0010      # 0.10% 真实零售吃单费率
BAND = 0.01       # 再平衡触发阈值: 任一侧偏离50%超过1%即调回
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "weekly_btc_eth_10y_multisource.csv")
OUT_HTML = os.path.join(HERE, "btc_eth_10y_curve.html")

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
    """Kraken OHLC: 返回 {date: close}, 升序, 周线覆盖约2013年起"""
    url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval=10080"
    s, d = _get(url)
    j = json.loads(d)
    arr = j["result"][[k for k in j["result"] if k != "last"][0]]
    out = {}
    for c in arr:
        ts = int(c[0])
        close = float(c[4])
        out[datetime.datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")] = close
    return out


def okx(inst):
    """OKX candles: 返回 {date: close}, 分页拉满10年. 数组结构 [ts_ms,o,h,l,c,...]"""
    out = {}
    after = None
    target = int(datetime.datetime(2016, 8, 1, tzinfo=UTC).timestamp() * 1000)
    for _ in range(20):
        url = f"https://www.okx.com/api/v5/market/candles?instId={inst}&bar=1W&limit=100"
        if after:
            url += f"&after={after}"
        s, d = _get(url)
        j = json.loads(d)
        data = j.get("data") or []
        if not data:
            break
        for c in data:
            ts = int(c[0])
            close = float(c[4])
            out[datetime.datetime.fromtimestamp(ts / 1000, UTC).strftime("%Y-%m-%d")] = close
        earliest = int(data[-1][0])
        if earliest <= target:
            break
        after = earliest
    return out


def coinbase(product):
    """Coinbase candles: 返回 {date: close}, 按300周窗口分页(尽力, 失败返回{})"""
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
                ts = int(c[0]); close = float(c[4])
                out[datetime.datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")] = close
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
    k_btc, k_eth = kraken("XBTUSD"), kraken("ETHUSD")
    print(f"  Kraken BTC {len(k_btc)}周 首{list(k_btc)[0]}  末{list(k_btc)[-1]}")
    print(f"  Kraken ETH {len(k_eth)}周 首{list(k_eth)[0]}  末{list(k_eth)[-1]}")
    print("[fetch] OKX (校验) ...")
    o_btc, o_eth = okx("BTC-USDT"), okx("ETH-USDT")
    print(f"  OKX BTC {len(o_btc)}周 首{list(o_btc)[0]}  末{list(o_btc)[-1]}")
    print(f"  OKX ETH {len(o_eth)}周 首{list(o_eth)[0]}  末{list(o_eth)[-1]}")
    print("[fetch] Coinbase (尽力) ...")
    cb_btc, cb_eth = coinbase("BTC-USD"), coinbase("ETH-USD")

    # 主源: Kraken, 两币交集日期
    dates = [d for d in k_btc if d in k_eth and d >= START_DATE and d < END_DATE]
    dates.sort()
    data = {
        "BTC_kraken": [k_btc[d] for d in dates],
        "ETH_kraken": [k_eth[d] for d in dates],
        "BTC_okx": [nearest(d, o_btc) or k_btc[d] for d in dates],
        "ETH_okx": [nearest(d, o_eth) or k_eth[d] for d in dates],
        "BTC_coinbase": [nearest(d, cb_btc) or "" for d in dates],
        "ETH_coinbase": [nearest(d, cb_eth) or "" for d in dates],
    }
    with open(CACHE, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "BTC_kraken", "ETH_kraken", "BTC_okx", "ETH_okx", "BTC_coinbase", "ETH_coinbase"])
        for i, d in enumerate(dates):
            w.writerow([d, data["BTC_kraken"][i], data["ETH_kraken"][i],
                        data["BTC_okx"][i], data["ETH_okx"][i],
                        data["BTC_coinbase"][i], data["ETH_coinbase"][i]])
    # 跨平台校验
    diffs = []
    for i, d in enumerate(dates):
        a, b = data["BTC_kraken"][i], data["BTC_okx"][i]
        if a and b:
            diffs.append(abs(a - b) / a)
    if diffs:
        print(f"[校验] BTC Kraken vs OKX: 中位偏差 {sorted(diffs)[len(diffs)//2]*100:.2f}%  最大偏差 {max(diffs)*100:.2f}%")
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
    pB, pE = data["BTC_kraken"], data["ETH_kraken"]
    half = INIT_CAP / 2.0

    bh = [half * pB[t] / pB[0] + half * pE[t] / pE[0] for t in range(n)]
    vB, vE = half, half
    rot, rebal, fees = [], 0, 0.0
    for t in range(n):
        if t > 0:
            vB *= pB[t] / pB[t - 1]
            vE *= pE[t] / pE[t - 1]
            total = vB + vE
            if abs(vB / total - 0.5) > BAND:
                traded = abs(vB - total / 2.0)
                fee = traded * FEE
                total -= fee
                vB = vE = total / 2.0
                rebal += 1; fees += fee
        rot.append(vB + vE)
    btc_only = [INIT_CAP * pB[t] / pB[0] for t in range(n)]
    eth_only = [INIT_CAP * pE[t] / pE[0] for t in range(n)]

    rot_f, bh_f = rot[-1], bh[-1]
    print(f"\n窗口 {dates[0]} ~ {dates[-1]} ({n}周, 约{n/52:.1f}年)")
    print(f"买入持有 50/50 : ${INIT_CAP} -> ${bh_f:.2f}  ({bh_f/INIT_CAP:.2f}x)  MDD {mdd(bh)*100:.1f}%")
    print(f"轮动   50/50   : ${INIT_CAP} -> ${rot_f:.2f}  ({rot_f/INIT_CAP:.2f}x)  MDD {mdd(rot)*100:.1f}%  [调仓{rebal}次, 手续费${fees:.2f}]")
    print(f"全仓 BTC       : ${INIT_CAP} -> ${btc_only[-1]:.2f}  ({btc_only[-1]/INIT_CAP:.2f}x)")
    print(f"全仓 ETH       : ${INIT_CAP} -> ${eth_only[-1]:.2f}  ({eth_only[-1]/INIT_CAP:.2f}x)")

    html = TEMPLATE
    html = html.replace("__TITLE__", "BTC / ETH 轮动 vs 买入持有 (10年, 多平台交叉验证)")
    html = html.replace("__SUB__",
        f"区间 {dates[0]} ~ {dates[-1]} ({n}周, 约{n/52:.1f}年) ｜ 起始 $200 = BTC $100 + ETH $100 ｜ "
        f"轮动: 50/50再平衡, 偏离>1%调回, 费率0.10% ｜ 主源 Kraken, OKX/Coinbase 校验")
    html = html.replace("__DATES__", json.dumps(dates))
    html = html.replace("__ROT__", json.dumps([round(x, 2) for x in rot]))
    html = html.replace("__BH__", json.dumps([round(x, 2) for x in bh]))
    html = html.replace("__BTC__", json.dumps([round(x, 2) for x in btc_only]))
    html = html.replace("__ETH__", json.dumps([round(x, 2) for x in eth_only]))
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
 假设: 轮动 = 每周检查, 任一侧权重偏离50%超过1%即调回50/50, 每次调仓对成交金额收0.10%吃单费 (Binance/OKX零售taker; BNB抵扣后0.075%)。
 10年共调仓 __REBAL__ 次, 累计手续费 __FEES__。虚线为单币参考(全仓BTC / 全仓ETH)。
 数据: Kraken 周线(主源, 历史至2013年) + OKX/Coinbase 交叉校验, 经本地代理 127.0.0.1:3067 拉取, 缓存于 data/weekly_btc_eth_10y_multisource.csv。
</div>
<script>
var DATES=__DATES__, ROT=__ROT__, BH=__BH__, BTC=__BTC__, ETH=__ETH__;
var traces=[
 {x:DATES,y:BH,name:"买入持有 50/50",mode:"lines",line:{color:"#ff7f0e",width:2.5}},
 {x:DATES,y:ROT,name:"轮动 50/50 (0.10%费率)",mode:"lines",line:{color:"#1f77b4",width:2.5}},
 {x:DATES,y:ETH,name:"全仓 ETH (参考)",mode:"lines",line:{color:"#d62728",width:1,dash:"dot"},opacity:0.55},
 {x:DATES,y:BTC,name:"全仓 BTC (参考)",mode:"lines",line:{color:"#2ca02c",width:1,dash:"dot"},opacity:0.55}
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
