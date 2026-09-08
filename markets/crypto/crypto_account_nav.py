"""总账户美元净值模拟 — 用户实盘视角。

此前穷举器的 rate / mult=(1+rate)^yrs 是【纯筹码口径】(币量增速, 死拿=1.0),
回答的是"多囤了多少币"。用户问"总账户最后能赚几倍"必须用【美元市值】口径:
  每币初始等资金 → 账户 nav[t] = mean_c( Pnorm[c][t] * R[c][t] )
    Pnorm = 币价/窗口起点价   R = 该币所在组的币量倍数(units_track, 孤币=1)
用户习惯: 币两两一配或四个一配, 组内月度等权再平衡, 组间不流动, 合起来是总账户。
模拟: 把公平窗老币随机打散成 2币组 / 4币组(余1孤币), 算总账户期末净值分布。
对比: ①单组4币(之前"抽一组")的美元净值  ②全池一个组(钱在组间也流动) ③等权死拿指数。
"""
import os
import sys
import importlib.util
import random
from itertools import combinations

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("sam", os.path.join(HERE, "crypto_rebalance_sampler.py"))
sam = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sam)

OUT_CSV = os.path.join(HERE, "data", "account_nav_13coin.csv")

px = sam.load()
end = px.index[-1]
fd = sam.first_dates(px)
fair = sorted(c for c in sam.OFFENSE if c in fd and (end - fd[c]).days / 365.25 >= 6)
START = pd.Timestamp("2020-08-14")

sub_all = px[fair].dropna(how="all")
sub = sub_all[sub_all.index >= START].ffill().bfill()
P0, P1 = sub.iloc[0], sub.iloc[-1]
Pnorm_end = (P1 / P0).to_dict()
N = len(fair)  # 13


def R_end_of(group):
    df = sam.units_track(sub[list(group)], list(group), 4)
    return df.iloc[-1].to_dict()


# 预计算所有可能组的期末币量倍数(每组内每币)
quad_R = {q: R_end_of(q) for q in combinations(fair, 4)}   # C(13,4)=715
pair_R = {p: R_end_of(p) for p in combinations(fair, 2)}   # C(13,2)=78


def account_nav(groups):
    """每币初始等资金; 组间不流动; 返回总账户期末美元倍数(初值=1)。"""
    tot = 0.0
    for g in groups:
        key = tuple(sorted(g))
        if len(g) == 4:
            r = quad_R[key]
            for c in g:
                tot += Pnorm_end[c] * r[c]
        elif len(g) == 2:
            r = pair_R[key]
            for c in g:
                tot += Pnorm_end[c] * r[c]
        else:  # 孤币: 无再平衡 = 币价倍数
            c = g[0]
            tot += Pnorm_end[c]
    return tot / N


def single_nav(group):
    """单独一组(组内等权, 只算这组)期末美元倍数。"""
    key = tuple(sorted(group))
    r = quad_R[key] if len(group) == 4 else pair_R[key]
    return sum(Pnorm_end[c] * r[c] for c in group) / len(group)


def simulate(mode, n_sims=5000, seed=20260909):
    rnd = random.Random(seed)
    res = []
    for _ in range(n_sims):
        lst = fair[:]
        rnd.shuffle(lst)
        if mode == 4:
            groups = [tuple(lst[i:i + 4]) for i in range(0, 12, 4)] + [tuple(lst[12:])]
        else:
            groups = [tuple(lst[i:i + 2]) for i in range(0, 12, 2)] + [tuple(lst[12:])]
        res.append(account_nav(groups))
    return res


