"""ETH vs SOL 净增发对照：为什么高增发资产的长期价格跑不赢低增发资产。

核心恒等式（定义式，精确成立，残差恒为 0）：
    价格倍数 = 市值倍数 ÷ 流通量倍数
即   P_t/P_0 = (MC_t/MC_0) / (C_t/C_0)

含义：净增发不是"影响价格的一个因素"，而是**价格公式的分母**。
所以"净增发高→难涨"里有一部分是机械必然，不是实证发现。

流通量口径 = 市值 ÷ 价格 反推，天然包含：
    协议发行 + 归属/解禁解锁 − 销毁
只要「能让流通盘变多」的项都被计入（含 CMC 口径把未流通部分计入流通的补入）。

数据源：data/cmc_history/<SYM>.json（CMC 网页版 data-api，全历史周度，无需 key）
配套：fetch_cmc_history.py（抓取）/ issuance_measured.py（27 币横截面）/ 本脚本（ETH-SOL 个案）

用法：
    E:/xmanbian/_venv/mx_quant/Scripts/python.exe eth_sol_dilution.py
"""
import io
import json
import os

import numpy as np
import pandas as pd

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cmc_history")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
WINDOWS = [("近1年", 365), ("近2年", 730), ("近3年", 1095)]
PEERS = ["BTC", "ETH", "SOL"]

# 协议通胀参考值（年化 %，已联网核实；用于把「流通量增速」拆成「协议通胀」与「口径补入」）
PROTO_INFLATION = {
    "SOL": [("2024", 4.2), ("2025", 3.8), ("2026", 3.8)],
    "ETH": [("2024~2026", 0.2), ("2026 低活动期", 0.83)],
}


def load(sym: str) -> pd.DataFrame:
    """读 CMC 落盘周度序列 -> DataFrame[px, mc]，剔除异常点。

    落盘格式：{"sym":..., "id":..., "points": {unix_ts_str: [price, volume, market_cap]}}
    """
    p = os.path.join(BASE, f"{sym}.json")
    d = json.load(io.open(p, encoding="utf-8"))
    rows = [(pd.to_datetime(int(t), unit="s"), v[0], v[2]) for t, v in d["points"].items()]
    df = pd.DataFrame(rows, columns=["t", "px", "mc"]).set_index("t").sort_index()
    return df[(df["px"] > 0) & (df["mc"] > 0)]


def decompose() -> pd.DataFrame:
    """三窗口严格乘法分解。同时给出加法近似的误差，说明大变动时不能用减法。"""
    out = []
    for sym in PEERS:
        df = load(sym)
        px, mc = df["px"], df["mc"]
        sup = mc / px
        for win, days in WINDOWS:
            cut = sup.index[-1] - pd.Timedelta(days=days)
            if cut < sup.index[0]:
                continue
            s, m, p = sup[sup.index >= cut], mc[mc.index >= cut], px[px.index >= cut]
            cs, cm, cp = s.iloc[-1] / s.iloc[0], m.iloc[-1] / m.iloc[0], p.iloc[-1] / p.iloc[0]
            out.append(dict(
                coin=sym, window=win,
                sup_x=cs, mc_x=cm, px_x=cp, px_check=cm / cs,
                net_pct=(cs - 1) * 100,
                ann_pct=(pow(cs, 1 / (days / 365)) - 1) * 100,
                mc_pct=(cm - 1) * 100, px_pct=(cp - 1) * 100,
                # 加法近似的绝对误差（pp）——大变动窗口下会失真，仅为展示
                add_approx_err=((cm - 1) - (cs - 1) - (cp - 1)) * 100,
            ))
    return pd.DataFrame(out)


def dilution_tax(d: pd.DataFrame) -> pd.DataFrame:
    """稀释税：SOL 的市值原样不变，只把流通量增速换成 ETH 的，看价格差异多少。

    回答"SOL 因多增发而少赚了多少"。
    """
    out = []
    for win, _ in WINDOWS:
        e = d[(d.coin == "ETH") & (d.window == win)]
        s = d[(d.coin == "SOL") & (d.window == win)]
        if e.empty or s.empty:
            continue
        e, s = e.iloc[0], s.iloc[0]
        counter = s.mc_x / e.sup_x          # 市值用 SOL 的，流通倍数用 ETH 的
        out.append(dict(
            window=win,
            sol_mc_x=s.mc_x,
            sol_sup_x=s.sup_x,
            eth_sup_x=e.sup_x,
            sol_actual_px_x=s.px_x,
            sol_actual_px_pct=(s.px_x - 1) * 100,
            sol_counter_px_x=counter,
            sol_counter_px_pct=(counter - 1) * 100,
            tax_pp=((s.px_x - counter) / counter) * 100,
            tax_abs_pp=(s.px_x - counter) * 100,
        ))
    return pd.DataFrame(out)


