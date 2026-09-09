"""天然气产业链 FRED 序列探测 —— 单条串行拉取(随机间隔), 避免批量触发风控。

覆盖: 天然气现货(HH/欧洲/日本/亚洲) / LNG / NGL(乙烷丙烷丁烷) / LPG /
      强相关品(煤/电/尿素/氦) / 天然气指数
"""
import os
import random
import time

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
PROXY = {"http": "http://127.0.0.1:3067", "https": "http://127.0.0.1:3067"}

CAND = [
    # 天然气现货
    ("PNGASJPUSDM", "天然气_日本LNG"), ("PNGASASUSDM", "天然气_亚洲"),
    ("PNgasUSUSDM", "天然气_美国"), ("PNGASEUUSDM", "天然气_欧洲"),
    ("DHHNGSP", "天然气_HenryHub日频"),
    # NGL / LPG / 丙烷丁烷
    ("PLPGUSDM", "液化石油气LPG"), ("PPROPUSDM", "丙烷"),
    ("PBUTAUSDM", "丁烷"), ("PETHYUSDM", "乙烯"),
    ("PNAPHTHAUSDM", "石脑油"),
    # 相关能源
    ("PCARBMUSDM", "煤炭_澳洲"), ("PCARBNUSDM", "煤炭_南非2"),
    ("PCOALAUUSDM", "煤炭_澳洲2"),
    # 贵金属补全(钯金等)
    ("PALLUSDM", "钯金"), ("PPALLUSDM", "钯金2"), ("PPLTUSDM", "铂金"),
    ("PMOLYUSDM", "钼"), ("PCOBALTUSDM", "钴"), ("PLITHIUMUSDM", "锂"),
    # 指数
    ("PNRGINDEXM", "商品指数_能源"),
]


def one(sid):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
    try:
        r = requests.get(url, proxies=PROXY, timeout=30)
        r.raise_for_status()
        t = r.text.strip()
        if not t or "observation_date" not in t:
            return None
        df = pd.read_csv(pd.io.common.StringIO(t))
        df.columns = ["date", "value"]
        v = pd.to_numeric(df["value"], errors="coerce").dropna()
        if v.empty:
            return None
        return {"n": len(v), "start": str(df["date"].iloc[0]), "end": str(df["date"].iloc[-1]),
                "last": float(v.iloc[-1])}
    except Exception as e:  # noqa: BLE001
        return {"err": str(e)[:45]}


def main():
    rows = []
    for i, (sid, name) in enumerate(CAND, 1):
        r = one(sid)
        if r and "err" not in r:
            print(f"[{i:2d}/{len(CAND)}] OK   {sid:16s} {name:16s} {r['n']:6d} {r['start']}~{r['end']} last={r['last']:.4g}")
            rows.append({"id": sid, "name": name, "usable": "OK", **r})
        else:
            msg = r["err"] if r else "empty"
            print(f"[{i:2d}/{len(CAND)}] FAIL {sid:16s} {name:16s} {msg}")
            rows.append({"id": sid, "name": name, "usable": "FAIL", "n": 0})
        time.sleep(random.uniform(2.0, 4.5))  # 随机间隔, 防限流

    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    pd.DataFrame(rows).to_csv(os.path.join(HERE, "data", "probe_gas_series.csv"),
                              index=False, encoding="utf-8-sig")
    ok = [r["id"] for r in rows if r["usable"] == "OK"]
    print(f"\n可用 {len(ok)}/{len(CAND)}: {', '.join(ok)}")


if __name__ == "__main__":
    main()