def stats(xs, tag):
    xs = sorted(xs)
    n = len(xs)
    med = xs[n // 2]
    mean = sum(xs) / n
    yrs = 6.064
    print(f"{tag}: n={n}")
    print(f"  总账户美元倍数: 中位 {med:.1f}x  均值 {mean:.1f}x  最差 {xs[0]:.1f}x  最好 {xs[-1]:.1f}x")
    print(f"  折合年化(中位): {(med ** (1/yrs) - 1) * 100:+.1f}%/y   (均值): {(mean ** (1/yrs) - 1) * 100:+.1f}%/y")
    return med, mean


def main():
    print(f"公平窗 {START.date()} ~ {end.date()} (~{(end-START).days/365.25:.2f}y)  13币: {fair}")
    yrs = (end - START).days / 365.25

    # ① 单组 4 币 (715 组, 之前的抽样单元) —— 美元口径
    scored = sorted(((single_nav(g), g) for g in quad_R), reverse=True)
    q = [x[0] for x in scored]
    print("\n" + "=" * 70)
    print(f"单组4币 (等权$买入一组并月度再平衡, 715组): 中位 {q[len(q)//2]:.1f}x  均值 {sum(q)/len(q):.1f}x  "
          f"区间 {q[-1]:.1f}x ~ {q[0]:.1f}x")
    print(f"  (口径提醒: 产币率37.9%/y→币量6.06y=7.0x 是'囤币量'倍数; 美元净值另有币价上涨, "
          f"中位12.8x——两者不同轴, 不可混用/互换)")
    print("  美元口径 TOP5:")
    for v, g in scored[:5]:
        r, _, _ = sam.annual_chip_rate(sub, list(g), start=START)
        print(f"    {v:6.1f}x  {g}   (产币率 {r:+.1f}%/y)")
    print("  美元口径 BOTTOM5:")
    for v, g in scored[-5:][::-1]:
        r, _, _ = sam.annual_chip_rate(sub, list(g), start=START)
        print(f"    {v:6.1f}x  {g}   (产币率 {r:+.1f}%/y)")

    # ② 满配总账户: 4币一组 / 2币一组
    print("\n" + "=" * 70)
    s4 = simulate(4)
    s2 = simulate(2)
    med4, mean4 = stats(s4, "总账户 · 4币一组×3 + 1孤币 (满配13币, 每币等资金)")
    med2, mean2 = stats(s2, "总账户 · 2币一对×6 + 1孤币 (满配13币, 每币等资金)")

    # ③ 参照: 全池一个组 (钱在组间也流动, 13币统一月度再平衡) vs 等权死拿
    rall = R_end_of(fair)
    nav_full = sum(Pnorm_end[c] * rall[c] for c in fair) / N
    nav_hold = sum(Pnorm_end.values()) / N
    print("\n" + "=" * 70)
    print(f"参照: 13币全放一个大组统一月度再平衡 = {nav_full:.1f}x  ({(nav_full**(1/yrs)-1)*100:+.1f}%/y)")
    print(f"参照: 13币等权死拿(不操作)        = {nav_hold:.1f}x  ({(nav_hold**(1/yrs)-1)*100:+.1f}%/y)")

    # 冠军拉高: 最好的总账户由哪些组构成
    print("\n" + "=" * 70)
    best = None
    for i, v in enumerate(s4):
        if best is None or v > best[0]:
            best = (v, i)
    rnd = random.Random(20260909)
    lst = fair[:]
    for i in range(best[1] + 1):
        rnd.shuffle(lst)
    groups = [tuple(lst[j:j + 4]) for j in range(0, 12, 4)] + [tuple(lst[12:])]
    print(f"最好总账户(4币一组): {best[0]:.1f}x, 构成:")
    for g in groups:
        tag = "孤币" if len(g) == 1 else f"{len(g)}币组"
        print(f"    {g}: 单组单独跑={single_nav(g) if len(g)>1 else Pnorm_end[g[0]]:.1f}x  ({tag})")

    rows = ([{"mode": "quad4", "sim": i, "nav": v} for i, v in enumerate(s4)] +
            [{"mode": "pair2", "sim": i, "nav": v} for i, v in enumerate(s2)])
    pd.DataFrame(rows).to_csv(OUT_CSV, index=False)
    print(f"\n明细存 {OUT_CSV}  ({len(rows)} 行)")


if __name__ == "__main__":
    main()