def sol_speed_trend() -> pd.DataFrame:
    """SOL 流通量年化增速的滚动收敛：11.7% -> 9.4% -> 5.6%，对照协议通胀。"""
    df = load("SOL")
    sup = df["mc"] / df["px"]
    m = sup.resample("MS").last().dropna()
    segs = [("近 2.5 年", "2024-03-01"), ("近 1.5 年", "2025-03-01"), ("近 9 个月", "2025-12-01")]
    out = []
    for tag, start in segs:
        seg = m[m.index >= pd.Timestamp(start)]
        if len(seg) < 2:
            continue
        yrs = (seg.index[-1] - seg.index[0]).days / 365
        out.append(dict(period=tag, years=round(yrs, 2),
                        ann_pct=((seg.iloc[-1] / seg.iloc[0]) ** (1 / yrs) - 1) * 100))
    return pd.DataFrame(out)


def monthly_supply(sym: str, months: int = 30) -> pd.DataFrame:
    """月度流通量序列，用于看台阶（一次性补入）还是平滑（持续发行）。"""
    df = load(sym)
    sup = df["mc"] / df["px"]
    m = sup.resample("MS").last().dropna()
    m = m[m.index >= m.index[-1] - pd.DateOffset(months=months)]
    r = pd.DataFrame({"circ": m.values / 1e6, "mom_pct": m.pct_change().values * 100},
                     index=m.index)
    r.index.name = "month"
    return r


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    d = decompose()
    print("### 严格乘法恒等式：价格倍数 = 市值倍数 ÷ 流通量倍数 ###")
    for win, _ in WINDOWS:
        print(f"\n--- {win} ---")
        for _, r in d[d.window == win].iterrows():
            print(f"  {r.coin:4s} 流通 x{r.sup_x:.4f} ({r.net_pct:+6.2f}%, 年化 {r.ann_pct:+5.2f}%)"
                  f" | 市值 x{r.mc_x:.3f} | 价格 x{r.px_x:.3f} ({r.px_pct:+7.1f}%)"
                  f" | 校验残差 {(r.px_x - r.px_check) * 1e6:+.1f}e-6"
                  f" | 加法近似误差 {r.add_approx_err:+.1f}pp")

    t = dilution_tax(d)
    print("\n### 稀释税：SOL 市值原样，流通增速换成 ETH 的水平 ###")
    for _, r in t.iterrows():
        print(f"  {r.window}: SOL 市值 x{r.sol_mc_x:.3f}")
        print(f"     实际   流通 x{r.sol_sup_x:.3f} -> 价格 x{r.sol_actual_px_x:.3f}"
              f" ({r.sol_actual_px_pct:+.1f}%)")
        print(f"     反事实 流通 x{r.eth_sup_x:.3f} -> 价格 x{r.sol_counter_px_x:.3f}"
              f" ({r.sol_counter_px_pct:+.1f}%)")
        print(f"     差距 {r.tax_abs_pp:+.1f}pp（相对 {r.tax_pp:+.1f}%）")

    s = sol_speed_trend()
    print("\n### SOL 流通量年化增速的收敛 ###")
    for _, r in s.iterrows():
        print(f"  {r.period:8s} ({r.years}y): {r.ann_pct:+.2f}%/y")
    print("  协议通胀参考: 2024 ~4.2% / 2025 ~3.8% / 2026 ~3.8%（SIMD-0550 前日程）")
    print("  => 差额即「流通口径补入」，按用户口径同样计入稀释")

    for f, name in [(d, "eth_sol_decompose.csv"), (t, "eth_sol_dilution_tax.csv"),
                    (s, "sol_speed_trend.csv")]:
        f.to_csv(os.path.join(OUT, name), index=False, encoding="utf-8-sig")
    for sym in ("ETH", "SOL"):
        monthly_supply(sym).to_csv(os.path.join(OUT, f"{sym.lower()}_monthly_supply.csv"),
                                   encoding="utf-8-sig")
    print(f"\n已落盘 CSV -> {OUT}")


if __name__ == "__main__":
    main()
