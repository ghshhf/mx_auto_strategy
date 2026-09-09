# -*- coding: utf-8 -*-
"""
Twelve Data 美股 / ETF 宇宙批量抓取 (免费档唯一开放的市场)

🔑 关键发现 (2026-09-09 实测):
  - Twelve Data 免费档 **只覆盖美股**; 港股/日股直接标的需 Grow 付费计划
    (港股 0700 返回 "available starting with the Grow or Venture plan")
  - 但美股历史极深: AMD 可到 **1980-03-17**, 2404 周 —— 比腾讯行情接口(2007起)多 27 年
  - 免费额度 800 credits/天, time_series = 1 credit/symbol → 一天可拉 800 个标的
  - 限流 8 credits/分钟 → 单条串行 + ~7.6s 间隔

日股/港股敞口用美股上市的国家 ETF 代理:
  EWJ(日本) EWH(香港) FXI/MCHI/KWEB(中国) —— 且这类 ETF 已有代币化版本
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data")
RAW_DIR = os.path.join(OUT_DIR, "raw_twelvedata")
os.makedirs(RAW_DIR, exist_ok=True)

KEY = json.load(open(os.path.join(HERE, "keys.local.json")))["twelvedata"]["key"]

# (symbol, tag, 名称, 分类)
TARGETS = [
    # 用户点名
    ("AMD", "AMD", "超威半导体", "个股"),
    # 国家/地区 ETF (日股腿 + 全球)
    ("EWJ", "EWJ", "日本 MSCI", "国家"),
    ("DXJ", "DXJ", "日本对冲", "国家"),
    ("EWH", "EWH", "香港", "国家"),
    ("FXI", "FXI", "中国大盘", "国家"),
    ("MCHI", "MCHI", "中国 MSCI", "国家"),
    ("KWEB", "KWEB", "中国互联网", "国家"),
    ("EWG", "EWG", "德国", "国家"),
    ("EWU", "EWU", "英国", "国家"),
    ("EWZ", "EWZ", "巴西", "国家"),
    ("INDA", "INDA", "印度", "国家"),
    ("EEM", "EEM", "新兴市场", "国家"),
    ("EFA", "EFA", "发达市场", "国家"),
    # 商品 ETF
    ("GLD", "GLD", "黄金", "商品"),
    ("IAU", "IAU", "黄金(小)", "商品"),
    ("SLV", "SLV", "白银", "商品"),
    ("PPLT", "PPLT", "铂金", "商品"),
    ("PALL", "PALL", "钯金", "商品"),
    ("DBC", "DBC", "商品综合", "商品"),
    ("GSG", "GSG", "商品综合2", "商品"),
    ("USO", "USO", "原油", "商品"),
    ("UNG", "UNG", "天然气", "商品"),
    ("DBA", "DBA", "农产品", "商品"),
    ("CORN", "CORN", "玉米", "商品"),
    ("WEAT", "WEAT", "小麦", "商品"),
    ("SOYB", "SOYB", "大豆", "商品"),
    ("DBB", "DBB", "基础金属", "商品"),
    ("CPER", "CPER", "铜", "商品"),
    # 债券
    ("TLT", "TLT", "20年国债", "债券"),
    ("IEF", "IEF", "7-10年国债", "债券"),
    ("SHY", "SHY", "1-3年国债", "债券"),
    ("LQD", "LQD", "投资级公司债", "债券"),
    ("HYG", "HYG", "高收益债", "债券"),
    ("TIP", "TIP", "通胀保值", "债券"),
    ("EMB", "EMB", "新兴市场债", "债券"),
    ("BND", "BND", "总债券市场", "债券"),
    # 宽基 / 行业
    ("SPY", "SPY", "标普500", "宽基"),
    ("QQQ", "QQQ", "纳指100", "宽基"),
    ("IWM", "IWM", "罗素2000", "宽基"),
    ("DIA", "DIA", "道指", "宽基"),
    ("VTI", "VTI", "全美股", "宽基"),
    ("VNQ", "VNQ", "地产", "行业"),
    ("XLF", "XLF", "金融", "行业"),
    ("XLE", "XLE", "能源", "行业"),
    ("XLK", "XLK", "科技", "行业"),
    ("XLV", "XLV", "医疗", "行业"),
    ("XLI", "XLI", "工业", "行业"),
    ("XLP", "XLP", "必需消费", "行业"),
    ("XLY", "XLY", "可选消费", "行业"),
    ("XLU", "XLU", "公用事业", "行业"),
    ("XLB", "XLB", "材料", "行业"),
    ("XLC", "XLC", "通信", "行业"),
    ("XLRE", "XLRE", "房地产", "行业"),
    # 加密相关
    ("IBIT", "IBIT", "比特币ETF", "加密"),
    ("FBTC", "FBTC", "比特币ETF2", "加密"),
    ("ETHA", "ETHA", "以太坊ETF", "加密"),
]

SLEEP = 7.6  # 8 credits/分钟


def fetch(symbol, interval="1week", outputsize=5000):
    params = {"symbol": symbol, "interval": interval, "outputsize": outputsize,
              "apikey": KEY, "order": "ASC"}
    url = "https://api.twelvedata.com/time_series?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=45) as r:
        d = json.load(r)
    if "values" not in d:
        raise RuntimeError(str(d)[:150])
    return d


def main():
    ok, fail = {}, []
    for i, (sym, tag, name, cat) in enumerate(TARGETS, 1):
        try:
            d = fetch(sym)
            df = pd.DataFrame(d["values"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            s = pd.Series(df["close"].values, index=pd.to_datetime(df["datetime"]), name=tag)
            s = s[~s.index.duplicated(keep="last")].sort_index()
            ok[tag] = s
            s.to_csv(os.path.join(RAW_DIR, f"{tag}.csv"), header=["close"])
            print(f"{i:3d}/{len(TARGETS)} {tag:6s} {name:12s} {len(s):5d}周 "
                  f"{s.index[0].date()}~{s.index[-1].date()} ({cat})")
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "ignore")[:80]
            print(f"{i:3d}/{len(TARGETS)} {tag:6s} {name:12s} HTTP {e.code}: {msg}")
            fail.append((tag, e.code))
        except Exception as e:
            print(f"{i:3d}/{len(TARGETS)} {tag:6s} {name:12s} ERR {str(e)[:70]}")
            fail.append((tag, str(e)[:40]))
        time.sleep(SLEEP)

    out = os.path.join(OUT_DIR, "us_etf_weekly_adjclose.csv")
    panel = pd.DataFrame(ok).sort_index()
    panel.to_csv(out)
    print(f"\n面板: {out}  {panel.shape[0]} 行 x {panel.shape[1]} 列")
    print(f"成功 {len(ok)} / 失败 {len(fail)}")
    if fail:
        print("失败:", ", ".join(f"{t}({r})" for t, r in fail[:20]))
    print("\n历史最长的 10 个:")
    for c in panel.columns:
        pass
    lens = panel.notna().sum().sort_values(ascending=False).head(10)
    for c, n in lens.items():
        col = panel[c].dropna()
        print(f"  {c:6s} {n:5d} 周  {col.index[0].date()} ~ {col.index[-1].date()}")


if __name__ == "__main__":
    main()
