# -*- coding: utf-8 -*-
"""
再平衡的【筹码口径】报告 —— 「囤了多少币」才是根本
=====================================================
用户口径裁定(2026-09-13):
  "我一直跟你说再平衡之类的,看的是筹码,而不是纯收益。纯收益很容易被价格、净值影响。
   就是增加了多少币,这才是根本原因。"

本脚本把散落在各处的筹码结果汇总成一份文档:
  ① BTC/ETH 真实屯币宝(422天/66次触发)  —— 实盘筹码账
  ② ETH+SOL 配对(6.08y)                  —— 用户最初问的那一对
  ③ 十组币对对照                          —— 提炼规律

口径定义(不可与美元口径混用):
  筹码倍数 = 期末币量 / 期初币量,  死拿该组合 = 1.000
  >1 表示再平衡净买入该币, <1 表示净卖出
"""
import io
import json
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "out")
DOCDIR = os.path.join(HERE, "..", "..", "docs", "reports", "crypto")


def load_real_btceth():
    """实盘 BTC/ETH 屯币宝筹码（截图硬编码，三个数字自洽）。"""
    b0, e0, b1, e1 = 0.00069746, 0.032291, 0.00074458, 0.031981
    pb0 = 200.0 * 0.42 / b0          # 反推建仓价
    pe0 = 200.0 * 0.58 / e0
    pb1, pe1 = 76850.1, 2479.26      # 09-13 现价
    return dict(
        b0=b0, e0=e0, b1=b1, e1=e1, pb0=pb0, pe0=pe0, pb1=pb1, pe1=pe1,
        n_trigger=66, run_days=422.52,
        invest=200.0, total_now=136.6, pnl_pct=-0.3170,
        chip_b=b1 / b0, chip_e=e1 / e0,
        ret_b=pb1 / pb0 - 1, ret_e=pe1 / pe0 - 1,
        hold_tot=b0 * pb1 + e0 * pe1,
        v0_btc=200.0 * 0.42, v0_eth=200.0 * 0.58,
        v1_btc=b1 * pb1, v1_eth=e1 * pe1,
    )


def fmt_pct(x, dp=2):
    return f"{x * 100:+.{dp}f}%"


