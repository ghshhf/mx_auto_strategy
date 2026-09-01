# -*- coding: utf-8 -*-
"""
build_cycle_weights_report.py - 生成逐引擎精选周期权重报告
读取 cycle_weights_experiment.json + cycle_weights_verify.json
"""
import os, json

ROOT = os.path.dirname(os.path.abspath(__file__))
EXP = json.load(open(os.path.join(ROOT, "cycle_weights_experiment.json"), encoding="utf-8"))
VFY = json.load(open(os.path.join(ROOT, "cycle_weights_verify.json"), encoding="utf-8"))
from cycles import specs as SP

CYCLE_NAME = {c["id"]: c["name"] for c in SP.CYCLES}
ENG_NAME = {"A股": "ashare", "美股": "us", "加密": "crypto"}

md = []
md.append("# 逐引擎精选周期权重 · 回测报告\n")
md.append("> 方法论: 把 12 个金融周期**逐个单独**接入三引擎(tilt=0.3), 测 ON/OFF 倍数比; ")
md.append("> 取三窗口几何均值 >1.0 的周期入选, 按有效性强弱赋相对权重(权重越高 -> 合成 regime 越主导)。\n")

# ---- 单周期有效性矩阵 ----
md.append("## 1. 单周期有效性矩阵 (ON/OFF 倍数比, tilt=0.3)\n")
md.append("大于 1.0 = 该周期单独接入对该引擎**有增益**; 小于 1.0 = 拖累。\n")
md.append("| 周期 | " + " | ".join(f"{e}" for e in ("A股", "美股", "加密")) + " |")
md.append("|" + "---|" * 4)
for cid in [c["id"] for c in SP.CYCLES]:
    cells = []
    for eng in ("A股", "美股", "加密"):
        g = EXP["geo_ratio"][eng].get(cid)
        cells.append(f"{g:+.4f}" if g is not None else "—")
    md.append(f"| {CYCLE_NAME[cid]}({cid}) | " + " | ".join(cells) + " |")
md.append("")

# ---- 精选结果 ----
md.append("## 2. 逐引擎精选周期 + 权重\n")
for eng in ("A股", "美股", "加密"):
    key = ENG_NAME[eng]
    w = SP.ENGINE_CYCLE_WEIGHTS.get(key, {})
    if w:
        items = ", ".join(f"{CYCLE_NAME[k]}({k})×{v}" for k, v in w.items())
    else:
        items = "（空 -> 叠加层中性, 建议保持关闭）"
    md.append(f"- **{eng}** (key=`{key}`): 精选 = {items}; 推荐 tilt = **{SP.ENGINE_TILT[key]}**")
md.append("")

# ---- 最终验证 ----
md.append("## 3. 最终效果: ON(精选权重) vs OFF 基线\n")
md.append("| 引擎 | 窗口 | OFF倍数 | ON倍数 | 倍数比 | OFF_MDD | ON_MDD |")
md.append("|---|---|---|---|---|---|---|")
for eng in ("A股", "美股", "加密"):
    for wname in ("3y", "5y", "10y"):
        r = VFY[eng][wname]
        off, on, ratio = r["off"], r["on"], r["ratio"]
        md.append(f"| {eng} | {wname} | {off['mult']:.3f} | {on['mult']:.3f} | "
                  f"**{ratio:+.4f}** | {off['mdd']:.1f}% | {on['mdd']:.1f}% |")
md.append("")

# ---- 解读 ----
md.append("## 4. 解读与诚实口径\n")
md.append("- **A股**: 入选 `credit`(信贷)+`commodity`(大宗商品)。fed_rate 对 A股**无效**(ratio<1, ")
md.append("  中国股受美联储利率传导弱), 但信贷利差/油价这类宏观周期确实影响 A股 -> 印证\"宏观类周期有用, ")
md.append("  只是走的不是美联储利率通道\"。精选后 tilt=0.3 在 3y/5y 带来 +9~11% 增益, 5y 回撤还略改善; ")
md.append("  10y 增益较小(因 10y 窗口含 2015 股灾, 周期信号难救)。**代价**: 高 tilt 会加深回撤, 故 A股 tilt 取 0.3 而非 0.5。\n")
md.append("- **美股**: 12 周期几何均值**全部 <1.0**。其引擎自带的死亡交叉→现金、波动率目标、主题解相关已吃掉 ")
md.append("  周期能加的东西 -> 叠加层对该引擎**无净增益**。精选集置空, 开启即中性(乘数1.0, 安全无副作用), ")
md.append("  **实证建议 美股保持 `cycle_overlay=False`**。\n")
md.append("- **加密**: 入选 `liquidity`(流动性)+`housing`+`commodity`+`fed_rate`, 以 liquidity 为主 ")
md.append("  (10y 单周期 ratio 1.99)。机制是 2022 寒冬前 regime 转逆风 -> 减仓保住本金, 吃后续反弹。")
md.append("  精选后 tilt=0.5 实现**增益+降回撤双击**(各窗口 MDD 改善 6–7pp, 10y 倍数 +57.5%)。\n")
md.append("- **总判断**: 不是\"周期加多了\", 而是此前等权把所有周期捆成一个标量、用偏重 tilt 全开, ")
md.append("  在强牛市里把上行砍掉。改为\"按引擎分别筛选有用周期 + 按权重作用 + 克制 tilt\"后, ")
md.append("  A股/加密真正用上了周期, 美股确认用不上也不受伤。\n")
md.append("> 免责声明: 周期叠加层仅反映市场观点, 非投资建议; 含幸存者偏差, 历史有效不代表未来。")

