# -*- coding: utf-8 -*-
"""
多源统一整合: 把 5 条通道的数据合并成一张**月度总面板**

源:
  1. World Bank Pink Sheet  —— 71 商品, 1960 起 (贵金属靠它补)
  2. FRED 商品              —— 41 序列, 1992 起
  3. FRED 全球资产          —— 利率/汇率/股指/VIX/通胀/房价/信用
  4. FRED 扩展              —— 波动率全家桶 + 全球股指 + 商品扩展 (fetch_fred_volatility_assets)
  5. EIA                    —— 气体/石油/电力/库存 (fetch_eia_gas / fetch_eia_full)
  6. Twelve Data 美股宇宙    —— 478 龙头股/ADR/ETF, 1980 起
  7. 腾讯行情 港股龙头      —— 91 港股, 1990 起
  8. 腾讯行情 个股          —— 腾讯/中海油/紫金/AMD
  9. 加密                   —— weekly_adjclose_crypto50 (周→月)

输出: data/all_assets_monthly.csv  (列 = 标的, 行 = 月末)
"""
import os
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
CRYPTO = os.path.join(os.path.dirname(HERE), "crypto", "data")

SOURCES = [
    # (文件, 频率, 源标签, 是否已是月度)
    ("commodity_worldbank_monthly.csv", "M", "WorldBank", True),
    ("commodity_fred_monthly.csv", "M", "FRED商品", True),
    ("global_assets_monthly.csv", "M", "FRED全球资产", True),
    ("fred_extended_monthly.csv", "M", "FRED扩展", True),
    ("eia_gas_monthly.csv", "M", "EIA", True),
    ("gas_panel_monthly.csv", "M", "EIA气体", True),
    ("us_universe_weekly_adjclose.csv", "W", "TwelveData", False),
    ("equities_weekly_adjclose.csv", "W", "腾讯个股", False),
    ("hk_leaders_weekly_adjclose.csv", "W", "腾讯港股", False),
]


def to_monthly(df):
    return df.resample("ME").last()


def main():
    panels = {}
    for fn, freq, tag, is_monthly in SOURCES:
        p = os.path.join(OUT, fn)
        if not os.path.exists(p):
            print(f"[跳过] {fn} 不存在")
            continue
        d = pd.read_csv(p, index_col=0, parse_dates=True)
        d = d[~d.index.duplicated(keep="last")].sort_index()
        d = d.apply(pd.to_numeric, errors="coerce")
        # 丢弃全空列 / 非正价格
        d = d.dropna(axis=1, how="all")
        m = d if is_monthly else to_monthly(d)
        panels[tag] = m
        print(f"[{tag:12s}] {fn:38s} {m.shape[1]:4d} 列  "
              f"{m.dropna(how='all').index[0].date()}~{m.dropna(how='all').index[-1].date()}")

    # 加密
    for fn in ["weekly_adjclose_crypto50.csv", "weekly_adjclose_crypto3.csv"]:
        p = os.path.join(CRYPTO, fn)
        if os.path.exists(p):
            d = pd.read_csv(p, index_col=0, parse_dates=True)
            d = d[~d.index.duplicated(keep="last")].sort_index()
            d = d.apply(pd.to_numeric, errors="coerce").dropna(axis=1, how="all")
            m = to_monthly(d)
            key = "加密50" if "50" in fn else "加密3"
            if key == "加密50" or "加密50" not in panels:
                panels[key] = m
                print(f"[{key:12s}] {fn:38s} {m.shape[1]:4d} 列  "
                      f"{m.dropna(how='all').index[0].date()}~{m.dropna(how='all').index[-1].date()}")

    # 合并 (列名冲突加后缀)
    allcols = {}
    for tag, m in panels.items():
        for c in m.columns:
            name = str(c)
            if name in allcols:
                name = f"{name}__{tag}"
            allcols[name] = m[c]
    panel = pd.DataFrame(allcols).sort_index()
    panel = panel[~panel.index.duplicated(keep="last")]

    # 清洗: 剔除有效样本 < 36 个月的列
    valid = panel.notna().sum()
    keep = valid[valid >= 36].index
    dropped = len(panel.columns) - len(keep)
    panel = panel[keep]

    out = os.path.join(OUT, "all_assets_monthly.csv")
    panel.to_csv(out)
    print(f"\n=== 统一面板 ===\n{out}")
    print(f"{panel.shape[0]} 行 x {panel.shape[1]} 列  "
          f"({panel.dropna(how='all').index[0].date()} ~ {panel.dropna(how='all').index[-1].date()})")
    print(f"剔除样本不足36月: {dropped} 列")

    # 各列起始年份分布
    starts = {c: panel[c].dropna().index[0].year for c in panel.columns}
    ys = pd.Series(list(starts.values()))
    print("\n起始年份分布:")
    for y, n in ys.value_counts().sort_index().head(12).items():
        print(f"  {y}: {n} 列")
    print("覆盖最长的 15 列:")
    for c in panel.columns:
        pass
    lens = panel.notna().sum().sort_values(ascending=False)
    for c, n in lens.head(15).items():
        col = panel[c].dropna()
        print(f"  {c:26s} {n:5d}月  {col.index[0].date()} ~ {col.index[-1].date()}")


if __name__ == "__main__":
    main()
