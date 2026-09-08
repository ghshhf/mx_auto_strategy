"""[错池对照·已废弃] us50 高相关成长股池版本 — 正确方法见 us_rebalance_quant.py。
保留仅作"同涨池无肉"的历史对照: 死拿等权 14.5x vs 再平衡 12.6~13.7x(超额≤0),
因为池内 2016-2026 单边同涨, 再平衡每月卖飞赢家。行业/跨资产池才有正超额。
"""
import os
import sys
import importlib.util
import random

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("sam", os.path.join(HERE, "..", "crypto", "crypto_rebalance_sampler.py"))
sam = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sam)

PANEL = os.path.join(HERE, "data", "weekly_adjclose_us50.csv")
OUT_CSV = os.path.join(HERE, "data", "us_account_nav.csv")
REBAL = 4  # 周频, 月度再平衡(与加密口径一致)

px = pd.read_csv(PANEL, index_col=0, parse_dates=True).sort_index()
px = px.loc[:, px.notna().any()]
DROP = {"SPY", "CWB"}
pool = [c for c in px.columns if c not in DROP]
N = len(pool)
px = px[pool].ffill().bfill()
end = px.index[-1]
start = px.index[0]
yrs = (end - start).days / 365.25

Pnorm_end = (px.iloc[-1] / px.iloc[0]).to_dict()


def R_end_of(group):
    df = sam.units_track(px[list(group)], list(group), REBAL)
    return df.iloc[-1].to_dict()


# 预计算 2股组 (key 一律字母序)
import itertools
pair_R = {tuple(sorted(p)): R_end_of(p) for p in itertools.combinations(pool, 2)}


def group_R(g):
    key = tuple(sorted(g))
    if len(g) == 2:
        return pair_R[key]
    return R_end_of(g)


def account_nav(groups):
    """每股票初始等资金, 组内再平衡, 组间不流动; 总账户期末美元倍数。"""
    tot = 0.0
    for g in groups:
        if len(g) == 1:
            tot += Pnorm_end[g[0]]
        else:
            r = group_R(g)
            for c in g:
                tot += Pnorm_end[c] * r[c]
    return tot / N


def simulate(k, n_sims=3000, seed=20260909):
    rnd = random.Random(seed)
    out = []
    for _ in range(n_sims):
        lst = pool[:]
        rnd.shuffle(lst)
        groups = [tuple(lst[i:i + k]) for i in range(0, N - N % k, k)]
        rem = lst[N - N % k:]
        if rem:
            groups.append(tuple(rem))
        out.append(account_nav(groups))
    return out


def line(tag, xs):
    xs = sorted(xs)
    n = len(xs)
    med, mean = xs[n // 2], sum(xs) / n
    print(f"{tag:<58} 中位 {med:6.1f}x ({((med ** (1/yrs) - 1) * 100):+5.1f}%/y)"
          f"   均值 {mean:6.1f}x ({((mean ** (1/yrs) - 1) * 100):+5.1f}%/y)"
          f"   区间 {xs[0]:5.1f}~{xs[-1]:5.1f}x")


def main():
    print(f"美股池 {start.date()} ~ {end.date()}  ({yrs:.2f}y)  个股 n={N} (剔除 SPY/CWB)")
    print(f"列数 {len(px.columns)}, 空值已 ffill/bfill")
    print()

    # 参照基准: 死拿等权 / SPY / QQQ(同窗口拉 us30)
    hold = sum(Pnorm_end.values()) / N
    line(f"基准 · 50股死拿等权(买完不动)", [hold])
    spy = px_bench("SPY")
    if spy is not None:
        line("基准 · SPY(同期)", [spy])
    qqq = px_bench("QQQ")
    if qqq is not None:
        line("基准 · QQQ(同期)", [qqq])

    # 单组 4 股抽样分布(和加密口径A对应的抽样单元)
    rnd = random.Random(7)
    single = []
    for _ in range(4000):
        g = tuple(rnd.sample(pool, 4))
        r = group_R(g)
        single.append(sum(Pnorm_end[c] * r[c] for c in g) / 4)
    line("单组4股 · 4000次抽样(等权$买一组并月度再平衡)", single)

    print()
    s4 = simulate(4, 3000)
    line("总账户 · 4股一组满配(50股)", s4)
    s2 = simulate(2, 3000)
    line("总账户 · 2股一对满配(50股)", s2)
    # 全池统一月度再平衡(与 crypto 的"13币全池一组"对应)
    rall = R_end_of(pool)
    nav_all = sum(Pnorm_end[c] * rall[c] for c in pool) / N
    line("总账户 · 全池一大组(统一月度再平衡)", [nav_all])
    # 一致性校验: 1股一组=死拿等权
    s1 = simulate(1, 500)
    line("校验   · 1股一组(应=死拿等权)", s1)

    rows = ([{"mode": "quad4", "sim": i, "nav": v} for i, v in enumerate(s4)] +
            [{"mode": "pair2", "sim": i, "nav": v} for i, v in enumerate(s2)] +
            [{"mode": "single4_sample", "sim": i, "nav": v} for i, v in enumerate(single)])
    pd.DataFrame(rows).to_csv(OUT_CSV, index=False)
    print(f"\n明细存 {OUT_CSV} ({len(rows)} 行)")


def px_bench(tkr):
    try:
        f = os.path.join(HERE, "data", "weekly_adjclose_us30.csv")
        b = pd.read_csv(f, index_col=0, parse_dates=True).sort_index()
        if tkr not in b.columns:
            return None
        s = b[tkr].dropna()
        s = s[(s.index >= start) & (s.index <= end)]
        return s.iloc[-1] / s.iloc[0]
    except Exception:
        return None


if __name__ == "__main__":
    main()
