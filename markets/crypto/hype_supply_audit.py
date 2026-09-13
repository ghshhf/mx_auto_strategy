# -*- coding: utf-8 -*-
"""HYPE 净增发/净销毁实测审计 + 与 ETH/SOL/BTC 同口径对照。

口径（按用户定义）：只要流通盘能变多都算增发。
  实测净增发 = Δ(流通量)，其中 流通量 = 市值 ÷ 价格（CMC 全历史）
  自然包含：协议发行 + 归属/解禁解锁 − 销毁/回购注销

关键纪律：把「一次性口径事件（大台阶）」与「稳态连续速率」分开报。
  否则会把一次性会计认定误读成"每年销毁百分之几"。

输出：out/hype_windows.csv / out/hype_monthly.csv / out/hype_steps.csv / out/hype_xasset.csv
"""
import io, json, os
import pandas as pd, numpy as np

CRYPTO = r"E:\xmanbian\mx_auto_strategy_repo\markets\crypto"
BASE = os.path.join(CRYPTO, "data", "cmc_history")
OUT = os.path.join(CRYPTO, "out")

WINDOWS = [("近1月", 30), ("近3月", 91), ("近6月", 182), ("近1年", 365), ("近2年", 730), ("近3年", 1095)]
STEP_TH = 0.01          # 周度 |变化| > 1% 视为台阶
MAXSUP = {"HYPE": 1_000_000_000.0}


def load(sym: str) -> pd.DataFrame:
    d = json.load(io.open(os.path.join(BASE, f"{sym}.json"), encoding="utf-8"))
    p = d["points"]
    df = pd.DataFrame(
        [(pd.to_datetime(int(t), unit="s"), v[0], v[2]) for t, v in p.items()],
        columns=["t", "px", "mc"],
    ).set_index("t").sort_index()
    df = df[(df["px"] > 0) & (df["mc"] > 0)]
    df["sup"] = df["mc"] / df["px"]
    return df


def windows(df: pd.DataFrame, sym: str) -> pd.DataFrame:
    rows = []
    end = df.index[-1]
    for w, days in WINDOWS:
        cut = end - pd.Timedelta(days=days)
        if cut < df.index[0]:
            continue
        s = df[df.index >= cut]
        cs = s["sup"].iloc[-1] / s["sup"].iloc[0]
        cm = s["mc"].iloc[-1] / s["mc"].iloc[0]
        cp = s["px"].iloc[-1] / s["px"].iloc[0]
        rows.append(dict(
            coin=sym, window=w, days=days,
            sup_x=cs, mc_x=cm, px_x=cp,
            net=(cs - 1) * 100,
            ann=(pow(cs, 365 / days) - 1) * 100,
            mc_g=(cm - 1) * 100,
            px_g=(cp - 1) * 100,
            ident_resid=(cp - cm / cs),
            sup_contrib=(cp - cm) * 100,       # 价格涨幅中由供给收缩贡献的 pp
        ))
    return pd.DataFrame(rows)


def monthly(df: pd.DataFrame, sym: str, months=24) -> pd.DataFrame:
    mo = df["sup"].resample("MS").last().dropna()
    mo = mo[mo.index >= mo.index[-1] - pd.DateOffset(months=months)]
    return pd.DataFrame({"coin": sym, "month": mo.index.date,
                         "sup_M": mo.values / 1e6,
                         "chg_pct": (mo.pct_change() * 100).values})


def steps(df: pd.DataFrame, sym: str) -> pd.DataFrame:
    we = df["sup"].resample("W").last().dropna()
    ch = we.pct_change().dropna()
    big = ch[ch.abs() > STEP_TH]
    return pd.DataFrame({"coin": sym, "date": [d.date() for d in big.index],
                         "chg_pct": big.values * 100,
                         "sup_after_M": we.reindex(big.index).values / 1e6})


def steady(df: pd.DataFrame, sym: str, after: str) -> dict:
    """台阶结束后的稳态年化（剔除一次性事件后的真实速率）。"""
    s = df[df.index >= pd.Timestamp(after)]
    d = (s.index[-1] - s.index[0]).days
    g = s["sup"].iloc[-1] / s["sup"].iloc[0]
    return dict(coin=sym, since=str(s.index[0].date()), days=d,
                sup_from_M=s["sup"].iloc[0] / 1e6, sup_to_M=s["sup"].iloc[-1] / 1e6,
                cum_pct=(g - 1) * 100, ann_pct=(pow(g, 365 / d) - 1) * 100,
                per_month_M=(s["sup"].iloc[-1] - s["sup"].iloc[0]) / 1e6 / (d / 30.44))


