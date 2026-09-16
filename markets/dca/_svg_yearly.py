# -*- coding: utf-8 -*-
"""由 yearly_result.json 生成「逐年盈亏」SVG 片段（贴进 show_widget）。"""
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
j = json.load(open(os.path.join(ROOT, "out", "yearly_result.json"), encoding="utf-8"))
rows = j["p1"]["rows"]

Y0, SCALE, W, GAP = 225.0, 100.0 / 950000.0, 13.0, 3.0
X0 = 36.0


def cx(age):
    return X0 + (age - 22) * (W + GAP) + W / 2


bars, ticks, marks = [], [], []
for i, r in enumerate(rows):
    x = X0 + i * (W + GAP)
    v = r["pnl"] * SCALE
    if v >= 0:
        y, h, fill = Y0 - v, v, "#dc2626"
    else:
        y, h, fill = Y0, -v, "#16a34a"
    bars.append(f'  <rect x="{x:.1f}" y="{y:.1f}" width="{W:.0f}" height="{max(h,0.6):.2f}" fill="{fill}" opacity="0.88"/>')

for a in range(22, 61, 5):
    ticks.append(f'  <text x="{cx(a):.1f}" y="343" font-size="10" fill="#94a3b8" text-anchor="middle">{a}岁</text>')

marks.append(f'  <line x1="{cx(25):.1f}" y1="188" x2="{cx(25):.1f}" y2="219" stroke="#94a3b8" stroke-width="0.8"/>')
marks.append(f'  <circle cx="{cx(25):.1f}" cy="{Y0-1.9:.1f}" r="3" fill="#0f172a"/>')
marks.append(f'  <text x="{cx(25)+4:.1f}" y="184" font-size="10.5" fill="#334155" text-anchor="middle">25 岁 · 一年赚的首次超过一年投的</text>')
marks.append(f'  <text x="{cx(43):.1f}" y="272" font-size="10.5" fill="#16a34a" text-anchor="middle">互联网泡沫 · 当年亏 30 万</text>')
marks.append(f'  <text x="660" y="330" font-size="10.5" fill="#16a34a" text-anchor="end">2022 · 当年亏 89 万</text>')

print("<svg viewBox=\"0 0 680 452\" xmlns=\"http://www.w3.org/2000/svg\" font-family=\"-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif\">")
print('  <rect x="0" y="0" width="680" height="452" rx="14" fill="#ffffff"/>')
print('  <rect x="0.5" y="0.5" width="679" height="451" rx="14" fill="none" stroke="#e2e8f0"/>')
print('  <text x="24" y="34" font-size="17" font-weight="700" fill="#0f172a">低保账户：每一年到底「赚了多少」</text>')
print('  <text x="24" y="55" font-size="12" fill="#64748b">22 → 60 岁 · 每交易日 40 元 · 1988 起点真实路径（红利腿接力）</text>')
print('  <text x="36" y="80" font-size="11.5" fill="#dc2626">■ 当年赚</text>')
print('  <text x="98" y="80" font-size="11.5" fill="#16a34a">■ 当年亏</text>')
print('  <text x="164" y="80" font-size="11.5" fill="#94a3b8">零轴 ≈ 一年投入（约 1.0 万元）—— 后期一天的波动就超过一整年的投入</text>')
print(f'  <line x1="36" y1="{Y0}" x2="660" y2="{Y0}" stroke="#cbd5e1" stroke-width="1"/>')
for s in bars:
    print(s)
for s in ticks + marks:
    print(s)
print('  <rect x="24" y="382" width="632" height="52" rx="10" fill="#0f172a"/>')
print('  <text x="44" y="404" font-size="13" font-weight="700" fill="#f8fafc">前 3 年看不出来；25 岁起一年赚的超过一年投的；40 岁后好年份一年赚的 ≈ 十年以上的投入</text>')
print('  <text x="44" y="423" font-size="11.5" fill="#94a3b8">39 年里有 8 年是负的，最深一次当年亏 89 万（2022）—— 终值仍是 618.9 万</text>')
print("</svg>")

neg = [r for r in rows if r["pnl"] < 0]
print("\n# 负年份:", len(neg), "/", len(rows))
print("# 最早 ratio>1:", next(r["age"] for r in rows if r["ratio"] > 1))
print("# 最小 pnl:", min(r["pnl"] for r in rows), " 最大:", max(r["pnl"] for r in rows))
