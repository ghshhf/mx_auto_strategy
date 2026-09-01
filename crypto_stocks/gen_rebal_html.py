"""生成 index_buyhold_rebal.html — 三种指数权重(等权持有/等权周平衡/市值加权)对比报告"""
import pandas as pd, numpy as np, json, index_buyhold as ib

px, mc = ib.load()
H = ib.HORIZONS

def sweep(min_basket=0, restrict=False):
    rows = {}
    for scheme, rebal in [('equal', False), ('equal', True), ('cap', False)]:
        key = 'equal_hold' if (scheme == 'equal' and not rebal) else ('equal_rebal' if rebal else 'cap')
        rows[key] = {}
        for hlabel, wks in H.items():
            mults = []
            for i in range(len(px)):
                trad = [c for c in px.columns if pd.notna(px[c].iloc[i]) and px[c].iloc[i] > 0]
                if restrict and len(trad) < 40:
                    continue
                r = ib.nav_from(px, mc, i, scheme, wks, rebal=rebal)
                if r:
                    mults.append(r[0])
            mults = np.array(mults)
            rows[key][hlabel] = dict(
                n=len(mults), med=float(np.median(mults)),
                pos=float(np.mean(mults > 1) * 100),
                best=float(mults.max()), worst=float(mults.min()))
    return rows

all_s = sweep(0, False)
full_s = sweep(0, True)

paths = json.load(open('index_nav_paths.json'))

def fmt_rows(d, label_map):
    out = ''
    for key, lab in label_map:
        out += f'<tr><td class="lab">{lab}</td>'
        for h in H:
            r = d[key][h]
            cls = 'neg' if r['med'] < 1 else 'pos'
            out += (f'<td><span class="{cls}">{r["med"]:.2f}x</span><br>'
                    f'<small>中位{r["med"]-1:+.0%} · 赚{r["pos"]:.0f}% · 最佳{r["best"]:.1f}x · 最差{r["worst"]:.2f}x</small></td>')
        out += '</tr>'
    return out

lab_all = [('equal_hold', '等权持有(不调仓)'), ('equal_rebal', '等权周平衡(每周)'), ('cap', '市值加权(不调仓)')]

HTML = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>指数买入持有 · 三种权重对比</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
*{{box-sizing:border-box}} body{{font-family:-apple-system,"PingFang SC",sans-serif;margin:0;background:#f5f7fa;color:#1f2937;line-height:1.5}}
.wrap{{max-width:860px;margin:0 auto;padding:16px}} h1{{font-size:20px;margin:8px 0}} h2{{font-size:16px;margin:22px 0 8px}}
.card{{background:#fff;border-radius:12px;padding:14px;margin:10px 0;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{padding:8px 6px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}}
th{{background:#f0f4f8;font-weight:600}} .lab{{font-weight:600;white-space:nowrap}}
.pos{{color:#dc2626;font-weight:700}} .neg{{color:#16a34a;font-weight:700}} small{{color:#6b7280}}
.note{{font-size:12px;color:#6b7280;background:#fffbeb;border-left:3px solid #f59e0b;padding:8px 10px;border-radius:6px;margin:10px 0}}
.legend span{{display:inline-block;margin-right:14px;font-size:12px}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:middle}}
</style></head><body><div class="wrap">
<h1>指数型买入持有 · 三种权重对比</h1>
<div class="card">
<div class="legend">
<span><i class="dot" style="background:#2563eb"></i>等权持有(不调仓)</span>
<span><i class="dot" style="background:#f59e0b"></i>等权周平衡(每周)</span>
<span><i class="dot" style="background:#16a34a"></i>市值加权(不调仓)</span>
<span><i class="dot" style="background:#dc2626"></i>等权@2021-11顶部(警示)</span>
</div>
<div id="c" style="width:100%;height:380px"></div>
</div>

<h2>方法说明</h2>
<div class="card">
• <b>等权持有</b>：每币买一样多，买入后不动，权重随价格漂移。<br>
• <b>等权周平衡</b>：每周把组合重新调回等权（卖出涨多的、买回跌多的）。<br>
• <b>市值加权</b>：按当前市值快照固定权重买入，不调仓（近似指数）。<br>
<span class="note">注：真实指数会定期再平衡；本脚本"持有"语义下不调仓。"周平衡"仅对等权做了每周再平衡，市值加权未做再平衡（对比用）。</span>
</div>

<h2>全历史起点滚动（含早期仅 BTC/ETH 篮，52币面板 2017-08~2026-08）</h2>
<div class="card"><table>
<tr><th>权重方式</th><th>3年</th><th>5年</th><th>10年*</th></tr>
{fmt_rows(all_s, lab_all)}
</table>
<small>*主面板仅 9.0 年，10年持有截到数据上限≈9y；早期篮仅含 BTC/ETH 两币。</small></div>

<h2>全篮子起点（买入时≥40币，≈2021年起真实全篮子）</h2>
<div class="card"><table>
<tr><th>权重方式</th><th>3年</th><th>5年</th><th>10年*</th></tr>
{fmt_rows(full_s, lab_all)}
</table>
<small>*2021 起的篮子最多持有到 2026-08≈5y，5y/10y 实际截到≈3.8y，与3年同源。</small></div>

<div class="note">
<b>核心结论</b>：对这套高动量山寨池，<b>等权周平衡是三种方式里最差的</b>。
全篮子 3年中位：等权持有 −19%、<b>等权周平衡 −46%</b>、市值加权 −0.3%。
原因——周平衡本质是"每周卖出赢家、买回输家"，在强动量市场里是反向交易，产生再平衡拖累。
市值加权靠 BTC/ETH 把胜率拉到 50%、中位勉强打平；纯山寨等权长期持有整体亏损，且结果极度依赖<b>买入时机</b>
（同一篮子 2021-01 买→+191%，2021-11 顶部买→−56%）。
<br><br>⚠️ 存活者偏差：本池已剔除 RIO/PAS/BEAM/METIS/HNT 等死币，真实全样本指数结果会更差。
</div>
</div>
<script>
var D = {json.dumps(paths)};
function mk(name,color,dash){{return {{name:name,x:D[name].x,y:D[name].y,type:'line',showSymbol:false,lineStyle:{{width:2,color:color,type:dash?'dashed':'solid'}},itemStyle:{{color:color}}}};}}
var chart=echarts.init(document.getElementById('c'));
chart.setOption({{
  grid:{{left:48,right:14,top:30,bottom:50}},
  tooltip:{{trigger:'axis',valueFormatter:function(v){{return v?v.toFixed(0)+'%':'-';}}}},
  xAxis:{{type:'category',data:D.a2021_equal.x,axisLabel:{{fontSize:10,formatter:function(v){{return v.slice(0,7);}}}}}},
  yAxis:{{type:'value',name:'净值(重基100)',axisLabel:{{fontSize:10,formatter:'{{value}}'}}}},
  series:[
    mk('等权持有@2021-01','#2563eb',false),
    mk('等权周平衡@2021-01','#f59e0b',false),
    mk('市值加权@2021-01','#16a34a',false),
    mk('等权持有@2021-11顶部','#dc2626',true)
  ]
}});
window.addEventListener('resize',function(){{chart.resize();}});
</script>
</body></html>"""

import os as _os
_OUT_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                         'docs', 'reports')
_os.makedirs(_OUT_DIR, exist_ok=True)
_OUT = _os.path.join(_OUT_DIR, 'index_buyhold_rebal.html')

open(_OUT, 'w', encoding='utf-8').write(HTML)
print('written', _OUT, '(', len(HTML), 'bytes )')
