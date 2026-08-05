# -*- coding: utf-8 -*-
"""
A股 10年 轮动回测 (与加密老币轮动同一套机制)
================================================
机制: 50/50 再平衡轮动 —— 任一侧权重偏离 50% 超过 BAND% 即调回 50/50, 每笔调仓费率 FEE%。
对照: 买入持有 50/50、单股全仓A、单股全仓B。
数据: Yahoo Finance 日线(经代理 3067 可达) -> 本地重采样为周线(用后复权 adjclose)。
      候选: 贵州茅台600519 / 招商银行600036 / 格力000651 / 中国平安601318 等, 均从2015年起。
用法: 改顶部 STOCK_A/STOCK_B/YF_A/YF_B 即可换任意两 A股。
"""
import urllib.request, json, datetime, csv, os

PROXY = "http://127.0.0.1:3067"
START = datetime.datetime(2015, 1, 1, tzinfo=datetime.timezone.utc)
END   = datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc)

# ===== 被测两 A股 =====
NAME_A, YF_A = "海康威视", "002415.SZ"
NAME_B, YF_B = "格力电器", "000651.SZ"
# ======================

BAND = 1.0      # 再平衡触发阈值 (%)：任一侧 >50%+BAND 或 <50%-BAND 调回
FEE  = 0.10     # 每笔调仓费率 (%) —— 与加密轮动一致(真实 A股 round-trip ~0.1%)

CACHE = f"data/weekly_yahoo_{YF_A[:6]}_{YF_B[:6]}_10y.csv"
OUT_HTML = f"ashare_{YF_A[:6]}_{YF_B[:6]}_10y_curve.html"

UTC = datetime.timezone.utc

