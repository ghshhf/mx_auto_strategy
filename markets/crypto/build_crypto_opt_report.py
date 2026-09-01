# -*- coding: utf-8 -*-
"""
build_crypto_opt_report.py - 由 cycle_crypto_asym.json 生成加密专属优化报告
输出: docs/crypto_overlay_report.md + cycle_crypto_overlay_report.html
"""
import os, json

ROOT = os.path.dirname(os.path.abspath(__file__))   # markets/crypto/
REPO = os.path.dirname(os.path.dirname(ROOT))                         # 仓库根
D = json.load(open(os.path.join(ROOT, "data", "cycle_crypto_asym.json"), encoding="utf-8"))
scan, best, oos = D["scan"], D["best"], D["oos"]

lines = []
lines.append("# 加密叠加层机制优化报告 (v6.23)\n")
lines.append("> 仅针对加密引擎。上一轮 walk-forward 揭示加密叠加层是「收益放大器 + 回撤放大器」"
             "(OOS 倍数 +22% t=5.4, 但 MDD 显著恶化 t=-5.98)。本工作验证**是否存在机制能消除回撤恶化**。\n")

lines.append("## 1. 方法\n")
lines.append("- 真实 OFF 基线(完全关闭叠加层)按窗口缓存, 不与 ON 混淆。")
lines.append("- 机制网格: 对称(tilt∈{0.3,0.5}) / 下行保护型(regime≥0 用 up, <0 用 down, down>up) / 纯保险型(up=0)。")
lines.append("- 指标: 3/5/10y ON/OFF 倍数比; 几何均值倍数比; 平均 MDD 变化(pp, >0=恶化)。")
lines.append("- 最优定义: 在 `平均MDD恶化 ≤ 2pp` 约束内最大化几何倍数比; 无满足则取 MDD 恶化最小。")
lines.append("- 对最优机制跑 walk-forward OOS(训练3y/测试1y 滚动, 2020-08 起), 输出几何倍数比 + paired t(倍数/MDD)。\n")

lines.append("## 2. 机制扫描结果 (in-sample)\n")
lines.append("| 机制 | 几何倍数比 | 平均MDD变化 | 3y | 5y | 10y |")
lines.append("|---|---|---|---|---|---|")
order = ["对称 tilt=0.3 (当前默认)", "对称 tilt=0.5 (旧默认)"]
order += [n for n in scan if n.startswith("下行保护")]
order += [n for n in scan if n.startswith("纯保险")]
for n in order:
    r = scan[n]
    w = r["windows"]
    lines.append(f"| {n} | {r['geo_ratio']:+.4f} | {r['mean_mdd_diff']:+.2f}pp | "
                 f"{w['3y']['ratio']:+.3f} | {w['5y']['ratio']:+.3f} | {w['10y']['ratio']:+.3f} |")

lines.append(f"\n**in-sample 最优**: `{best}` (依据: {D['best_basis']}) — "
             f"geo={scan[best]['geo_ratio']:+.4f}, 平均MDD={scan[best]['mean_mdd_diff']:+.2f}pp\n")

lines.append("## 3. 样本外 walk-forward 验证 (最优机制)\n")
lines.append(f"- 测试期数: {oos['samples']}")
lines.append(f"- 几何倍数比: **{oos['geo_ratio']:+.4f}**")
lines.append(f"- t(倍数): **{oos['t_mult']}** (≥2 = 收益增益显著)")
lines.append(f"- t(MDD): **{oos['t_mdd']}** (显著为正 = 回撤被显著放大)\n")
lines.append("| 测试期起点 | 倍数比 | MDD变化 |")
lines.append("|---|---|---|")
test_starts = ["2020-08-14", "2021-08-14", "2022-08-14", "2023-08-14", "2024-08-14"]
for s, (r, d) in zip(test_starts, oos["detail"]):
    lines.append(f"| {s} | {r:+.3f} | {d:+.2f}pp |")

lines.append("\n## 4. 结论 (诚实)\n")
lines.append("1. **没有机制能消除回撤恶化。** 对称/下行保护/纯保险三类在所有窗口都显著放大 MDD"
             "(in-sample +4~+11pp; OOS t(MDD)=+6.4)。")
lines.append("2. **纯保险型(顺风不加仓)牺牲全部收益**: 10y 倍数比 < 1.0 (即负增益), 因加密增益主要来自"
             "「宏观宽松期顺趋势加仓」而非「逆风减仓躲崩盘」。")
