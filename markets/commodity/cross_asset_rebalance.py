"""跨资产全球池再平衡测试 —— 对应"全资产上链"后可组合的池子。

命题: 资产上链的真实意义不是"能买股票了", 而是**把不同相关结构的资产放进同一个池子**,
      再平衡溢价 = f(低相关, 高波动)。资产种类越多、相关性结构越丰富, 收割机会越多。

池子(由窄到宽):
  1. 纯商品(金/铜/油/气/玉米)          —— 单资产类别
  2. 股+债(60/40 经典)                 —— 传统组合
  3. 股+债+商品(全天候)                —— 跨类别
  4. 股+债+商品+加密(全资产)           —— 上链后的完整池
  5. 全商品71 + 股 + 债                —— 极限宽度

债券口径: DGS10 收益率 → 构造总回报指数(久期近似), r = y/12 - D·Δy, D=8.5
"""
import os
import importlib.util

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WB = os.path.join(HERE, "data", "commodity_worldbank_monthly.csv")
GA = os.path.join(HERE, "data", "global_assets_monthly.csv")
CRYPTO = os.path.join(REPO, "markets", "crypto", "data", "weekly_adjclose_crypto50_10y.csv")
US30 = os.path.join(REPO, "markets", "us", "data", "weekly_adjclose_us30.csv")

_spec = importlib.util.spec_from_file_location(
    "sam", os.path.join(REPO, "markets", "crypto", "crypto_rebalance_sampler.py"))
sam = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sam)


def bond_index(y, dur=8.5):
    """由收益率构造债券总回报指数(月度). y 单位为百分数(如 4.5)。"""
    y = y.dropna()
    dy = y.diff()
    r = y.shift(1) / 12 / 100 - dur * dy / 100
    r = r.dropna()
    idx = (1 + r).cumprod()
    idx.iloc[0] = 1.0
    return idx


def load_all():
    """统一 resample 到月末(ME), 否则不同源的日期(月初/月末/周)无法对齐, dropna 后全空。"""
    cols = {}
    wb = pd.read_csv(WB, index_col=0, parse_dates=True)
    for c in wb.columns:
        cols[c] = wb[c].dropna().resample("ME").last()

    ga = pd.read_csv(GA, index_col=0, parse_dates=True)
    if "DGS10" in ga.columns:
        cols["BOND10"] = bond_index(ga["DGS10"]).resample("ME").last()
    if "DGS2" in ga.columns:
        cols["BOND2"] = bond_index(ga["DGS2"], dur=1.9).resample("ME").last()
    for c in ["SP500", "NASDAQCOM", "DJIA", "NIKKEI225", "VIXCLS", "DEXUSEU", "DEXJPUS"]:
        if c in ga.columns:
            cols[c] = ga[c].dropna().resample("ME").last()

    if os.path.exists(US30):
        us = pd.read_csv(US30, index_col=0, parse_dates=True)
        for c in ["SPY", "QQQ"]:
            if c in us.columns:
                cols[c] = us[c].dropna().resample("ME").last()

    if os.path.exists(CRYPTO):
        cr = pd.read_csv(CRYPTO, index_col=0, parse_dates=True)
        for c in ["BTC", "ETH"]:
            if c in cr.columns:
                cols[c] = cr[c].dropna().resample("ME").last()

    return pd.DataFrame(cols).sort_index()


