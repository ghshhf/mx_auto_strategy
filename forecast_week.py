"""
forecast_week.py - v6.3 下周收益情景预测(概率化)
基于:
  1. 两周回测真实数据(2026-07-06~07-17): 5个标的日收益率/σ/MDD
  2. 网格参数: 凯莱英步距5.26%/长江电力2%/每层3.2万/5层
  3. 仓位结构: 54%(3防均配) + 30%(2攻均配) + 16%现金网格
  4. 排行榜门槛(图片4): Top10=9.79%, Top13=8.20%, Top15=4.50%, Top16=4.32%
方法:
  用各标的近10日日收益率序列做bootstrap重采样, 模拟N=10000次下周走势,
  加上网格额外收益估算(基于震荡次数×格距), 输出各目标的达成概率.
"""
import sys, os, json, random, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from market_data import get_kline

# v6.2 选定标的
DEF = [("601669","中国电建"), ("000651","格力电器"), ("600016","民生银行")]
OFF = [("002821","凯莱英"), ("600900","长江电力")]

# 排行榜门槛(图片4, 实时)
THRESHOLDS = {
    "top8":   (17.65, "TOP 8 (50元)"),
    "top10":  (9.79,  "TOP 10 (50元)"),
    "top11":  (9.76,  "TOP 11"),
    "top12":  (9.37,  "TOP 12"),
    "top13":  (8.20,  "TOP 13 (~18.8元线)"),
    "top14":  (5.19,  "TOP 14"),
    "top15":  (4.50,  "TOP 15 (8.8元线?)"),
    "top16":  (4.32,  "TOP 16 (8.8元)"),
}

# 仓位权重(百分比)
W_DEF_PER = 54 / len(DEF)   # 18% each
W_OFF_PER = 30 / len(OFF)   # 15% each


def get_daily_returns(code, n=12):
    """取最近n天的日收益率序列"""
    kl = get_kline(code, "day", n + 2)
    if len(kl) < 2:
        return []
    rets = [(kl[i]["close"] / kl[i - 1]["close"] - 1) * 100 for i in range(1, min(n + 1, len(kl)))]
    return rets


def estimate_grid_bonus(rets, step_pct):
    """
    估算网格额外收益(粗略).
    思路: 统计ret序列中的"方向翻转次数"(涨->跌 或 跌->涨),
         每次翻转代表一次潜在的网格吃差价机会.
         单次网格收益 ≈ step_pct * 一层金额占比.
         网格效率系数(实际吃到差价的比例)设为 0.4(保守估计, T+1下不可能全吃).
    """
    if len(rets) < 2:
        return 0.0
    flips = sum(1 for i in range(1, len(rets)) if (rets[i] >= 0) != (rets[i - 1] >= 0))
    # 每层金额占网格弹药的比例 = 1/layers(5层=0.2)
    # 网格弹药占总资金 = 16%
    # 单次网格收益贡献 = step_pct * 0.2 * 0.16 = step_pct * 0.032
    per_flip = step_pct * 0.032 * 0.4  # 效率40%
    return flips * per_flip


def simulate_one(all_rets_dict, grid_bonuses, days=5):
    """单次模拟: bootstrap采样days天, 返回组合总收益率"""
    total = 0.0
    for code, name in DEF:
        rets = all_rets_dict.get(code, [0])
        if not rets:
            continue
        sampled = [random.choice(rets) for _ in range(days)]
        avg_ret = sum(sampled) / days
        total += W_DEF_PER * avg_ret / 100
    for code, name in OFF:
        rets = all_rets_dict.get(code, [0])
        if not rets:
            continue
        sampled = [random.choice(rets) for _ in range(days)]
        avg_ret = sum(sampled) / days
        total += W_OFF_PER * avg_ret / 100
    # 加上网格bonus(保守固定值, 不随机因为网格本身是确定性的)
    grid_total = sum(grid_bonuses.values())
    total += grid_total
    return total * 100  # 百分比


