# -*- coding: utf-8 -*-
"""build_cycle_report.py - 由 run_cycle_windows.py 的结果 dict 生成报告
输出: Markdown 表 + 自包含 HTML(表格 + ON/OFF 倍数对比条形图)
"""
import os


ENGINES = ["A股", "美股", "加密"]
WIN_ORDER = ["3y", "5y", "10y"]
WIN_LABEL = {"3y": "3 年", "5y": "5 年", "10y": "10 年"}
BENCH = {"A股": "沪深300", "美股": "SPY", "加密": "BTC"}


def _get(rec, key):
    if rec and isinstance(rec, dict) and key in rec:
        return rec[key]
    return None


def _pct(x):
    return f"{x*100:.2f}%" if x is not None else "—"


def _mult(x):
    return f"{x:.3f}x" if x is not None else "—"


def _effect(off, on):
    if off and on:
        return (on - off) / off
    return None


def build_reports(results, md_path, html_path):
    # ---- 结构化行 ----
    rows = []
    for eng in ENGINES:
        for w in WIN_ORDER:
            r = results.get(eng, {}).get(w, {})
            off, on = r.get("off"), r.get("on")
            o_m, o_c, o_d = _get(off, "mult"), _get(off, "cagr_calc"), _get(off, "mdd")
            n_m, n_c, n_d = _get(on, "mult"), _get(on, "cagr_calc"), _get(on, "mdd")
            bench = _get(on, "bench") or _get(off, "bench")
            eff = _effect(o_m, n_m)
            rows.append({
                "eng": eng, "w": w, "start": r.get("start"), "end": r.get("end"),
                "yrs": r.get("actual_years"),
                "off_m": o_m, "off_c": o_c, "off_d": o_d,
                "on_m": n_m, "on_c": n_c, "on_d": n_d,
                "bench": bench, "eff": eff,
                "off_err": _get(off, "error"), "on_err": _get(on, "error"),
            })

    # ===================== Markdown =====================
    md = []
    md.append("# 三引擎 × 周期叠加层(ON/OFF) 回测报告\n")
    md.append("> 周期叠加层 = `cycles` 模块 12 层 `composite_regime`，作为统一风险 regime 信号接入 A股/美股/加密三引擎。\n")
    md.append("> 每个 (引擎, 窗口) 跑两组：基线 `cycle_overlay=False` vs `cycle_overlay=True, cycle_tilt=0.5`（进攻仓乘数 ∈ [0.5,1.5]，额度守恒、无隐性杠杆）。\n")
    md.append("")
    md.append("## 结论速览\n")
    md.append("| 引擎 | 3年 ON/OFF | 5年 ON/OFF | 10年 ON/OFF | 叠加层净效应 |")
    md.append("|---|---|---|---|---|")
    for eng in ENGINES:
        cells = []
        for w in WIN_ORDER:
            rr = next(x for x in rows if x["eng"] == eng and x["w"] == w)
            if rr["off_m"] and rr["on_m"]:
                cells.append(f"{rr['on_m']:.2f}x / {rr['off_m']:.2f}x")
            else:
                cells.append("ERR")
        effs = [_effect(rr["off_m"], rr["on_m"]) for rr in rows if rr["eng"] == eng]
        effs = [e for e in effs if e is not None]
        net = "混合" if (any(e > 0 for e in effs) and any(e < 0 for e in effs)) \
            else ("多数拖累" if sum(effs) < 0 else "多数增益")
        md.append(f"| {eng} | " + " | ".join(cells) + f" | **{net}** |")
    md.append("")

    for eng in ENGINES:
        md.append(f"## {eng}\n")
        md.append(f"基准对照：{BENCH[eng]} 买入持有。窗口终点锚定各引擎最新周。\n")
        md.append("| 窗口 | 起~止 | 实际年数 | 基线倍数 | 叠加倍数 | 叠加净效应 | 基线CAGR | 叠加CAGR | 基线MDD | 叠加MDD | 基准倍数 |")
        md.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for w in WIN_ORDER:
            rr = next(x for x in rows if x["eng"] == eng and x["w"] == w)
            if rr["off_err"] or rr["on_err"]:
                md.append(f"| {WIN_LABEL[w]} | {rr['start']}~{rr['end']} | {rr['yrs']} | "
                          f"ERROR: {rr['off_err'] or rr['on_err']} | | | | | | | |")
                continue
            md.append(
                f"| {WIN_LABEL[w]} | {rr['start']}~{rr['end']} | {rr['yrs']} | "
                f"{_mult(rr['off_m'])} | {_mult(rr['on_m'])} | {_pct(rr['eff'])} | "
                f"{_pct(rr['off_c'])} | {_pct(rr['on_c'])} | {rr['off_d']:.2f}% | {rr['on_d']:.2f}% | "
                f"{_mult(rr['bench'])} |"
            )
        md.append("")

    md.append("## 关键说明与免责\n")
    md.append("1. **叠加层默认关闭**。本报告用 `cycle_tilt=0.5`（乘数 ∈ [0.5,1.5]）。顺风加进攻 / 逆风减进攻，所有 helper 保证不产生隐性杠杆（加仓只从防御仓/现金/稳定币匀额度）。")
    md.append("2. **定性周期不随时间变化**：半导体 / AI创新 / 地缘 / 估值 4 层为 2026-08 单一静态分析师判定，对所有历史窗口施加同一常数偏移；周期维度的**时间变化完全来自 8 个量化周期**（FRED 数据 2005-01 起，完整覆盖全部 3/5/10 年窗口）。")
    md.append("3. **窗口口径提示**：A股 10 年窗口为 2016-2026（起点在 2015 股灾之后），故倍数远高于全样本权威真值 **18.185x**（2014-2026，含 2015 崩盘）；美股/加密绝对倍数随当前扩展面板而定，不直接等于历史文档真值，但 **ON vs OFF 为同一配置对照，差值即叠加层净效应**，对比有效。")
    md.append("4. **幸存者偏差**：A股静态候选池、加密现存币清单均含幸存者偏差（非未来承诺）。本报告仅测策略的压力抗性与区间表现，**不构成投资建议**；周期叠加层仅反映市场观点。")
    md_text = "\n".join(md)
    os.makedirs(os.path.dirname(md_path), exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text)

    # ===================== HTML =====================
    html = _html(results, rows)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已写入 {md_path}")
    print(f"已写入 {html_path}")


