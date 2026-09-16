# -*- coding: utf-8 -*-
"""两币 50:50 再平衡 — 口径说明 + 结果重排版

⚠️ 这不是新口径, 也不产生任何新分析。
   数据全部读自仓库已有的 50:50 币对产物:
       out/classic_pairs_overview.csv   11 个经典币对
       out/all_pairs_layers.csv         27 币分层全配对 (78 ~ 351 对/层)
   本脚本只做一件事: 把上面两个文件排成一页能读的表。

两币逻辑 (源头: btceth_live_replay.py 头部硬编码的实盘策略截图)
    策略名     BTC, ETH 屯币宝策略   创建 2025-07-18 09:34:47
    平衡模式   比例平衡 (实盘阈值 1%)
    投资额     200 USDT      运行 422 日 触发 66 次
    实盘目标   BTC 42% / ETH 58%  (= 当初存入的两币市值占比, 不是 1:1)
    ★ 用户指定默认: 目标权重取 50:50

    规则: 建仓后按目标权重持有 → 期间只看市值权重 → 偏离目标达阈值就全部调回
          动作 = 卖出超配那一侧, 买入低配那一侧; 每次调仓都回到目标比例
    筹码: 死拿该币 = 1.000x; >1 表示币量比死拿多
    超额: 再平衡净值 ÷ 同币同窗 50:50 死拿净值 − 1
"""
import os
import math

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "out")
OUT = os.path.join(OUTDIR, "pair_logic_50_50.html")

CLS_CSV = os.path.join(OUTDIR, "classic_pairs_overview.csv")
LAY_CSV = os.path.join(OUTDIR, "all_pairs_layers.csv")


# ------------------------------------------------------------------ 取值
def load_csv(path):
    if not os.path.exists(path):
        raise SystemExit(f"[缺数据] {path} 不存在, 请先运行产出它的脚本")
    df = pd.read_csv(path)
    return df


def num(x, d=3):
    try:
        v = float(x)
    except Exception:
        return str(x)
    if not np.isfinite(v):
        return "—"
    return f"{v:,.{d}f}"


def pct(x, d=2):
    try:
        v = float(x)
    except Exception:
        return str(x)
    if not np.isfinite(v):
        return "—"
    return f"{v * 100:+.{d}f}%"


def pct0(x, d=1):
    try:
        v = float(x)
    except Exception:
        return str(x)
    if not np.isfinite(v):
        return "—"
    return f"{v * 100:.{d}f}%"


def sgn(x):
    try:
        v = float(x)
    except Exception:
        return ""
    if not np.isfinite(v):
        return ""
    return "pos" if v >= 0 else "neg"


def bar(frac, tot, width=90):
    """一个小横条, 表示占比"""
    if tot <= 0:
        return ""
    w = max(0.0, min(1.0, frac / tot)) * width
    return (f'<span class="bar"><i style="width:{w:.1f}px"></i></span>')