def main():
    os.makedirs(OUT, exist_ok=True)
    w_all, m_all, s_all = [], [], []
    for sym in ["HYPE", "ETH", "SOL", "BTC"]:
        try:
            df = load(sym)
        except Exception as e:                                   # noqa: BLE001
            print(f"  !! {sym} 读取失败: {e}")
            continue
        w_all.append(windows(df, sym))
        m_all.append(monthly(df, sym))
        s_all.append(steps(df, sym))

    pw = pd.concat(w_all, ignore_index=True)
    pm = pd.concat(m_all, ignore_index=True)
    ps = pd.concat(s_all, ignore_index=True)
    pw.to_csv(os.path.join(OUT, "hype_windows.csv"), index=False, encoding="utf-8-sig")
    pm.to_csv(os.path.join(OUT, "hype_monthly.csv"), index=False, encoding="utf-8-sig")
    ps.to_csv(os.path.join(OUT, "hype_steps.csv"), index=False, encoding="utf-8-sig")

    print("=" * 92)
    print("各窗口：严格乘法恒等式  价格倍数 = 市值倍数 ÷ 流通量倍数")
    print("=" * 92)
    print(f"{'币':5s}{'窗口':7s}{'净增发%':>10s}{'年化%':>9s}{'市值%':>10s}{'价格%':>10s}"
          f"{'供给贡献pp':>11s}{'残差':>12s}")
    for _, r in pw.iterrows():
        print(f"{r.coin:5s}{r.window:7s}{r.net:>10.2f}{r.ann:>9.2f}{r.mc_g:>10.2f}"
              f"{r.px_g:>10.2f}{r.sup_contrib:>11.2f}{r.ident_resid:>12.2e}")

    print()
    print("=" * 92)
    print("HYPE 台阶（周度 |变化| > 1%）—— 一次性口径事件  vs  连续速率")
    print("=" * 92)
    hs = ps[ps["coin"] == "HYPE"].sort_values("date")
    for _, r in hs.iterrows():
        print(f"  {r.date}  {r.chg_pct:+7.2f}%   -> {r.sup_after_M:.3f}M")

    df_h = load("HYPE")
    end = df_h.index[-1]
    cut = end - pd.Timedelta(days=365)
    seg = df_h[df_h.index >= cut]
    s_from = seg["sup"].iloc[0]
    # 台阶的绝对量必须取自序列本身（台阶周 vs 前一周），不能拿窗口起点当锚点
    we_all = df_h["sup"].resample("W").last().dropna()
    ch_all = we_all.pct_change().dropna()
    drops = []
    for d, v in ch_all[ch_all.abs() > STEP_TH].items():
        if d >= cut:
            drops.append((we_all.loc[d] - we_all.loc[d - pd.Timedelta(days=7)]))
    tot_delta = seg["sup"].iloc[-1] - s_from
    step_abs = sum(drops)
    print()
    print(f"  近1年 {seg.index[0].date()} -> {seg.index[-1].date()}: "
          f"{s_from/1e6:.2f}M -> {seg['sup'].iloc[-1]/1e6:.2f}M  "
          f"净 {tot_delta/1e6:+.2f}M ({(tot_delta/s_from)*100:+.2f}%)")
    print(f"    台阶合计 {step_abs/1e6:+.2f}M  占净变化 {step_abs/tot_delta*100:.1f}%")
    print(f"    剔除台阶后的连续部分 {(tot_delta-step_abs)/1e6:+.2f}M "
          f"({((tot_delta-step_abs)/s_from)*100:+.2f}%)")

    print()
    print("=" * 92)
    print("台阶结束后的稳态速率（真实可持续净销毁/净增发）")
    print("=" * 92)
    st = steady(df_h, "HYPE", "2026-02-08")
    for k, v in st.items():
        print(f"  {k}: {v}")
    pd.DataFrame([st]).to_csv(os.path.join(OUT, "hype_steady.csv"), index=False, encoding="utf-8-sig")

    print()
    print("=" * 92)
    print("跨资产对照：市值（推动上涨所需资金）与净增发")
    print("=" * 92)
    xa = []
    for sym in ["BTC", "ETH", "SOL", "HYPE"]:
        df = load(sym)
        mc_now = df["mc"].iloc[-1]
        r1 = windows(df, sym)
        r1y = r1[r1.window == "近1年"]
        ann1 = float(r1y["ann"].iloc[0]) if len(r1y) else np.nan
        xa.append(dict(coin=sym, mc_now_B=mc_now / 1e9,
                       px_now=df["px"].iloc[-1],
                       sup_now_M=df["sup"].iloc[-1] / 1e6,
                       net1y_ann_pct=ann1,
                       mc_1pct_B=mc_now * 0.01 / 1e9))
    x = pd.DataFrame(xa)
    for _, r in x.iterrows():
        print(f"  {r.coin:5s} 市值 ${r.mc_now_B:8.2f}B  现价 ${r.px_now:>10,.2f}  "
              f"流通 {r.sup_now_M:9.2f}M  近1年净增发年化 {r.net1y_ann_pct:+7.2f}%  "
              f"每涨 1% 需边际资金 ≈ ${r.mc_1pct_B:.3f}B")
    x.to_csv(os.path.join(OUT, "hype_xasset.csv"), index=False, encoding="utf-8-sig")

    print()
    print("=" * 92)
    print("HYPE 抛压存量")
    print("=" * 92)
    cur = df_h["sup"].iloc[-1]
    mx = MAXSUP["HYPE"]
    print(f"  硬顶 {mx/1e6:.0f}M  流通 {cur/1e6:.2f}M  已流通 {cur/mx*100:.2f}%  "
          f"未流通 {(mx-cur)/1e6:.2f}M ({(mx-cur)/mx*100:.2f}%)  "
          f"按现价 ${(mx-cur)*df_h['px'].iloc[-1]/1e9:,.1f}B")
    print(f"\n落盘: out/hype_windows.csv / hype_monthly.csv / hype_steps.csv / "
          f"hype_steady.csv / hype_xasset.csv")


if __name__ == "__main__":
    main()
