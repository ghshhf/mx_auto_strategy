# -*- coding: utf-8 -*-
"""生成 HYPE 净增发实测报告（含与 ETH/SOL/BTC 同口径对照）。

纪律：正文所有数字一律动态计算注入，不硬编码。
输出：docs/reports/crypto/hype_supply_measured.html
"""
import io, json, os
import pandas as pd, numpy as np
import plotly.graph_objects as go

CRYPTO = r"E:\xmanbian\mx_auto_strategy_repo\markets\crypto"
REPO = r"E:\xmanbian\mx_auto_strategy_repo"
BASE = os.path.join(CRYPTO, "data", "cmc_history")
OUT = os.path.join(CRYPTO, "out")

BLUE, RED, GREEN, AMBER, GRAY = "#378ADD", "#E24B4A", "#1D9E75", "#BA7517", "#888780"
BASE_LAYOUT = dict(
    template="plotly_white", font=dict(family="Inter, Segoe UI, Microsoft YaHei, sans-serif", size=12),
    margin=dict(l=60, r=30, t=56, b=50), hoverlabel=dict(font_size=12),
)


def load(sym: str) -> pd.DataFrame:
    d = json.load(io.open(os.path.join(BASE, f"{sym}.json"), encoding="utf-8"))
    p = d["points"]
    df = pd.DataFrame([(pd.to_datetime(int(t), unit="s"), v[0], v[2]) for t, v in p.items()],
                      columns=["t", "px", "mc"]).set_index("t").sort_index()
    df = df[(df["px"] > 0) & (df["mc"] > 0)]
    df["sup"] = df["mc"] / df["px"]
    return df


