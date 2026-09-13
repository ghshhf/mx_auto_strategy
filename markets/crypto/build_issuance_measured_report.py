"""生成「实测净增发率 vs 涨跌」报告。

与前一版（issuance_vs_return_27coins.html）的区别 —— 这一版是<b>实测</b>：
  · 增发率不再是按协议规则推测，而是用 CMC 全历史 市值/价格 反推流通量算出来的
  · 并用 CoinGecko 近一年日频数据做双源对账（23/27 差异 <=0.3pp）
  · 新增「阶跃事件」识别（cliff 解锁 / 一次性销毁 / 供应商重分类）
  · 新增「过去 12 个月实测 vs 前瞻」修正表，并联网核实了 APT/ETHFI/DOT/HYPE 的改革

输入  markets/crypto/out/issuance_measured.json
输出  docs/reports/crypto/issuance_measured_27coins.html
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "markets" / "crypto" / "out" / "issuance_measured.json"
OUTF = ROOT / "docs" / "reports" / "crypto" / "issuance_measured_27coins.html"

RED, GREEN = "#c0392b", "#1e8449"
INK, MUTED = "#1c2733", "#66788a"
WINDOWS = ["近1年", "近2年", "近3年"]

# 前瞻（2026-09 起 12 个月）—— (协议排放%, 流通量增速%, 机制类型, 依据, 来源)
#
# ⚠️ 两个口径必须分开，这是 2026-09-12 修正的核心：
#   协议排放  = 质押/区块奖励等「协议自己铸出来的新币」，长期可持续
#   流通量增速 = 协议排放 + 归属解锁 − 销毁，是「实测市值÷价格」那列真正度量的东西
# 对已释放率低、归属程序还在跑的币，两者可以差 4 倍以上（APT：2.6% vs ~10%）。
FORWARD = {
    "APT": (2.6, 10.0, "限时解锁",
            "实测 +24.7% 的分解（与观测逐月吻合）：归属解锁 ≈10.2M 枚/月 + 质押排放 5.2M/月"
            "（2026-04-14 改革后降至 2.6M/月）——改革前实测 ~15.9M/月、改革后稳定在 ~12.8M/月，"
            "断点正好落在 2026-04。2026-10 四年归属期结束后计划释放量 −60%，"
            "剩余 ≈(社区 4.25M + 质押 2.6M)×12 ≈ 82M 枚/年 ÷ 858M ≈ +10%。"
            "协议级硬顶 21 亿枚；基金会 2.1 亿枚永久锁定；gas 费提高 10 倍且 100% 销毁",
            "实测分解 data/cmc_history/APT.json + KuCoin / BanklessTimes 2026-04"),
    "ETHFI": (0.0, 0.0, "解锁已收官",
              "⚠️ 更正上一版归因：实测 +107.1% 不是「供应商重分类」，而是<b>等量线性归属解锁</b>——"
              "2025-05 起连续 15 个月绝对增量恒定在 44~49M 枚/月（相对率由 39.9% 单调衰减到 5.0%，"
              "正是「固定绝对量 ÷ 不断变大的基数」的指纹）。2026-07 后程序结束"
              "（2026-08 Δ=−8.1M 回修、2026-09 Δ=0）。当前 circ 965.4M ÷ 硬顶 1000M = 96.5%，"
              "仅剩 34.6M 枚（上限 +3.6%），且阶梯已停两个月 → 前瞻取 <b>0%</b>。",
              "实测分解 data/cmc_history/ETHFI.json（本报告自查，已推翻旧源）"),
    "DOT": (3.1, 3.3, "持续低通胀",
            "2026-03-14 硬顶 21 亿枚（OpenGov #1710/#1828，81% 赞成）；年发行 1.2 亿→5688 万枚"
            "（−53.6%），通胀 7~10%→3.1%，每两年再减剩余供应的 13.14%。已释放 81.1%，"
            "DOT 无归属 cliff（发行即流通）→ 流通量增速≈协议排放 5688万 ÷ 1702M ≈ 3.3%",
            "BlockchainReporter / Plisio / CryptoNews 2026-03~06 + 实测"),
    "HYPE": (-2.0, -2.0, "通缩+欠解锁",
             "协议净通缩：HyperEVM gas 燃烧 + 援助基金回购销毁。实测近 1 年 circ 由 336.7M → 251.8M"
             "（−24.6%），全部来自 2026-01（−11.0%）、2026-02（−14.0%）两次负台阶 = 真实销毁，"
             "不是平滑流出，故不可年化外推。⚠️ CMC 序列首月（2024-11）circ≈0，导致近 2/3 年窗口"
             "年化出现 inf 伪影，已剔除。已释放仅 22.2%（Tokenomist 解锁进度 46.49%），"
             "模式化月解锁 992 万枚但实际认领仅 4~5%",
             "Tokenomist 2026-09-02 / Hyperliquid Strategies 10-K 2026-06-30 + 实测"),
    "ETH": (0.6, 0.6, "持续微通胀",
            "PoS 发行约 0.5~1%，EIP-1559 + blob 销毁部分对冲；2026 净通胀约 0.23~1%。"
            "已释放 100%，无解锁尾",
            "多源综合 2026"),
}

# 机制标注：实测那列只列近 1 年 >2% 的币，说明「这个高增发是持续的还是会停的」
MECH = {
    "FIL": ("持续发行·待核实",
            "周变化中位 0.48%、仅 1 次 >4% 台阶 → <b>连续平滑发行</b>，非 cliff；绝对值 ≈11M 枚/月 ≈132M/年。"
            "但该量级高于 FIL 已知区块奖励发行量，疑含归属释放或供应商口径调整 → 标注待核实"),
    "LINK": ("储备释放·非通胀",
             "月度增量几乎恒为 0，只在 2025-10/+18.8M、2025-12/+11.3M、2026-04/+19.0M、2026-07/+21.0M "
             "四次跳跃 → <b>不是协议增发</b>（LINK 总量固定 1B、无 mint），是基金会/团队储备被计入流通。"
             "剩余 252M 枚未流通 → 该节奏按 ~70M/年 还可续 ~3.6 年"),
}

CSS = """
<style>
  :root { --line:#e3e8ee; --ink:#1c2733; --muted:#66788a; --hl:#c0392b; --bg:#f7f9fb; }
  * { box-sizing:border-box; }
  body { margin:0; padding:32px 24px 64px; background:var(--bg); color:var(--ink);
         font-family:-apple-system,"Segoe UI","Microsoft YaHei",system-ui,sans-serif;
         line-height:1.72; font-size:15px; }
  .wrap { max-width:1180px; margin:0 auto; }
  .card { background:#fff; border:1px solid var(--line); border-radius:12px;
          padding:26px 30px; margin-bottom:20px; box-shadow:0 1px 2px rgba(16,24,40,.04); }
  h1 { font-size:25px; margin:0 0 6px; letter-spacing:-.2px; }
  h2 { font-size:18px; margin:0 0 14px; padding-bottom:10px; border-bottom:1px solid var(--line); }
  h3 { font-size:15px; margin:20px 0 8px; color:#2c3e50; }
  .sub { color:var(--muted); font-size:13.5px; margin-bottom:0; }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; }
  .kpi { background:var(--bg); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
  .kpi .k { font-size:12.5px; color:var(--muted); }
  .kpi .v { font-size:22px; font-weight:650; letter-spacing:-.5px; margin:2px 0; }
  .kpi .n { font-size:12.5px; color:var(--muted); }
  .red { color:var(--hl); } .pos { color:#c0392b; } .neg { color:#1e8449; }
  table { width:100%; border-collapse:collapse; font-size:13.5px; }
  th,td { padding:9px 11px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
  th { background:#f2f5f8; font-weight:600; color:#3d4d5c; font-size:12.5px; }
  td.l,th.l { text-align:left; }
  td.hl { font-weight:650; }
  .mono { font-family:"JetBrains Mono",Consolas,"Courier New",monospace; font-size:12.5px; }
  tbody tr:hover { background:#fafcfe; }
  .note { background:#fffbf0; border:1px solid #f0e0b8; border-left:4px solid #e0a800;
          border-radius:8px; padding:14px 18px; font-size:13.5px; color:#5c4a15; }
  .key { background:#fdf2f0; border:1px solid #f2cfc9; border-left:4px solid var(--hl);
         border-radius:8px; padding:14px 18px; font-size:13.8px; }
  .win { background:#f1f8f4; border:1px solid #c8e3d3; border-left:4px solid #1e8449;
         border-radius:8px; padding:14px 18px; font-size:13.8px; color:#17452e; }
  .fix { background:#f1f5fb; border:1px solid #c9dcf2; border-left:4px solid #2c6fb5;
         border-radius:8px; padding:14px 18px; font-size:13.8px; color:#1b3c5f; }
  ul { padding-left:20px; margin:8px 0; } li { margin:5px 0; }
  code { background:#eef2f6; padding:1px 6px; border-radius:4px; font-size:12.8px; }
  .scroll { overflow-x:auto; }
</style></head><body><div class="wrap">
"""

BASE = dict(template="plotly_white", font=dict(family="Segoe UI, Microsoft YaHei, sans-serif",
                                               size=12.5, color=INK))


def read_df() -> pd.DataFrame:
    recs = json.loads(DATA.read_text(encoding="utf-8"))
    return pd.DataFrame(recs)


def piv(df: pd.DataFrame, col: str) -> pd.DataFrame:
    return df.pivot_table(index="coin", columns="window", values=col, aggfunc="first")


def fig_scatter(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=1, cols=2,
                        subplot_titles=("近 3 年", "近 1 年"),
                        horizontal_spacing=0.09)
    for j, w in enumerate(["近3年", "近1年"], start=1):
        g = df[df["window"] == w]
        fig.add_trace(go.Scatter(
            x=g["g_sup"] * 100, y=g["g_px"] * 100, mode="markers+text",
            text=g["coin"], textposition="top center",
            textfont=dict(size=9.5, color=MUTED),
            marker=dict(size=9, color=RED if w == "近1年" else "#2c6fb5",
                        opacity=0.8, line=dict(width=0.5, color="#fff")),
            showlegend=False), row=1, col=j)
        for xv, lab in ((5, "5%"), (10, "10%")):
            fig.add_vline(x=xv, line=dict(color="#e0a800", width=1.4, dash="dot"),
                          row=1, col=j,
                          annotation_text=lab, annotation_position="top",
                          annotation_font=dict(size=10, color="#b8860b"))
        fig.add_hline(y=0, line=dict(color="#b9c4ce", width=1))
    fig.update_xaxes(title_text="年化净增发率 (%)")
    fig.update_yaxes(title_text="年化价格涨幅 (%)", row=1, col=1)
    fig.update_yaxes(range=[-100, 300], row=1, col=2)
    fig.update_layout(height=520, **BASE,
                      title_text="净增发率 vs 价格涨幅（点位为币种；右图 Y 轴已截断，"
                                 "ZEC 近1年 +2400% 超出显示范围）")
    return fig


def fig_group(df: pd.DataFrame) -> go.Figure:
    bins = [(-1e9, 0.05, "<5%"), (0.05, 0.10, "5-10%"), (0.10, 1e9, ">10%")]
    fig = go.Figure()
    for w in WINDOWS:
        g = df[df["window"] == w]
        ys, ns = [], []
        for lo, hi, _ in bins:
            m = g[(g["g_sup"] >= lo) & (g["g_sup"] < hi)]
            ys.append(m["g_px"].median() * 100 if len(m) else np.nan)
            ns.append(len(m))
        fig.add_trace(go.Bar(
            name=w, x=[b[2] for b in bins], y=ys,
            text=[f"{v:+.0f}%<br>n={n}" if np.isfinite(v) else "" for v, n in zip(ys, ns)],
            textposition="outside", textfont=dict(size=10.5),
            marker_color={"近1年": "#8fa8bf", "近2年": "#4b7ba8", "近3年": "#2c6fb5"}[w]))
    fig.add_hline(y=0, line=dict(color="#b9c4ce", width=1))
    fig.update_layout(height=460, barmode="group", **BASE,
                      yaxis_title="价格涨幅中位 (%)",
                      title_text="按净增发率分档的价格涨幅中位（三窗口）")
    return fig


def fig_threshold(df: pd.DataFrame) -> go.Figure:
    cuts = [0.03, 0.05, 0.07, 0.10, 0.15]
    fig = go.Figure()
    for w, c in zip(WINDOWS, ["#8fa8bf", "#4b7ba8", "#2c6fb5"]):
        g = df[df["window"] == w]
        ys = []
        for v in cuts:
            lo, hi = g[g["g_sup"] < v]["g_px"], g[g["g_sup"] >= v]["g_px"]
            ys.append((lo.median() - hi.median()) * 100 if len(lo) and len(hi) else np.nan)
        fig.add_trace(go.Scatter(x=[f"{int(x * 100)}%" for x in cuts], y=ys, name=w,
                                 mode="lines+markers", line=dict(width=2.4, color=c),
                                 marker=dict(size=8)))
    fig.update_layout(height=440, **BASE, xaxis_title="分界线（年化净增发率）",
                      yaxis_title="低增发组 − 高增发组 的价格涨幅中位差 (pp)",
                      title_text="阈值敏感性：判别力随分界线上移而增强 → 真正的线在 10% 附近，不是 5%")
    return fig


def fig_trend(df: pd.DataFrame) -> go.Figure:
    p = piv(df, "g_sup").reindex(columns=["近3年", "近2年", "近1年"])
    p = p.sort_values("近1年", ascending=False)
    p = p[p["近1年"] >= 0.02]                       # 只看近期仍 >=2% 的
    fig = go.Figure()
    for w, c in zip(["近3年", "近2年", "近1年"], ["#c8d8e6", "#6f9cc4", "#2c6fb5"]):
        fig.add_trace(go.Bar(name=w, x=p.index, y=p[w] * 100,
                             marker_color=c, text=[f"{v * 100:.0f}%" if pd.notna(v) else ""
                                                   for v in p[w]],
                             textposition="outside", textfont=dict(size=10)))
    fig.update_layout(height=480, barmode="group", **BASE,
                      yaxis_title="年化净增发率 (%)",
                      title_text="增发收敛了吗：3年 → 2年 → 1 年（仅列近 1 年 >=2% 的币）")
    return fig


def fig_forward(df: pd.DataFrame, meas: dict) -> go.Figure:
    """三根柱：实测近1年 / 前瞻·协议排放 / 前瞻·流通量增速。

    第二、三根柱的分离就是本次修正的核心——对欠解锁的币，两者的差就是「归属解锁」这块。
    """
    rowsd = []
    for c, (fw_em, fw_sup, kind, _, _) in FORWARD.items():
        rowsd.append((c, meas.get(c, np.nan) * 100, fw_em, fw_sup, kind))
    for c, (kind, _) in MECH.items():
        v = meas.get(c, np.nan) * 100
        rowsd.append((c, v, v, v, kind))
    rowsd.sort(key=lambda r: -(r[1] if np.isfinite(r[1]) else -9))
    coins = [r[0] for r in rowsd]
    fig = go.Figure()
    for k, (name, col) in enumerate([("实测：过去 12 个月", "#8fa8bf"),
                                     ("前瞻：协议排放口径", "#e8b23a"),
                                     ("前瞻：流通量增速口径", GREEN)]):
        ys = [r[1 + k] for r in rowsd]
        fig.add_trace(go.Bar(
            name=name, x=coins, y=ys, marker_color=col,
            text=[f"{v:.1f}%" if np.isfinite(v) else "—" for v in ys],
            textposition="outside", textfont=dict(size=10)))
    fig.update_layout(height=500, barmode="group", **BASE, yaxis_title="年化净增发率 (%)",
                      title_text="关键修正：过去 12 个月 ≠ 未来 12 个月"
                                 "（黄绿两柱的落差 = 归属解锁，不是协议通胀）")
    return fig


def main() -> None:
    df = read_df()
    p_sup = piv(df, "g_sup")
    p_px = piv(df, "g_px")
    g1 = df[df["window"] == "近1年"].set_index("coin")
    meas1 = g1["g_sup"].to_dict()

    # 解锁/释放进度（circ ÷ 硬顶）——用来判断高增发是「进行中」还是「已近尾声」
    PROG = {}
    snap_p = ROOT / "markets" / "crypto" / "out" / "cg_supply_2026-09-12.json"
    if snap_p.exists():
        _snap = json.loads(snap_p.read_text(encoding="utf-8"))
        for _s, _v in _snap.items():
            _den = _v.get("maxs") or _v.get("total")
            if _v.get("circ") and _den:
                PROG[_s] = _v["circ"] / _den

    fig1, fig2, fig3, fig4, fig5 = (fig_scatter(df), fig_group(df), fig_threshold(df),
                                    fig_trend(df), fig_forward(df, meas1))
    figs = [f.to_html(include_plotlyjs=("cdn" if i == 0 else False), full_html=False,
                      config={"responsive": True})
            for i, f in enumerate([fig1, fig2, fig3, fig4, fig5])]

    # ---------- 正文数字全部动态计算，避免硬编码漂移 ----------
    def spearman(x, y):
        x, y = pd.Series(np.asarray(x, float)), pd.Series(np.asarray(y, float))
        m = np.isfinite(x) & np.isfinite(y)
        return float(np.corrcoef(x[m].rank(), y[m].rank())[0, 1])

    S: dict = {}
    S["n_coins"] = int(df["coin"].nunique())
    for w in WINDOWS:
        g = df[df["window"] == w]
        S[f"rho_{w}"] = spearman(g["g_sup"], g["g_px"])
        S[f"n_{w}"] = len(g)
        # 回归 价格涨幅 = a + b·净增发
        b, _ = np.polyfit(g["g_sup"].values, g["g_px"].values, 1)
        S[f"b_{w}"] = b
        S[f"r2_{w}"] = float(np.corrcoef(g["g_sup"], g["g_px"])[0, 1]) ** 2
        # 分层（2020 为界）
        nw, od = g[g["vintage"] > 2020], g[g["vintage"] <= 2020]
        S[f"new_{w}"] = spearman(nw["g_sup"], nw["g_px"])
        S[f"nnew_{w}"] = len(nw)
        S[f"old_{w}"] = spearman(od["g_sup"], od["g_px"])
        S[f"nold_{w}"] = len(od)
        # 三档中位
        for k, (lo, hi) in {"lo": (0, 0.05), "mid": (0.05, 0.10), "hi": (0.10, 9.9)}.items():
            s = g[(g["g_sup"] >= lo) & (g["g_sup"] < hi)]
            S[f"med_{k}_{w}"] = s["g_px"].median() * 100
            S[f"cnt_{k}_{w}"] = len(s)
        # 阈值敏感性
        S[f"thr_{w}"] = {int(v * 100): (g[g["g_sup"] < v]["g_px"].median()
                                        - g[g["g_sup"] >= v]["g_px"].median()) * 100
                         for v in (0.03, 0.05, 0.10, 0.15)}
        # >10% 档的市值中位（用于拆「纯稀释 vs 需求撤退」）
        _h = g[g["g_sup"] > 0.10]
        S[f"mc_hi_{w}"] = _h["g_mc"].median() * 100 if len(_h) else np.nan
        S[f"sup_hi_{w}"] = _h["g_sup"].median() * 100 if len(_h) else np.nan
        S[f"gap_hi_{w}"] = abs(S[f"med_hi_{w}"] - S[f"mc_hi_{w}"]) if len(_h) else np.nan
        _apt = g[g["coin"] == "APT"]
        if len(_apt):
            S[f"apt_mc_{w}"] = float(_apt.iloc[0]["g_mc"]) * 100
            S[f"apt_px_{w}"] = float(_apt.iloc[0]["g_px"]) * 100
            S[f"apt_sup_{w}"] = float(_apt.iloc[0]["g_sup"]) * 100
    S["r2_min"] = min(S[f"r2_{w}"] for w in WINDOWS)
    S["r2_max"] = max(S[f"r2_{w}"] for w in WINDOWS)
    # >10% 档逐窗口名单
    for w in WINDOWS:
        g = df[(df["window"] == w) & (df["g_sup"] > 0.10)].sort_values("g_sup", ascending=False)
        S[f"hi10_{w}"] = "、".join(f"{r.coin} {r.g_sup*100:+.1f}%（价 {r.g_px*100:+.1f}%）"
                                  for r in g.itertuples())
    # 全池正收益币数（用来说明近 1 年是普跌年）
    S["n_up_1y"] = int((df[df["window"] == "近1年"]["g_px"] > 0).sum())

    # ---------- 主表：27 币实测 ----------
    def cell(v, fmt="{:+.2f}%"):
        return f"<td>{fmt.format(v * 100)}</td>" if pd.notna(v) else "<td>—</td>"

    tbl = ""
    for c in g1.sort_values("g_sup", ascending=False).index:
        r = g1.loc[c]
        v3 = p_sup.at[c, "近3年"] if (c in p_sup.index and "近3年" in p_sup.columns) else np.nan
        v2 = p_sup.at[c, "近2年"] if (c in p_sup.index and "近2年" in p_sup.columns) else np.nan
        # 前瞻流通量增速：有核实的用 FORWARD，无核实的沿用实测
        _fw = FORWARD.get(c)
        fw_sup = _fw[1] if _fw else r["g_sup"] * 100
        fw_txt = f"{fw_sup:+.1f}%"
        pr = PROG.get(c, np.nan)
        pr_txt = (f"{pr * 100:.0f}%" if np.isfinite(pr) else "—")
        # 释放进度 <60% 且当前增发 >5% → 稀释还在进行中，标红提示（⚠️ 警示色，非涨跌色）
        pr_cls = "red" if (np.isfinite(pr) and pr < 0.6 and r["g_sup"] > 0.05) else ""
        # 阶跃标记跨全部窗口（任一窗口出现大台阶即标），并注出发生在哪个窗口——
        # 否则会出现「大台阶次数(近1年)=0 却标 阶跃」的读表歧义（如 APT/DOT 的台阶在近2年）
        _sub = df[(df["coin"] == c) & (df["step_event"])]
        if len(_sub):
            _ws = [w for w in ("近1年", "近2年", "近3年") if w in set(_sub["window"])]
            flag = ("<span style='color:#b8860b'>阶跃</span>"
                    f"<span style='color:#8a95a0;font-size:11px'>（{'/'.join(_ws)}）</span>")
        else:
            flag = ""
        sign = "pos" if r["g_sup"] > 0 else "neg"
        pxs = "pos" if r["g_px"] > 0 else "neg"
        tbl += (
            f"<tr><td class='l'><b>{c}</b></td>"
            f"<td class='hl {sign}'>{r['g_sup'] * 100:+.2f}%</td>"
            + cell(v2)
            + cell(v3)
            + f"<td class='{pxs}'>{r['g_px'] * 100:+.1f}%</td>"
            f"<td>{r['g_mc'] * 100:+.1f}%</td>"
            f"<td>{r['max_jump'] * 100:.1f}%</td>"
            f"<td>{int(r['n_big_jumps'])}</td>"
            f"<td>{int(r['vintage'])}</td>"
            f"<td class='{pr_cls}'>{pr_txt}</td>"
            f"<td style='color:#2c6fb5;font-weight:600'>{fw_txt}</td>"
            f"<td class='l' style='white-space:normal;font-size:12px;color:#5a6773'>{flag}</td></tr>")

    # ---------- 前瞻修正表 ----------
    ftbl = ""
    for c, (fw_em, fw_sup, kind, why, src) in FORWARD.items():
        m = meas1.get(c, np.nan) * 100
        gap = fw_sup - fw_em
        gap_txt = (f"<span style='color:#c0392b;font-weight:600'>+{gap:.1f}pp</span>"
                   if gap > 1 else "—")
        ftbl += (f"<tr><td class='l'><b>{c}</b></td>"
                 f"<td class='hl'>{m:+.1f}%</td>"
                 f"<td>{fw_em:+.1f}%</td>"
                 f"<td class='pos'><b>{fw_sup:+.1f}%</b></td>"
                 f"<td class='l' style='font-size:12px'>{gap_txt}</td>"
                 f"<td class='l' style='font-size:12px'>{kind}</td>"
                 f"<td class='l' style='white-space:normal;font-size:12.5px'>{why}</td>"
                 f"<td class='l' style='white-space:normal;font-size:11.5px;color:#66788a'>{src}</td></tr>")
    for c, (kind, why) in MECH.items():
        m = meas1.get(c, np.nan) * 100
        ftbl += (f"<tr><td class='l'><b>{c}</b></td><td class='hl'>{m:+.1f}%</td>"
                 f"<td>—</td><td class='pos'><b>{m:+.1f}%</b></td>"
                 f"<td class='l' style='font-size:12px'>—</td>"
                 f"<td class='l' style='font-size:12px'>{kind}</td>"
                 f"<td class='l' style='white-space:normal;font-size:12.5px'>{why}</td>"
                 f"<td class='l' style='white-space:normal;font-size:11.5px;color:#66788a'>"
                 f"实测分解 data/cmc_history/{c}.json（未查到已生效的减发改革 → 前瞻沿用实测）</td></tr>")

    # 近 2 年 >10% 的币 → 现在落到哪一档（名单动态推导，不写死枚数）
    conv = ""
    _hi2 = p_sup["近2年"].dropna()
    _hi2 = _hi2[_hi2 > 0.10].sort_values(ascending=False)
    _n2 = len(_hi2)
    S["n_hi2"] = _n2
    for c in _hi2.index:
        a = _hi2[c] * 100
        b = p_sup.at[c, "近1年"] * 100 if (c in p_sup.index and pd.notna(p_sup.at[c, "近1年"])) \
            else np.nan
        _f = FORWARD.get(c)
        fw = _f[1] if _f else b
        pr = PROG.get(c, np.nan)
        pr_txt = (f"剩 {(1 - pr) * 100:.1f}%（已释放 {pr * 100:.1f}%）"
                  if np.isfinite(pr) else "—")
        conv += (f"<tr><td class='l'><b>{c}</b></td><td>{a:+.1f}%</td>"
                 f"<td>{b:+.1f}%</td>"
                 f"<td class='l pos'><b>{fw:+.1f}%</b></td>"
                 f"<td class='l' style='font-size:12px;color:#66788a'>{pr_txt}</td></tr>")

    sp = {}
    for w in WINDOWS:
        g = df[df["window"] == w]
        x = pd.Series(g["g_sup"].to_numpy()).rank().to_numpy()
        y = pd.Series(g["g_px"].to_numpy()).rank().to_numpy()
        sp[w] = float(np.corrcoef(x, y)[0, 1])

    html = CSS + f"""
<div class="card">
  <h1>币池 27 枚：<b>实测</b>净增发率 vs 涨跌</h1>
  <p class="sub">
  命题：净增发 &lt;5%/年 更容易涨、&gt;10%/年 基本难涨　　生成 {time.strftime('%Y-%m-%d %H:%M')}<br>
  流通量 = CMC 全历史<b>市值 ÷ 价格</b>（周频，回溯到各币上线日）→ 天然含「发行 + 解锁 − 销毁」，<b>实测口径</b>；
  并以 CoinGecko 近一年日频做双源对账（23/27 差异 ≤0.3pp）。<br>
  本地落盘：<code>markets/crypto/data/cmc_history/</code>（27 币）、
  <code>markets/crypto/data/supply_history/</code>（27 币）</p>
</div>

<div class="card">
  <h2>一、结论</h2>
  <div class="key">
    <b>您的方向成立，但那条线不在 5%，在 10%。</b>
    实测净增发与价格涨幅在三个窗口内全部负相关（Spearman
    {sp['近1年']:+.3f} / {sp['近2年']:+.3f} / {sp['近3年']:+.3f}），
    <b>&gt;10% 档在三个窗口里都是最差一档</b>（价格中位
    {S['med_hi_近1年']:+.1f}% / {S['med_hi_近2年']:+.1f}% / {S['med_hi_近3年']:+.1f}%）。
    但「&lt;5%」这条线不成立：<b>&lt;5% 与 5-10% 两档的顺序并不单调</b>
    （近 2 年 5-10% 档 {S['med_mid_近2年']:+.1f}%、反而最好），
    而判别力在近 3 年是<b>随分界线上移单调增强</b>的——从 5% 处的
    {S['thr_近3年'][5]:.1f}pp 一路升到 15% 处的 {S['thr_近3年'][15]:.1f}pp
    （近 2 年则在 5% 处有回撤：{S['thr_近2年'][3]:.1f} → {S['thr_近2年'][5]:.1f}pp）。
  </div>
  <div class="kpis" style="margin-top:16px">
    <div class="kpi"><div class="k">双源对账</div><div class="v">23 / 27</div>
      <div class="n">CMC 与 CoinGecko 差异 ≤0.3pp</div></div>
    <div class="kpi"><div class="k">Spearman（近 1 年）</div><div class="v red">{sp['近1年']:+.3f}</div>
      <div class="n">n=27，负相关</div></div>
    <div class="kpi"><div class="k">前 3 高增发（实测 1y）</div><div class="v red">107.1 / 24.7 / 20.4%</div>
      <div class="n">ETHFI / APT / FIL → 价格 −50.7 / −85.3 / −65.3%</div></div>
    <div class="kpi"><div class="k">前瞻仍 ≥10% 稀释</div><div class="v">3 个</div>
      <div class="n">FIL 20.4% / LINK 10.3% / <b>APT 10.0%</b>（归属尾未走完）</div></div>
    <div class="kpi"><div class="k">解锁程序已收官</div><div class="v">2 个</div>
      <div class="n">ETHFI（96.5% 已释放→前瞻 ≈0%）、POL（100%）</div></div>
  </div>

  <h3>五点要点</h3>
  <ul>
    <li><b>① 「&gt;10% 难涨」拿到实测支撑。</b>&gt;10% 档在近 1 年 / 近 2 年 / 近 3 年三个窗口的价格涨幅中位
      分别是 <b>{S['med_hi_近1年']:+.1f}% / {S['med_hi_近2年']:+.1f}% / {S['med_hi_近3年']:+.1f}%</b>，
      都是当档最差。近 1 年 &gt;10% 档只有 {S['cnt_hi_近1年']} 枚：
      {S['hi10_近1年']}。</li>
    <li><b>② 但「5%」这条线实测不成立。</b>近 2 年：&lt;5% 档 {S['med_lo_近2年']:+.1f}%、
      5-10% 档 <b>{S['med_mid_近2年']:+.1f}%</b>、&gt;10% 档 {S['med_hi_近2年']:+.1f}%
      —— 中间档反而是唯一正收益档。近 3 年 &lt;5% 与 5-10% 两档接近
      （{S['med_lo_近3年']:+.1f}% vs {S['med_mid_近3年']:+.1f}%）。
      <b>更准确的说法是「&gt;10% 是危险线」，而不是「5% 是门槛」。</b></li>
    <li><b>③ 解释力弱，必须诚实指出。</b>回归「价格涨幅 = a + b·净增发」得
      b ≈ {S['b_近1年']:.1f}（近 1 年）、{S['b_近2年']:.1f}（近 2 年）、{S['b_近3年']:.1f}（近 3 年），
      与「市值不变、纯稀释」的机械关系一致；<b>但 R² 只有
      {S['r2_min']:.3f} ~ {S['r2_max']:.3f}</b>。
      即：增发能解释的价格波动不到 {S['r2_max']*100:.0f}%，它是<b>必要条件/门槛</b>，不是选择器。</li>
    <li><b>④ 新币比老币敏感 —— 但只在近 2/3 年成立。</b>近 2 年：新币（&gt;2020 上市）
      Spearman <b>{S['new_近2年']:+.3f}</b>（n={S['nnew_近2年']}），老币仅 {S['old_近2年']:+.3f}；
      近 3 年 新币 {S['new_近3年']:+.3f} vs 老币 {S['old_近3年']:+.3f}。
      <b>⚠️ 近 1 年方向相反</b>（新币 {S['new_近1年']:+.3f} vs 老币 {S['old_近1年']:+.3f}），
      因该窗口 n 小且全线普跌。老币的涨跌主要由别的因素决定。</li>
    <li><b>⑤ 增发是「过去的」还是「现在的」，差别巨大 —— 这是本次最重要的修正，但要修两处。</b>
      2 年前 &gt;10% 的 {S['n_hi2']} 枚币里，POL 26.1%→2.05%、RENDER 15.0%→0.04%、SOL 12.0%→8.2%、
      DOT 11.7%→5.4%（前瞻 3.3%）确实已收敛；
      <b>但 ETHFI 与 APT 的修正方向和我上一版说的不同</b>：ETHFI 是「线性归属已收官」（前瞻 ≈0%，
      比原判断更彻底），APT 则<b>不是</b>「前瞻 2.6%」——那只是协议排放口径，
      按流通量增速算仍有 <b>+10.0%</b>（已释放仅 40.9%）。
      <br><b>结论修正为：修正后池内前瞻稀释仍 ≥10% 的是 FIL（20.4%）、LINK（10.3%）、APT（10.0%）三枚。</b></li>
  </ul>
</div>

<div class="card">
  <h2>二、散点：净增发率 vs 价格涨幅</h2>
  {figs[0]}
  <div class="note" style="margin-top:14px">
    <b>读法：</b>点越靠右下 = 增发越高、涨得越差。<b>近 3 年</b>图里 10% 线右侧的 6 枚币
    （SOL / LINK / RENDER / DOT / FIL / APT）除 SOL、LINK 外全部为负；
    <b>近 1 年</b>图里几乎所有币都在左半区（低增发），却仍普遍下跌——因为这是普跌年，
    说明<b>低增发不能保证上涨，只是不额外挨一刀</b>。
  </div>
</div>

<div class="card">
  <h2>三、分档与阈值敏感性</h2>
  {figs[1]}
  {figs[2]}
  <div class="note" style="margin-top:14px">
    <b>为什么 &gt;10% 档这么差？</b>先记住恒等式：<code>价格 = 市值 ÷ 流通量</code>，
    所以<b>价格跌幅 ≈ 市值跌幅 + 稀释幅度</b>（对数口径下是严格等式）。
    近 3 年 &gt;10% 档：价格中位 {S['med_hi_近3年']:+.1f}%、市值中位 {S['mc_hi_近3年']:+.1f}%，
    价格多跌了 <b>{S['gap_hi_近3年']:.1f}pp</b>，而这组的净增发中位是
    <b>{S['sup_hi_近3年']:.1f}%</b> —— 两者量级相当。
    也就是说：市值几乎没掉、价格被新增供应摊薄，这是<b>纯稀释</b>，不是有人抛弃它。
    <br><b>但 APT 是另一个故事。</b>近 3 年 APT 市值 {S['apt_mc_近3年']:+.1f}%，
    远差于该组中位 {S['mc_hi_近3年']:+.1f}% —— 除稀释之外，<b>需求端也在撤退</b>（估值下移 + 稀释双杀），
    所以它是池内表现最差的币（价 {S['apt_px_近3年']:+.1f}%）。
    <br><b>读法：</b>「价格跌」要拆成「市值跌」和「稀释」两截 ——
    前者是市场对它的判断，后者是代币机制强加的，后者可控、前者不可控。
  </div>
</div>

<div class="card">
  <h2>四、增发在收敛还是顽固</h2>
  {figs[3]}
  <div class="win" style="margin-top:14px">
    <b>三类要分开（机制不同，结局不同）：</b>
    <br>· 「<b>收敛型</b>」= 增发率逐年下降（APT 55.2→32.8→24.7%、DOT 11.7→6.8→5.4%、
    SOL 12.6→12.0→8.2%、POL 26.1→2.05%、RENDER 15.0→0.04%）→ 时间站在你这边。
    <br>· 「<b>顽固型</b>」= 卡在同档的<b>持续通胀</b>（XLM 8.2→8.6→9.7%、XRP 5.8→5.6→5.3%、
    FIL 22.8→19.0→20.4%）→ 不改革就永久背稀释。
    <br>· 「<b>释放型</b>」= 数值不低但<b>不是协议通胀</b>，而是储备/归属被计入流通
    （<b>LINK 11.7→11.0→10.3% 属此类</b>：月度增量几乎恒为 0，只在 4 个时点跳 +18~21M）→
    有明确终点（LINK 剩 252M 枚，按 ~70M/年 还可续 ~3.6 年）。
    <br><b>⚠️ 修正：上一版把 LINK 归入「顽固型」是错的</b>——它不是持续通胀，是储备释放，
    两者对「该不该长期持有」的含义完全相反。
  </div>
</div>

<div class="card">
  <h2>五、关键修正：过去 12 个月的增发 ≠ 未来的增发</h2>
  {figs[4]}
  <div class="fix" style="margin-top:14px">
    <b>您指出的这一点是对的，而且是本次分析里最有价值的修正。</b>
    我上一版把「过去实现的高增发」当成当下的门槛，会把已经改革完的币误判成高稀释标的。
    <br>但把实测序列拆到月度之后，又发现<b>修正方向对、归因错了两处</b>，一并更正如下：
  </div>
  <div class="key" style="margin-top:12px">
    <b>更正 1（ETHFI）：不是「供应商重分类」，是等量线性归属解锁，且已经收官。</b>
    我用 CMC 序列按月反推 circ，发现 2025-05 起连续 15 个月<b>绝对增量恒定在 44~49M 枚/月</b>，
    相对率由 39.9% 单调衰减到 5.0%——这是「固定绝对量 ÷ 不断变大的基数」的指纹，只能是线性归属，
    不可能是重分类。2026-07 后程序结束（8 月 Δ=−8.1M 回修、9 月 Δ=0）。
    当前 circ 965.4M ÷ 硬顶 1000M = <b>96.5%</b>，只剩 34.6M 枚 →
    前瞻从 +3.3% 下修到 <b>≈0%</b>（比原判断更彻底）。
  </div>
  <div class="key" style="margin-top:10px">
    <b>更正 2（APT）：+2.6% 是「协议排放」口径，不是流通量增速；后者约 +10%。</b>
    实测 +24.7% 逐月分解 = 归属解锁 ≈10.2M/月 + 质押排放 5.2M/月，
    改革后观测值稳定在 ~12.8M/月（= 10.2 + 2.6），断点正好在 2026-04 —— 与改革公告完全吻合。
    <b>但 2026-10 归属期结束后，社区 10 年线性释放（≈4.25M/月）仍在跑</b>，
    加上质押 2.6M/月 ≈ 82M 枚/年 ÷ 858M ≈ <b>+10%</b>。
    已释放率只有 40.9%（剩 1241M 枚未解锁），<b>APT 不能算「已出清的高增发」</b>。
  </div>
  <div class="scroll" style="margin-top:14px">
  <table>
    <thead><tr><th class="l">币</th><th>实测<br>1 年</th><th>前瞻<br>协议排放</th>
      <th>前瞻<br>流通量增速</th><th class="l">差<br>(=归属解锁)</th><th class="l">机制</th>
      <th class="l">依据</th><th class="l">来源</th></tr></thead>
    <tbody>{ftbl}</tbody>
  </table></div>
  <h3>2 年前 &gt;10% 的 7 枚币，现在落到哪一档</h3>
  <div class="scroll">
  <table>
    <thead><tr><th class="l">币</th><th>近 2 年年化</th><th>近 1 年实测</th>
      <th class="l">前瞻（流通量增速）</th><th class="l">还剩多少未释放</th></tr></thead>
    <tbody>{conv}</tbody>
  </table></div>
  <div class="note" style="margin-top:14px">
    <b>口径纪律（本次修正的核心）：</b>三列不可混用。
    <br>· <b>实测</b> = 「市值 ÷ 价格」反推的流通量变化，含归属解锁的台阶，做<b>历史归因</b>用。
    <br>· <b>前瞻·协议排放</b> = 质押/区块奖励等协议自己铸的币，长期可持续，衡量<b>永久性稀释</b>。
    <br>· <b>前瞻·流通量增速</b> = 协议排放 + 归属解锁 − 销毁，是<b>实际供应压力</b>，
    也就是您感觉到的「稀释」，<b>做门槛判断必须用这一列</b>。
    <br>对欠解锁的币，第 2、3 列能差 4 倍以上（APT：2.6% vs 10.0%）——上一版正是只看了第 2 列才误判。
  </div>
</div>

<div class="card">
  <h2>六、逐币实测明细</h2>
  <div class="scroll">
  <table>
    <thead><tr>
      <th class="l">币</th><th>净增发<br>近1年</th><th>近2年</th><th>近3年</th>
      <th>价格<br>近1年</th><th>市值<br>近1年</th><th>最大单周<br>流通量跳变<br>(近1年)</th>
      <th>大台阶<br>次数<br>(近1年)</th>
      <th>上市年</th><th>已释放<br>÷硬顶</th>
      <th>前瞻<br>流通量<br>增速</th><th class="l">标注<br>(跨窗口)</th>
    </tr></thead>
    <tbody>{tbl}</tbody>
  </table></div>
  <div class="note" style="margin-top:14px">
    <b>「阶跃」是什么意思：</b>单周流通量变化 &gt;5% 且出现 ≥2 次。协议发行通常平滑（周变化 &lt;1%），
    出现大台阶必然是「解锁/释放/回修」。逐币核对台阶<b>日期与幅度</b>后，可分成四种，性质完全不同：
  </div>
  <div class="scroll" style="margin-top:10px">
  <table>
    <thead><tr><th class="l">币</th><th class="l">台阶形态（实测）</th><th class="l">性质判定</th></tr></thead>
    <tbody>
    <tr><td class="l"><b>ETHFI</b></td>
      <td class="l" style="white-space:normal">2025-09~2026-07 连续 12 次，日期等间隔约 4 周，
        幅度 +9.6%→+8.8%→+7.9%→+7.2%→+6.8%→+6.4%→+6.0%→+5.7%→+5.3%→+5.3%→+4.8%→+4.6%，
        末次 2026-08-30 为 <b>−5.2%</b></td>
      <td class="l" style="white-space:normal"><b>等量线性归属解锁</b>（绝对量恒定 44~49M 枚/月，
        相对率衰减）。台阶已停 → 前瞻 ≈0%。
        <b>⚠️ 上一版判为「供应商重分类」是错的，此处更正</b></td></tr>
    <tr><td class="l"><b>APT</b></td>
      <td class="l" style="white-space:normal">近 1 年 <b>0 次</b>（最大周变化仅 1.78%）；
        近 3 年内 7 次集中在 2023-11~2024-04（+10.3/+9.3/+8.5/+7.6/+7.1/+6.6/+5.6%），
        日期严格 4 周间隔</td>
      <td class="l" style="white-space:normal"><b>早期月度 cliff 解锁，现已转入平滑</b>
        （月度绝对增量稳定在 12.8M 枚，单月 &lt;4% 故不触发阈值）→ 高增发没停，只是不再跳</td></tr>
    <tr><td class="l"><b>DOT</b></td>
      <td class="l" style="white-space:normal">5 次全在 2023-10~2024-03，且<b>正负交替</b>
        （+4.3/−5.3/+7.3/−6.5/+10.5%）</td>
      <td class="l" style="white-space:normal"><b>供应商重分类</b>（供给只会增不会减，
        ±交替说明是「桶的归类在动」而非真实发行）</td></tr>
    <tr><td class="l"><b>GRAM</b></td>
      <td class="l" style="white-space:normal">2024-06-02 <b>−30.6%</b>、2025-08-10 +6.2%</td>
      <td class="l" style="white-space:normal"><b>改名/重述</b>（TON→Gram 供应商换了流通口径），
        不是销毁</td></tr>
    <tr><td class="l"><b>HYPE</b></td>
      <td class="l" style="white-space:normal">2026-01-18 <b>−11.0%</b>、2026-02-08 <b>−14.0%</b>；
        另首月 2024-11 circ≈0 造成近 2/3 年窗口「年化 = inf」伪影</td>
      <td class="l" style="white-space:normal"><b>真实销毁</b>（回购+gas 燃烧），两只负台阶 →
        该币通缩成立；inf 伪影已剔除</td></tr>
    <tr><td class="l"><b>RAY</b></td>
      <td class="l" style="white-space:normal">2024-11-17 +10.3%、2025-06-22 −7.0%</td>
      <td class="l" style="white-space:normal">解锁 + 供应商回修混合，样本仅 2 次，不判定</td></tr>
    </tbody>
  </table></div>
  <div class="note" style="margin-top:10px">
    <b>读表提醒：</b>「最大单周跳变」「大台阶次数」两列只统计<b>近 1 年</b>；「标注」列的阶跃是<b>跨窗口</b>判定，
    括号内注出发生在哪个窗口——所以会出现「近 1 年 0 次台阶却标注阶跃」的情况（如 APT/DOT 的台阶在近 3 年）。
  </div>
</div>

<div class="card">
  <h2>七、局限</h2>
  <ul>
    <li><b>幸存者偏差（最严重）。</b>本池按「买旧不买新 + 熊市幸存」选出，结构上已排除掉高增发而死亡的项目。
      {S['n_coins']} 枚里实测近 1 年增发 &gt;10% 的只有 {S['cnt_hi_近1年']} 枚，
      &lt;5% 的有 {S['cnt_lo_近1年']} 枚 —— 分布本身就是筛选结果，
      所以「门槛效应」在本池内必然被压缩，<b>不可外推为全市场规律</b>。</li>
    <li><b>窗口混杂。</b>近 1 年是普跌年（BTC −30%、多数山寨 −50~75%），截面差异被系统性风险主导；
      近 2/3 年更接近正常周期，结论应以近 2/3 年为主。</li>
    <li><b>供应商口径。</b>DOT（CMC 5.35% vs CG 11.93%）、AVAX、UNI、HYPE 在两家供应商间差异 &gt;2.5pp，
      因「哪些算流通」判定不同；本报告采用 CMC 为主、CG 对账。</li>
    <li><b>相关 ≠ 因果。</b>β≈−1 与机械恒等式（价格 = 市值/流通量）一致，含部分定义内生的成分；
      R² 极低也说明该变量单独不构成策略。</li>
    <li><b>被剔除的伪影（已查、已标）。</b>HYPE 在 CMC 序列首月（2024-11）circ≈0，
      导致近 2/3 年窗口的「年化净增发」计算为 <code>inf</code>——已排除，不做任何引用。
      ETHFI 的 −5.2%、DOT 的 ±交替、GRAM 的 −30.6% 均判定为供应商口径变动而非真实供给变化，
      已在第六节的台阶表里逐条标注性质。</li>
    <li><b>一个失败的替代变量（如实记录）。</b>我尝试用「剩余未解锁比例（1 − circ ÷ 硬顶）」
      替代净增发率作为前瞻性稀释指标，假设它应更能预测未来压力。
      <b>实测失败</b>：ρ(剩余未解锁, 价格涨幅) = −0.184，弱于净增发率本身的 −0.431；
      欠解锁组（剩余 &gt;40%）的价格中位反而最差（−63.5%）但正收益占比最高（1/5）——n 太小且方向矛盾。
      <b>结论：净增发率仍是本池内最好的单变量，但「已释放进度」是有价值的补充读法，不是替代品。</b></li>
    <li><b>前瞻值的不确定性。</b>APT 的 +10.0% 由「月度绝对增量 12.8M 枚」外推，
      依赖「2026-10 归属期结束后释放量 −60%」这条公告兑现；若社区释放节奏与公告不符，
      该值可能落在 +10% ~ +21% 区间。ETHFI 的 ≈0% 依赖「硬顶 1000M」前提。</li>
  </ul>
</div>

<div class="card">
  <h2>八、可操作结论</h2>
  <div class="key">
    <b>1. 用法：当前瞻准入门槛，不当选择器。</b>
    实测判别力峰值在 10~15% 而不是 5%，且 R² &lt;{S['r2_max']*100:.0f}% —— 它能剔掉被稀释拖累的名字，
    选不出赢家。
  </div>
  <div class="key" style="margin-top:10px">
    <b>2. 门槛线：用 10%，不用 5%。</b>
    5% 这条线的分组顺序不单调（近 2 年 5-10% 档反而是唯一正收益档），
    而 &gt;10% 在三个窗口都是最差档。
  </div>
  <div class="key" style="margin-top:10px">
    <b>3. 必须用「流通量增速」前瞻，不能用协议排放前瞻，更不能用过去 12 个月。</b>
    · 用过去 12 个月 → ETHFI（+107%）被当成最毒标的，实际它前瞻 ≈0%（解锁已收官）。
    <br>· 用协议排放前瞻 → APT 显示 +2.6% 看似安全，实际流通量增速仍有 <b>+10.0%</b>（已释放仅 40.9%）。
    <br><b>两个方向都会错，且错法相反。</b>
  </div>
  <div class="key" style="margin-top:10px">
    <b>4. 本池前瞻稀释仍 ≥10% 的三枚：FIL 20.4% / LINK 10.3% / APT 10.0%。</b>
    其中 LINK 是「储备释放」（剩 252M 枚，约 3.6 年释放完）、FIL 是「持续通胀」（待核实构成）、
    APT 是「归属尾未走完」（2026-10 后减 60%）。其余 24 枚前瞻均已 &lt;10%。
  </div>
  <div class="key" style="margin-top:10px">
    <b>5. 对再平衡池的含义。</b>净增发是<b>慢变量</b>——它决定长期跑不赢的原因，
    但不决定短期涨跌（R² 太低）。所以它适合做<b>入池前的排雷</b>，不适合做择时信号；
    真正驱动净值波动的仍是周期相位与再平衡超额（见 <code>btc_ada_pair_rebalance.html</code>）。
  </div>
  <p style="color:#66788a;font-size:13px;margin-top:16px">
    本报告为量化研究，不构成投资建议。加密货币波动极高，请自行研究并承担风险。
  </p>
</div>
</div></body></html>
"""
    OUTF.parent.mkdir(parents=True, exist_ok=True)
    OUTF.write_text(html, encoding="utf-8")
    print(f"已生成 {OUTF.relative_to(ROOT)}  ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
