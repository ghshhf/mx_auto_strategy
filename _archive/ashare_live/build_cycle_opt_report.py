# -*- coding: utf-8 -*-
"""build_cycle_opt_report.py - 由 cycle_opt_tilt.json 生成可读报告 + 自包含 HTML。"""
import os, json, math


def build_opt_report(out, md_path, html_path):
    sweep = out["sweep"]
    off = out["off_cache"]
    abl = out["ablation"]
    grid = out["tilt_grid"]
    atilt = out["ablation_tilt"]
    opt = out["opt_tilt"]
    engines = ["A股", "美股", "加密"]
    wins = ["3y", "5y", "10y"]

    # ---------- Markdown ----------
    L = []
    L.append("# 周期叠加层参数优化报告 (v6.21)\n")
    L.append("> 免责声明：周期叠加层仅反映市场观点，非投资建议。回测含幸存者偏差与历史数据局限。\n")

    L.append("## 一、核心结论\n")
    L.append("- 当前默认 `cycle_tilt=0.5`（乘数∈[0.5,1.5]）**确实偏重**：在强趋势上行市里，")
    L.append("  composite_regime 多为轻微偏空/中性，大摆动会一路砍掉进攻仓的上行收益，")
    L.append("  而对回撤帮助有限。这正是 A股/美股被拖累、加密独善其身的原因。\n")
    L.append("- **推荐默认力度下调**：见下表各引擎最优 tilt。\n")
    for eng in engines:
        L.append(f"  - **{eng}**：最优 tilt ≈ `{opt[eng]}`")
    L.append("")

    L.append("## 二、tilt 敏感度扫描（ON/OFF 倍数比率，>1 表示叠加层净增益）\n")
    for eng in engines:
        L.append(f"### {eng}\n")
        L.append("| 窗口 | OFF倍数 | " + " | ".join(f"t={t}" for t in grid) + " |")
        L.append("|" + "---|" * (2 + len(grid)))
        for w in wins:
            row = sweep[eng][w]
            offm = row["off"].get("mult")
            cells = []
            for t in grid:
                rec = row["on"].get(t, {})
                r = rec.get("ratio")
                cells.append(f"{r:.3f}" if r is not None else "—")
            L.append(f"| {w} | {offm:.3f}x | " + " | ".join(cells) + " |")
        L.append("")

    L.append("## 三、单周期留一法消融（tilt=%s 下，去掉该周期后的倍数 vs 全12周期）\n" % atilt)
    L.append("> 含义：去掉后倍数**上升**→该周期净负贡献（在帮倒忙）；下降→净正贡献（应保留）。\n")
    for eng in engines:
        L.append(f"### {eng}\n")
        L.append("| 窗口 | " + " | ".join(c["id"] for c in __import__("cycles.specs", fromlist=["CYCLES"]).CYCLES) + " |")
        L.append("|" + "---|" * (1 + 12))
        for w in wins:
            full = sweep[eng][w]["on"].get(atilt, {}).get("mult")
            ab = abl[eng][w]
            cells = []
            for c in __import__("cycles.specs", fromlist=["CYCLES"]).CYCLES:
                cid = c["id"]
                m = ab.get(cid)
                if m is None or full in (None, 0):
                    cells.append("—")
                else:
                    d = (m - full) / full * 100
                    cells.append(f"{d:+.1f}%")
            L.append(f"| {w} | " + " | ".join(cells) + " |")
        L.append("")

    md = "\n".join(L)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    # ---------- HTML ----------
    html = _html(out)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    return md


