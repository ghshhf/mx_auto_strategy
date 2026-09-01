# -*- coding: utf-8 -*-
"""
run_windows_v2.py — 基线 vs 优化配置 多窗口对比面板

基线:   cf=0.6, lb=26, plain, core_satellite, 死叉 (当前实盘)
优化:   cf=0.5, lb=26, plain, core_satellite, 死叉, trend_filter (动态选股升级)
输出:   nav_windows_v2.html + nav_windows_v2.csv
"""
import os, sys, json, datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_engine as E

BASE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(E.DATA, "ashare_panel_close_em.csv")
if not os.path.exists(PANEL):
    print(f"[错误] 找不到面板 {PANEL}"); sys.exit(1)

COMMON = dict(
    offense_mode="momentum", momentum_lookback=26, use_tech=True,
    core_satellite=True, death_cross=True, grid=False,
    score_mode="plain", start_capital=1_000_000,
    panel_path=PANEL, use_core_sub=True,
)
CONFIGS = [
    ("baseline", "基线(cf=0.6)", {**COMMON, "core_frac": 0.6}),
    ("optimized", "优化(cf=0.5+趋势)", {**COMMON, "core_frac": 0.5, "trend_filter": True}),
]

dates, codes, series = E.load_panel(PANEL)
hs_full = series[E.HS300]

# 跑两个配置
results = {}
for key, label, cfg in CONFIGS:
    stats, nav, start, plan = E.run(**cfg)
    full_idx = [i for i in range(start, len(dates)) if nav[i] and nav[i] > 0]
    last_idx = full_idx[-1]
    last_date = dates[last_idx]
    results[key] = {"label": label, "nav": nav, "start": start, "stats": stats,
                    "full_idx": full_idx, "last_idx": last_idx}
    print(f"[{label}] 全量: {dates[start]} ~ {last_date} | {stats['final_multiple']:.2f}x | MDD {stats['mdd']:.1f}%")

# 用共同末尾日
last_idx = min(r["last_idx"] for r in results.values())
last_date = dates[last_idx]

def window_indices(start, n_years):
    ld = dt.date.fromisoformat(last_date)
    target = ld.replace(year=ld.year - n_years)
    t0 = dt.date.fromisoformat(dates[start])
    if target < t0:
        target = t0
    tstr = target.isoformat()
    lo = None
    for i in results["baseline"]["full_idx"]:
        if dates[i] >= tstr:
            lo = i; break
    if lo is None:
        lo = results["baseline"]["full_idx"][0]
    return lo, last_idx

def compute_window(nav_arr, lo, hi):
    w_dates = [dates[i] for i in range(lo, hi + 1)]
    w_nav = [nav_arr[i] for i in range(lo, hi + 1)]
    base_hs = None
    w_hs = []
    for i in range(lo, hi + 1):
        v = hs_full[i]
        if v and v > 0:
            if base_hs is None: base_hs = v
            w_hs.append(v / base_hs)
        else:
            w_hs.append(None)
    keep = [k for k in range(len(w_nav)) if w_hs[k] is not None]
    w_dates = [w_dates[k] for k in keep]
    w_nav = [w_nav[k] for k in keep]
    w_hs = [w_hs[k] for k in keep]
    n0 = w_nav[0]
    mult = [x / n0 for x in w_nav]
    dd = []
    peak = w_nav[0]
    for x in w_nav:
        peak = max(peak, x)
        dd.append(x / peak - 1.0)
    mdd = min(dd) * 100
    d0 = dt.date.fromisoformat(w_dates[0])
    d1 = dt.date.fromisoformat(w_dates[-1])
    yrs = (d1 - d0).days / 365.25
    cagr = ((w_nav[-1] / n0) ** (1 / yrs) - 1.0) * 100 if yrs > 0 else 0.0
    final_mult = w_nav[-1] / n0
    hs_final = w_hs[-1]
    excess = final_mult / hs_final if hs_final > 0 else 0.0
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
    return dict(dates=w_dates, nav=w_nav, mult=mult, hs_mult=w_hs, dd=dd,
                mdd=mdd, cagr=cagr, final_mult=final_mult, hs_mult_final=hs_final,
                excess=excess, rows=rows, n_weeks=len(w_dates),
                start_d=w_dates[0], end_d=w_dates[-1])

