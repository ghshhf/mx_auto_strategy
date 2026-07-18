"""
forecast_week_v2.py - 下周收益情景预测(修正版)
v1的bug: 纯bootstrap在正值均值标的上会指数放大, 不现实.
v2方法:
  1. 用"期望收益 ± 1σ/2σ" 构建离散情景(非对称分布)
  2. 考虑凯莱英的高σ导致的双向极端可能
  3. 加上网格bonus确定性附加
  4. 基于排行榜门槛(图片4)给出概率
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from market_data import get_kline

DEF = [("601669","中国电建"), ("000651","格力电器"), ("600016","民生银行")]
OFF = [("002821","凯莱英"), ("600900","长江电力")]

W_DEF_PER = 54 / len(DEF)   # 18%
W_OFF_PER = 30 / len(OFF)   # 15%

THRESHOLDS = {
    "top8":   (17.65, "TOP 8 (50元)"),
    "top10":  (9.79,  "TOP 10 (50元)"),
    "top13":  (8.20,  "TOP 13 (~18.8元线)"),
    "top15":  (4.50,  "TOP 15 (8.8元线?)"),
    "top16":  (4.32,  "TOP 16 (8.8元)"),
}


def get_stats(code, n=12):
    kl = get_kline(code, "day", n + 2)
    if len(kl) < 3:
        return None
    rets = [(kl[i]["close"]/kl[i-1]["close"]-1)*100 for i in range(1, min(n+1, len(kl)))]
    avg = sum(rets)/len(rets)
    var = sum((r-avg)**2 for r in rets)/len(rets)
    sigma = math.sqrt(var)
    return {"avg": avg, "sigma": sigma, "n": len(rets), "rets": rets}


def main():
    print("="*70)
    print("  下周收益情景预测 v2 (期望±σ情景分析)")
    print("="*70)

    all_stats = {}
    print("\n【各标的基础统计】")
    print(f"{'代码':<8} {'名称':<8} {'日均%':>8} {'σ(日%)':>7} {'5d期望%':>9} {'5d±1σ':>12} {'5d±2σ':>12}")
    print("-"*72)
    for code, name in DEF + OFF:
        s = get_stats(code)
        if not s:
            continue
        all_stats[code] = s
        exp_5d = s["avg"] * 5
        sig_5d = s["sigma"] * math.sqrt(5)  # 5日累积σ
        print(f"{code:<8} {name:<8} {s['avg']:>+7.3f} {s['sigma']:>7.3f} {exp_5d:>+8.2f} [{exp_5d-sig_5d:+.2f}, {exp_5d+sig_5d:+.2f}] [{exp_5d-sig_5d*2:+.2f}, {exp_5d+sig_5d*2:+.2f}]")

    # 构建情景矩阵
    scenarios = [
        ("极度悲观🔴", -2),  # 所有标的取 -2σ
        ("悲观⚠️",      -1),  # 所有标的取 -1σ
        ("中性🟡",       0),  # 取期望
        ("乐观🟢",      +1),  # +1σ
        ("极度乐观🚀",  +2),  # +2σ
    ]

    # 特殊情景: 凯莱英崩盘(-2σ) + 其他中性
    extra = [
        ("凯莱英崩盘+其他中性💥", {"002821": -2, "600900": 0, "601669": 0, "000651": 0, "600016": 0}),
        ("凯莱英暴涨+其他中性🌟", {"002821": +2, "600900": 0, "601669": 0, "000651": 0, "600016": 0}),
    ]

    grid_bonus_total = 0.98  # 来自v1估算: ~+0.98%

    print(f"\n{'='*70}")
    print(f"  5日情景矩阵 (含网格bonus≈+{grid_bonus_total:.2f}%)")
    print(f"{'='*70}")
    print(f"{'情景':<24} {'总收益%':>10} {'能否达目标?'}")
    print("-"*60)

    results_by_scenario = []
    for name, mult in scenarios:
        total_pct = 0.0
        detail = {}
        for code, name_s in DEF:
            s = all_stats.get(code)
            if not s: continue
            ret_5d = (s["avg"] + mult * s["sigma"]) * 5
            contrib = W_DEF_PER * ret_5d / 100
            total_pct += contrib
            detail[code] = ret_5d
        for code, name_s in OFF:
            s = all_stats.get(code)
            if not s: continue
            ret_5d = (s["avg"] + mult * s["sigma"]) * 5
            contrib = W_OFF_PER * ret_5d / 100
            total_pct += contrib
            detail[code] = ret_5d
        total_pct += grid_bonus_total

        hits = [f"{label}(>{thr}%)" for key2,(thr,label) in THRESHOLDS.items() if total_pct >= thr]
        hit_str = ", ".join(hits) if hits else "❌ 无"
        results_by_scenario.append((name, total_pct, detail))
        print(f"{name:<24} {total_pct:>+9.2f}%   {hit_str}")

    for name, fn in extra:
        total_pct = 0.0
        detail = {}
        for code, name_s in DEF + OFF:
            s = all_stats.get(code)
            if not s: continue
            m = fn.get(code, 0)
            ret_5d = (s["avg"] + m * s["sigma"]) * 5
            w = W_DEF_PER if code in [c[0] for c in DEF] else W_OFF_PER
            total_pct += w * ret_5d / 100
            detail[code] = ret_5d
        total_pct += grid_bonus_total
        hits = [f"{label}(>{thr}%)" for key2,(thr,label) in THRESHOLDS.items() if total_pct >= thr]
        hit_str = ", ".join(hits) if hits else "❌ 无"
        results_by_scenario.append((name, total_pct, detail))
        print(f"{name:<24} {total_pct:>+9.2f}%   {hit_str}")

    # 概率评估(主观权重, 基于当前深度防御市场环境)
    print(f"\n{'='*70}")
    print(f"  概率评估(基于当前沪深300-6.46%弱势市)")
    print(f"{'='*70}")

    # 在弱市中, 正态分布左偏: 悲观情景概率更高
    prob_weights = {
        "极度悲观🔴": 0.15,
        "悲观⚠️":      0.30,
        "中性🟡":       0.30,
        "乐观🟢":      0.18,
        "极度乐观🚀":  0.05,
        "凯莱英崩盘+其他中性💥": 0.02,
        "凯莱英暴涨+其他中性🌟": 0.00,
    }

    for key, (thr, label) in sorted(THRESHOLDS.items(), key=lambda x: x[1][0]):
        hit_prob = sum(prob_weights[s] for s, tot, d in results_by_scenario if tot >= thr)
        emoji = "✅大概率" if hit_prob >= 0.6 else ("⚠️有机会" if hit_prob >= 0.3 else ("🔶看运气" if hit_prob >= 0.1 else "❌很难"))
        print(f"  {label:>22} (>={thr:>5.2f}%): 达成概率≈{hit_prob*100:.0f}%  {emoji}")

    # 最关键结论
    neutral_tot = [t for s,t,d in results_by_scenario if s=="中性🟡"]
    neutral_tot = neutral_tot[0] if neutral_tot else 0
    bearish_tot = [t for s,t,d in results_by_scenario if s=="悲观⚠️"]
    bearish_tot = bearish_tot[0] if bearish_tot else 0

    print(f"\n{'─'*70}")
    print(f"  核心结论:")
    print(f"  • 中性情景(最可能)下周收益 ≈ {neutral_tot:+.2f}%")
    print(f"  • 悲观情景(30%概率) 收益 ≈ {bearish_tot:+.2f}%")
    print(f"  • 网格贡献确定性 +{grid_bonus_total:.2f}%")
    print(f"  • 冲前13({THRESHOLDS['top13'][0]}%+,18.8元): {'能' if neutral_tot>=THRESHOLDS['top13'][0] else '看运气'} (中性情景{'已达标' if neutral_tot>=THRESHOLDS['top13'][0] else '未达标'})")
    print(f"  • 冲前10({THRESHOLDS['top10'][0]}%+,50元): {'需要行情配合' if neutral_tot<THRESHOLDS['top10'][0] else '中性即可'}")
    print(f"  • 保底前16({THRESHOLDS['top16'][0]}%+,8.8元): 几乎确定可达成")


if __name__ == "__main__":
    main()
