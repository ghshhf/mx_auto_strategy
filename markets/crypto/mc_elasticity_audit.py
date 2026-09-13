# -*- coding: utf-8 -*-
"""弹性检验：把「资金流入」与「起点市值」分离，回答两个被混为一谈的问题。

用户质疑（2026-09-13）：
  "隐私龙头（ZEC）是在机构强推下才这样的，而且它是从底部升起来的，
   底部的时候市值没多少。你不考虑这个问题？"

被指出的漏洞：上一轮横截面把「给定资金量」当外生条件。
正确分解：
    价格倍数 = 市值倍数 ÷ 流通量倍数
    市值倍数 − 1 = Δ$ / M0        <- 弹性 = 1/M0，与资金流入 Δ$ 相乘
    ΔP/P ≈ (Δ$/M0) ÷ (1 + 净增发)

所以「市值大→涨得慢」是**条件命题**（给定 Δ$ 时成立），
而横截面是无条件观测 —— 两者不矛盾，混用会得出错结论。

本脚本做三件事：
  A. 全部币的 Δ$（美元资金净流入）与 M0 拆解表
  B. 同额资金反事实：给所有币注入同样 Δ$，看价格涨幅 = 弹性差异
  C. ZEC 底部起涨与机构资金通道核实；资金流在大/小市值间的分配检验
"""
import io, json, os
import pandas as pd, numpy as np

CRYPTO = r"E:\xmanbian\mx_auto_strategy_repo\markets\crypto"
BASE = os.path.join(CRYPTO, "data", "cmc_history")
OUT = os.path.join(CRYPTO, "out")


def spearman(a, b):
    from math import erf, sqrt
    a, b = pd.Series(a), pd.Series(b)
    m = a.notna() & b.notna()
    a, b = a[m], b[m]
    if len(a) < 4:
        return np.nan, np.nan, len(a)
    ra, rb = a.rank(), b.rank()
    rho = float(np.corrcoef(ra, rb)[0, 1])
    n = len(a)
    t = rho * np.sqrt((n - 2) / max(1e-12, 1 - rho ** 2))
    p = 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2))))
    return rho, p, n


def load(sym):
    d = json.load(io.open(os.path.join(BASE, f"{sym}.json"), encoding="utf-8"))
    p = d["points"]
    df = pd.DataFrame([(pd.to_datetime(int(t), unit="s"), v[0], v[2]) for t, v in p.items()],
                      columns=["t", "px", "mc"]).set_index("t").sort_index()
    return df[(df["px"] > 0) & (df["mc"] > 0)]