def _html(out):
    sweep = out["sweep"]; grid = out["tilt_grid"]; opt = out["opt_tilt"]
    engines = ["A股", "美股", "加密"]; wins = ["3y", "5y", "10y"]
    specs = __import__("cycles.specs", fromlist=["CYCLES"]).CYCLES
    cyc_ids = [c["id"] for c in specs]

    def color(r):
        if r is None: return "#999"
        if r >= 1.0: return "#1a7f37"   # 绿=增益
        if r >= 0.97: return "#b08900"  # 黄=轻微拖累
        return "#c0392b"                 # 红=明显拖累

    parts = []
    parts.append("""<html><head><meta charset="utf-8"><style>
    body{font-family:-apple-system,Segoe UI,'Microsoft YaHei',sans-serif;max-width:1080px;margin:24px auto;padding:0 16px;color:#1a1a1a;background:#fff}
    h1{font-size:22px}h2{font-size:17px;margin-top:28px;border-left:4px solid #2d6cdf;padding-left:8px}
    table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}
    th,td{border:1px solid #e0e0e0;padding:5px 8px;text-align:center}
    th{background:#f5f7fa;font-weight:600}
    td.eng{text-align:left;font-weight:600;background:#fafbfc}
    .badge{display:inline-block;padding:2px 8px;border-radius:10px;color:#fff;font-size:12px}
    .note{color:#666;font-size:12px}.dis{color:#999;font-size:11px;margin-top:24px}
    </style></head><body>""")
    parts.append("<h1>周期叠加层参数优化报告</h1>")
    parts.append("<div class='note'>免责声明：周期叠加层仅反映市场观点，非投资建议。回测含幸存者偏差与历史数据局限。</div>")

    parts.append("<h2>一、核心结论</h2><ul>")
    for eng in engines:
        parts.append(f"<li><b>{eng}</b> 最优 tilt ≈ <span class='badge' style='background:#2d6cdf'>{opt[eng]}</span> "
                     f"（乘数范围 [{(1-opt[eng]):.2f},{(1+opt[eng]):.2f}]）</li>")
    parts.append("</ul><div class='note'>当前默认 0.5（乘数[0.5,1.5]）偏重：强趋势市里 composite_regime 多偏空/中性，"
                 "大摆动砍掉上行收益而对回撤帮助有限，故 A股/美股被拖累、加密独善。</div>")

    for eng in engines:
        parts.append(f"<h2>二、{eng} — tilt 敏感度扫描（ON/OFF 倍数比率，&gt;1=增益）</h2>")
        parts.append("<table><tr><th>窗口</th><th>OFF</th>" +
                     "".join(f"<th>t={t}</th>" for t in grid) + "</tr>")
        for w in wins:
            row = sweep[eng][w]; offm = row["off"].get("mult")
            cells = ""
            for t in grid:
                r = row["on"].get(t, {}).get("ratio")
                txt = f"{r:.3f}" if r is not None else "—"
                cells += f"<td style='color:{color(r)};font-weight:600'>{txt}</td>"
            parts.append(f"<tr><td class='eng'>{w}</td><td>{offm:.2f}x</td>{cells}</tr>")
        parts.append("</table>")

    parts.append(f"<h2>三、单周期留一法消融（tilt={out['ablation_tilt']}，去掉该周期后的倍数变化%）</h2>")
    parts.append("<div class='note'>正数=去掉后更好（该周期在帮倒忙，净负贡献）；负数=去掉后变差（应保留）。</div>")
    for eng in engines:
        parts.append(f"<h3 style='margin:14px 0 4px'>{eng}</h3>")
        parts.append("<table><tr><th>窗口</th>" + "".join(f"<th>{cid}</th>" for cid in cyc_ids) + "</tr>")
        for w in wins:
            full = sweep[eng][w]["on"].get(out["ablation_tilt"], {}).get("mult")
            ab = out["ablation"][eng][w]
            cells = ""
            for cid in cyc_ids:
                m = ab.get(cid)
                if m is None or full in (None, 0):
                    cells += "<td>—</td>"
                else:
                    d = (m - full) / full * 100
                    c = "#1a7f37" if d > 0 else "#c0392b"
                    cells += f"<td style='color:{c}'>{d:+.1f}</td>"
            parts.append(f"<tr><td class='eng'>{w}</td>{cells}</tr>")
        parts.append("</table>")

    parts.append("<div class='dis'>生成：optimize_cycle_params.py · 数据口径同 cycle_windows_report。</div>")
    parts.append("</body></html>")
    return "".join(parts)