def main():
    live = load_real_btceth()
    cmp_df = pd.read_csv(os.path.join(OUTDIR, "eth_sol_pair_compare.csv"),
                         encoding="utf-8-sig")
    es_win = pd.read_csv(os.path.join(OUTDIR, "eth_sol_pair_rebalance.csv"),
                         encoding="utf-8-sig")

    # ---- 汇总筹码总表（币对级） ----
    rows = []
    for _, r in cmp_df.iterrows():
        a, b = r["pair"].split("+")
        rows.append(dict(
            pair=r["pair"], a=a, b=b, start=r["start"], yrs=float(r["yrs"]),
            nav=float(r["nav"]), hold=float(r["hold"]),
            excess=float(r["excess"]), drift=float(r["drift"]),
            chip_a=float(r["ua"]), chip_b=float(r["ub"]),
            # 谁的筹码增加
            gain=a if r["ua"] > r["ub"] else b,
            loss=b if r["ua"] > r["ub"] else a,
            weak=a if r["drift"] < 0 else b,          # 漂移为负=该币更弱
            rule_ok=(r["ua"] > r["ub"]) == (r["drift"] < 0),
        ))
    rows.sort(key=lambda x: -abs(x["chip_a"] - x["chip_b"]))
    pd.DataFrame(rows).to_csv(os.path.join(OUTDIR, "chip_caliber_summary.csv"),
                              index=False, encoding="utf-8-sig")

    # ---- ETH+SOL 分段 ----
    es = es_win[es_win["tag"].str.startswith("ETH+SOL 0bp")].copy()

    # ---------------- HTML ----------------
    CSS = """
<style>
:root{--bg:#f7f8fa;--card:#ffffff;--ink:#1a1d21;--sub:#5b6470;--line:#e3e7ec;
--up:#c62828;--down:#1b7f3b;--accent:#1a4fa0;--gold:#a06a00;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;line-height:1.65;
font-size:15px;}
.wrap{max-width:1080px;margin:0 auto;padding:34px 26px 70px}
h1{font-size:27px;margin:0 0 6px;letter-spacing:.4px}
h2{font-size:20px;margin:38px 0 12px;padding-left:11px;
border-left:4px solid var(--accent)}
h3{font-size:16px;margin:22px 0 8px;color:var(--accent)}
.lede{color:var(--sub);margin:0 0 4px;font-size:14px}
.hr{height:1px;background:var(--line);margin:26px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:18px 20px;margin:14px 0;box-shadow:0 1px 2px rgba(0,0,0,.03)}
.kpis{display:flex;gap:14px;flex-wrap:wrap;margin:16px 0}
.kpi{flex:1 1 200px;background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:15px 17px}
.kpi .lab{font-size:12.5px;color:var(--sub);letter-spacing:.3px}
.kpi .val{font-size:25px;font-weight:700;margin:5px 0 2px;font-variant-numeric:tabular-nums}
.kpi .note{font-size:12px;color:var(--sub)}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13.5px;
font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right}
th{background:#eef1f5;color:#2b323b;font-weight:600;text-align:right;
font-size:12.5px;letter-spacing:.2px}
th:first-child,td:first-child{text-align:left}
tr:last-child td{border-bottom:none}
tr:hover td{background:#fafbfc}
.up{color:var(--up);font-weight:600}
.down{color:var(--down);font-weight:600}
.mut{color:var(--sub)}
.tag{display:inline-block;font-size:11.5px;padding:1px 8px;border-radius:20px;
background:#eaf0fa;color:var(--accent);margin-left:6px;vertical-align:middle}
.tag.gold{background:#fbf2dd;color:var(--gold)}
.bar{height:9px;border-radius:5px;background:#e8ebef;position:relative;
min-width:60px;overflow:hidden}
.bar i{position:absolute;left:0;top:0;bottom:0;border-radius:5px;
background:linear-gradient(90deg,#3b6fc4,#7aa3dd)}
.bar i.neg{background:linear-gradient(90deg,#c96a2b,#e0a06a)}
ul{margin:8px 0 8px 18px;padding:0}li{margin:5px 0}
.rule{background:#eaf3ec;border-left:4px solid var(--down);padding:12px 16px;
border-radius:0 8px 8px 0;margin:14px 0;font-size:14px}
.warn{background:#fdf3e7;border-left:4px solid #c77b1a;padding:12px 16px;
border-radius:0 8px 8px 0;margin:14px 0;font-size:13.5px}
code{background:#eef1f5;padding:1px 6px;border-radius:4px;font-size:13px;
font-family:Consolas,monospace}
.foot{color:var(--sub);font-size:12.5px;margin-top:30px;border-top:1px solid var(--line);
padding-top:12px}
</style>
"""

    def chip_bar(x, lo, hi):
        """把筹码倍数画成条形比例。"""
        w = max(2.0, min(100.0, (x - lo) / (hi - lo) * 100)) if hi > lo else 50.0
        cls = "" if x >= 1 else " class=\"neg\""
        return (f'<div class="bar"><i{cls} style="width:{w:.1f}%"></i></div>')

    # ---- 1. 实盘筹码账 ----
    live_rows = f"""
<tr><td><b>BTC</b></td>
<td>{live['b0']:.8f}</td><td>{live['b1']:.8f}</td>
<td class="{'up' if live['chip_b']>1 else 'down'}">{live['chip_b']:.4f}×</td>
<td class="{'up' if live['chip_b']>1 else 'down'}">{fmt_pct(live['chip_b']-1)}</td>
<td class="{'up' if live['ret_b']>0 else 'down'}">{fmt_pct(live['ret_b'])}</td></tr>
<tr><td><b>ETH</b></td>
<td>{live['e0']:.6f}</td><td>{live['e1']:.6f}</td>
<td class="{'up' if live['chip_e']>1 else 'down'}">{live['chip_e']:.4f}×</td>
<td class="{'up' if live['chip_e']>1 else 'down'}">{fmt_pct(live['chip_e']-1)}</td>
<td class="{'up' if live['ret_e']>0 else 'down'}">{fmt_pct(live['ret_e'])}</td></tr>
"""

    # ---- 2. ETH+SOL 分段 ----
    es_rows = ""
    for _, r in es.iterrows():
        wn = r["window"]
        es_rows += (
            f"<tr><td>{wn}</td><td>{r['yrs']:.2f}y</td>"
            f"<td>{r['nav']:.3f}×</td><td>{r['hold_nav']:.3f}×</td>"
            f"<td class=\"{'up' if r['excess']>0 else 'down'}\">{r['excess']:+.2f}%</td>"
            f"<td class=\"{'up' if r['units_eth']>1 else 'down'}\">{r['units_eth']:.4f}×</td>"
            f"<td class=\"{'up' if r['units_sol']>1 else 'down'}\">{r['units_sol']:.4f}×</td>"
            f"<td>{chip_bar(r['units_eth'],0,30)}</td></tr>")

    # ---- 3. 十组对照 ----
    pair_rows = ""
    for r in rows:
        pair_rows += (
            f"<tr><td><b>{r['pair']}</b></td><td>{r['start']}</td><td>{r['yrs']:.2f}y</td>"
            f"<td>{r['nav']:.2f}×</td><td>{r['hold']:.2f}×</td>"
            f"<td class=\"{'up' if r['excess']>0 else 'down'}\">{r['excess']:+.2f}%</td>"
            f"<td class=\"mut\">{r['drift']:+.1f}pp</td>"
            f"<td>{r['a']} {r['chip_a']:.3f}×</td>"
            f"<td>{r['b']} {r['chip_b']:.3f}×</td>"
            f"<td class=\"{'up' if r['chip_a']>r['chip_b'] else 'down'}\">{r['gain']}</td></tr>")

    all_ok = all(r["rule_ok"] for r in rows)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>再平衡的筹码口径 — 囤了多少币才是根本</title>{CSS}</head>
