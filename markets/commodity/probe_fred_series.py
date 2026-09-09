"""探测 FRED 大宗商品候选序列的可用性(行数/起止/频率)，用于定池。

用法: python probe_fred_series.py
输出: candidates_probe.csv
"""
import os

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "candidates_probe.csv")
PROXY = {"http": "http://127.0.0.1:3067", "https": "http://127.0.0.1:3067"}

# (FRED ID, 中文名, 分组, 单位说明)
CANDIDATES = [
    # 贵金属
    ("GOLDPMGBD228NLBM", "黄金_伦敦PM", "precious", "USD/oz"),
    ("SLVPRUSD", "白银_伦敦", "precious", "USD/oz"),
    ("IR14270", "黄金_月度替代", "precious", "?"),
    ("PPLTUSDM", "铂金", "precious", "USD/oz"),
    ("PALLUSDM", "钯金", "precious", "USD/oz"),
    ("PPLSTERUSDM", "铂金_替代", "precious", "USD/oz"),
    # 工业金属
    ("PCOPPUSDM", "铜", "industrial", "USD/mt"),
    ("PALUMUSDM", "铝", "industrial", "USD/mt"),
    ("PZINCUSDM", "锌", "industrial", "USD/mt"),
    ("PNICKUSDM", "镍", "industrial", "USD/mt"),
    ("PTINUSDM", "锡", "industrial", "USD/mt"),
    ("PLEADUSDM", "铅", "industrial", "USD/mt"),
    ("PIORECRUSDM", "铁矿石", "industrial", "USD/mt"),
    ("PMOLYUSDM", "钼", "industrial", "USD/mt"),
    ("PURANUSDM", "铀", "industrial", "USD/lb"),
    # 能源
    ("DCOILWTICO", "原油_WTI", "energy", "USD/bbl"),
    ("DCOILBRENTEU", "原油_Brent", "energy", "USD/bbl"),
    ("DHHNGSP", "天然气_HenryHub", "energy", "USD/mmbtu"),
    ("PNGASEUUSDM", "天然气_欧洲", "energy", "USD/mmbtu"),
    ("PNgasUSUSDM", "天然气_美国", "energy", "USD/mmbtu"),
    ("PCARBMUSDM", "煤炭_澳洲", "energy", "USD/mt"),
    # 农产品
    ("PMAIZMTUSDM", "玉米", "agri", "USD/mt"),
    ("PWHEAMTUSDM", "小麦", "agri", "USD/mt"),
    ("PSOYBUSDQ", "大豆", "agri", "USD/mt"),
    ("PSUGAUSAUSDM", "糖", "agri", "USD/mt"),
    ("PCOFFOTMUSDM", "咖啡", "agri", "USD/mt"),
    ("PCOCOUSDM", "可可", "agri", "USD/mt"),
    ("PCOTTINDUSDM", "棉花", "agri", "USD/mt"),
    ("PRICENPQUSDM", "大米", "agri", "USD/mt"),
    # 综合指数
    ("PALLFNFINDEXM", "大宗商品全指数", "index", "index"),
    ("PNRGINDEXM", "能源指数", "index", "index"),
    ("PMETAINDEXM", "金属指数", "index", "index"),
    ("PAGRIINDEXM", "农产品指数", "index", "index"),
]


def fetch(sid):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
    try:
        r = requests.get(url, proxies=PROXY, timeout=30)
        r.raise_for_status()
        txt = r.text.strip()
        if not txt or "!" in txt.split("\n")[0]:
            return None
        df = pd.read_csv(pd.io.common.StringIO(txt), parse_dates=["observation_date"])
    except Exception as e:  # noqa: BLE001
        return {"err": str(e)[:60]}
    vals = pd.to_numeric(df.iloc[:, 1], errors="coerce").dropna()
    if vals.empty:
        return None
    return {
        "rows": int(len(df)),
        "valid": int(len(vals)),
        "start": str(df["observation_date"].iloc[0].date()),
        "end": str(df["observation_date"].iloc[-1].date()),
        "last": float(vals.iloc[-1]),
    }


def main():
    rows = []
    for sid, name, grp, unit in CANDIDATES:
        r = fetch(sid)
        if r is None:
            rows.append({"id": sid, "name": name, "group": grp, "unit": unit,
                         "rows": 0, "valid": 0, "start": "", "end": "", "last": None,
                         "usable": "FAIL"})
            print(f"  FAIL  {sid:22s} {name}")
            continue
        if "err" in r:
            rows.append({"id": sid, "name": name, "group": grp, "unit": unit, "usable": "ERR:" + r["err"]})
            print(f"  ERR   {sid:22s} {name}  {r['err']}")
            continue
        ok = "OK" if r["valid"] > 120 else "SHORT"
        rows.append({"id": sid, "name": name, "group": grp, "unit": unit,
                     "rows": r["rows"], "valid": r["valid"], "start": r["start"],
                     "end": r["end"], "last": r["last"], "usable": ok})
        print(f"  {ok:5s} {sid:22s} {name:14s} {r['valid']:5d} pts  {r['start']} ~ {r['end']}  last={r['last']:.4g}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"\n存 {OUT}   可用: {sum(1 for r in rows if r.get('usable') == 'OK')}/{len(rows)}")


if __name__ == "__main__":
    main()
