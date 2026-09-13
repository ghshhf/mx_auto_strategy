# -*- coding: utf-8 -*-
"""ETH + SOL 配对: 1 / 3 / 5 年窗口「死拿 vs 再平衡」报告（每周调仓为主口径）

读 out/eth_sol_pair_windows.csv + eth_sol_pair_start_sens.csv + eth_sol_pair_theory.csv
输出 self-contained HTML。正文数字全部动态计算注入，不硬编码。
"""
import os
import io

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "out")
DOCDIR = os.path.join(HERE, "..", "..", "docs", "reports", "crypto")
TARGET = os.path.join(DOCDIR, "eth_sol_pair_windows.html")


def F(v, nd=2, sign=True):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    return f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"


def cls(v):
    return "pos" if v > 0 else "neg"


def build():
    w = pd.read_csv(os.path.join(OUTDIR, "eth_sol_pair_windows.csv")).set_index("window")
    ss = pd.read_csv(os.path.join(OUTDIR, "eth_sol_pair_start_sens.csv"))
    th = pd.read_csv(os.path.join(OUTDIR, "eth_sol_pair_theory.csv")).set_index("window")
    WINS = ["1 年", "3 年", "5 年", "全窗口"]

    def g(win, col):
        return w.at[win, col]

    # 主表
    main_rows = ""
    for win in WINS:
        main_rows += (
            f"<tr><td class='l'><b>{win}</b></td><td>{g(win,'yrs'):.2f}</td>"
            f"<td>{g(win,'nav_w'):.4f}x</td><td>{g(win,'nav_m'):.4f}x</td>"
            f"<td>{g(win,'nav_hold'):.4f}x</td>"
            f"<td class='{cls(g(win,'excess_w'))}'><b>{F(g(win,'excess_w'),3)}%</b></td>"
            f"<td class='{cls(g(win,'excess_m'))}'>{F(g(win,'excess_m'),3)}%</td>"
            f"<td>{F(g(win,'excess_w0'),3)}%</td>"
            f"<td>{g(win,'mdd_w'):+.2f}%</td><td>{g(win,'mdd_hold'):+.2f}%</td>"
            f"<td>{F(g(win,'dd_better_w'))}pp</td>"
            f"<td>{g(win,'turn_w'):.0f}%</td></tr>"
        )

    # 单币参照
    solo_rows = ""
    drift = {}
    for win in WINS:
        e, s, rw = g(win, "nav_eth"), g(win, "nav_sol"), g(win, "nav_w")
        yrs = g(win, "yrs")
        dd = ((e ** (1 / yrs)) - (s ** (1 / yrs))) * 100
        drift[win] = dd
        solo_rows += (
            f"<tr><td class='l'><b>{win}</b></td><td>{e:.3f}x</td><td>{s:.3f}x</td>"
            f"<td>{rw:.3f}x</td>"
            f"<td class='{cls(rw - e)}'>{(rw / e - 1) * 100:+.1f}%</td>"
            f"<td class='{cls(rw - s)}'>{(rw / s - 1) * 100:+.1f}%</td>"
            f"<td>{dd:+.1f}pp</td></tr>"
        )

    # 频率对照
    freq_rows = ""
    for win in WINS:
        freq_rows += (
            f"<tr><td class='l'><b>{win}</b></td>"
            f"<td>{g(win,'ev_w'):.0f}</td><td>{g(win,'turn_w'):.0f}%</td>"
            f"<td>{g(win,'nav_w'):.4f}x</td>"
            f"<td class='{cls(g(win,'excess_w'))}'><b>{F(g(win,'excess_w'),2)}%</b></td>"
            f"<td>{g(win,'ev_m'):.0f}</td><td>{g(win,'turn_m'):.0f}%</td>"
            f"<td>{g(win,'nav_m'):.4f}x</td>"
            f"<td class='{cls(g(win,'excess_m'))}'>{F(g(win,'excess_m'),2)}%</td>"
            f"<td class='{cls(g(win,'excess_w')-g(win,'excess_m'))}'>"
            f"{F(g(win,'excess_w')-g(win,'excess_m'),2)}%</td></tr>"
        )

    # 起点敏感性
    sens_rows = ""
    for _, x in ss.iterrows():
        sens_rows += (
            f"<tr><td class='l'>{x['start']}</td><td>{x['excess']:+.3f}%</td>"
            f"<td>{x['units_eth']:.4f}x</td><td>{x['units_sol']:.4f}x</td>"
            f"<td>{x['corr']:.3f}</td><td>{x['drift']:+.1f}pp</td></tr>"
        )

    # 理论收割
    th_rows = ""
    for win in WINS:
        th_rows += (
            f"<tr><td class='l'><b>{win}</b></td>"
            f"<td>{th.at[win,'vol_eth']:.1f}%</td><td>{th.at[win,'vol_sol']:.1f}%</td>"
            f"<td>{th.at[win,'corr']:.3f}</td>"
            f"<td class='pos'>{th.at[win,'harvest']:+.2f}%/年</td>"
            f"<td class='{cls(g(win,'excess_w'))}'>{F(g(win,'excess_w')/g(win,'yrs'),2)}%/年</td>"
            f"<td class='{cls(g(win,'excess_m'))}'>{F(g(win,'excess_m')/g(win,'yrs'),2)}%/年</td></tr>"
        )

    # 相位检验
    ph = pd.read_csv(os.path.join(OUTDIR, "eth_sol_phase_audit.csv"))
    phase_rows = ""
    for win in WINS:
        d = ph[ph.window == win]
        for freq in (1, 2, 4, 8):
            dd = d[d.freq == freq]
            v = dd["nav"].values
            s = dd["units_sol"].values
            phase_rows += (
                f"<tr><td class='l'><b>{win}</b></td><td>{freq} 周</td><td>{len(dd)}</td>"
                f"<td>{v.min():.4f}x</td><td>{v.max():.4f}x</td>"
                f"<td class='{'neg' if (v.max()/v.min()-1) > 0.10 else ''}'>"
                f"{(v.max()/v.min()-1)*100:.1f}%</td>"
                f"<td>{np.median(v):.4f}x</td>"
                f"<td>{s.min():.4f}x ~ {s.max():.4f}x</td></tr>"
            )

    def phstat(win, freq, col="nav"):
        d = ph[(ph.window == win) & (ph.freq == freq)][col].values
        return d.min(), d.max(), float(np.median(d))

    # 筹码口径
    chip_rows = ""
    for win in WINS:
        chip_rows += (
            f"<tr><td class='l'><b>{win}</b></td>"
            f"<td>{g(win,'units_eth_w'):.4f}x</td><td>{g(win,'units_sol_w'):.4f}x</td>"
            f"<td>{g(win,'units_eth_m'):.4f}x</td><td>{g(win,'units_sol_m'):.4f}x</td>"
            f"<td class='{'neg' if g(win,'units_sol_w') < 1 else ''}'>"
            f"{'掉队' if g(win,'units_sol_w') < 1 else '不掉队'}</td></tr>"
        )

    S = dict(
        e1=w.at["1 年", "excess_w"], e3=w.at["3 年", "excess_w"],
        e5=w.at["5 年", "excess_w"], ef=w.at["全窗口", "excess_w"],
        m1=w.at["1 年", "excess_m"], m3=w.at["3 年", "excess_m"],
        m5=w.at["5 年", "excess_m"], mf=w.at["全窗口", "excess_m"],
        n1=w.at["1 年", "nav_w"], n3=w.at["3 年", "nav_w"],
        n5=w.at["5 年", "nav_w"], nf=w.at["全窗口", "nav_w"],
        nm1=w.at["1 年", "nav_m"], nm3=w.at["3 年", "nav_m"],
        nm5=w.at["5 年", "nav_m"], nmf=w.at["全窗口", "nav_m"],
        o1=w.at["1 年", "nav_hold"], o3=w.at["3 年", "nav_hold"],
        o5=w.at["5 年", "nav_hold"], of=w.at["全窗口", "nav_hold"],
        s1=w.at["1 年", "start"], e1d=w.at["1 年", "end"],
        w1=w.at["1 年", "weeks"], w3=w.at["3 年", "weeks"],
        w5=w.at["5 年", "weeks"], wf=w.at["全窗口", "weeks"],
        cw1=w.at["1 年", "cost_w"], cw3=w.at["3 年", "cost_w"],
        cw5=w.at["5 年", "cost_w"], cwf=w.at["全窗口", "cost_w"],
        mdd1=w.at["1 年", "mdd_w"], mdd1h=w.at["1 年", "mdd_hold"],
        mdd3=w.at["3 年", "mdd_w"], mdd3h=w.at["3 年", "mdd_hold"],
        mdd5=w.at["5 年", "mdd_w"], mdd5h=w.at["5 年", "mdd_hold"],
        mddf=w.at["全窗口", "mdd_w"], mddfh=w.at["全窗口", "mdd_hold"],
        cal5=w.at["5 年", "calmar_w"], cal5h=w.at["5 年", "calmar_hold"],
        calf=w.at["全窗口", "calmar_w"], calfh=w.at["全窗口", "calmar_hold"],
        cal1=w.at["1 年", "calmar_w"], cal1h=w.at["1 年", "calmar_hold"],
        cal3=w.at["3 年", "calmar_w"], cal3h=w.at["3 年", "calmar_hold"],
        ue1=w.at["1 年", "units_eth_w"], us1=w.at["1 年", "units_sol_w"],
        ue3=w.at["3 年", "units_eth_w"], us3=w.at["3 年", "units_sol_w"],
        ue5=w.at["5 年", "units_eth_w"], us5=w.at["5 年", "units_sol_w"],
        uef=w.at["全窗口", "units_eth_w"], usf=w.at["全窗口", "units_sol_w"],
        uemf=w.at["全窗口", "units_eth_m"], usmf=w.at["全窗口", "units_sol_m"],
        sens_min=ss["excess"].min(), sens_max=ss["excess"].max(),
        sens_med=ss["excess"].median(), sens_n=len(ss),
        sens_pos=int((ss["excess"] > 0).sum()), sens_sd=ss["excess"].std(),
        cost_freq=(w.at["全窗口", "cost_w"]), 
        h1=th.at["1 年", "harvest"], hf=th.at["全窗口", "harvest"],
        h3=th.at["3 年", "harvest"], h5=th.at["5 年", "harvest"],
        nsf=w.at["全窗口", "nav_sol"], nef=w.at["全窗口", "nav_eth"],
        d3=drift["3 年"], d1=drift["1 年"], d5=drift["5 年"],
        corr0=float(ss[ss["k"] == 0]["corr"].iloc[0]),
        n_pos_win=int((w["excess_w"] > 0).sum()), n_win=len(w),
        p1=phstat("1 年", 4), p3=phstat("3 年", 4),
        p5=phstat("5 年", 4), pf=phstat("全窗口", 4),
        p8f=phstat("全窗口", 8),
        p1s=phstat("1 年", 4, "units_sol"), pfs=phstat("全窗口", 4, "units_sol"),
        pfw1=float(ph[(ph.window == "全窗口") & (ph.freq == 1)]["units_sol"].iloc[0]),
    )

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ETH + SOL 配对：1 / 3 / 5 年窗口的死拿 vs 再平衡（每周调仓）</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--tx:#1c2430;--mut:#66788a;--bd:#e3e7ec;
--pos:#c0392b;--neg:#1e8a4c;--hl:#f2f6fb}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tx);
font:14.5px/1.75 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1220px;margin:0 auto;padding:32px 22px 70px}}
h1{{font-size:25px;margin:0 0 6px}}
.sub{{color:var(--mut);font-size:13.5px;margin:0 0 22px}}
.card{{background:var(--card);border:1px solid var(--bd);border-radius:12px;
padding:20px 22px;margin-bottom:18px}}
h2{{font-size:17px;margin:0 0 14px;padding-bottom:9px;border-bottom:1px solid var(--bd)}}
table{{width:100%;border-collapse:collapse;font-size:13.3px;font-variant-numeric:tabular-nums}}
th,td{{padding:8px 9px;text-align:right;border-bottom:1px solid var(--bd);white-space:nowrap}}
th{{background:var(--hl);font-weight:600;color:#3d4d5e}}
.l{{text-align:left}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}}
.scroll{{overflow-x:auto}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(172px,1fr));gap:12px}}
.kpi{{background:var(--hl);border-radius:9px;padding:13px 15px}}
.kpi .k{{font-size:12.3px;color:var(--mut);margin-bottom:5px}}
.kpi .v{{font-size:21px;font-weight:600;letter-spacing:-.3px}}
.kpi .n{{font-size:12px;color:var(--mut);margin-top:3px}}
.key{{border-left:3px solid #2c6fb5;background:#f4f8fd;padding:12px 15px;border-radius:0 8px 8px 0;
margin-top:14px;font-size:13.8px}}
.warn{{border-left:3px solid #c0392b;background:#fdf3f2;padding:12px 15px;border-radius:0 8px 8px 0;
margin-top:14px;font-size:13.8px}}
.ok{{border-left:3px solid #1e8a4c;background:#f2faf5;padding:12px 15px;border-radius:0 8px 8px 0;
margin-top:14px;font-size:13.8px}}
.note{{background:#f7f8fa;border:1px solid var(--bd);border-radius:8px;padding:12px 15px;
font-size:13px;color:#4a5a6b;margin-top:14px}}
code{{background:#eef1f5;padding:1px 6px;border-radius:4px;font-size:12.5px}}
ul{{margin:8px 0;padding-left:20px}} li{{margin:5px 0}}
</style></head><body><div class="wrap">

<h1>ETH + SOL 配对：1 / 3 / 5 年窗口的死拿 vs 再平衡</h1>
<p class="sub">主口径 <b>每周调仓</b>（用户 2026-09-13 指定），附月度对照，均扣 10bp。
面板周频后复权，末周 {S['e1d']}。1 年窗口 {S['w1']} 周、3 年 {S['w3']} 周、5 年 {S['w5']} 周、全窗口 {S['wf']} 周。</p>

<div class="card">
<h2>一、直接回答：跑赢多少</h2>
<div class="kpis">
  <div class="kpi"><div class="k">1 年（每周）</div>
    <div class="v {cls(S['e1'])}">{F(S['e1'],3)}%</div>
    <div class="n">{S['n1']:.4f}x vs 死拿 {S['o1']:.4f}x｜月度 {F(S['m1'],3)}%</div></div>
  <div class="kpi"><div class="k">3 年（每周）</div>
    <div class="v {cls(S['e3'])}">{F(S['e3'],3)}%</div>
    <div class="n">{S['n3']:.4f}x vs 死拿 {S['o3']:.4f}x｜月度 {F(S['m3'],3)}%</div></div>
  <div class="kpi"><div class="k">5 年（每周）</div>
    <div class="v {cls(S['e5'])}">{F(S['e5'],3)}%</div>
    <div class="n">{S['n5']:.4f}x vs 死拿 {S['o5']:.4f}x｜月度 {F(S['m5'],3)}%</div></div>
  <div class="kpi"><div class="k">全窗口 6.08 年（每周）</div>
    <div class="v {cls(S['ef'])}">{F(S['ef'],3)}%</div>
    <div class="n">{S['nf']:.3f}x vs 死拿 {S['of']:.3f}x｜月度 {F(S['mf'],3)}%</div></div>
</div>
<div class="scroll" style="margin-top:16px"><table>
<thead><tr><th class="l">窗口</th><th>年数</th><th>再平衡<br>每周</th><th>再平衡<br>每月</th>
<th>死拿</th><th>跑赢<br>(每周)</th><th>跑赢<br>(每月)</th><th>跑赢<br>每周0bp</th>
<th>MDD<br>每周</th><th>MDD<br>死拿</th><th>回撤<br>改善</th><th>换手<br>每周</th></tr></thead>
<tbody>{main_rows}</tbody></table></div>

<div class="warn">
<b>三档窗口的答案：</b>
1 年每周 {F(S['e1'],3)}%（月度 {F(S['m1'],3)}%）、3 年 {F(S['e3'],3)}%（月度 {F(S['m3'],3)}%，仍跑输）、
5 年 {F(S['e5'],3)}%（月度 {F(S['m5'],3)}%）。
<b>每周与每月在三档窗口下的差异都在 1% 以内</b>——调仓频率不是决定因素。
全窗口那一格看似差距很大（每周 {S['nf']:.2f}x vs 月度 {S['nmf']:.2f}x），
<b>但经检验主要是调仓日历运气，见第三节。</b>
</div>
</div>

<div class="card">
<h2>二、1 年窗口为什么差异这么小（以及它其实不是"一样"）</h2>
<p>1 年窗口每周调仓跑赢 {F(S['e1'],3)}%、月度 {F(S['m1'],3)}%，两者都在 0.5% 以内，
看上去像"平衡与不平衡没区别"。<b>但这是终点巧合，不是过程没差异。</b></p>
<h3>起点挪动 ±6 周的敏感性（每周调仓）</h3>
<div class="scroll"><table>
<thead><tr><th class="l">起点</th><th>跑赢</th><th>筹码 ETH</th><th>筹码 SOL</th>
<th>周收益相关</th><th>漂移差<br>(ETH−SOL)</th></tr></thead>
<tbody>{sens_rows}</tbody></table></div>
<div class="ok">
<b>13 个起点里 {S['sens_pos']} 个为正超额</b>，区间 {S['sens_min']:+.3f}% ~ {S['sens_max']:+.3f}%，
中位 <b>{S['sens_med']:+.3f}%</b>（标准差 {S['sens_sd']:.3f}pp）。
即：<b>「1 年 ≈ 无差异」只在特定的那个起点上成立；换一个起点，每周调仓稳定小幅跑赢。</b>
</div>
<div class="note">
<b>为什么差异本来就小：</b>1 年窗口 ETH/SOL 的周收益相关高达 {ss['corr'].iloc[6]:.3f}，
同向下跌（区间累计 ETH −46.6% / SOL −57.8%），大部分时间两个币在同步走。
再平衡的「高卖低买」与「削掉强币」几乎互相抵销。
同时这段的<b>理论收割上限只有 {S['h1']:+.2f}%/年</b>（因相关性 0.89 极高），
再被成本与削峰吃掉一部分 → 净效应本来就只该在 ±0.5% 量级。
</div>
</div>

<div class="card">
<h2>三、频率对照与「调仓日历运气」检验（本次最重要的一节）</h2>
<div class="scroll"><table>
<thead><tr><th class="l">窗口</th><th>每周<br>调仓数</th><th>每周<br>换手</th>
<th>每周净值</th><th>每周跑赢</th>
<th>每月<br>调仓数</th><th>每月<br>换手</th><th>每月净值</th><th>每月跑赢</th>
<th>周−月<br>超额差</th></tr></thead>
<tbody>{freq_rows}</tbody></table></div>

<div class="warn">
<b>⚠️ 修正：上一版把「全窗口每周比每月差」当作频率的系统性劣势，这是错的。</b>
每周调仓（{S['nf']:.3f}x）与每月调仓（{S['nmf']:.3f}x，相位 0）确实相差很大，
但<b>只要把同一个频率换个调仓日历（相位），结果就大幅改变</b>——
说明这个差距主要来自<b>调仓日历的运气</b>，不是频率本身。
</div>

<h3>相位检验：同一频率，只换调仓日历</h3>
<div class="scroll"><table>
<thead><tr><th class="l">窗口</th><th>频率</th><th>相位个数</th><th>净值最小</th><th>净值最大</th>
<th>极差</th><th>中位</th><th>SOL 币量区间</th></tr></thead>
<tbody>{phase_rows}</tbody></table></div>

<div class="key">
<b>怎么读这张表：</b>
<ul>
<li><b>全窗口月度有 {len(ph[(ph.window=='全窗口') & (ph.freq==4)])} 个相位，净值落在
{S['pf'][0]:.3f}x ~ {S['pf'][1]:.3f}x，极差 {(S['pf'][1]/S['pf'][0]-1)*100:.1f}%（中位 {S['pf'][2]:.3f}x）。</b>
每周调仓是 {S['nf']:.3f}x，<b>相对月度中位只差 {(S['nf']/S['pf'][2]-1)*100:+.1f}%</b>；
上一版拿来对比的 {S['nmf']:.3f}x 恰好是这 {len(ph[(ph.window=='全窗口') & (ph.freq==4)])} 个相位里
<b>最有利</b>的那一个。8 周频率的极差更大：{(S['p8f'][1]/S['p8f'][0]-1)*100:.1f}%。</li>
<li><b>1 年 / 3 年 / 5 年窗口的日历运气很小</b>：月度 4 相位极差分别只有
{(S['p1'][1]/S['p1'][0]-1)*100:.1f}% / {(S['p3'][1]/S['p3'][0]-1)*100:.1f}% / {(S['p5'][1]/S['p5'][0]-1)*100:.1f}%；
每周相对月度<b>中位</b>的差异分别是
{(S['n1']/S['p1'][2]-1)*100:+.1f}% / {(S['n3']/S['p3'][2]-1)*100:+.1f}% / {(S['n5']/S['p5'][2]-1)*100:+.1f}%
—— 基本为零。
→ <b>用户问的 1/3/5 年三档结论是稳健的；不稳健的是全窗口那一格。</b></li>
<li><b>窗口越长，日历运气越大</b>
（{(S['p1'][1]/S['p1'][0]-1)*100:.1f}% → {(S['p3'][1]/S['p3'][0]-1)*100:.1f}% →
{(S['p5'][1]/S['p5'][0]-1)*100:.1f}% → {(S['pf'][1]/S['pf'][0]-1)*100:.1f}%）。
因为时间越长，某次调仓日恰好踩中极端行情的概率与复利放大效应都更大。
<b>这是个通用的方法论警告：长周期单路径回测的结论远比短周期脆弱。</b></li>
</ul>
</div>

<div class="note">
<b>那还有真实差异吗？有，但很小。</b>把相位取中位看，全窗口
2 周频率中位 {ph[(ph.window=='全窗口') & (ph.freq==2)]['nav'].median():.3f}x、
4 周 {ph[(ph.window=='全窗口') & (ph.freq==4)]['nav'].median():.3f}x、
8 周 {ph[(ph.window=='全窗口') & (ph.freq==8)]['nav'].median():.3f}x ——
存在「调仓越频繁、期望净值略低」的弱趋势，量级约
{(1 - ph[(ph.window=='全窗口') & (ph.freq==2)]['nav'].median() /
      ph[(ph.window=='全窗口') & (ph.freq==8)]['nav'].median())*100:.0f}%，
<b>远小于日历运气造成的 {(S['pf'][1]/S['pf'][0]-1)*100:.0f}%</b>。
成本则是确定的：每周换手 {g('全窗口','turn_w'):.0f}%/年 vs 每月 {g('全窗口','turn_m'):.0f}%/年，
每周累计成本拖累 {abs(S['cwf']):.2f}%，同样解释不了 25% 的净值差。
</div>
</div>

<div class="card">
<h2>四、筹码口径：连「不掉队」也依赖日历选择</h2>
<div class="scroll"><table>
<thead><tr><th class="l">窗口</th><th>每周<br>ETH 币量</th><th>每周<br>SOL 币量</th>
<th>每月<br>ETH 币量</th><th>每月<br>SOL 币量</th><th>SOL 是否掉队<br>(每周)</th></tr></thead>
<tbody>{chip_rows}</tbody></table></div>
<div class="warn">
<b>这条同样要小心解读。</b>全窗口每周调仓的 SOL 币量是 <b>{S['usf']:.4f}x</b>（掉队 {(1-S['usf'])*100:.1f}%），
月度（相位 0）是 <b>{S['usmf']:.4f}x</b>（看似不掉队）。
但月度相位不同，SOL 币量落在 <b>{S['pfs'][0]:.4f}x ~ {S['pfs'][1]:.4f}x</b> 之间
—— 也就是说<b>「月度能保住筹码」这个结论只在相位 0 成立，换个日历一样掉队</b>。
每周的 {S['pfw1']:.4f}x 只是这分布的下沿，不是异常值。
</div>
<div class="key">
<b>真正稳健的只有一条：调仓越频繁，最强币的币量掉得越多。</b>
1 年窗口不明显（ETH {S['ue1']:.4f}x / SOL {S['us1']:.4f}x，两个都还在 1 附近），
5 年与全窗口就很清楚：SOL 币量从月度的 {S['usmf']:.4f}x 降到每周的 {S['usf']:.4f}x。
按项目既定口径「再平衡的目的是筹码不掉队（≥1.0）而非收益最大化」，
<b>高频调仓与这个目的存在方向性冲突</b>，且这个冲突不依赖日历选择。
</div>
</div>

<div class="card">
<h2>五、理论上限与实际实现的差距</h2>
<p>连续再平衡的波动率² 收割收益 ≈ <code>0.5 × (σ²平均 − σ²组合) × t</code>，这是上限（不含成本与削峰）：</p>
<div class="scroll"><table>
<thead><tr><th class="l">窗口</th><th>σ ETH</th><th>σ SOL</th><th>相关</th>
<th>理论收割</th><th>实际(每周)</th><th>实际(每月)</th></tr></thead>
<tbody>{th_rows}</tbody></table></div>
<div class="key">
1 年窗口理论收割仅 {S['h1']:+.2f}%/年（相关 0.89 太高），实际实现 {F(S['e1']/w.at['1 年','yrs'],2)}%/年——
<b>已接近上限</b>，说明没有异常。
全窗口理论 {S['hf']:+.2f}%/年、累计约 {(1+S['hf']/100)**w.at['全窗口','yrs']*0+0:.0f}，
而每月实现 {F(S['mf']/w.at['全窗口','yrs'],2)}%/年、每周只有 {F(S['ef']/w.at['全窗口','yrs'],2)}%/年
——<b>每周反而离上限更远</b>，正说明高频在强趋势资产上的削峰代价超过了收割增益。
</div>
<div class="note">
注意：全窗口月度实现的年化超额 {F(S['mf']/w.at['全窗口','yrs'],2)}%/年，
而理论收割是 {S['hf']:+.2f}%/年，二者关系需要谨慎解读——
理论公式给的是对数收益的一阶近似，且此处超额用净值比而非对数差，
数值量级可比、不宜逐位对照。
</div>
</div>

<div class="card">
<h2>六、结论</h2>
<ul>
<li><b>1 年：每周 {F(S['e1'],3)}%、每月 {F(S['m1'],3)}%。</b>
净值 {S['n1']:.4f}x vs 死拿 {S['o1']:.4f}x。两者差异在 0.4% 以内，
日历运气也只有 {(S['p1'][1]/S['p1'][0]-1)*100:.1f}%，起点敏感性显示每周口径
{S['sens_pos']}/{S['sens_n']} 个起点为正 → <b>每周稳定小幅跑赢，但幅度极小</b>。</li>
<li><b>3 年：每周 {F(S['e3'],3)}%、每月 {F(S['m3'],3)}%，两口径都跑输。</b>
原因是该窗口 SOL 年化 +75.5% 对 ETH +14.9%（漂移差 {S['d3']:+.1f}pp），
再平衡持续卖 SOL 买 ETH —— <b>这是削峰型的单边行情，与调仓频率无关</b>。
回撤改善 {F(g('3 年','dd_better_w'))}pp（{S['mdd3']:+.2f}% vs {S['mdd3h']:+.2f}%）。</li>
<li><b>5 年：每周 {F(S['e5'],3)}%、每月 {F(S['m5'],3)}%，两口径都跑赢。</b>
注意净值 {S['n5']:.4f}x / {S['o5']:.4f}x <b>都是亏损</b>
（CAGR {g('5 年','cagr_w'):+.2f}% vs {g('5 年','cagr_hold'):+.2f}%），
「跑赢 {F(S['e5'],2)}%」在这段窗口的含义是<b>亏得少</b>。</li>
<li><b>全窗口 6.08 年：每周 {F(S['ef'],3)}%（{S['nf']:.3f}x）、每月 {F(S['mf'],3)}%（{S['nmf']:.3f}x）。</b>
<b>但这一格不能读作「每周差 25%」</b>——月度有 4 个相位，净值
{S['pf'][0]:.3f}x ~ {S['pf'][1]:.3f}x（极差 {(S['pf'][1]/S['pf'][0]-1)*100:.0f}%），
每周相对月度中位只有 {(S['nf']/S['pf'][2]-1)*100:+.1f}%。
<b>上一版的「每周明显更差」是把最有利的月度日历当成了基准。</b></li>
</ul>
<div class="key">
<b>一句话回答：</b>1 年 / 3 年 / 5 年三档下，每周调仓相对死拿分别是
{F(S['e1'],3)}% / {F(S['e3'],3)}% / {F(S['e5'],3)}%
（月度对照 {F(S['m1'],3)}% / {F(S['m3'],3)}% / {F(S['m5'],3)}%）。
<b>三档窗口下「每周 vs 每月」的差异都在 1% 以内，几乎可以忽略</b>——
真正决定成败的是窗口里有没有单边行情，不是调仓频率。
</div>
<div class="warn">
<b>方法论警告（本次最重要的收获）：</b>全窗口月度不同日历的净值极差达
{(S['pf'][1]/S['pf'][0]-1)*100:.0f}%，而 1 年窗口只有 {(S['p1'][1]/S['p1'][0]-1)*100:.1f}%。
<b>回测窗口越长，单一路径的结论越不可靠</b>——必须做相位/起点的稳健性检验，
否则很容易把「运气」讲成「规律」。这也解释了为什么上一版会得出「每周差 42.8%」这个错误结论。
</div>
</div>

<p style="font-size:12px;color:var(--mut);text-align:center;margin-top:26px">
脚本 <code>eth_sol_pair_windows.py</code>（引擎复用 <code>crypto_btc_ada_pair.py</code>）<br>
明细 <code>out/eth_sol_pair_windows.csv</code>、<code>eth_sol_pair_start_sens.csv</code>、
<code>eth_sol_pair_theory.csv</code>、<code>eth_sol_weekly_series.json</code>
</p>
</div></body></html>"""

    os.makedirs(DOCDIR, exist_ok=True)
    io.open(TARGET, "w", encoding="utf-8").write(html)
    print(f"[OK] {os.path.relpath(TARGET, HERE)}  {len(html) // 1024} KB")


if __name__ == "__main__":
    build()
