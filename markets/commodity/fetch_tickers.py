# -*- coding: utf-8 -*-
"""串行(一个一个)抓取指定 ticker 周线, 追加到 us_universe_weekly_adjclose.csv.
用户提醒: 批量抓容易触发限速 → 单条串行 + 间隔(7.5s, 免费档 8 credits/min)。
修复: duplicate labels (panel 去重 + 新序列索引去重)。
"""
import time, json, urllib.request, pandas as pd

KEY = "8ab093782d9f44a6b0e57d2a50d5ed93"
OUT = "data/us_universe_weekly_adjclose.csv"
PROXY = "http://127.0.0.1:3067"
SLEEP = 7.5

# ===== 补现有宇宙空白: 高波动 + 不同行业 + 跨地区 =====
TICKERS = [
    # 航运 / 港口 / 物流 (极强周期, 高波动)
    "ZIM", "SBLK", "GNK", "STNG", "MATX", "DAC", "SFL", "EGLE",
    "GOGL", "DSX", "ESEA", "GSL", "SB", "PANL", "CPLP", "TNK",
    # 国家/地区代理 (日/韩/台/德/巴西/澳, 上链后可直接买)
    "EWJ", "EWY", "EWT", "EWG", "EWZ", "EWA", "EWH", "INDA",
    # 高波动行业 ETF
    "XBI", "XOP", "XME", "KRE", "ARKK", "URA", "XRT", "ITB",
    # 加密相关权益
    "MARA", "RIOT", "COIN", "CLSK", "IREN", "WULF", "CORZ", "HIVE",
    # 半导体/AI 高波动
    "ASML", "ARM", "MRVL", "ONTO", "TER", "ENTG", "MKSI", "AEHR",
    # 资源/矿业 (高波动周期)
    "SCCO", "AEM", "WPM", "RGLD", "PAAS", "HL", "CDE", "MTRN",
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
        s = s[~s.index.duplicated(keep="last")]      # ← 修复 duplicate labels
        s.name = sym
        return s
    except Exception as e:
        print(f"  FAIL {sym}: {type(e).__name__} {e}", flush=True)
        return None


panel = pd.read_csv(OUT, index_col=0, parse_dates=True)
panel = panel.loc[:, ~panel.columns.duplicated()]      # ← 修复 duplicate labels
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
    time.sleep(SLEEP)

if added:
    new = pd.concat(added, axis=1)
    new = new[~new.index.duplicated(keep="last")]
    panel = pd.concat([panel, new], axis=1)
    panel = panel.loc[:, ~panel.columns.duplicated()]
    panel.to_csv(OUT)
    print(f"\n已追加 {len(new.columns)} 个: {list(new.columns)}")
    print(f"宇宙列数 → {panel.shape[1]}")
else:
    print("\n无新增标的")
