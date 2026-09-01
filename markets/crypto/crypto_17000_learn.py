# -*- coding: utf-8 -*-
"""【学习脚本】17000x 是怎么来的 —— 在 10y 面板(619周)上做逐层拆解,
把"为什么能到一万多倍"讲清楚。所有数字均为实跑, 非估计。"""
import copy
import crypto_options_bt as m
import crypto_adoption_v2 as ca2

px10 = m.pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()
print(f"[面板] 10y = {len(px10)} 周, {px10.index[0].date()} ~ {px10.index[-1].date()}, {px10.shape[1]} 币\n")

# ---------- 1) 复现 17000x (含税参数) ----------
base_h = dict(m.DEFAULT_CFG)
base_h.update(halving_cycle_enabled=True,
              halving_crash_risk_scale=0.5,
              halving_bear_bottom_risk_scale=0.5,
              pre_halving_start_month=31.0)
r_pub = m.run_bt(px10, base_h, label='17000x同参(含税)')
print(f"[复现] 含税参数(10y): {r_pub['multiple']:.1f}x | CAGR {r_pub['cagr']*100:.1f}% | MDD {r_pub['mdd']*100:.1f}% | Sharpe {r_pub.get('sharpe',0):.2f}\n")

# ---------- 2) 逐层拆解 (同一10y面板, 关掉减半, 只叠期权层) ----------
def run(over):
    c = dict(m.DEFAULT_CFG); c.update(over)
    return m.run_bt(px10, c, label='layer')

print("="*72)
print("逐层拆解 (10y面板, 减半关, 只叠期权三件套):")
print("="*72)
layers = []
# 纯动量
c0 = dict(m.DEFAULT_CFG)
for k in ['enabled_call','enabled_put','enabled_short','enabled_ovl','enabled_cooldown']:
    c0[k] = False
r0 = m.run_bt(px10, c0, label='pure_mom')
layers.append(('纯动量(轮动 Top3, 无期权/无做空)', r0['multiple']))
# + covered call
r1 = run({'enabled_put':False,'enabled_short':False,'enabled_ovl':False,'enabled_cooldown':False})
layers.append(('+ 止盈 covered call', r1['multiple']))
# + short
r2 = run({'enabled_put':False,'enabled_ovl':False,'enabled_cooldown':False})
layers.append(('+ 止盈后做空闭环', r2['multiple']))
# + ovl 主动call
r3 = run({'enabled_put':False,'enabled_cooldown':False})
layers.append(('+ 极度高估主动 call', r3['multiple']))
# + put 双保护
r4 = run({'enabled_cooldown':False})
layers.append(('+ 双层保护性 put', r4['multiple']))
# + 冷却
r5 = run({})
layers.append(('+ 冷却期(默认全开)', r5['multiple']))
# + 减半周期
r6 = m.run_bt(px10, base_h, label='+halving')
layers.append(('+ 减半周期(含税参数)', r6['multiple']))

prev = None
for name, mult in layers:
    if prev is None:
        print(f"  {name:<28}: {mult:>10.1f}x")
    else:
        print(f"  {name:<28}: {mult:>10.1f}x   (×{mult/prev:.2f} vs 上一层)")
    prev = mult

print("\n[解读] 期权三件套贡献主要来自 covered call + 被行权做空 的复利轮动;")
print("       减半周期是最后一块'涡轮'——它在暴跌相位把做空仓位×2、把MA收紧抓崩盘。\n")

# ---------- 3) 减半相位在 10y 面板上的分布 ----------
from collections import Counter
ph_count = Counter()
ph_weeks = Counter()
for d in px10.index:
    ph, ms, mn = m.halving_cycle_phase(d, pre_halving_start_month=31.0)
    ph_count[ph] += 1
print("="*72)
print("10y 面板上各减半相位的周数分布 (pre_halving_start_month=31):")
print("="*72)
total = sum(ph_count.values())
for ph in ['accumulation','euphoria','crash','bear_bottom','pre_halving','pre_data']:
    if ph_count[ph]:
        print(f"  {ph:<14}: {ph_count[ph]:>4} 周  ({ph_count[ph]/total*100:>4.1f}%)")
print(f"  {'合计':<14}: {total:>4} 周")
print("\n[解读] crash 相位≈18-24月 post-halving, 历史上正是 BTC -50~80% 暴跌段;")
print("       减半周期在这里 double 做空 + 收紧MA, 等于'知道何时该躲'。这是它的 alpha 来源。")
