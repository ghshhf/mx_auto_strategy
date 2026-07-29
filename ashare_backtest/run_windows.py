# -*- coding: utf-8 -*-
"""
run_windows.py - 用东方财富后复权金标准面板, 跑一次全量 NAV,
再切出 3年 / 5年 / 10年 三个 trailing 窗口, 生成可直接查看的对比面板。

用法: python run_windows.py
输出: nav_windows.html (自包含 plotly 面板) + nav_windows.csv
"""
import os
import sys
import json
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_engine as E

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = E.DATA
EM_PANEL = os.path.join(DATA, "ashare_panel_close_em.csv")

if not os.path.exists(EM_PANEL):
    print(f"[错误] 找不到面板 {EM_PANEL}，请先 python eastmoney_hfq_rebuild.py --budget 600")
    sys.exit(1)

PANEL = EM_PANEL
USE_CORE_SUB = True
SRC = "东方财富后复权(金标准, 约14.5年全量, 切片 3/5/10y)"

# ---- 跑一次全量 NAV ----
cfg = dict(offense_mode="momentum", momentum_lookback=26, use_tech=True,
           core_satellite=True, core_frac=0.6, death_cross=True, grid=False,
           score_mode="plain", start_capital=1_000_000, verbose=False,
           panel_path=PANEL, use_core_sub=USE_CORE_SUB)

stats, nav, start, plan = E.run(**cfg)
dates, codes, series = E.load_panel(PANEL)
hs_full = series[E.HS300]

# 全量有效 NAV(从策略起点 start 起)
full_idx = [i for i in range(start, len(dates)) if nav[i] and nav[i] > 0]
last_idx = full_idx[-1]
last_date = dates[last_idx]
print(f"[全量] {dates[start]} ~ {last_date} ({len(full_idx)} 周, 约 {len(full_idx)/52:.1f} 年)")


def window_indices(n_years):
    """返回 [lo, hi] 闭区间索引: 末日向前推 n_years。"""
    ld = dt.date.fromisoformat(last_date)
    target = ld.replace(year=ld.year - n_years)
    if target < dt.date.fromisoformat(dates[start]):
        target = dt.date.fromisoformat(dates[start])
    tstr = target.isoformat()
    lo = None
    for i in full_idx:
        if dates[i] >= tstr:
            lo = i
            break
    if lo is None:
        lo = full_idx[0]
    return lo, last_idx


def compute_window(lo, hi):
    w_dates = [dates[i] for i in range(lo, hi + 1)]
    w_nav = [nav[i] for i in range(lo, hi + 1)]
    # 沪深300 同窗口归一
    base_hs = None
    w_hs = []
    for i in range(lo, hi + 1):
        v = hs_full[i]
        if v and v > 0:
            if base_hs is None:
                base_hs = v
            w_hs.append(v / base_hs)
        else:
            w_hs.append(None)
    # 对齐: 丢弃 hs 仍 None 的早期点
    keep = [k for k in range(len(w_nav)) if w_hs[k] is not None]
    w_dates = [w_dates[k] for k in keep]
    w_nav = [w_nav[k] for k in keep]
    w_hs = [w_hs[k] for k in keep]

    n0 = w_nav[0]
    mult = [x / n0 for x in w_nav]
    hs_mult = [x for x in w_hs]
    dd = []
    peak = w_nav[0]
    for x in w_nav:
        peak = max(peak, x)
        dd.append(x / peak - 1.0)
    mdd = min(dd) * 100

    # CAGR
    d0 = dt.date.fromisoformat(w_dates[0])
    d1 = dt.date.fromisoformat(w_dates[-1])
    yrs = (d1 - d0).days / 365.25
    cagr = ((w_nav[-1] / n0) ** (1 / yrs) - 1.0) * 100 if yrs > 0 else 0.0

    final_mult = w_nav[-1] / n0
    hs_final = hs_mult[-1]
    excess = final_mult / hs_final if hs_final > 0 else 0.0

    # 逐年表
    years = {}
    for idx, d in enumerate(w_dates):
        years.setdefault(d[:4], []).append(idx)
    rows = []
    prev_end = w_nav[0]
    for y in sorted(years):
        idxs = years[y]
        first, last = idxs[0], idxs[-1]
        base = prev_end if rows else w_nav[first]
        yr_ret = w_nav[last] / base - 1.0
        pk = w_nav[first]; mx = 0.0
        for k in idxs:
            pk = max(pk, w_nav[k])
            mx = min(mx, w_nav[k] / pk - 1.0)
        prev_end = w_nav[last]
        rows.append((y, yr_ret * 100, mx * 100, w_nav[last] / n0))
    return dict(
        lo=lo, hi=hi, dates=w_dates, nav=w_nav, mult=mult, hs_mult=hs_mult, dd=dd,
        mdd=mdd, cagr=cagr, final_mult=final_mult, hs_mult_final=hs_final,
        excess=excess, rows=rows, n_weeks=len(w_dates),
        start_d=w_dates[0], end_d=w_dates[-1],
    )