lines.append("3. **这 4 个宏观周期是顺周期动量确认, 不是逆周期保险**: 它们只确认趋势方向, 但加密自身崩盘"
             "幅度(-80%)远超慢变量周期能预测的减仓幅度(下限砍半到0.5), 减仓根本躲不过崩盘。")
lines.append("4. **加密叠加层 = 收益/回撤 trade-off 旋钮, 非风控装置。** 推翻此前「崩盘保险」叙事。")
lines.append("5. **实践建议**: 想要更高收益且能承受更大回撤 -> 开启(tilt 0.3~0.5); 想要回撤控制 -> "
             "`cycle_overlay=False` 回到无叠加基线。引擎默认 `cycle_overlay=False`, 故默认不启用。\n")

lines.append("---\n*数据: `cycle_crypto_asym.json` · 脚本: `optimize_crypto_asym.py` · 生成于 2026-08-11*")

md = "\n".join(lines)
with open(os.path.join(REPO, "docs", "crypto_overlay_report.md"), "w", encoding="utf-8") as f:
    f.write(md)

# ---- 简单 HTML ----
rows = ""
for n in order:
    r = scan[n]; w = r["windows"]
    cls = " class='best'" if n == best else ""
    rows += (f"<tr{cls}><td>{n}</td><td>{r['geo_ratio']:+.4f}</td><td>{r['mean_mdd_diff']:+.2f}pp</td>"
             f"<td>{w['3y']['ratio']:+.3f}</td><td>{w['5y']['ratio']:+.3f}</td><td>{w['10y']['ratio']:+.3f}</td></tr>")
oos_rows = ""
for s, (r, d) in zip(test_starts, oos["detail"]):
    oos_rows += f"<tr><td>{s}</td><td>{r:+.3f}</td><td>{d:+.2f}pp</td></tr>"

html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>加密叠加层机制优化</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,'Microsoft YaHei',sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#1a1a1a;line-height:1.6}}
h1{{font-size:22px;border-bottom:2px solid #2563eb;padding-bottom:8px}}
h2{{font-size:17px;margin-top:28px;color:#1e3a8a}}
table{{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}}
th,td{{border:1px solid #ddd;padding:6px 9px;text-align:center}}
th{{background:#f1f5f9}}
tr.best{{background:#fff7ed;font-weight:600}}
.neg{{color:#dc2626}}.pos{{color:#16a34a}}
.note{{background:#fef3c7;border-left:4px solid #f59e0b;padding:10px 14px;margin:14px 0;border-radius:4px}}
</style></head><body>
<h1>加密叠加层机制优化报告 (v6.23)</h1>
<p>仅针对加密引擎。验证<strong>是否存在机制能消除回撤恶化</strong>。结论: <span class="neg">无</span>——加密叠加层是顺周期收益放大器, 非保险。</p>
<h2>1. 机制扫描 (in-sample)</h2>
<table><thead><tr><th>机制</th><th>几何倍数比</th><th>平均MDD变化</th><th>3y</th><th>5y</th><th>10y</th></tr></thead><tbody>{rows}</tbody></table>
<p>in-sample 最优: <code>{best}</code> ({D['best_basis']})</p>
<h2>2. 样本外 walk-forward (最优机制)</h2>
<table><thead><tr><th>测试期起点</th><th>倍数比</th><th>MDD变化</th></tr></thead><tbody>{oos_rows}</tbody></table>
<p>几何倍数比 <span class="pos">{oos['geo_ratio']:+.4f}</span> · t(倍数) <span class="pos">{oos['t_mult']}</span> · t(MDD) <span class="neg">{oos['t_mdd']}</span></p>
<div class="note"><strong>诚实结论:</strong> 没有机制能消除回撤恶化(纯保险型虽减回撤却牺牲全部收益, 10y 倍数比&lt;1)。
这 4 个宏观周期对加密是<strong>顺周期动量确认</strong>, 不是逆周期保险。加密叠加层是一个<strong>收益/回撤 trade-off 旋钮</strong>, 不是风控装置。
想要更高收益→开启(tilt 0.3~0.5); 想要回撤控制→ <code>cycle_overlay=False</code>。</div>
</body></html>"""
_REPORT_DIR = os.path.join(REPO, "docs", "reports")
os.makedirs(_REPORT_DIR, exist_ok=True)
with open(os.path.join(_REPORT_DIR, "cycle_crypto_overlay_report.html"), "w", encoding="utf-8") as f:
    f.write(html)

print("已生成 docs/crypto_overlay_report.md + docs/reports/cycle_crypto_overlay_report.html")
