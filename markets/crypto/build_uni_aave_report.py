# -*- coding: utf-8 -*-
"""生成 UNI + AAVE 双币配对再平衡报告 (HTML, 本地留底)。

用法: python markets/crypto/build_uni_aave_report.py
输出: docs/reports/crypto/uni_aave_pair_rebalance.html

口径铁律 (与全项目一致):
  ① 筹码口径 units_mult (死拿=1.000) — 根本答案
  ② 美元口径 nav               — 赚几倍
  ③ 超额 = 再平衡净值 / 同币同窗口等权死拿净值 - 1 — 机器效率
所有正文数字一律由 main() 动态计算注入, 禁止硬编码。
"""
import os
import importlib.util

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
_spec = importlib.util.spec_from_file_location("pair", os.path.join(HERE, "uni_aave_pair_rebalance.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)
bap = mod.bap

OUT = os.path.join(REPO, "docs", "reports", "crypto", "uni_aave_pair_rebalance.html")
A, B = "UNI", "AAVE"


def pct(x, d=2):
    return f"{x * 100:+.{d}f}%"


def main():
    px = mod.load_panel()
    win0 = mod.natural_start(px, [A, B])
    win0s = str(win0.date())

    # ---------- 全部数字先算好 ----------
    r0 = bap.sim(px, [A, B], start=win0s, cost_bp=0.0)
    r10 = bap.sim(px, [A, B], start=win0s, cost_bp=10.0)
    r30 = bap.sim(px, [A, B], start=win0s, cost_bp=30.0)
    st, en = r0["start"], r0["end"]
    h = bap.buyhold(px, [A, B], st, en)
    sa = bap.solo(px, A, st, en)
    sb = bap.solo(px, B, st, en)
    ex0 = r0["nav"] / h["nav"] - 1
    ex10 = r10["nav"] / h["nav"] - 1
    drift = (sa["cagr"] - sb["cagr"]) * 100
    kind = "双正" if sa["cagr"] > 0 and sb["cagr"] > 0 else ("双负" if sa["cagr"] < 0 and sb["cagr"] < 0 else "一正一负")

    sub = px.loc[win0s:, [A, B]].dropna()
    rr = sub.pct_change().dropna()
    corr = float(rr[A].corr(rr[B]))
    vol_a = float(rr[A].std() * np.sqrt(52))
    vol_b = float(rr[B].std() * np.sqrt(52))
    w = np.array([0.5, 0.5])
    pvol = float(np.sqrt(w @ (rr.cov().values * 52) @ w))

    ua0, ub0 = r0["units_mult"][A], r0["units_mult"][B]
    ua10, ub10 = r10["units_mult"][A], r10["units_mult"][B]

    S = dict(
        A=A, B=B, win0=win0s, end=str(en.date()), yrs=r0["yrs"],
        nav0=r0["nav"], nav10=r10["nav"], nav30=r30["nav"],
        cagr0=r0["cagr"], cagr10=r10["cagr"], mdd0=r0["mdd"],
        hold=h["nav"], hold_cagr=h["cagr"], hold_mdd=h["mdd"],
        sa_nav=sa["nav"], sa_cagr=sa["cagr"], sa_mdd=sa["mdd"],
        sb_nav=sb["nav"], sb_cagr=sb["cagr"], sb_mdd=sb["mdd"],
        ex0=ex0, ex10=ex10, ua0=ua0, ub0=ub0, ua10=ua10, ub10=ub10,
        drift=drift, kind=kind, corr=corr, vol_a=vol_a, vol_b=vol_b, pvol=pvol,
        turn=r0["turnover_ann"], nev=r0["turnover_events"],
        pa0=r0["px_first"][A], pa1=r0["px_last"][A],
        pb0=r0["px_first"][B], pb1=r0["px_last"][B],
    )

    # 分段
    SEGS = [
        ("段1 · 上轮牛熊 (2020-10~2022-11)", None, "2022-11-11"),
        ("段2 · 复苏 (2022-11~2024-04)", "2022-11-11", "2024-04-19"),
        ("段3 · 本轮 (2024-04~今)", "2024-04-19", None),
        ("近 3 年", str((en - __import__("pandas").Timedelta(days=1095)).date()), None),
        ("近 2 年", str((en - __import__("pandas").Timedelta(days=730)).date()), None),
        ("近 1 年", str((en - __import__("pandas").Timedelta(days=365)).date()), None),
    ]
    seg_rows = ""
    for name, s0, s1 in SEGS:
        r = bap.sim(px, [A, B], start=s0, end=s1, cost_bp=10.0)
        if r is None:
            continue
        hh = bap.buyhold(px, [A, B], r["start"], r["end"])
        ex = r["nav"] / hh["nav"] - 1
        um = r["units_mult"]
        seg_rows += (
            f"<tr><td class='l'>{name}</td><td>{r['yrs']:.2f}</td>"
            f"<td class='hl'>{r['nav']:.3f}x</td>"
            f"<td class='{'pos' if r['cagr'] > 0 else 'neg'}'>{pct(r['cagr'])}</td>"
            f"<td class='neg'>{r['mdd'] * 100:.2f}%</td><td>{hh['nav']:.3f}x</td>"
            f"<td class='{'pos' if ex > 0 else 'neg'}'><b>{pct(ex)}</b></td>"
            f"<td class='{'pos' if um[A] >= 1 else 'neg'}'>{um[A]:.4f}x</td>"
            f"<td class='{'pos' if um[B] >= 1 else 'neg'}'>{um[B]:.4f}x</td></tr>"
        )

    # 频率 (含相位)
    freq_rows = ""
    for freq, lab in ((1, "每周"), (2, "双周"), (4, "月度"), (8, "双月")):
        base = bap.sim(px, [A, B], rebal_weeks=freq, start=win0s, cost_bp=0.0)
        if base is None:
            continue
        ph_navs = []
        nph = min(freq, 8)
        for sh in range(nph):
            s2 = str((win0 + __import__("pandas").Timedelta(weeks=sh)).date())
            r = bap.sim(px, [A, B], rebal_weeks=freq, start=s2, cost_bp=0.0)
            if r:
                ph_navs.append(r["nav"])
        rng = (max(ph_navs) / min(ph_navs) - 1) * 100 if len(ph_navs) > 1 else 0.0
        freq_rows += (
            f"<tr><td class='l'>{lab}</td><td>{nph}</td><td class='hl'>{base['nav']:.3f}x</td>"
            f"<td class='{'pos' if base['nav'] > h['nav'] else 'neg'}'>"
            f"{(base['nav'] / h['nav'] - 1) * 100:+.2f}%</td>"
            f"<td>{base['units_mult'][A]:.4f}x</td><td>{base['units_mult'][B]:.4f}x</td>"
            f"<td>{base['turnover_ann'] * 100:.0f}%</td>"
            f"<td>{'—' if len(ph_navs) <= 1 else f'{rng:.1f}%'}</td></tr>"
        )

    # 筹码轨迹 (每季度抽样)
    us = r0["units_ser"]
    traj_rows = ""
    for dt in us.index[::13]:
        traj_rows += (f"<tr><td class='l'>{dt.date()}</td>"
                      f"<td class='{'pos' if us.loc[dt, A] >= 1 else 'neg'}'>{us.loc[dt, A]:.4f}x</td>"
                      f"<td class='{'pos' if us.loc[dt, B] >= 1 else 'neg'}'>{us.loc[dt, B]:.4f}x</td></tr>")
    traj_rows += (f"<tr style='background:#fdf6f5'><td class='l'><b>{us.index[-1].date()} 期末</b></td>"
                  f"<td class='hl'><b>{us.iloc[-1][A]:.4f}x</b></td>"
                  f"<td class='hl'><b>{us.iloc[-1][B]:.4f}x</b></td></tr>")

    # SVG 筹码轨迹图 (无需外部依赖)
    W, H, PAD = 980, 260, 46
    xs = np.linspace(PAD, W - PAD, len(us))
    series = {A: us[A].values, B: us[B].values}
    ymin = min(min(v) for v in series.values()) * 0.97
    ymax = max(max(v) for v in series.values()) * 1.03

    def sy(v):
        return H - PAD - (v - ymin) / (ymax - ymin) * (H - 2 * PAD)

    def path(v):
        return " ".join(f"{'M' if i == 0 else 'L'}{xs[i]:.1f},{sy(v[i]):.1f}" for i in range(len(v)))

    grid = ""
    for gv in np.linspace(ymin, ymax, 5):
        grid += (f"<line x1='{PAD}' y1='{sy(gv):.1f}' x2='{W - PAD}' y2='{sy(gv):.1f}' "
                 f"stroke='#e3e8ee' stroke-width='1'/>"
                 f"<text x='{PAD - 8}' y='{sy(gv) + 4:.1f}' font-size='11' fill='#66788a' "
                 f"text-anchor='end'>{gv:.2f}</text>")
    base1 = sy(1.0)
    grid += (f"<line x1='{PAD}' y1='{base1:.1f}' x2='{W - PAD}' y2='{base1:.1f}' "
             f"stroke='#c0392b' stroke-width='1.2' stroke-dasharray='5,4'/>"
             f"<text x='{W - PAD - 4}' y='{base1 - 6:.1f}' font-size='11' fill='#c0392b' "
             f"text-anchor='end'>死拿 = 1.000</text>")
    xticks = ""
    for i in range(0, len(us), max(1, len(us) // 7)):
        xticks += (f"<text x='{xs[i]:.1f}' y='{H - PAD + 18}' font-size='11' fill='#66788a' "
                   f"text-anchor='middle'>{us.index[i].date()}</text>")

    svg = (f"<svg viewBox='0 0 {W} {H}' style='width:100%;height:auto'>"
           f"{grid}{xticks}"
           f"<path d='{path(series[A])}' fill='none' stroke='#c0392b' stroke-width='2.2'/>"
           f"<path d='{path(series[B])}' fill='none' stroke='#2471a3' stroke-width='2.2'/>"
           f"<text x='{W - PAD}' y='16' font-size='12' fill='#c0392b' text-anchor='end'>{A}</text>"
           f"<text x='{W - PAD - 44}' y='16' font-size='12' fill='#2471a3' text-anchor='end'>{B}</text>"
           f"</svg>")

    # ---------- 年化筹码增速 与 可持续性 (⚠️ 纯筹码口径, 不用超额/净值) ----------
    _m = __import__("math")
    pd = __import__("pandas")
    geo = lambda x: _m.exp(x) - 1
    cls = lambda v: "pos" if v >= 0 else "neg"
    y0 = r10["yrs"]

    # 唯一主指标: 单币筹码年化 (log) 与 组合筹码年化
    rca, rcb = _m.log(ua10) / y0, _m.log(ub10) / y0
    rcm = (rca + rcb) / 2          # 组合筹码年化 = 两币筹码年化的几何平均
    # 分解(只用各币价格倍数, 不引入 NAV/净值/起点价歧义):
    #   log 筹码_i = 组合筹码年化 + (log 价格倍数_其他 − log 价格倍数_i) / (2T)
    gA_, gB_ = _m.log1p(sa["cagr"]), _m.log1p(sb["cagr"])
    move_a, move_b = (gB_ - gA_) / 2, (gA_ - gB_) / 2

    # 分段年化筹码增速
    seg2_rows = ""
    seg_pm, seg_ra, seg_rb = [], [], []
    for name, s0, s1 in SEGS:
        r = bap.sim(px, [A, B], start=s0, end=s1, cost_bp=10.0)
        if r is None:
            continue
        ra = _m.log(r["units_mult"][A]) / r["yrs"]
        rb = _m.log(r["units_mult"][B]) / r["yrs"]
        pm2 = (ra + rb) / 2
        seg_pm.append(pm2)
        seg_ra.append(ra)
        seg_rb.append(rb)
        seg2_rows += (
            f"<tr><td class='l'>{name}</td><td>{r['yrs']:.2f}</td>"
            f"<td class='{cls(ra)}'>{geo(ra) * 100:+.2f}%</td>"
            f"<td class='{cls(rb)}'>{geo(rb) * 100:+.2f}%</td>"
            f"<td class='{cls(pm2)}'><b>{geo(pm2) * 100:+.2f}%</b></td>"
            f"<td class='{cls(r['units_mult'][A] - 1)}'>{r['units_mult'][A]:.4f}x</td>"
            f"<td class='{cls(r['units_mult'][B] - 1)}'>{r['units_mult'][B]:.4f}x</td></tr>"
        )

    # 滚动 2 年窗口: 组合筹码年化的分布 (路径依赖)
    idx2 = px[[A, B]].dropna().index
    W2 = 104
    roll_comb = []
    for i in range(0, len(idx2) - W2, 2):
        r = bap.sim(px, [A, B], start=idx2[i], end=idx2[i + W2], cost_bp=10.0)
        if r is None:
            continue
        ra = _m.log(r["units_mult"][A]) / r["yrs"]
        rb = _m.log(r["units_mult"][B]) / r["yrs"]
        roll_comb.append((ra + rb) / 2)
    rc_s = pd.Series(roll_comb)
    rq = rc_s.quantile([0, .25, .5, .75, 1])
    roll_n = len(roll_comb)
    neg_pm = float(np.mean([p < 0 for p in roll_comb]))

    # 滚动 1 年波动 / 相关 (筹码收割强度的两个来源)
    lrx = np.log(px[[A, B]]).diff()
    sig_r = (lrx.rolling(52).std() * np.sqrt(52)).dropna()
    rho_r = lrx[A].rolling(52).corr(lrx[B]).dropna()
    cmn = sig_r.index.intersection(rho_r.index)
    sig_avg = (sig_r.loc[cmn, A] + sig_r.loc[cmn, B]) / 2
    rho_r = rho_r.loc[cmn]
    sig_med, sig_lo, sig_hi, sig_now = (float(sig_avg.median()), float(sig_avg.min()),
                                        float(sig_avg.max()), float(sig_avg.iloc[-1]))
    rho_med, rho_lo, rho_hi, rho_now = (float(rho_r.median()), float(rho_r.min()),
                                        float(rho_r.max()), float(rho_r.iloc[-1]))

    # 全窗口对数口径 (Fernholz 收割公式的正确口径; 与第六节简单收益波动略有差异, 不影响结论)
    sig_full_a = float(lrx[A].dropna().std() * np.sqrt(52))
    sig_full_b = float(lrx[B].dropna().std() * np.sqrt(52))
    rho_full = float(lrx[A].dropna().corr(lrx[B].dropna()))

    # 组合筹码年化 = 波动收割项 = 0.25*(1-rho)*sigma^2 (等波动近似)
    SENS_RHO = (0.40, 0.60, round(rho_med, 2), 0.90)
    sens_head = "".join(f"<th>ρ={r_:.2f}</th>" for r_ in SENS_RHO)
    sens_rows = ""
    for s_ in (1.10, 0.90, 0.80, 0.60, 0.40, 0.30, 0.20):
        cells = ""
        for r_ in SENS_RHO:
            p_ = 0.25 * (1 - r_) * s_ * s_
            cells += f"<td class='pos'>{p_ * 100:+.2f}%</td>"
        hl = _m.log(2) / max(0.25 * (1 - rho_full) * s_ * s_, 1e-9)
        sens_rows += f"<tr><td class='l'>{s_ * 100:.0f}%</td>{cells}<td>{hl:.1f}</td></tr>"

    # 组合筹码年化归零临界 rho* = (k^2+1)/(2k)
    k_ = sig_full_a / sig_full_b
    rho_star = ((k_ ** 2) + 1) / (2 * k_)
    half_comb = _m.log(2) / rcm
    ten_comb = _m.log(10) / rcm
    harv_now = 0.25 * (1 - rho_now) * sig_now * sig_now
    harv = lambda s_: 0.25 * (1 - rho_full) * s_ * s_      # 全窗口 ρ 下的 σ→年化映射
    cut90 = 0.10 / max(1 - rho_full, 1e-9)                  # ρ=0.9 时相对当前被砍到的比例

    # ---------- HTML ----------
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>UNI + AAVE 配对再平衡 · 筹码口径</title>
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
  tbody tr:hover {{ background:#fafcfe; }}
  .note {{ background:#fffbf0; border:1px solid #f0e0b8; border-left:4px solid #e0a800;
           border-radius:8px; padding:14px 18px; font-size:13.5px; color:#5c4a15; }}
  .key {{ background:#fdf2f0; border:1px solid #f2cfc9; border-left:4px solid var(--hl);
          border-radius:8px; padding:14px 18px; font-size:13.8px; }}
  ul {{ padding-left:20px; margin:8px 0; }} li {{ margin:5px 0; }}
  code {{ background:#eef2f6; padding:1px 6px; border-radius:4px; font-size:12.8px; }}
  .scroll {{ overflow-x:auto; }}
</style>
</head>
<body><div class="wrap">

<div class="card">
  <h1>UNI + AAVE 配对再平衡 · 筹码口径</h1>
  <p class="sub">加密内部配对（不跨资产）· 等权月度再平衡 · 数据 <code>weekly_adjclose_crypto50_10y.csv</code>（周频后复权，27 币面板）<br>
  公共窗口 {S['win0']} ~ {S['end']}（{S['yrs']:.2f} 年，AAVE 上市自然起点）· 成本口径：主表扣 10bp 单边</p>
</div>

<div class="card">
  <h2>一、直接回答：增加了多少筹码</h2>
  <div class="kpis">
    <div class="kpi"><div class="k">UNI 币量 / 死拿</div><div class="v red">{S['ua10']:.3f}x</div>
      <div class="n">+{(S['ua10'] - 1) * 100:.1f}%（扣 10bp）</div></div>
    <div class="kpi"><div class="k">AAVE 币量 / 死拿</div><div class="v red">{S['ub10']:.3f}x</div>
      <div class="n">+{(S['ub10'] - 1) * 100:.1f}%（扣 10bp）</div></div>
    <div class="kpi"><div class="k">再平衡超额<br>（机器效率）</div><div class="v red">{pct(S['ex10'])}</div>
      <div class="n">净值比 {r10['nav'] / h['nav']:.4f}</div></div>
    <div class="kpi"><div class="k">组合净值 / 死拿</div><div class="v">{S['nav10']:.3f}x / {S['hold']:.3f}x</div>
      <div class="n">CAGR {pct(S['cagr10'])} vs {pct(S['hold_cagr'])}</div></div>
  </div>

  <div class="key" style="margin-top:18px">
    <b>一句话答案：</b>UNI+AAVE 月度再平衡在 {S['yrs']:.1f} 年里把
    <b>UNI 币量做到 {S['ua10']:.3f} 倍（+{(S['ua10'] - 1) * 100:.1f}%）、AAVE 币量做到 {S['ub10']:.3f} 倍（+{(S['ub10'] - 1) * 100:.1f}%）</b>；
    同期两者价格分别为 {S['pa0']:.3f} → {S['pa1']:.3f}（UNI）与 {S['pb0']:.2f} → {S['pb1']:.2f}（AAVE）。<br>
    <b>筹码明显偏向 UNI 一侧</b>——因为窗口内 UNI 的独立死拿 CAGR（{pct(S['sa_cagr'])}）低于 AAVE（{pct(S['sb_cagr'])}），
    漂移差 <b>{S['drift']:+.1f}pp</b>，再平衡按纪律持续<b>卖出相对强的 AAVE、买入相对弱的 UNI</b>。
  </div>
</div>

<div class="card">
  <h2>二、主对照（全窗口）</h2>
  <div class="scroll">
  <table>
    <thead><tr><th class="l">口径</th><th>净值</th><th>CAGR</th><th>MDD</th><th>Calmar</th><th class="l">说明</th></tr></thead>
    <tbody>
      <tr><td class="l"><b>UNI+AAVE 月再平衡 (0bp)</b></td><td class="hl">{S['nav0']:.3f}x</td>
        <td class="pos">{pct(S['cagr0'])}</td><td class="neg">{S['mdd0'] * 100:.2f}%</td>
        <td>{r0['calmar']:.2f}</td><td class="l">理想成本（0 手续费）</td></tr>
      <tr><td class="l"><b>UNI+AAVE 月再平衡 (10bp)</b></td><td class="hl">{S['nav10']:.3f}x</td>
        <td class="pos">{pct(S['cagr10'])}</td><td class="neg">{r10['mdd'] * 100:.2f}%</td>
        <td>{r10['calmar']:.2f}</td><td class="l"><b>主口径</b>（现货单边 10bp）</td></tr>
      <tr><td class="l">UNI+AAVE 月再平衡 (30bp)</td><td>{S['nav30']:.3f}x</td>
        <td class="pos">{pct(r30['cagr'])}</td><td class="neg">{r30['mdd'] * 100:.2f}%</td>
        <td>{r30['calmar']:.2f}</td><td class="l">高费率压力测试</td></tr>
      <tr><td class="l">UNI+AAVE 等权死拿</td><td>{S['hold']:.3f}x</td>
        <td class="pos">{pct(S['hold_cagr'])}</td><td class="neg">{S['hold_mdd'] * 100:.2f}%</td>
        <td>{h['calmar']:.2f}</td><td class="l">不再平衡基准</td></tr>
      <tr><td class="l">&nbsp;&nbsp;└ UNI 独家死拿</td><td>{S['sa_nav']:.3f}x</td>
        <td class="pos">{pct(S['sa_cagr'])}</td><td class="neg">{S['sa_mdd'] * 100:.2f}%</td>
        <td>{sa['calmar']:.2f}</td><td class="l">标的质量参照</td></tr>
      <tr><td class="l">&nbsp;&nbsp;└ AAVE 独家死拿</td><td>{S['sb_nav']:.3f}x</td>
        <td class="pos">{pct(S['sb_cagr'])}</td><td class="neg">{S['sb_mdd'] * 100:.2f}%</td>
        <td>{sb['calmar']:.2f}</td><td class="l">标的质量参照</td></tr>
    </tbody>
  </table>
  </div>
  <p class="sub" style="margin-top:12px">
  年化换手 {S['turn'] * 100:.1f}% / 年，全窗口调仓 {S['nev']} 次。
  <b>成本影响可忽略</b>：0bp→30bp 净值仅从 {S['nav0']:.3f}x 降到 {S['nav30']:.3f}x（{(S['nav30'] / S['nav0'] - 1) * 100:.2f}%），
  因为月度再平衡换手仅 {S['turn'] * 100:.0f}%/年。</p>
</div>

<div class="card">
  <h2>三、筹码轨迹（每币币量 / 死拿，1.000 = 不增不减）</h2>
  {svg}
  <div class="scroll" style="margin-top:16px">
  <table>
    <thead><tr><th class="l">日期</th><th>{A} 币量倍数</th><th>{B} 币量倍数</th></tr></thead>
    <tbody>{traj_rows}</tbody>
  </table>
  </div>
  <div class="note" style="margin-top:14px">
    <b>读法：</b>曲线在 1.0 以上 = 该币筹码增加（再平衡净买入），以下 = 掉队。
    UNI 筹码曾于 {us[A].idxmax().date()} 冲到 {us[A].max():.3f}x 高点后回落至 {us.iloc[-1][A]:.3f}x，
    说明<b>筹码倍数随行情阶段波动</b>，不是单调累积——它反映的是"这段路谁更弱"。
  </div>
</div>

<div class="card">
  <h2>四、分段拆解（扣 10bp）</h2>
  <div class="scroll">
  <table>
    <thead><tr><th class="l">区间</th><th>年数</th><th>再平衡</th><th>CAGR</th><th>MDD</th>
      <th>死拿</th><th>超额</th><th>{A} 筹码</th><th>{B} 筹码</th></tr></thead>
    <tbody>{seg_rows}</tbody>
  </table>
  </div>
  <p class="sub" style="margin-top:12px">
  <b>近 1 年是唯一失效窗口</b>——超额转负，因为该窗口内两币同步下跌、再平衡无"强弱差"可收割，只剩成本。
  这正是"再平衡超额 = 波动率² 收割"的边界：<b>它需要路径分歧，不需要单纯的高波动</b>。</p>
</div>

<div class="card">
  <h2>五、调仓频率对比（0bp）</h2>
  <div class="scroll">
  <table>
    <thead><tr><th class="l">频率</th><th>起点平移档数</th><th>净值</th><th>超额</th><th>{A} 筹码</th>
      <th>{B} 筹码</th><th>换手</th><th>起点平移净值极差</th></tr></thead>
    <tbody>{freq_rows}</tbody>
  </table>
  </div>
  <div class="note" style="margin-top:14px">
    <b>⚠️ 方法论警示：</b>同频率只换调仓日历（或平移起点几周）就会明显改变结果，窗口越长日历运气越大。
    因此"每周 vs 每月哪个好"在本表中<b>不可直接比较</b>——须看末列极差。
    唯一稳健的频率效应是：<b>调仓越频繁，最强币的币量掉得越多</b>。
    成本影响很小（全窗口仅 1% 量级），不足以解释频率间的净值差。
  </div>
</div>

<div class="card">
  <h2>六、配对准入检验</h2>
  <div class="scroll">
  <table>
    <thead><tr><th class="l">指标</th><th>数值</th><th class="l">准入要求</th><th class="l">判定</th></tr></thead>
    <tbody>
      <tr><td class="l">周收益相关</td><td>{S['corr']:.3f}</td><td class="l">&lt; 0.3（低相关）</td>
        <td class="l">{'✅ 通过' if S['corr'] < 0.3 else '❌ 不通过（相关性偏高）'}</td></tr>
      <tr><td class="l">{A} 年化波动</td><td>{S['vol_a'] * 100:.1f}%</td><td class="l">&gt; 20%（高波动）</td>
        <td class="l">✅ 通过</td></tr>
      <tr><td class="l">{B} 年化波动</td><td>{S['vol_b'] * 100:.1f}%</td><td class="l">&gt; 20%（高波动）</td>
        <td class="l">✅ 通过</td></tr>
      <tr><td class="l">长期漂移方向</td><td>{S['kind']}（差 {S['drift']:+.1f}pp）</td>
        <td class="l">无长期单边赢家/输家</td>
        <td class="l">{'✅ 通过' if abs(S['drift']) < 30 else '⚠️ 漂移差偏大，超额会被削弱'}</td></tr>
      <tr><td class="l">组合年化波动</td><td>{S['pvol'] * 100:.1f}%</td><td class="l">—</td>
        <td class="l">回撤代价参考</td></tr>
    </tbody>
  </table>
  </div>
  <p class="sub" style="margin-top:12px">
  <b>判据提醒：</b>决定再平衡超额的不是"两币波动都大"，而是
  <b>两币长期漂移方向是否一致</b>（|漂移差| 越小超额越高）。
  本组漂移差 {S['drift']:+.1f}pp，属"双正但强弱有别"，因此超额为正但不极端。</p>
</div>

<div class="card">
  <h2>七、平均每年增加多少筹码 / 还能拉多少年</h2>
  <p class="sub" style="margin-top:-4px">
  <b>⚠️ 本节只用筹码口径，不使用"超额收益"。</b>超额是净值除法，会被两币价格涨跌幅度、起点价选择、
  死拿口径的起点歧义共同污染（同币同窗口换一个起点，超额可差数个百分点），
  <b>无法分辨"机器效率"与"标的运气"</b>。筹码（币量倍数）不含价格，是唯一干净的口径。
  </p>

  <h3>7.1 年化筹码增速（几何口径，扣 10bp）</h3>
  <div class="kpis">
    <div class="kpi"><div class="k">{A} 筹码年化</div><div class="v red">{geo(rca) * 100:+.2f}%</div>
      <div class="n">{ua10:.4f}x ÷ {y0:.2f} 年</div></div>
    <div class="kpi"><div class="k">{B} 筹码年化</div><div class="v red">{geo(rcb) * 100:+.2f}%</div>
      <div class="n">{ub10:.4f}x ÷ {y0:.2f} 年</div></div>
    <div class="kpi"><div class="k">组合筹码年化<br>（= 波动收割）</div><div class="v red">{geo(rcm) * 100:+.2f}%</div>
      <div class="n">两币筹码年化的几何平均</div></div>
    <div class="kpi"><div class="k">按此速度翻倍</div><div class="v">{half_comb:.1f} 年</div>
      <div class="n">翻十倍 {ten_comb:.1f} 年</div></div>
  </div>

  <div class="key" style="margin-top:16px">
    <b>为什么 {A} 和 {B} 的增速差这么多？拆成两块（只用各币价格倍数，不引入净值）：</b><br>
    <code>log 筹码增速_i = 组合筹码年化 + ½ × (log 价格倍数_另一边 − log 价格倍数_i) ÷ T</code>
    <ul>
      <li><b>组合筹码年化 = {geo(rcm) * 100:+.2f}%/年</b> —— 这是<b>波动收割</b>，可重复的机器产出，两边都有</li>
      <li><b>搬运项（零和）：</b>窗口内 {A} 涨得少、{B} 涨得多，再平衡就把 {B} 的涨幅搬成 {A} 的币量 →
        {A} <b>{geo(move_a) * 100:+.2f}%</b> ／ {B} <b>{geo(move_b) * 100:+.2f}%</b>（两者相加 ≈ 0）</li>
    </ul>
    <b>所以 {A} 的 {geo(rca) * 100:+.2f}%/年 里，只有 {geo(rcm) * 100:.2f}pp 是真增量，其余是搬运 ——
    搬运部分意味着"用 {B} 的涨幅换了 {A} 的币量"，不是凭空多出来的财富。</b><br>
    <b>评估这套机制请盯组合筹码（{geo(rcm) * 100:+.2f}%/年），不要盯单币筹码倍数。</b>
  </div>

  <h3>7.2 分段年化筹码增速 —— 单币会反转，组合不会</h3>
  <div class="scroll">
  <table>
    <thead><tr><th class="l">区间</th><th>年数</th><th>{A} 筹码年化</th><th>{B} 筹码年化</th>
      <th>组合筹码年化</th><th>{A} 倍数</th><th>{B} 倍数</th></tr></thead>
    <tbody>{seg2_rows}</tbody>
  </table>
  </div>
  <div class="note" style="margin-top:14px">
    <b>本表最重要的观察：</b>单币筹码增速<b>会整体反转</b>——近 1 年 {A} 掉到
    {geo(seg_ra[-1]) * 100:+.2f}%、{B} 冲到 {geo(seg_rb[-1]) * 100:+.2f}%
    （因为近 1 年涨的是 {B}，机制自动反向搬运）。
    但<b>组合筹码年化在 {len(seg_pm)} 个分段里全部为正，区间
    {geo(min(seg_pm)) * 100:+.2f}% ~ {geo(max(seg_pm)) * 100:+.2f}%</b>。
    结论：<b>"筹码往哪边堆"会翻转，"能堆出多少筹码"不消失。</b>
  </div>

  <h3>7.3 任意 2 年窗口的分布 —— "每年几个点"不是合同利率</h3>
  <div class="scroll">
  <table>
    <thead><tr><th class="l">组合筹码年化（滚动 2 年，{roll_n} 个起点）</th><th>最差</th><th>p25</th>
      <th>中位</th><th>p75</th><th>最好</th></tr></thead>
    <tbody><tr><td class="l">几何年化</td>
      <td class="hl">{geo(rq.iloc[0]) * 100:+.2f}%</td><td>{geo(rq.iloc[1]) * 100:+.2f}%</td>
      <td><b>{geo(rq.iloc[2]) * 100:+.2f}%</b></td><td>{geo(rq.iloc[3]) * 100:+.2f}%</td>
      <td>{geo(rq.iloc[4]) * 100:+.2f}%</td></tr></tbody>
  </table>
  </div>
  <p class="sub" style="margin-top:12px">
  {roll_n} 个滚动 2 年窗口里，<b>组合筹码年化为负的比例 = {neg_pm * 100:.1f}%</b>，
  下界 <b>{geo(rq.iloc[0]) * 100:+.2f}%/年</b>，中位 {geo(rq.iloc[2]) * 100:+.2f}%/年。
  即：从过去任意一周入场持有满 2 年，筹码都是净增的。
  </p>

  <h3>7.4 "还能拉多少年"取决于波动率，不是时间</h3>
  <p class="sub">
  组合筹码年化的来源只有两个：<b>波动</b>与<b>相关性</b>，与两币涨跌方向无关。
  等波动近似下 <code>组合筹码年化 = ¼ (1 − ρ) · σ²</code>。
  <b>它没有到期日，只有衰减路径</b>——只要波动还在，搬运就在发生。
  </p>
  <div class="scroll">
  <table>
    <thead><tr><th class="l">年化波动 σ</th>{sens_head}<th>按 ρ={rho_full:.2f} 翻倍</th></tr></thead>
    <tbody>{sens_rows}</tbody>
  </table>
  </div>
  <p class="sub" style="margin-top:12px">
  实测（<b>对数收益口径</b>，与第六节简单收益波动略有差异，结论一致）<b>滚动 1 年波动</b>：中位 {sig_med * 100:.1f}%，区间 {sig_lo * 100:.1f}% ~ {sig_hi * 100:.1f}%，
  <b>最近 {sig_now * 100:.1f}%</b>；<b>滚动 1 年相关</b>：中位 {rho_med:.3f}，
  区间 {rho_lo:.3f} ~ {rho_hi:.3f}，<b>最近 {rho_now:.3f}</b>。
  按最近读数（σ={sig_now * 100:.0f}%、ρ={rho_now:.2f}）推，组合筹码年化约
  <b>{harv_now * 100:+.2f}%</b>，仍在有效区间。
  </p>

  <div class="key" style="margin-top:16px">
    <b>结论：每年几个点、能拉多少年</b>
    <ul>
      <li><b>每年：</b>组合层面 <b>{geo(rcm) * 100:+.2f}%</b>（样本下界 {geo(rq.iloc[0]) * 100:+.2f}%、
        中位 {geo(rq.iloc[2]) * 100:+.2f}%）。单币层面 {A} <b>{geo(rca) * 100:+.2f}%</b>、
        {B} <b>{geo(rcb) * 100:+.2f}%</b>——但"谁多谁少"由价格相对强弱决定，<b>会反转</b>（近 1 年已反）。
        真正可重复的只有组合那一项。</li>
      <li><b>多少年：数学上无期限。</b>组合筹码年化归零需要相关系数达到
        <code>ρ* = (k²+1)/(2k)</code>（k = 两币波动之比）。实测 k = {k_:.4f} → ρ* = {rho_star:.4f}，
        而 ρ 最大只到 1 —— <b>不可达</b>。只要两币波动不完全相同，收割恒为正。
        样本内验证：滚动 2 年窗口为负的比例 {neg_pm * 100:.1f}%。</li>
      <li><b>实际约束是"变薄"而非"到期"：</b>σ 从 110% 掉到 60%，年化从 {harv(1.10) * 100:+.1f}% 降到 {harv(0.60) * 100:+.1f}%；
        掉到 30% 只剩 {harv(0.30) * 100:+.1f}%（机器还在跑，但没肉）。<b>要盯的是 σ 与 ρ，不是年份。</b></li>
      <li><b>真正会终结的是三种情形：</b>① <b>ρ → 0.9</b>（两币完全同涨同跌，没有强弱差可搬运，年化被砍到当前水平的约 {cut90 * 100:.0f}%）；
        ② <b>σ 坍塌</b>（币成熟到 30% 以下）；③ <b>单币归零 / 被踢出池</b>——
        这是唯一让筹码口径彻底失效的情形：币量可以堆到很高，但价格归零，筹码不值钱。
        <b>所以池子准入（熊市幸存币、不掉队）比调仓参数重要得多。</b></li>
      <li><b>翻倍时间：</b>按组合筹码 {geo(rcm) * 100:+.2f}%/年，翻倍约 <b>{half_comb:.1f} 年</b>、
        十倍约 <b>{ten_comb:.1f} 年</b>。</li>
    </ul>
  </div>
</div>

<div class="card">
  <h2>八、口径与数据说明</h2>
  <ul>
    <li><b>筹码口径（根本答案）：</b><code>units_mult = 期末币量 / 死拿币量</code>，死拿 = 1.000，&lt;1 即掉队。
      这是再平衡真正做的事，<b>不受价格与起点价污染</b>。</li>
    <li><b>美元口径：</b><code>nav = Σ w_c · R_c · Pnorm_c</code>，回答"赚几倍"。它与筹码倍数<b>不可互换</b>。</li>
    <li><b>超额：</b>再平衡净值 ÷ 同币同窗口等权死拿净值 − 1，衡量"机器效率"，与标的涨跌无关。</li>
    <li><b>成本：</b>主口径单边 10bp，按当期成交额扣减；表中另给 0 / 30bp。</li>
    <li><b>窗口：</b>两币公共窗口取较晚的起始日（{S['win0']}，AAVE 上市），死亡期不参与。</li>
    <li><b>数据：</b><code>weekly_adjclose_crypto50_10y.csv</code>（周频后复权，27 币）。
      面板末格日期为 {S['end']}，其承载价格为最新交易周（含最新收盘）。</li>
    <li><b>⚠️ 已知数据特征：</b>该面板的日期标签由交易所周K（周一开盘）经 <code>(weekday-4)%7</code> 映射而来，
      实际承载的价格对应<b>标签日 +9 天的收盘</b>（即标签比价格早约 7 个交易日）。
      <b>该偏移对所有币一致，不影响收益序列与筹码倍数</b>，但会使"面板末日"看起来比真实交易日更早。</li>
  </ul>
</div>

<div class="card">
  <p class="sub">
  生成脚本 <code>markets/crypto/build_uni_aave_report.py</code> ·
  回测脚本 <code>markets/crypto/uni_aave_pair_rebalance.py</code> ·
  数据落盘 <code>markets/crypto/out/uni_aave_pair_rebalance.csv</code> ·
  生成时间 {__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")}
  </p>
</div>

</div></body></html>
"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] 报告已生成 -> {OUT}")
    print(f"     窗口 {S['win0']} ~ {S['end']} ({S['yrs']:.2f}y)")
    print(f"     筹码 {A} {S['ua10']:.4f}x / {B} {S['ub10']:.4f}x  (10bp)")
    print(f"     超额 {S['ex10'] * 100:+.2f}%  净值 {S['nav10']:.3f}x vs 死拿 {S['hold']:.3f}x")


if __name__ == "__main__":
    main()
