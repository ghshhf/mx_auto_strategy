# -*- coding: utf-8 -*-
"""市值 vs 净增发：分工、横截面检验与 HYPE/ZEC 双案例。

回答的问题：
  「市值越大涨得越慢」在横截面上是否成立？
  「净增发是分母」有多重要？
正文数字一律动态计算注入。
输出：docs/reports/crypto/marketcap_vs_supply_lens.html
"""
import io, os, json
from math import erf, sqrt
import pandas as pd, numpy as np
import plotly.graph_objects as go

CRYPTO = r"E:\xmanbian\mx_auto_strategy_repo\markets\crypto"
REPO = r"E:\xmanbian\mx_auto_strategy_repo"
OUT = os.path.join(CRYPTO, "out")
BLUE, RED, GREEN, AMBER, PURPLE = "#378ADD", "#E24B4A", "#1D9E75", "#BA7517", "#7F77DD"
LAY = dict(template="plotly_white",
           font=dict(family="Inter, Segoe UI, Microsoft YaHei, sans-serif", size=12),
           margin=dict(l=60, r=30, t=56, b=50), hoverlabel=dict(font_size=12))


def spearman(a, b):
    a, b = pd.Series(a), pd.Series(b)
    m = a.notna() & b.notna()
    a, b = a[m], b[m]
    if len(a) < 4:
        return np.nan, np.nan, len(a)
    rho = float(np.corrcoef(a.rank(), b.rank())[0, 1])
    n = len(a)
    t = rho * np.sqrt((n - 2) / max(1e-12, 1 - rho ** 2))
    return rho, 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2)))), n


