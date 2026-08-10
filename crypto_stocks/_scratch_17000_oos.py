# -*- coding: utf-8 -*-
"""OOS 验证: 时间刻减仓 vs 当前默认(反应式做空)。
项目铁律: walk-forward 双维度(倍数+MDD)配对 t 检验, |t|>=2 才算真改进。
另做减半周期切割 OOS (训练轮选参 -> 下一轮测试)。
"""
import math
import crypto_options_bt as m

px10 = m.pd.read_csv('data/weekly_adjclose_crypto50_10y.csv', index_col=0, parse_dates=True).sort_index()

A = dict()                                                   # 当前默认: halving关 + MA20门控做空
B = dict(halving_cycle_enabled=True, pre_halving_start_month=31.0,
         halving_crash_risk_scale=0.5, halving_bear_bottom_risk_scale=0.5,
         short_proactive_ma=0, short_cycle_gate=False)        # 纯时间刻减仓(稳健档)
G = dict(halving_cycle_enabled=True, pre_halving_start_month=31.0,
         halving_crash_risk_scale=0.3, halving_bear_bottom_risk_scale=0.3)  # 减仓+门控做空(激进档)

def run(p, over):
    c = dict(m.DEFAULT_CFG); c.update(over)
    return m.run_bt(p, c, label='wf')

def paired_t(diffs):
    n = len(diffs)
    if n < 2: return 0.0, 0.0
    mu = sum(diffs)/n
    sd = math.sqrt(sum((d-mu)**2 for d in diffs)/(n-1))
    if sd == 0: return mu, 0.0
    return mu, mu/(sd/math.sqrt(n))

# ---------- 1) Walk-forward 滚动 2 年窗口 ----------
W, STEP = 104, 26
wins = []
i = 0
while i + W <= len(px10):
    wins.append(px10.iloc[i:i+W]); i += STEP
print(f"[Walk-forward] {len(wins)} 个不重叠步进窗口 (窗宽{W}周=2年, 步进{STEP}周=半年)\n")

rows = []
for w in wins:
    ra, rb, rg = run(w, A), run(w, B), run(w, G)
    rows.append((w.index[0].date(), w.index[-1].date(),
                 ra['multiple'], ra['mdd'], rb['multiple'], rb['mdd'], rg['multiple'], rg['mdd']))
    print(f"  {rows[-1][0]}~{rows[-1][1]}  A {ra['multiple']:>7.2f}x/{ra['mdd']*100:>6.1f}%  "
          f"B {rb['multiple']:>7.2f}x/{rb['mdd']*100:>6.1f}%  G {rg['multiple']:>7.2f}x/{rg['mdd']*100:>6.1f}%")

print("\n" + "="*80)
print("配对 t 检验 (对数倍数差 + MDD差), 基准 = A(当前默认)")
print("="*80)
for label, mi, di in [('B 纯时间刻减仓', 4, 5), ('G 减仓+门控做空', 6, 7)]:
    dm = [math.log(max(r[mi],1e-9)) - math.log(max(r[2],1e-9)) for r in rows]
    dd = [r[di] - r[3] for r in rows]           # MDD 为负数, 差>0 = 回撤更浅 = 改善
    mu_m, t_m = paired_t(dm); mu_d, t_d = paired_t(dd)
    win_m = sum(1 for x in dm if x > 0); win_d = sum(1 for x in dd if x > 0)
    print(f"\n  {label}:")
    print(f"    倍数(log)  Δ均值={mu_m:+.4f}  t={t_m:+.2f}  胜{win_m}/{len(dm)}  "
          f"{'✅显著改善' if t_m>=2 else ('❌显著恶化' if t_m<=-2 else '⚪未显著')}")
    print(f"    MDD        Δ均值={mu_d*100:+.2f}pp t={t_d:+.2f}  胜{win_d}/{len(dd)}  "
          f"{'✅显著改善' if t_d>=2 else ('❌显著恶化' if t_d<=-2 else '⚪未显著')}")

# ---------- 2) 减半周期切割 OOS ----------
print("\n" + "="*80)
print("减半周期切割 OOS: 训练轮(选参) -> 下一轮测试(不重选)")
print("="*80)
HD = m.BTC_HALVING_DATES
cyc = []
for k in range(len(HD)-1):
    seg = px10.loc[str(HD[k].date()):str(HD[k+1].date())]
    if len(seg) > 40: cyc.append((HD[k].date(), HD[k+1].date(), seg))
tail = px10.loc[str(HD[-1].date()):]
if len(tail) > 40: cyc.append((HD[-1].date(), px10.index[-1].date(), tail))

GRID = [(cr, bb) for cr in (0.3,0.5,0.7,1.0) for bb in (0.3,0.5,0.7,1.0)]
for k in range(len(cyc)-1):
    tr_s, tr_e, tr = cyc[k]
    te_s, te_e, te = cyc[k+1]
    best, bestm = None, -1
    for cr, bb in GRID:
        r = run(tr, {**G, 'halving_crash_risk_scale':cr, 'halving_bear_bottom_risk_scale':bb})
        if r['multiple'] > bestm: bestm, best = r['multiple'], (cr, bb)
    r_te = run(te, {**G, 'halving_crash_risk_scale':best[0], 'halving_bear_bottom_risk_scale':best[1]})
    r_te_a = run(te, A)
    # 后视镜: 在测试轮上直接选最优
    hind = max(run(te, {**G,'halving_crash_risk_scale':cr,'halving_bear_bottom_risk_scale':bb})['multiple']
               for cr, bb in GRID)
    keep = r_te['multiple']/hind*100 if hind > 0 else 0
    print(f"\n  训练 {tr_s}~{tr_e} ({len(tr)}周) 选出 cr={best[0]}/bb={best[1]} (训练内{bestm:.1f}x)")
    print(f"  测试 {te_s}~{te_e} ({len(te)}周): 该参={r_te['multiple']:.2f}x/{r_te['mdd']*100:.1f}%  "
          f"| 当前默认A={r_te_a['multiple']:.2f}x/{r_te_a['mdd']*100:.1f}%  | 后视镜最优={hind:.2f}x  保留率={keep:.0f}%")
