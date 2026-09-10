"""FRED 大宗商品现货价(IMF/World Bank 口径)全量抓取 —— 本地数据资产化。

设计原则(用户: "数据才是一切"):
  1. 原始序列全量落盘 raw_fred/<ID>.csv —— 保留最大信息量, 不因某次研究需求裁剪;
  2. 同时产出对齐后的宽表面板(月度/周度), 供回测直接消费;
  3. 增量更新: 已存在的序列与本地合并去重, 只补新点;
  4. 带重试 + 限速, 防 FRED 限流(实测会偶发 404)。

覆盖: 贵金属 / 工业金属 / 能源 / 农产品 / 综合指数
"""
import os
import time

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "raw_fred")
PROXY = {"http": "http://127.0.0.1:3067", "https": "http://127.0.0.1:3067"}

# (ID, 中文名, 分组, 单位)
SERIES = [
    # ---- 贵金属 (IMF 口径 2015 起; IR/IQ 系列为指数, 历史更长) ----
    ("IQ12260", "黄金_指数", "precious", "index"),
    ("IR14270", "黄金_指数2", "precious", "index"),
    ("GOLDPMGBD228NLBM", "黄金_伦敦PM", "precious", "USD/oz"),
    ("SLVPRUSD", "白银_伦敦", "precious", "USD/oz"),
    ("PPLTUSDM", "铂金", "precious", "USD/oz"),
    ("PALLUSDM", "钯金", "precious", "USD/oz"),
    # ---- 工业金属 ----
    ("PCOPPUSDM", "铜", "industrial", "USD/mt"),
    ("PALUMUSDM", "铝", "industrial", "USD/mt"),
    ("PZINCUSDM", "锌", "industrial", "USD/mt"),
    ("PNICKUSDM", "镍", "industrial", "USD/mt"),
    ("PTINUSDM", "锡", "industrial", "USD/mt"),
    ("PLEADUSDM", "铅", "industrial", "USD/mt"),
    ("PIORECRUSDM", "铁矿石", "industrial", "USD/mt"),
    ("PURANUSDM", "铀", "industrial", "USD/lb"),
    ("PMOLYUSDM", "钼", "industrial", "USD/mt"),
    # ---- 能源 ----
    ("DCOILWTICO", "原油_WTI", "energy", "USD/bbl"),
    ("DCOILBRENTEU", "原油_Brent", "energy", "USD/bbl"),
    ("DHHNGSP", "天然气_HenryHub", "energy", "USD/mmbtu"),
    ("PNGASEUUSDM", "天然气_欧洲", "energy", "USD/mmbtu"),
    ("PNgasUSUSDM", "天然气_美国", "energy", "USD/mmbtu"),
    ("PCARBMUSDM", "煤炭_澳洲", "energy", "USD/mt"),
    ("PCARBNUSDM", "煤炭_南非", "energy", "USD/mt"),
    # ---- 农产品 ----
    ("PMAIZMTUSDM", "玉米", "agri", "USD/mt"),
    ("PWHEAMTUSDM", "小麦", "agri", "USD/mt"),
    ("PSOYBUSDQ", "大豆", "agri", "USD/mt"),
    ("PSUGAUSAUSDM", "糖", "agri", "USD/mt"),
    ("PCOFFOTMUSDM", "咖啡", "agri", "USD/mt"),
    ("PCOCOUSDM", "可可", "agri", "USD/mt"),
    ("PCOTTINDUSDM", "棉花", "agri", "USD/mt"),
    ("PRICENPQUSDM", "大米", "agri", "USD/mt"),
    ("PBARLUSDM", "大麦", "agri", "USD/mt"),
    ("PSORGUSDM", "高粱", "agri", "USD/mt"),
    ("PBEEFUSDM", "牛肉", "agri", "USD/mt"),
    ("PPOULTUSDM", "禽肉", "agri", "USD/mt"),
    ("PFISHUSDM", "鱼粉", "agri", "USD/mt"),
    ("PWOOLCUSDM", "羊毛", "agri", "USD/mt"),
    ("PRUBBUSDM", "橡胶", "agri", "USD/mt"),
    ("PLOGSKUSDM", "原木", "agri", "USD/mt"),
    ("PBANSOPUSDM", "香蕉", "agri", "USD/mt"),
    ("PORANGUSDM", "橙子", "agri", "USD/mt"),
    ("PPOILUSDM", "棕榈油", "agri", "USD/mt"),
    ("PSUNOUSDM", "葵花油", "agri", "USD/mt"),
    ("PGRUNOUSDM", "花生油", "agri", "USD/mt"),
    ("PSOYOUSDM", "豆油", "agri", "USD/mt"),
    ("PCOCOOUSDM", "椰子油", "agri", "USD/mt"),
    ("POLVOILUSDM", "橄榄油", "agri", "USD/mt"),
    # ---- 综合/分组指数 ----
    ("PALLFNFINDEXM", "商品指数_全", "index", "index"),
    ("PNRGINDEXM", "商品指数_能源", "index", "index"),
    ("PMETAINDEXM", "商品指数_金属", "index", "index"),
    ("PAGRIINDEXM", "商品指数_农产品", "index", "index"),
    ("PRAWMINDEXM", "商品指数_原材料", "index", "index"),
    ("PBEGEMINDEXM", "商品指数_新兴", "index", "index"),
    ("PNONEGINDEXM", "商品指数_非能源", "index", "index"),
    ("PBEVPINDEXM", "商品指数_饮料", "index", "index"),
    ("PFOODINDEXM", "商品指数_食品", "index", "index"),
    ("POILAPSPINDEXM", "商品指数_油籽油脂", "index", "index"),
    ("PPREMEINDEXM", "商品指数_贵金属", "index", "index"),
    ("PBASEMETAINDEXM", "商品指数_基金属", "index", "index"),
]

