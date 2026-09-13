# -*- coding: utf-8 -*-
"""ZEC（Zcash）净增发实测 + 价格分解，与 BTC/ETH/SOL/HYPE 同口径。

口径：实测净增发 = Δ(流通量) = Δ(市值 ÷ 价格)。
Zcash 是 BTC 式固定硬顶 21M + 减半，无解锁悬崖 → 预期供给曲线极平滑。
"""
import io, json, os
import pandas as pd, numpy as np

CRYPTO = r"E:\xmanbian\mx_auto_strategy_repo\markets\crypto"
BASE = os.path.join(CRYPTO, "data", "cmc_history")
OUT = os.path.join(CRYPTO, "out")
MAXSUP = 21_000_000.0


def load(sym):
    d = json.load(io.open(os.path.join(BASE, f"{sym}.json"), encoding="utf-8"))
    p = d["points"]
    df = pd.DataFrame([(pd.to_datetime(int(t), unit="s"), v[0], v[2]) for t, v in p.items()],
                      columns=["t", "px", "mc"]).set_index("t").sort_index()
    df = df[(df["px"] > 0) & (df["mc"] > 0)]
    df["sup"] = df["mc"] / df["px"]
    return df


def main():
    Z = load("ZEC")
    px, mc, sup = Z["px"], Z["mc"], Z["sup"]
    end = Z.index[-1]
    yrs = (end - Z.index[0]).days / 365
    print("=" * 86)
    print(f"ZEC  {Z.index[0].date()} -> {end.date()}  ({yrs:.2f}y, {len(Z)} 点)")
    print(f"  现价 ${px.iloc[-1]:,.2f}   流通 {sup.iloc[-1]/1e6:.3f}M / 硬顶 {MAXSUP/1e6:.0f}M "
          f"({sup.iloc[-1]/MAXSUP*100:.2f}%)   市值 ${mc.iloc[-1]/1e9:,.2f}B")
    print(f"  全期: 流通 x{sup.iloc[-1]/sup.iloc[0]:.4f} (年化 {(pow(sup.iloc[-1]/sup.iloc[0],1/yrs)-1)*100:+.2f}%) "
          f"| 市值 x{mc.iloc[-1]/mc.iloc[0]:.3f} | 价格 x{px.iloc[-1]/px.iloc[0]:.3f}")
    print()
    print("-" * 86)
    print("各窗口：价格倍数 = 市值倍数 ÷ 流通量倍数")
    print("-" * 86)
    print(f"{'窗口':7s}{'净增发%':>9s}{'年化%':>9s}{'市值%':>11s}{'价格%':>11s}{'供给贡献pp':>12s}{'残差':>12s}")
    rows = []
    for w, days in [("近1月", 30), ("近3月", 91), ("近6月", 182), ("近1年", 365), ("近2年", 730), ("近3年", 1095)]:
        cut = end - pd.Timedelta(days=days)
        if cut < Z.index[0]:
            continue
        s = Z[Z.index >= cut]
        cs = s["sup"].iloc[-1] / s["sup"].iloc[0]
        cm = s["mc"].iloc[-1] / s["mc"].iloc[0]
        cp = s["px"].iloc[-1] / s["px"].iloc[0]
        rec = dict(window=w, days=days, net=(cs - 1) * 100, ann=(pow(cs, 365 / days) - 1) * 100,
                   mc=(cm - 1) * 100, px=(cp - 1) * 100, sup_pp=(cp - cm) * 100,
                   resid=(cp - cm / cs))
        rows.append(rec)
        print(f"{w:7s}{rec['net']:>9.2f}{rec['ann']:>9.2f}{rec['mc']:>11.1f}{rec['px']:>11.1f}"
              f"{rec['sup_pp']:>12.2f}{rec['resid']:>12.2e}")
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "zec_windows.csv"), index=False, encoding="utf-8-sig")
    print()
    print("-" * 86)
    print("阶梯检测（通缩/通胀悬崖）")
    print("-" * 86)
    we = sup.resample("W").last().dropna()
    ch = we.pct_change().dropna()
    big = ch[ch.abs() > 0.01]
    print(f"  周度 |变化|>1% 的次数: {len(big)}")
    for d, v in big.items():
        print(f"    {d.date()}  {v*100:+.2f}%   -> {we.loc[d]/1e6:.3f}M")
    print()
    print("-" * 86)
    print("月度流通量（近 24 个月）")
    print("-" * 86)
    mo = sup.resample("MS").last().dropna()
    mo = mo[mo.index >= mo.index[-1] - pd.DateOffset(months=24)]
    mc_ = mo.pct_change() * 100
    for i in range(len(mo)):
        c = mc_.iloc[i]
        print(f"  {mo.index[i].date()}  {mo.iloc[i]/1e6:8.3f}M  " + (f"{c:+7.3f}%" if np.isfinite(c) else "    —"))
    print()
    print("-" * 86)
    print("本轮上涨（近 1 年）拆开看：市值 vs 价格 vs 供给")
    print("-" * 86)
    cut = end - pd.Timedelta(days=365)
    s = Z[Z.index >= cut]
    print(f"  价格 ${s['px'].iloc[0]:,.2f} -> ${s['px'].iloc[-1]:,.2f}  ({(s['px'].iloc[-1]/s['px'].iloc[0]-1)*100:+.1f}%)")
    print(f"  市值 ${s['mc'].iloc[0]/1e9:.3f}B -> ${s['mc'].iloc[-1]/1e9:.3f}B  ({(s['mc'].iloc[-1]/s['mc'].iloc[0]-1)*100:+.1f}%)")
    print(f"  流通 {s['sup'].iloc[0]/1e6:.3f}M -> {s['sup'].iloc[-1]/1e6:.3f}M  ({(s['sup'].iloc[-1]/s['sup'].iloc[0]-1)*100:+.2f}%)")
    cm = s["mc"].iloc[-1] / s["mc"].iloc[0]
    cs = s["sup"].iloc[-1] / s["sup"].iloc[0]
    cp = s["px"].iloc[-1] / s["px"].iloc[0]
    print(f"  拆解: 市值 x{cm:.2f} ({((cm-1)*100):+.1f}%) ÷ 流通 x{cs:.4f} -> 价格 x{cp:.2f} ({((cp-1)*100):+.1f}%)")
    print(f"  仅供给稀释单独效应 = {((1/cs)-1)*100:+.2f}%   （正数=供给收缩帮了忙）")
    print(f"  对数份额: 市值 {(np.log(cm)/np.log(cp)*100):.1f}% / 供给 {(np.log(1/cs)/np.log(cp)*100):.1f}%")
    print(f"  未流通 {(MAXSUP - sup.iloc[-1])/1e6:.3f}M 枚 = 硬顶的 {(MAXSUP-sup.iloc[-1])/MAXSUP*100:.2f}%")
    print()
    print("-" * 86)
    print("跨资产：市值规模 与 每涨 1% 所需边际资金")
    print("-" * 86)
    rows2 = []
    for sym in ["BTC", "ETH", "SOL", "ZEC", "HYPE"]:
        df = load(sym)
        c = df.index[-1] - pd.Timedelta(days=365)
        ss = df[df.index >= c]
        ann = (pow(ss["sup"].iloc[-1] / ss["sup"].iloc[0], 1.0) - 1) * 100
        rows2.append(dict(coin=sym, mc_B=df["mc"].iloc[-1] / 1e9, ann=ann,
                          per1p_B=df["mc"].iloc[-1] * 0.01 / 1e9, px=df["px"].iloc[-1]))
    x = pd.DataFrame(rows2).sort_values("per1p_B", ascending=False)
    for _, r in x.iterrows():
        print(f"  {r.coin:5s} 市值 ${r.mc_B:8.2f}B  现价 ${r.px:>10,.2f}  "
              f"近1年净增发 {r.ann:+7.2f}%  每涨 1% 需 ${r.per1p_B:.3f}B")
    x.to_csv(os.path.join(OUT, "zec_xasset.csv"), index=False, encoding="utf-8-sig")
    print(f"\n落盘: out/zec_windows.csv / out/zec_xasset.csv")


if __name__ == "__main__":
    main()