def analyze(tag, px, periods=(1, 3, 12)):
    n = px.shape[1]
    start, end = px.index[0], px.index[-1]
    yrs = (end - start).days / 365.25
    pend = px.iloc[-1] / px.iloc[0]
    hold = float(pend.mean())
    rets = px.pct_change().dropna()
    c = rets.corr().values
    v = c[np.triu_indices_from(c, 1)]
    vol_a = float(rets.std().median()) * np.sqrt(12)

    print(f"\n=== {tag}  {start.date()}~{end.date()} ({yrs:.1f}y) n={n} ===")
    print(f"  相关性中位 {np.median(v):.2f}   年化波动(中位) {vol_a*100:.1f}%")
    print(f"  死拿等权   {hold:7.2f}x  {(hold**(1/yrs)-1)*100:+6.2f}%/y")

    out = {}
    for p, lb in zip(periods, ["月度", "季度", "年度"]):
        R = sam.units_track(px, list(px.columns), p).iloc[-1].to_dict()
        x = float(sum(pend[k] * R[k] for k in px.columns) / n)
        out[p] = x
        ex = (x ** (1 / yrs) - 1) * 100 - (hold ** (1 / yrs) - 1) * 100
        print(f"  {lb}再平衡  {x:7.2f}x  {(x**(1/yrs)-1)*100:+6.2f}%/y   超额 {ex:+.2f} pp/y")

    print("  各资产死拿倍数: " + "  ".join(f"{k}={pend[k]:.1f}x" for k in px.columns))

    def cg(x):
        return (x ** (1 / yrs) - 1) * 100

    return {"pool": tag, "n": n, "yrs": round(yrs, 1), "corr": round(float(np.median(v)), 2),
            "vol_ann": round(vol_a * 100, 1), "hold_x": round(hold, 2), "hold_cagr": round(cg(hold), 2),
            "excess_m": round(cg(out[1]) - cg(hold), 2), "excess_q": round(cg(out[3]) - cg(hold), 2),
            "excess_y": round(cg(out[12]) - cg(hold), 2), "rebal_q_cagr": round(cg(out[3]), 2)}


def main():
    allp = load_all()
    print(f"全资产面板 {allp.shape}  {allp.index[0].date()} ~ {allp.index[-1].date()}")

    def sub(cols, start=None):
        d = allp[[c for c in cols if c in allp.columns]].dropna()
        if start:
            d = d[d.index >= start]
        return d

    CMD = ["XAU", "CU", "OIL_BRENT", "NG_US", "MAIZE"]
    res = []

    print("\n\n########## A. 长窗: 不含加密 (1975起) ##########")
    pools = [
        ("A1 纯商品(金铜油气玉米)", CMD),
        ("A2 股+债(60/40经典)", ["NASDAQCOM", "BOND10"]),
        ("A3 股+债+商品(全天候)", ["NASDAQCOM", "BOND10", "XAU", "CU", "OIL_BRENT"]),
        ("A4 股+债+商品5(宽)", ["NASDAQCOM", "BOND10"] + CMD),
        ("A5 股+债+商品+汇率", ["NASDAQCOM", "BOND10", "XAU", "OIL_BRENT", "DEXUSEU"]),
    ]
    for tag, cols in pools:
        d = sub(cols, start=pd.Timestamp("1975-01-01"))
        if d.shape[1] >= 2 and len(d) > 24:
            res.append(analyze(tag, d))

    print("\n\n########## B. 含加密全资产 (2014起, 上链后完整池) ##########")
    pools2 = [
        ("B1 商品+加密", CMD + ["BTC"]),
        ("B2 股+债+商品+加密", ["NASDAQCOM", "BOND10"] + CMD + ["BTC"]),
        ("B3 股+债+商品+加密(ETH)", ["NASDAQCOM", "BOND10", "XAU", "CU", "OIL_BRENT",
                                     "BTC", "ETH"]),
        ("B4 SPY+债+金+BTC", ["SPY", "BOND10", "XAU", "BTC"]),
    ]
    for tag, cols in pools2:
        d = sub(cols, start=pd.Timestamp("2014-10-01"))
        if d.shape[1] >= 2 and len(d) > 24:
            res.append(analyze(tag, d))

    df = pd.DataFrame(res)
    out = os.path.join(HERE, "data", "cross_asset_rebalance.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n存 {out}")
    print("\n=== 跨资产汇总(按季度超额排序) ===")
    print(df[["pool", "n", "yrs", "corr", "vol_ann", "hold_cagr",
              "excess_m", "excess_q", "excess_y", "rebal_q_cagr"]]
          .sort_values("excess_q", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
