"""大宗商品再平衡量化 —— 回答"商品池再平衡超额有多大? 与波动率/相关性的关系?"

理论锚(既有实测结论):
  · 再平衡超额 = 波动率² 收割, 美股(低波动/高相关) 0.3~0.6 pp/y, 加密(高波动/低相关) ~11.9 pp/y
  · 商品特征: 波动率介于两者之间, 且品种间相关性天然低(金 vs 铜 vs 玉米 vs 原油)
  → 预期: 商品再平衡超额应显著高于美股, 是"全资产上链"后值得重点布局的池子

口径(铁律):
  · nav = mean(Pnorm_end × R_end)  ← 美元净值, R=再平衡产币倍数(units_track)
  · 禁止把"产币率/币量倍数"当收益

池子:
  A. 金属全(贵金属+工业金属)   B. 工业金属   C. 贵金属
  D. 能源    E. 农产品(抽样)   F. 全商品    G. 跨大类(金属+能源+农产)
窗口: 1960起全窗 + 1975起浮动汇率子窗(排除布雷顿森林固定金价期)
"""
import os
import random
import importlib.util

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.join(HERE, "data", "commodity_worldbank_monthly.csv")

# 复用加密/美股同一套再平衡实现, 保证口径一致
_spec = importlib.util.spec_from_file_location(
    "sam", os.path.join(HERE, "..", "crypto", "crypto_rebalance_sampler.py"))
sam = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sam)

PRECIOUS = ["XAU", "XAG", "XPT"]
INDUSTRIAL = ["CU", "AL", "ZN", "NI", "SN", "PB", "FE_ORE"]
ENERGY = ["OIL_BRENT", "OIL_WTI", "OIL_DUBAI", "OIL_AVG",
          "NG_US", "NG_EU", "LNG_JP", "COAL_AUS", "COAL_ZAF"]
FERT = ["UREA", "DAP", "KCL", "PHOS_ROCK"]
TIMBER = ["LOG_CMR", "LOG_MYS", "SAWN_CMR", "SAWN_MYS", "PLYWOOD"]


def load(cols=None, start=None):
    df = pd.read_csv(WB, index_col=0, parse_dates=True).sort_index()
    if cols:
        df = df[[c for c in cols if c in df.columns]]
    df = df.dropna(how="all")
    # 公共起点: 所有列都有数据才开始(防 bfill 注水)
    df = df[df.index >= df.dropna().index[0]]
    if start:
        df = df[df.index >= start]
    return df.ffill().bfill()


