#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股 20 年轮动回测 (可口可乐 KO + 强生 JNJ)
数据源: Yahoo Finance 日线 (经代理 127.0.0.1:3067), 本地重采样为周线(后复权, 含分红)
机制: 50/50 再平衡轮动, 偏离目标权重 >1% 即调回, 单边费率 0.10%
与 crypto_stocks 下 ashare_rotation_10y.py / us_rotation_10y.py 同机制, 仅窗口拉到 20 年。
"""
import urllib.request, json, datetime, csv, os
from collections import defaultdict

PROXY = "http://127.0.0.1:3067"
START = datetime.datetime(2006, 1, 1, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc)
FEE = 0.0010          # 单边费率 (真实零售现货 taker ~0.10%)
BAND = 0.01           # 再平衡阈值: 任一侧偏离 50% 超过 1% 即调回
CAPITAL = 200.0       # 起始本金 (两股各 100)
CACHE_DIR = "data"

# ===== 被测两股 (Yahoo ticker) =====
SYM_A, NAME_A = "KO", "可口可乐"
SYM_B, NAME_B = "JNJ", "强生"
# ================================

UTC = datetime.timezone.utc

def fetch_daily(sym):
    p1 = int(START.timestamp()); p2 = int(END.timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={p1}&period2={p2}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    op = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    for _ in range(3):
        try:
            r = op.open(req, timeout=60)
            d = json.loads(r.read()); r0 = d["chart"]["result"][0]
            ts = r0["timestamp"]; adj = r0["indicators"].get("adjclose", [None])[0]["adjclose"]
            out = {}
            for t, a in zip(ts, adj):
                if a is None or a <= 0:
                    continue
                out[datetime.datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d")] = a
            return out
        except Exception as e:
            print("fetch err", sym, e); 
            import time; time.sleep(2)
    return {}

def to_weekly(daily):
    """取每周最后一个交易日的 close 作为周线收盘"""
    buckets = defaultdict(list)
    for d, v in daily.items():
        dt = datetime.datetime.strptime(d, "%Y-%m-%d").date()
        monday = dt - datetime.timedelta(days=dt.weekday())
        buckets[monday].append((d, v))
    out = [(buckets[m][-1][0], buckets[m][-1][1]) for m in sorted(buckets)]
    return out

def load_or_fetch():
    cache = f"{CACHE_DIR}/weekly_yahoo_{SYM_A}_{SYM_B}_20y.csv"
    if os.path.exists(cache):
        with open(cache, newline='', encoding='utf-8') as fh:
            rows = list(csv.reader(fh))
        dates = [r[0] for r in rows[1:]]
        a = [float(r[1]) for r in rows[1:]]
        b = [float(r[2]) for r in rows[1:]]
        print(f"[cache] 载入 {len(dates)} 周")
        return dates, a, b
    wa = to_weekly(fetch_daily(SYM_A))
    wb = to_weekly(fetch_daily(SYM_B))
    da = {d: v for d, v in wa}; db = {d: v for d, v in wb}
    dates = [d for d in sorted(da) if d in db]
    with open(cache, "w", newline='', encoding='utf-8') as fh:
        w = csv.writer(fh); w.writerow(["date", NAME_A, NAME_B])
        for d in dates:
            w.writerow([d, da[d], db[d]])
    print(f"[fetch] 拉取并缓存 {len(dates)} 周")
    return dates, [da[d] for d in dates], [db[d] for d in dates]

def max_dd(nav):
    peak = nav[0]; mdd = 0.0
    for v in nav:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < mdd: mdd = dd
    return mdd

def backtest(dates, a, b):
    # 轮动: 持有股数 ua/ub, 偏离>band 调回 50/50 (扣费)
    ua = (CAPITAL/2) / a[0]; ub = (CAPITAL/2) / b[0]
    rot = []
    for i in range(len(dates)):
        pa, pb = a[i], b[i]
        if i > 0:
            va = ua*pa; vb = ub*pb; tot = va+vb
            if tot > 0 and abs(va/tot - 0.5) > BAND:
                traded = abs(va - tot*0.5)
                tot_after = tot - traded*FEE
                tv = tot_after * 0.5
                ua = tv/pa; ub = tv/pb
        rot.append(ua*pa + ub*pb)
    # 买入持有
    ha = (CAPITAL/2)/a[0]; hb = (CAPITAL/2)/b[0]
    hold = [ha*pa + hb*pb for pa, pb in zip(a, b)]
    # 全仓单股
    sa = CAPITAL/a[0]; sb = CAPITAL/b[0]
    na = [sa*pa for pa in a]; nb = [sb*pb for pb in b]
    return rot, hold, na, nb

def mk(y, name, color, dash="solid"):
    return {"x": y[0], "y": y[1], "mode": "lines", "name": name,
            "line": {"color": color, "width": 2, "dash": dash}}

def build_html(dates, rot, hold, na, nb, outfile):
    sa, sb = rot[-1], hold[-1]
    na_v, nb_v = na[-1], nb[-1]
    mdd_r, mdd_h = max_dd(rot), max_dd(hold)
    summary = (f"窗口 {dates[0]} ~ {dates[-1]} ({len(dates)}周, 约{len(dates)/52.18:.1f}年) | "
               f"起始 ${CAPITAL:.0f} (各$100)<br>"
               f"轮动 50/50: <b>${sa:.0f} ({sa/CAPITAL:.2f}x)</b> | 最大回撤 {mdd_r*100:.1f}%<br>"
               f"买入持有: ${sb:.0f} ({sb/CAPITAL:.2f}x) | 最大回撤 {mdd_h*100:.1f}%<br>"
               f"全仓{NAME_A}: ${na_v:.0f} ({na_v/CAPITAL:.2f}x) | 全仓{NAME_B}: ${nb_v:.0f} ({nb_v/CAPITAL:.2f}x)<br>"
               f"机制: 50/50 再平衡, 偏离&gt;1% 调回, 单边费率 0.10% (Yahoo 后复权, 含分红)")
    traces = [
        mk((dates, rot), f"轮动 50/50 ({sa/CAPITAL:.2f}x)", "#e74c3c", "solid"),
        mk((dates, hold), f"买入持有 ({sb/CAPITAL:.2f}x)", "#2c3e50", "solid"),
        mk((dates, na), f"全仓 {NAME_A} ({na_v/CAPITAL:.2f}x)", "#17a589", "dot"),
        mk((dates, nb), f"全仓 {NAME_B} ({nb_v/CAPITAL:.2f}x)", "#8e44ad", "dot"),
    ]
    data_json = json.dumps(traces, ensure_ascii=False)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{NAME_A}+{NAME_B} 20年轮动</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{{font-family:-apple-system,"Segoe UI",sans-serif;margin:0;background:#fff;color:#222}}
.container{{max-width:1040px;margin:24px auto;padding:0 16px}}
h2{{font-size:20px;margin-bottom:4px}} .sub{{color:#666;font-size:13px;margin-bottom:12px}}
#summary{{background:#f7f9fb;border-left:4px solid #e74c3c;padding:12px 16px;margin:16px 0;
font-size:14px;line-height:1.7;border-radius:4px}}
#chart{{width:100%;height:620px}}</style></head>
<body><div class="container">
<h2>{NAME_A} + {NAME_B} · 20 年轮动 vs 买入持有</h2>
<div class="sub">美股 · Yahoo 后复权周线 · 同机制对照 (crypto_stocks)</div>
<div id="summary">{summary}</div>
<div id="chart"></div></div>
<script>var traces={data_json};
Plotly.newPlot('chart', traces, {{
  margin:{{t:20,r:20,b:50,l:60}}, hovermode:'x unified',
  xaxis:{{title:'', type:'date'}}, yaxis:{{title:'组合净值 ($)', rangemode:'tozero'}},
  legend:{{orientation:'h', y:-0.15}}, plot_bgcolor:'#fff', paper_bgcolor:'#fff'
}});</script></body></html>"""
    with open(outfile, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"[html] 写出 {outfile}")

def main():
    os.makedirs(CACHE_DIR, exist_ok=True)
    dates, a, b = load_or_fetch()
    rot, hold, na, nb = backtest(dates, a, b)
    print(f"\n窗口: {dates[0]} ~ {dates[-1]} ({len(dates)}周, 约{len(dates)/52.18:.1f}年)")
    print(f"轮动 50/50 : ${rot[-1]:.0f} ({rot[-1]/CAPITAL:.2f}x)  MDD {max_dd(rot)*100:.1f}%")
    print(f"买入持有   : ${hold[-1]:.0f} ({hold[-1]/CAPITAL:.2f}x)  MDD {max_dd(hold)*100:.1f}%")
    print(f"全仓{NAME_A}  : ${na[-1]:.0f} ({na[-1]/CAPITAL:.2f}x)")
    print(f"全仓{NAME_B}  : ${nb[-1]:.0f} ({nb[-1]/CAPITAL:.2f}x)")
    out = f"{SYM_A}_{SYM_B}_20y_curve.html"
    build_html(dates, rot, hold, na, nb, out)
    print(f"\n完成 -> {out}")

if __name__ == "__main__":
    main()
