"""探测贵金属长历史源 + Yahoo 可投资商品 ETF/期货的可用性。

1) FRED 贵金属长序列候选(需 >1992 起)，并打印值域判断是否为指数口径
2) Yahoo 商品 ETF / 期货 周线可用性(起止、点数)
"""
import os

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "candidates_precious_etf.csv")
PROXY = {"http": "http://127.0.0.1:3067", "https": "http://127.0.0.1:3067"}

FRED_CAND = [
    ("IR14270", "黄金_指数1973起"),
    ("GOLDPMGBD228NLBM", "黄金_伦敦PM2015起"),
    ("SLVPRUSD", "白银_2015起"),
    ("IQ12260", "黄金_alt"),
    ("GOLDPMGBD228NLBMEU", "黄金_欧元计价"),
    ("SLVPRUSDEU", "白银_欧元计价"),
    ("PCRETT01USM661N", "黄金_其它"),
    ("PPLTUSDM", "铂金_2015起"),
    ("PALLUSDM", "钯金_2015起"),
    ("PPLSTERUSDM", "铂金_英镑"),
]

YAHOO = [
    ("GC=F", "黄金期货", "precious"), ("SI=F", "白银期货", "precious"),
    ("PL=F", "铂金期货", "precious"), ("PA=F", "钯金期货", "precious"),
    ("HG=F", "铜期货", "industrial"), ("ALI=F", "铝期货", "industrial"),
    ("GLD", "黄金ETF", "precious"), ("IAU", "黄金ETF2", "precious"),
    ("SLV", "白银ETF", "precious"), ("PPLT", "铂金ETF", "precious"),
    ("PALL", "钯金ETF", "precious"), ("CPER", "铜ETF", "industrial"),
    ("DBB", "基础金属ETF", "industrial"), ("JJU", "铜ETN", "industrial"),
    ("XME", "金属矿业股", "industrial"), ("GDX", "金矿股", "precious"),
    ("GDXJ", "小金矿股", "precious"),
    ("DBC", "综合商品ETF", "index"), ("GSG", "综合商品ETF2", "index"),
    ("USO", "原油ETF", "energy"), ("BNO", "布伦特ETF", "energy"),
    ("UNG", "天然气ETF", "energy"), ("XLE", "能源股ETF", "energy"),
    ("DBA", "农业ETF", "agri"), ("CORN", "玉米ETF", "agri"),
    ("WEAT", "小麦ETF", "agri"), ("SOYB", "大豆ETF", "agri"),
    ("NIB", "可可ETF", "agri"), ("JO", "咖啡ETF", "agri"),
    ("BAL", "棉花ETF", "agri"), ("CANE", "糖ETF", "agri"),
]


def fred(sid):
    try:
        r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}",
                         proxies=PROXY, timeout=30)
        r.raise_for_status()
        txt = r.text.strip()
        if not txt:
            return None
        df = pd.read_csv(pd.io.common.StringIO(txt), parse_dates=["observation_date"])
    except Exception as e:  # noqa: BLE001
        return {"err": str(e)[:50]}
    v = pd.to_numeric(df.iloc[:, 1], errors="coerce").dropna()
    if v.empty:
        return None
    return {"rows": len(v), "start": str(df["observation_date"].iloc[0].date()),
            "end": str(df["observation_date"].iloc[-1].date()),
            "first": float(v.iloc[0]), "last": float(v.iloc[-1]),
            "min": float(v.min()), "max": float(v.max())}


def main():
    rows = []
    print("== FRED 贵金属候选 ==")
    for sid, name in FRED_CAND:
        r = fred(sid)
        if r is None or "err" in (r or {}):
            msg = (r or {}).get("err", "empty")
            print(f"  FAIL {sid:22s} {name}  {msg}")
            rows.append({"src": "FRED", "id": sid, "name": name, "usable": "FAIL"})
            continue
        print(f"  {r['rows']:5d} {sid:22s} {name:16s} {r['start']}~{r['end']}  "
              f"first={r['first']:.4g} last={r['last']:.4g} min={r['min']:.4g} max={r['max']:.4g}")
        rows.append({"src": "FRED", "id": sid, "name": name, "usable": "OK",
                     "rows": r["rows"], "start": r["start"], "end": r["end"],
                     "last": r["last"]})

    print("\n== Yahoo 商品 ETF/期货 (周线) ==")
    try:
        import yfinance as yf
        for tk, name, grp in YAHOO:
            try:
                df = yf.download(tk, period="max", interval="1wk",
                                 progress=False, auto_adjust=False)
            except Exception as e:  # noqa: BLE001
                print(f"  ERR  {tk:8s} {name}  {str(e)[:40]}")
                rows.append({"src": "Yahoo", "id": tk, "name": name, "group": grp, "usable": "ERR"})
                continue
            if df is None or df.empty:
                print(f"  EMPTY {tk:8s} {name}")
                rows.append({"src": "Yahoo", "id": tk, "name": name, "group": grp, "usable": "EMPTY"})
                continue
            col = "Adj Close" if "Adj Close" in df.columns else "Close"
            s = df[col].dropna()
            idx = s.index
            st = idx[0].date() if hasattr(idx[0], "date") else idx[0]
            en = idx[-1].date() if hasattr(idx[-1], "date") else idx[-1]
            print(f"  {len(s):5d} {tk:8s} {name:14s} {st}~{en}  last={float(s.iloc[-1]):.4g}")
            rows.append({"src": "Yahoo", "id": tk, "name": name, "group": grp, "usable": "OK",
                         "rows": int(len(s)), "start": str(st), "end": str(en),
                         "last": float(s.iloc[-1])})
    except ImportError:
        print("  yfinance 未安装")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"\n存 {OUT}")


if __name__ == "__main__":
    main()