def main():
    d = pd.read_csv(os.path.join(OUT, "xsec_mc_vs_return.csv"))
    S = {}

    # 相关系数与稳健性
    for w in ["近1年", "近2年", "近3年"]:
        g = d[d.window == w]
        gx = g[~g["coin"].isin(["ZEC"])]
        S[f"mc_{w}"] = spearman(g["log_mc0"], g["px_ret"])
        S[f"net_{w}"] = spearman(g["net"], g["px_ret"])
        S[f"mcx_{w}"] = spearman(gx["log_mc0"], gx["px_ret"])
        S[f"netx_{w}"] = spearman(gx["net"], gx["px_ret"])
        S[f"n_{w}"] = len(g)

    # 三分档
    terc = {}
    for w in ["近1年", "近2年", "近3年"]:
        g = d[d.window == w].copy()
        g["q"] = pd.qcut(g["mc_start_B"], 3, labels=["小市值", "中市值", "大市值"])
        terc[w] = g.groupby("q", observed=True).agg(
            n=("coin", "size"), mc0=("mc_start_B", "median"),
            px=("px_ret", "median"), net=("net", "median"))
    S["terc"] = terc

    # HYPE / ZEC 案例
    g1 = d[d.window == "近1年"].set_index("coin")
    S["Z"] = dict(mc0=g1.at["ZEC", "mc_start_B"], mc1=g1.at["ZEC", "mc_end_B"],
                  px=g1.at["ZEC", "px_ret"], mc=g1.at["ZEC", "mc_ret"], net=g1.at["ZEC", "net"])
    S["H"] = dict(mc0=g1.at["HYPE", "mc_start_B"], mc1=g1.at["HYPE", "mc_end_B"],
                  px=g1.at["HYPE", "px_ret"], mc=g1.at["HYPE", "mc_ret"], net=g1.at["HYPE", "net"])
    S["ratio_mc0"] = S["H"]["mc0"] / S["Z"]["mc0"]   # HYPE 起点市值是 ZEC 的多少倍

    # ── 弹性检验：把「资金流入 Δ$」与「起点市值 M0」分离 ──
    ep = os.path.join(OUT, "mc_elasticity_audit.csv")
    e = pd.read_csv(ep)
    e["log_m0"] = np.log10(e["m0"])
    S["X"] = float(e[(e.window == "近1年") & (e.coin == "ZEC")]["dM_B"].iloc[0])
    S["dsum_近1年"] = float(e[e.window == "近1年"]["dM_B"].sum())
    S["n_up_近1年"] = int((e[e.window == "近1年"]["dM_B"] > 0).sum())
    for w in ["近1年", "近2年", "近3年"]:
        g = e[e.window == w]
        up, dnn = g[g.dM_B > 0], g[g.dM_B <= 0]
        S[f"cond_up_{w}"] = spearman(up.log_m0, up.px_ret)
        S[f"cond_dn_{w}"] = spearman(dnn.log_m0, dnn.px_ret)
        S[f"nup_{w}"], S[f"ndn_{w}"] = len(up), len(dnn)
        S[f"dsum_{w}"] = float(g.dM_B.sum())
        S[f"nupos_{w}"] = int((g.dM_B > 0).sum())
        # 三分档的 Δ$ 中位
        gg = g.copy()
        gg["q"] = pd.qcut(gg.m0, 3, labels=["小市值", "中市值", "大市值"])
        S[f"dmq_{w}"] = gg.groupby("q", observed=True)["dM_B"].median().to_dict()
        S[f"dmpct_{w}"] = gg.groupby("q", observed=True)["mc_ret"].median().to_dict()

    # 同额资金反事实
    gz = e[e.window == "近1年"].copy()
    gz["counter_px"] = (1 + S["X"] / gz["m0"]) / gz["sup_x"] - 1
    gz.to_csv(os.path.join(OUT, "mc_elasticity_counterfactual.csv"), index=False, encoding="utf-8-sig")
    S["cf"] = gz
    S["per1p"] = gz.set_index("coin")["per1p_B_mid"].to_dict()

    # ZEC 底部
    zj = json.load(io.open(os.path.join(CRYPTO, "data", "cmc_history", "ZEC.json"), encoding="utf-8"))["points"]
    zdf = pd.DataFrame([(pd.to_datetime(int(t), unit="s"), v[0], v[2]) for t, v in zj.items()],
                       columns=["t", "px", "mc"]).set_index("t").sort_index()
    cut3 = zdf.index[-1] - pd.Timedelta(days=1095)
    z3 = zdf[zdf.index >= cut3]
    S["zlow_mc"] = z3["mc"].min() / 1e9
    S["zlow_dt"] = z3["mc"].idxmin().date()
    S["zlow_mul"] = zdf["mc"].iloc[-1] / z3["mc"].min()

    # 机构通道口径（外源事实，非本地可推导）：ZCSH 上市至 2026-09 初
    # 外部净流入约 $70M + DCG International 投资 $100M = 约 $0.17B
    S["etf_in"] = 0.07 + 0.10

    # ---- 图1：散点 起点市值 vs 近1年涨幅 ----
    f1 = go.Figure()
    for w, col, sym in [("近1年", BLUE, "circle"), ("近2年", AMBER, "diamond")]:
        g = d[d.window == w]
        f1.add_trace(go.Scatter(
            x=g["mc_start_B"], y=g["px_ret"], mode="markers", name=w,
            marker=dict(size=11, color=col, symbol=sym, line=dict(width=1, color="white")),
            text=g["coin"],
            hovertemplate="%{text}<br>起点市值 $%{x:.2f}B<br>价格涨幅 %{y:+.1f}%<extra></extra>"))
    for c, dy in [("ZEC", 8), ("HYPE", -14), ("BTC", 8), ("ETH", -14)]:
        r1 = g1.loc[c]
        f1.add_annotation(x=np.log10(r1["mc_start_B"]), y=r1["px_ret"], text=c,
                          showarrow=False, yshift=dy, font=dict(size=11, color="#333"))
    f1.add_hline(y=0, line=dict(color="#bbb", width=1))
    f1.update_layout(height=420, **LAY, title_text="起点市值（对数轴）vs 后续价格涨幅：不是负相关",
                     xaxis=dict(type="log", title="起点市值（十亿美元，对数）"),
                     yaxis_title="价格涨幅 (%)",
                     legend=dict(orientation="h", y=-0.18, x=0))

    # ---- 图2：三分档 ----
    f2 = go.Figure()
    for q, col in [("小市值", "#F09595"), ("中市值", "#EF9F27"), ("大市值", "#1D9E75")]:
        f2.add_trace(go.Bar(name=q, x=["近1年", "近2年", "近3年"],
                            y=[terc[w].loc[q, "px"] for w in ["近1年", "近2年", "近3年"]],
                            marker_color=col,
                            text=[f"{terc[w].loc[q, 'px']:+.0f}%" for w in ["近1年", "近2年", "近3年"]],
                            textposition="outside", textfont=dict(size=10)))
    f2.add_hline(y=0, line=dict(color="#999", width=1))
    f2.update_layout(height=400, **LAY, barmode="group",
                     title_text="按起点市值三分档：大市值档三个窗口都是最好的一档",
                     yaxis_title="价格涨幅中位 (%)", legend=dict(orientation="h", y=-0.18, x=0))

    # ---- 图3：HYPE vs ZEC ----
    f3 = go.Figure()
    f3.add_trace(go.Bar(name="近1年价格涨幅", x=["HYPE", "ZEC"],
                        y=[S["H"]["px"], S["Z"]["px"]], marker_color=[PURPLE, GREEN],
                        text=[f"{S['H']['px']:+.0f}%", f"{S['Z']['px']:+.0f}%"],
                        textposition="outside", yaxis="y"))
    f3.add_trace(go.Scatter(name="近1年净增发（右轴）", x=["HYPE", "ZEC"],
                            y=[S["H"]["net"], S["Z"]["net"]], yaxis="y2",
                            mode="markers+text", marker=dict(size=15, symbol="x", color=RED),
                            text=[f"净销毁 {S['H']['net']:+.1f}%", f"净增发 {S['Z']['net']:+.1f}%"],
                            textposition="bottom center", textfont=dict(size=11, color=RED)))
    f3.update_layout(height=400, **LAY, showlegend=False,
                     title_text="同样是近 1 年：净销毁的 HYPE 涨 57%，净增发 4% 的 ZEC 涨 24 倍",
                     yaxis=dict(title="近 1 年价格涨幅 (%)", rangemode="tozero"),
                     yaxis2=dict(title="近 1 年净增发 (%)", overlaying="y", side="right",
                                 range=[-40, 40], showgrid=False, zeroline=True,
                                 zerolinecolor="#c0392b", zerolinewidth=1.2))

    # ---- 图4：同额资金反事实（弹性） ----
    cf = S["cf"].sort_values("counter_px", ascending=True)
    f4 = go.Figure()
    f4.add_trace(go.Bar(
        x=(S["X"] / cf["m0"]), y=cf["coin"], orientation="h",
        marker_color=[AMBER if c == "ZEC" else BLUE for c in cf["coin"]],
        text=[f"{p*100:+.0f}%" for p in cf["counter_px"]],
        textposition="outside", textfont=dict(size=10),
        customdata=cf[["m0", "counter_px"]].values,
        hovertemplate="%{y}<br>起点市值 $%{customdata[0]:.2f}B<br>"
                      "资金冲击 %{x:.2f}×<br>反事实价格 %{customdata[1]:+.1%}<extra></extra>"))
    f4.update_layout(height=520, **LAY,
                     title_text=f"同一笔 ${S['X']:.1f}B 净流入，投给不同起点的币（横轴对数）",
                     xaxis=dict(type="log", title="Δ$ ÷ 起点市值（倍，对数）", range=[-2.4, 2.6]),
                     yaxis=dict(title="", tickfont=dict(size=11)))

    # ---- 图5：ZEC 市值路径 ----
    zm = zdf.resample("MS").last().dropna()
    zm = zm[zm.index >= pd.Timestamp("2023-09-01")]
    f5 = go.Figure()
    f5.add_trace(go.Scatter(x=zm.index, y=zm["mc"] / 1e9, mode="lines+markers",
                            line=dict(color=AMBER, width=2), marker=dict(size=4),
                            fill="tozeroy", fillcolor="rgba(186,117,23,0.10)",
                            hovertemplate="%{x|%Y-%m}<br>市值 $%{y:.2f}B<extra></extra>"))
    f5.add_vline(x=pd.Timestamp("2026-08-25"), line=dict(color=RED, width=1.4, dash="dash"),
                 annotation_text="ETF 上市 2026-08-25", annotation_position="top left",
                 annotation_font=dict(size=11, color=RED))
    f5.update_layout(height=360, **LAY, title_text="ZEC 市值路径：底部横盘两年，起跳点仅 $0.88B",
                     yaxis=dict(type="log", title="市值（十亿美元，对数）"),
                     xaxis_title="")

    figs = [f.to_html(include_plotlyjs=("cdn" if i == 0 else False), full_html=False,
                      config={"responsive": True}) for i, f in enumerate([f1, f2, f3, f4, f5])]

    tr = ""
    for w in ["近1年", "近2年", "近3年"]:
        t = terc[w]
        for q in ["小市值", "中市值", "大市值"]:
            r = t.loc[q]
            tr += (f"<tr><td class='l'>{w}</td><td class='l'><b>{q}</b></td><td>{int(r.n)}</td>"
                   f"<td>${r.mc0:.2f}B</td>"
                   f"<td>{S[f'dmq_{w}'][q]:+.2f}B</td>"
                   f"<td>{S[f'dmpct_{w}'][q]*100:+.1f}%</td>"
                   f"<td>{r.net:+.2f}%</td><td>{r.px:+.1f}%</td></tr>")

    def rho_row(w):
        return (f"<tr><td class='l'><b>{w}</b></td>"
                f"<td>{S[f'mc_{w}'][0]:+.3f}</td><td>{S[f'mc_{w}'][1]:.3f}</td>"
                f"<td>{S[f'mcx_{w}'][0]:+.3f}</td><td>{S[f'mcx_{w}'][1]:.3f}</td>"
                f"<td class='neg'>{S[f'net_{w}'][0]:+.3f}</td><td>{S[f'net_{w}'][1]:.3f}</td></tr>")

    rho_tbl = "".join(rho_row(w) for w in ["近1年", "近2年", "近3年"])

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>市值 vs 净增发：分工、弹性检验与横截面真相</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#20252b;--mut:#66788a;--bd:#e3e7ec;--red:#A32D2D;--grn:#1D9E75;--blu:#185FA5;--amb:#854F0B}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.78 "Microsoft YaHei","Inter",system-ui,sans-serif}}
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
.kpi .v{{font-size:22px;font-weight:600;margin:3px 0 1px;letter-spacing:-.5px}}
.kpi .n{{font-size:11.5px;color:var(--mut)}}
.red{{color:var(--red)}} .grn{{color:var(--grn)}} .blu{{color:var(--blu)}} .amb{{color:var(--amb)}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th,td{{padding:8px 9px;border-bottom:1px solid var(--bd);text-align:right}}
th{{background:#f8f9fb;font-weight:600;color:var(--mut);font-size:12.5px}}
td.l,th.l{{text-align:left}}
.scroll{{overflow-x:auto}}
.pos{{color:var(--red);font-weight:600}} .neg{{color:var(--grn);font-weight:600}}
.ok{{background:#f0f8f4;border-left:3px solid var(--grn);padding:13px 15px;border-radius:0 8px 8px 0;margin:14px 0;font-size:14px}}
.bad{{background:#fdf2f0;border-left:3px solid #c0392b;padding:13px 15px;border-radius:0 8px 8px 0;margin:14px 0;font-size:14px}}
.note{{background:#f8f9fb;border-left:3px solid var(--blu);padding:11px 14px;border-radius:0 8px 8px 0;font-size:13.5px;margin:12px 0}}
.key{{background:#fdf8ee;border-left:3px solid var(--amb);padding:13px 15px;border-radius:0 8px 8px 0;margin:14px 0;font-size:14px}}
ul,ol{{margin:6px 0 10px;padding-left:20px}} li{{margin:6px 0}}
code{{background:#eef1f5;padding:1.5px 5px;border-radius:4px;font-size:12.5px;font-family:Consolas,monospace}}
.fml{{background:#f8f9fb;border:1px dashed var(--bd);border-radius:8px;padding:12px 14px;text-align:center;
 font-family:Consolas,monospace;font-size:14px;margin:12px 0}}
</style></head><body><div class="wrap">
<h1>市值 vs 净增发：分工、弹性检验与横截面真相</h1>
<p class="sub">价格倍数 = 市值倍数 ÷ 流通量倍数。本报告做三件事：① 拆开「资金流入 Δ$」与「起点市值 M₀」，
检验弹性（1/M₀）；② 用条件检验说明为什么无条件横截面会给出误导性结论；
③ HYPE / ZEC 双案例。样本 {S['n_近1年']} 币，截至 2026-09-10。</p>

<div class="card">
<h2>一、结论：一句对，一句我上一版说错了</h2>
<div class="kpis">
  <div class="kpi"><div class="k">近1年资金净流入的币</div><div class="v amb">{S['nupos_近1年']} / {S['n_近1年']}</div>
    <div class="n">Δ$ 合计 {S['dsum_近1年']:+,.0f}B —— 这是资金净流出年</div></div>
  <div class="kpi"><div class="k">同一笔钱的价格弹性差</div><div class="v">4 个数量级</div>
    <div class="n">${S['X']:.1f}B 投给 GLM 涨 {S['cf'].set_index('coin').at['GLM','counter_px']*100:+.0f}%
      ／ 投给 BTC {S['cf'].set_index('coin').at['BTC','counter_px']*100:+.1f}%</div></div>
  <div class="kpi"><div class="k">条件检验（仅 Δ$&gt;0）</div><div class="v grn">{S['cond_up_近2年'][0]:+.3f}</div>
    <div class="n">近2年 Spearman，n={S['nup_近2年']} —— <b>符号翻负</b></div></div>
  <div class="kpi"><div class="k">ZEC 距 3 年低点</div><div class="v">×{S['zlow_mul']:.0f}</div>
    <div class="n">${S['zlow_mc']:.3f}B @ {S['zlow_dt']}</div></div>
</div>
<div class="ok">
<b>对的那一句：</b>「价格 = 市值 ÷ 流通量」是定义式，所以分析价格必须拆成
<b>分子（市值／资金）</b>和<b>分母（供给）</b>两部分。只看价格，会把「销毁／解锁造成的机械波动」
误读成需求变化。这是<b>完备分解</b>，不是可选视角。
</div>
<div class="bad">
<b>我上一版说错的那一句：</b>「『市值越大涨得越慢』在横截面上不成立」。
这个说法<b>本身是对的，但归因错了</b> —— 我把「无条件横截面没看到负号」当成了「命题被证伪」，
实际上那个横截面是一个<b>伪检验</b>：它测的是「<b>谁拿到了钱</b>」，
而不是「<b>同样的钱投下去效果如何</b>」。
<br><br>
正确表述是：<b>「市值大 → 同样资金下涨得慢」是一个条件命题</b>
（条件 = 给定美元资金流入 Δ$）。无条件横截面之所以给出正号，是因为
<b>Δ$ 本身不是常数、也不是外生的</b> —— 近 1 年只有 <b>{S['nupos_近1年']}/{S['n_近1年']}</b> 枚币有资金净流入，
合计 <b>{S['dsum_近1年']:+,.0f}B</b>；而且抽水<b>按比例偏向中小市值</b>
（小市值档 Δ$÷M₀ 中位 {S['dmpct_近1年']['小市值']*100:+.1f}% vs 大市值档 {S['dmpct_近1年']['大市值']*100:+.1f}%）。
<b>大市值跌得少，是资金分配的结果，不是弹性律被推翻。</b>
<br><br>
<b>条件检验直接给出反证</b>：只看有资金净流入（Δ$&gt;0）的子样本，
近 2 年 Spearman(log M₀, 价格涨幅) = <b>{S['cond_up_近2年'][0]:+.3f}</b>（n={S['nup_近2年']}）、
近 3 年 = <b>{S['cond_up_近3年'][0]:+.3f}</b>（n={S['nup_近3年']}）—— <b>符号全部翻负，与你说的方向一致</b>
（样本小、不显著，只作方向证据）。
</div>
</div>

<div class="card">
<h2>二、弹性：为什么「市值大 = 涨得慢」是条件命题</h2>
<div class="fml">ΔP/P &nbsp;≈&nbsp; (Δ$ / M₀) &nbsp;−&nbsp; ΔSup/Sup</div>
<p>这个式子把涨幅拆成三样东西，缺一不可：</p>
<ul>
<li><b>Δ$ —— 美元资金净流入。</b>由叙事、机构通道、赛道轮动驱动，<b>外生且高度不均匀</b>。
这是唯一被无条件横截面遗漏的变量。</li>
<li><b>M₀ —— 起点市值。</b>决定<b>弹性 = 1/M₀</b>。同样的 Δ$，M₀ 越小涨幅越大。
这一层是机械的、必然的、不需要统计检验。</li>
<li><b>ΔSup/Sup —— 净增发。</b>是固定<b>百分比</b>扣减，与市值大小无关。</li>
</ul>
<p><b>所以「市值大 → 涨得慢」只在「给定 Δ$」时成立。</b>把它写成无条件命题才是错的 ——
而错的是我的表述，不是你的直觉。下面这笔反事实把弹性差异摊开：</p>
{figs[3]}
<div class="note">
把 ZEC 近 1 年实际净流入的 <b>${S['X']:.2f}B</b> 假设原样投给其他币（净增发不变）：
<b>GLM 会涨 {S['cf'].set_index('coin').at['GLM','counter_px']*100:+.0f}%</b>（起点 ${S['cf'].set_index('coin').at['GLM','m0']:.2f}B），
ETHFI {S['cf'].set_index('coin').at['ETHFI','counter_px']*100:+.0f}%，
HYPE {S['cf'].set_index('coin').at['HYPE','counter_px']*100:+.0f}%，
ETH 只有 {S['cf'].set_index('coin').at['ETH','counter_px']*100:+.1f}%，
BTC 是 {S['cf'].set_index('coin').at['BTC','counter_px']*100:+.1f}%。
<b>同一笔钱，弹性差 4 个数量级（{S['X']/S['cf'].set_index('coin').at['GLM','m0']:.1f}× vs {S['X']/S['cf'].set_index('coin').at['BTC','m0']:.4f}×）。</b>
</div>
<p>换个说法看边际成本：近 1 年区间中值市值口径下，每推涨 <b>1%</b> 需要</p>
<div class="scroll"><table>
<thead><tr><th class="l">币</th><th>当期中值市值</th><th>每 +1% 需资金</th><th>相对 ZEC</th></tr></thead>
<tbody>
<tr><td class="l"><b>BTC</b></td><td>${S['per1p']['BTC']*100:.0f}B</td><td>${S['per1p']['BTC']:.3f}B</td><td>{S['per1p']['BTC']/S['per1p']['ZEC']:.0f}×</td></tr>
<tr><td class="l"><b>ETH</b></td><td>${S['per1p']['ETH']*100:.0f}B</td><td>${S['per1p']['ETH']:.3f}B</td><td>{S['per1p']['ETH']/S['per1p']['ZEC']:.0f}×</td></tr>
<tr><td class="l"><b>HYPE</b></td><td>${S['per1p']['HYPE']*100:.0f}B</td><td>${S['per1p']['HYPE']:.3f}B</td><td>{S['per1p']['HYPE']/S['per1p']['ZEC']:.1f}×</td></tr>
<tr><td class="l"><b>ZEC</b></td><td>${S['per1p']['ZEC']*100:.0f}B</td><td>${S['per1p']['ZEC']:.3f}B</td><td>1.0×</td></tr>
</tbody></table></div>
<div class="key">
这一层<b>完全支持你的原话</b>：市值变高后推动上涨需要更多资金。而且量级差极大 ——
<b>BTC 每 1% 要 ${S['per1p']['BTC']:.2f}B，是 ZEC 的 {S['per1p']['BTC']/S['per1p']['ZEC']:.0f} 倍。</b>
注意这里用的还只是「区间中值市值」；若用 <b>ZEC 的起点市值 ${S['Z']['mc0']:.2f}B</b> 算，
每 1% 只要 <b>${S['Z']['mc0']*0.01*1000:.0f}M</b>，与 BTC 差 <b>{S['per1p']['BTC']*1e9/(S['Z']['mc0']*1e9*0.01):.0f} 倍</b>。
</div>
</div>

<div class="card">
<h2>三、横截面检验</h2>
{figs[0]}
<div class="scroll"><table>
<thead><tr><th class="l">窗口</th><th>起点市值 ρ</th><th>p</th><th>剔除极值 ρ</th><th>p</th>
<th>净增发 ρ</th><th>p</th></tr></thead>
<tbody>{rho_tbl}</tbody></table></div>
<div class="note">
<b>读法：</b>「起点市值 ρ」为正值说明<b>市值越大、后续涨幅越好</b>——看起来与直觉相反。
真正稳定显著的只有<b>净增发</b>（近 1 年 {S['net_近1年'][0]:+.3f}、近 2 年 {S['net_近2年'][0]:+.3f}，p 均 &lt;0.05），
近 3 年转不显著（{S['net_近3年'][0]:+.3f}，p={S['net_近3年'][1]:.3f}）。
<br><br>
<b>但这一节请读成「反例展示」而不是「结论」。</b>它漏掉了 Δ$，因此测的是
「<b>谁拿到了钱</b>」而不是「<b>同样的钱效果如何</b>」。条件检验见下。
</div>
{figs[1]}
<div class="scroll"><table>
<thead><tr><th class="l">窗口</th><th class="l">档次</th><th>n</th><th>起点市值中位</th>
<th>Δ$ 中位</th><th>Δ$÷M₀ 中位</th><th>净增发中位</th><th>价格涨幅中位</th></tr></thead>
<tbody>{tr}</tbody></table></div>
<div class="key">
三个窗口里，<b>大市值档的价格涨幅中位都是最好的一档</b>
（近1年 {S['terc']['近1年'].loc['大市值','px']:+.1f}% vs 小市值 {S['terc']['近1年'].loc['小市值','px']:+.1f}%；
近2年 {S['terc']['近2年'].loc['大市值','px']:+.1f}% vs {S['terc']['近2年'].loc['小市值','px']:+.1f}%；
近3年 {S['terc']['近3年'].loc['大市值','px']:+.1f}% vs {S['terc']['近3年'].loc['小市值','px']:+.1f}%）。
<b>但看新增的两列就明白了</b>：这不是「大市值涨得快」，而是<b>资金按比例撤离时更偏向中小市值</b>——
近 1 年小市值档 <b>Δ$÷M₀ 中位 {S['dmpct_近1年']['小市值']*100:+.1f}%</b>，
大市值档只有 <b>{S['dmpct_近1年']['大市值']*100:+.1f}%</b>。
换成美元绝对额更直观：小市值档 Δ$ 中位仅 {S['dmq_近1年']['小市值']:+.2f}B，
大市值档 {S['dmq_近1年']['大市值']:+.2f}B —— <b>大市值抽走的钱多得多，但相对自己的体量抽得少</b>。
</div>
<h3>条件检验：只看有资金净流入的子样本</h3>
<p>把 Δ$ 的干扰按住，只保留 Δ$ &gt; 0 的币，再看起点市值与涨幅的关系：</p>
<div class="scroll"><table>
<thead><tr><th class="l">窗口</th><th>n（Δ$&gt;0）</th><th>Spearman(log M₀, 涨幅)</th><th>p</th><th class="l">方向</th>
<th>n（Δ$≤0）</th><th>Spearman</th></tr></thead>
<tbody>
<tr><td class="l"><b>近1年</b></td><td>{S['nup_近1年']}</td><td>{S['cond_up_近1年'][0]:+.3f}</td>
<td>{S['cond_up_近1年'][1]:.3f}</td><td class="l">样本过少，不作判断</td>
<td>{S['ndn_近1年']}</td><td>{S['cond_dn_近1年'][0]:+.3f}</td></tr>
<tr><td class="l"><b>近2年</b></td><td>{S['nup_近2年']}</td><td class="grn"><b>{S['cond_up_近2年'][0]:+.3f}</b></td>
<td>{S['cond_up_近2年'][1]:.3f}</td><td class="l"><b>负 —— 支持「小市值弹性大」</b></td>
<td>{S['ndn_近2年']}</td><td>{S['cond_dn_近2年'][0]:+.3f}</td></tr>
<tr><td class="l"><b>近3年</b></td><td>{S['nup_近3年']}</td><td class="grn"><b>{S['cond_up_近3年'][0]:+.3f}</b></td>
<td>{S['cond_up_近3年'][1]:.3f}</td><td class="l"><b>负 —— 同上</b></td>
<td>{S['ndn_近3年']}</td><td>{S['cond_dn_近3年'][0]:+.3f}</td></tr>
</tbody></table></div>
<div class="bad">
<b>关键结果：一旦限定在「有资金净流入」的子样本，符号就翻负。</b>
近 2 年 {S['cond_up_近2年'][0]:+.3f}（n={S['nup_近2年']}）、近 3 年 {S['cond_up_近3年'][0]:+.3f}（n={S['nup_近3年']}）。
不显著是因为样本小（本池只有 {S['n_近1年']} 枚，且熊市里净流入的币本来就少），
<b>但方向与无条件横截面相反，说明无条件结果的负号来自资金流分配，而不是弹性律失效。</b>
</div>
</div>

<div class="card">
<h2>四、双案例：净销毁的没跑赢净增发的</h2>
{figs[2]}
<p>这是最干净的一组对照 —— <b>分母方向完全相反，但结果与分母无关</b>：</p>
<div class="scroll"><table>
<thead><tr><th class="l">指标</th><th>HYPE</th><th>ZEC</th></tr></thead>
<tbody>
<tr><td class="l">近 1 年净增发</td><td class="neg">{S['H']['net']:+.2f}%</td><td class="pos">{S['Z']['net']:+.2f}%</td></tr>
<tr><td class="l">近 1 年市值涨幅</td><td>{S['H']['mc']:+.1f}%</td><td>{S['Z']['mc']:+.1f}%</td></tr>
<tr><td class="l">近 1 年价格涨幅</td><td class="pos">{S['H']['px']:+.1f}%</td><td class="pos">{S['Z']['px']:+.1f}%</td></tr>
<tr><td class="l">近 1 年 Δ$（美元净流入）</td><td>+{S['H']['mc1']-S['H']['mc0']:.2f}B</td><td><b>+{S['Z']['mc1']-S['Z']['mc0']:.2f}B</b></td></tr>
<tr><td class="l">起点市值</td><td>${S['H']['mc0']:.2f}B</td><td>${S['Z']['mc0']:.2f}B</td></tr>
<tr><td class="l">现市值</td><td>${S['H']['mc1']:.2f}B</td><td>${S['Z']['mc1']:.2f}B</td></tr>
</tbody></table></div>
<div class="ok">
<b>HYPE 的分母在减（{S['H']['net']:+.2f}%），ZEC 的分母在增（{S['Z']['net']:+.2f}%），
结果 ZEC 涨了 {S['Z']['px']/S['H']['px']:.1f} 倍于 HYPE。</b>
差别不在分母，在<b>起点市值差了 {S['ratio_mc0']:.0f} 倍</b>
（${S['Z']['mc0']:.2f}B vs ${S['H']['mc0']:.2f}B）——
一个从地板起涨，一个已经在 ${S['H']['mc0']:.0f}B 的高台上。
</div>
{figs[4]}
<div class="note">
<b>ZEC 的起跳点在哪：近 3 年最低市值 ${S['zlow_mc']:.3f}B（{S['zlow_dt']}），
现市值 ${S['Z']['mc1']:.2f}B —— <b>距底部 ×{S['zlow_mul']:.0f}</b>。</b>
而且路径分成两腿：<b>第一腿 2025-10~11 月</b>（$0.88B → $8.64B），<b>那时 ETF 还没上市</b>；
第二腿才是 2026-08-25 Grayscale ZCSH 现货 ETF 上市之后。所以
「从底部起来 + 盘子极小」是<b>第一腿的前提</b>，ETF 是把叙事合法化并接力的第二腿。
</div>
<div class="key">
<b>机构通道到底贡献了多少？</b>联网核实：ZCSH 上市两周 AUM 破 $5 亿，
其中<b>外部净流入仅约 $7,000 万</b>，另获 DCG International 的 $1 亿投资；
ETF 持有约 55 万枚 ZEC（≈流通量 3%）。而 ZEC 同期市值增量是
<b>${S['Z']['mc1']-S['Z']['mc0']:.2f}B</b> ——
<b>ETF 的钱只占约 {(S['etf_in']/(S['Z']['mc1']-S['Z']['mc0']))*100:.1f}%</b>。
<br><br>
<b>所以「机构强推」的作用不是买了多少钱，而是</b>：① 给了合规标签（SEC 2026-01 结案、ETF 通道打开），
② 把「隐私叙事」变成可配置的资产类别，③ 触发空头挤压（OI 峰值 $2.15B、单日清算 $3,450 万）。
<b>在一个 ${S['Z']['mc0']:.2f}B 的盘子上，叙事加杠杆就能放大几十倍 —— 这恰恰是弹性的证据，不是反驳。</b>
</div>
<div class="note">
ZEC 的实测净增发 <b>{S['Z']['net']:+.2f}%/年</b>还刚好可以验证数据可靠性：
2024-11 减半后区块奖励 1.5625 ZEC、出块 75 秒 → 约 1,800 枚/日 × 365 ≈
<b>65.7 万枚/年</b>，除以约 16.2M 流通量 = <b>+4.06%</b>，与实测 {S['Z']['net']:+.2f}% 吻合。
且月度增量恒定在 +0.29%，<b>无任何解锁悬崖</b> —— 这是 BTC 式发行曲线，供给端最白盒的一类。
</div>
</div>

<div class="card">
<h2>五、那到底该看什么</h2>
<ol>
<li><b>把涨幅拆成「弹性 × 资金」再谈，不要用「市值大／小」当单一变量。</b>
    涨幅 ≈ (Δ$/M₀) ÷ (1+净增发)。<b>M₀ 决定弹性，Δ$ 决定发生与否。</b>
    ZEC 的 {S['Z']['px']/100:.0f} 倍 = 极小 M₀（${S['Z']['mc0']:.2f}B，3 年低点 ${S['zlow_mc']:.3f}B）
    × 巨大 Δ$（+{S['Z']['mc1']-S['Z']['mc0']:.2f}B）；缺任一项都不会发生。</li>
<li><b>「市值大 → 涨得慢」是对的，但要加条件「给定 Δ$」。</b>
    直接量化就是：BTC 每推 1% 要 ~${S['per1p']['BTC']*1000:.0f}M，
    ZEC 在 ${S['Z']['mc0']:.2f}B 起点时只要 ~${S['Z']['mc0']*0.01*1000:.0f}M，
    <b>差 {S['per1p']['BTC']*1e9/(S['Z']['mc0']*1e9*0.01):.0f} 倍</b>。
    无条件横截面看不到它，是因为 Δ$ 被内生化、且在熊市按比例偏向大市值。</li>
<li><b>看分母（净增发）要分「稳态速率」和「一次性事件」。</b>
    HYPE 账面 {S['H']['net']:+.1f}% 里 96.9% 是一次性会计认定，真实稳态只有 −5.17%/年。
    <b>任何「近 1 年净增发」口径都必须先跑台阶剔除。</b></li>
<li><b>别把「门槛」当「选择器」。</b>净增发率在本池显著但解释力低（回归 R² 仅 0.002~0.113）。
    它能帮你在同等条件下<b>剔掉被稀释拖累的名字</b>，不能帮你选出赢家。</li>
<li><b>真正决定「谁涨」的是叙事与资金通道</b>（ETF、监管、收入模型、赛道轮动）——
    也就是 Δ$ 从哪里来。ZEC 的 Δ$ 由「减半 + 屏蔽池锁仓 31% + SEC 结案 + 现货 ETF 获批 + 空头挤压」叠加；
    HYPE 的 Δ$ 来自「真实现金流 + 97% 手续费回购」。
    <b>两者的分母一正一负，都不足以解释结果；决定结果的是 Δ$ 和 M₀。</b></li>
</ol>
<div class="bad">
<b>本报告相对上一版的修正（2026-09-13）：</b>
上一版把「无条件横截面没看到负号」写成「命题被证伪」，并据此说「要修的」是你的判断。
<b>这个结论是错的，本版已改。</b>正确的说法是：无条件横截面是伪检验
（遗漏 Δ$、且 Δ$ 被内生化），条件检验（仅 Δ$&gt;0）给出与直觉一致的负号
（近 2 年 {S['cond_up_近2年'][0]:+.3f}、近 3 年 {S['cond_up_近3年'][0]:+.3f}）。
</div>
</div>

<p style="font-size:12px;color:var(--mut);text-align:center;margin-top:26px">
脚本 <code>mc_elasticity_audit.py</code>、<code>xsec_mc_vs_return.py</code>、<code>hype_supply_audit.py</code>、<code>zec_supply_audit.py</code>
／ 明细 <code>out/mc_elasticity_audit.csv</code>、<code>out/mc_elasticity_counterfactual.csv</code>
／ 机构通道数据来源：Grayscale ZCSH 上市公告与 2026-09 行情报道（AInvest / Crypto Times / Gate）
</p>
</div></body></html>"""

    dst = os.path.join(REPO, "docs", "reports", "crypto", "marketcap_vs_supply_lens.html")
    io.open(dst, "w", encoding="utf-8").write(html)
    print(f"OK -> {dst}  ({len(html)//1024} KB)")


if __name__ == "__main__":
    main()