def analyze(tag, px, periods=(1, 3, 12)):
    """periods: 再平衡间隔(月) —— 1=月度, 3=季度, 12=年度"""
    n = px.shape[1]
    start, end = px.index[0], px.index[-1]
    yrs = (end - start).days / 365.25
    pend = px.iloc[-1] / px.iloc[0]
    hold = float(pend.mean())
    rets = px.pct_change().dropna()

    c = rets.corr().values
    v = c[np.triu_indices_from(c, 1)]
    vol_m = float(rets.std().median())
    vol_a = vol_m * np.sqrt(12)

    out = {}
    for p in periods:
        R = sam.units_track(px, list(px.columns), p).iloc[-1].to_dict()
        out[p] = float(sum(pend[k] * R[k] for k in px.columns) / n)

    print(f"\n=== {tag}   {start.date()}~{end.date()} ({yrs:.1f}y)  n={n} ===")
    print(f"  池内相关性中位 {np.median(v):.2f}    月波动中位 {vol_m*100:.1f}%   年化 ~{vol_a*100:.1f}%")
    print(f"  死拿等权        {hold:7.2f}x   {(hold**(1/yrs)-1)*100:+6.2f}%/y")
    for p, lb in zip(periods, ["月度", "季度", "年度"]):
        x = out[p]
        ex = (x ** (1 / yrs) - 1) * 100 - (hold ** (1 / yrs) - 1) * 100
        print(f"  {lb}再平衡        {x:7.2f}x   {(x**(1/yrs)-1)*100:+6.2f}%/y   超额 {ex:+.2f} pp/y")

    rnd = random.Random(11)
    ss = []
    if n >= 4:
        for _ in range(2000):
            g = tuple(rnd.sample(list(px.columns), min(4, n)))
            if len(g) < 2:
                break
            R = sam.units_track(px[list(g)], list(g), 1).iloc[-1].to_dict()
            ss.append(sum(pend[k] * R[k] for k in g) / len(g))
        ss.sort()
    med4 = ss[len(ss) // 2] if ss else float("nan")
    if ss:
        print(f"  单组4抽样中位  {med4:7.2f}x   {(med4**(1/yrs)-1)*100:+6.2f}%/y")

    def cg(x):
        return (x ** (1 / yrs) - 1) * 100

    return {"pool": tag, "n": n, "yrs": round(yrs, 1),
            "corr": round(float(np.median(v)), 2),
            "vol_m": round(vol_m * 100, 1), "vol_ann": round(vol_a * 100, 1),
            "hold_x": round(hold, 2), "hold_cagr": round(cg(hold), 2),
            "rebal_m": round(out[1], 2), "excess_m_pp": round(cg(out[1]) - cg(hold), 2),
            "rebal_q": round(out[3], 2), "excess_q_pp": round(cg(out[3]) - cg(hold), 2),
            "rebal_y": round(out[12], 2), "excess_y_pp": round(cg(out[12]) - cg(hold), 2),
            "med4": round(med4, 2), "med4_cagr": round(cg(med4), 2)}


def main():
    allc = list(pd.read_csv(WB, index_col=0, nrows=1).columns)
    agri_pool = [c for c in allc if c not in PRECIOUS + INDUSTRIAL + ENERGY + FERT + TIMBER
                 and not c.startswith(("NG_", "OIL_", "COAL_"))]
    # 农产品抽样 10 个(保证长历史且代表性)
    agri10 = [c for c in ["MAIZE", "WHEAT_US_SRW", "WHEAT_US_HRW", "SOYBEANS", "RICE_THAI_5",
                          "COTTON_A_INDEX", "SUGAR_WORLD", "COFFEE_ARABICA", "COFFEE_ROBUSTA",
                          "COCOA", "BANANA_US", "ORANGE", "PALM_OIL", "SOYBEAN_OIL",
                          "BARLEY", "FISH_MEAL"] if c in allc][:10]

    pools = [
        ("A 金属全(贵金属+工业)", PRECIOUS + INDUSTRIAL),
        ("B 工业金属", INDUSTRIAL),
        ("C 贵金属", PRECIOUS),
        ("D 能源", ENERGY),
        ("E 农产品10", agri10),
        ("F 全商品71", allc),
        ("G 跨大类(金属+能源+农产)", PRECIOUS[:2] + INDUSTRIAL[:4] + ENERGY[:4] + agri10[:4]),
        ("H 化肥", FERT),
    ]

    res = []
    print("########## 全窗口 (1960起) ##########")
    for tag, cols in pools:
        px = load(cols)
        if px.shape[1] >= 2:
            r = analyze(tag, px)
            r["window"] = "1960+"
            res.append(r)

    print("\n\n########## 浮动汇率窗口 (1975起, 排除布雷顿森林固定金价) ##########")
    for tag, cols in pools[:7]:
        px = load(cols, start=pd.Timestamp("1975-01-01"))
        if px.shape[1] >= 2:
            r = analyze(tag, px)
            r["window"] = "1975+"
            res.append(r)

    df = pd.DataFrame(res)
    out = os.path.join(HERE, "data", "commodity_rebalance_quant.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n\n存 {out}")
    print("\n=== 汇总: 超额(pp/y) 排序 ===")
    print(df[df.window == "1960+"][["pool", "n", "yrs", "corr", "vol_ann",
                                    "hold_cagr", "excess_m_pp", "excess_q_pp", "excess_y_pp"]]
          .sort_values("excess_m_pp", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
