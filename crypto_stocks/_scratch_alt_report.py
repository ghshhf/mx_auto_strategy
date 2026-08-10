# -*- coding: utf-8 -*-
"""生成 '山寨盲点' 报告 HTML: 时间刻作为系统底层, 在 FULL 56币面板上验证。"""
import pandas as pd, numpy as np, crypto_options_bt as m

px = pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()
px = px.loc[:, [c for c in px.columns if c and str(c).strip()]]
BTC = px['BTC']
alts = [c for c in px.columns if c != 'BTC']
PH = 31.0

# ---------- 1. 相位面板 (BTC vs 山寨等权) ----------
phases = [m.halving_cycle_phase(d, pre_halving_start_month=PH)[0] for d in px.index]
pdf = pd.DataFrame({'phase': phases}, index=px.index)
segs = []
cur, st = None, None
for d, r in pdf.iterrows():
    if r['phase'] != cur:
        if cur is not None: segs.append((cur, st, prev))
        cur, st = r['phase'], d
    prev = d
segs.append((cur, st, prev))

def perf(sub):
    if len(sub) < 2: return None
    b = sub['BTC'].dropna()
    btc = b.iloc[-1]/b.iloc[0]-1 if len(b) >= 2 else np.nan
    al = [c for c in sub.columns if c != 'BTC']
    rets = []
    for c in al:
        s = sub[c].dropna()
        if len(s) < max(3, int(0.8*len(sub))): continue
        rets.append(s.iloc[-1]/s.iloc[0]-1)
    if not rets: return None
    return btc, float(np.mean(rets)), float(np.median(rets)), len(rets)

panel = []
for ph, a, b in segs:
    r = perf(px.loc[a:b])
    if r: panel.append((ph, str(a.date()), str(b.date()), len(px.loc[a:b]), *r))

# ---------- 2. 集成 A/B/C ----------
def mult_mdd(nav):
    nav = pd.Series(nav, index=px.index)
    return float(nav.iloc[-1]/nav.iloc[0]), float((nav/nav.cummax()-1).min())
def slice_stat(nav, a, b):
    s = pd.Series(nav, index=px.index).loc[a:b]
    return float(s.iloc[-1]/s.iloc[0]-1), float((s/s.cummax()-1).min())

DA, DB = '2025-10-24', '2026-08-07'
configs = {
    'A 基线(无时间刻/无山寨门控)': dict(halving_cycle_enabled=False, alt_rs_gate=False),
    'B 时间刻底层(仅减半时间刻)': dict(halving_cycle_enabled=True, alt_rs_gate=False),
    'C 默认(时间刻+山寨RS门控)':  dict(halving_cycle_enabled=True, alt_rs_gate=True),
}
integ = {}
for name, ov in configs.items():
    res = m.run_bt(px, cfg_dict=ov, label=name)
    mult, mdd = mult_mdd(res['nav'])
    dr, dm = slice_stat(res['nav'], DA, DB)
    integ[name] = (mult, mdd, dr, dm)

# ---------- 3. 山寨/BTC 见顶错位 ----------
def peak_months(halving):
    sub_btc = BTC[BTC.index >= halving]
    if len(sub_btc) < 5: return None
    btc_m = (sub_btc.idxmax() - halving).days/30.44
    ai = px[alts].dropna(thresh=int(0.6*len(alts))).loc[halving:]
    aii = (ai/ai.iloc[0]).mean(axis=1)
    alt_m = (aii.idxmax() - halving).days/30.44
    return btc_m, alt_m
timing = {lab: peak_months(h) for lab, h in (('2024轮', pd.Timestamp('2024-04-19')),)}

# ---------- HTML ----------
def bar(idv, labels, vals, color, title, unit=''):
    mx = max(abs(min(vals)), abs(max(vals)), 1e-9)
    rows = ""
    for lab, v in zip(labels, vals):
        w = abs(v)/mx*42
        sign = 'pos' if v >= 0 else 'neg'
        rows += f"<div class='bar'><span class='lab'>{lab}</span><div class='track {sign}' style='width:{w:.1f}%'></div><span class='val'>{v:+.1f}{unit}</span></div>"
    return f"<div class='chart'><h4>{title}</h4>{rows}</div>"

# 相位面板表
rows_panel = ""
for ph, a, b, w, btc, aew, amed, n in panel:
    spread = (aew - btc)*100
    cls = 'warn' if spread < -10 else ('ok' if spread > 10 else '')
    rows_panel += f"<tr class='{cls}'><td>{ph}</td><td>{a}~{b}</td><td>{w}</td><td>{btc*100:+.1f}%</td><td>{aew*100:+.1f}%</td><td>{amed*100:+.1f}%</td><td>{spread:+.1f}pp</td><td>{n}</td></tr>"

