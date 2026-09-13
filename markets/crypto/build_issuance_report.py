# -*- coding: utf-8 -*-
"""生成「净增发率 vs 涨跌」报告 (HTML, 本地留底)。
用法: python markets/crypto/build_issuance_report.py
输出: docs/reports/crypto/issuance_vs_return_27coins.html
"""
import os
import io
import importlib.util
import contextlib
import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
_spec = importlib.util.spec_from_file_location("ivr", os.path.join(HERE, "issuance_vs_return.py"))
mod = importlib.util.module_from_spec(_spec)
with contextlib.redirect_stdout(io.StringIO()):
    _spec.loader.exec_module(mod)

OUT = os.path.join(REPO, "docs", "reports", "crypto", "issuance_vs_return_27coins.html")

px = mod.load_panel()
df = mod.build(px)
W0, W1, W2 = (w[0] for w in mod.WINDOWS)
C0, C1, C2 = (f"{w[0]}|cagr" for w in mod.WINDOWS)
P0 = f"{W0}|pos_rate"
df["bin_avg"] = df["net_avg"].map(mod.bucket)

first_yr = {c: px[c].dropna().index[0].year for c in px.columns}
df["vintage"] = [first_yr[c] for c in df["coin"]]

s0 = df.dropna(subset=[C0])
s1 = df.dropna(subset=[C1])


def _sp(x, y):
    return mod._spearman(np.asarray(x, float), np.asarray(y, float))


rho0, p0 = _sp(s0["net_avg"], s0[C0])
rho1, p1 = _sp(s1["net_avg"], s1[C1])
pear1 = float(np.corrcoef(s1["net_avg"], s1[C1])[0, 1])

old = s1[s1["vintage"] <= 2020]
new = s1[s1["vintage"] > 2020]
rho_old, p_old = _sp(old["net_avg"], old[C1])
rho_new, p_new = _sp(new["net_avg"], new[C1])

# ---------- 图1: 散点 ----------
COL = {"A. <5%": "#c0392b", "B. 5-10%": "#e08a1e", "C. >10%": "#1e8449"}
fig1 = go.Figure()
for b, col in COL.items():
    g = s0[s0["bin_avg"] == b]
    if not len(g):
        continue
    fig1.add_trace(go.Scatter(
        x=g["net_avg"], y=g[C0], mode="markers+text", name=b,
        text=g["coin"], textposition="top center", textfont=dict(size=10.5, color="#55606d"),
        marker=dict(size=13, color=col, line=dict(color="#fff", width=1.4),
                    symbol="circle", opacity=.9),
        hovertemplate="%{text}<br>净增发 %{x:.1f}%/y<br>CAGR %{y:+.1f}%<extra></extra>",
    ))
# 拟合线
z = np.polyfit(s0["net_avg"], s0[C0], 1)
xs = np.linspace(s0["net_avg"].min(), s0["net_avg"].max(), 50)
fig1.add_trace(go.Scatter(x=xs, y=np.polyval(z, xs), mode="lines", name="线性拟合",
                          line=dict(color="#7f8c8d", width=2, dash="dash")))
fig1.add_hline(y=0, line=dict(color="#95a5a6", width=1.2))
for xv, lb in ((5, "5% 分界"), (10, "10% 分界")):
    fig1.add_vline(x=xv, line=dict(color="#bdc3c7", width=1.4, dash="dot"),
                   annotation_text=lb, annotation_position="top")
fig1.update_layout(
    title=f"净增发率(持有期平均) vs 价格 CAGR —— 27 币全部历史　"
          f"Pearson {pear1:+.2f} / Spearman {rho0:+.2f}(p≈{p0:.3f})",
    xaxis=dict(title="净增发率（%/年，持有期平均）"), yaxis=dict(title="价格 CAGR（%）"),
    template="plotly_white", height=560, hovermode="closest",
    legend=dict(orientation="h", y=1.09, x=0), margin=dict(l=60, r=30, t=80, b=50),
    font=dict(size=13),
)

