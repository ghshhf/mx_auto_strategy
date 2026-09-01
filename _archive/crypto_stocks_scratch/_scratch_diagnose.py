# -*- coding: utf-8 -*-

# --- [relocated 2026-08-31] 目录重构引导: 等效于在 crypto_stocks/ 根目录下运行 ---
import os as _os, sys as _sys
_SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))
_d = _SCRIPT_DIR
while _os.path.basename(_d) != 'crypto_stocks' and _d != _os.path.dirname(_d):
    _d = _os.path.dirname(_d)
_CS_ROOT = _d if _os.path.basename(_d) == 'crypto_stocks' else _SCRIPT_DIR
if _CS_ROOT != _SCRIPT_DIR:
    if _CS_ROOT not in _sys.path:
        _sys.path.insert(0, _CS_ROOT)
    _os.chdir(_CS_ROOT)
# --- [relocated] 引导结束 ---
"""加密诊断: 17000x 来历 + 448x 是否极限/有无浪费的上行"""
import crypto_options_bt as m
import crypto_adoption_v2 as ca2
import copy

px = m._load_default()            # 468周面板
px10 = m.pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()

REAL_ALLOC = copy.deepcopy(ca2.REGIME_ALLOC)
ALL_OFFENSE = {k: {'defense':0.0,'offense':1.0,'stable':0.0,'desc':'all-offense'} for k in REAL_ALLOC}

def run_cfg(panel, label, alloc=None, **over):
    if alloc is not None:
        ca2.REGIME_ALLOC = alloc
    c = dict(m.DEFAULT_CFG); c.update(over)
    r = m.run_bt(panel, c, label=label)
    ca2.REGIME_ALLOC = REAL_ALLOC   # 还原
    return r

print("="*70)
print("一、17000x(减半开) 在 10y 面板上是怎么来的 —— 参数扫描证明它是 in-sample 峰值")
print("="*70)
base_h = dict(m.DEFAULT_CFG); base_h.update(halving_cycle_enabled=True,
        halving_crash_risk_scale=0.5, halving_bear_bottom_risk_scale=0.5, pre_halving_start_month=31.0)
for eu,cr,bb in [(1.0,0.3,0.3),(1.0,0.5,0.5),(1.0,0.7,0.7),(0.8,0.5,0.5)]:
    c = dict(base_h); c['halving_euphoria_risk_scale']=eu; c['halving_crash_risk_scale']=cr; c['halving_bear_bottom_risk_scale']=bb
    r = m.run_bt(px10, c, label=f'eu{eu}/cr{cr}/bb{bb}')
    print(f"  eu{eu} cr{cr} bb{bb}: {r['multiple']:>10.1f}x | CAGR {r['cagr']*100:>5.1f}% | MDD {r['mdd']*100:>5.1f}%")
r_pub = m.run_bt(px10, base_h, label='17000x同参'); print(f"  >>> 17000x同参(10y): {r_pub['multiple']:.1f}x  (这就是提交里的17000x)")
print("  注: 这些都是 619周全样本内(in-sample)拟合峰值; OOS实测=3.4x(切割B)/274.8x(Walk-forward), 见crypto_oos_out.txt")

print()
print("="*70)
print("二、448x 是不是极限? 浪费的上行在哪? (均在468周面板)")
print("="*70)
r_def = run_cfg(px, '默认(期权开/封顶4.5x)')
print(f"  默认(期权开/封顶4.5x): {r_def['multiple']:.1f}x | CAGR {r_def['cagr']*100:.1f}% | MDD {r_def['mdd']*100:.1f}%")

r_all = run_cfg(px, '全进攻(防御/现金=0)', alloc=ALL_OFFENSE)
print(f"  [诊断A] 全进攻(无防御无现金): {r_all['multiple']:.1f}x | CAGR {r_all['cagr']*100:.1f}% | MDD {r_all['mdd']*100:.1f}%")

r_nocd = run_cfg(px, '关冷却(cooldown=0)', cooldown_weeks=0)
print(f"  [诊断B] 关冷却(cooldown=0): {r_nocd['multiple']:.1f}x | CAGR {r_nocd['cagr']*100:.1f}% | MDD {r_nocd['mdd']*100:.1f}%")

r_both = run_cfg(px, '全进攻+关冷却', alloc=ALL_OFFENSE, cooldown_weeks=0)
print(f"  [诊断C] 全进攻+关冷却: {r_both['multiple']:.1f}x | CAGR {r_both['cagr']*100:.1f}% | MDD {r_both['mdd']*100:.1f}%")

print()
print("="*70)
print("三、分散化拖拽: 面板里单币买入持有最高能到多少? (理论上限)")
print("="*70)
best = []
for c in px.columns:
    s = px[c].dropna()
    if len(s) >= 52:
        best.append((c, s.iloc[-1]/s.iloc[0]))
best.sort(key=lambda x: x[1], reverse=True)
print("  单币买入持有 Top8 (起点->终点):")
for c,mult in best[:8]:
    print(f"    {c:<8}: {mult:.1f}x")
print(f"  单币最高 {best[0][0]} = {best[0][1]:.1f}x  vs 策略聚合 448.6x")
print(f"  => 分散到3币+轮动 把'单押赢家'的上行摊薄, 但换来更低MDD(策略-57% vs 单币常-90%+)")