WINDOWS = [(3, "3年"), (5, "5年"), (10, "10年")]
res = {}
for ny, label in WINDOWS:
    lo, hi = window_indices(ny)
    w = compute_window(lo, hi)
    res[label] = w
    print(f"[{label}] {w['start_d']} ~ {w['end_d']} | {w['final_mult']:.2f}x | "
          f"MDD {w['mdd']:.1f}% | CAGR {w['cagr']:.1f}% | 超额 {w['excess']:.2f}x")

# ---- 共同日期轴(取 10年窗口全集) ----
axis_dates = res["10年"]["dates"]
# 各窗口按日期对齐到 axis: 用 dict 查表
def align(seq_dates, seq_vals):
    m = {d: v for d, v in zip(seq_dates, seq_vals)}
    return [m.get(d) for d in axis_dates]

m3 = align(res["3年"]["dates"], res["3年"]["mult"])
m5 = align(res["5年"]["dates"], res["5年"]["mult"])
m10 = align(res["10年"]["dates"], res["10年"]["mult"])
d3 = align(res["3年"]["dates"], res["3年"]["dd"])
d5 = align(res["5年"]["dates"], res["5年"]["dd"])
d10 = align(res["10年"]["dates"], res["10年"]["dd"])
h10 = align(res["10年"]["dates"], res["10年"]["hs_mult"])
nav3 = align(res["3年"]["dates"], res["3年"]["nav"])
nav5 = align(res["5年"]["dates"], res["5年"]["nav"])
nav10 = align(res["10年"]["dates"], res["10年"]["nav"])

# ---- 对比表 ----
cmp_rows = [
    ("窗口起止", f"{res['3年']['start_d']} ~ {res['3年']['end_d']}",
     f"{res['5年']['start_d']} ~ {res['5年']['end_d']}",
     f"{res['10年']['start_d']} ~ {res['10年']['end_d']}"),
    ("覆盖周数", f"{res['3年']['n_weeks']}", f"{res['5年']['n_weeks']}", f"{res['10年']['n_weeks']}"),
    ("累计倍数", f"{res['3年']['final_mult']:.2f}x", f"{res['5年']['final_mult']:.2f}x", f"{res['10年']['final_mult']:.2f}x"),
    ("终点金额(万)", f"{res['3年']['nav'][-1]/10000:.0f}", f"{res['5年']['nav'][-1]/10000:.0f}", f"{res['10年']['nav'][-1]/10000:.0f}"),
    ("最大回撤", f"{res['3年']['mdd']:.1f}%", f"{res['5年']['mdd']:.1f}%", f"{res['10年']['mdd']:.1f}%"),
    ("年化 CAGR", f"{res['3年']['cagr']:.1f}%", f"{res['5年']['cagr']:.1f}%", f"{res['10年']['cagr']:.1f}%"),
    ("沪深300同期", f"{res['3年']['hs_mult_final']:.2f}x", f"{res['5年']['hs_mult_final']:.2f}x", f"{res['10年']['hs_mult_final']:.2f}x"),
    ("超额收益", f"{res['3年']['excess']:.2f}x", f"{res['5年']['excess']:.2f}x", f"{res['10年']['excess']:.2f}x"),
]
cmp_html = "".join(
    f"<tr><td style='text-align:left;font-weight:600'>{r[0]}</td>"
    f"<td>{r[1]}</td><td>{r[2]}</td><td style='background:#f0f4f8;font-weight:700'>{r[3]}</td></tr>"
    for r in cmp_rows)

