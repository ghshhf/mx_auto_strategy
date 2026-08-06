# -*- coding: utf-8 -*-
"""
valuation_fetch.py - 抓取全 A 股市场估值(PE/PB)历史, 落盘为 data/valuation_daily.csv

数据源: akshare 乐咕乐股接口
  stock_a_ttm_lyr()  -> 全 A 股滚动市盈率(中位数/等权平均), 2005-01 起
  stock_a_all_pb()   -> 全 A 股市净率(中位数/等权平均), 2005-01 起

★ 为什么不用接口自带的 quantile 列:
  akshare 返回的 quantileInAllHistory* 是用**整段历史(含未来)**算出来的分位,
  直接拿来回测等于告诉 2015 年的策略"你现在处于 2005-2026 全历史的 90 分位"。
  这是前视偏差。本脚本只落盘原始 PE/PB 绝对值, 分位由引擎用
  **扩展窗口(expanding)** 在每个时点现算 —— 第 t 周的分位只统计 [0, t] 的历史。

★ 发布滞后: 市场估值由当日收盘价与最新财报计算, 当日盘后即可得。
  引擎侧统一取「上一周」的值(滞后 1 周)再使用, 保证决策时该数据确已公开。

用法: python valuation_fetch.py
"""
import os
import csv

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.setdefault(_k, "http://127.0.0.1:3067")

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "valuation_daily.csv")


def fetch():
    import akshare as ak
    pe = ak.stock_a_ttm_lyr()
    pb = ak.stock_a_all_pb()

    def _key(df, col):
        m = {}
        for _, r in df.iterrows():
            d = str(r["date"])[:10]
            try:
                v = float(r[col])
            except (TypeError, ValueError):
                continue
            if v > 0:
                m[d] = v
        return m

    pe_m = _key(pe, "middlePETTM")
    pb_m = _key(pb, "middlePB")
    dates = sorted(set(pe_m) | set(pb_m))
    rows = [{"date": d, "pe_ttm_median": pe_m.get(d, ""), "pb_median": pb_m.get(d, "")}
            for d in dates]
    return rows


def main():
    rows = fetch()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "pe_ttm_median", "pb_median"])
        w.writeheader()
        w.writerows(rows)
    print(f"[valuation_fetch] {len(rows)} rows -> {OUT}")
    if rows:
        print(f"  range: {rows[0]['date']} ~ {rows[-1]['date']}")
        print(f"  last : PE={rows[-1]['pe_ttm_median']} PB={rows[-1]['pb_median']}")


if __name__ == "__main__":
    main()
