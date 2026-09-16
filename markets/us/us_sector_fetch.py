"""us_sector_fetch.py - 联网抓取美股**权威行业分类**, 落地为本地可复用数据。

背景
----
本地 `markets/us/` 的行业标签是之前手工编的(self-invented: 软饮/日化家清/电商平台...),
不是任何官方口径, 无法与外部数据对齐。本脚本联网取三个**互相独立**的官方/权威源:

  源 A  Nasdaq 官方 screener API      -> sector(12类) / industry(细分) / marketCap / ipoyear
        全市场 ~7,095 只, 一个请求拿全。覆盖纳交所+纽交所+美交所。
  源 B  GICS 官方分类 (S&P 500 成分)  -> GICS Sector(标准 11 大类) / GICS Sub-Industry / CIK
        经 `gh api` 从 datasets/s-and-p-500-companies 取（raw.githubusercontent 被墙）。
        **GICS 是行业分类的行业标准**, Nasdaq/SEC 都不等于它。
  源 C  SEC EDGAR                     -> sic(4位行业码) / sicDescription / entityType (监管口径)
        CIK 来源: 优先用源 B 的 CIK; 非 S&P 成分用 efts.sec.gov 全文本搜索反查。
        ⚠️ 只有 `data.sec.gov` 可达; `www.sec.gov` 返回 403(代理层阻挡)。

实测被墙/失效的源(不再尝试):
  · Yahoo Finance      : 中国大陆 IP 直接返回 "no longer accessible from mainland China" 页
  · Wikipedia          : 代理下 code=000 连接失败
  · raw.githubusercontent.com : code=000
  · www.sec.gov        : 403 (data.sec.gov / efts.sec.gov 正常)
  · stockanalysis.com  : /api/screener/s/f 返回 404

产物
----
  data/raw_nasdaq_screener.json   Nasdaq 全市场原始 dump (可离线复用)
  data/gics_sp500_raw.csv         GICS 官方分类原始表 (S&P500 503 只, 含 CIK)
  data/raw_sec_sic.json           本池 145 只的 SEC SIC 抓取结果(含缓存, 重跑秒回)
  data/us_sector_map.csv          **主产物**: 145 只 × [三源分类 + 市值 + 上市年 + 统一11大类]

用法
----
    python us_sector_fetch.py            # 增量抓取(有缓存则跳过)
    python us_sector_fetch.py --refresh  # 强制重抓
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from net_config import proxy_opener  # noqa: E402

DATA = os.path.join(HERE, "data")
PANEL = os.path.join(DATA, "weekly_adjclose_full.csv")
NASDAQ_RAW = os.path.join(DATA, "raw_nasdaq_screener.json")
GICS_RAW = os.path.join(DATA, "gics_sp500_raw.csv")
SEC_RAW = os.path.join(DATA, "raw_sec_sic.json")
OUT_CSV = os.path.join(DATA, "us_sector_map.csv")

# ⚠️ 浏览器 UA 是硬要求: SEC 对非浏览器 UA 直接 403; Nasdaq 亦同
BUA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

NASDAQ_URL = ("https://api.nasdaq.com/api/screener/stocks"
              "?tableonly=true&limit=25000&offset=0&download=true")

# 已改名/换代码的标的 -> 现行 ticker (抓取用)
TICKER_ALIAS = {"FISV": "FI"}

REFRESH = "--refresh" in sys.argv


def get(url, ua=BUA, timeout=45, retry=3):
    """走 net_config 代理抓取, 带重试。返回 bytes。"""
    opener = proxy_opener()
    last = None
    for k in range(retry):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": ua,
                              "Accept": "application/json, text/html, */*",
                              "Accept-Language": "en-US,en;q=0.9"})
            with opener.open(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:                       # noqa: BLE001
            last = e
            time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"GET 失败 {url}: {last}")


def tickers_of_pool():
    import pandas as pd
    return list(pd.read_csv(PANEL, index_col=0, nrows=1).columns)


# ============================================================ 源 A: Nasdaq
def fetch_nasdaq():
    if os.path.exists(NASDAQ_RAW) and not REFRESH:
        d = json.load(open(NASDAQ_RAW, encoding="utf-8"))
        print(f"[A] Nasdaq 缓存命中 {len(d):,} 只")
        return d
    raw = get(NASDAQ_URL)
    rows = json.loads(raw.decode("utf-8"))["data"]["rows"]
    recs = {}
    for r in rows:
        sym = (r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        try:
            mc = float(str(r.get("marketCap") or "").replace(",", ""))
        except ValueError:
            mc = float("nan")
        recs[sym] = dict(name=(r.get("name") or "").strip(),
                         sector=(r.get("sector") or "").strip(),
                         industry=(r.get("industry") or "").strip(),
                         market_cap=mc,
                         ipo_year=(r.get("ipoyear") or "").strip(),
                         country=(r.get("country") or "").strip())
    json.dump(recs, open(NASDAQ_RAW, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"[A] Nasdaq 抓取 {len(recs):,} 只 -> {os.path.basename(NASDAQ_RAW)}")
    return recs


# ============================================================ 源 B: GICS
def fetch_gics():
    """GICS 官方分类。raw.githubusercontent 被墙 -> 走 gh api 取 base64。"""
    import base64
    if not os.path.exists(GICS_RAW) or REFRESH:
        r = subprocess.run(
            ["gh", "api",
             "repos/datasets/s-and-p-500-companies/contents/data/constituents.csv",
             "--jq", ".content"],
            capture_output=True, text=True, check=True)
        blob = base64.b64decode("".join(r.stdout.split()))
        open(GICS_RAW, "wb").write(blob)
        print(f"[B] GICS 抓取 -> {os.path.basename(GICS_RAW)}")
    import pandas as pd
    d = pd.read_csv(GICS_RAW)
    print(f"[B] GICS 命中 {len(d)} 只 S&P 500 成分 (GICS Sector + Sub-Industry + CIK)")
    return d


# ============================================================ 源 C: SEC SIC
def efts_cik(ticker):
    """用 EDGAR 全文本搜索反查 CIK(非 S&P 成分用)。"""
    q = quote(f'"{ticker}"')
    url = (f"https://efts.sec.gov/LATEST/search-index?q={q}"
           "&forms=10-K,10-Q,20-F")
    try:
        js = json.loads(get(url, timeout=30).decode("utf-8"))
    except Exception:                                # noqa: BLE001
        return None
    for h in js.get("hits", {}).get("hits", []):
        src = h.get("_source", {})
        if any(f"({ticker})" in n for n in (src.get("display_names") or [])):
            c = src.get("ciks") or []
            if c:
                return int(c[0])
    return None


def fetch_sec(pool, cik_hint):
    cache = {}
    if os.path.exists(SEC_RAW) and not REFRESH:
        cache = json.load(open(SEC_RAW, encoding="utf-8"))
    todo = [t for t in pool if t not in cache]
    if not todo:
        print(f"[C] SEC 缓存命中 {len(cache)} 只")
        return cache
    print(f"[C] 待抓 {len(todo)} 只 (CIK: 源B 命中 "
          f"{sum(1 for t in todo if cik_hint.get(t))} 只, 其余走 efts 反查)")
    for i, t in enumerate(todo, 1):
        alias = TICKER_ALIAS.get(t, t)
        cik = cik_hint.get(t) or efts_cik(alias)
        if not cik:
            cache[t] = {"found": False}
        else:
            try:
                js = json.loads(get(
                    f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                    timeout=30).decode("utf-8"))
                cache[t] = dict(found=True, cik=cik,
                                sec_name=js.get("name", ""),
                                sic=str(js.get("sic", "")),
                                sic_desc=js.get("sicDescription", ""),
                                entity_type=js.get("entityType", ""),
                                exchanges=js.get("exchanges", []))
            except Exception as e:                   # noqa: BLE001
                cache[t] = {"found": False, "err": str(e)[:60]}
        time.sleep(0.13)                              # SEC 限速 ~10 req/s
        if i % 25 == 0 or i == len(todo):
            print(f"[C] {i}/{len(todo)} ...")
    json.dump(cache, open(SEC_RAW, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return cache


# ============================================================ 统一 11 大类
# GICS 标准 11 大类 (官方英文 -> 中文)
GICS_TO_UNI = {
    "Information Technology": "信息技术", "Communication Services": "通信服务",
    "Consumer Discretionary": "可选消费", "Consumer Staples": "必需消费",
    "Health Care": "医疗保健", "Financials": "金融", "Industrials": "工业",
    "Energy": "能源", "Materials": "材料", "Utilities": "公用事业",
    "Real Estate": "房地产",
}
# Nasdaq 自己的 12 类 -> 统一命名。⚠️ Nasdaq 与 GICS 不同: 它没有 Communication
# Services, 把互联网/媒体塞进 Technology; 且 Telecommunications 是独立一类。
NASDAQ_TO_UNI = {
    "Technology": "信息技术", "Telecommunications": "通信服务",
    "Consumer Discretionary": "可选消费", "Consumer Staples": "必需消费",
    "Health Care": "医疗保健", "Finance": "金融", "Industrials": "工业",
    "Energy": "能源", "Basic Materials": "材料", "Utilities": "公用事业",
    "Real Estate": "房地产", "Miscellaneous": "其他",
}
# SEC SIC(4位) -> 统一 11 大类。仅覆盖本池实际出现的码 + 常见码; 其余走 division 兜底。
SIC_TO_UNI = {
    "2833": "医疗保健", "2834": "医疗保健", "2835": "医疗保健", "2836": "医疗保健",
    "3826": "医疗保健", "3841": "医疗保健", "3842": "医疗保健", "3843": "医疗保健",
    "3844": "医疗保健", "3845": "医疗保健", "3851": "医疗保健", "8062": "医疗保健",
    "8071": "医疗保健", "6324": "医疗保健", "8090": "医疗保健", "8011": "医疗保健",
    "3674": "信息技术", "3672": "信息技术", "3677": "信息技术", "3678": "信息技术",
    "3679": "信息技术", "3661": "信息技术", "3663": "信息技术", "3669": "信息技术",
    "3571": "信息技术", "3572": "信息技术", "3575": "信息技术", "3576": "信息技术",
    "3577": "信息技术", "3578": "信息技术", "3579": "信息技术", "7372": "信息技术",
    "3570": "信息技术", "3827": "信息技术", "3829": "信息技术",
    "2840": "必需消费", "2843": "必需消费", "2890": "材料",
    "7371": "信息技术", "7373": "信息技术", "7374": "信息技术", "7379": "信息技术",
    "7370": "信息技术", "7377": "信息技术",
    "4813": "通信服务", "4812": "通信服务", "4841": "通信服务", "4833": "通信服务",
    "4832": "通信服务", "7311": "通信服务", "7310": "通信服务", "7812": "通信服务",
    "7841": "通信服务", "7990": "通信服务", "7997": "通信服务", "7375": "通信服务",
    "4899": "通信服务", "2741": "通信服务",
    "3711": "可选消费", "3714": "可选消费", "3716": "可选消费", "3751": "可选消费",
    "5812": "可选消费", "5813": "可选消费", "5331": "可选消费", "5651": "可选消费",
    "5661": "可选消费", "5945": "可选消费", "5961": "可选消费", "5531": "可选消费",
    "5731": "可选消费", "5734": "可选消费", "7011": "可选消费", "7819": "可选消费",
    "7830": "可选消费", "3861": "可选消费", "3944": "可选消费", "2320": "可选消费",
    "3140": "可选消费", "3021": "可选消费", "5944": "可选消费", "5960": "可选消费",
    "2086": "必需消费", "2080": "必需消费", "2090": "必需消费", "2111": "必需消费",
    "2131": "必需消费", "2844": "必需消费", "2842": "必需消费", "2841": "必需消费",
    "5140": "必需消费", "5122": "必需消费", "2000": "必需消费", "2011": "必需消费",
    "2024": "必需消费", "2060": "必需消费", "2070": "必需消费", "2098": "必需消费",
    "5912": "必需消费", "5411": "必需消费", "5399": "必需消费", "5812b": "可选消费",
    "6021": "金融", "6022": "金融", "6020": "金融", "6035": "金融", "6036": "金融",
    "6311": "金融", "6331": "金融", "6321": "金融", "6351": "金融", "6411": "金融",
    "6211": "金融", "6221": "金融", "6282": "金融", "6141": "金融", "6153": "金融",
    "6159": "金融", "6199": "金融", "6099": "金融", "6733": "金融", "6770": "金融",
    "6200": "金融", "6280": "金融", "6710": "金融", "6712": "金融", "6779": "金融",
    "6162": "金融", "6163": "金融", "6199b": "金融",
    "3721": "工业", "3724": "工业", "3728": "工业", "3760": "工业", "3812": "工业",
    "3531": "工业", "3537": "工业", "3560": "工业", "3569": "工业", "3585": "工业",
    "3600": "工业", "3612": "工业", "3613": "工业", "3620": "工业", "3621": "工业",
    "3630": "工业", "3640": "工业", "3690": "工业", "3510": "工业", "3523": "工业",
    "3540": "工业", "3559": "工业", "3823": "工业", "3824": "工业", "3825": "工业",
    "3821": "工业", "4011": "工业", "4210": "工业", "4213": "工业", "4512": "工业",
    "4513": "工业", "4731": "工业", "4700": "工业", "4953": "工业", "7389": "工业",
    "8711": "工业", "8712": "工业", "8742": "工业", "8741": "工业", "1731": "工业",
    "1623": "工业", "1700": "工业", "7363": "工业", "7359": "工业", "7350": "工业",
    "1311": "能源", "1381": "能源", "1382": "能源", "1389": "能源", "2911": "能源",
    "1220": "能源", "1221": "能源", "4610": "能源", "4922": "能源", "4923": "能源",
    "4924": "能源", "1311b": "能源",
    "2810": "材料", "2821": "材料", "2860": "材料", "2870": "材料", "2890": "材料",
    "3312": "材料", "3317": "材料", "3350": "材料", "3357": "材料", "2611": "材料",
    "2621": "材料", "3241": "材料", "3270": "材料", "3334": "材料", "1040": "材料",
    "1000": "材料", "1021": "材料", "1090": "材料", "1470": "材料", "1400": "材料",
    "4911": "公用事业", "4931": "公用事业", "4939": "公用事业", "4941": "公用事业",
    "4952": "公用事业", "4991": "公用事业", "4961": "公用事业",
    "6798": "房地产", "6552": "房地产", "6512": "房地产", "6531": "房地产",
    "6532": "房地产", "6500": "房地产", "6798b": "房地产",
}

# SIC 大区(division)兜底
SIC_DIV = [
    (100, 999, "材料"), (1000, 1499, "能源"), (1500, 1799, "工业"),
    (2000, 2199, "必需消费"), (2200, 2399, "可选消费"), (2400, 2799, "材料"),
    (2800, 2899, "材料"), (2900, 2999, "能源"), (3000, 3399, "材料"),
    (3400, 3599, "工业"), (3600, 3669, "信息技术"), (3670, 3699, "信息技术"),
    (3700, 3799, "可选消费"), (3800, 3899, "工业"), (3900, 3999, "可选消费"),
    (4000, 4799, "工业"), (4800, 4899, "通信服务"), (4900, 4999, "公用事业"),
    (5000, 5199, "必需消费"), (5200, 5999, "可选消费"), (6000, 6199, "金融"),
    (6200, 6299, "金融"), (6300, 6411, "金融"), (6500, 6599, "房地产"),
    (6700, 6799, "金融"), (7000, 7299, "可选消费"), (7300, 7369, "工业"),
    (7370, 7379, "信息技术"), (7380, 7399, "工业"), (7500, 7999, "可选消费"),
    (8000, 8099, "医疗保健"), (8100, 8999, "工业"), (9000, 9999, "其他"),
]


def sic_to_uni(sic):
    if sic in SIC_TO_UNI:
        return SIC_TO_UNI[sic], "精确码"
    try:
        c = int(sic)
    except (TypeError, ValueError):
        return "", ""
    for lo, hi, s in SIC_DIV:
        if lo <= c <= hi:
            return s, "大区兜底"
    return "", ""


ETF_LIKE = {"SPY", "QQQ", "DIA", "IWM", "MDY", "VTI", "CWB"}


# ============================================================ 组装
def build():
    import pandas as pd
    pool = tickers_of_pool()
    nas = fetch_nasdaq()
    gics = fetch_gics()
    gics["Symbol"] = gics.Symbol.astype(str).str.strip().str.upper()
    gmap = gics.set_index("Symbol").to_dict("index")
    cik_hint = {s: int(v["CIK"]) for s, v in gmap.items()
                if str(v.get("CIK", "")).strip().isdigit()}
    sec = fetch_sec(pool, cik_hint)

    rows = []
    for t in pool:
        n = nas.get(TICKER_ALIAS.get(t, t), nas.get(t, {}))
        g = gmap.get(t, {})
        s = sec.get(t, {})
        sic = s.get("sic", "") if s.get("found") else ""
        gs = (g.get("GICS Sector") or "").strip()
        rows.append(dict(
            ticker=t,
            name=n.get("name", "") or s.get("sec_name", ""),
            sec_name=s.get("sec_name", "") if s.get("found") else "",
            market_cap=n.get("market_cap", float("nan")),
            ipo_year=n.get("ipo_year", ""),
            country=n.get("country", ""),
            gics_sector=gs,
            gics_sub_industry=(g.get("GICS Sub-Industry") or "").strip(),
            gics_date_added=g.get("Date added", ""),
            nasdaq_sector=n.get("sector", ""),
            nasdaq_industry=n.get("industry", ""),
            sec_sic=sic,
            sec_sic_desc=s.get("sic_desc", "") if s.get("found") else "",
            sec_entity=s.get("entity_type", "") if s.get("found") else "",
            uni_gics=GICS_TO_UNI.get(gs, ""),
            uni_nasdaq=NASDAQ_TO_UNI.get(n.get("sector", ""), ""),
            uni_sec=sic_to_uni(sic)[0],
            sec_map_how=sic_to_uni(sic)[1],
            src_nasdaq=bool(n), src_gics=bool(g), src_sec=bool(s.get("found")),
        ))
    df = pd.DataFrame(rows)
    df["is_etf"] = df.ticker.isin(ETF_LIKE)
    # 统一口径优先级: GICS(行业标准) > Nasdaq > SEC
    df["uni_sector"] = (df.uni_gics.where(df.uni_gics != "")
                        .fillna(df.uni_nasdaq.where(df.uni_nasdaq != ""))
                        .fillna(df.uni_sec))
    df.loc[df.is_etf, "uni_sector"] = "指数ETF"
    df["uni_sector"] = df.uni_sector.fillna("未覆盖").replace("", "未覆盖")
    df["n_src"] = df[["src_nasdaq", "src_gics", "src_sec"]].sum(axis=1)

    cols = ["ticker", "name", "uni_sector", "gics_sector", "gics_sub_industry",
            "nasdaq_sector", "nasdaq_industry", "sec_sic", "sec_sic_desc",
            "sec_entity", "uni_gics", "uni_nasdaq", "uni_sec", "sec_map_how",
            "market_cap", "ipo_year", "country", "is_etf",
            "src_nasdaq", "src_gics", "src_sec", "n_src", "gics_date_added"]
    df = df[cols]
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"[✓] {len(df)} 行 -> {os.path.basename(OUT_CSV)}")
    return df


def main():
    df = build()
    out = print
    out("=" * 94)
    out("美股行业分类抓取结果 (三源: GICS 官方 + Nasdaq 官方 + SEC EDGAR SIC)")
    out("=" * 94)
    out(f"  池子 {len(df)} 只")
    out(f"  GICS   命中 {df.src_gics.sum():>4} 只  ({df.src_gics.mean():.1%})")
    out(f"  Nasdaq 命中 {df.src_nasdaq.sum():>4} 只  ({df.src_nasdaq.mean():.1%})")
    out(f"  SEC    命中 {df.src_sec.sum():>4} 只  ({df.src_sec.mean():.1%})")
    out(f"  三源齐全 {(df.n_src == 3).sum()} 只   两源以上 {(df.n_src >= 2).sum()} 只"
        f"   零源 {(df.n_src == 0).sum()} 只")
    no_gics = df[~df.src_gics].ticker.tolist()
    out(f"  非 S&P500 成分(无 GICS) {len(no_gics)} 只, 由 Nasdaq/SEC 兜底:")
    for i in range(0, len(no_gics), 12):
        out("      " + " ".join(f"{t:<6}" for t in no_gics[i:i + 12]))
    out()
    out("  统一 11 大类分布 (GICS 优先):")
    for k, v in df.uni_sector.value_counts().items():
        out(f"    {k:<10}{v:>4} 只  {v / len(df):>6.1%}")
    out()
    both = df[(df.uni_gics != "") & (df.uni_nasdaq != "")]
    out(f"  GICS vs Nasdaq 一致率: {float((both.uni_gics == both.uni_nasdaq).mean()):.1%}"
        f"  ({int((both.uni_gics == both.uni_nasdaq).sum())}/{len(both)})")
    diff = both[both.uni_gics != both.uni_nasdaq]
    if len(diff):
        out(f"  分歧 {len(diff)} 只 (Nasdaq 无 Communication Services, 把互联网/媒体归 Technology):")
        for _, r in diff.iterrows():
            out(f"    {r.ticker:<6} GICS={r.uni_gics:<6}({r.gics_sub_industry[:28]:<28}) "
                f"Nasdaq={r.uni_nasdaq:<6}({r.nasdaq_industry[:26]})")
    out()
    b3 = df[(df.uni_gics != "") & (df.uni_sec != "")]
    out(f"  GICS vs SEC-SIC 一致率: {float((b3.uni_gics == b3.uni_sec).mean()):.1%}"
        f"  ({int((b3.uni_gics == b3.uni_sec).sum())}/{len(b3)})")
    d3 = b3[b3.uni_gics != b3.uni_sec]
    if len(d3):
        out(f"  分歧 {len(d3)} 只:")
        for _, r in d3.iterrows():
            out(f"    {r.ticker:<6} GICS={r.uni_gics:<6} SEC={r.sec_sic} "
                f"{r.sec_sic_desc[:38]:<38} ->{r.uni_sec}({r.sec_map_how})")
    out()
    out("  SIC 映射方式统计:", df[df.sec_sic != ""].sec_map_how.value_counts().to_dict())


if __name__ == "__main__":
    main()
