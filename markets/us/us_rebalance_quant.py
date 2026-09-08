"""美股再平衡全面量化 v2 — 三池对照(修正 bfill 注水 bug)。

回答命题: "美股(成熟/低波动)再平衡是否也有超额? 量级多少?"
理论锚: 再平衡溢价(volatility pumping)≈ 波动率²收割, 学术量级美股 0.5~1.1%/y。
三池:
  A. us50 成长股池 (2016-08~2026-07, ~10y, 50只, 高相关) — 展示"同涨池"无肉
  B. 行业指数+GLD (2016-08~2026-08, ~10y, 10资产, 低相关) — 正确测法
  C. 板块ETF (1999-03~2026-08, ~27y, SPY/QQQ/DIA/XLE/XLP/XLV/XLU) — 超长窗
每池: 死拿等权 vs 全池月度再平衡 vs 单组4抽样, 并报告相关性/波动率。
"""
import os
import random
import importlib.util

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("sam", os.path.join(HERE, "..", "crypto", "crypto_rebalance_sampler.py"))
sam = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sam)


def load_panel(path, cols=None, start=None):
    df = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    if cols:
        df = df[cols]
    df = df.loc[df.notna().any(axis=1)]
    # 只保留从"所有列都有数据"的公共起点开始 (防 bfill 注水)
    df = df[df.index >= df.dropna().index[0]]
    if start:
        df = df[df.index >= start]
    return df.ffill().bfill()


def analyze(tag, df):
    px = df
    n = px.shape[1]
    start, end = px.index[0], px.index[-1]
    yrs = (end - start).days / 365.25
    pend = px.iloc[-1] / px.iloc[0]
    hold = float(pend.mean())
    rets = px.pct_change().dropna()

    corr = rets.corr().values
    v = corr[np.triu_indices_from(corr, 1)]
    vol = float(rets.std().median())

    def rend(g):
        return sam.units_track(px[list(g)], list(g), 4).iloc[-1].to_dict()

    rall = rend(list(px.columns))
    nav_all = float(sum(pend[c] * rall[c] for c in px.columns) / n)

    rnd = random.Random(11)
    ss = []
    for _ in range(3000):
        g = tuple(rnd.sample(list(px.columns), min(4, n)))
        if len(g) < 2:
            break
        r = rend(g)
        ss.append(sum(pend[c] * r[c] for c in g) / len(g))
    ss.sort()
    med4 = ss[len(ss) // 2] if ss else float("nan")

    print(f"\n=== {tag}  {start.date()} ~ {end.date()} ({yrs:.1f}y)  n={n} ===")
    print(f"  池内相关性(两两中位): {np.median(v):.2f}   周波动(中位): {vol*100:.1f}%")
    print(f"  死拿等权:          {hold:6.2f}x  ({(hold**(1/yrs)-1)*100:+5.1f}%/y)")
    print(f"  全池月度再平衡:    {nav_all:6.2f}x  ({(nav_all**(1/yrs)-1)*100:+5.1f}%/y)   超额 {(nav_all/hold-1)*100:+5.1f}% ({(nav_all**(1/yrs)-1)*100 - (hold**(1/yrs)-1)*100:+.2f}pp/y)")
    if ss:
        print(f"  单组4抽样中位:      {med4:6.2f}x  ({(med4**(1/yrs)-1)*100:+5.1f}%/y)")
    return {"tag": tag, "n": n, "yrs": round(yrs, 2), "corr": round(float(np.median(v)), 2),
            "vol": round(vol * 100, 1), "hold_x": round(hold, 2),
            "hold_cagr": round((hold ** (1 / yrs) - 1) * 100, 1),
            "rebal_x": round(nav_all, 2), "rebal_cagr": round((nav_all ** (1 / yrs) - 1) * 100, 1),
            "excess_pp_y": round(((nav_all ** (1 / yrs) - 1) - (hold ** (1 / yrs) - 1)) * 100, 2),
            "single4_med": round(med4, 2)}


def main():
    res = []
    # A. us50 成长股池
    u50 = pd.read_csv(os.path.join(HERE, "data", "weekly_adjclose_us50.csv"), index_col=0, parse_dates=True)
    a_pool = [c for c in u50.columns if c not in {"SPY", "CWB"}]
    a = load_panel(os.path.join(HERE, "data", "weekly_adjclose_us50.csv"), a_pool)
    res.append(analyze("A · us50 成长股池 (同涨, 错池对照)", a))

    # B. 行业指数+GLD
    fe = pd.read_csv(os.path.join(HERE, "data", "weekly_adjclose_full_ext.csv"), index_col=0, parse_dates=True)
    b_pool = [c for c in fe.columns if c.endswith("_INDEX")] + ["GLD"]
    b = load_panel(os.path.join(HERE, "data", "weekly_adjclose_full_ext.csv"), b_pool, start=pd.Timestamp("2016-08-01"))
    res.append(analyze("B · 行业指数+GLD (低相关, 正确测法)", b))

    # C. 板块ETF 超长窗
    c_pool = ["SPY", "QQQ", "DIA", "XLE", "XLP", "XLV", "XLU"]
    c = load_panel(os.path.join(HERE, "data", "weekly_adjclose_us30.csv"), c_pool)
    res.append(analyze("C · 板块ETF (1999起 ~27y 超长窗)", c))

    df = pd.DataFrame(res)
    out = os.path.join(HERE, "data", "us_rebalance_quant.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n存 {out}")


if __name__ == "__main__":
    main()