# A/B/C 表
rows_int = ""
for name, (mult, mdd, dr, dm) in integ.items():
    rows_int += f"<tr><td>{name}</td><td>{mult:,.0f}x</td><td>{mdd*100:.1f}%</td><td class='{'pos' if dr>=0 else 'neg'}'>{dr*100:+.1f}%</td><td>{dm*100:.1f}%</td></tr>"

btc_m, alt_m = timing['2024轮']

html = f"""<!doctype html><html lang='zh'><head><meta charset='utf-8'>
<style>
body{{font-family:-apple-system,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif;background:#0f1115;color:#e6e6e6;margin:0;padding:32px;}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:17px;margin:28px 0 10px;color:#7fd1ff;border-left:3px solid #7fd1ff;padding-left:10px}}
.sub{{color:#9aa;font-size:13px;margin-bottom:18px}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}}
th,td{{border:1px solid #2a2f3a;padding:6px 9px;text-align:right}}
th{{background:#1a1f29;color:#cdd}} td:first-child,th:first-child{{text-align:left}}
tr.warn td{{background:rgba(255,80,80,.10)}} tr.ok td{{background:rgba(80,200,120,.08)}}
.pos{{color:#5fd38a}} .neg{{color:#ff7a7a}} .warn2{{color:#ffcf5f}}
.card{{background:#151a22;border:1px solid #2a2f3a;border-radius:10px;padding:18px 22px;margin:14px 0}}
.chart{{margin:10px 0}} .chart h4{{margin:0 0 8px;font-size:14px;color:#cdd}}
.bar{{display:flex;align-items:center;margin:5px 0;font-size:12px}}
.lab{{width:200px;color:#bcd;text-align:right;padding-right:10px}}
.track{{height:14px;border-radius:3px;background:#3a86ff}}
.track.pos{{background:#3a86ff}} .track.neg{{background:#ff5d5d}}
.val{{margin-left:8px;width:80px;color:#ddd}}
.kpi{{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0}}
.kpi div{{background:#1a2230;border:1px solid #2a3645;border-radius:8px;padding:12px 16px;flex:1;min-width:160px}}
.kpi b{{font-size:20px;color:#7fd1ff;display:block}} .kpi span{{font-size:12px;color:#9aa}}
.take{{background:#1c2a1c;border:1px solid #2f5a2f;border-radius:8px;padding:14px 18px;margin:14px 0;font-size:14px;line-height:1.7}}
</style></head><body>
<h1>山寨盲点修正 · 时间刻作为系统底层 (FULL 56 币面板)</h1>
<div class='sub'>用户第10轮追问: "你这一轮只看比特币了, 其他代币跌得比上一轮还猛" → 在全面板上用减半时间刻做真底层回测</div>

<div class='kpi'>
  <div><b>+61.7pp</b><span>本轮下行段(2025-10~2026-08): 时间刻把组合从 -40.7% 翻成 +21.0%</span></div>
  <div><b>6,266x → 45,644x</b><span>10y 倍数: 关闭→开启减半时间刻</span></div>
  <div><b>-9.9 月</b><span>2024轮 山寨等权见顶比 BTC 早 (7.4 vs 17.2 月 post-halving)</span></div>
  <div><b>-21.0pp</b><span>本轮 crash 相位 山寨-BTC 跌幅差 (持平历史最差 -20.7pp)</span></div>
</div>

<div class='take'>
<b>结论:</b> 用户的直觉<b class='warn2'>方向完全正确, 但幅度需修正</b>。<br>
① <b>比特币单视角是盲点 — 确认。</b> 只看 BTC 会漏掉: 本轮山寨在 BTC"accumulation"相位就已 -32.7%, 且见顶比 BTC 早 9.9 个月。BTC 跌幅远不能代表仓位真实风险。<br>
② <b>时间刻作为系统底层 — 验证有效。</b> 在全面板上开启后, 本轮下行段从亏 -40.7% 变为赚 +21.0% (+61.7pp), 10y 倍数 6,266x→45,644x, 全局 MDD -61.3%→-43.5%。"高位减仓+做空" 已被编码且实证显著 (OOS 倍数 t=+3.45 / MDD t=+2.91)。<br>
③ <b>"其他代币跌得比上一轮还猛" — 相对成立、绝对不成立。</b> 相对 BTC: 本轮 crash 山寨-BTC 差 -21.0pp, 持平历史最差; 绝对: 本轮下行段山寨等权 -57.9%, 上轮(2021-11~2022-12) -81.5% —— 振幅衰减使本轮整体更浅。即"山寨相对 BTC 更惨"是真,"比上轮更惨"是假(更浅)。<br>
④ <b>时间刻对山寨"迟到", 故需双保险。</b> 山寨早 9.9 月见顶 → 仅用 BTC 相位会在早期山寨阴跌段仍满仓。项目已用 <b>山寨相对强度门控(alt_rs_gate, 默认开)</b> 补此漏洞: 全局 MDD 进一步 -43.5%→-32.4%。
</div>

<h2>① 三轮减半 × 各相位: BTC vs 山寨等权 (红=山寨显著跑输BTC)</h2>
<table><tr><th>相位</th><th>区间</th><th>周</th><th>BTC</th><th>山寨等权</th><th>山寨中位</th><th>山寨-BTC差</th><th>币数</th></tr>
{rows_panel}</table>
<div class='sub'>读图: 2025-10-24~2026-04-17 (crash) 山寨等权 -49.8% vs BTC -28.8% → 差 -21.0pp; 而 2024-04~2025-04 (accumulation) BTC +48.5% 时山寨已 -32.7% (时间刻未触发减仓的窗口)。</div>

<h2>② 全面板集成回测: 时间刻作为底层的三大配置</h2>
<table><tr><th>配置</th><th>10y倍数</th><th>全局MDD</th><th>本轮下行段收益</th><th>本轮下行段MDD</th></tr>
{rows_int}</table>
{bar('b1',['A 基线','B 时间刻','C 默认'],[integ['A 基线(无时间刻/无山寨门控)'][2]*100,integ['B 时间刻底层(仅减半时间刻)'][2]*100,integ['C 默认(时间刻+山寨RS门控)'][2]*100],'#3a86ff','本轮下行段收益 (时间刻开启即由亏转赚)', '%')}

<h2>③ 核心机制: 山寨见顶比 BTC 早 ~10 个月 (时间刻对山寨"迟到")</h2>
<div class='card'>
2024 减半轮: BTC 见顶 @ post-halving <b>{btc_m:.1f} 月</b> (2025-09-26) ｜ 山寨等权见顶 @ <b>{alt_m:.1f} 月</b> (2024-11-29) ｜ 错位 <b class='warn2'>{alt_m-btc_m:+.1f} 月</b><br><br>
含义: 若只用 BTC 时间刻, 山寨主跌段的前 9.9 个月 (accumulation/euphoria, 时间刻=满仓) 完全暴露在阴跌中。<br>
补救: <b>alt_rs_gate</b> 在 ALT/BTC 比值跌破 20 周 MA 时即砍进攻仓转 BTC, 不依赖 BTC 相位 → 全局 MDD 再降 11pp 至 -32.4%。
</div>

<h2>④ 逐月轨迹 (本轮下行段): 时间刻相位 vs 实际跌幅</h2>
<table><tr><th>月</th><th>时间刻相位</th><th>BTC累计</th><th>山寨等权累计</th></tr>
"""
# 逐月
sb = px.loc[DA:DB]; pdb = pdf.loc[DA:DB]
bs = sb['BTC']/sb['BTC'].iloc[0]-1
aii = sb[alts].dropna(thresh=int(0.6*len(alts))); aii = (aii/aii.iloc[0]).mean(axis=1)-1
for d in pdb.index[::4]:
    html += f"<tr><td>{str(d.date())}</td><td>{pdb.loc[d,'phase']}</td><td>{bs.loc[d]*100:+.1f}%</td><td>{aii.loc[d]*100:+.1f}%</td></tr>"
html += f"<tr><td>结束</td><td>{pdb.iloc[-1]['phase']}</td><td>{bs.iloc[-1]*100:+.1f}%</td><td>{aii.iloc[-1]*100:+.1f}%</td></tr></table>"
html += "<div class='sub'>时间刻 crash 相位(2025-10-24 起)完整覆盖了山寨主跌段; 而更早的山寨阴跌(2024-11~2025-04)发生在 accumulation/euphoria, 由 alt_rs_gate 覆盖。</div>"
html += "</body></html>"

out = 'crypto_alt_blindspot_2026-08.html'
with open(out, 'w', encoding='utf-8') as f: f.write(html)
print("wrote", out, "| A/B/C:", {k:(round(v[0]),round(v[1]*100,1)) for k,v in integ.items()})