META = {sid: (nm, grp, unit) for sid, nm, grp, unit in SERIES}


def fetch_one(sid, tries=4):
    """带重试抓取单个 FRED 序列; 返回 DataFrame(date, value) 或 None。"""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
    last = None
    for k in range(tries):
        try:
            r = requests.get(url, proxies=PROXY, timeout=30)
            r.raise_for_status()
            txt = r.text.strip()
            if not txt or "observation_date" not in txt:
                raise ValueError("unexpected payload")
            df = pd.read_csv(pd.io.common.StringIO(txt))
            df.columns = ["date", "value"]
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            df = df.dropna(subset=["value"]).drop_duplicates("date").sort_values("date")
            if df.empty:
                raise ValueError("no valid rows")
            return df.reset_index(drop=True)
        except Exception as e:  # noqa: BLE001
            last = str(e)[:60]
            time.sleep(1.5 * (k + 1))
    print(f"    !! {sid} 失败: {last}")
    return None


def load_existing(path):
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        return df
    except Exception:  # noqa: BLE001
        return None


def main():
    os.makedirs(RAW, exist_ok=True)
    panel_wide, panel_m = {}, {}
    report = []

    for i, (sid, name, grp, unit) in enumerate(SERIES, 1):
        path = os.path.join(RAW, f"{sid}.csv")
        old = load_existing(path)
        df = fetch_one(sid)
        n_new = 0
        if df is not None:
            if old is not None and len(old):
                merged = pd.concat([old, df]).drop_duplicates("date").sort_values("date")
                n_new = len(merged) - len(old)
                df = merged
            df.to_csv(path, index=False, encoding="utf-8-sig")
            s = df.set_index("date")["value"]
            panel_wide[sid] = s
            # 日频/周频 → 月频(月末最后值)
            panel_m[sid] = s.resample("ME").last().dropna()
        else:
            if old is not None:
                s = old.set_index("date")["value"]
                panel_wide[sid] = s
                panel_m[sid] = s.resample("ME").last().dropna()

        rows = len(panel_wide.get(sid, pd.Series(dtype=float)))
        st = panel_wide[sid].index[0].date() if rows else "-"
        en = panel_wide[sid].index[-1].date() if rows else "-"
        report.append({"id": sid, "name": name, "group": grp, "unit": unit,
                       "n_obs": int(rows), "start": str(st), "end": str(en), "new": int(n_new)})
        flag = f"(新抓取 +{n_new})" if df is not None else "(用旧档)"
        print(f"[{i:2d}/{len(SERIES)}] {sid:20s} {name:16s} {rows:5d} 点 {st} ~ {en} {flag}")
        time.sleep(0.4)

    # 原始频率宽表 + 月频宽表
    pw = pd.DataFrame(panel_wide).sort_index()
    pm = pd.DataFrame(panel_m).sort_index()
    pw.to_csv(os.path.join(HERE, "data", "commodity_fred_rawfreq.csv"), encoding="utf-8-sig")
    pm.to_csv(os.path.join(HERE, "data", "commodity_fred_monthly.csv"), encoding="utf-8-sig")

    rep = pd.DataFrame(report)
    rep.to_csv(os.path.join(HERE, "data", "commodity_fred_coverage.csv"), index=False, encoding="utf-8-sig")

    print("\n=== 覆盖报告 ===")
    print(rep.groupby("group")["n_obs"].agg(["count", "min", "median", "max"]).to_string())
    print(f"\n原始频率宽表: {pw.shape}   月频宽表: {pm.shape}")
    print(f"落盘目录: {RAW}  ({len(os.listdir(RAW))} 个原始序列)")


if __name__ == "__main__":
    main()