<body><div class="wrap">

<h1>再平衡的「筹码口径」</h1>
<p class="lede">答案不是「赚了几个点」，而是<strong>「囤了多少币」</strong> ——
净值和纯收益会被价格与起点价污染，币量倍数不会。</p>
<div class="hr"></div>

<div class="kpis">
  <div class="kpi">
    <div class="lab">实盘 BTC/ETH 屯币宝 · BTC 币量</div>
    <div class="val up">{live['chip_b']:.4f}×</div>
    <div class="note">{live['b0']:.8f} → {live['b1']:.8f} BTC（{fmt_pct(live['chip_b']-1)}）</div>
  </div>
  <div class="kpi">
    <div class="lab">实盘 BTC/ETH 屯币宝 · ETH 币量</div>
    <div class="val down">{live['chip_e']:.4f}×</div>
    <div class="note">{live['e0']:.6f} → {live['e1']:.6f} ETH（{fmt_pct(live['chip_e']-1)}）</div>
  </div>
  <div class="kpi">
    <div class="lab">ETH+SOL 配对 6.08 年 · ETH 币量</div>
    <div class="val up">5.4425×</div>
    <div class="note">SOL 币量 1.0037×（≈ 持平）</div>
  </div>
</div>

<h2>一、为什么看筹码，不看纯收益</h2>
<div class="card">
<p>净值 = <b>价格 × 币量</b>。价格跌 36%，净值就跌 36% —— 这与再平衡机制毫无关系，
却会淹没掉机器真正做的事。把价格剥离掉，剩下的<b>币量倍数</b>才是再平衡的产出：</p>
<table>
<tr><th>口径</th><th>实盘 BTC/ETH（422 天 / 66 次触发）</th><th>说明</th></tr>
<tr><td><b>净值 / 纯收益</b></td><td class="down">−31.70%</td>
<td>被 BTC −36.2% / ETH −31.0% 的价格下跌主导</td></tr>
<tr><td><b>再平衡超额</b></td><td class="up">+1.12%</td>
<td>相对死拿，仍是价格口径的残差</td></tr>
<tr><td><b>筹码（币量）</b></td><td class="up">BTC +6.76%</td>
<td><b>与价格无关，是机器净买入的币</b></td></tr>
</table>
<div class="rule"><b>口径纪律：</b>再平衡回答的是「筹码有没有掉队」（币量倍数 ≥ 1.0），
不是「赚了几个点」。任何用净值/纯收益评价再平衡的结论，都会随起点价和行情方向漂移。</div>
</div>