def _html(results, rows):
    # 收集所有有效倍数用于纵轴缩放
    allm = [r["off_m"] for r in rows if r["off_m"]] + [r["on_m"] for r in rows if r["on_m"]]
    vmax = max(allm) * 1.15 if allm else 1.0

    charts = ""
    for eng in ENGINES:
        charts += _bar_chart(eng, rows, vmax)

    # 表格 HTML
    tables = ""
    for eng in ENGINES:
        body = ""
        for w in WIN_ORDER:
            rr = next(x for x in rows if x["eng"] == eng and x["w"] == w)
            if rr["off_m"] and rr["on_m"]:
                eff_cls = "pos" if rr["eff"] >= 0 else "neg"
                body += (f"<tr><td>{WIN_LABEL[w]}</td><td class='mono'>{rr['start']} ~ {rr['end']}</td>"
                         f"<td>{rr['yrs']}</td>"
                         f"<td>{rr['off_m']:.3f}x</td><td>{rr['on_m']:.3f}x</td>"
                         f"<td class='{eff_cls}'>{rr['eff']*100:+.2f}%</td>"
                         f"<td>{_pct(rr['off_c'])}</td><td>{_pct(rr['on_c'])}</td>"
                         f"<td>{rr['off_d']:.2f}%</td><td>{rr['on_d']:.2f}%</td>"
                         f"<td>{_mult(rr['bench'])}</td></tr>")
            else:
                body += (f"<tr><td>{WIN_LABEL[w]}</td><td colspan=9 class='err'>"
                         f"ERROR: {rr['off_err'] or rr['on_err']}</td></tr>")
        tables += f"""
        <div class="card">
          <h2>{eng} <span class="sub">基准对照：{BENCH[eng]} 买入持有</span></h2>
          <table>
            <thead><tr><th>窗口</th><th>起~止</th><th>实际年数</th><th>基线倍数</th><th>叠加倍数</th>
            <th>叠加净效应</th><th>基线CAGR</th><th>叠加CAGR</th><th>基线MDD</th><th>叠加MDD</th><th>基准倍数</th></tr></thead>
            <tbody>{body}</tbody>
          </table>
          {_bar_chart(eng, rows, vmax)}
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>三引擎 × 周期叠加层 回测报告</title>
<style>
  :root{{--bg:#f6f7f9;--card:#fff;--ink:#1f2733;--muted:#6b7686;--line:#e4e8ee;
         --off:#9aa7b8;--on:#2f6df0;--pos:#1f9d55;--neg:#d6453d;}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);
        font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.5}}
  .wrap{{max-width:1080px;margin:0 auto;padding:28px 20px 60px}}
  h1{{font-size:24px;margin:0 0 4px}}
  .lede{{color:var(--muted);font-size:14px;margin:0 0 22px}}
  .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;
         padding:18px 20px;margin-bottom:22px;box-shadow:0 1px 3px rgba(20,30,50,.04)}}
  h2{{font-size:18px;margin:0 0 14px}}
  .sub{{font-size:13px;color:var(--muted);font-weight:400;margin-left:8px}}
  table{{width:100%;border-collapse:collapse;font-size:13.5px}}
  th,td{{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line)}}
  th:first-child,td:first-child{{text-align:left}}
  th{{color:var(--muted);font-weight:600;background:#fafbfc}}
  .mono{{font-variant-numeric:tabular-nums;color:var(--muted);font-size:12.5px}}
  .pos{{color:var(--pos);font-weight:600}}
  .neg{{color:var(--neg);font-weight:600}}
  .err{{color:var(--neg)}}
  .chart{{margin-top:14px}}
  .note{{font-size:13px;color:var(--muted);background:#fbfcfe;border:1px solid var(--line);
         border-radius:10px;padding:14px 16px}}
  .note ol{{margin:8px 0 0;padding-left:20px}}
  .note li{{margin:6px 0}}
  .tag{{display:inline-block;padding:2px 8px;border-radius:6px;font-size:12px;font-weight:600}}
  .tag.off{{background:#eef1f5;color:#56627a}} .tag.on{{background:#e7f0ff;color:#2f6df0}}
</style></head>
<body><div class="wrap">
  <h1>三引擎 × 周期叠加层（ON/OFF）回测报告</h1>
  <p class="lede">12 层 <code>composite_regime</code> 作为统一风险 regime 信号接入 A股 / 美股 / 加密三引擎；
     每个（引擎 × 窗口）对比 <span class="tag off">基线 cycle_overlay=False</span> 与
     <span class="tag on">叠加 cycle_overlay=True, tilt=0.5</span>（乘数∈[0.5,1.5]，无隐性杠杆）。</p>
  {tables}
  <div class="note">
    <strong>关键说明与免责</strong>
    <ol>
      <li><b>叠加层默认关闭</b>。本报告用 <code>cycle_tilt=0.5</code>（乘数∈[0.5,1.5]）：顺风加进攻/逆风减进攻，所有 helper 保证不产生隐性杠杆（加仓只从防御仓/现金/稳定币匀额度）。</li>
      <li><b>定性周期不随时间变化</b>：半导体 / AI 创新 / 地缘 / 估值 4 层为 2026-08 单一静态分析师判定，对所有历史窗口施加同一常数偏移；周期维度的<b>时间变化完全来自 8 个量化周期</b>（FRED 数据 2005-01 起，完整覆盖全部窗口）。</li>
      <li><b>窗口口径提示</b>：A股 10 年窗口为 2016-2026（起点在 2015 股灾之后），故倍数远高于全样本权威真值 <b>18.185x</b>（2014-2026，含 2015 崩盘）；美股/加密绝对倍数随当前扩展面板而定，不直接等于历史文档真值，但 <b>ON vs OFF 为同一配置对照，差值即叠加层净效应</b>，对比有效。</li>
      <li><b>幸存者偏差</b>：A股静态候选池、加密现存币清单均含幸存者偏差（非未来承诺）。本报告仅测策略压力抗性与区间表现，<b>不构成投资建议</b>；周期叠加层仅反映市场观点。</li>
    </ol>
  </div>
</div></body></html>"""


