# -*- coding: utf-8 -*-
"""
FRED 补充抓取: 波动率全家桶 + 全球股指 + 商品扩展 + 利率/信用/货币供应

⭐ 核心诉求: 用户要"组更多的波动率相关的池" ——
  波动率指数(VIX/VXN/OVX/GVZ/EVZ/VVIX)天然**均值回归、无长期单边赢家**,
  正好满足再平衡收割的第 3 个准入条件, 是理论上最理想的池子品种。

⚠️ 坑 (2026-09-09 实测): FRED 批量连拉会触发 404 限流
   → 必须**单条串行 + 随机间隔 2-4.5s**

用法: python fetch_fred_volatility_assets.py
"""
import os
import random
import time

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data")
RAW_DIR = os.path.join(OUT_DIR, "raw_fred")
os.makedirs(RAW_DIR, exist_ok=True)
PANEL = os.path.join(OUT_DIR, "fred_extended_monthly.csv")

BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"

# (series_id, 名称, 分类)
TARGETS = [
    # ============ 波动率全家桶 (核心) ============
    ("VIXCLS", "VIX标普波动率", "波动率"),
    ("VIXCLS", "VIX2", "波动率"),  # 重复占位, 会自动去重
    ("VXNCLS", "VXN纳指100波动率", "波动率"),
    ("VXDCLS", "VXD道指波动率", "波动率"),
    ("RVXCLS", "RVX罗素2000波动率", "波动率"),
    ("OVXCLS", "OVX原油波动率", "波动率"),
    ("GVZCLS", "GVZ黄金波动率", "波动率"),
    ("EVZCLS", "EVZ欧元波动率", "波动率"),
    ("VXVCLS", "VXV三月VIX", "波动率"),
    ("VVIX", "VVIX波动率的波动率", "波动率"),
    ("SRVIX", "短期VIX", "波动率"),
    ("BAMLH0A0HYM2", "高收益债利差", "信用"),
    ("BAMLC0A0CM", "投资级债利差", "信用"),
    ("TEDRATE", "TED利差", "信用"),
    ("STLFSI4", "圣路易斯金融压力", "信用"),
    # ============ 全球股指 (跨国池) ============
    ("SP500", "标普500", "股指"),
    ("NASDAQCOM", "纳斯达克综合", "股指"),
    ("DJIA", "道琼斯", "股指"),
    ("NIKKEI225", "日经225", "股指"),
    ("FTSE", "英国富时100? ", "股指"),
    ("DAX", "德国DAX? ", "股指"),
    ("WILL5000IND", "威尔希尔5000", "股指"),
    ("WILLLRGCAP", "威尔希尔大盘", "股指"),
    ("WILLSMLCAP", "威尔希尔小盘", "股指"),
    ("RUT", "罗素2000", "股指"),
    ("KS11", "韩国KOSPI? ", "股指"),
    # ============ 利率 / 收益率曲线 ============
    ("DGS1MO", "1月国债", "利率"),
    ("DGS3MO", "3月国债", "利率"),
    ("DGS6MO", "6月国债", "利率"),
    ("DGS1", "1年国债", "利率"),
    ("DGS5", "5年国债", "利率"),
    ("DGS7", "7年国债", "利率"),
    ("DGS20", "20年国债", "利率"),
    ("DGS30", "30年国债", "利率"),
    ("DFII5", "5年TIPS实际利率", "利率"),
    ("DFII10", "10年TIPS实际利率", "利率"),
    ("DFII30", "30年TIPS实际利率", "利率"),
    ("T5YIE", "5年通胀预期", "通胀"),
    ("T10YIE", "10年通胀预期", "通胀"),
    ("T5YIFR", "5年5年远期通胀", "通胀"),
    ("MORTGAGE30US", "30年房贷利率", "利率"),
    ("MORTGAGE15US", "15年房贷利率", "利率"),
    ("SOFR", "SOFR", "利率"),
    ("FEDFUNDS", "联邦基金利率", "利率"),
    ("DTB3", "3月国库券", "利率"),
    # ============ 货币供应 / 流动性 ============
    ("M1SL", "M1", "货币"),
    ("M2SL", "M2", "货币"),
    ("WALCL", "美联储总资产", "货币"),
    ("H41RESPPALDKNWW", "银行准备金", "货币"),
    ("RRPONTSYD", "逆回购", "货币"),
    ("WTREGEN", "财政部TGA", "货币"),
    # ============ 汇率 ============
    ("DEXCHUS", "人民币", "汇率"),
    ("DEXKOUS", "韩元", "汇率"),
    ("DEXINUS", "印度卢比", "汇率"),
    ("DEXBZUS", "巴西雷亚尔", "汇率"),
    ("DEXMXUS", "墨西哥比索", "汇率"),
    ("DEXSFUS", "南非兰特", "汇率"),
    ("DTWEXBGS", "美元名义广义指数", "汇率"),
    ("DTWEXAFEGS", "美元实际广义指数", "汇率"),
    ("DEXSZUS", "瑞士法郎", "汇率"),
    ("DEXCAUS", "加元", "汇率"),
    ("DEXAUS", "澳元", "汇率"),
    ("DEXNOUS", "挪威克朗", "汇率"),
    ("DEXSDUS", "瑞典克朗", "汇率"),
    ("DEXSLUS", "斯洛伐克? ", "汇率"),
    ("DEXTHUS", "泰铢", "汇率"),
    ("DEXMAUS", "马来西亚林吉特", "汇率"),
    ("DEXSIUS", "新加坡元", "汇率"),
    ("DEXHKUS", "港币", "汇率"),
    ("DEXTAUS", "台币", "汇率"),
    # ============ 商品扩展 ============
    ("PURANUSDM", "铀", "商品"),
    ("PIORECRUSDM", "铁矿石", "商品"),
    ("PSTEELUSDM", "钢材? ", "商品"),
    ("PWOODUSDM", "木材? ", "商品"),
    ("PRUBBUSDM", "橡胶", "商品"),
    ("PSUGAISAUSDM", "糖", "商品"),
    ("PCOFFOTMUSDM", "咖啡", "商品"),
    ("PCOCOUSDM", "可可", "商品"),
    ("PCOTTINDUSDM", "棉花", "商品"),
    ("PPOILUSDM", "棕榈油", "商品"),
    ("PSUNOUSDM", "葵花油", "商品"),
    ("PMAIZMTUSDM", "玉米", "商品"),
    ("PWHEAMTUSDM", "小麦", "商品"),
    ("PRICENPQUSDM", "大米", "商品"),
    ("PSOYBUSDM", "大豆", "商品"),
    ("POILBREUSDM", "布伦特", "商品"),
    ("PAPGOLDUSDM", "黄金? ", "商品"),
    ("PNRGINDEXM", "能源指数", "商品"),
    ("PMETAINDEXM", "金属指数", "商品"),
    ("PALLFNFINDEXM", "全部商品指数", "商品"),
    ("PAPRINDEXM", "农产品指数", "商品"),
    ("PNFUELINDEXM", "燃料指数", "商品"),
    ("PIORINDEXM", "矿石指数", "商品"),
    ("pbearbindexm", "饮料指数", "商品"),
    ("PRAWMINDEXM", "原材料指数", "商品"),
    ("PNGASEUUSDM", "欧洲天然气", "商品"),
    ("PNGASJPUSDM", "日本LNG", "商品"),
    ("PCOALAUUSDM", "澳洲煤", "商品"),
    ("PCOALSAUSDM", "南非煤", "商品"),
    ("DHHNGSP", "HenryHub现货", "商品"),
    # ============ 化肥 / 新能源金属 ============
    ("PIUREAUSDM", "尿素", "化肥"),
    ("PDAPUSDM", "磷酸二铵DAP", "化肥"),
    ("PPOTASHUSDM", "钾肥", "化肥"),
    ("PTSPHOSPHUSDM", "磷酸盐岩", "化肥"),
    # ============ 宏观 / 景气 ============
    ("UNRATE", "失业率", "宏观"),
    ("CPIAUCSL", "CPI", "宏观"),
    ("CPILFESL", "核心CPI", "宏观"),
    ("PCEPI", "PCE", "宏观"),
    ("PPIACO", "PPI", "宏观"),
    ("GDP", "GDP", "宏观"),
    ("INDPRO", "工业产出", "宏观"),
    ("RSAFS", "零售销售", "宏观"),
    ("UMCSENT", "密歇根信心", "宏观"),
    ("CSUSHPISA", "Case-Shiller房价", "房地产"),
    ("MSPUS", "新房中位价", "房地产"),
    ("HOUST", "新屋开工", "房地产"),
]