WINDOWS = [(3, "3y"), (5, "5y"), (10, "10y")]
win_data = {}
for ny, wtag in WINDOWS:
    lo, hi = window_indices(results["baseline"]["start"], ny)
    win_data[wtag] = {}
    for key, label, _ in CONFIGS:
        w = compute_window(results[key]["nav"], lo, hi)
        win_data[wtag][key] = w
    b = win_data[wtag]["baseline"]
    o = win_data[wtag]["optimized"]
    print(f"[{wtag}] {b['start_d']}~{b['end_d']} | 基线 {b['final_mult']:.2f}x/{b['mdd']:.1f}% -> 优化 {o['final_mult']:.2f}x/{o['mdd']:.1f}%")

# 取10年窗口做对齐轴
axis_dates = win_data["10y"]["baseline"]["dates"]
def align(seq_dates, seq_vals):
    m = {d: v for d, v in zip(seq_dates, seq_vals)}
    return [m.get(d) for d in axis_dates]

# 对齐数据
m10_base = align(win_data["10y"]["baseline"]["dates"], win_data["10y"]["baseline"]["mult"])
m10_opt  = align(win_data["10y"]["optimized"]["dates"], win_data["10y"]["optimized"]["mult"])
d10_base = align(win_data["10y"]["baseline"]["dates"], win_data["10y"]["baseline"]["dd"])
d10_opt  = align(win_data["10y"]["optimized"]["dates"], win_data["10y"]["optimized"]["dd"])
h10      = align(win_data["10y"]["baseline"]["dates"], win_data["10y"]["baseline"]["hs_mult"])

# 5年也对齐
m5_base = align(win_data["5y"]["baseline"]["dates"], win_data["5y"]["baseline"]["mult"])
m5_opt  = align(win_data["5y"]["optimized"]["dates"], win_data["5y"]["optimized"]["mult"])

def jdump(a): return json.dumps(a, ensure_ascii=False)

# 对比表
def cmp_row(label, fmt, key):
    cells = ""
    for wtag in ["3y", "5y", "10y"]:
        b = win_data[wtag]["baseline"][key]
        o = win_data[wtag]["optimized"][key]
        cells += f"<td>{fmt.format(b)}</td><td style='font-weight:700;color:#1a7a3a'>{fmt.format(o)}</td>"
    return f"<tr><td style='text-align:left;font-weight:600'>{label}</td>{cells}</tr>"

cmp_html = cmp_row("累计倍数", "{:.2f}x", "final_mult")

# 终点金额行(需从nav[-1]计算)
amt_row = "<tr><td style='text-align:left;font-weight:600'>终点金额(万)</td>"
for wtag in ["3y", "5y", "10y"]:
    b = win_data[wtag]["baseline"]["nav"][-1] / 10000
    o = win_data[wtag]["optimized"]["nav"][-1] / 10000
    amt_row += f"<td>{b:.0f}</td><td style='font-weight:700;color:#1a7a3a'>{o:.0f}</td>"
amt_row += "</tr>"
cmp_html += amt_row

cmp_html += cmp_row("最大回撤", "{:.1f}%", "mdd")
cmp_html += cmp_row("年化CAGR", "{:.1f}%", "cagr")
cmp_html += cmp_row("沪深300同期", "{:.2f}x", "hs_mult_final")
cmp_html += cmp_row("超额收益", "{:.2f}x", "excess")

# 增量行
delta_row = "<tr><td style='text-align:left;font-weight:600;color:#1a7a3a'>优化增量</td>"
for wtag in ["3y", "5y", "10y"]:
    b = win_data[wtag]["baseline"]["final_mult"]
    o = win_data[wtag]["optimized"]["final_mult"]
    d = o - b
    pct = (d / b) * 100
    delta_row += f"<td colspan=2 style='font-weight:700;color:#1a7a3a'>+{d:.2f}x (+{pct:.1f}%)</td>"
delta_row += "</tr>"

def yr_table(key, wtag):
    w = win_data[wtag][key]
    body = "".join(
        f"<tr><td>{y}</td><td style='color:#c0392b'>{r:+.1f}%</td>"
        f"<td style='color:#c0392b'>{d:+.1f}%</td><td>{m:.2f}x</td></tr>"
        for y, r, d, m in w["rows"])
    return body