def _bar_chart(eng, rows, vmax):
    w = next(x for x in rows if x["eng"] == eng)
    # 画布
    W, H = 460, 180
    pad_l, pad_b, pad_t = 36, 28, 14
    plot_w = W - pad_l - 10
    plot_h = H - pad_b - pad_t
    gw = plot_w / 3.0
    bw = 26
    y_scale = plot_h / vmax

    svg = [f'<svg class="chart" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'role="img" aria-label="{eng} 倍数对比">']
    # 轴线 + 网格
    for g in range(0, 5):
        yy = pad_t + plot_h - (plot_h * g / 4.0)
        val = vmax * g / 4.0
        svg.append(f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{W-10}" y2="{yy:.1f}" stroke="#eef1f5"/>')
        svg.append(f'<text x="{pad_l-4}" y="{yy+3:.1f}" text-anchor="end" font-size="9" fill="#9aa7b8">{val:.0f}x</text>')
    svg.append(f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t+plot_h}" stroke="#cdd5e0"/>')

    for i, wlab in enumerate(WIN_ORDER):
        rr = next(x for x in rows if x["eng"] == eng and x["w"] == wlab)
        cx = pad_l + gw * i + gw / 2
        # OFF
        if rr["off_m"]:
            h1 = rr["off_m"] * y_scale
            svg.append(f'<rect x="{cx-bw-3:.1f}" y="{pad_t+plot_h-h1:.1f}" width="{bw}" height="{h1:.1f}" fill="#9aa7b8"><title>基线 {rr["off_m"]:.2f}x</title></rect>')
            svg.append(f'<text x="{cx-bw/2-3:.1f}" y="{pad_t+plot_h-h1-3:.1f}" text-anchor="middle" font-size="9" fill="#56627a">{rr["off_m"]:.1f}x</text>')
        # ON
        if rr["on_m"]:
            h2 = rr["on_m"] * y_scale
            svg.append(f'<rect x="{cx+3:.1f}" y="{pad_t+plot_h-h2:.1f}" width="{bw}" height="{h2:.1f}" fill="#2f6df0"><title>叠加 {rr["on_m"]:.2f}x</title></rect>')
            svg.append(f'<text x="{cx+bw/2+3:.1f}" y="{pad_t+plot_h-h2-3:.1f}" text-anchor="middle" font-size="9" fill="#2f6df0">{rr["on_m"]:.1f}x</text>')
        svg.append(f'<text x="{cx:.1f}" y="{H-10}" text-anchor="middle" font-size="11" fill="#1f2733">{wlab}</text>')
    svg.append('</svg>')
    return (f'<div class="chart">{ "".join(svg) }'
            f'<div style="font-size:11px;color:#9aa7b8;margin-top:2px">'
            f'<span style="color:#9aa7b8">■</span> 基线 &nbsp; '
            f'<span style="color:#2f6df0">■</span> 叠加(ON)</div></div>')
