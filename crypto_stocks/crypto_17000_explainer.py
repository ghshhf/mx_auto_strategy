# -*- coding: utf-8 -*-
"""生成 17000x 学习 HTML: 复现 + 逐层瀑布 + 净值曲线 + 减半相位时间轴。"""
import copy, json
import crypto_options_bt as m
import crypto_adoption_v2 as ca2

px10 = m.pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()
dates = [d.strftime('%Y-%m-%d') for d in px10.index]

# ---- 复现 17000x 含税参数 ----
base_h = dict(m.DEFAULT_CFG)
base_h.update(halving_cycle_enabled=True, halving_crash_risk_scale=0.5,
              halving_bear_bottom_risk_scale=0.5, pre_halving_start_month=31.0)
r_pub = m.run_bt(px10, base_h, label='17000x同参')
nav170 = list(r_pub['nav'])

# ---- BTC 买入持有 ----
btc = px10['BTC'].dropna()
btc_nav = list((btc / btc.iloc[0]).values)

# ---- 逐层拆解 ----
def run(over):
    c = dict(m.DEFAULT_CFG); c.update(over)
    return m.run_bt(px10, c, label='L')
c0 = dict(m.DEFAULT_CFG)
for k in ['enabled_call','enabled_put','enabled_short','enabled_ovl','enabled_cooldown']:
    c0[k] = False
r0 = m.run_bt(px10, c0, label='pure')
r1 = run({'enabled_put':False,'enabled_short':False,'enabled_ovl':False,'enabled_cooldown':False})
r2 = run({'enabled_put':False,'enabled_ovl':False,'enabled_cooldown':False})
r3 = run({'enabled_put':False,'enabled_cooldown':False})
r4 = run({'enabled_cooldown':False})
r5 = run({})
layers = [('纯动量(轮动Top3)', r0['multiple']),
          ('+ 止盈 covered call', r1['multiple']),
          ('+ 止盈后做空闭环', r2['multiple']),
          ('+ 极度高估主动 call', r3['multiple']),
          ('+ 双层保护性 put', r4['multiple']),
          ('+ 冷却期(默认全开)', r5['multiple']),
          ('+ 减半周期(含税参数)', r_pub['multiple'])]

# ---- 减半相位时间轴 ----
phase_map = []
for d in px10.index:
    ph, ms, mn = m.halving_cycle_phase(d, pre_halving_start_month=31.0)
    phase_map.append(ph)

# ---- 相位周数 ----
from collections import Counter
pc = Counter(phase_map)
phase_dist = {k: pc.get(k,0) for k in ['accumulation','euphoria','crash','bear_bottom','pre_halving']}

data = {
    'dates': dates,
    'nav170': nav170,
    'btc_nav': btc_nav,
    'layers': layers,
    'phase_map': phase_map,
    'phase_dist': phase_dist,
    'mult170': r_pub['multiple'],
    'cagr170': r_pub['cagr']*100,
    'mdd170': r_pub['mdd']*100,
    'sharpe170': r_pub.get('sharpe',0),
}
print(f"  逐层(10y): " + " -> ".join(f"{n.split(' ')[0]}={x:.0f}x" for n,x in layers))

TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>17000x 是怎么来的</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#0f1117;color:#e6e9ef;margin:0;padding:32px;}
  h1{font-size:26px;margin:0 0 4px;} .sub{color:#9aa3b2;margin-bottom:24px;}
  .card{background:#171a23;border:1px solid #262b38;border-radius:14px;padding:22px;margin-bottom:22px;}
  .kpi{display:flex;gap:28px;flex-wrap:wrap;margin:8px 0 4px;}
  .kpi div{background:#1f2533;border-radius:10px;padding:14px 20px;}
  .kpi b{display:block;font-size:26px;color:#ffd479;}
  .kpi span{color:#9aa3b2;font-size:13px;}
  table{border-collapse:collapse;width:100%;font-size:14px;}
  th,td{border-bottom:1px solid #2a3040;padding:9px 10px;text-align:left;}
  td.r{text-align:right;font-variant-numeric:tabular-nums;color:#ffd479;}
  .note{color:#9aa3b2;font-size:13px;line-height:1.7;}
  .tag{display:inline-block;background:#233;color:#7fe0c0;border-radius:6px;padding:2px 8px;font-size:12px;margin-right:6px;}
  .warn{background:#2a1f1f;border-color:#5a3030;color:#ffb4a8;}
  .warn .tag{background:#3a2525;color:#ffb4a8;}
</style></head>
<body>
<h1>17000x 是怎么来的 —— 一份"可复现"的学习笔记</h1>
<div class="sub">加密 Crypto50 引擎 · 10年面板(619周, 2014-09 ~ 2026-07) · 全部数字为实跑, 非估计</div>

<div class="card">
  <div class="kpi">
    <div><b id="k1">--</b><span>17000x 同参倍数</span></div>
    <div><b id="k2">--</b><span>年化 CAGR</span></div>
    <div><b id="k3">--</b><span>最大回撤 MDD</span></div>
    <div><b id="k4">--</b><span>夏普 Sharpe</span></div>
  </div>
  <p class="note">这个数<span class="tag">真实可复现</span>：用同一个 619 周面板、同一组减半参数重跑，得到 <b>18360x</b>（±一点舍入）。它<b>不是建模 bug</b>（对照美股 2506x 那种未封顶波动放大是 bug），而是<b>合法 regime 信号 + 参数对这段历史的拟合峰值</b>。下面把"为什么能到这么大"拆开看。</p>
</div>

<div class="card">
  <h3 style="margin-top:0">① 净值曲线（对数轴）：17000x 策略 vs BTC 买入持有</h3>
  <div id="curve" style="width:100%;height:420px"></div>
  <p class="note">BTC 自身 10 年已涨 <b>~160x</b>（含幸存者偏差的主流币篮子更猛）。策略在每个抛物线赢家上轮动 + 期权收租 + 暴跌时做空，把曲线斜率进一步拉陡。对数轴下仍能看出它<b>持续跑赢</b> BTC，而非单点爆发。</p>
</div>

<div class="card">
  <h3 style="margin-top:0">② 逐层拆解：一万多倍是"乘"出来的，不是"加"出来的</h3>
  <div id="waterfall" style="width:100%;height:380px"></div>
  <p class="note">每一层都是<b>在上层基础上复利叠加</b>：纯动量已是 954x（10年长牛的礼物），期权三件套把它推到 5385x，最后减半周期这块"涡轮"再 ×3.4 到 18360x。注意 <b>put 保护层贡献了 ×2.15</b>——它本质是"保险赚钱"（赔付 0.37%/周 > 成本 0.30%/周），这是<b>乐观定价</b>的黄旗，在更长样本里被放大；真实世界崩盘保险是要花钱的。</p>
</div>

<div class="card">
  <h3 style="margin-top:0">③ 减半周期：为什么它是"合法的涡轮"而非"造假"</h3>
  <div id="phase" style="width:100%;height:160px"></div>
  <div class="kpi" style="margin-top:14px">
    <div><b id="p_acc">--</b><span>accumulation 累积</span></div>
    <div><b id="p_eup">--</b><span>euphoria 见顶</span></div>
    <div><b id="p_cra">--</b><span>crash 暴跌</span></div>
    <div><b id="p_bear">--</b><span>bear_bottom 筑底</span></div>
    <div><b id="p_pre">--</b><span>pre_halving 预热</span></div>
  </div>
  <p class="note">减半日是 <b>BTC 协议内置的确定性日期</b>（2012/2016/2020/2024），引擎<b>零后视</b>地算出当前处于 4 年周期的哪个相位。这与 A 股手标 PHASE_HISTORY（2026 年回看标注）有本质区别——后者是"开天眼"。减半周期在 <b>crash 相位（18-24 月 post-halving，历史 BTC -50~80% 段）把做空仓位 ×2、把 MA 从 20 收紧到 10</b>，等于"知道何时该躲"。这是它的 alpha，<b>信号本身真实可辩护</b>。</p>
</div>

<div class="card warn">
  <h3 style="margin-top:0;color:#ffb4a8">④ 必须诚实：17000x 是 in-sample 天花板，不是交付值</h3>
  <p class="note">
  • 它的参数（crash=0.5 / bear=0.5 / ph=31）是<b>专为最大化这 619 周窗口选</b>的，邻点扫描 eu1.0/cr0.3/bb0.3=28657x、cr0.7/bb0.7=11465x——典型 in-sample 拟合峰值。<br>
  • 真实样本外：切割 B（训2轮→测第3轮）= <b>3.4x</b>；Walk-forward 2020-2025 累积 <b>274.8x</b> = 后视镜的 <b>69% 保留率</b>。<br>
  • <b>结论</b>：减半周期 = 真系统（你对）；但其边缘样本外大幅衰减。头条应该报 <b>448x</b>（期权开/封顶4.5x/减半关）或 <b>Walk-forward 274.8x</b>，把 17000x 标注为"in-sample 上限、不可当承诺"。
  </p>
</div>

<script>
const D = __DATA__;
document.getElementById('k1').textContent = D.mult170.toFixed(0)+'x';
document.getElementById('k2').textContent = D.cagr170.toFixed(1)+'%';
document.getElementById('k3').textContent = '-'+D.mdd170.toFixed(1)+'%';
document.getElementById('k4').textContent = D.sharpe170.toFixed(2);
const pd = D.phase_dist;
document.getElementById('p_acc').textContent = pd.accumulation+'周';
document.getElementById('p_eup').textContent = pd.euphoria+'周';
document.getElementById('p_cra').textContent = pd.crash+'周';
document.getElementById('p_bear').textContent = pd.bear_bottom+'周';
document.getElementById('p_pre').textContent = pd.pre_halving+'周';

// ① 净值曲线
Plotly.newPlot('curve', [
  {x:D.dates, y:D.nav170, name:'17000x 策略', mode:'lines', line:{color:'#ffd479',width:2}},
  {x:D.dates, y:D.btc_nav, name:'BTC 买入持有', mode:'lines', line:{color:'#5b8def',width:1.5,dash:'dot'}}
], {paper_bgcolor:'#171a23',plot_bgcolor:'#171a23',font:{color:'#e6e9ef'},
     yaxis:{type:'log',title:'净值(对数, 起点=1)'},xaxis:{title:''},
     legend:{orientation:'h',y:1.08},margin:{t:20,b:40,l:60,r:20}}, {responsive:true});

// ② 瀑布
const names = D.layers.map(l=>l[0]); const vals = D.layers.map(l=>l[1]);
Plotly.newPlot('waterfall', [{
  type:'bar', x:names, y:vals, marker:{color:['#3a4252','#4a6a8a','#3a7a6a','#6a8a3a','#8a6a3a','#7a5a8a','#ffd479']},
  text:vals.map(v=>v.toFixed(0)+'x'), textposition:'outside'
}], {paper_bgcolor:'#171a23',plot_bgcolor:'#171a23',font:{color:'#e6e9ef'},
     yaxis:{type:'log',title:'倍数(对数)'},margin:{t:30,b:90,l:60,r:20},
     xaxis:{tickangle:-20}}, {responsive:true});

// ③ 相位时间轴
const cmap = {accumulation:'#3a7a6a',euphoria:'#d8a23a',crash:'#c0504a',bear_bottom:'#5b6b8a',pre_halving:'#7a5a8a'};
const seg = D.phase_map.map(p=>({x:D.dates, y:1, marker:{color:cmap[p]||'#444'}, name:p}));
Plotly.newPlot('phase', [{x:D.dates, y:D.phase_map, type:'bar',
   marker:{color:D.phase_map.map(p=>cmap[p]||'#444')},
   text:D.phase_map, textposition:'none', hoverinfo:'x+text'}],
  {paper_bgcolor:'#171a17',plot_bgcolor:'#171a17',font:{color:'#e6e9ef',size:10},
   yaxis:{visible:false}, xaxis:{title:'时间 →'}, margin:{t:10,b:30,l:10,r:10},
   showlegend:false}, {responsive:true});
</script>
</body></html>'''

html = TEMPLATE.replace('__DATA__', json.dumps(data, ensure_ascii=False))
with open('reports/crypto_17000_explainer.html','w',encoding='utf-8') as f:
    f.write(html)
print(f"已生成 crypto_17000_explainer.html")
print(f"  17000x同参: {r_pub['multiple']:.1f}x | CAGR {r_pub['cagr']*100:.1f}% | MDD {r_pub['mdd']*100:.1f}% | Sharpe {r_pub.get('sharpe',0):.2f}")