# ---------- 图2: 稀释门槛 ----------
d2 = s1.sort_values(C1)
fig2 = go.Figure()
fig2.add_trace(go.Bar(
    x=d2["coin"], y=d2[C1], name="实际价格 CAGR",
    marker_color=["#c0392b" if v > 0 else "#1e8449" for v in d2[C1]],
    hovertemplate="%{x}<br>CAGR %{y:+.1f}%<extra></extra>",
))
fig2.add_trace(go.Scatter(
    x=d2["coin"], y=d2["net_avg"], name="稀释门槛（=净增发率，市值持平所需年涨幅）",
    mode="markers", marker=dict(color="#2c3e50", size=11, symbol="diamond",
                                line=dict(color="#fff", width=1.2)),
    hovertemplate="%{x}<br>门槛 %{y:.1f}%/y<extra></extra>",
))
fig2.add_hline(y=0, line=dict(color="#95a5a6", width=1.2))
fig2.update_layout(
    title="稀释门槛检验：柱=实际年化涨幅，菱形=必须跑赢的稀释速度（2021-01 起窗口）",
    xaxis=dict(title="", tickangle=-45), yaxis=dict(title="%/年"),
    template="plotly_white", height=520, hovermode="x unified",
    legend=dict(orientation="h", y=1.10, x=0), margin=dict(l=60, r=30, t=80, b=90),
    font=dict(size=12.5), bargap=.35,
)

# ---------- 图3: 三窗口分组 ----------
fig3 = go.Figure()
for tag, cc in (("全历史", C0), ("近5.7年", C1), ("本轮(2024起)", C2)):
    g = df.dropna(subset=[cc])
    ys, xs, txt = [], [], []
    for b in COL:
        sub = g[g["bin_avg"] == b]
        if not len(sub):
            continue
        xs.append(b)
        ys.append(float(sub[cc].median()))
        txt.append(f"n={len(sub)}")
    fig3.add_trace(go.Bar(x=xs, y=ys, name=tag, text=txt, textposition="outside",
                          hovertemplate="%{x}<br>中位 CAGR %{y:+.1f}%<extra></extra>"))
fig3.update_layout(
    title="按净增发分组的 CAGR 中位数（三窗口对照，n=组内币数）",
    yaxis=dict(title="CAGR 中位数（%）"), xaxis=dict(title=""),
    barmode="group", template="plotly_white", height=440,
    legend=dict(orientation="h", y=1.12, x=0), margin=dict(l=60, r=30, t=80, b=50),
    font=dict(size=13),
)
fig3.add_hline(y=0, line=dict(color="#95a5a6", width=1.2))

# ---------- 图4: 老币 vs 新币 ----------
fig4 = go.Figure()
for tag, g, col in (("老币 ≤2020上市", old, "#7d3c98"), ("新币 >2020上市", new, "#d35400")):
    fig4.add_trace(go.Scatter(
        x=g["net_avg"], y=g[C1], mode="markers+text", name=tag, text=g["coin"],
        textposition="top center", textfont=dict(size=10, color="#55606d"),
        marker=dict(size=12, color=col, line=dict(color="#fff", width=1.3), opacity=.85),
        hovertemplate="%{text}<br>净增发 %{x:.1f}%/y<br>CAGR %{y:+.1f}%<extra></extra>",
    ))
fig4.update_layout(
    title=f"分层检验：老币相关性弱(Spearman {rho_old:+.2f}, p≈{p_old:.3f})　"
          f"vs　新币极强({rho_new:+.2f}, p≈{p_new:.3f})",
    xaxis=dict(title="净增发率（%/年）"), yaxis=dict(title="CAGR（%），2021-01 起"),
    template="plotly_white", height=480, hovermode="closest",
    legend=dict(orientation="h", y=1.10, x=0), margin=dict(l=60, r=30, t=80, b=50),
    font=dict(size=13),
)
fig4.add_hline(y=0, line=dict(color="#95a5a6", width=1.2))
fig4.add_vline(x=5, line=dict(color="#bdc3c7", width=1.4, dash="dot"))