def main(random_seed=42):
    random.seed(random_seed)

    print("="*70)
    print(f"  下周收益情景预测 (v6.3, N=10000次bootstrap)")
    print(f"  数据源: 近10日K线(07-04~07-17)")
    print("="*70)

    # 收集各标的日收益序列
    all_rets = {}
    grid_bonuses = {}
    print("\n【各标的近10日统计】")
    print(f"{'代码':<8} {'名称':<8} {'日均收益%':>10} {'σ(日%)':>8} {'MDD(%)':>8} {'方向翻转/10d':>14}")
    print("-"*70)
    for code, name in DEF + OFF:
        rets = get_daily_returns(code, 12)
        all_rets[code] = rets
        if not rets:
            print(f"{code:<8} {name:<8} 数据缺失"); continue
        avg_r = sum(rets)/len(rets)
        var_r = sum((r-avg_r)**2 for r in rets)/len(rets) if rets else 0
        sigma = math.sqrt(var_r)
        # MDD from raw returns
        cum = 0; peak = 0; mdd = 0
        for r in rets:
            cum += r
            peak = max(peak, cum)
            mdd = min(mdd, cum - peak)
        flips = sum(1 for i in range(1, len(rets)) if (rets[i]>=0)!=(rets[i-1]>=0))
        step = 5.26 if code == "002821" else 2.0
        gb = estimate_grid_bonus(rets, step)
        grid_bonuses[code] = gb
        print(f"{code:<8} {name:<8} {avg_r:>10.3f} {sigma:>8.3f} {mdd:>8.2f} {flips:>14}  网格≈{gb:.2f}%")

    print(f"\n  网格总bonus(5天估算) ≈ {sum(grid_bonuses.values()):+.2f}%")
    print(f"  (注: 网格bonus为确定性附加, 不受bootstrap影响)")

    # Bootstrap模拟
    N = 10000
    results = [simulate_one(all_rets, grid_bonuses, days=5) for _ in range(N)]
    results.sort()

    # 分位数
    pctiles = [5, 10, 25, 50, 75, 90, 95]
    print(f"\n【Bootstrap N={N} 次, 下周总收益分布】")
    print(f"{'分位':>6} {'收益率%':>10} {'对应目标'}")
    print("-"*50)
    for p in pctiles:
        idx = int(N * p / 100)
        val = results[idx]
        # 找最接近的目标
        best_match = None
        best_diff = 999
        for key, (thr, label) in THRESHOLDS.items():
            diff = abs(val - thr)
            if diff < best_diff:
                best_diff = diff
                best_match = f"{label}(>{thr}%)"
        tag = f" → {best_match}" if val > 4 else ""
        print(f"P{p:>3}   {val:>+9.2f}%{tag}")

    # 各目标达成概率
    print(f"\n【各排名目标达成概率】")
    print(f"{'目标':>22} {'门槛%':>7} {'达成概率':>10} {'评价'}")
    print("-"*60)
    for key, (thr, label) in sorted(THRESHOLDS.items(), key=lambda x: x[1][0]):
        hits = sum(1 for r in results if r >= thr)
        prob = hits / N * 100
        if prob >= 70:
            emoji = "✅ 高概率"
        elif prob >= 30:
            emoji = "⚠️ 有希望"
        elif prob >= 10:
            emoji = "🔶 低概率"
        else:
            emoji = "❌ 极难"
        print(f"{label:>22} {thr:>6.2f}%   {prob:>8.1f}%   {emoji}")

    # 关键结论
    median = results[N // 2]
    mean_v = sum(results) / N
    neg_prob = sum(1 for r in results if r < 0) / N * 100
    top50_thr = THRESHOLDS["top13"][0]  # ~8.2%

    print(f"\n{'='*70}")
    print(f"  结论:")
    print(f"  中位数收益 = {median:+.2f}%  均值 = {mean_v:+.2f}%")
    print(f"  亏损概率 = {neg_prob:.1f}%")
    print(f"  冲前50({top50_thr}%+) 概率 = {sum(1 for r in results if r>=top50_thr)/N*100:.1f}%")
    print(f"  前10(9.79%+) 概率 = {sum(1 for r in results if r>=9.79)/N*100:.1f}%")
    print(f"{'='*70}")

    return results


if __name__ == "__main__":
    main()