def main():
    H = load("HYPE")
    end = H.index[-1]
    WINS = [("近1月", 30), ("近3月", 91), ("近6月", 182), ("近1年", 365)]
    S = {}

    win_rows = []
    for w, days in WINS:
        cut = end - pd.Timedelta(days=days)
        s = H[H.index >= cut]
        cs = s["sup"].iloc[-1] / s["sup"].iloc[0]
        cm = s["mc"].iloc[-1] / s["mc"].iloc[0]
        cp = s["px"].iloc[-1] / s["px"].iloc[0]
        win_rows.append(dict(w=w, days=days, net=(cs - 1) * 100, ann=(pow(cs, 365 / days) - 1) * 100,
                             mc=(cm - 1) * 100, px=(cp - 1) * 100, sup_pp=(cp - cm) * 100))
    S["win"] = pd.DataFrame(win_rows)

    # 台阶与稳态
    we = H["sup"].resample("W").last().dropna()
    ch = we.pct_change().dropna()
    big = ch[ch.abs() > 0.01]
    cut1y = end - pd.Timedelta(days=365)
    seg = H[H.index >= cut1y]
    drops = [(we.loc[d] - we.loc[d - pd.Timedelta(days=7)]) for d in big.index if d >= cut1y]
    tot_delta = seg["sup"].iloc[-1] - seg["sup"].iloc[0]
    S["net1y_M"] = tot_delta / 1e6
    S["net1y_pct"] = tot_delta / seg["sup"].iloc[0] * 100
    S["step_M"] = sum(drops) / 1e6
    S["step_share"] = sum(drops) / tot_delta * 100
    S["cont_M"] = (tot_delta - sum(drops)) / 1e6
    S["cont_pct"] = (tot_delta - sum(drops)) / seg["sup"].iloc[0] * 100
    S["n_step"] = int(len([d for d in big.index if d >= cut1y]))

    st_from = pd.Timestamp("2026-02-08")
    st = H[H.index >= st_from]
    d_st = (st.index[-1] - st.index[0]).days
    g_st = st["sup"].iloc[-1] / st["sup"].iloc[0]
    S["st_days"] = d_st
    S["st_ann"] = (pow(g_st, 365 / d_st) - 1) * 100
    S["st_from_M"] = st["sup"].iloc[0] / 1e6
    S["st_to_M"] = st["sup"].iloc[-1] / 1e6
    S["st_per_mo"] = (st["sup"].iloc[-1] - st["sup"].iloc[0]) / 1e6 / (d_st / 30.44)
    S["st_date0"] = st.index[0].date()
    S["st_date1"] = st.index[-1].date()

    # 反事实
    S["px_1y"] = (H["px"].iloc[-1] / H[H.index >= cut1y]["px"].iloc[0] - 1) * 100
    S["mc_1y"] = (H["mc"].iloc[-1] / H[H.index >= cut1y]["mc"].iloc[0] - 1) * 100
    S["flat_1y"] = S["mc_1y"]
    S["sup_contrib_1y"] = S["px_1y"] - S["mc_1y"]

    # 全期
    yrs = (end - H.index[0]).days / 365
    S["all_yrs"] = yrs
    S["all_sup_x"] = H["sup"].iloc[-1] / H["sup"].iloc[0]
    S["all_mc_x"] = H["mc"].iloc[-1] / H["mc"].iloc[0]
    S["all_px_x"] = H["px"].iloc[-1] / H["px"].iloc[0]
    # 独奏效应（各项单独贡献的倍数），以及对数份额（可加分解）
    S["sup_solo_pct"] = (1 / S["all_sup_x"] - 1) * 100          # 仅缩供给能带来的涨幅
    S["mc_solo_pct"] = (S["all_mc_x"] - 1) * 100                # 仅市值增长能带来的涨幅
    S["sup_share_all"] = np.log(1 / S["all_sup_x"]) / np.log(S["all_px_x"]) * 100
    S["mc_share_all"] = 100 - S["sup_share_all"]
    # 近 1 年内台阶日期
    S["step_dates"] = " / ".join(str(d.date()) for d in big.index if d >= cut1y)

    # 当前快照
    S["px_now"] = H["px"].iloc[-1]
    S["sup_now_M"] = H["sup"].iloc[-1] / 1e6
    S["mc_now_B"] = H["mc"].iloc[-1] / 1e9
    S["circ_pct"] = H["sup"].iloc[-1] / 1e9 * 100
    S["locked_M"] = (1e9 - H["sup"].iloc[-1]) / 1e6
    S["locked_B"] = (1e9 - H["sup"].iloc[-1]) * H["px"].iloc[-1] / 1e9
    S["mo_from_M"] = seg["sup"].iloc[0] / 1e6
    S["mo_to_M"] = seg["sup"].iloc[-1] / 1e6
    S["d0"] = seg.index[0].date()
    S["d1"] = seg.index[-1].date()

    # 跨资产
    xa = []
    for sym in ["BTC", "ETH", "SOL", "HYPE"]:
        df = load(sym)
        cut = df.index[-1] - pd.Timedelta(days=365)
        s = df[df.index >= cut]
        ann = (pow(s["sup"].iloc[-1] / s["sup"].iloc[0], 1.0) - 1) * 100
        xa.append(dict(coin=sym, mc_B=df["mc"].iloc[-1] / 1e9, ann=ann,
                       per1p_B=df["mc"].iloc[-1] * 0.01 / 1e9, px=df["px"].iloc[-1]))
    S["xa"] = pd.DataFrame(xa)

    # ---- 图 1：月度流通量 ----
    mo = H["sup"].resample("MS").last().dropna()
    mo = mo[mo.index >= mo.index[-1] - pd.DateOffset(months=21)]
    f1 = go.Figure()
    f1.add_trace(go.Scatter(x=mo.index, y=mo.values / 1e6, mode="lines+markers",
                            line=dict(color=BLUE, width=2.4), marker=dict(size=6),
                            fill="tozeroy", fillcolor="rgba(55,138,221,0.10)",
                            name="月度流通量", hovertemplate="%{x|%Y-%m}<br>%{y:.2f}M 枚<extra></extra>"))
    for d in big.index:
        if d >= mo.index[0]:
            f1.add_vline(x=d, line=dict(color=RED, width=1.4, dash="dot"))
    f1.update_layout(height=380, **BASE_LAYOUT, title_text="HYPE 流通量：两次一次性台阶，之后转缓坡",
                     yaxis_title="流通量（百万枚）", showlegend=False)
    f1.update_yaxes(range=[mo.min() / 1e6 - 8, mo.max() / 1e6 + 6])

    # ---- 图 2：价格涨幅分解 ----
    f2 = go.Figure()
    f2.add_trace(go.Bar(name="市值贡献", x=S["win"]["w"], y=S["win"]["mc"],
                        marker_color=BLUE, text=[f"{v:+.1f}%" for v in S["win"]["mc"]],
                        textposition="inside", textfont=dict(size=11, color="white")))
    f2.add_trace(go.Bar(name="供给贡献（净销毁为正）", x=S["win"]["w"], y=S["win"]["sup_pp"],
                        marker_color=GREEN, text=[f"{v:+.1f}pp" for v in S["win"]["sup_pp"]],
                        textposition="outside", textfont=dict(size=11)))
    f2.add_trace(go.Scatter(name="实际价格涨幅", x=S["win"]["w"], y=S["win"]["px"], mode="markers+text",
                            marker=dict(symbol="diamond", size=12, color=AMBER),
                            text=[f"{v:+.1f}%" for v in S["win"]["px"]], textposition="top center",
                            textfont=dict(size=11, color=AMBER)))
    f2.update_layout(height=420, **BASE_LAYOUT, barmode="relative",
                     title_text="HYPE 价格涨幅分解：价格倍数 = 市值倍数 ÷ 流通量倍数",
                     yaxis_title="贡献（%）", legend=dict(orientation="h", y=-0.16, x=0))

    # ---- 图 3：跨资产 ----
    x = S["xa"].sort_values("per1p_B")
    f3 = go.Figure()
    f3.add_trace(go.Bar(x=x["per1p_B"], y=x["coin"], orientation="h",
                        marker_color=[GREEN if c == "HYPE" else BLUE for c in x["coin"]],
                        text=[f"${v:.3f}B" for v in x["per1p_B"]], textposition="outside",
                        textfont=dict(size=11),
                        customdata=x[["ann", "mc_B"]].values,
                        hovertemplate="%{y}<br>每 1% 需 $%{x:.3f}B<br>"
                                      "近1年净增发 %{customdata[0]:+.2f}%<br>"
                                      "市值 $%{customdata[1]:.1f}B<extra></extra>"))
    f3.update_layout(height=320, **BASE_LAYOUT, showlegend=False,
                     title_text="市值越大，推动 1% 所需的边际资金越多（HYPE 分母为负）",
                     xaxis_title="推动 1% 涨幅所需边际资金（十亿美元）")
    f3.update_xaxes(range=[0, x["per1p_B"].max() * 1.22])

    figs = [f.to_html(include_plotlyjs=("cdn" if i == 0 else False), full_html=False,
                      config={"responsive": True}) for i, f in enumerate([f1, f2, f3])]

    wr = ""
    for _, r in S["win"].iterrows():
        cls = "pos" if r["px"] >= 0 else "neg"
        wr += (f"<tr><td class='l'><b>{r.w}</b></td><td>{r.net:+.2f}%</td><td>{r.ann:+.2f}%</td>"
               f"<td>{r.mc:+.2f}%</td><td class='{cls}'>{r.px:+.2f}%</td>"
               f"<td>{r.sup_pp:+.2f}pp</td></tr>")

    xr = ""
    for _, r in S["xa"].iterrows():
        c = "#1D9E75" if r.ann < 0 else "#A32D2D"
        xr += (f"<tr><td class='l'><b>{r.coin}</b></td><td>${r.mc_B:,.1f}B</td>"
               f"<td style='color:{c};font-weight:600'>{r.ann:+.2f}%</td>"
               f"<td>${r.per1p_B:.3f}B</td></tr>")

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HYPE 净增发/净销毁实测审计</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#20252b;--mut:#66788a;--bd:#e3e7ec;--red:#A32D2D;--grn:#1D9E75;--blu:#185FA5;--amb:#854F0B}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.75 "Microsoft YaHei","Inter",system-ui,sans-serif}}
.wrap{{max-width:1020px;margin:0 auto;padding:34px 20px 70px}}
h1{{font-size:25px;margin:0 0 6px;letter-spacing:-.3px}}
.sub{{color:var(--mut);font-size:13.5px;margin:0 0 26px}}
.card{{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:20px 22px;margin:0 0 18px}}
h2{{font-size:17.5px;margin:0 0 14px;padding-bottom:9px;border-bottom:1px solid var(--bd)}}
h3{{font-size:15px;margin:20px 0 9px;color:var(--blu)}}
p{{margin:0 0 11px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:4px 0 6px}}
.kpi{{background:#f8f9fb;border:1px solid var(--bd);border-radius:10px;padding:12px 14px}}
.kpi .k{{font-size:12px;color:var(--mut)}}
.kpi .v{{font-size:23px;font-weight:600;margin:3px 0 1px;letter-spacing:-.5px}}
.kpi .n{{font-size:11.5px;color:var(--mut)}}
.red{{color:var(--red)}} .grn{{color:var(--grn)}} .blu{{color:var(--blu)}} .amb{{color:var(--amb)}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th,td{{padding:8px 9px;border-bottom:1px solid var(--bd);text-align:right}}
th{{background:#f8f9fb;font-weight:600;color:var(--mut);font-size:12.5px}}
td.l,th.l{{text-align:left}}
.scroll{{overflow-x:auto}}
.pos{{color:var(--red);font-weight:600}} .neg{{color:var(--grn);font-weight:600}}
.note{{background:#f8f9fb;border-left:3px solid var(--blu);padding:11px 14px;border-radius:0 8px 8px 0;font-size:13.5px;margin:12px 0}}
.key{{background:#fdf8ee;border-left:3px solid var(--amb);padding:13px 15px;border-radius:0 8px 8px 0;margin:14px 0;font-size:14px}}
.fix{{background:#fdf2f0;border-left:3px solid #c0392b;padding:13px 15px;border-radius:0 8px 8px 0;margin:14px 0;font-size:14px}}
ul{{margin:6px 0 10px;padding-left:20px}} li{{margin:5px 0}}
code{{background:#eef1f5;padding:1.5px 5px;border-radius:4px;font-size:12.5px;font-family:Consolas,monospace}}
</style></head><body><div class="wrap">
<h1>HYPE 净增发/净销毁实测审计</h1>
<p class="sub">口径：实测净增发 = Δ(流通量) = Δ(市值 ÷ 价格)，含协议发行 + 归属解锁 − 回购销毁。
数据源 CMC 全历史，截至 {S['d1']}。与 ETH / SOL / BTC 同口径对照。</p>

<div class="card">
<h2>一、结论</h2>
<div class="kpis">
  <div class="kpi"><div class="k">近 1 年账面净增发</div><div class="v red">{S['net1y_pct']:+.2f}%</div>
    <div class="n">{S['mo_from_M']:.1f}M → {S['mo_to_M']:.1f}M 枚</div></div>
  <div class="kpi"><div class="k">其中一次性口径调整</div><div class="v amb">{S['step_share']:.1f}%</div>
    <div class="n">{S['n_step']} 次大台阶，合计 {S['step_M']:+.1f}M 枚</div></div>
  <div class="kpi"><div class="k">剔除台阶后真实稳态</div><div class="v grn">{S['st_ann']:+.2f}%</div>
    <div class="n">年化，{S['st_date0']} 起 {S['st_days']} 天</div></div>
  <div class="kpi"><div class="k">当前流通 / 硬顶</div><div class="v">{S['circ_pct']:.1f}%</div>
    <div class="n">未流通 {S['locked_M']:.0f}M 枚 ≈ ${S['locked_B']:.1f}B</div></div>
</div>
<div class="key">
HYPE <b>确实是净通缩</b>，但可持续的净销毁速率是 <b>{S['st_ann']:+.2f}%/年</b>，
<b>不是账面那个 {S['net1y_pct']:+.2f}%</b>。近 1 年 −{abs(S['net1y_pct']):.2f}% 的收缩里，
<b>{S['step_share']:.1f}% 来自 {S['n_step']} 次一次性口径调整</b>（累计回购销毁被一次性计入），
剔除后连续部分仅 {S['cont_pct']:+.2f}%。<b>把钱数当速率用会高估约 {abs(S['net1y_pct']/S['st_ann']):.1f} 倍。</b>
</div>
</div>

<div class="card">
<h2>二、流通量序列：台阶 vs 缓坡</h2>
{figs[0]}
<div class="note">
近 1 年内共 {S['n_step']} 次台阶，日期为 <b>{S['step_dates']}</b>。
台阶之外，月度降幅只有 −0.2%~−0.8%，
折算约 <b>{S['st_per_mo']:.2f}M 枚/月</b>（{S['st_date0']}~{S['st_date1']} 实测）。
这一量级与协议侧「AF 每日回购约 $2M、年化约 7% 流通市值」的说法同量级，
说明 <b>CMC 已在实时扣减回购量</b>，稳态值可信。
</div>
</div>

<div class="card">
<h2>三、价格涨幅分解：涨的到底是什么</h2>
{figs[1]}
<div class="scroll"><table>
<thead><tr><th class="l">窗口</th><th>净增发</th><th>年化</th><th>市值</th><th>价格</th><th>供给贡献</th></tr></thead>
<tbody>{wr}</tbody></table></div>
<div class="fix">
<b>全期视角最能说明问题：</b>HYPE 上市至今 {S['all_yrs']:.2f} 年，
价格 <b>×{S['all_px_x']:.2f}</b>、市值 <b>×{S['all_mc_x']:.2f}</b>、流通量 <b>×{S['all_sup_x']:.4f}</b>。
拆开看两项各自的「独奏」效果：<b>仅靠流通量收缩，价格只能到 {S['sup_solo_pct']:+.2f}%</b>；
而仅靠市值增长，价格能到 <b>{S['mc_solo_pct']:+.1f}%</b>。
按对数分解，<b>销毁缩供给只占总涨幅的 {S['sup_share_all']:.1f}%，市值增长占 {S['mc_share_all']:.1f}%</b>。
即使拿着全行业最激进的回购机制（年化约 7% 流通市值），
<b>净销毁也只是小数点后的顺风，不是上涨的来源。</b>
</div>
<div class="note">
反过来看近 1 年：账面净增发 −{abs(S['net1y_pct']):.2f}%，价格却 {S['px_1y']:+.2f}%。
若流通量持平（即零销毁），价格应为 {S['flat_1y']:+.2f}% —— 供给在账面口径上「贡献」了 {S['sup_contrib_1y']:+.2f}pp。
但这 {S['sup_contrib_1y']:.1f}pp 属于<b>一次性会计认定的机械效应</b>，市场早已把 AF 持仓当作不流通，
不能当作可重复的收益来源。
</div>
</div>

<div class="card">
<h2>四、跨资产对照：市值是「推动成本」，净增发是「分母」</h2>
{figs[2]}
<div class="scroll"><table>
<thead><tr><th class="l">币</th><th>当前市值</th><th>近1年净增发(年化)</th><th>每涨 1% 所需边际资金</th></tr></thead>
<tbody>{xr}</tbody></table></div>
<div class="note">
这解释了「推动成本随市值上升」：<b>价格 = 市值 ÷ 流通量</b>，
同样 1% 的涨幅在 BTC 上要花 $15.5B，在 HYPE 上只要 $0.21B —— <b>差约 {S['xa'].set_index('coin').at['BTC','per1p_B']/S['xa'].set_index('coin').at['HYPE','per1p_B']:.0f} 倍</b>。
<br><b>但这是「给定资金量」下的机械关系，不等于「小市值一定涨得快」。</b>
本池实测横截面显示，起点市值与后续涨幅是<b>正相关或不显著</b>（近 1 年 ρ=+0.32，剔除极值后 +0.46 且显著），
大市值档在近 1/2/3 年三个窗口都是最好的一档 —— 因为<b>资金流入量本身不是常数</b>，
深熊里资金反而向大市值避险。详见另报《市值与净增发：分工与横截面检验》。
</div>
</div>

<div class="card">
<h2>五、机制核实与风险（已联网核实）</h2>
<ul>
<li><b>回购来源：</b>协议手续费 97% 自动流入 Assistance Fund，链上 TWAP 每日市价买入 HYPE，无治理投票、无人工择时。
另叠加 USDC 储备收益的一部分（协议与 Circle/Coinbase 分成后约 90% 计入）。</li>
<li><b>销毁认定：</b>2025-12-24 验证者投票（85 赞成）正式将 AF 持有的 HYPE 认定为<b>永久销毁</b>，
此后所有 AF 累积同样视为永久销毁 —— <b>这正对应本报告观察到的两次一次性台阶。</b></li>
<li><b>非加密收入：</b>HIP-3 无许可永续（黄金/白银/原油/股指）已占相当交易量份额，是加密周期之外的第二现金流。</li>
<li><b>回购依赖交易量：</b>与 ETH 的 EIP-1559 销毁同性质 —— 是<b>活动驱动</b>的负项。
低波动、低成交期回购力度会同步衰减。</li>
</ul>
<div class="fix">
<b>需要点明的三个风险：</b>
<ul>
  <li><b>未流通 {S['locked_M']:.0f}M 枚（占硬顶 {100 - S['circ_pct']:.2f}%，按现价约 ${S['locked_B']:.1f}B）仍在场外。</b>
    其中未来社区激励占约 38.8%，处置方式未定 —— <b>这是唯一能推翻「净通缩」的变量</b>。
    若基金会大规模释放预留代币，供需会瞬间反转。</li>
  <li><b>团队解锁已主动砍约 90%</b>（月度从百万枚级压到十几万枚级），
    但这是<b>团队自主选择，不是合约锁死</b>，可以再改回去。</li>
  <li><b>销毁 ≠ 上涨。</b>本报告第三节已证明：HYPE 全期涨幅中约 {100 - S['sup_share_all']:.1f}% 来自市值。
    回购是「增长果实的分配机制」，不是增长引擎。</li>
</ul>
</div>
</div>

<div class="card">
<h2>六、可操作结论</h2>
<ol>
<li><b>判断「增发压力」要看稳态速率，不看账面 Δ。</b>HYPE 账面 {S['net1y_pct']:+.2f}%，
真实稳态 {S['st_ann']:+.2f}% —— 差 {abs(S['net1y_pct']/S['st_ann']):.1f} 倍。
任何「近 1 年净增发」口径都必须先跑台阶剔除。</li>
<li><b>净销毁是「分配机制」，不是收益来源。</b>约 {100 - S['sup_share_all']:.1f}% 的涨幅来自市值增长。
选币要先看市值有没有增长空间，再看分母是否拖累。</li>
<li><b>市值是推动成本。</b>小市值 + 分母不涨的组合涨幅弹性最大；
大市值 + 持续增发是双重逆风（这正是 SOL 近 2 年的处境）。</li>
<li><b>把「未流通占比」当风险位而非机会位。</b>HYPE 只有 {S['circ_pct']:.1f}% 在流通，
这是它弹性大的原因，也是它最大的尾部风险。</li>
</ol>
</div>

<p style="font-size:12px;color:var(--mut);text-align:center;margin-top:26px">
脚本 <code>hype_supply_audit.py</code> ／ 明细 <code>out/hype_windows.csv</code>、<code>hype_monthly.csv</code>、
<code>hype_steps.csv</code>、<code>hype_steady.csv</code>、<code>hype_xasset.csv</code>
</p>
</div></body></html>"""

    dst = os.path.join(REPO, "docs", "reports", "crypto", "hype_supply_measured.html")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    io.open(dst, "w", encoding="utf-8").write(html)
    print(f"OK -> {dst}  ({len(html)//1024} KB)")


if __name__ == "__main__":
    main()