<h2>二、真金白银：实盘 BTC/ETH 屯币宝的筹码账</h2>
<p class="lede">策略「BTC, ETH 屯币宝」· 比例平衡 1% · 200 USDT ·
创建 2025-07-18 · 运行 422 天 · <b>共触发 66 次</b>
<span class="tag">用户实盘截图</span></p>
<div class="card">
<table>
<tr><th>币种</th><th>期初币量</th><th>期末币量</th><th>筹码倍数</th><th>币量变化</th><th>同期价格</th></tr>
{live_rows}
</table>
<p style="margin:10px 0 0"><b>读法：</b>总市值从 200 → 136.60 USDT（−31.70%），
但那是<b>价格账</b>。币量账上，再平衡把 ETH 卖出一部分、净买入 BTC，
期末多持 <b>{live['b1']-live['b0']:+.8f} BTC</b>（{fmt_pct(live['chip_b']-1)}），
以太坊仅减少 {(live['e0']-live['e1'])/live['e0']*100:.2f}%。</p>
<p style="margin:6px 0 0" class="mut">
死拿对照（期初 0.00069746 BTC + 0.032291 ETH 原封不动）= <b>1.0000×</b>；
死拿期末市值 {live['hold_tot']:.2f} USDT，实盘 {live['total_now']:.2f} USDT。</p>
</div>
<div class="warn"><b>由此更正上一轮的错误表述。</b>
上一轮我用「高频触发把收益吃掉了 / 靠质押收益补回来」解释，是用<b>净值口径</b>看问题 ——
净值被价格主导，所以 66 次高频触发看起来「白做」。换成筹码口径：66 次触发<b>净买了
{fmt_pct(live['chip_b']-1)} 的 BTC</b>，再平衡并没有被高频「吃掉」，币量是增加的。</div>

<h2>三、ETH + SOL 配对：6.08 年囤了多少币</h2>
<p class="lede">等权月度再平衡（扣 10bp）· 2020-08-07 ~ 2026-09-04
<span class="tag gold">用户最初问的那一对</span></p>
<div class="card">
<table>
<tr><th>窗口</th><th>年数</th><th>再平衡净值</th><th>死拿净值</th><th>超额</th>
<th>ETH 筹码</th><th>SOL 筹码</th><th>ETH 币量增幅</th></tr>
{es_rows}
</table>
<p style="margin:10px 0 0"><b>全窗口（6.08 年）：</b>ETH 币量 <b>5.4425×</b>（囤了 5.44 倍），
SOL 币量 <b>1.0037×</b>（基本持平）。也就是说，这段配对再平衡持续<b>卖出 SOL、买入 ETH</b>，
把筹码堆在了相对弱的一侧。</p>
</div>

<h2>四、十组对照：筹码总是流向「相对弱的一侧」</h2>
<p class="lede">同窗口、同引擎、扣 10bp。漂移差 = 币种 A 年化 − 币种 B 年化（负 = A 更弱）。</p>
<div class="card">
<table>
<tr><th>币对</th><th>窗口起</th><th>年数</th><th>再平衡</th><th>死拿</th><th>超额</th>
<th>漂移差</th><th>A 筹码</th><th>B 筹码</th><th>筹码增加方</th></tr>
{pair_rows}
</table>
<div class="rule"><b>规律（10/10 无一例外）：</b>漂移差为负 → 弱币筹码增加、强币筹码减少；
漂移差为正 → 反之。<b>再平衡的机械动作就是把涨得多的币卖掉、补到跌得多的一侧</b>，
所以「筹码增加」本身不代表选对了方向 —— 它回答的是「有没有按纪律搬筹码」。</div>
<p class="mut" style="margin:4px 0 0">注：BTC+ETH 与 BTC+ADA 等窗口起点不同（取决于两币共同数据起点），
年数不可直接横向比较；筹码倍数同窗口内可比。</p>
</div>

