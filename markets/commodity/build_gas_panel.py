"""天然气(气体)产业链面板构建 + 再平衡测试。

源: World Bank Pink Sheet(1960起, 区域天然气/LNG/指数/煤) + FRED(1992起, 更新到 2026-07 + HenryHub 日频)
产出:
  data/gas_panel_monthly.csv      天然气产业链月度面板(宽表)
  data/gas_rebalance_quant.csv    再平衡量化结果
"""
import os
import random
import time
import importlib.util

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.join(HERE, "data", "commodity_worldbank_monthly.csv")
FRED_RAW = os.path.join(HERE, "data", "raw_fred")
PROXY = {"http": "http://127.0.0.1:3067", "https": "http://127.0.0.1:3067"}

# FRED 天然气/气体相关(单条串行拉)
FRED_GAS = [
    ("PNgasUSUSDM", "NG_US_FRED"), ("PNGASEUUSDM", "NG_EU_FRED"),
    ("PNGASJPUSDM", "LNG_JP_FRED"), ("DHHNGSP", "NG_HENRYHUB"),
    ("PCOALAUUSDM", "COAL_AUS_FRED"),
]

_spec = importlib.util.spec_from_file_location(
    "sam", os.path.join(HERE, "..", "crypto", "crypto_rebalance_sampler.py"))
sam = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sam)


def fred_fetch(sid, tries=3):
    for k in range(tries):
        try:
            r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}",
                             proxies=PROXY, timeout=30)
            r.raise_for_status()
            t = r.text.strip()
            if "observation_date" not in t:
                raise ValueError("bad payload")
            df = pd.read_csv(pd.io.common.StringIO(t))
            df.columns = ["date", "value"]
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            return df.dropna().drop_duplicates("date").set_index("date")["value"]
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (k + 1))
    return None


def build_panel():
    cols = {}
    wb = pd.read_csv(WB, index_col=0, parse_dates=True)
    for c in ["NG_US", "NG_EU", "LNG_JP", "NG_INDEX", "COAL_AUS", "COAL_ZAF"]:
        if c in wb.columns:
            cols[c] = wb[c].dropna()

    for sid, name in FRED_GAS:
        p = os.path.join(FRED_RAW, f"{sid}.csv")
        s = None
        if os.path.exists(p):
            d = pd.read_csv(p, parse_dates=["date"])
            s = d.set_index("date")["value"].dropna()
        else:
            s = fred_fetch(sid)
            if s is not None:
                s.to_frame("value").to_csv(p, encoding="utf-8-sig")
            time.sleep(random.uniform(1.5, 3.0))
        if s is not None and len(s):
            cols[name] = s.resample("ME").last().dropna()

    panel = pd.DataFrame(cols).sort_index()
    panel = panel.dropna(how="all")
    out = os.path.join(HERE, "data", "gas_panel_monthly.csv")
    panel.to_csv(out, encoding="utf-8-sig")
    print(f"天然气面板 {panel.shape}  {panel.index[0].date()} ~ {panel.index[-1].date()}")
    for c in panel.columns:
        s = panel[c].dropna()
        print(f"  {c:16s} {len(s):5d} 点 {str(s.index[0].date()):12s}~{s.index[-1].date()}  last={s.iloc[-1]:.4g}")
    return panel


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
    print(f"  相关性中位 {np.median(v):.2f}   年化波动 {vol_a*100:.1f}%")
    print(f"  死拿等权   {hold:7.2f}x  {(hold**(1/yrs)-1)*100:+6.2f}%/y")

    res = {}
    for p, lb in zip(periods, ["月度", "季度", "年度"]):
        R = sam.units_track(px, list(px.columns), p).iloc[-1].to_dict()
        x = float(sum(pend[k] * R[k] for k in px.columns) / n)
        res[p] = x
        ex = (x ** (1 / yrs) - 1) * 100 - (hold ** (1 / yrs) - 1) * 100
        print(f"  {lb}再平衡  {x:7.2f}x  {(x**(1/yrs)-1)*100:+6.2f}%/y   超额 {ex:+.2f} pp/y")

    def cg(x):
        return (x ** (1 / yrs) - 1) * 100

    return {"pool": tag, "n": n, "yrs": round(yrs, 1), "corr": round(float(np.median(v)), 2),
            "vol_ann": round(vol_a * 100, 1), "hold_x": round(hold, 2), "hold_cagr": round(cg(hold), 2),
            "excess_m": round(cg(res[1]) - cg(hold), 2), "excess_q": round(cg(res[3]) - cg(hold), 2),
            "excess_y": round(cg(res[12]) - cg(hold), 2),
            "rebal_q_x": round(res[3], 2), "rebal_q_cagr": round(cg(res[3]), 2)}


def main():
    panel = build_panel()
    res = []

    # 公共起点对齐
    def sub(cols, start=None):
        d = panel[[c for c in cols if c in panel.columns]].dropna()
        if start:
            d = d[d.index >= start]
        return d

    pools = [
        ("天然气·三区域(WB)", ["NG_US", "NG_EU", "LNG_JP"]),
        ("天然气·含指数(WB)", ["NG_US", "NG_EU", "LNG_JP", "NG_INDEX"]),
        ("天然气·FRED口径", ["NG_US_FRED", "NG_EU_FRED", "LNG_JP_FRED"]),
        ("燃气+煤·WB", ["NG_US", "NG_EU", "LNG_JP", "NG_INDEX", "COAL_AUS", "COAL_ZAF"]),
        ("全气体能源·合并", ["NG_US_FRED", "NG_EU_FRED", "LNG_JP_FRED", "NG_HENRYHUB",
                             "COAL_AUS", "COAL_ZAF"]),
    ]
    for tag, cols in pools:
        d = sub(cols)
        if d.shape[1] >= 2 and len(d) > 24:
            res.append(analyze(tag, d))
        else:
            print(f"\n=== {tag} 跳过(数据不足: {d.shape}) ===")

    # 近 20 年子窗(现代天然气市场: 页岩气革命后)
    print("\n\n########## 近 20 年(2005起, 页岩气革命后) ##########")
    for tag, cols in pools[:4]:
        d = sub(cols, start=pd.Timestamp("2005-01-01"))
        if d.shape[1] >= 2:
            r = analyze(tag + "·05+", d)
            r["pool"] = tag + "_05plus"
            res.append(r)

    df = pd.DataFrame(res)
    out = os.path.join(HERE, "data", "gas_rebalance_quant.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n存 {out}")
    print("\n=== 天然气池汇总 ===")
    print(df[["pool", "n", "yrs", "corr", "vol_ann", "hold_cagr",
              "excess_m", "excess_q", "excess_y"]].to_string(index=False))


if __name__ == "__main__":
    main()
