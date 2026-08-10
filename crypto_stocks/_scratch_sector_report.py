"""生成赛道整合 + 下一轮预判 HTML 报告 (读取 consolidate 的 json)"""
import json, html
J = json.load(open('_scratch_sector_consolidate.json'))

sec_map = J['sector_map']
cycle   = J['cycle_returns']
cur     = J['current_rs']
pred    = J['next_round_prediction']

# ---- 赛道映射表行 ----
map_rows = ""
for sec, coins in sec_map.items():
    map_rows += f"<tr><td class='sec'>{sec}</td><td class='cnt'>{len(coins)}</td><td>{', '.join(coins)}</td></tr>"

# ---- 周期领涨表 ----
cyc_blocks = ""
for cname, d in cycle.items():
    rows = ""
    for sec, v in d.items():
        if v[0] is None:
            rows += f"<tr><td>{sec}</td><td class='na'>未上市</td><td class='na'>—</td></tr>"
        else:
            rcls = 'up' if v[0] >= 0 else 'down'
            rscls = 'up' if v[1] >= 0 else 'down'
            rows += f"<tr><td>{sec}</td><td class='{rcls}'>{v[0]:+.1f}%</td><td class='{rscls}'>{v[1]:+.1f}pp</td></tr>"
    cyc_blocks += f"<div class='cyc'><h4>{cname}</h4><table><tr><th>赛道</th><th>累计收益</th><th>RS vs BTC</th></tr>{rows}</table></div>"

# ---- 当前 RS 快照 (热=饱和, 冷=早期) ----
cur_rows = ""
for sec, v in sorted(cur.items(), key=lambda x: x[1][1], reverse=True):
    hot = v[1] >= 15
    cold = v[1] <= -15
    cls = 'hot' if hot else ('cold' if cold else 'mid')
    tag = '🔥饱和' if hot else ('❄️早期' if cold else '—')
    cur_rows += f"<tr><td>{sec}</td><td class='{cls}'>{v[0]:+.1f}pp</td><td class='{cls}'>{v[1]:+.1f}pp</td><td class='{cls}'>{tag}</td></tr>"

# ---- 下一轮概率排名 ----
maxp = max(p['prob'] for p in pred)
prob_rows = ""
for p in pred:
    w = p['prob']/maxp*100
    top = 'top' if p['prob']>=11.8 else ''
    note = {'RWA / 真实资产':'#1 真实经济连接+政策尾风','DePIN / AI基建':'#2 AI基础设施延伸',
            '模块化 / DA':'早期但尾风较弱','AI × 加密':'十年宏观主题,但2024已部分领涨=成熟度风险',
            '基础设施':'预言机/域名,常做β','存储 / 数据':'FIL/AR,周期性强',
            'GameFi / 元宇宙':'2021霸主,需等下一轮复苏','L1 智能合约公链':'已成熟,渗透见顶',
            'DeFi / DEX':'2020饱和,难再爆发','隐私 / 匿名':'当前极热=将均值回归',
            'L2 / 扩容':'当前偏热,且2024已洗','平台币':'当前偏热(BNB+OKB),防御末段',
            '链上永续交易所 / On-chain Deriv DEX':'真实收入/用途,买旧幸存者框架(DYDX+GMX)加持'}.get(p['sector'],'')
    prob_rows += f"""<tr class='{top}'><td>{p['sector']}</td><td class='p'>{p['prob']:.1f}%</td>
      <td><div class='bar'><div class='fill' style='width:{w:.0f}%'></div></div></td>
      <td class='note'>{note}</td></tr>"""