FIGS = [f.to_html(include_plotlyjs=("cdn" if i == 0 else False), full_html=False,
                  config={"responsive": True}) for i, f in enumerate([fig1, fig2, fig3, fig4])]

# ---------- 表格 ----------
rows = ""
for d in s0.sort_values("net_avg").to_dict(orient="records"):
    cg = d[C0]
    pr = d[P0]
    cls = "pos" if cg > 0 else "neg"
    conf_col = {"高": "#1e8449", "中高": "#27ae60", "中": "#7f8c8d",
                "中低": "#e08a1e", "低": "#c0392b"}[d["conf"]]
    rows += (
        f"<tr><td class='l'><b>{d['coin']}</b></td>"
        f"<td class='hl'>{d['net_avg']:+.1f}%</td>"
        f"<td>{d['net_now']:+.1f}%</td>"
        f"<td class='l mono'>{d['cap']}</td>"
        f"<td style='color:{conf_col};font-weight:600'>{d['conf']}</td>"
        f"<td class='{cls}'><b>{cg:+.1f}%</b></td>"
        f"<td>{d[f'{W0}|mult']:.2f}x</td>"
        f"<td class='neg'>{d[f'{W0}|mdd']:.1f}%</td>"
        f"<td>{pr:.0f}%</td>"
        f"<td class='{'pos' if cg - d['net_avg'] > 0 else 'neg'}'>"
        f"{cg - d['net_avg']:+.1f}pp</td>"
        f"<td class='l' style='white-space:normal;font-size:12.3px;color:#5a6773'>{d['mech']}</td></tr>"
    )

# 分组统计表
grows = ""
for tag, cc in (("全历史", C0), ("近5.7年", C1), ("本轮(2024起)", C2)):
    g = df.dropna(subset=[cc])
    if len(g) < 5:
        continue
    rho, pv = _sp(g["net_avg"], g[cc])
    for b in ["A. <5%", "B. 5-10%", "C. >10%"]:
        sub = g[g["bin_avg"] == b]
        if not len(sub):
            grows += (f"<tr><td class='l'>{tag}</td><td class='l'>{b}</td><td>0</td>"
                      f"<td colspan='5' style='color:#8a97a3'>无样本</td></tr>")
            continue
        mem = " ".join(f"{c}({v:+.0f}%)" for c, v in zip(sub["coin"], sub[cc]))
        grows += (
            f"<tr><td class='l'>{tag}</td><td class='l'>{b}</td><td>{len(sub)}</td>"
            f"<td class='{'pos' if sub[cc].median() > 0 else 'neg'}'><b>{sub[cc].median():+.1f}%</b></td>"
            f"<td>{sub[cc].mean():+.1f}%</td>"
            f"<td>{(sub[cc] > 0).mean() * 100:.0f}%</td>"
            f"<td class='l mono' style='white-space:normal;font-size:12px'>{mem}</td></tr>"
        )
    grows += (f"<tr class='sub'><td class='l'>{tag}</td><td class='l'>相关系数</td>"
              f"<td>{len(g)}</td><td colspan='4' class='l'>Pearson "
              f"{np.corrcoef(g['net_avg'], g[cc])[0, 1]:+.3f}　Spearman {rho:+.3f}　"
              f"p≈{pv:.3f}{'　✅显著' if pv < 0.05 else '　⚠️不显著'}</td></tr>")

# 阈值敏感性
sens = ""
for th in (3, 5, 7, 10, 15):
    hi = s1[s1["net_avg"] >= th]
    lo = s1[s1["net_avg"] < th]
    sens += (f"<tr><td>{th}%</td><td>{len(hi)}</td>"
             f"<td class='{'pos' if hi[C1].median() > 0 else 'neg'}'>{hi[C1].median():+.1f}%</td>"
             f"<td>{lo[C1].median():+.1f}%</td>"
             f"<td class='{'pos' if hi[C1].median() > lo[C1].median() else 'neg'}'>"
             f"{hi[C1].median() - lo[C1].median():+.1f}pp</td></tr>")