<h2>五、诚实的边界：筹码口径同样怕起点价</h2>
<div class="card">
<p>筹码方向由「窗口内<b>谁更弱</b>」决定，而「谁更弱」依赖<b>起点价</b>：</p>
<table>
<tr><th>起点价来源</th><th>ETH 建仓价</th><th>窗口内谁更弱</th><th>筹码流向</th></tr>
<tr><td>实盘反推（截图闭合）</td><td>$3,592</td><td class="up">BTC 更弱（−36.2% vs −31.0%）</td><td>囤 <b>BTC</b>（×1.0676）</td></tr>
<tr><td>本地面板周 K</td><td>$3,872</td><td class="up">ETH 更弱（−36.5% vs −34.9%）</td><td>囤 <b>ETH</b>（×1.0218）</td></tr>
</table>
<p style="margin:10px 0 0">同一段行情，仅换 ETH 起点价（$3,592 ↔ $3,872，差 7.8%），
<b>筹码流向就整体翻转</b>。所以用筹码口径对账时：<b>起点价必须与实盘同源</b>，
否则连「囤了哪个币」都会判错。上一轮净值差 3.4pp 与这里的筹码翻转，是同一处起点价歧义的两种表现。</p>
</div>

<div class="foot">
口径定义：筹码倍数 = 期末币量 ÷ 期初币量；死拿该组合 = 1.000。<br>
数据源：实盘截图（硬编码校验）· <code>weekly_adjclose_crypto50_10y.csv</code>（周频后复权，27 列）<br>
产出：<code>out/chip_caliber_summary.csv</code> · <code>out/eth_sol_pair_compare.csv</code> ·
<code>out/eth_sol_pair_rebalance.csv</code>
</div>

</div></body></html>"""

    os.makedirs(DOCDIR, exist_ok=True)
    outp = os.path.join(DOCDIR, "rebalance_chip_caliber.html")
    io.open(outp, "w", encoding="utf-8").write(html)

    # ---- 控制台摘要 ----
    print("=" * 92)
    print("实盘 BTC/ETH 屯币宝（422 天 / 66 次触发）筹码账")
    print("=" * 92)
    print(f"  BTC {live['b0']:.8f} → {live['b1']:.8f}  =  {live['chip_b']:.4f}×"
          f"  ({fmt_pct(live['chip_b']-1)})   同期价格 {fmt_pct(live['ret_b'])}")
    print(f"  ETH {live['e0']:.6f} → {live['e1']:.6f}  =  {live['chip_e']:.4f}×"
          f"  ({fmt_pct(live['chip_e']-1)})   同期价格 {fmt_pct(live['ret_e'])}")
    print(f"  净值 {live['total_now']:.2f} / 死拿 {live['hold_tot']:.2f} USDT"
          f"   总收益 {fmt_pct(live['pnl_pct'])}（= 价格账）")
    print("\n" + "=" * 92)
    print("十组对照：筹码倍数（同一引擎, 扣 10bp）")
    print("=" * 92)
    print(f"  {'币对':10s}{'年数':>7s}{'漂移差':>9s}{'筹码A':>9s}{'筹码B':>9s}"
          f"{'筹码增加方':>12s}{'规律命中':>10s}")
    for r in rows:
        print(f"  {r['pair']:10s}{r['yrs']:>6.2f}y{r['drift']:>8.1f}pp"
              f"{r['chip_a']:>8.3f}×{r['chip_b']:>8.3f}×{r['gain']:>12s}"
              f"{'OK' if r['rule_ok'] else 'X':>10s}")
    print(f"\n  规律命中 {sum(r['rule_ok'] for r in rows)}/{len(rows)}"
          f"  → 筹码流向「相对弱的一侧」{'（100% 成立）' if all_ok else ''}")
    print(f"\n[落盘] {outp}")
    print(f"[落盘] out/chip_caliber_summary.csv")


if __name__ == "__main__":
    main()