md_text = "\n".join(md)
os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
with open(os.path.join(ROOT, "docs", "cycle_weights_report.md"), "w", encoding="utf-8") as f:
    f.write(md_text)

# ---- HTML ----
html = ["<html><head><meta charset='utf-8'><style>",
        "body{font-family:-apple-system,'Segoe UI',sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#1a1a1a;line-height:1.6}",
        "h1{font-size:22px}h2{font-size:17px;margin-top:28px;border-left:4px solid #2b6cb0;padding-left:10px}",
        "table{border-collapse:collapse;width:100%;font-size:13px;margin:10px 0}",
        "th,td{border:1px solid #ddd;padding:6px 8px;text-align:center}",
        "th{background:#f4f6f8}.pos{color:#c0392b;font-weight:600}.neg{color:#1e824c;font-weight:600}",
        ".note{background:#f8f9fa;border:1px solid #e2e8f0;padding:12px 14px;border-radius:6px;font-size:13px}",
        "</style></head><body>"]
html.append("<h1>逐引擎精选周期权重 · 回测报告</h1>")
html.append("<p style='color:#666'>方法论: 12 周期逐个单独接入三引擎(tilt=0.3)测 ON/OFF 倍数比; 取三窗口几何均值&gt;1.0 入选, 按有效性强弱赋相对权重(权重越高→合成 regime 越主导)。</p>")

html.append("<h2>1. 单周期有效性矩阵 (ON/OFF 倍数比, tilt=0.3)</h2>")
html.append("<p style='font-size:13px'>大于 1.0 = 该周期单独接入对该引擎有增益; 小于 1.0 = 拖累。</p>")
html.append("<table><tr><th>周期</th><th>A股</th><th>美股</th><th>加密</th></tr>")
for cid in [c["id"] for c in SP.CYCLES]:
    cells = []
    for eng in ("A股", "美股", "加密"):
        g = EXP["geo_ratio"][eng].get(cid)
        if g is None:
            cells.append("<td>—</td>")
        else:
            cls = "pos" if g > 1.0 else "neg"
            cells.append(f"<td class='{cls}'>{g:+.4f}</td>")
    html.append(f"<tr><td style='text-align:left'>{CYCLE_NAME[cid]} <span style='color:#999'>({cid})</span></td>" + "".join(cells) + "</tr>")
html.append("</table>")

html.append("<h2>2. 逐引擎精选周期 + 权重</h2><ul style='font-size:13px'>")
for eng in ("A股", "美股", "加密"):
    key = ENG_NAME[eng]
    w = SP.ENGINE_CYCLE_WEIGHTS.get(key, {})
    if w:
        items = ", ".join(f"{CYCLE_NAME[k]}×{v}" for k, v in w.items())
    else:
        items = "（空 → 叠加层中性，建议保持关闭）"
    html.append(f"<li><b>{eng}</b> (<code>{key}</code>): {items}；推荐 tilt = <b>{SP.ENGINE_TILT[key]}</b></li>")
html.append("</ul>")

html.append("<h2>3. 最终效果: ON(精选权重) vs OFF 基线</h2>")
html.append("<table><tr><th>引擎</th><th>窗口</th><th>OFF倍数</th><th>ON倍数</th><th>倍数比</th><th>OFF_MDD</th><th>ON_MDD</th></tr>")
for eng in ("A股", "美股", "加密"):
    for wname in ("3y", "5y", "10y"):
        r = VFY[eng][wname]; off, on, ratio = r["off"], r["on"], r["ratio"]
        cls = "pos" if ratio and ratio >= 1.0 else "neg"
        html.append(f"<tr><td>{eng}</td><td>{wname}</td><td>{off['mult']:.3f}</td><td>{on['mult']:.3f}</td>"
                    f"<td class='{cls}'>{ratio:+.4f}</td><td>{off['mdd']:.1f}%</td><td>{on['mdd']:.1f}%</td></tr>")
html.append("</table>")

html.append("<h2>4. 解读</h2><div class='note'>")
html.append("<p><b>A股</b>: 入选 credit+commodity。fed_rate 对 A股无效(中国股受美联储利率传导弱), 但信贷利差/油价这类宏观周期确实影响 A股。精选后 tilt=0.3 在 3y/5y 带来 +9~11% 增益, 5y 回撤还略改善; 高 tilt 会加深回撤故取 0.3。</p>")
html.append("<p><b>美股</b>: 12 周期几何均值全部 &lt;1.0。其死亡交叉→现金、波动率目标、主题解相关已吃掉周期能加的东西。精选集置空, 开启即中性(安全无副作用), 建议保持关闭。</p>")
html.append("<p><b>加密</b>: 入选 liquidity+housing+commodity+fed_rate(以 liquidity 为主, 10y 单周期 ratio 1.99)。机制是 2022 寒冬前 regime 转逆风减仓保本金。tilt=0.5 实现增益+降回撤双击(各窗口 MDD 改善 6–7pp, 10y 倍数 +57.5%)。</p>")
html.append("<p><b>总判断</b>: 不是\"周期加多了\", 而是此前等权全开+偏重 tilt 在强牛市砍了上行。改为按引擎筛选+按权重作用+克制 tilt 后, A股/加密真正用上周期, 美股用不上也不受伤。</p>")
html.append("<p style='color:#999'>免责声明: 周期叠加层仅反映市场观点, 非投资建议; 含幸存者偏差。</p>")
html.append("</div></body></html>")
with open(os.path.join(ROOT, "cycle_weights_report.html"), "w", encoding="utf-8") as f:
    f.write("".join(html))

print("已生成 docs/cycle_weights_report.md 与 cycle_weights_report.html")
