"""全球资产(非商品) FRED 序列补全 —— 单条串行拉取, 随机间隔防限流。

覆盖: 国债收益率曲线 / 实际利率(TIPS) / 信用利差 / 主要汇率 / 波动率 / 全球股指 / 通胀
目的: 建立"全球全资产"面板, 供跨资产再平衡与波动率收割研究使用。
     (用户视角: 资产上链后, 池子边界=全球资产, 不是单一市场)
"""
import os
import random
import time

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "raw_fred")
PROXY = {"http": "http://127.0.0.1:3067", "https": "http://127.0.0.1:3067"}

SERIES = [
    # ---- 国债收益率曲线(全球资产定价之锚) ----
    ("DGS3MO", "美债3月", "rates"), ("DGS6MO", "美债6月", "rates"),
    ("DGS1", "美债1年", "rates"), ("DGS2", "美债2年", "rates"),
    ("DGS3", "美债3年", "rates"), ("DGS5", "美债5年", "rates"),
    ("DGS7", "美债7年", "rates"), ("DGS10", "美债10年", "rates"),
    ("DGS20", "美债20年", "rates"), ("DGS30", "美债30年", "rates"),
    # ---- 实际利率 / 通胀预期 ----
    ("DFII5", "TIPS实际利率5年", "rates"), ("DFII10", "TIPS实际利率10年", "rates"),
    ("DFII30", "TIPS实际利率30年", "rates"),
    ("T5YIE", "5年通胀预期", "inflation"), ("T10YIE", "10年通胀预期", "inflation"),
    ("T10Y2Y", "期限利差10Y-2Y", "rates"), ("T10Y3M", "期限利差10Y-3M", "rates"),
    # ---- 信用 ----
    ("BAMLH0A0HYM2", "高收益信用利差", "credit"),
    ("BAMLC0A0CM", "投资级信用利差", "credit"),
    # ---- 汇率(主要货币对) ----
    ("DEXUSEU", "汇率_美元欧元", "fx"), ("DEXJPUS", "汇率_日元美元", "fx"),
    ("DEXUSUK", "汇率_美元英镑", "fx"), ("DEXCHUS", "汇率_人民币美元", "fx"),
    ("DEXCAUS", "汇率_加元美元", "fx"), ("DEXAUS", "汇率_澳元美元", "fx"),
    ("DEXSZUS", "汇率_瑞郎美元", "fx"), ("DEXBZUS", "汇率_雷亚尔美元", "fx"),
    ("DEXINUS", "汇率_卢比美元", "fx"), ("DEXKOUS", "汇率_韩元美元", "fx"),
    ("DEXMXUS", "汇率_比索美元", "fx"), ("DEXNOUS", "汇率_挪威克朗", "fx"),
    ("DEXSDUS", "汇率_瑞典克朗", "fx"), ("DEXTHUS", "汇率_泰铢美元", "fx"),
    ("DEXMAUS", "汇率_林吉特美元", "fx"), ("DEXSIUS", "汇率_新元美元", "fx"),
    ("DTWEXBGS", "美元指数_广义", "fx"),
    # ---- 波动率 / 风险 ----
    ("VIXCLS", "VIX波动率指数", "volatility"),
    ("STLFSI4", "圣路易斯金融压力", "volatility"),
    ("NFCI", "芝加哥金融条件", "volatility"),
    # ---- 全球股指 ----
    ("SP500", "标普500", "equity"), ("DJIA", "道琼斯", "equity"),
    ("NASDAQCOM", "纳斯达克综指", "equity"),
    ("WILL5000IND", "威尔希尔5000", "equity"),
    ("NIKKEI225", "日经225", "equity"),
    # ---- 通胀 / 大宗指标 ----
    ("CPIAUCSL", "美国CPI", "inflation"), ("PCEPI", "美国PCE", "inflation"),
    ("PPIACO", "美国PPI", "inflation"),
    # ---- 房地产 ----
    ("CSUSHPINSA", "Case-Shiller房价", "housing"),
    ("MSACSR", "新屋售价中位", "housing"),
]

METAMAP = {s: (n, g) for s, n, g in SERIES}


def fetch(sid, tries=3):
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
            df = df.dropna().drop_duplicates("date").sort_values("date")
            if df.empty:
                raise ValueError("empty")
            return df.reset_index(drop=True)
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (k + 1))
    return None


def main():
    os.makedirs(RAW, exist_ok=True)
    rows, cols_m = [], {}
    for i, (sid, name, grp) in enumerate(SERIES, 1):
        p = os.path.join(RAW, f"{sid}.csv")
        n_new = 0
        if os.path.exists(p):
            df = pd.read_csv(p, parse_dates=["date"])
        else:
            df = fetch(sid)
            if df is not None:
                df.to_csv(p, index=False, encoding="utf-8-sig")
                n_new = len(df)
        if os.path.exists(p):
            d = pd.read_csv(p, parse_dates=["date"]).set_index("date")["value"].dropna()
            cols_m[sid] = d.resample("ME").last()
            rows.append({"id": sid, "name": name, "group": grp, "n": len(d),
                         "start": str(d.index[0].date()), "end": str(d.index[-1].date()),
                         "last": float(d.iloc[-1]), "new": n_new})
            print(f"[{i:2d}/{len(SERIES)}] {sid:14s} {name:14s} {len(d):6d} {d.index[0].date()}~{d.index[-1].date()} last={d.iloc[-1]:.4g}{' NEW' if n_new else ''}")
        else:
            rows.append({"id": sid, "name": name, "group": grp, "n": 0, "start": "", "end": "", "last": None, "new": 0})
            print(f"[{i:2d}/{len(SERIES)}] {sid:14s} {name:14s} FAIL")
        time.sleep(random.uniform(1.5, 3.0))

    pd.DataFrame(rows).to_csv(os.path.join(HERE, "data", "global_assets_coverage.csv"),
                              index=False, encoding="utf-8-sig")
    pm = pd.DataFrame(cols_m).sort_index()
    pm.to_csv(os.path.join(HERE, "data", "global_assets_monthly.csv"), encoding="utf-8-sig")
    print(f"\n月频面板 {pm.shape}  落盘 {len([r for r in rows if r['n'] > 0])}/{len(rows)} 个序列")
    rep = pd.DataFrame(rows)
    print(rep[rep.n > 0].groupby("group").agg(个数=("id", "count"), 最早=("start", "min"),
                                              最晚=("end", "max")).to_string())


if __name__ == "__main__":
    main()
