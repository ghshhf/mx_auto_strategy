#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉取美股 30 年周线后复权收盘 (1996-01 ~ 至今) —— us30 DCA 基准数据
====================================================================
标的池 (2026-09-07 用户选定: "几大指数 + 行业指数 + 龙头(苹果英伟达这种)"):
  指数腿: SPY(标普500) / QQQ(纳指100) / DIA(道指)
  行业腿: XLE(能源) / XLP(必需消费) / XLV(医疗) / XLU(公用事业)
  龙头腿: AAPL / NVDA / MSFT
数据源: yfinance 周线 auto_adjust(后复权, 含分红再投等价)。
  QQQ 1999-03 上市 / NVDA 1999-01 / 行业ETF 1998-12 / DIA 1998-01 前的区间
  由回测引擎按"未上市标的权重分给已上市标的"处理(动态可用集), 无需在此填坑。
输出: us/data/weekly_adjclose_us30.csv  (Date,SPY,QQQ,DIA,XLE,XLP,XLV,XLU,AAPL,NVDA,MSFT)
用法: python fetch_us30_weekly.py
"""
import os
import sys
import time
import datetime

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))   # markets/ -> net_config

# yfinance 走代理
try:
    from net_config import proxy_url
    _px = proxy_url()
    os.environ["HTTP_PROXY"] = _px
    os.environ["HTTPS_PROXY"] = _px
except Exception:
    pass

import yfinance as yf

TICKERS = ["SPY", "QQQ", "DIA", "XLE", "XLP", "XLV", "XLU",
           "AAPL", "NVDA", "MSFT"]
OUT = os.path.join(HERE, "data", "weekly_adjclose_us30.csv")
START = "1996-01-01"
END = datetime.date.today().isoformat()


def fetch_one(tk):
    for attempt in range(3):
        try:
            df = yf.download(tk, start=START, end=END, interval="1wk",
                             auto_adjust=True, progress=False, threads=False,
                             timeout=30)
            if df is None or df.empty:
                raise RuntimeError("empty")
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            s = df["Close"].dropna()
            return s
        except Exception as e:
            print(f"  {tk} attempt{attempt+1} fail: {str(e)[:100]}")
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"{tk} failed after 3 attempts")


def main():
    data = {}
    print(f"拉取 {len(TICKERS)} 只, {START} -> {END} (周线, 后复权)")
    for i, tk in enumerate(TICKERS):
        s = fetch_one(tk)
        data[tk] = s
        print(f"  [{i+1}/{len(TICKERS)}] {tk}: {s.index[0].date()} ~ {s.index[-1].date()}  {len(s)} 周")
        time.sleep(0.8)
    px = pd.DataFrame(data).sort_index()
    px.index.name = "Date"
    px.to_csv(OUT, float_format="%.4f")
    print(f"\n输出: {OUT}  shape={px.shape}  "
          f"{px.index[0].date()} ~ {px.index[-1].date()}")


if __name__ == "__main__":
    main()