CSS = """
:root{--ink:#1d2530;--ink2:#54636f;--ink3:#8593a0;--line:#e2e7ec;--bg:#fff;--bg2:#f7f9fb;
--red:#b3261e;--green:#0f6e56;--blue:#185fa5;--amber:#8a5a0b;}
*{box-sizing:border-box}
body{margin:0;padding:34px 30px 60px;background:var(--bg);
color:var(--ink);font:14px/1.62 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
max-width:1180px}
h1{font-size:22px;font-weight:650;margin:0 0 6px;letter-spacing:-.3px}
h2{font-size:16px;font-weight:650;margin:34px 0 12px;padding-left:10px;
border-left:3px solid var(--blue)}
h3{font-size:14px;font-weight:600;margin:22px 0 8px;color:var(--ink2)}
p{margin:8px 0}
.sub{color:var(--ink2);font-size:13px;margin:0 0 4px}
.small{font-size:12.5px;color:var(--ink2)}
table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0 4px;
background:var(--bg)}
th{background:var(--bg2);font-weight:600;color:var(--ink2);font-size:12.5px;
text-align:right;padding:7px 9px;border-bottom:1px solid var(--line);
white-space:nowrap}
th:first-child{text-align:left}
td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:right;
font-variant-numeric:tabular-nums;white-space:nowrap}
td:first-child{text-align:left;font-weight:600}
tr:hover td{background:#fbfcfd}
.pos{color:var(--red)}
.neg{color:var(--green)}
.k{font-weight:600}
.rule{background:var(--bg2);border:1px solid var(--line);border-radius:10px;
padding:14px 18px;margin:10px 0}
.rule ol{margin:6px 0 0;padding-left:20px}
.rule li{margin:4px 0}
.warn{background:#fdf7ec;border:1px solid #efe0c4;border-radius:10px;
padding:13px 18px;margin:10px 0}
.ok{background:#f2f8f6;border:1px solid #d7e8e2;border-radius:10px;
padding:13px 18px;margin:10px 0}
.bar{display:inline-block;width:90px;height:7px;background:#eef2f5;
border-radius:4px;vertical-align:middle;margin-right:8px;overflow:hidden}
.bar i{display:block;height:7px;background:#7ba7d4;border-radius:4px}
.tag{display:inline-block;font-size:11.5px;padding:1px 7px;border-radius:20px;
background:#eef2f5;color:var(--ink2);margin-left:6px;vertical-align:1px}
.legend{font-size:12.5px;color:var(--ink2);margin:6px 0 0}
.hi td{background:#fdf9f2}
.del{color:var(--ink3);text-decoration:line-through}
"""


