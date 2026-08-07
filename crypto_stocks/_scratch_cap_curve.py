import crypto_options_bt as m
import pandas as pd
import numpy as np
import plotly.graph_objects as go

px = m._load_default()  # 默认468周面板 (2017-2026), 与448x口径一致
base = dict(m.DEFAULT_CFG)

def run_cfg(label, **over):
    c = dict(base); c.update(over)
    r = m.run_bt(px, c, label=label)
    return r

# 1) BTC 买入持有 (参照)
btc0 = float(px['BTC'].iloc[0]); btc1 = float(px['BTC'].iloc[-1])
btc_mult = btc1 / btc0

# 2) 纯动量 (全关期权/做空/put) —— "原来不含封顶的逻辑"基线
r_pure = run_cfg('纯动量(关期权/做空/put)',
                 enabled_call=False, enabled_ovl=False,
                 enabled_put=False, enabled_short=False)

# 3) 期权全开·旧封顶3x (entry*(1+1.0)*1.5) —— 我修之前的279x
r_cap30 = run_cfg('期权全开·旧封顶3x', take_profit_pct=1.0)

# 3b) 期权全开·当前封顶4.5x (entry*(1+2.0)*1.5) —— 我的448x
r_cap45 = run_cfg('期权全开·封顶4.5x (当前默认)', take_profit_pct=2.0)

# 4) 期权全开·不封顶 (tp=100 -> 行权价≈entry*151x, 样本内基本不被行权, 但仍收保费)
r_nocap = run_cfg('期权全开·不封顶(tp=100, 收保费但不截顶)',
                  take_profit_pct=100.0)

results = [('BTC买入持有', btc_mult, None),
           ('纯动量', r_pure['multiple'], r_pure['nav']),
           ('期权·旧封顶3x', r_cap30['multiple'], r_cap30['nav']),
           ('期权·封顶4.5x', r_cap45['multiple'], r_cap45['nav']),
           ('期权·不封顶', r_nocap['multiple'], r_nocap['nav'])]

print('=== 封顶 vs 不封顶 对照 (468周面板) ===')

# 打印带CAGR/MDD的明细
print()
print(f'  BTC买入持有      : {btc_mult:.1f}x')
print(f'  纯动量           : {r_pure["multiple"]:.1f}x | CAGR {r_pure["cagr"]*100:.1f}% | MDD {r_pure["mdd"]*100:.1f}%')
print(f'  期权·旧封顶3x    : {r_cap30["multiple"]:.1f}x | CAGR {r_cap30["cagr"]*100:.1f}% | MDD {r_cap30["mdd"]*100:.1f}%')
print(f'  期权·封顶4.5x    : {r_cap45["multiple"]:.1f}x | CAGR {r_cap45["cagr"]*100:.1f}% | MDD {r_cap45["mdd"]*100:.1f}%')
print(f'  期权·不封顶      : {r_nocap["multiple"]:.1f}x | CAGR {r_nocap["cagr"]*100:.1f}% | MDD {r_nocap["mdd"]*100:.1f}%')

# ---- 画曲线 (对数轴) ----
fig = go.Figure()
colors = {'BTC买入持有':'#888', '纯动量':'#1f77b4', '期权·旧封顶3x':'#ff7f0e', '期权·封顶4.5x':'#d62728', '期权·不封顶':'#2ca02c'}
for lab, mult, navs in results:
    if navs is None:
        # BTC 买持: 构造等权净值
        btc = px['BTC'].astype(float).values
        nav_btc = btc / btc[0]
        fig.add_trace(go.Scatter(x=px.index, y=nav_btc, name=f'BTC买入持有 ({btc_mult:.0f}x)',
                                 line=dict(color=colors[lab], width=1.5, dash='dot')))
    else:
        fig.add_trace(go.Scatter(x=navs.index, y=navs.values, name=f'{lab} ({mult:.0f}x)',
                                 line=dict(color=colors[lab], width=2)))

fig.update_layout(
    title='加密策略净值曲线：封顶 vs 不封顶（对数轴，起点均为1）',
    xaxis_title='周', yaxis_title='净值 (对数)', yaxis_type='log',
    height=620, width=1000, template='plotly_white',
    legend=dict(orientation='h', y=1.08, x=0),
    hovermode='x unified'
)
fig.write_html('crypto_cap_curve.html', include_plotlyjs='cdn')
print('\n曲线已写出: crypto_cap_curve.html')