HTML = f"""<!doctype html><html lang='zh'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>加密赛道整合 & 下一轮领涨预判</title>
<style>
*{{box-sizing:border-box}} body{{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;
 background:#f5f6f8;color:#1f2430;margin:0;padding:32px;line-height:1.6}}
.wrap{{max-width:1080px;margin:0 auto}}
h1{{font-size:26px;margin:0 0 4px}} h2{{font-size:19px;margin:34px 0 10px;border-left:4px solid #2b6cb0;padding-left:10px}}
h3{{font-size:15px;color:#555;font-weight:500;margin:0 0 18px}}
h4{{font-size:14px;margin:0 0 6px;color:#2b6cb0}}
.card{{background:#fff;border:1px solid #e4e7ec;border-radius:12px;padding:18px 22px;margin:14px 0;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
p{{margin:8px 0}} .lead{{font-size:15px;color:#333}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{padding:7px 10px;text-align:left;border-bottom:1px solid #eef0f3}}
th{{color:#667;font-weight:600;background:#fafbfc}}
.cyc-wrap{{display:flex;gap:14px;flex-wrap:wrap}} .cyc{{flex:1;min-width:230px;background:#fafbfc;border:1px solid #eef0f3;border-radius:10px;padding:12px}}
.up{{color:#c0392b;font-weight:600}} .down{{color:#1e7d4f;font-weight:600}} .na{{color:#aaa}}
.hot{{color:#c0392b;font-weight:700}} .cold{{color:#1e6fd0;font-weight:700}} .mid{{color:#888}}
.sec{{font-weight:600;color:#2b6cb0}} .cnt{{color:#888;text-align:center}}
.bar{{background:#eef0f3;border-radius:6px;height:16px;overflow:hidden}} .fill{{background:linear-gradient(90deg,#2b6cb0,#4f9cf0);height:100%}}
tr.top{{background:#fff7e6}} tr.top td.p{{color:#c0392b;font-weight:800;font-size:15px}}
.note{{color:#777;font-size:12px}} .p{{font-weight:700}}
.kpi{{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0}} .kpi div{{flex:1;min-width:160px;background:#f0f6ff;border:1px solid #d6e6fb;border-radius:10px;padding:12px}}
.kpi b{{display:block;font-size:22px;color:#2b6cb0}} .kpi span{{font-size:12px;color:#667}}
.tag{{display:inline-block;background:#2b6cb0;color:#fff;border-radius:20px;padding:2px 12px;font-size:12px;margin:2px 4px 2px 0}}
.warn{{background:#fff4f4;border:1px solid #f3c9c9;border-radius:10px;padding:12px 16px;color:#a33;font-size:13.5px}}
footer{{color:#99a;font-size:12px;margin-top:30px;text-align:center}}
</style></head><body><div class='wrap'>
<h1>加密赛道整合 & 下一轮(≈2028)领涨预判</h1>
<h3>数据驱动 · 零前视 · 61 币完整归并到 13 个互斥整合赛道</h3>

<div class='card lead'>
<b>核心论点（用户洞察）：</b>加密的"赛道"本质是<b>有限叙事</b>——不像股票有海量实体经济垂直行业可对应，
加密只有约十来个可穷举的叙事桶（L1/L2/DeFi/AI/DePIN/RWA/GameFi/隐私/存储/模块化/基础设施/平台币），
且它们只是<b>换皮轮动</b>。正因为有限且可穷举，<b>预判下一轮领涨反而比股市更可行</b>：
轮动律 = <i>本轮"早期/边缘"的题材，下一轮成熟爆发</i>。
</div>

<h2>一、整合赛道映射（61 币 → 13 互斥桶）</h2>
<div class='card'><table>
<tr><th>整合赛道</th><th>币数</th><th>成分</th></tr>{map_rows}</table></div>

<h2>二、历史每轮上行窗：赛道领涨排名（纯数据，无手标）</h2>
<div class='card'><div class='cyc-wrap'>{cyc_blocks}</div>
<p class='lead'>读法：每轮真正爆发的叙事都不同，且<b>上一轮的霸主到下一轮基本被洗干净</b>。
2021 的 GameFi(+17938%)/L2(+8867%)/AI基建(+3351%) → 2024 全部转负（GameFi −71% / L2 −72% / AI −51% / 模块化 −90%）。</p></div>

<h2>三、当前（2026-08-07）赛道温度：谁热=饱和，谁冷=早期</h2>
<div class='card'><table>
<tr><th>赛道</th><th>13w RS</th><th>26w RS</th><th>状态</th></tr>{cur_rows}</table>
<div class='warn'>⚠️ <b>当前最热的（隐私 +59pp、平台币 +25pp、L2 +7pp）正是晚期防御/CEX 玩法，已近均值回归——它们几乎不可能领下一轮。</b>
下一轮领涨必从<b>现在被洗出去的冷赛道</b>（RWA −19pp / AI −50pp / DePIN −51pp / 模块化 −90pp）里出。</div></div>

<h2>四、下一轮（≈2028 减半后）领涨赛道 · 概率排序</h2>
<div class='card'><table>
<tr><th>整合赛道</th><th>概率</th><th></th><th>逻辑</th></tr>{prob_rows}</table>
<div class='kpi'>
<div><b>RWA</b><span>我的 #1 最高概率</span></div>
<div><b>DePIN/AI基建</b><span>近并列 #2</span></div>
<div><b>AI×加密</b><span>十年主题,但已部分领涨</span></div>
</div>
<p class='lead'><b>我的判断：</b>下一轮领涨冠军最可能是 <b>RWA / 真实资产上链</b>（与 DePIN/AI基建 几乎并列）。
理由：① 2024 它只是"刚出生"（ONDO 单币 launched，整赛道未动，26w RS −19pp=早期）；
② 渗透率仅 ~1%（上行空间最大）；③ <b>它是唯一带真实经济连接的加密赛道</b>（国债/股票/信用上链 + 机构 BlackRock），
政策尾风最强（GENIUS/稳定币法案）；④ 完美契合轮动律（上一轮边缘→下轮成熟）。
<b>AI×加密</b>是十年宏观主题、不会缺席，但 2023末–2024 已部分领涨（FET/RENDER），存在成熟度/买在前高风
险，故作为"高确定性但难择时"的并列候选。当前最热的隐私/平台币/L2 概率最低——它们在见顶。</p></div>

<h2>五、给选股引擎的落地建议</h2>
<div class='card'>
<p>① <b>赛道倾斜选股</b>（已设计 `offense_top_n(mode='data_theme_lead')`）：用赛道指数 RS 检测领涨题材倾斜，
替代手写 `PHASE_HISTORY` 前视手标（A股已清算过的同款偏差）。</p>
<p>② <b>减半相位门控</b>：高位（euphoria/crash）强制退出高β题材，保留低β/防御——吸收"山寨比BTC早见顶9.9月"。</p>
<p>③ <b>下一轮预埋观察清单</b>：RWA(ONDO/MANTRA/RIO/POLYX)、DePIN(HNT/AKT/PEAQ)、模块化(TIA/DYM)、AI-Agent 子层。
<b>严守 OOS 双维 |t|≥2 铁律</b>后，方可进默认。</p>
</div>

<footer>生成于 2026-08-11 · 数据区间 2017-08-11~2026-08-07 · 零前视 · 复现: _scratch_sector_consolidate.py</footer>
</div></body></html>"""

open('crypto_sector_forecast_2026-08.html','w',encoding='utf-8').write(HTML)
print("written crypto_sector_forecast_2026-08.html", len(HTML), "bytes")
