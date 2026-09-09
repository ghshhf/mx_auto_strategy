"""解析 World Bank Pink Sheet(大宗商品月度价, 1960 起) → 本地数据资产。

产出:
  1. raw_worldbank/pink_monthly_long.csv   长表(date, code, name, unit, group, value) —— 最大信息量
  2. commodity_worldbank_monthly.csv       宽表(date × 商品) —— 供回测消费
  3. commodity_worldbank_coverage.csv      覆盖报告(每品种起止/点数/缺失率)

设计: 商品名 → 中文名 + 分组 + 短代码, 便于与其它源(FRED/akshare)对齐合并。
"""
import os
import re

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "data", "raw_worldbank", "CMO_Historical_Data_Monthly.xlsx")

# 英文原名 → (短代码, 中文名, 分组)
MAP = {
    "Crude oil, average": ("OIL_AVG", "原油_均价", "energy"),
    "Crude oil, Brent": ("OIL_BRENT", "原油_布伦特", "energy"),
    "Crude oil, Dubai": ("OIL_DUBAI", "原油_迪拜", "energy"),
    "Crude oil, WTI": ("OIL_WTI", "原油_WTI", "energy"),
    "Coal, Australian": ("COAL_AUS", "煤炭_澳洲", "energy"),
    "Coal, South African **": ("COAL_ZAF", "煤炭_南非", "energy"),
    "Natural gas, US": ("NG_US", "天然气_美国", "energy"),
    "Natural gas, Europe": ("NG_EU", "天然气_欧洲", "energy"),
    "Liquefied natural gas, Japan": ("LNG_JP", "液化天然气_日本", "energy"),
    "Natural gas index": ("NG_INDEX", "天然气指数", "energy"),
    # 贵金属
    "Gold": ("XAU", "黄金", "precious"),
    "Silver": ("XAG", "白银", "precious"),
    "Platinum": ("XPT", "铂金", "precious"),
    # 工业金属
    "Copper": ("CU", "铜", "industrial"),
    "Aluminum": ("AL", "铝", "industrial"),
    "Zinc": ("ZN", "锌", "industrial"),
    "Nickel": ("NI", "镍", "industrial"),
    "Tin": ("SN", "锡", "industrial"),
    "Lead": ("PB", "铅", "industrial"),
    "Iron ore, cfr spot": ("FE_ORE", "铁矿石", "industrial"),
    # 化肥
    "Phosphate rock": ("PHOS_ROCK", "磷矿石", "fertilizer"),
    "DAP": ("DAP", "磷酸二铵", "fertilizer"),
    "TSP": ("TSP", "过磷酸钙", "fertilizer"),
    "Urea": ("UREA", "尿素", "fertilizer"),
    "Potassium chloride **": ("KCL", "氯化钾", "fertilizer"),
    # 木材/橡胶
    "Logs, Cameroon": ("LOG_CMR", "原木_喀麦隆", "timber"),
    "Logs, Malaysian": ("LOG_MYS", "原木_马来西亚", "timber"),
    "Sawnwood, Cameroon": ("SAWN_CMR", "锯材_喀麦隆", "timber"),
    "Sawnwood, Malaysian": ("SAWN_MYS", "锯材_马来西亚", "timber"),
    "Plywood": ("PLYWOOD", "胶合板", "timber"),
    "Rubber, TSR20 **": ("RUB_TSR20", "橡胶_TSR20", "timber"),
    "Rubber, RSS3": ("RUB_RSS3", "橡胶_RSS3", "timber"),
}


def default_code(name):
    code = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    return code[:14]


def group_of(name):
    if "oil," in name.lower() or "coal" in name.lower() or "gas" in name.lower():
        return "energy"
    if name.lower().startswith(("gold", "silver", "platinum", "palladium")):
        return "precious"
    return "agri"


def parse_month(s):
    m = re.match(r"^(\d{4})M(\d{1,2})$", str(s).strip())
    if not m:
        return pd.NaT
    return pd.Timestamp(int(m.group(1)), int(m.group(2)), 1)


def main():
    d = pd.read_excel(SRC, sheet_name="Monthly Prices", header=None)
    names = d.iloc[4, 1:].tolist()
    units = d.iloc[5, 1:].tolist()
    body = d.iloc[6:].copy()
    body.columns = ["period"] + list(range(len(names)))
    body["date"] = body["period"].map(parse_month)
    body = body.dropna(subset=["date"]).set_index("date")
    body = body.drop(columns=["period"])

    long_rows, wide, cov = {}, {}, []
    for i, (nm, un) in enumerate(zip(names, units)):
        s = pd.to_numeric(body[i], errors="coerce")
        s.index.name = "date"
        s = s.dropna()
        if s.empty:
            continue
        code, cn, grp = MAP.get(nm, (default_code(nm), nm, group_of(nm)))
        if nm in MAP:
            cn, grp = MAP[nm][1], MAP[nm][2]
        wide[code] = s
        cov.append({"code": code, "cn": cn, "en": nm, "unit": str(un).strip("()"),
                    "group": grp, "n": int(len(s)),
                    "start": str(s.index[0].date()), "end": str(s.index[-1].date()),
                    "first": float(s.iloc[0]), "last": float(s.iloc[-1])})
        long_rows[code] = pd.DataFrame({"date": s.index, "code": code, "name": cn,
                                        "en": nm, "unit": str(un).strip("()"),
                                        "group": grp, "value": s.values})

    lg = pd.concat(long_rows.values(), ignore_index=True).sort_values(["date", "code"])
    wd = pd.DataFrame(wide).sort_index()

    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    lg.to_csv(os.path.join(HERE, "data", "raw_worldbank", "pink_monthly_long.csv"),
              index=False, encoding="utf-8-sig")
    wd.to_csv(os.path.join(HERE, "data", "commodity_worldbank_monthly.csv"), encoding="utf-8-sig")
    cdf = pd.DataFrame(cov).sort_values(["group", "code"])
    cdf.to_csv(os.path.join(HERE, "data", "commodity_worldbank_coverage.csv"),
               index=False, encoding="utf-8-sig")

    print(f"长表 {lg.shape}  宽表 {wd.shape}  品种 {len(cov)}")
    print(f"时间范围: {wd.index[0].date()} ~ {wd.index[-1].date()}")
    print("\n按组:")
    print(cdf.groupby("group").agg(品种数=("code", "count"), 最早=("start", "min"),
                                   最晚=("end", "max"), 中位点数=("n", "median")).to_string())
    print("\n金属与贵金属明细:")
    print(cdf[cdf.group.isin(["precious", "industrial", "fertilizer"])]
          [["code", "cn", "unit", "n", "start", "end", "last"]].to_string(index=False))


if __name__ == "__main__":
    main()