def yr_table_html(label):
    rows = res[label]["rows"]
    body = "".join(
        f"<tr><td>{y}</td><td style='color:#c0392b'>{r:+.1f}%</td>"
        f"<td style='color:#c0392b'>{d:+.1f}%</td><td>{m:.2f}x</td></tr>"
        for y, r, d, m in rows)
    return (f"<h3 style='margin:0 0 8px'>{label} · 逐年收益/回撤</h3>"
            f"<table><thead><tr><th>年份</th><th>当年收益</th><th>当年最大回撤</th><th>累计倍数</th></tr></thead>"
            f"<tbody>{body}</tbody></table>")

def jdump(a): return json.dumps(a, ensure_ascii=False)

html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>配置策略 · 3/5/10年 回测对比面板</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{{font-family:-apple-system,'Segoe UI',sans-serif;margin:24px;background:#fafafa;color:#222}}
.card{{background:#fff;border:1px solid #e3e3e3;border-radius:10px;padding:18px;margin-bottom:18px;box-shadow:0 1px 3px rgba(0,0,0,.05)}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#888;font-size:13px;margin-bottom:12px}}
.kpis{{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0}}
.kpi{{flex:1;min-width:150px;background:#f7f9fc;border:1px solid #e8eef6;border-radius:8px;padding:12px}}
.kpi .v{{font-size:22px;font-weight:700;color:#1a4f8b}}
.kpi .l{{font-size:12px;color:#777}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #e3e3e3;padding:6px 10px;text-align:center}}
th{{background:#f0f4f8;color:#444}} td:first-child,th:first-child{{text-align:left}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:900px){{.grid2{{grid-template-columns:1fr}}}}
</style></head><body>
<h1>配置策略 · 3年 / 5年 / 10年 回测对比面板</h1>
<div class="sub">配置: 核心-卫星 0.6 / L26 / 木头姐(时变相位) / 死叉全防御 / plain 动态选股 &nbsp;|&nbsp;
起点 100 万 &nbsp;|&nbsp; 数据源: {SRC} &nbsp;|&nbsp; 末日 {last_date}</div>

<div class="card">
  <div class="kpis">
    <div class="kpi"><div class="v">{res['3年']['final_mult']:.2f}x</div><div class="l">3年累计倍数 (→{res['3年']['nav'][-1]/10000:.0f}万)</div></div>
    <div class="kpi"><div class="v">{res['5年']['final_mult']:.2f}x</div><div class="l">5年累计倍数 (→{res['5年']['nav'][-1]/10000:.0f}万)</div></div>
    <div class="kpi"><div class="v">{res['10年']['final_mult']:.2f}x</div><div class="l">10年累计倍数 (→{res['10年']['nav'][-1]/10000:.0f}万)</div></div>
    <div class="kpi"><div class="v" style='color:#c0392b'>{res['10年']['mdd']:.1f}%</div><div class="l">10年最大回撤</div></div>
    <div class="kpi"><div class="v">{res['10年']['cagr']:.1f}%</div><div class="l">10年年化 CAGR</div></div>
  </div>
</div>

<div class="card">
  <h3 style="margin-top:0">核心指标对比</h3>
  <table><thead><tr><th>指标</th><th>3年</th><th>5年</th><th>10年</th></tr></thead>
  <tbody>{cmp_html}</tbody></table>
</div>

<div class="card"><div id="nav" style="height:460px"></div></div>
<div class="card"><div id="dd" style="height:340px"></div></div>

<div class="grid2">
  <div class="card">{yr_table_html("3年")}</div>
  <div class="card">{yr_table_html("5年")}</div>
</div>
<div class="card">{yr_table_html("10年")}</div>

<div class="card">
  <p class="sub" style="margin-top:6px">
  口径说明: 各窗口均以自身起点归一化为 1.0(即"若在该时点投入, 至今增长"), 为公募基金通行的 trailing 业绩口径;
  数据用东方财富后复权(金标准)。未含交易成本; 防御/进攻为配置层代理(非实时三维选股); 温度计 live-only 杠杆未计入。
  2026-07-24 之后数据为回测外(未来函数不存在)。
  </p>
</div>

<script>
var AX={jdump(axis_dates)};
var M3={jdump(m3)}, M5={jdump(m5)}, M10={jdump(m10)}, H10={jdump(h10)};
var D3={jdump(d3)}, D5={jdump(d5)}, D10={jdump(d10)};
Plotly.newPlot('nav',[
  {{x:AX,y:M3,type:'scatter',mode:'lines',name:'策略 3年 (归一1.0)',line:{{color:'#27ae60',width:2}}}},
  {{x:AX,y:M5,type:'scatter',mode:'lines',name:'策略 5年 (归一1.0)',line:{{color:'#e67e22',width:2}}}},
  {{x:AX,y:M10,type:'scatter',mode:'lines',name:'策略 10年 (归一1.0)',line:{{color:'#1a4f8b',width:2.4}}}},
  {{x:AX,y:H10,type:'scatter',mode:'lines',name:'沪深300 10年 (归一1.0)',line:{{color:'#bbb',width:1.4,dash:'dot'}}}}
],{{title:'NAV 曲线对比 (各窗口起点=1.0)',yaxis:{{title:'倍数 (log)'}},xaxis:{{title:'日期'}},
   yaxis_type:'log',legend:{{orientation:'h'}},margin:{{t:40,r:20,b:40,l:55}}}});
Plotly.newPlot('dd',[
  {{x:AX,y:D3,type:'scatter',mode:'lines',name:'3年回撤',line:{{color:'#27ae60'}},fill:'tozeroy',fillcolor:'rgba(39,174,96,0.10)'}},
  {{x:AX,y:D5,type:'scatter',mode:'lines',name:'5年回撤',line:{{color:'#e67e22'}},fill:'tozeroy',fillcolor:'rgba(230,126,34,0.10)'}},
  {{x:AX,y:D10,type:'scatter',mode:'lines',name:'10年回撤',line:{{color:'#c0392b'}},fill:'tozeroy',fillcolor:'rgba(192,57,43,0.14)'}}
],{{title:'回撤水下图对比 (Drawdown)',yaxis:{{title:'回撤 %',range:[-0.35,0.01],tickformat:'.0%'}},
   xaxis:{{title:'日期'}},legend:{{orientation:'h'}},margin:{{t:40,r:20,b:40,l:55}}}});
</script>
</body></html>"""

out_html = os.path.join(BASE, "nav_windows.html")
with open(out_html, "w", encoding="utf-8") as f:
    f.write(html)

# ---- CSV (按日期对齐的全部窗口) ----
out_csv = os.path.join(BASE, "nav_windows.csv")
hdr = ["date", "nav_mult_3y", "nav_mult_5y", "nav_mult_10y", "dd_3y", "dd_5y", "dd_10y",
       "hs300_mult_10y", "nav_3y_yuan", "nav_5y_yuan", "nav_10y_yuan"]
with open(out_csv, "w", encoding="utf-8") as f:
    f.write(",".join(hdr) + "\n")
    for k, d in enumerate(axis_dates):
        def g(lst):
            v = lst[k]
            return f"{v:.4f}" if v is not None else ""
        f.write(f"{d},{g(m3)},{g(m5)},{g(m10)},{g(d3)},{g(d5)},{g(d10)},{g(h10)},"
                f"{g(nav3)},{g(nav5)},{g(nav10)}\n")

print(f"\n输出: {out_html}\n       {out_csv}")