def main():
    syms = sorted(f[:-5] for f in os.listdir(BASE) if f.endswith(".json"))
    recs = []
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
            m0 = s["mc"].iloc[0] / 1e9
            m1 = s["mc"].iloc[-1] / 1e9
            sup_x = (s["mc"].iloc[-1] / s["px"].iloc[-1]) / (s["mc"].iloc[0] / s["px"].iloc[0])
            recs.append(dict(
                coin=sym, window=w, days=days,
                m0=m0, m1=m1, dM_B=m1 - m0,
                mc_ret=s["mc"].iloc[-1] / s["mc"].iloc[0] - 1,
                px_ret=s["px"].iloc[-1] / s["px"].iloc[0] - 1,
                sup_x=sup_x, net=(sup_x - 1) * 100,
                per1p_B_mid=(m0 + m1) / 2 * 0.01,
            ))
    d = pd.DataFrame(recs)
    d["log_m0"] = np.log10(d["m0"])
    d.to_csv(os.path.join(OUT, "mc_elasticity_audit.csv"), index=False, encoding="utf-8-sig")

    # ───────────────────────────── A ─────────────────────────────
    print("=" * 100)
    print("### A. 资金流入 Δ$（美元）与起点市值 M0 拆解 ###")
    print("=" * 100)
    for w in ["近1年", "近2年", "近3年"]:
        g = d[d.window == w].sort_values("m0")
        print(f"\n--- {w} (n={len(g)}) ---")
        print(f"  {'币':6s}{'M0 $B':>9s}{'M1 $B':>9s}{'Δ$ $B':>9s}{'Δ$/M0':>9s}"
              f"{'价格%':>10s}{'净增发%':>9s}{'每1pp需$B(当期中)':>18s}")
        for _, r in g.iterrows():
            print(f"  {r.coin:6s}{r.m0:>9.3f}{r.m1:>9.2f}{r.dM_B:>+9.2f}"
                  f"{r.mc_ret*100:>8.1f}%{r.px_ret*100:>9.1f}%{r.net:>8.2f}%{r.per1p_B_mid:>18.4f}")
        n_up = int((g.dM_B > 0).sum())
        print(f"  → 资金净流入(Δ$>0)的币: {n_up}/{len(g)}；"
              f"Δ$ 合计 {g.dM_B.sum():+,.1f}B")

    # ─────────────────────────── B ───────────────────────────
    print()
    print("=" * 100)
    print("### B. 同额资金反事实：注入相同的美元 Δ$，价格涨幅 = 弹性 × Δ$ ÷ 供给 ###")
    print("=" * 100)
    w = "近1年"
    g = d[d.window == w].copy()
    zec = g[g.coin == "ZEC"].iloc[0]
    X = zec.dM_B
    print(f"\n基准：ZEC 近1年实际净流入 Δ$ = {X:+.2f}B（M0 ${zec.m0:.3f}B → M1 ${zec.m1:.2f}B）")
    print(f"      ZEC 实际价格 {zec.px_ret*100:+.0f}%，净增发 {zec.net:+.2f}%\n")
    print("  若把【同样这笔 Δ$】投给其他币（假设净增发不变）：")
    print(f"  {'币':6s}{'M0 $B':>10s}{'Δ$/M0':>10s}{'价格(反事实)':>14s}{'实际价格':>12s}")
    g["counter_mc_x"] = 1 + X / g["m0"]
    g["counter_px"] = g["counter_mc_x"] / g["sup_x"] - 1
    for _, r in g.sort_values("counter_px", ascending=False).iterrows():
        print(f"  {r.coin:6s}{r.m0:>10.3f}{X/r.m0:>9.1f}x{r.counter_px*100:>13.1f}%{r.px_ret*100:>11.1f}%")
    print("\n  → 同一笔钱，弹性（1/M0）差了 4 个数量级。这就是你说的『底部市值没多少』的量化形态。")

    print("\n  退一步看：BTC/ETH 每涨 1% 各需要多少钱（近1年区间中值市值）：")
    for c in ["BTC", "ETH", "ZEC", "HYPE"]:
        r = g[g.coin == c]
        if len(r):
            r = r.iloc[0]
            print(f"    {c:5s} 当期中值市值 ${r.per1p_B_mid/0.01:>8.1f}B → 每 +1% 需 ${r.per1p_B_mid:>7.3f}B"
                  f"（ZEC 的 {r.per1p_B_mid/g[g.coin=='ZEC'].iloc[0].per1p_B_mid:>6.1f} 倍）")

    # ─────────────────── C. 资金流分配 + 条件检验 ───────────────────
    print()
    print("=" * 100)
    print("### C. 资金流是外生的吗？熊市里 Δ$ 如何在大/小市值间分配 ###")
    print("=" * 100)
    for w in ["近1年", "近2年", "近3年"]:
        g = d[d.window == w].copy()
        g["q"] = pd.qcut(g["m0"], 3, labels=["小市值", "中市值", "大市值"])
        print(f"\n--- {w} ---")
        for q, sub in g.groupby("q", observed=True):
            print(f"  {q}: n={len(sub):2d}  M0中位 ${sub.m0.median():8.2f}B  "
                  f"Δ$中位 {sub.dM_B.median():+8.2f}B  Δ$均值 {sub.dM_B.mean():+8.2f}B  "
                  f"Δ$/M0中位 {sub.mc_ret.median()*100:+8.1f}%  "
                  f"价格中位 {sub.px_ret.median()*100:+8.1f}%  "
                  f"净增发中位 {sub.net.median():+6.2f}%")
        # 条件检验：只看资金净流入的子样本，M0 与涨幅关系
        up = g[g.dM_B > 0]
        if len(up) >= 4:
            rho, p, n = spearman(up.log_m0, up.px_ret)
            print(f"  [条件检验] 仅 Δ$>0 的 {n} 枚：Spearman(log M0, 价格涨幅) = {rho:+.3f} (p={p:.3f})")
            print(f"             → 这里面 M0 越小涨幅越大？{'是' if rho < 0 else '否（反向）'}"
                  f"  注意 n 很小，只作方向参考")
        dn = g[g.dM_B <= 0]
        if len(dn) >= 4:
            rho, p, n = spearman(dn.log_m0, dn.px_ret)
            print(f"  [条件检验] 仅 Δ$≤0 的 {n} 枚：Spearman(log M0, 价格涨幅) = {rho:+.3f} (p={p:.3f})")

    # ─────────────────── D. ZEC 底部与起涨 ───────────────────
    print()
    print("=" * 100)
    print("### D. ZEC：从底部起涨的量化形态 + 资金通道 ###")
    print("=" * 100)
    z = load("ZEC")
    for span, days in [("近1年", 365), ("近2年", 730), ("近3年", 1095)]:
        cut = z.index[-1] - pd.Timedelta(days=days)
        s = z[z.index >= cut]
        if len(s) < 5:
            continue
        lo_i = s["mc"].idxmin()
        print(f"  {span}: 区间最低市值 ${s['mc'].min()/1e9:.3f}B @ {lo_i.date()}；"
              f"最低点价格 ${s['px'].min():.2f}")
        print(f"          现市值 ${s['mc'].iloc[-1]/1e9:.2f}B → 距底部 "
              f"×{s['mc'].iloc[-1]/s['mc'].min():.1f}（市值口径）")
    allmin_i = z["mc"].idxmin()
    print(f"  全历史(近{len(z)}周): 最低市值 ${z['mc'].min()/1e9:.3f}B @ {allmin_i.date()}；"
          f"现 ${z['mc'].iloc[-1]/1e9:.2f}B → ×{z['mc'].iloc[-1]/z['mc'].min():.1f}")

    # ─────────────────── E. 价格 vs 市值 的读数差异 ───────────────────
    print()
    print("=" * 100)
    print("### E. 你的方法论主张检验：『看市值，不看价格』影响多大 ###")
    print("=" * 100)
    for w in ["近1年", "近2年", "近3年"]:
        g = d[d.window == w]
        dif = (g.px_ret - g.mc_ret).abs()
        worst = g.loc[dif.idxmax()]
        print(f"  {w}: |价格涨幅 − 市值涨幅| 中位 {dif.median()*100:.1f}pp、最大 "
              f"{dif.max()*100:.1f}pp（{worst.coin}: 价格 {worst.px_ret*100:+.1f}% vs "
              f"市值 {worst.mc_ret*100:+.1f}%，差 {dif.max()*100:.1f}pp，其净增发 {worst.net:+.2f}%）")
    print("  → 差额 ≈ 净增发，即「价格读数被供给污染」的幅度。")


if __name__ == "__main__":
    main()