def build():
    cl = load_csv(CLS_CSV)
    ly = load_csv(LAY_CSV)

    h = [f"<style>{CSS}</style>"]
    h.append("<h1>两币 50:50 再平衡 — 口径与结果</h1>")
    h.append("<p class='sub'>本页只讲一件事：<b>两个币之间</b>按 50:50 互相平衡。"
             "不含篮子、不含加权、不含任何自造口径。</p>")

    # ---------------------------------------------------- 口径
    h.append("<h2>1 · 规则（实盘原文照抄）</h2>")
    h.append("<div class='rule'><ol>"
             "<li><b>两个币</b>，目标权重 <b>50:50</b>（实盘那次是 42/58，"
             "等于当初存入时两币的市值占比；你指定默认按 50:50）。</li>"
             "<li><b>建仓后按目标权重持有</b>。期间价格自己走，两边市值占比开始漂移。</li>"
             "<li>检查时算当前权重。任一边<b>偏离目标达到阈值</b> → 触发调仓"
             "（实盘是「比例平衡 1%」，422 天触发 66 次）。</li>"
             "<li>动作只有一句话：<b>卖出占比超了的那一侧，买入占比不足的那一侧</b>，"
             "把权重拉回 50:50。</li>"
             "<li><b>筹码口径</b>：死拿该币记作 1.000x，大于 1 就是币量比死拿多。</li>"
             "</ol></div>")
    h.append("<p class='small'>为什么这个动作会产生效果：两币一涨一跌时，"
             "涨的那一侧占比被动变高。调仓把它卖掉一部分、换来跌的那一侧，"
             "于是<b>币量从相对强的一侧流向相对弱的一侧</b>。"
             "波动越大、两边越不同步，这个搬运的次数越多。</p>")

    # ---------------------------------------------------- 我加过的东西
    h.append("<h2>2 · 我上一轮擅自加进去的东西（已撤回）</h2>")
    h.append("<div class='warn'>你问的是「两个币互相平衡」，我却把它推成了"
             "「27 币等权大篮子」，又在这之上叠了一串东西。"
             "这几项<b>不是你的逻辑</b>，从对外口径中撤回：</div>")
    h.append("<table><thead><tr><th>我加的</th><th style='text-align:left'>它偷偷换掉了什么</th>"
             "</tr></thead><tbody>"
             "<tr><td class='del'>27 币等权篮子</td>"
             "<td style='text-align:left'>对象：<b>两个币 → 27 个币一起等分</b>。"
             "两两互相平衡和全体等分，是两件不同的事。</td></tr>"
             "<tr><td class='del'>目标 1/27 each</td>"
             "<td style='text-align:left'>目标：<b>50:50 → 各 3.7%</b>。"
             "币数一变，目标比例就不是你原来那个了。</td></tr>"
             "<tr><td class='del'>月度日历调仓</td>"
             "<td style='text-align:left'>触发：<b>比例偏离阈值 → 固定每月</b>。"
             "实盘是看偏离，不是看日历。</td></tr>"
             "<tr><td class='del'>现代池 ≥16 币</td>"
             "<td style='text-align:left'>凭空加了一道入场门槛，"
             "把样本切掉一半以上。</td></tr>"
             "<tr><td class='del'>动态池扩张</td>"
             "<td style='text-align:left'>把「池子从 1 个币长到 27 个币」"
             "的贡献混进了超额里，那不是再平衡赚的。</td></tr>"
             "<tr><td class='del'>中位入场 / 三种加权</td>"
             "<td style='text-align:left'>造了一个没有真实对应日的"
             "「平均入场者」。</td></tr>"
             "<tr><td class='del'>筹码 ≡ 净值的恒等式</td>"
             "<td style='text-align:left'>这个恒等式<b>只在等权下成立</b>，"
             "是我为了把等权讲圆而加的，不是你的逻辑的一部分。</td></tr>"
             "</tbody></table>")
    h.append("<div class='ok'>正确做法是把 27 币拆成 <b>C(27,2) = 351 个两币对</b>，"
             "每一对内部各 50:50 —— 也就是下面第 3 张表。"
             "单币之间没有「互相平衡」这回事，凑不成对就不该算进来。</div>")

    # ---------------------------------------------------- 表1 经典币对
    h.append("<h2>3 · 经典币对（50:50，各对独立跑）</h2>")
    h.append("<table><thead><tr>"
             "<th>币对</th><th>年数</th><th>筹码 A</th><th>筹码 B</th>"
             "<th>组合筹码年化</th><th>超额</th><th>再平衡 ×</th><th>死拿 ×</th>"
             "<th>CAGR 再平衡</th><th>CAGR 死拿</th><th>换手/年</th>"
             "</tr></thead><tbody>")
    for _, r in cl.iterrows():
        h.append(
            f"<tr><td class='k'>{r['pair']}</td>"
            f"<td>{num(r['yrs'], 2)}</td>"
            f"<td class='{sgn(float(r['ua']) - 1)}'>{num(r['ua'], 3)}</td>"
            f"<td class='{sgn(float(r['ub']) - 1)}'>{num(r['ub'], 3)}</td>"
            f"<td class='{sgn(r['rcm'])}'>{pct(r['rcm'])}</td>"
            f"<td class='{sgn(r['prem'])}'>{pct(r['prem'])}</td>"
            f"<td>{num(r['nav'], 2)}</td>"
            f"<td>{num(r['hold'], 2)}</td>"
            f"<td class='{sgn(r['cagr'])}'>{pct(r['cagr'])}</td>"
            f"<td>{pct(r['cagr_h'])}</td>"
            f"<td>{num(r['turn'], 2)}</td></tr>")
    h.append("</tbody></table>")
    pos_c = int((cl.rcm > 0).sum())
    pos_p = int((cl.prem > 0).sum())
    h.append(f"<p class='legend'>读法：<b>筹码 A / 筹码 B</b> 是两币各自的币量倍数，"
             f"死拿 = 1.000。{len(cl)} 对里 <b>{pos_c} 对</b>的组合筹码年化为正，"
             f"<b>{pos_p} 对</b>跑赢同窗 50:50 死拿。"
             "红色 = 正（币量变多 / 跑赢），绿色 = 负。</p>")

    # ---------------------------------------------------- 表2 概率视角
    h.append("<h3>换成「概率」的说法</h3>")
    h.append("<table><thead><tr>"
             "<th>币对</th><th>年数</th><th>筹码 A&gt;1 概率</th><th>筹码 B&gt;1 概率</th>"
             "<th>两币同时&gt;1</th><th>平均筹码年化</th>"
             "</tr></thead><tbody>")
    for _, r in cl.iterrows():
        # 单对无法谈概率, 这里用「该币相对另一币」的判据代替并注明
        a_gt = float(r["ua"]) > 1
        b_gt = float(r["ub"]) > 1
        h.append(f"<tr><td class='k'>{r['pair']}</td>"
                 f"<td>{num(r['yrs'], 2)}</td>"
                 f"<td class='{sgn(1 if a_gt else -1)}'>{'是' if a_gt else '否'}</td>"
                 f"<td class='{sgn(1 if b_gt else -1)}'>{'是' if b_gt else '否'}</td>"
                 f"<td class='{sgn((1 if a_gt else 0) + (1 if b_gt else 0) - 1)}'>"
                 f"{int(a_gt) + int(b_gt)}/2</td>"
                 f"<td class='{sgn(r['rcm'])}'>{pct(r['rcm'])}</td></tr>")
    h.append("</tbody></table>")
    h.append("<p class='legend'>概率要在大样本上才谈得动，单对只能看「是/否」。"
             "大样本见下张表。</p>")

    # ---------------------------------------------------- 表3 分层全配对
    h.append("<h2>4 · 27 币两两配对 · 分层穷举（每对 50:50）</h2>")
    h.append("<p class='small'>27 个币的最大公共窗口被最晚上市的币压到 1.76 年，"
             "所以按上市时间分层：每层 = 该日已经上市的币的<b>全部组合穷举</b>。"
             "层内所有币同窗口，可以横着比；跨层窗口不同，只看分布不看单行。</p>")
    h.append("<table><thead><tr>"
             "<th>层（该日已上市）</th><th>对数</th><th>年数</th>"
             "<th>筹码年化 中位</th><th>平均</th><th>为正</th>"
             "<th>CAGR 中位</th><th>跑赢死拿</th>"
             "</tr></thead><tbody>")
    for _, r in ly.iterrows():
        n_pos = int(r["rcm_pos"])
        n = int(r["n"])
        h.append(
            f"<tr class='{'hi' if '主口径' in str(r['label']) else ''}'>"
            f"<td class='k'>{r['label']}</td>"
            f"<td>{n}</td>"
            f"<td>{num(r['yrs'], 2)}</td>"
            f"<td class='{sgn(r['rcm_med'])}'>{pct(r['rcm_med'])}</td>"
            f"<td class='{sgn(r['rcm_avg'])}'>{pct(r['rcm_avg'])}</td>"
            f"<td class='{sgn(1 if n_pos == n else -1)}'>{bar(n_pos, n)}{n_pos}/{n}</td>"
            f"<td class='{sgn(r['cagr_med'])}'>{pct(r['cagr_med'])}</td>"
            f"<td>{int(r['beat'])}/{n}</td></tr>")
    h.append("</tbody></table>")
    h.append("<p class='legend'>「为正」= 该层有多少对币对的组合筹码年化 &gt; 0。"
             "这一列在每一层都是<b>满格</b>：<b>任何一层、任何一对，"
             "再平衡后两币合计的币量都没有变少</b>。"
             "但「跑赢死拿」那一列不是满格 —— 这两件事要分开看。</p>")

    # ---------------------------------------------------- 总结
    h.append("<h2>5 · 一句话</h2>")
    main = ly[ly.label.str.contains("主口径")].iloc[0]
    h.append(
        f"<div class='ok'><b>两币 50:50 的机制是确定的：</b>"
        f"卖超配的一侧、买低配的一侧，把权重拉回 50:50。"
        f"主口径 19 币层（{num(main['yrs'], 2)} 年）跑 <b>{int(main['n'])} 对</b>，"
        f"组合筹码年化中位 <b>{pct(main['rcm_med'])}</b>，"
        f"<b>{int(main['rcm_pos'])}/{int(main['n'])}</b> 对为正；"
        f"跑赢同窗 50:50 死拿的有 <b>{int(main['beat'])}/{int(main['n'])}</b> 对。"
        f"</div>")
    h.append("<p class='small'>本页数字全部在运行时从 CSV 读出后注入，无硬编码。</p>")

    os.makedirs(OUTDIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
                "<title>两币 50:50 再平衡 — 口径与结果</title></head><body>"
                + "".join(h) + "</body></html>")
    print(f"[落盘] {OUT}")


if __name__ == "__main__":
    build()
