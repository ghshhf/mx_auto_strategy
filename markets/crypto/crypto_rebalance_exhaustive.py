"""27 币池 4 币组合穷举器 — 在 sampler 之上跑满全部组合, 不抽样。

口径A: 13 个历史>=6y 进攻币, 公共起点(全对齐) → C(13,4)=715 组
口径B: 全部 25 个进攻币, 自然窗口(组内最晚起点) → C(25,4)=12,650 组
月度等权再平衡 (rebal_weeks=4), 纯筹码口径 (死拿=0%)。
全组合明细存 markets/crypto/data/rebalance_exhaustive.csv, 终端只出统计。
"""
import os
import importlib.util
from itertools import combinations

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("sam", os.path.join(HERE, "crypto_rebalance_sampler.py"))
sam = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sam)

OUT_CSV = os.path.join(HERE, "data", "rebalance_exhaustive.csv")


def exhaustive(px, universe, common_start=None, tag=""):
    res = []
    for grp in combinations(universe, 4):
        r, yrs, st = sam.annual_chip_rate(px, list(grp), start=common_start)
        if r is None:
            continue
        res.append({"universe": tag, "grp": "+".join(sorted(grp)), "rate": round(r, 2),
                    "yrs": round(yrs, 2), "start": str(st.date()) if st is not None else "",
                    "deep": bool(sam.DEEP & set(grp))})
    return res


def report(title, res):
    rates = sorted(x["rate"] for x in res)
    n = len(rates)
    med = rates[n // 2]
    mean = sum(rates) / n
    p10, p90 = rates[int(n * 0.10)], rates[int(n * 0.90)]
    print(f"\n{'=' * 72}")
    print(f"{title}   组数={n}")
    print(f"  中位 {med:+.1f}%   均值 {mean:+.1f}%   P10 {p10:+.1f}%   P90 {p90:+.1f}%")
    nd = [x for x in res if not x["deep"]]
    wd = [x for x in res if x["deep"]]
    for label, sub in (("不含ZEC/BCH", nd), ("含ZEC/BCH", wd)):
        if sub:
            rr = sorted(x["rate"] for x in sub)
            print(f"  {label}: n={len(rr)}  中位 {rr[len(rr)//2]:+.1f}%  区间 {rr[0]:+.1f}% ~ {rr[-1]:+.1f}%")
    s = sorted(res, key=lambda x: -x["rate"])
    print("  TOP5:")
    for x in s[:5]:
        print(f"    {x['rate']:+7.1f}%  {x['grp']}  ({x['yrs']}y, {x['start']})")
    print("  BOTTOM5:")
    for x in s[-5:]:
        print(f"    {x['rate']:+7.1f}%  {x['grp']}  ({x['yrs']}y, {x['start']})")
    # 直方图
    lo, hi = rates[0], rates[-1]
    buckets = 12
    w = max((hi - lo) / buckets, 1e-9)
    cnt = [0] * buckets
    for r in rates:
        i = min(int((r - lo) / w), buckets - 1)
        cnt[i] += 1
    mx = max(cnt)
    print("  分布:")
    for i in range(buckets):
        a, b = lo + i * w, lo + (i + 1) * w
        print(f"    {a:+6.0f}~{b:+6.0f}% | {'#' * round(cnt[i] * 40 / mx)} {cnt[i]}")


def main():
    px = sam.load()
    fd = sam.first_dates(px)
    end = px.index[-1]
    fair = [c for c in sam.OFFENSE if c in fd and (end - fd[c]).days / 365.25 >= 6]
    common_start = pd.Timestamp("2020-08-14")

    resA = exhaustive(px, fair, common_start=common_start, tag="A_fair6y")
    report("口径A 公平窗口 (历史>=6y 13币, 公共起点 2020-08-14)", resA)

    resB = exhaustive(px, sam.OFFENSE, common_start=None, tag="B_natural25")
    report("口径B 自然窗口 (全25进攻币, 组内最晚起点)", resB)

    df = pd.DataFrame(resA + resB)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n全组合明细已存: {OUT_CSV}  ({len(df)} 行)")


if __name__ == "__main__":
    main()