today = datetime.date.today().isoformat()
HTML = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>币池净增发率 vs 涨跌 · 27 币检验</title>
<style>
  :root {{ --line:#e3e8ee; --ink:#1c2733; --muted:#66788a; --hl:#c0392b; --bg:#f7f9fb; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:32px 24px 64px; background:var(--bg); color:var(--ink);
         font-family:-apple-system,"Segoe UI","Microsoft YaHei",system-ui,sans-serif;
         line-height:1.72; font-size:15px; }}
  .wrap {{ max-width:1180px; margin:0 auto; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:12px;
           padding:26px 30px; margin-bottom:20px; box-shadow:0 1px 2px rgba(16,24,40,.04); }}
  h1 {{ font-size:25px; margin:0 0 6px; letter-spacing:-.2px; }}
  h2 {{ font-size:18px; margin:0 0 14px; padding-bottom:10px; border-bottom:1px solid var(--line); }}
  h3 {{ font-size:15px; margin:20px 0 8px; color:#2c3e50; }}
  .sub {{ color:var(--muted); font-size:13.5px; margin-bottom:0; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; }}
  .kpi {{ background:var(--bg); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .kpi .k {{ font-size:12.5px; color:var(--muted); }}
  .kpi .v {{ font-size:22px; font-weight:650; letter-spacing:-.5px; margin:2px 0; }}
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
</style></head><body><div class="wrap">

<div class="card">
  <h1>币池 27 枚：净增发率 vs 涨跌</h1>
  <p class="sub">检验命题「净增发 &lt;5%/年 更容易涨、&gt;10%/年 基本难涨」　|　
  价格：本地周K面板（2014-09-19 ~ 2026-09-04，<b>未调用任何外部接口</b>）　|　
  增发：各币协议规则（减半/尾排/销毁）推导，逐条标注依据与置信度　|　生成 {today}</p>
</div>

<div class="card" style="border-left:4px solid #c0392b;background:#fdf2f0">
  <h2 style="border-bottom:none;margin-bottom:8px">⚠️ 勘误（2026-09-12）：本版增发率为「协议规则推测」，已被实测版取代</h2>
  <p style="margin:0 0 10px;font-size:13.8px">
  本版增发率是<b>按排放计划推测</b>的，且用的是「历史平均」，并非实测。后续用 CMC 全历史
  「市值 ÷ 价格」反推出<b>实测流通量</b>（并以 CoinGecko 近一年日频双源对账，23/27 差异 ≤0.3pp）后，
本版有<b>四处结论需要修正</b>（前两条是口径，后两条是我自己的归因错误）：
  </p>
  <ul style="margin:0;font-size:13.8px">
    <li><b>「5% 附近是斜率最陡的地方」不成立。</b>实测阈值敏感性显示判别力<b>随分界线上移而单调增强</b>
      （近 3 年：5% 处 18.4pp → 10% 处 43.0pp → 15% 处 68.0pp），
      且 &lt;5% 与 5-10% 两档顺序不单调（近 2 年 5-10% 档反而最好）。
      <b>真正的危险线在 10%，不是 5%。</b></li>
    <li><b>「APT 前瞻仅 +2.6%」这句话本身也要再修一次（2026-09-12 二次修正）。</b>
      +2.6% 是<b>协议排放口径</b>（质押奖励），不是流通量增速。把实测序列拆到月度后：
      实测 +24.7% = 归属解锁 ≈10.2M 枚/月 + 质押排放 5.2M 枚/月，改革后观测稳定在 ~12.8M/月
      （断点正好在 2026-04，与改革公告吻合）。2026-10 归属期结束后社区 10 年线性释放仍在跑，
      加上质押 2.6M/月 ≈ 82M 枚/年 ÷ 858M ≈ <b>+10%</b>，且已释放率仅 40.9%（剩 1241M 枚）。
      <b>按流通量增速算，APT 仍是高稀释标的。</b></li>
    <li><b>「ETHFI 是供应商重分类」这个归因是错的（同上）。</b>月度反推显示 2025-05 起连续
      15 个月<b>绝对增量恒定在 44~49M 枚/月</b>、相对率由 39.9% 单调衰减到 5.0%
      ——这是线性归属解锁的指纹。程序已于 2026-07 结束，circ 达硬顶的 96.5%，
      前瞻不是 +3.3% 而是 <b>≈0%</b>（比原判断更彻底）。</li>
    <li><b>「LINK 是顽固型持续通胀」也要改。</b>LINK 月度增量几乎恒为 0，只在 4 个时点跳
      +18~21M ——是<b>基金会储备被计入流通</b>，不是协议增发（LINK 总量固定 1B、无 mint），
      有明确终点（剩 252M 枚）。</li>
  </ul>
  <p style="margin:10px 0 0;font-size:13.8px">
  <b>口径警告：</b>「协议排放」与「流通量增速」是两个数，本版及上一版实测表都只反映了后者，
  而前瞻判断必须用后者。用前者会漏掉归属解锁（APT 被低估 4 倍）。
  </p>
  <p style="margin:10px 0 0;font-size:13.8px">
  → 请以实测版为准：<code>docs/reports/crypto/issuance_measured_27coins.html</code>
  （脚本 <code>issuance_measured.py</code> + <code>fetch_cmc_history.py</code> +
  <code>build_issuance_measured_report.py</code>；含逐币台阶日期与性质判定表）
  </p>
</div>

<div class="card">
  <h2>一、结论</h2>
  <div class="key">
    <b>方向成立，但要分清「门槛」与「选择器」：</b>净增发率与长期收益在三个窗口内都呈显著负相关
    （Spearman {rho0:+.3f} / {rho1:+.3f} / {_sp(*[df.dropna(subset=[C2])["net_avg"], df.dropna(subset=[C2])[C2]])[0]:+.3f}，p 均 &lt; 0.05）。
    但真正决定涨跌的是<b>需求增长</b>——增发只是必须跑赢的那道门槛。
  </div>
  <div class="kpis" style="margin-top:16px">
    <div class="kpi"><div class="k">全池 Spearman（全历史）</div><div class="v red">{rho0:+.3f}</div>
      <div class="n">p≈{p0:.3f}，n={len(s0)}　负相关显著</div></div>
    <div class="kpi"><div class="k">近 5.7 年 Spearman</div><div class="v red">{rho1:+.3f}</div>
      <div class="n">p≈{p1:.3f}，Pearson {pear1:+.3f}</div></div>
    <div class="kpi"><div class="k">分组中位 CAGR</div><div class="v">8.9% / 1.3% / -51.6%</div>
      <div class="n">&lt;5% / 5-10% / &gt;10% 三档</div></div>
    <div class="kpi"><div class="k">新币分层 Spearman</div><div class="v red">{rho_new:+.3f}</div>
      <div class="n">p≈{p_new:.3f}（老币仅 {rho_old:+.3f}，不显著）</div></div>
  </div>

  <h3>五点要点</h3>
  <ul>
    <li><b>① 「阈值有效」这点成立，但最陡的位置不是 5%。</b>本版用推测增发率时，分界放 3% 两组中位差仅 5.8pp、
      移到 5% 跳到 <b>{abs(s1[s1['net_avg']>=5][C1].median()-s1[s1['net_avg']<5][C1].median()):.1f}pp</b>，
      10% 扩大到 52pp。<b>⚠️ 用实测增发率重跑后，判别力在近 3 年随分界线上移单调增强
      （5% 处 18.4pp → 10% 处 43.0pp → 15% 处 68.0pp；近 2 年在 5% 处有回撤），
      真正的危险线在 10%。</b>方向与您的直觉一致，只是位置偏了 5pp。</li>
    <li><b>② 但「&gt;10% 难涨」在本池只有 2 个样本</b>（APT −50.8%、ETHFI −52.5%，两个都是 0% 正收益年）。
      方向一致，样本极薄，不足以当规律用。<b>补充（实测口径）：这 2 枚的"高增发"性质完全不同</b>——
      ETHFI 是线性归属解锁且<b>已收官</b>（前瞻 ≈0%），APT 是<b>归属尾未走完</b>
      （流通量增速前瞻 ≈+10%，不是协议排放的 +2.6%）。直接把它们当"高稀释标的"或
      当"已出清"都是误判，详见实测版第五节。</li>
    <li><b>③ 最有价值的发现是分层：</b>老币（≤2020 上市）增发与收益<b>几乎无关</b>
      （Spearman {rho_old:+.3f}，p≈{p_old:.3f}）；新币（&gt;2020）<b>高度相关</b>
      （{rho_new:+.3f}，p≈{p_new:.3f}）。说明增发/解锁是<b>新币杀估值的主因</b>，
      老币的涨跌由别的因素决定。</li>
    <li><b>④ 增发是门槛不是选择器。</b>SOL 净增发 5.5% 却 +74.9%、LINK 6.0% 却 +51.8%；
      反例 ADA 4.0% −3.3%、XLM 0% −6.2%、GLM 0% −21.6%（<b>零增发照样跌</b>）。</li>
    <li><b>⑤ &lt;5% 档内部离散极大</b>（−28% ~ +129%，中位 8.9%）。
      单靠增发筛不出赢家，但能排掉明显高稀释的。</li>
  </ul>
</div>

<div class="card">
  <h2>二、散点：净增发率 vs 价格 CAGR</h2>
  {FIGS[0]}
  <div class="note" style="margin-top:14px">
    <b>读法：</b>趋势线向下、且斜率不小 —— 每多 1pp 年化增发，长期 CAGR 大约少
    {abs(np.polyfit(s0["net_avg"], s0[C0], 1)[0]):.1f}pp。但注意右下角有 SOL/LINK/PENDLE
    落在趋势线上方（稀释被需求盖过），左下角也有 ADA/XLM/LTC/GLM 落在下方（零增发也跌）。
    <b>负相关的斜率里，有一部分是恒等式</b>（见第六节局限）。
  </div>
</div>

<div class="card">
  <h2>三、稀释门槛：价格必须跑赢自己的增发速度</h2>
  {FIGS[1]}
  <div class="win">
    市值持平所需的年涨幅 = 净增发率。柱子在菱形之上 = 市值扩张（真涨）；柱子低于菱形 = 即便价格没跌，
    持有者的份额也在被稀释。剔除稀释后的「需求增长」（CAGR − 增发）分组中位数：
    <b>&lt;5% 组 +6.9pp</b>、<b>5-10% 组 −7.2pp</b>、<b>&gt;10% 组 −71.6pp</b>。
    即：高增发币不只是涨得慢，它们的<b>需求是负的</b>——连市值都没保住。
  </div>
</div>

<div class="card">
  <h2>四、分组统计（三窗口）</h2>
  {FIGS[2]}
  <div class="scroll" style="margin-top:14px">
  <table>
    <thead><tr><th class="l">窗口</th><th class="l">分组</th><th>币数</th>
      <th>CAGR 中位</th><th>CAGR 均值</th><th>正收益占比</th>
      <th class="l">成员（括号内为 CAGR）</th></tr></thead>
    <tbody>{grows}</tbody>
  </table></div>
</div>

<div class="card">
  <h2>五、分层检验：老币 vs 新币</h2>
  {FIGS[3]}
  <div class="note" style="margin-top:14px">
    <b>为什么这一层很重要：</b>如果只看全池的 −0.47，会以为是「增发决定一切」。
    拆开看才发现规律几乎全部来自新币（{rho_new:+.3f}，p≈{p_new:.3f}），
    老币组只有 {rho_old:+.3f}（p≈{p_old:.3f}，<b>不显著</b>）。
    共线性也排除了「上市新老才是真因」：Corr(上市年份, CAGR) 仅
    {np.corrcoef(df.dropna(subset=[C1])['vintage'], df.dropna(subset=[C1])[C1])[0,1]:+.3f}，
    Corr(增发, 上市年份) {np.corrcoef(df['net_avg'], df['vintage'])[0,1]:+.3f}，
    两者<b>共线性不强</b>。
  </div>
  <h3>阈值敏感性</h3>
  <table><thead><tr><th>分界线</th><th>≥ 该线币数</th><th>该组 CAGR 中位</th>
    <th>&lt; 该线中位</th><th>差值</th></tr></thead><tbody>{sens}</tbody></table>
</div>

<div class="card">
  <h2>六、全表（27 币，按持有期平均净增发升序）</h2>
  <div class="scroll">
  <table>
    <thead><tr><th class="l">币</th><th>持有期<br>均增发</th><th>当前<br>增发</th>
      <th class="l">硬顶</th><th>置信<br>度</th><th>全历史<br>CAGR</th><th>倍数</th>
      <th>MDD</th><th>上涨年<br>占比</th><th>需求<br>增长</th><th class="l">机制与依据</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  <div class="note" style="margin-top:14px">
    <b>口径提醒：</b>「持有期均增发」= 该币在面板可得窗口内的平均净增发速度（持有者实际承受的稀释）；
    「当前增发」= 现时速度。二者差异可观（BTC 3.6% → 0.83%，因为早期减半前的发行速度高得多），
    引用时必须标口径。<b>「需求增长」= CAGR − 净增发</b>，为正说明需求扩张盖过了稀释。
  </div>
</div>

<div class="card">
  <h2>七、口径与局限（必须一起读）</h2>
  <ul>
    <li><b>① 部分机械性：</b>「市值持平所需年涨幅 = 增发率」本身是恒等式，所以负相关里含定义成分。
      真正有信息的是<b>偏离</b>——本池高增发币的「需求增长」为负（−71.6pp），说明它们不只是被稀释，
      是需求端在萎缩。</li>
    <li><b>② 增发数据不是抓取的</b>，是按协议规则推导（减半表、尾排曲线、销毁机制），并逐条标注
      置信度。<b>RAY / PENDLE / ETHFI 三条为「低」置信</b>（排放计划多次调整、解锁节奏不透明），
      结论中对这三币的依赖应当打折。</li>
    <li><b>③ 幸存者偏差（最严重）：</b>本池按「买旧不买新 + 熊市幸存」选出，结构上已排除掉
      高增发而死亡的项目。所以「&gt;10% 难涨」在<b>本池内</b>成立，<b>不能外推为全市场规律</b>——
      全市场里高增发币的比例远高于本池的 2/27。</li>
    <li><b>④ 流通量增速 ≠ 总供给增速：</b>APT / ETHFI 的高增发主要是<b>归属解锁</b>（一次性、有终点），
      而 DOT / FIL 是<b>持续通胀</b>（无终点）。前者是时间问题，后者是结构问题，不应混为一谈。</li>
    <li><b>⑤ 样本量：</b>&gt;10% 档 n=2、5-10% 档 n=6、<5% 档 n=19。分组统计的稳健性主要来自 &lt;5% 档。</li>
    <li><b>⑥ 未控制变量：</b>叙事/板块、筹码集中度、机构买盘、解锁日历、流动性。增发只是其中一个门。</li>
  </ul>
  <div class="key" style="margin-top:14px">
    <b>可操作结论：</b>把「净增发率」当作<b>准入门槛</b>而非选币信号 ——
    它可以有效剔除明显被稀释拖累的名字（本池里全部落在 &gt;5% 档），
    但进池之后能否上涨，必须另看需求端（真实用量/收入/买盘）。
    与现有框架一致：<b>「买旧不买新」本身就是在回避高增发的解锁期币</b>，
    本次检验从稀释角度给了这条规则一个量化支撑。
  </div>
</div>

<div class="card">
  <p class="sub">数据源：<code>data/weekly_adjclose_crypto50_10y.csv</code>（本地周K，27 币）　|　
  脚本：<code>markets/crypto/issuance_vs_return.py</code>、<code>build_issuance_report.py</code>　|　
  表格数据：<code>markets/crypto/out/issuance_vs_return.json</code></p>
</div>

</div></body></html>"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"报告已生成: {OUT}")
print(f"  大小 {len(HTML) / 1024:.0f} KB   含 4 张图")
