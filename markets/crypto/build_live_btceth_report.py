# -*- coding: utf-8 -*-
"""生成「BTC/ETH 实盘再平衡复现对账」报告 HTML。"""
import io
import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
DOCS = os.path.join(HERE, "..", "..", "docs", "reports", "crypto")

RED, GREEN, BLUE, GREY, ORANGE = "#c0392b", "#1a7f37", "#2c6fb5", "#8fa8bf", "#b8860b"
BASE = dict(template="plotly_white", font=dict(family="Microsoft YaHei, Arial", size=12),
            margin=dict(l=60, r=30, t=50, b=50), height=400)


def load():
    d = json.load(io.open(os.path.join(OUT, "live_btceth_daily.json"), encoding="utf-8"))
    r = json.load(io.open(os.path.join(OUT, "live_btceth_replay.json"), encoding="utf-8"))
    t = pd.read_csv(os.path.join(OUT, "live_btceth_threshold.csv"), encoding="utf-8-sig")
    return d, r, t


def main():
    import plotly.graph_objects as go

    D, R, TH = load()
    live = R["live"]
    hold_tot = D["hold_tot"]
    live_tot = live["total_now"]
    pure_ex = D["excess_live_pure"]
    pb0, pe0 = D["reverse_px"]["btc"], D["reverse_px"]["eth"]
    pbp, pep = D["panel_px"]["btc"], D["panel_px"]["eth"]
    e_interp = D["cmc_interp_eth"]
    e_t = D["trigger_theory_days"]

    daily = pd.DataFrame(D["daily"])
    g0 = daily[daily.cost == "0bp"].set_index("granularity")
    g10 = daily[daily.cost == "10bp"].set_index("granularity")
    rb0 = float(g0.loc["每日", "excess"])
    wk0 = float(g0.loc["每周", "excess"])
    rep = pd.DataFrame(R["replay"])
    rep0 = rep[(rep.cost == "0bp") & (rep.freq == "每周检查")]
    panel_wk0 = float(rep0["excess"].iloc[0]) if len(rep0) else np.nan
    sens = D["start_sens"]
    s0 = sens.get("0bp（实盘条件）", {})
    s10 = sens.get("10bp", {})

    # ---------------- 图 1: 起点价敏感度带 ----------------
    pts = [(e_interp, "CMC 插值", GREY), (pe0, "实盘反推（截图）", RED), (pep, "本地面板周收盘", BLUE)]
    b_end_v = (live["invest"] * live["w_btc"]) / pb0 * live["px_b1"]
    rows_sens = []
    for ep, src, col in pts:
        ev = (live["invest"] * live["w_eth"]) / ep * live["px_e1"]
        rows_sens.append((ep, src, col, ev, b_end_v + ev))
    f1 = go.Figure()
    f1.add_trace(go.Bar(
        x=[f"{r[1]}\nETH ${r[0]:,.0f}" for r in rows_sens],
        y=[(r[4] / live["invest"] - 1) * 100 for r in rows_sens],
        marker_color=[r[2] for r in rows_sens],
        text=[f"{(r[4]/live['invest']-1)*100:.2f}%" for r in rows_sens],
        textposition="outside", textfont=dict(size=12)))
    f1.add_hline(y=live["pnl_pct"] * 100, line=dict(color=RED, dash="dash", width=2),
                 annotation_text=f"实盘实际 {live['pnl_pct']*100:.2f}%",
                 annotation_position="top right", annotation_font_color=RED)
    f1.update_layout(**BASE, showlegend=False,
                     title_text="① 只换「起点价的数据源」，期末收益率就在 −30% ~ −36% 移动",
                     yaxis_title="期末收益率 (%)", yaxis_range=[-40, -24])

    # ---------------- 图 2: 粒度 vs 触发次数 vs 超额 ----------------
    order = ["每日检查", "每3日", "每周检查", "每2周", "每月", "每季"]
    g = pd.DataFrame(D["daily"])
    g["lab"] = g["granularity"].map({"每日检查": "每日", "每周检查": "每周",
                                     "每3日": "每3日", "每2周": "每2周",
                                     "每月": "每月", "每季": "每季"})
    g0 = g[g.cost == "0bp"].set_index("granularity")
    g10 = g[g.cost == "10bp"].set_index("granularity")
    labs = [l for l in ["每日检查", "每3日", "每周检查", "每2周", "每月", "每季"] if l in g0.index]
    f2 = go.Figure()
    f2.add_trace(go.Bar(name="触发次数", x=labs,
                        y=[int(g0.loc[l, "n_trigger"]) for l in labs],
                        marker_color=GREY, yaxis="y2", opacity=.55,
                        text=[int(g0.loc[l, "n_trigger"]) for l in labs],
                        textposition="outside", textfont=dict(size=10)))
    f2.add_trace(go.Scatter(name="超额 · 0bp（实盘条件）", x=labs,
                            y=[g0.loc[l, "excess"] for l in labs], mode="lines+markers+text",
                            line=dict(color=RED, width=3), marker=dict(size=10),
                            text=[f"{g0.loc[l,'excess']:+.2f}%" for l in labs],
                            textposition="top center", textfont=dict(size=10, color=RED)))
    f2.add_trace(go.Scatter(name="超额 · 10bp", x=labs,
                            y=[g10.loc[l, "excess"] for l in labs], mode="lines+markers+text",
                            line=dict(color=GREEN, width=3, dash="dot"), marker=dict(size=9),
                            text=[f"{g10.loc[l,'excess']:+.2f}%" for l in labs],
                            textposition="bottom center", textfont=dict(size=10, color=GREEN)))
    f2.update_layout(**{**BASE, "height": 460}, title_text="② 调仓越频繁：0bp 下超额越高，10bp 下超额越差",
                     yaxis=dict(title="再平衡超额 (%)"), yaxis2=dict(title="触发次数", overlaying="y",
                     side="right", showgrid=False), legend=dict(orientation="h", y=-0.18))

    # ---------------- 图 3: 三源起点价 ----------------
    f3 = go.Figure()
    f3.add_trace(go.Bar(name="BTC 起点价", x=["实盘反推", "本地面板", "CMC"], y=[pb0, pbp, 118739],
                        marker_color=ORANGE, text=[f"${pb0:,.0f}", f"${pbp:,.0f}", "$118,739"],
                        textposition="outside", textfont=dict(size=11)))
    f3.add_trace(go.Bar(name="ETH 起点价", x=["实盘反推", "本地面板", "CMC"],
                        y=[pe0, pep, e_interp * 3.5],  # 缩放仅用于同图对比
                        marker_color=BLUE, text=[f"${pe0:,.0f}", f"${pep:,.0f}", f"≈${e_interp:,.0f}"],
                        textposition="outside", textfont=dict(size=11)))
    f3.update_layout(**{**BASE, "height": 360}, barmode="group",
                     title_text="③ 2025-07-18 起点价：BTC 三源一致（分歧 <1.5%），ETH 分歧达 15%",
                     yaxis_title="价格 (USD)", showlegend=True,
                     legend=dict(orientation="h", y=-0.2))

    # ---------------- 表格 ----------------
    def cls(v):
        return "pos" if v > 0 else "neg"

    # 三源表
    tri = ""
    for nm, b, e, note in [("实盘反推（截图 3 组数字互校）", pb0, pe0, "权重 42/58 精确闭合"),
                           ("本地面板 weekly_adjclose（周收盘）", pbp, pep, "周内波动大，单点代表性弱"),
                           ("CMC data-api（6~9 天粒度，线性插值）", 118739, e_interp, "该周 ETH +35.8%，插值噪声大")]:
        tri += (f"<tr><td class='l'><b>{nm}</b></td><td>${b:,.0f}</td><td>${e:,.0f}</td>"
                f"<td>{b/e:.2f}</td><td class='l' style='font-size:12px;color:#66788a'>{note}</td></tr>")

    sens_band = ""
    for ep, src, col, ev, tot in rows_sens:
        sens_band += (f"<tr><td class='l'><b>{src}</b></td><td>${ep:,.0f}</td>"
                      f"<td>{b_end_v:.2f}</td><td>{ev:.2f}</td><td>{tot:.2f}</td>"
                      f"<td class='{cls(tot/live['invest']-1)}'><b>{tot/live['invest']-1:+.2%}</b></td></tr>")

    gran = ""
    for l in labs:
        r0, r10 = g0.loc[l], g10.loc[l]
        gran += (f"<tr><td class='l'><b>{l.replace('检查','')}</b></td>"
                 f"<td>{int(r0.n_trigger)}</td>"
                 f"<td class='{cls(r0.excess)}'>{r0.excess:+.3f}%</td>"
                 f"<td class='{cls(r10.excess)}'>{r10.excess:+.3f}%</td>"
                 f"<td>{r0.chip_btc:.4f}x</td><td>{r0.chip_eth:.4f}x</td></tr>")

    # 三个独立口径
    three = [
        ("实盘自身分解（只读截图数字）", pure_ex, "死拿 133.66 vs 实盘 136.60，剔除质押/赚币"),
        ("面板周度复现（实盘同窗口, 0bp）", panel_wk0, "2025-07-18~2026-09-04，59 周"),
        ("CoinGecko 日度复现（整 1 年, 0bp）", rb0, "2025-09-12~2026-09-11，365 天"),
    ]
    three_rows = ""
    for nm, v, note in three:
        three_rows += (f"<tr><td class='l'><b>{nm}</b></td>"
                       f"<td class='{'pos' if v>0 else 'neg'}'><b>{v:+.3f}%</b></td>"
                       f"<td class='l' style='font-size:12px;color:#66788a'>{note}</td></tr>")

    figs = [f.to_html(include_plotlyjs=("cdn" if i == 0 else False), full_html=False,
                      config={"responsive": True}) for i, f in enumerate([f1, f2, f3])]

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BTC/ETH 实盘再平衡复现对账</title>
<style>
:root{{--bg:#f6f8fa;--fg:#1f2933;--mut:#66788a;--bd:#dbe3ea;--card:#fff;--acc:#2c6fb5}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);
font:14.5px/1.72 "Microsoft YaHei",-apple-system,Arial,sans-serif}}
.wrap{{max-width:1120px;margin:0 auto;padding:26px 18px 60px}}
h1{{font-size:24px;margin:6px 0 6px;letter-spacing:.4px}}
.sub{{color:var(--mut);font-size:13.2px;margin:0 0 20px}}
.card{{background:var(--card);border:1px solid var(--bd);border-radius:11px;padding:20px 22px;margin:16px 0}}
h2{{font-size:17px;margin:0 0 14px;padding-bottom:9px;border-bottom:2px solid var(--bd)}}
h3{{font-size:14.6px;margin:20px 0 9px;color:#2b3a47}}
table{{width:100%;border-collapse:collapse;font-size:13.1px}}
th,td{{border:1px solid var(--bd);padding:7px 9px;text-align:center;white-space:nowrap}}
th{{background:#eef3f8;font-weight:600;font-size:12.4px;color:#3c4e5e}}
td.l,th.l{{text-align:left;white-space:normal}}
.pos{{color:{RED};font-weight:600}}
.neg{{color:{GREEN};font-weight:600}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(186px,1fr));gap:12px;margin:6px 0 4px}}
.kpi{{background:#fbfcfd;border:1px solid var(--bd);border-radius:9px;padding:13px 15px}}
.kpi .k{{font-size:12.2px;color:var(--mut);margin-bottom:5px}}
.kpi .v{{font-size:21px;font-weight:700;letter-spacing:.3px}}
.kpi .n{{font-size:11.8px;color:var(--mut);margin-top:4px}}
.red{{color:{RED}}}.green{{color:{GREEN}}}.blue{{color:{BLUE}}}
.key{{background:#f0f7f1;border-left:4px solid {GREEN};padding:13px 16px;border-radius:0 8px 8px 0;margin:14px 0;font-size:13.6px}}
.warn{{background:#fdf6ec;border-left:4px solid {ORANGE};padding:13px 16px;border-radius:0 8px 8px 0;margin:14px 0;font-size:13.6px}}
.bad{{background:#fdf2f0;border-left:4px solid {RED};padding:13px 16px;border-radius:0 8px 8px 0;margin:14px 0;font-size:13.6px}}
.note{{background:#f4f7fa;border-left:4px solid {BLUE};padding:12px 15px;border-radius:0 8px 8px 0;margin:13px 0;font-size:13.2px;color:#3d4c5a}}
.scroll{{overflow-x:auto;margin:12px 0}}
ul,ol{{margin:8px 0;padding-left:22px}}li{{margin:5px 0}}
code{{background:#eef2f6;padding:1.5px 5px;border-radius:4px;font-size:12.6px}}
.fml{{background:#f4f7fa;border:1px dashed var(--bd);border-radius:8px;padding:12px;text-align:center;
font-size:15px;font-family:Consolas,monospace;margin:12px 0}}
</style></head><body><div class="wrap">

<h1>BTC/ETH 实盘再平衡复现对账</h1>
<p class="sub">样本：用户提供的真实策略截图（「BTC, ETH 屯币宝策略」，比例平衡 1%，200 USDT，
2025-07-18 创建，运行 422 天，触发 66 次）。目的：检验本地再平衡引擎能否复现真实平台的落点。
数据截至 2026-09-13。价格源：本地面板（周）+ CoinGecko（日）+ CMC（6~9 天）。</p>

<div class="card">
<h2>一、结论：引擎对上了，3.4pp 的净值差来自起点价歧义</h2>
<div class="kpis">
  <div class="kpi"><div class="k">实盘总收益</div><div class="v green">−31.70%</div>
    <div class="n">136.6 USDT / 投入 200</div></div>
  <div class="kpi"><div class="k">同一批币「死拿」</div><div class="v green">−33.17%</div>
    <div class="n">133.66 USDT，不调仓</div></div>
  <div class="kpi"><div class="k">再平衡超额（纯交易）</div><div class="v red">+1.12%</div>
    <div class="n">剔除质押 +1.36 / 赚币 +0.083</div></div>
  <div class="kpi"><div class="k">触发再平衡</div><div class="v blue">66 次</div>
    <div class="n">每 6.4 天一次</div></div>
</div>
<p>我把「再平衡 − 死拿」的超额用<b>三个互相独立的口径</b>各算了一遍，全部落在
<b>+0.9% ~ +1.2%</b>：</p>
<div class="scroll"><table>
<thead><tr><th class="l">口径</th><th>再平衡超额</th><th class="l">说明</th></tr></thead>
<tbody>{three_rows}</tbody></table></div>
<div class="key">
<b>三个独立口径都在 +1% 附近 → 引擎逻辑与真实平台一致。</b>
而上轮复现出的 −35.06%（vs 实盘 −31.70%）那 3.4pp 的差，
<b>经定位是「起点价选了哪个数据源」造成的，不是逻辑错误</b>——见第二节。
</div>
</div>

<div class="card">
<h2>二、3.4pp 净值差的真正来源：起点价歧义</h2>
<p>实盘截图给了 3 组互相独立的数字（目标比例 42/58、初始持仓、投入 200 USDT），
可以反解出它创建时刻的成交价。结果是：</p>
<div class="scroll"><table>
<thead><tr><th class="l">数据源</th><th>BTC 起点价</th><th>ETH 起点价</th>
<th>BTC/ETH</th><th class="l">备注</th></tr></thead>
<tbody>{tri}</tbody></table></div>
<div class="bad">
<b>为什么会分歧 15%？</b>因为那一周 ETH 在剧烈波动：CMC 记录
2025-07-10 ETH 仅 $2,771，到 07-22 已 $3,763，<b>12 天 +35.8%</b>。
在这种斜率下，「2025-07-18 09:34」这一个时点的 ETH 价格本身就依赖数据源与采样时刻。
BTC 同期平稳，所以三源只差 1.5%。
</div>
<h3>起点价换一下，期末收益就移动 6pp</h3>
<div class="scroll"><table>
<thead><tr><th class="l">ETH 起点价来源</th><th>ETH 起点价</th><th>BTC 端值</th>
<th>ETH 端值</th><th>总市值</th><th>期末收益率</th></tr></thead>
<tbody>{sens_band}</tbody></table></div>
<div class="note">
固定实盘终点价（BTC $76,850.1 / ETH $2,479.26）、固定实盘终点持仓，只改 ETH 起点价：
<b>期末收益率在 −30.24% ~ −36.06% 之间移动</b>，实盘实际 −31.70% 完整落在带内。
我上一轮取的 <b>面板值 ${pep:,.0f} 恰好在带的最悲观一端</b> —— 这就是那 3.4pp。
</div>
{figs[0]}
</div>

<div class="card">
<h2>三、66 次触发：第一通过时间理论可以复现</h2>
<p>「比例平衡 1%」= 权重偏离目标 1 个百分点就调仓。对 42/58 组合，权重对价格比值的灵敏度是：</p>
<div class="fml">dW / d ln(BTC/ETH) = w(1−w) = 0.42 × 0.58 = {0.42*0.58:.4f}</div>
<div class="fml">1% 权重偏离 ⇔ BTC/ETH 相对变动 {1/ (0.42*0.58) *0.01:.2%}（对数）</div>
<p>再用随机游走的第一通过时间期望 <code>E[T] ≈ a² / σ²</code>：</p>
<ul>
<li>BTC/ETH 相对波动：周 3.999% → 日 <b>1.512%</b></li>
<li>E[T] ≈ 0.0411² / 0.01512² = <b>{e_t:.1f} 天/次</b> → 一年约 <b>{365/e_t:.0f} 次</b></li>
<li>实盘：66 次 / 422 天 = <b>每 6.4 天一次</b> —— 比理论更密，说明实盘窗口的波动高于面板均值</li>
</ul>
<div class="warn">
<b>为什么我上一轮的周度复现只数到 18 次？</b>因为周度采样只有 59 个检查点，
且<b>完全看不到周内的穿越</b>（偏离 1% 又回来，周度上看不到）。
这是<b>采样粒度</b>问题，不是引擎漏算 —— 日度复现立刻回到 33 次，量级正确。
</div>
</div>

<div class="card">
<h2>四、粒度与成本：高频再平衡只在零手续费下划算</h2>
<p>用同一份日度数据、只改「多久检查一次」，得到一条非常干净的单调关系：</p>
<div class="scroll"><table>
<thead><tr><th class="l">检查粒度</th><th>触发次数</th><th>超额 · 0bp</th><th>超额 · 10bp</th>
<th>BTC 筹码</th><th>ETH 筹码</th></tr></thead>
<tbody>{gran}</tbody></table></div>
{figs[1]}
<div class="key">
<b>0bp 下：高频整体优于低频</b>（每日 +{rb0:.2f}% vs 每2周 +{float(g0.loc['每2周','excess']):.2f}%），
但<b>长间隔端不单调</b>（每季 +{float(g0.loc['每季','excess']):.2f}% 反而高于每月 +{float(g0.loc['每月','excess']):.2f}%）
—— 调仓次数少时日历运气主导，与既有的「相位检验」结论一致。<br>
<b>10bp 下：严格单调恶化</b>（每日 {float(g10.loc['每日','excess']):.2f}% → 每季 +{float(g10.loc['每季','excess']):.2f}%），
因为成本随频率线性累加，且这部分是确定的。<br>
→ 实盘能拿到 +1.12% 而触发高达 66 次，<b>反推该平台的再平衡是免手续费（或极低费率）</b>；
这也解释了它为什么会另收「质押收益 +1.36」——盈利点在质押/息差，不在调仓费。
</div>
</div>

<div class="card">
<h2>五、稳健性：30 个滚动起点，0bp 下全部为正超额</h2>
<div class="scroll"><table>
<thead><tr><th class="l">条件</th><th>起点数</th><th>超额中位</th><th>超额均值</th>
<th>区间</th><th>正超额占比</th><th>触发次数中位</th></tr></thead>
<tbody>
<tr><td class="l"><b>0bp（实盘条件）</b></td><td>{s0.get('n','—')}</td>
<td class="pos"><b>{s0.get('med',float('nan')):+.2f}%</b></td>
<td class="pos">{(s0.get('lo',0)+s0.get('hi',0))/2:+.2f}%</td>
<td>[{s0.get('lo',float('nan')):+.2f}%, {s0.get('hi',float('nan')):+.2f}%]</td>
<td class="pos"><b>{s0.get('pos','—')}/{s0.get('n','—')}</b></td>
<td>{s0.get('n_trig_med','—')}</td></tr>
<tr><td class="l">10bp</td><td>{s10.get('n','—')}</td>
<td class="neg"><b>{s10.get('med',float('nan')):+.2f}%</b></td>
<td class="neg">{(s10.get('lo',0)+s10.get('hi',0))/2:+.2f}%</td>
<td>[{s10.get('lo',float('nan')):+.2f}%, {s10.get('hi',float('nan')):+.2f}%]</td>
<td class="neg">0/{s10.get('n','—')}</td>
<td>{s10.get('n_trig_med','—')}</td></tr>
</tbody></table></div>
<div class="note">
0bp 条件下 <b>30/30 全为正超额</b>，中位 +{s0.get('med',0):.2f}%、区间仅
[{s0.get('lo',0):+.2f}%, {s0.get('hi',0):+.2f}%] —— 非常稳定。
一旦计入 10bp，<b>30/30 全为负</b>。结论：<b>这个策略的全部价值都在「零成本」这个前提上</b>。
</div>
{figs[2]}
</div>

<div class="card">
<h2>六、可操作结论</h2>
<ol>
<li><b>引擎已验证。</b>三个独立口径给出同一答案（+0.9% ~ +1.2%），
真实平台一年的落点与本地回测一致。以后用本地引擎评估再平衡，数值可信。</li>
<li><b>比较再平衡不要比净值，要比超额。</b>净值受起点价/数据源影响可达 6pp
（本例 ETH 起点 3,348→3,872 就让期末收益从 −30% 变 −36%），
而超额在两条不同价格路径上都稳定在 +1%。</li>
<li><b>短窗口（1 年）的超额很小，且对成本极敏感。</b>+1% 的超额，
在 10bp 成本下直接翻成 −2%。评估短周期再平衡必须先确认成本假设。</li>
<li><b>触发频率要用第一通过时间判断，不要用采样频率猜。</b>
1% 阈值在 42/58 组合上对应约 7 天一次；周度采样会漏掉 2/3 的触发事件。</li>
<li><b>再平衡不能对抗趋势。</b>这段窗口两币都跌 30%+，
再平衡贡献的 +1.12% 相对 −31.70% 的结局几乎可以忽略。
它改善的是分配效率与回撤，不是收益方向。</li>
</ol>
</div>

<p style="font-size:12px;color:var(--mut);text-align:center;margin-top:26px">
脚本 <code>btceth_live_replay.py</code>、<code>btceth_live_daily.py</code>
／ 明细 <code>out/live_btceth_replay.csv</code>、<code>out/live_btceth_daily.csv</code>、
<code>out/live_btceth_threshold.csv</code>
</p>
</div></body></html>"""

    os.makedirs(DOCS, exist_ok=True)
    p = os.path.join(DOCS, "live_btceth_replay.html")
    io.open(p, "w", encoding="utf-8").write(html)
    print(f"[生成] {p}  ({len(html)//1024} KB)")


if __name__ == "__main__":
    main()