def fetch_daily(sym):
    p1, p2 = int(START.timestamp()), int(END.timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={p1}&period2={p2}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    for _ in range(3):
        try:
            r = opener.open(req, timeout=60)
            d = json.loads(r.read())
            res = d["chart"]["result"][0]
            ts = res["timestamp"]
            cl = res["indicators"]["quote"][0]["close"]
            adj = res["indicators"].get("adjclose", [{"adjclose": [None]*len(cl)}])[0]["adjclose"]
            out = {}
            for t, c, a in zip(ts, cl, adj):
                if c is None:
                    continue
                dt = datetime.datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d")
                out[dt] = a if (a is not None and a > 0) else c  # 优先后复权
            return out
        except Exception as e:
            print("fetch err", sym, e); 
            import time; time.sleep(2)
    return {}

def to_weekly(daily):
    weeks = {}
    for d, p in sorted(daily.items()):
        dt = datetime.datetime.strptime(d, "%Y-%m-%d")
        y, w = dt.isocalendar()[:2]
        weeks[(y, w)] = (d, p)  # 保留每周最后一根
    return [(v[0], v[1]) for v in weeks.values()]

def load_or_fetch():
    if os.path.exists(CACHE):
        with open(CACHE, newline='', encoding='utf-8') as fh:
            rows = list(csv.reader(fh))
        dates = [r[0] for r in rows[1:]]
        a = [float(r[1]) for r in rows[1:]]
        b = [float(r[2]) for r in rows[1:]]
        print(f"[cache] 载入 {len(dates)} 周")
        return dates, a, b
    da, db = to_weekly(fetch_daily(YF_A)), to_weekly(fetch_daily(YF_B))
    sa = {d: p for d, p in da}
    sb = {d: p for d, p in db}
    dates = [d for d in sa if d in sb]
    with open(CACHE, "w", newline='', encoding='utf-8') as fh:
        w = csv.writer(fh); w.writerow(["date", NAME_A, NAME_B])
        for d in dates:
            w.writerow([d, sa[d], sb[d]])
    print(f"[fetch] 拉取并缓存 {len(dates)} 周")
    return dates, [sa[d] for d in dates], [sb[d] for d in dates]

def rotation(a, b):
    n = len(a)
    sh_a, sh_b = 100.0 / a[0], 100.0 / b[0]
    nav, peak, mdd, fee_tot, rebal = [], 200.0, 0.0, 0.0, 0
    for i in range(n):
        tot = sh_a * a[i] + sh_b * b[i]
        nav.append(tot)
        peak = max(peak, tot); mdd = min(mdd, (tot - peak) / peak)
        if i == n - 1:
            break
        wa = (sh_a * a[i]) / tot
        if abs(wa - 0.5) > BAND / 100.0:
            target = tot / 2.0
            trade = abs(target - sh_a * a[i])
            fee_amt = trade * FEE / 100.0
            new_tot = tot - fee_amt
            sh_a = (new_tot / 2.0) / a[i]
            sh_b = (new_tot / 2.0) / b[i]
            rebal += 1; fee_tot += fee_amt
    return nav, rebal, fee_tot, mdd

def buyhold(a, b):
    sh_a, sh_b = 100.0 / a[0], 100.0 / b[0]
    nav = [sh_a * a[i] + sh_b * b[i] for i in range(len(a))]
    peak, mdd = nav[0], 0.0
    for v in nav:
        peak = max(peak, v); mdd = min(mdd, (v - peak) / peak)
    return nav, mdd

def single(a):
    sh = 200.0 / a[0]
    nav = [sh * a[i] for i in range(len(a))]
    peak, mdd = nav[0], 0.0
    for v in nav:
        peak = max(peak, v); mdd = min(mdd, (v - peak) / peak)
    return nav, mdd

def build_html(dates, rot, bh, sa, sb, meta):
    import html as _h
    def s(x): return _h.escape(str(x))
    rotj = [[d, round(v, 2)] for d, v in zip(dates, rot)]
    bhj  = [[d, round(v, 2)] for d, v in zip(dates, bh)]
    saj  = [[d, round(v, 2)] for d, v in zip(dates, sa)]
    sbj  = [[d, round(v, 2)] for d, v in zip(dates, sb)]
    rows = "".join(
        f"<tr><td>{s(k)}</td><td>{s(v)}</td></tr>" for k, v in meta.items())
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>A股轮动 {NAME_A}/{NAME_B} 10年</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{{font-family:system-ui,'Microsoft YaHei',sans-serif;margin:24px;background:#fff;color:#222}}
h2{{margin-bottom:6px}} .box{{background:#f7f7f9;border:1px solid #e3e3e8;border-radius:8px;padding:12px 16px;margin:12px 0}}
table{{border-collapse:collapse;font-size:14px}} td,th{{border:1px solid #ddd;padding:4px 12px;text-align:left}}</style></head>
<body>
<h2>A股轮动 vs 买入持有 — {NAME_A}({YF_A}) / {NAME_B}(YF_B)</h2>
<div class="box"><table>{rows}</table></div>
<div id="chart" style="width:100%;height:560px"></div>
<script>
var rot={rotj}, bh={bhj}, sa={saj}, sb={sbj};
var t=rot.map(r=>r[0]);
function mk(y,n,c,dash){{return{{x:t,y:y.map(r=>r[1]),name:n,mode:'lines',
 line:{{color:c,width:2,dash:dash||'solid'}}}};}}
Plotly.newPlot('chart',[
 mk(rot,'轮动 50/50 (再平衡)','#e4572e'),
 mk(bh,'买入持有 50/50','#2e86de'),
 mk(sa,'全仓 '+{NAME_A!r},'#17a589','dot'),
 mk(sb,'全仓 '+{NAME_B!r},'#8e44ad','dot')
],{{title:'净值曲线 ($200 起点) ',xaxis:{{title:'周'}},yaxis:{{title:'组合价值 ($)',type:'log'}},
 legend:{{orientation:'h'}},hovermode:'x unified'}});
</script></body></html>"""

def main():
    dates, a, b = load_or_fetch()
    rot, rcount, fee_tot, rmdd = rotation(a, b)
    bh, bmdd = buyhold(a, b)
    sa, samdd = single(a)
    sb, sbmdd = single(b)
    yrs = (datetime.datetime.strptime(dates[-1], "%Y-%m-%d") -
           datetime.datetime.strptime(dates[0], "%Y-%m-%d")).days / 365.25
    meta = {
        "窗口": f"{dates[0]} ~ {dates[-1]} (≈{yrs:.1f} 年, {len(dates)} 周)",
        "起点价": f"{NAME_A}=${a[0]:.2f}  {NAME_B}=${b[0]:.2f}",
        "终点价": f"{NAME_A}=${a[-1]:.2f}  {NAME_B}=${b[-1]:.2f}",
        "轮动 50/50": f"${rot[-1]:.2f}  ({rot[-1]/200:.2f}x)  最大回撤 {rmdd*100:.1f}%  调仓 {rcount} 次 手续费 ${fee_tot:.2f}",
        "买入持有 50/50": f"${bh[-1]:.2f}  ({bh[-1]/200:.2f}x)  最大回撤 {bmdd*100:.1f}%",
        f"全仓 {NAME_A}": f"${sa[-1]:.2f}  ({sa[-1]/200:.2f}x)  最大回撤 {samdd*100:.1f}%",
        f"全仓 {NAME_B}": f"${sb[-1]:.2f}  ({sb[-1]/200:.2f}x)  最大回撤 {sbmdd*100:.1f}%",
        "规则": f"再平衡阈值 BAND={BAND}%  费率 FEE={FEE}%  后复权价",
    }
    html = build_html(dates, rot, bh, sa, sb, meta)
    with open(OUT_HTML, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("\n=== 结果 ($200 起点) ===")
    for k, v in meta.items():
        print(f"  {k}: {v}")
    print(f"\n曲线已生成: {OUT_HTML}")

if __name__ == "__main__":
    main()
