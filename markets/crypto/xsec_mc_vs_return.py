# -*- coding: utf-8 -*-
"""横截面检验：起点市值 vs 近1年涨幅（"市值越大涨得越慢"是否成立）。

用户命题：
  ① 市值越大，推动同样涨幅需要的资金越多 → 市值大 = 涨幅慢
  ② 低市值时若叠加高增发，同样资金下涨幅更小
  ③ 应看市值，不看价格（价格会被销毁/解锁污染）

检验：对全池做 Spearman(起点市值, 近1年涨幅)，并对比 Spearman(净增发, 近1年涨幅)。
"""
import io, json, os
import pandas as pd, numpy as np

CRYPTO = r"E:\xmanbian\mx_auto_strategy_repo\markets\crypto"
BASE = os.path.join(CRYPTO, "data", "cmc_history")
OUT = os.path.join(CRYPTO, "out")


def spearman(a, b):
    a, b = pd.Series(a), pd.Series(b)
    m = a.notna() & b.notna()
    a, b = a[m], b[m]
    if len(a) < 4:
        return np.nan, np.nan, len(a)
    ra, rb = a.rank(), b.rank()
    rho = float(np.corrcoef(ra, rb)[0, 1])
    n = len(a)
    t = rho * np.sqrt((n - 2) / max(1e-12, 1 - rho ** 2))
    # 双尾 p（正态近似，避免引 scipy）
    from math import erf, sqrt
    p = 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2))))
    return rho, p, n


def load(sym):
    d = json.load(io.open(os.path.join(BASE, f"{sym}.json"), encoding="utf-8"))
    p = d["points"]
    df = pd.DataFrame([(pd.to_datetime(int(t), unit="s"), v[0], v[2]) for t, v in p.items()],
                      columns=["t", "px", "mc"]).set_index("t").sort_index()
    df = df[(df["px"] > 0) & (df["mc"] > 0)]
    df["sup"] = df["mc"] / df["px"]
    return df


def main():
    syms = sorted(f[:-5] for f in os.listdir(BASE) if f.endswith(".json"))
    rows = []
    for sym in syms:
        df = load(sym)
        if len(df) < 60:
            continue
        end = df.index[-1]
        for w, days in [("近1年", 365), ("近2年", 730), ("近3年", 1095)]:
            cut = end - pd.Timedelta(days=days)
            if cut < df.index[0]:
                continue
            s = df[df.index >= cut]
            rows.append(dict(
                coin=sym, window=w,
                mc_start_B=s["mc"].iloc[0] / 1e9,
                mc_end_B=s["mc"].iloc[-1] / 1e9,
                px_ret=(s["px"].iloc[-1] / s["px"].iloc[0] - 1) * 100,
                mc_ret=(s["mc"].iloc[-1] / s["mc"].iloc[0] - 1) * 100,
                net=(s["sup"].iloc[-1] / s["sup"].iloc[0] - 1) * 100,
                per1p_B=s["mc"].iloc[-1] * 0.01 / 1e9,
            ))
    d = pd.DataFrame(rows)
    d["log_mc0"] = np.log10(d["mc_start_B"])
    d.to_csv(os.path.join(OUT, "xsec_mc_vs_return.csv"), index=False, encoding="utf-8-sig")

    for w in ["近1年", "近2年", "近3年"]:
        g = d[d.window == w]
        print("=" * 88)
        print(f"### {w}   n={len(g)}  ###")
        for a, b, tag in [("log_mc0", "px_ret", "起点市值 vs 价格涨幅"),
                          ("net", "px_ret", "净增发 vs 价格涨幅"),
                          ("log_mc0", "mc_ret", "起点市值 vs 市值涨幅"),
                          ("net", "mc_ret", "净增发 vs 市值涨幅")]:
            rho, p, n = spearman(g[a], g[b])
            sig = "显著" if (np.isfinite(p) and p < 0.05) else "不显著"
            print(f"  {tag:22s} Spearman {rho:+.3f}  p={p:.4f}  n={n}  {sig}")
        # 稳健性：剔除最大极值（ZEC）
        gx = g[~g["coin"].isin(["ZEC"])]
        rho_x, p_x, n_x = spearman(gx["log_mc0"], gx["px_ret"])
        rho_n, p_n, n_n = spearman(gx["net"], gx["px_ret"])
        print(f"  [剔除 ZEC] 起点市值 vs 价格涨幅 Spearman {rho_x:+.3f} p={p_x:.4f} n={n_x}"
              f" | 净增发 vs 价格涨幅 {rho_n:+.3f} p={p_n:.4f}")
        # 稳健性：用「市值涨幅」而非「价格涨幅」测市值效应（价格含销毁污染）
        print()
        print(f"  {'币':6s}{'起点市值$B':>12s}{'现市值$B':>11s}{'价格涨幅%':>12s}"
              f"{'市值涨幅%':>12s}{'净增发%':>10s}{'每涨1%需$B':>12s}")
        for _, r in g.sort_values("mc_start_B").iterrows():
            print(f"  {r.coin:6s}{r.mc_start_B:>12.3f}{r.mc_end_B:>11.2f}{r.px_ret:>12.1f}"
                  f"{r.mc_ret:>12.1f}{r.net:>10.2f}{r.per1p_B:>12.4f}")
        print()
        g2 = g.copy()
        g2["q"] = pd.qcut(g2["mc_start_B"], 3, labels=["小市值", "中市值", "大市值"])
        print("  按起点市值三分档：")
        for q, sub in g2.groupby("q", observed=True):
            print(f"    {q}: n={len(sub):2d}  起点市值中位 ${sub['mc_start_B'].median():8.3f}B  "
                  f"价格涨幅中位 {sub['px_ret'].median():+9.1f}%  "
                  f"净增发中位 {sub['net'].median():+6.2f}%  "
                  f"市值涨幅中位 {sub['mc_ret'].median():+9.1f}%")
        print()


if __name__ == "__main__":
    main()