def load_panel():
    if os.path.exists(PANEL):
        return pd.read_csv(PANEL, index_col=0, parse_dates=True)
    return pd.DataFrame()


def main():
    panel = load_panel()
    have = set(panel.columns)
    seen = set()
    todo = []
    for sid, name, cat in TARGETS:
        if sid in seen or sid in have:
            continue
        seen.add(sid)
        todo.append((sid, name, cat))

    print(f"清单 {len(TARGETS)} (去重 {len(seen)}), 待抓 {len(todo)}")
    ok, fail = {}, []
    for i, (sid, name, cat) in enumerate(todo, 1):
        try:
            df = pd.read_csv(BASE.format(sid=sid))
            col = [c for c in df.columns if c not in ("observation_date", "DATE", "date")]
            if not col:
                raise RuntimeError("无数据列")
            v = df.columns[-1]
            s = pd.to_numeric(df[v], errors="coerce")
            s.index = pd.to_datetime(df.iloc[:, 0])
            s = s.dropna()
            s.name = sid
            if len(s) < 5:
                raise RuntimeError(f"仅 {len(s)} 点")
            ok[sid] = s
            s.to_csv(os.path.join(RAW_DIR, f"{sid}.csv"), header=["value"])
            print(f"{i:3d}/{len(todo)} {sid:20s} {name:16s} {len(s):6d}点 "
                  f"{s.index[0].date()}~{s.index[-1].date()} ({cat})", flush=True)
        except Exception as e:
            print(f"{i:3d}/{len(todo)} {sid:20s} {name:16s} ERR {str(e)[:50]}", flush=True)
            fail.append(sid)
        time.sleep(random.uniform(2.0, 4.5))

    if ok:
        panel = pd.concat([panel, pd.DataFrame(ok).sort_index()], axis=1, sort=True)
        panel = panel[~panel.index.duplicated(keep="last")].sort_index()
        panel.to_csv(PANEL)
        print(f"\n面板: {panel.shape[0]} 行 x {panel.shape[1]} 列 -> {PANEL}")
    print(f"成功 {len(ok)} / 失败 {len(fail)}")
    if fail:
        print("失败:", ", ".join(fail))


if __name__ == "__main__":
    main()
