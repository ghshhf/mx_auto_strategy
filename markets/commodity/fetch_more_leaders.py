# -*- coding: utf-8 -*-
"""
补抓【各行各业龙头】(串行, 一个一个, 7.5s 间隔, 避免限速)
目标: 把高波动(vol>=40)候选池从 49 个扩到 100+, 才能撑起 N=50 的跨行业宽池。
覆盖: 半导体/设备 · 生物科技 · 新能源 · 矿业金属 · 油服 · 航空邮轮 · 博彩酒店
      · 加密 · 中国ADR · 新兴市场ETF · 券商/金融高波 · 零售高波
"""
import time, json, urllib.request, pandas as pd

KEY = "8ab093782d9f44a6b0e57d2a50d5ed93"
OUT = "data/us_universe_weekly_adjclose.csv"
PROXY = "http://127.0.0.1:3067"
SLEEP = 7.5

TICKERS = [
    # ---- 半导体/设备(高波动周期) ----
    "AMAT", "LRCX", "QCOM", "TXN", "ADI", "NXPI", "ONTO", "ACMR", "UCTT", "ICHR",
    "CRUS", "DIOD", "RMBS", "ALGM", "SITM", "LSCC", "FORM", "COHU", "AEHR", "MRAM",
    # ---- 生物科技(极高波动) ----
    "BIIB", "MRNA", "INCY", "BMRN", "UTHR", "EXAS", "NBIX", "JAZZ", "IONS",
    "SRPT", "RARE", "FOLD", "CRSP", "NTLA", "BEAM", "EDIT", "VIR", "ARWR", "PCVX", "KRYS",
    # ---- 新能源/清洁(高波动) ----
    "ENPH", "SEDG", "RUN", "PLUG", "BE", "CHPT", "QS", "SLDP", "MVST", "NXT", "FLNC", "STEM",
    # ---- 矿业/金属/铀(周期高波动) ----
    "FCX", "NEM", "WPM", "PAAS", "HL", "CDE", "GOLD", "AU", "KGC", "AG", "EXK",
    "IAG", "SAND", "FSM", "SVM", "LAC", "ALB", "MP", "UUUU", "CCJ", "UEC", "DNN", "LEU",
    # ---- 油服/能源设备 ----
    "SLB", "OII", "NOV", "HP", "WFRD", "LBRT", "PUMP", "CHX", "VAL", "RIG", "NE", "DO", "PTEN",
    # ---- 航空/邮轮/出行(极高波动) ----
    "CCL", "NCLH", "UAL", "DAL", "AAL", "LUV", "ALK", "JBLU", "SNCY", "ULCC",
    # ---- 博彩/酒店/消费高波 ----
    "MAR", "HLT", "LVS", "WYNN", "MGM", "CZR", "PENN", "DKNG", "MCRI", "BYD",
    # ---- 加密权益 ----
    "RIOT", "COIN", "CLSK", "IREN", "WULF", "CORZ", "BITF", "HUT", "BTBT", "GLXY",
    # ---- 中国ADR(高波动) ----
    "PDD", "JD", "BABA", "LI", "XPEV", "NIO", "TME", "BEKE", "FUTU", "YMM",
    "ZTO", "LEGN", "TIGR", "GDS", "VNET", "DQ", "JKS", "CSIQ", "NIU", "QFIN",
    # ---- 新兴市场/国家ETF ----
    "EEM", "VWO", "EWU", "EWP", "EWI", "EWL", "EWN", "EWQ", "EWK", "EWZ",
    "EZA", "TUR", "THD", "EPU", "ECH", "ARGT", "FXI", "MCHI", "KWEB", "CQQQ",
    "ASHR", "GXC", "EWW", "EWS", "EWM", "EPHE", "EIDO", "ENZL", "EIS", "ERUS",
]


def fetch(sym):
    url = (f"https://api.twelvedata.com/time_series?symbol={sym}"
           f"&interval=1week&outputsize=5000&apikey={KEY}")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    try:
        with opener.open(url, timeout=45) as r:
            d = json.load(r)
        if "values" not in d:
            return None
        df = pd.DataFrame(d["values"])[["datetime", "close"]]
        df["datetime"] = pd.to_datetime(df["datetime"])
        s = df.set_index("datetime")["close"].astype(float).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        s.name = sym
        return s
    except Exception as e:
        print(f"  FAIL {sym}: {type(e).__name__} {e}", flush=True)
        return None


panel = pd.read_csv(OUT, index_col=0, parse_dates=True)
panel = panel.loc[:, ~panel.columns.duplicated()]
panel = panel[~panel.index.duplicated(keep="last")]
have = set(panel.columns)
todo = [t for t in TICKERS if t not in have]
print(f"现有宇宙 {panel.shape[1]} 列 | 待抓 {len(todo)} 个 (已存在 {len(TICKERS)-len(todo)} 个跳过)", flush=True)

added = []
for i, t in enumerate(todo, 1):
    s = fetch(t)
    if s is not None and len(s) > 100:
        added.append(s)
        print(f"  [{i}/{len(todo)}] OK   {t:<6} {len(s):>5} 周  {s.index[0].date()} ~ {s.index[-1].date()}", flush=True)
    else:
        print(f"  [{i}/{len(todo)}] MISS {t}", flush=True)
    # 每 20 个存一次盘, 防中断丢数据
    if len(added) > 0 and len(added) % 20 == 0:
        new = pd.concat(added, axis=1)
        new = new[~new.index.duplicated(keep="last")]
        panel = pd.concat([panel, new], axis=1)
        panel = panel.loc[:, ~panel.columns.duplicated()]
        panel.to_csv(OUT)
        print(f"  --- 阶段存盘: 宇宙 {panel.shape[1]} 列 ---", flush=True)
        added = []
    time.sleep(SLEEP)

if added:
    new = pd.concat(added, axis=1)
    new = new[~new.index.duplicated(keep="last")]
    panel = pd.concat([panel, new], axis=1)
    panel = panel.loc[:, ~panel.columns.duplicated()]

panel.to_csv(OUT)
print(f"\n完成. 宇宙列数 → {panel.shape[1]}")