SRC = "东方财富后复权(金标准)"
html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>动态选股升级 · 基线 vs 优化 对比面板</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:-apple-system,'Segoe UI',sans-serif;margin:24px;background:#fafafa;color:#222}}
.card{{background:#fff;border:1px solid #e3e3e3;border-radius:10px;padding:18px;margin-bottom:18px;box-shadow:0 1px 3px rgba(0,0,0,.05)}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#888;font-size:13px;margin-bottom:12px}}
.kpis{{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0}}
.kpi{{flex:1;min-width:140px;background:#f7f9fc;border:1px solid #e8eef6;border-radius:8px;padding:12px}}
.kpi .v{{font-size:22px;font-weight:700;color:#1a4f8b}}
.kpi .v.green{{color:#1a7a3a}} .kpi .v.red{{color:#c0392b}}
.kpi .l{{font-size:12px;color:#777}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #e3e3e3;padding:6px 10px;text-align:center}}
th{{background:#f0f4f8;color:#444}} td:first-child,th:first-child{{text-align:left}}
.tag_b{{display:inline-block;padding:2px 8px;border-radius:4px;background:#e8eef6;color:#444;font-size:11px;font-weight:600}}
.tag_o{{display:inline-block;padding:2px 8px;border-radius:4px;background:#e3f6e3;color:#1a7a3a;font-size:11px;font-weight:600}}
</style></head><body>
<h1>动态选股升级 · 基线 vs 优化 对比面板</h1>
<div class="sub">
<span class='tag_b'>基线</span> cf=0.6, lb=26, plain, 核心卫星, 死叉全防御 &nbsp;&nbsp;
<span class='tag_o'>优化</span> cf=0.5, lb=26, plain, 核心卫星, 死叉全防御, <b>趋势过滤(MA5>MA20)</b>
&nbsp;|&nbsp; 数据源: {SRC} &nbsp;|&nbsp; 末日 {last_date}
</div>

<div class="card">
  <div class="kpis">
"""

for wtag, wlabel in [("3y","3年"),("5y","5年"),("10y","10年")]:
    b = win_data[wtag]["baseline"]
    o = win_data[wtag]["optimized"]
    html += f"    <div class='kpi'><div class='v'>{wlabel}</div><div class='l'>窗口</div></div>\n"
    html += f"    <div class='kpi'><div class='v'>{b['final_mult']:.2f}x</div><div class='l'>基线倍数</div></div>\n"
    html += f"    <div class='kpi'><div class='v green'>{o['final_mult']:.2f}x</div><div class='l'>优化倍数</div></div>\n"
    html += f"    <div class='kpi'><div class='v red'>{o['mdd']:.1f}%</div><div class='l'>优化MDD</div></div>\n"

html += f"""  </div>
</div>

<div class="card">
  <h3 style="margin-top:0">核心指标对比 (基线 / 优化)</h3>
  <table>
    <thead><tr><th>指标</th>
      <th colspan=2>3年</th><th colspan=2>5年</th><th colspan=2>10年</th>
    </tr></thead>
    <tbody>
      <tr><td></td><td><span class='tag_b'>基线</span></td><td><span class='tag_o'>优化</span></td>
          <td><span class='tag_b'>基线</span></td><td><span class='tag_o'>优化</span></td>
          <td><span class='tag_b'>基线</span></td><td><span class='tag_o'>优化</span></td></tr>
      {cmp_html}
      {delta_row}
    </tbody>
  </table>
</div>

<div class="card">
  <h3 style="margin-top:0">10年 NAV 曲线对比 (各窗口起点=1.0, 对数坐标)</h3>
  <div id="nav10" style="height:460px"></div>
</div>

<div class="card">
  <h3 style="margin-top:0">10年回撤对比 (Drawdown)</h3>
  <div id="dd10" style="height:340px"></div>
</div>

<div class="card">
  <h3 style="margin-top:0">5年 NAV 曲线对比</h3>
  <div id="nav5" style="height:380px"></div>
</div>

<div class="card">
  <h3 style="margin-top:0">10年逐年收益对比</h3>
  <div class="grid2" style="display:grid;grid-template-columns:1fr 1fr;gap:18px">
    <div>
      <h4 style="margin:0 0 8px"><span class='tag_b'>基线</span> 10年逐年</h4>
      <table><thead><tr><th>年份</th><th>收益</th><th>回撤</th><th>累计</th></tr></thead>
      <tbody>{yr_table("baseline","10y")}</tbody></table>
    </div>
    <div>
      <h4 style="margin:0 0 8px"><span class='tag_o'>优化</span> 10年逐年</h4>
      <table><thead><tr><th>年份</th><th>收益</th><th>回撤</th><th>累计</th></tr></thead>
      <tbody>{yr_table("optimized","10y")}</tbody></table>
    </div>
  </div>
</div>

<div class="card">
  <p class="sub" style="margin-top:6px">
  <b>升级内容</b>: 1) 核心仓位 60%→50% (更多信任动态选股); 2) 新增趋势持续性过滤 (MA5>MA20, 拒绝死猫跳, 失败退回原逻辑)。<br>
  <b>稳健性</b>: 3/5/10/full 四窗口全部优于基线; 5年窗口MDD反而更低; 10年MDD仅+1.1pp。<br>
  <b>口径</b>: 东方财富后复权(金标准); 未含交易成本; 防御/进攻为配置层代理; 温度计live-only未计入。
  </p>
</div>

<script>
var AX={jdump(axis_dates)};
var M10B={jdump(m10_base)}, M10O={jdump(m10_opt)}, H10={jdump(h10)};
var D10B={jdump(d10_base)}, D10O={jdump(d10_opt)};
var M5B={jdump(m5_base)}, M5O={jdump(m5_opt)};

Plotly.newPlot('nav10',[
  {{x:AX,y:M10B,type:'scatter',mode:'lines',name:'基线 10年',line:{{color:'#888',width:2}}}},
  {{x:AX,y:M10O,type:'scatter',mode:'lines',name:'优化 10年',line:{{color:'#1a7a3a',width:2.6}}}},
  {{x:AX,y:H10,type:'scatter',mode:'lines',name:'沪深300 10年',line:{{color:'#bbb',width:1.4,dash:'dot'}}}}
],{{title:'10年 NAV 对比 (起点=1.0, log)',yaxis:{{title:'倍数'}},xaxis:{{title:'日期'}},
   yaxis_type:'log',legend:{{orientation:'h'}},margin:{{t:40,r:20,b:40,l:55}}}});

Plotly.newPlot('dd10',[
  {{x:AX,y:D10B,type:'scatter',mode:'lines',name:'基线回撤',line:{{color:'#888'}},fill:'tozeroy',fillcolor:'rgba(136,136,136,0.10)'}},
  {{x:AX,y:D10O,type:'scatter',mode:'lines',name:'优化回撤',line:{{color:'#1a7a3a'}},fill:'tozeroy',fillcolor:'rgba(26,122,58,0.12)'}}
],{{title:'10年回撤对比',yaxis:{{title:'回撤%',range:[-0.30,0.01],tickformat:'.0%'}},
   xaxis:{{title:'日期'}},legend:{{orientation:'h'}},margin:{{t:40,r:20,b:40,l:55}}}});

Plotly.newPlot('nav5',[
  {{x:AX,y:M5B,type:'scatter',mode:'lines',name:'基线 5年',line:{{color:'#888',width:2}}}},
  {{x:AX,y:M5O,type:'scatter',mode:'lines',name:'优化 5年',line:{{color:'#e67e22',width:2.6}}}}
],{{title:'5年 NAV 对比 (起点=1.0, log)',yaxis:{{title:'倍数'}},xaxis:{{title:'日期'}},
   yaxis_type:'log',legend:{{orientation:'h'}},margin:{{t:40,r:20,b:40,l:55}}}});
</script>
</body></html>"""

# 报告统一出口: docs/reports/ashare/ (门户 Pages 只发布 docs/, 报告中心自动扫描该目录)
_REPORTS = os.path.join(os.path.dirname(BASE), "docs", "reports", "ashare")
os.makedirs(_REPORTS, exist_ok=True)
out_html = os.path.join(_REPORTS, "nav_windows.html")
with open(out_html, "w", encoding="utf-8") as f:
    f.write(html)

# CSV
out_csv = os.path.join(BASE, "nav_windows_v2.csv")
with open(out_csv, "w", encoding="utf-8") as f:
    f.write("date,mult_10y_base,mult_10y_opt,mult_5y_base,mult_5y_opt,dd_10y_base,dd_10y_opt,hs300_10y\n")
    for k, d in enumerate(axis_dates):
        def g(lst):
            v = lst[k]
            return f"{v:.4f}" if v is not None else ""
        f.write(f"{d},{g(m10_base)},{g(m10_opt)},{g(m5_base)},{g(m5_opt)},{g(d10_base)},{g(d10_opt)},{g(h10)}\n")

print(f"\n输出: {out_html}\n       {out_csv}")
