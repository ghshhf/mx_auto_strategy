# -*- coding: utf-8 -*-
"""生成双币配对再平衡报告 (HTML, 本地留底): BTC+ADA 与 ETH+ADA 主案例 + 15 组配对扫描。
用法: python markets/crypto/build_btc_ada_report.py
输出: docs/reports/crypto/btc_ada_pair_rebalance.html
"""
import os
import io
import importlib.util
import contextlib

import numpy as np
import plotly.graph_objects as go

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
_spec = importlib.util.spec_from_file_location("pair", os.path.join(HERE, "crypto_btc_ada_pair.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

OUT = os.path.join(REPO, "docs", "reports", "crypto", "btc_ada_pair_rebalance.html")

px = mod.sam.load()
fd = mod.sam.first_dates(px)
NAT0 = max(fd["BTC"], fd["ADA"])
NAT0S = str(NAT0.date())
END = px.index[-1]

SEGS = [
    ("全期", NAT0S, None),
    ("段1 熊/吸筹", NAT0S, "2020-05-11"),
    ("段2 上轮周期", "2020-05-11", "2024-04-19"),
    ("段3 本轮", "2024-04-19", None),
]

# ---------- 主案例 ----------
cases = {}
for tag, a, b in (("BTC", "BTC", "ADA"), ("ETH", "ETH", "ADA")):
    r0 = mod.sim(px, [a, b], start=NAT0S, cost_bp=0.0)
    r10 = mod.sim(px, [a, b], start=NAT0S, cost_bp=10.0)
    h = mod.buyhold(px, [a, b], NAT0S, None)
    cases[tag] = {
        "a": a, "b": b, "r0": r0, "r10": r10, "h": h,
        "sa": mod.solo(px, a, r0["start"], r0["end"]),
        "sb": mod.solo(px, b, r0["start"], r0["end"]),
        "ex": r10["nav"] / h["nav"] - 1,
        "ex0": r0["nav"] / h["nav"] - 1,
    }

# 分段(两案例)
seg_rows = ""
for tag in ("BTC", "ETH"):
    c = cases[tag]
    for name, s0, s1 in SEGS:
        r10 = mod.sim(px, [c["a"], c["b"]], start=s0, end=s1, cost_bp=10.0)
        h = mod.buyhold(px, [c["a"], c["b"]], (s0 or r10["start"]), (s1 or r10["end"]))
        ex = r10["nav"] / h["nav"] - 1
        um = r10["units_mult"]
        seg_rows += (
            f"<tr><td class='l'>{c['a']}+{c['b']}</td><td class='l'>{name}</td>"
            f"<td>{r10['yrs']:.2f}</td><td class='hl'>{r10['nav']:.3f}x</td>"
            f"<td class='{'pos' if r10['cagr'] > 0 else 'neg'}'>{r10['cagr'] * 100:+.2f}%</td>"
            f"<td class='neg'>{r10['mdd'] * 100:.2f}%</td><td>{h['nav']:.3f}x</td>"
            f"<td class='{'pos' if ex > 0 else 'neg'}'>{ex * 100:+.2f}%</td>"
            f"<td>{um[c['a']]:.3f}</td><td>{um[c['b']]:.3f}</td></tr>"
        )

# ---------- 配对扫描 ----------
pxf = px.ffill()
avail = [c for c in px.columns if not pxf.loc[NAT0:, c].isna().any()]
with contextlib.redirect_stdout(io.StringIO()):
    scan = mod.pair_scan(px, avail, NAT0S)
by_pair = {r["pair"]: r for r in scan}

solo_cagr = {c: mod.solo(px, c, NAT0, END)["cagr"] for c in avail}


def grp(r):
    if r["ca"] > 0 and r["cb"] > 0:
        return "双正"
    if r["ca"] <= 0 and r["cb"] <= 0:
        return "双负"
    return "一正一负"


scan_rows = ""
for r in scan:
    hi = " style='background:#fdf6f5'" if r["pair"] in ("ETH+ADA", "BTC+ADA") else ""
    scan_rows += (
        f"<tr{hi}><td class='l'>{r['pair']}</td><td class='l'>{grp(r)}</td>"
        f"<td class='hl'>{r['nav']:.3f}x</td><td>{r['cagr'] * 100:+.2f}%</td>"
        f"<td class='neg'>{r['mdd'] * 100:.2f}%</td><td>{r['hold']:.3f}x</td>"
        f"<td class='{'pos' if r['ex'] > 0 else 'neg'}'><b>{r['ex'] * 100:+.2f}%</b></td>"
        f"<td>{r['vol'] * 100:.1f}%</td><td>{r['corr']:.3f}</td>"
        f"<td>{r['drift'] * 100:+.1f}pp</td>"
        f"<td class='l mono'>{'  '.join(f'{k} {v:.3f}' for k, v in r['chip'].items())}</td></tr>"
    )

gsum = {"双正": [], "双负": [], "一正一负": []}
for r in scan:
    gsum[grp(r)].append(r)
grp_rows = ""
for g in ("双正", "双负", "一正一负"):
    sub = gsum[g]
    if not sub:
        continue
    exs = [x["ex"] for x in sub]
    grp_rows += (
        f"<tr><td class='l'><b>{g}</b></td><td>{len(sub)}</td>"
        f"<td class='{'pos' if np.mean(exs) > 0 else 'neg'}'><b>{np.mean(exs) * 100:+.2f}%</b></td>"
        f"<td>{np.median(exs) * 100:+.2f}%</td>"
        f"<td class='mono'>{min(exs) * 100:+.2f}% ~ {max(exs) * 100:+.2f}%</td>"
        f"<td>{np.mean([x['vol'] for x in sub]) * 100:.1f}%</td>"
        f"<td>{np.mean([x['corr'] for x in sub]):.3f}</td></tr>"
    )
corr_vol = float(np.corrcoef([r["ex"] for r in scan], [r["vol"] for r in scan])[0, 1])
corr_drift = float(np.corrcoef([r["ex"] for r in scan], [abs(r["drift"]) for r in scan])[0, 1])
mean_vol = {g: float(np.mean([x["vol"] for x in gsum[g]])) for g in gsum if gsum[g]}
mean_ex = {g: float(np.mean([x["ex"] for x in gsum[g]])) for g in gsum if gsum[g]}
ea = by_pair["ETH+ADA"]
ba = by_pair["BTC+ADA"]

# ---------- 图1: 净值曲线 ----------
fig1 = go.Figure()
for name, ser, color, dash in [
    ("ETH+ADA 月度再平衡 (扣10bp)", cases["ETH"]["r10"]["nav_ser"], "#c0392b", None),
    ("ETH+ADA 等权死拿", cases["ETH"]["h"]["ser"], "#e07b63", "dash"),
    ("BTC+ADA 月度再平衡 (扣10bp)", cases["BTC"]["r10"]["nav_ser"], "#7d3c98", None),
    ("纯 ETH 死拿", cases["ETH"]["sa"]["ser"], "#e67e22", "dot"),
    ("纯 ADA 死拿", cases["ETH"]["sb"]["ser"], "#27ae60", "dot"),
]:
    fig1.add_trace(go.Scatter(x=ser.index, y=ser / ser.iloc[0], name=name, mode="lines",
                              line=dict(color=color, width=2.2, dash=dash)))
fig1.update_layout(
    title=f"美元口径净值曲线（起点=1，对数轴）  {NAT0.date()} ~ {END.date()}",
    yaxis=dict(type="log", title="净值（倍）"), xaxis=dict(title=""),
    template="plotly_white", height=540, hovermode="x unified",
    legend=dict(orientation="h", y=1.10, x=0), margin=dict(l=60, r=30, t=78, b=40),
    font=dict(size=13),
)

# ---------- 图2: 币量曲线 ----------
fig2 = go.Figure()
for tag, coin, color, dash in (("ETH", "ETH", "#f39c12", None), ("ETH", "ADA", "#8e44ad", None),
                               ("BTC", "BTC", "#2980b9", "dot"), ("BTC", "ADA", "#16a085", "dot")):
    us = cases[tag]["r0"]["units_ser"][coin]
    fig2.add_trace(go.Scatter(x=us.index, y=us, name=f"{tag}+ADA 组合内的 {coin}",
                              mode="lines", line=dict(color=color, width=2.2, dash=dash)))
fig2.add_hline(y=1.0, line=dict(color="#7f8c8d", width=1.6, dash="dash"),
               annotation_text="1.0 = 死拿不掉队线", annotation_position="bottom right")
fig2.update_layout(
    title="筹码口径：再平衡后每币持仓量 / 该组合死拿持仓量（起点均为 1.0）",
    yaxis=dict(type="log", title="币量倍数（倍）"), xaxis=dict(title=""),
    template="plotly_white", height=490, hovermode="x unified",
    legend=dict(orientation="h", y=1.09, x=0), margin=dict(l=60, r=30, t=70, b=40),
    font=dict(size=13),
)

FIG1 = fig1.to_html(include_plotlyjs="cdn", full_html=False, config={"responsive": True})
FIG2 = fig2.to_html(include_plotlyjs=False, full_html=False, config={"responsive": True})


def pct(x, d=2):
    return f"{x * 100:+.{d}f}%"


main_rows = ""
for tag in ("BTC", "ETH"):
    c = cases[tag]
    r10, h, sa, sb = c["r10"], c["h"], c["sa"], c["sb"]
    main_rows += (
        f"<tr><td class='l'><b>{c['a']}+{c['b']}</b></td>"
        f"<td class='hl'>{r10['nav']:.3f}x</td>"
        f"<td class='{'pos' if r10['cagr'] > 0 else 'neg'}'>{pct(r10['cagr'])}</td>"
        f"<td class='neg'>{r10['mdd'] * 100:.2f}%</td>"
        f"<td>{h['nav']:.3f}x</td><td>{pct(h['cagr'])}</td>"
        f"<td class='{'pos' if c['ex'] > 0 else 'neg'}'><b>{pct(c['ex'])}</b></td>"
        f"<td>{pct(r10['cagr'] - h['cagr'])}</td>"
        f"<td>{r10['turnover_ann'] * 100:.0f}%</td></tr>"
    )
    main_rows += (
        f"<tr class='sub'><td class='l'>&nbsp;&nbsp;└ 单币死拿</td>"
        f"<td colspan='3' class='mono'>{c['a']} {sa['nav']:.3f}x ({pct(sa['cagr'])}) ／ "
        f"{c['b']} {sb['nav']:.3f}x ({pct(sb['cagr'])})</td>"
        f"<td colspan='5' class='l mono'>筹码：{c['a']} {r10['units_mult'][c['a']]:.3f}x ／ "
        f"{c['b']} {r10['units_mult'][c['b']]:.3f}x</td></tr>"
    )

solo_rows = "".join(
    f"<tr><td class='l'>{c}</td><td>{mod.solo(px, c, NAT0, END)['nav']:.3f}x</td>"
    f"<td class='{'pos' if v > 0 else 'neg'}'>{v * 100:+.2f}%</td>"
    f"<td class='l'>{'正收益' if v > 0 else '负收益'}</td></tr>"
    for c, v in sorted(solo_cagr.items(), key=lambda kv: -kv[1])
)

eb, ee = cases["BTC"]["ex"], cases["ETH"]["ex"]
ub, ua_b = cases["BTC"]["r10"]["units_mult"]["BTC"], cases["BTC"]["r10"]["units_mult"]["ADA"]
ue, ua_e = cases["ETH"]["r10"]["units_mult"]["ETH"], cases["ETH"]["r10"]["units_mult"]["ADA"]
btc_drift = cases["BTC"]["sa"]["cagr"] - cases["BTC"]["sb"]["cagr"]
eth_drift = cases["ETH"]["sa"]["cagr"] - cases["ETH"]["sb"]["cagr"]

HTML = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>双币配对再平衡 · BTC+ADA 与 ETH+ADA</title>
<style>
  :root {{ --line:#e3e8ee; --ink:#1c2733; --muted:#66788a; --hl:#c0392b; --bg:#f7f9fb; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:32px 24px 64px; background:var(--bg); color:var(--ink);
         font-family:-apple-system,"Segoe UI","Microsoft YaHei",system-ui,sans-serif;
         line-height:1.72; font-size:15px; }}
  .wrap {{ max-width:1120px; margin:0 auto; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:12px;
           padding:26px 30px; margin-bottom:20px; box-shadow:0 1px 2px rgba(16,24,40,.04); }}
  h1 {{ font-size:25px; margin:0 0 6px; letter-spacing:-.2px; }}
  h2 {{ font-size:18px; margin:0 0 14px; padding-bottom:10px; border-bottom:1px solid var(--line); }}
  h3 {{ font-size:15px; margin:20px 0 8px; color:#2c3e50; }}
  .sub {{ color:var(--muted); font-size:13.5px; margin-bottom:0; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(215px,1fr)); gap:14px; }}
  .kpi {{ background:var(--bg); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .kpi .k {{ font-size:12.5px; color:var(--muted); }}
  .kpi .v {{ font-size:23px; font-weight:650; letter-spacing:-.5px; margin:2px 0; }}
  .kpi .n {{ font-size:12.5px; color:var(--muted); }}
  .red {{ color:var(--hl); }} .pos {{ color:#c0392b; }} .neg {{ color:#1e8449; }}
  table {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
  th,td {{ padding:9px 11px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }}
  th {{ background:#f2f5f8; font-weight:600; color:#3d4d5c; font-size:12.5px; }}
  td.l,th.l {{ text-align:left; }}
  td.hl {{ font-weight:650; }}
  tr.sub td {{ background:#fbfcfd; font-size:12.5px; color:var(--muted); }}
  .mono {{ font-family:"JetBrains Mono",Consolas,"Courier New",monospace; font-size:12.5px; }}
  tbody tr:hover {{ background:#fafcfe; }}
  .note {{ background:#fffbf0; border:1px solid #f0e0b8; border-left:4px solid #e0a800;
           border-radius:8px; padding:14px 18px; font-size:13.5px; color:#5c4a15; }}
  .key {{ background:#fdf2f0; border:1px solid #f2cfc9; border-left:4px solid var(--hl);
          border-radius:8px; padding:14px 18px; font-size:13.8px; }}
  .win {{ background:#f1f8f4; border:1px solid #c8e3d3; border-left:4px solid #1e8449;
          border-radius:8px; padding:14px 18px; font-size:13.8px; color:#17452e; }}
  ul {{ padding-left:20px; margin:8px 0; }} li {{ margin:5px 0; }}
  code {{ background:#eef2f6; padding:1px 6px; border-radius:4px; font-size:12.8px; }}
  .scroll {{ overflow-x:auto; }}
</style>
</head>
<body><div class="wrap">

<div class="card">
  <h1>双币配对再平衡：BTC+ADA 与 ETH+ADA</h1>
  <p class="sub">加密内部配对（不跨资产）· 月度等权再平衡 · 数据 <code>weekly_adjclose_crypto50_10y.csv</code>（周频后复权）·
  公共窗口 {NAT0.date()} ~ {END.date()}（{cases['BTC']['r0']['yrs']:.2f} 年，ADA 上市自然起点）</p>
</div>

<div class="card">
  <h2>一、结论摘要</h2>
  <div class="kpis">
    <div class="kpi"><div class="k">ETH+ADA 再平衡收益（扣10bp）</div><div class="v red">{cases['ETH']['r10']['nav']:.3f}x</div>
      <div class="n">CAGR {pct(cases['ETH']['r10']['cagr'])} · MDD {cases['ETH']['r10']['mdd'] * 100:.1f}%</div></div>
    <div class="kpi"><div class="k">ETH+ADA 相对死拿超额</div><div class="v red">{pct(ee)}</div>
      <div class="n">BTC+ADA 仅 {pct(eb)}，提升 {(ee - eb) * 100:.1f}pp</div></div>
    <div class="kpi"><div class="k">ETH 币量 / 死拿</div><div class="v">{ue:.3f}x</div>
      <div class="n">掉队 {(1 - ue) * 100:.0f}%（BTC+ADA 里 BTC 掉队 {(1 - ub) * 100:.0f}%）</div></div>
    <div class="kpi"><div class="k">ADA 币量 / 死拿</div><div class="v">{ua_e:.3f}x</div>
      <div class="n">BTC+ADA 组合里为 {ua_b:.3f}x</div></div>
  </div>

  <div class="key" style="margin-top:18px">
    <b>三点结论：</b>
    <ul>
      <li><b>您的直觉方向成立，但归因要修正。</b>ETH+ADA 的超额 <b>{pct(ee)}</b> 确实远高于 BTC+ADA 的 {pct(eb)}（近 3.5 倍）。
      但真正起作用的<b>不是"波动都大"</b>：15 组配对里，超额与组合波动的相关性只有 <b>{corr_vol:+.3f}</b>，
      而与"两币长期收益是否同向"的差距达 <b>{abs(mean_ex['双正'] - mean_ex['一正一负']) * 100:.0f}pp</b>（见第五节）。
      真正帮 ETH+ADA 的是 <b>漂移差从 {btc_drift * 100:.1f}pp 收窄到 {eth_drift * 100:.1f}pp</b>。</li>
      <li><b>绝对收益反而更低。</b>ETH+ADA 只有 {cases['ETH']['r10']['nav']:.3f}x（CAGR {pct(cases['ETH']['r10']['cagr'])}），
      低于 BTC+ADA 的 {cases['BTC']['r10']['nav']:.3f}x（{pct(cases['BTC']['r10']['cagr'])}）——
      因为 ETH 本身 8.4 年只涨 {cases['ETH']['sa']['nav']:.2f}x，而 BTC 涨 {cases['BTC']['sa']['nav']:.2f}x。
      <b>再平衡超额是"分配效率"，不是"收益来源"</b>：标的选错，收割再漂亮也补不回绝对收益。</li>
      <li><b>风险代价更高、收益更低。</b>ETH+ADA 组合年化波动 {ea['vol'] * 100:.1f}%、
      MDD <b>{cases['ETH']['r10']['mdd'] * 100:.2f}%</b>，比 BTC+ADA 的 {cases['BTC']['r10']['mdd'] * 100:.2f}% 更深 ——
      波动大确实让回撤更难看，却不保证换来更高的绝对收益。</li>
    </ul>
  </div>
</div>

<div class="card">
  <h2>二、两组配对主对照（全窗口，扣 10bp）</h2>
  <div class="scroll">
  <table>
    <thead><tr><th class="l">组合</th><th>再平衡净值</th><th>CAGR</th><th>MDD</th>
      <th>死拿净值</th><th>死拿CAGR</th><th>超额</th><th>年化超额</th><th>换手</th></tr></thead>
    <tbody>{main_rows}</tbody>
  </table>
  </div>
  <p class="sub" style="margin-top:12px">
  <b>怎么读：</b>"超额"衡量的是再平衡这台机器分配筹码的效率，与标的绝对涨跌无关；
  "再平衡净值"才是最终到手收益（= 机器效率 × 标的质量）。ETH+ADA 赢了前者、输了后者。</p>

  <h3>窗口内各币独立死拿（衡量"标的质量"）</h3>
  <table>
    <thead><tr><th class="l">币</th><th>净值</th><th>CAGR</th><th class="l">方向</th></tr></thead>
    <tbody>{solo_rows}</tbody>
  </table>
</div>

<div class="card">
  <h2>三、美元口径净值曲线</h2>
  {FIG1}
  <p class="sub">对数轴。ETH+ADA 再平衡（红）相对其死拿（浅红）的领先幅度，明显大于 BTC+ADA 再平衡（紫）相对其死拿的领先 —— 超额差异的可视化。</p>
</div>

<div class="card">
  <h2>四、筹码口径：囤了多少币</h2>
  {FIG2}
  <p class="sub">实线为 ETH+ADA 组合内的币量，虚线为 BTC+ADA 组合内的币量。四条线都要跟 1.0 线比：&gt;1 是加仓、&lt;1 是掉队。</p>
  <div class="note">
    <b>要点：</b>ETH+ADA 里 ETH 币量 {ue:.3f}x（掉队 {(1 - ue) * 100:.0f}%），好于 BTC+ADA 里 BTC 的 {ub:.3f}x（掉队 {(1 - ub) * 100:.0f}%）。
    原因是 ETH 相对 ADA 只强 {eth_drift * 100:.1f}pp／年，而 BTC 相对 ADA 强 {btc_drift * 100:.1f}pp／年 ——
    <b>强者越强，被再平衡搬走给弱者的筹码就越多</b>。
  </div>
</div>

<div class="card">
  <h2>五、全配对扫描：15 组双币配对横向对照（同窗口）</h2>
  <p class="sub">候选币 = 公共窗口内全程有数据的 {len(avail)} 个老币（{', '.join(avail)}），穷举 C({len(avail)},2)=15 组，按再平衡超额降序。</p>
  <div class="scroll">
  <table>
    <thead><tr><th class="l">币对</th><th class="l">漂移方向</th><th>再平衡</th><th>CAGR</th><th>MDD</th>
      <th>死拿</th><th>超额</th><th>组合波动</th><th>相关</th><th>漂移差</th><th class="l">筹码（/死拿）</th></tr></thead>
    <tbody>{scan_rows}</tbody>
  </table>
  </div>

  <h3>按"两币长期收益方向是否一致"分组 —— 真正的分界线</h3>
  <table>
    <thead><tr><th class="l">分组</th><th>组数</th><th>平均超额</th><th>中位超额</th><th>区间</th>
      <th>平均组合波动</th><th>平均相关</th></tr></thead>
    <tbody>{grp_rows}</tbody>
  </table>

  <div class="win" style="margin-top:16px">
    <b>决定性证据：</b>三个分组的<b>平均组合波动几乎相同</b>
    （双正 {mean_vol['双正'] * 100:.1f}% ／ 双负 {mean_vol['双负'] * 100:.1f}% ／ 一正一负 {mean_vol['一正一负'] * 100:.1f}%），
    但平均超额相差 <b>{abs(mean_ex['双正'] - mean_ex['一正一负']) * 100:.0f}pp</b>
    （{mean_ex['双正'] * 100:+.2f}% vs {mean_ex['一正一负'] * 100:+.2f}%）。
    所以分界不是波动率，而是<b>两币的长期收益方向是否一致</b> —— 这与框架第③条"无长期单边赢家/输家"是同一件事的两种说法。
  </div>

  <div class="note" style="margin-top:14px">
    <b>ETH+ADA 是"一正一负"组里最强的（{pct(ee)}，8 组中唯一超过 +10%）。</b>
    原因是它的漂移差（{eth_drift * 100:.1f}pp）在 8 组里最小；但它仍属结构性不利的那一类 ——
    该类别平均超额是 {mean_ex['一正一负'] * 100:+.2f}%。
    单变量相关：超额 ~ 组合波动 <b>{corr_vol:+.3f}</b>；超额 ~ |漂移差| <b>{corr_drift:+.3f}</b>。
  </div>
</div>

<div class="card">
  <h2>六、分周期拆解（两对并列，扣 10bp）</h2>
  <div class="scroll">
  <table>
    <thead><tr><th class="l">配对</th><th class="l">区间</th><th>年数</th><th>再平衡净值</th><th>CAGR</th>
      <th>MDD</th><th>死拿净值</th><th>超额</th><th>币A量</th><th>币B量</th></tr></thead>
    <tbody>{seg_rows}</tbody>
  </table>
  </div>
  <div class="note" style="margin-top:16px">
    <b>最值得注意的一段是段1（2018-04~2020-05 熊市）：</b>
    BTC+ADA 超额 <b style="color:#1e8449">-20.57%</b>（ADA 崩、BTC 相对抗跌 → 再平衡持续卖 BTC 补 ADA）；
    ETH+ADA 超额 <b style="color:#c0392b">+2.55%</b> —— 因为 ETH 与 ADA <b>同步下跌</b>（-41%/年 vs -56%/年），
    再平衡没有被单向拖拽，反而收割了协调波动的方差。<b>这是"方向一致性"在单段内的直接体现。</b>
  </div>
</div>

<div class="card">
  <h2>七、配对准入检验（框架三条件）</h2>
  <div class="scroll">
  <table>
    <thead><tr><th class="l">条件</th><th class="l">BTC+ADA</th><th class="l">ETH+ADA</th><th class="l">判定</th></tr></thead>
    <tbody>
      <tr><td class="l">① 低相关（&lt;0.3）</td>
        <td class="l mono">{ba['corr']:.3f}</td><td class="l mono">{ea['corr']:.3f}</td>
        <td class="l">⚠ 两者都偏高，且 ETH+ADA 还更高，却超额更大 → 相关不是这里的决定因素</td></tr>
      <tr><td class="l">② 高波动（&gt;20%）</td>
        <td class="l mono">{ba['vol'] * 100:.1f}%</td><td class="l mono">{ea['vol'] * 100:.1f}%</td>
        <td class="l">✅ 均满足；ETH+ADA 更高，但只换来更深的回撤</td></tr>
      <tr><td class="l">③ 无长期单边赢家/输家</td>
        <td class="l mono">BTC {pct(cases['BTC']['sa']['cagr'])} vs ADA {pct(cases['BTC']['sb']['cagr'])}<br>差 {btc_drift * 100:.1f}pp</td>
        <td class="l mono">ETH {pct(cases['ETH']['sa']['cagr'])} vs ADA {pct(cases['ETH']['sb']['cagr'])}<br>差 {eth_drift * 100:.1f}pp</td>
        <td class="l">❌ 两者都不满足，但 <b>ETH+ADA 的偏离小 {(1 - eth_drift / btc_drift) * 100:.0f}%</b> → 超额高 3.5 倍</td></tr>
    </tbody>
  </table>
  </div>
  <div class="note" style="margin-top:16px">
    <b>结论：</b>把三条件当打分卡，ETH+ADA 只在第③条上"少违规一点"，就拿到近 3.5 倍的超额 ——
    这说明第③条的<b>敏感度极高</b>，也说明"波动大"本身不是可交易的优势：
    它同时放大回撤（ETH+ADA MDD 达 {cases['ETH']['r10']['mdd'] * 100:.2f}%），只在漂移方向一致时才转化为超额。
  </div>
</div>

<div class="card">
  <h2>八、口径与可复现说明</h2>
  <ul>
    <li><b>数据源</b>：<code>markets/crypto/data/weekly_adjclose_crypto50_10y.csv</code>，周频、后复权（hfq）。</li>
    <li><b>窗口</b>：{NAT0.date()} ~ {END.date()}（{cases['BTC']['r0']['yrs']:.2f} 年），取两币公共起点（ADA 上市日）；
      15 组扫描只纳入该窗口内全程无缺的 {len(avail)} 个币，保证窗口一致可比。</li>
    <li><b>再平衡规则</b>：每 4 周（月度）重置为等权，区间内持仓量恒定。成本单边 10bp，按当期成交额扣减。</li>
    <li><b>收益口径</b>：美元 NAV = 组合市值 / 初始投入，<b>不是</b>币量倍数；币量倍数单独列示，二者不可混用。</li>
    <li><b>"超额"定义</b>：再平衡期末净值 ÷ 同币同窗口等权死拿期末净值 − 1，衡量再平衡机器本身，与标的绝对涨跌无关。</li>
    <li><b>复现</b>：<code>python markets/crypto/crypto_btc_ada_pair.py</code>（终端全量输出）／
        <code>python markets/crypto/build_btc_ada_report.py</code>（生成本报告）。</li>
    <li><b>免责</b>：历史回测不构成投资建议；15 组扫描为 8.4 年单一窗口的样本内事实，样本量小
      （"双负"组仅 1 例、"双正"6 例），分组均值不宜外推为稳定规律。</li>
  </ul>
</div>

</div></body></html>
"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"报告已生成: {OUT}")
for tag in ("BTC", "ETH"):
    c = cases[tag]
    print(f"  {c['a']}+{c['b']}: 再平衡 {c['r10']['nav']:.3f}x / CAGR {pct(c['r10']['cagr'])} / "
          f"MDD {c['r10']['mdd'] * 100:.2f}% / 超额 {pct(c['ex'])} / "
          f"筹码 {c['a']} {c['r10']['units_mult'][c['a']]:.3f}x, {c['b']} {c['r10']['units_mult'][c['b']]:.3f}x")
print(f"  15 组扫描分组: 双正 {mean_ex['双正'] * 100:+.2f}% / 双负 {mean_ex['双负'] * 100:+.2f}% / "
      f"一正一负 {mean_ex['一正一负'] * 100:+.2f}%")
print(f"  相关: 超额~波动 {corr_vol:+.3f} / 超额~|漂移差| {corr_drift:+.3f}")
