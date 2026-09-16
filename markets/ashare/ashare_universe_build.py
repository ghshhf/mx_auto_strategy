# -*- coding: utf-8 -*-
"""
ashare_universe_build.py —— A 股行业龙头池: Yahoo 后复权日线下载 + 周线面板构建
================================================================================
为什么需要这个脚本
------------------
1) markets/ashare/data/ashare/bars/*.json (腾讯日线) 经实测 **未做完整复权**:
   51 只个股里 36 只存在共 146 次「单日跌幅 < -15%」(最低 -67%), 主板限跌 10%
   不可能出现 —— 全是除权/送股假暴跌。直接拿去跑再平衡会在除权日抄底, 结果全假。
2) data/weekly_yahoo_*.csv 只有 4 个文件 / 7 只蓝筹, 样本太小, 代表不了 A 股。
3) 本脚本改从 Yahoo chart API 拉 **日线 adjclose (后复权)**, 自行按周五重采样,
   保证与 crypto 面板完全同口径 (周末收盘 / 周五对齐)。

产出
----
  data/yahoo_daily/<code>.csv             逐标的日线 (date, close)
  data/ashare_weekly_panel.csv            周线宽表 (index=周五, columns=代码)
  data/ashare_universe.json               标的清单 (代码/名称/行业)
  data/ashare_adj_audit.csv              复权异常审计 (区分「市场级暴跌」与「个股级假摔」)

用法
----
  python ashare_universe_build.py            # 断点续传下载 + 构建面板
  python ashare_universe_build.py --audit    # 只跑复权审计, 不下载
"""
import os
import sys
import json
import time
import datetime
import urllib.request
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DAILY = os.path.join(DATA, "yahoo_daily")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

PROXY = os.environ.get("MX_PROXY", "http://127.0.0.1:3067")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# --------------------------------------------------------------- 标的池
# 各行业龙头 / 能叫得出名字的 A 股。 (代码, 名称, 行业)
UNIVERSE = [
    # 白酒 / 食品饮料
    ("600519", "贵州茅台", "白酒"), ("000858", "五粮液", "白酒"), ("000568", "泸州老窖", "白酒"),
    ("600809", "山西汾酒", "白酒"), ("002304", "洋河股份", "白酒"),
    ("600887", "伊利股份", "乳品"), ("603288", "海天味业", "调味品"), ("000895", "双汇发展", "肉制品"),
    ("600600", "青岛啤酒", "啤酒"),
    # 银行 / 保险 / 券商
    ("600036", "招商银行", "银行"), ("601398", "工商银行", "银行"), ("601166", "兴业银行", "银行"),
    ("002142", "宁波银行", "银行"), ("601318", "中国平安", "保险"), ("601601", "中国太保", "保险"),
    ("601628", "中国人寿", "保险"), ("600030", "中信证券", "券商"), ("300059", "东方财富", "券商"),
    # 医药
    ("600276", "恒瑞医药", "医药"), ("300760", "迈瑞医疗", "医药"), ("603259", "药明康德", "医药"),
    ("300015", "爱尔眼科", "医药"), ("600436", "片仔癀", "中药"), ("000538", "云南白药", "中药"),
    ("600085", "同仁堂", "中药"),
    # 家电
    ("000333", "美的集团", "家电"), ("000651", "格力电器", "家电"), ("600690", "海尔智家", "家电"),
    ("002032", "苏泊尔", "家电"),
    # 汽车
    ("002594", "比亚迪", "汽车"), ("601633", "长城汽车", "汽车"), ("600104", "上汽集团", "汽车"),
    ("000625", "长安汽车", "汽车"), ("601127", "赛力斯", "汽车"),
    # 新能源 / 光伏
    ("300750", "宁德时代", "电池"), ("601012", "隆基绿能", "光伏"), ("600438", "通威股份", "光伏"),
    ("300274", "阳光电源", "光伏"), ("002459", "晶澳科技", "光伏"), ("300014", "亿纬锂能", "电池"),
    # 电子 / 半导体 / 安防
    ("002475", "立讯精密", "电子"), ("000725", "京东方A", "电子"), ("601138", "工业富联", "电子"),
    ("002415", "海康威视", "安防"), ("002236", "大华股份", "安防"), ("603501", "韦尔股份", "半导体"),
    ("002371", "北方华创", "半导体"), ("688981", "中芯国际", "半导体"), ("603986", "兆易创新", "半导体"),
    # 软件 / 传媒
    ("002230", "科大讯飞", "软件"), ("600570", "恒生电子", "软件"), ("000977", "浪潮信息", "服务器"),
    ("002027", "分众传媒", "传媒"),
    # 资源 / 公用
    ("601899", "紫金矿业", "有色"), ("601088", "中国神华", "煤炭"), ("601225", "陕西煤业", "煤炭"),
    ("600900", "长江电力", "电力"), ("600309", "万华化学", "化工"), ("600585", "海螺水泥", "建材"),
    ("600019", "宝钢股份", "钢铁"), ("603993", "洛阳钼业", "有色"),
    # 机械 / 军工 / 交运
    ("600031", "三一重工", "机械"), ("300124", "汇川技术", "机械"), ("600760", "中航沈飞", "军工"),
    ("002352", "顺丰控股", "交运"), ("601816", "京沪高铁", "交运"), ("601888", "中国中免", "免税"),
    ("600009", "上海机场", "交运"),
    # 地产 / 建筑
    ("000002", "万科A", "地产"), ("601668", "中国建筑", "建筑"), ("600048", "保利发展", "地产"),
    # 农业 / 通信
    ("002714", "牧原股份", "养殖"), ("600941", "中国移动", "通信"), ("000063", "中兴通讯", "通信"),
]

NAMES = {c: n for c, n, _ in UNIVERSE}
INDUS = {c: i for c, _, i in UNIVERSE}
CODES = [c for c, _, _ in UNIVERSE]


def yahoo_symbol(code):
    """6 位 A 股代码 -> Yahoo 符号 (6xxxxx/688xxx -> .SS, 其余 -> .SZ)"""
    return code + (".SS" if code[0] == "6" else ".SZ")


def fetch_daily(code, tries=3, timeout=60):
    """拉 Yahoo 日线 adjclose -> [(date_iso, close), ...]"""
    sym = yahoo_symbol(code)
    p1 = int(datetime.datetime(2004, 1, 1, tzinfo=datetime.timezone.utc).timestamp())
    p2 = int(datetime.datetime.now(datetime.timezone.utc).timestamp() + 86400)
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={p1}&period2={p2}&interval=1d")
    req = urllib.request.Request(url, headers=UA)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(
        {"http": PROXY, "https": PROXY}))
    last = ""
    for _ in range(tries):
        try:
            r = opener.open(req, timeout=timeout)
            res = json.loads(r.read())["chart"]["result"][0]
            ts = res["timestamp"]
            cl = res["indicators"]["quote"][0]["close"]
            adjl = res["indicators"].get("adjclose")
            adj = (adjl[0]["adjclose"] if adjl else [None] * len(cl)) or [None] * len(cl)
            rows = []
            for t, c, a in zip(ts, cl, adj):
                v = a if a is not None else c
                if v is None:
                    continue
                d = datetime.datetime.fromtimestamp(t, datetime.UTC).date()
                rows.append((d.isoformat(), float(v)))
            return rows
        except Exception as e:          # noqa: BLE001
            last = str(e)
            time.sleep(1.2)
    print(f"    ✗ {code} {NAMES.get(code, '')} 失败: {last[:80]}")
    return None


def download(force=False):
    os.makedirs(DAILY, exist_ok=True)
    got, skip, fail = 0, 0, []
    for i, code in enumerate(CODES, 1):
        path = os.path.join(DAILY, code + ".csv")
        if os.path.exists(path) and not force:
            skip += 1
            continue
        rows = fetch_daily(code)
        if not rows or len(rows) < 60:
            fail.append(code)
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write("date,close\n")
            for d, v in rows:
                f.write(f"{d},{v:.6f}\n")
        got += 1
        print(f"    [{i:>3}/{len(CODES)}] {code} {NAMES.get(code,''):<6} {len(rows):>5} 日 "
              f"{rows[0][0]} ~ {rows[-1][0]}", flush=True)
        time.sleep(0.25)
    print(f"\n  下载 {got} / 跳过(已存在) {skip} / 失败 {len(fail)}")
    if fail:
        print("  失败代码: " + " ".join(fail))
    return fail


def pct_limit(code, d):
    """该标的在该日期的单日涨跌幅限制 (用于判定『不可能是真实交易』)"""
    if code.startswith("688"):
        return 0.22                      # 科创板 20%
    if code.startswith("300"):
        return 0.22 if d >= datetime.date(2020, 8, 24) else 0.11   # 创业板改 20%
    return 0.11                          # 主板 / 中小板 10%


def clean_series(code, s):
    """
    自建『后复权』清洗。Yahoo 对 A 股 adjclose 并不保证完整复权
    (实测: 亿纬锂能 2017-05-11 10转10 未调整, 单日 -51.3%)。
    两步:
      A) 剔除上市前填充段 —— 开头连续 >=5 个交易日收盘完全相同 (Yahoo 伪值), 整段删除;
      B) 除权修复 —— 日跌幅超过该标的涨跌停限制的日子只可能是除权/送转,
         把该日之前所有价格乘以 (P_t / P_{t-1}), 使序列在除权日收益为 0 (标准后复权)。
         同时把该日之前的『死拿建仓量』口径统一, 不影响价格倍数。
    返回 (清洗后 Series, 事件 list)
    """
    import pandas as pd
    import numpy as np
    v = s.values.astype(float)
    idx = s.index
    events = []

    # ---- A) 上市前填充段
    cut = 0
    run = 1
    for i in range(1, len(v)):
        if v[i] == v[i - 1]:
            run += 1
        else:
            break
    if run >= 5:                     # 开头就是一段不动价 -> 全部是填充
        # 找到恒定段结束后的第一个真实交易日
        j = run
        cut = j
        events.append(dict(code=code, name=NAMES.get(code, ""), kind="上市前填充",
                           date=str(idx[min(cut, len(idx) - 1)].date()),
                           detail=f"开头 {run} 个交易日收盘恒为 {v[0]:.4f}"))
    if cut >= len(v) - 30:
        cut = 0
    v = v[cut:]
    idx = idx[cut:]

    # ---- B) 除权修复 (从后往前累乘, 保证 ratio 基于原始相邻价比)
    raw = v.copy()
    A = np.ones(len(raw))
    for t in range(1, len(raw)):
        if raw[t - 1] <= 0:
            continue
        r = raw[t] / raw[t - 1] - 1.0
        lim = pct_limit(code, idx[t].date())
        if r < -lim or r > lim:
            ratio = raw[t] / raw[t - 1]
            A[:t] *= ratio
            events.append(dict(code=code, name=NAMES.get(code, ""),
                               kind="除权/送转修复" if r < 0 else "反向调整",
                               date=str(idx[t].date()),
                               detail=f"前一日 {raw[t-1]:.4f} -> 当日 {raw[t]:.4f} "
                                      f"({r * 100:+.1f}%), 因子 {ratio:.6f}"))
    v_adj = raw * A

    # 停牌段 (中间连续 >=5 日收盘不动) 只记录, 不调整 —— 这是真实的 A 股停牌
    run, start = 1, 0
    for i in range(1, len(raw)):
        if raw[i] == raw[i - 1]:
            run += 1
        else:
            if run >= 8:
                events.append(dict(code=code, name=NAMES.get(code, ""), kind="停牌段(真实)",
                                   date=str(idx[start].date()),
                                   detail=f"{run} 个交易日收盘不动"))
            run, start = 1, i
    return pd.Series(v_adj, index=idx, name=s.name), events


def build_panel():
    import pandas as pd
    series, allev = {}, []
    for code in CODES:
        path = os.path.join(DAILY, code + ".csv")
        if not os.path.exists(path):
            continue
        s = pd.read_csv(path, index_col=0, encoding="utf-8-sig")
        s.index = pd.to_datetime(s.index)
        s = s[~s.index.duplicated()].sort_index()
        s, ev = clean_series(code, s["close"])
        allev += ev
        # 与 crypto 面板同口径: 按周五重采样, 取该周最后一个交易日收盘
        w = s.resample("W-FRI").last().dropna()
        series[NAMES.get(code, code) + "|" + code] = w
    if not series:
        return None, None
    px = pd.DataFrame(series)
    px.index.name = "date"
    px = px.sort_index()
    # 剔除未走完的当周 (W-FRI 会把本周标成未来的周五)
    if len(px) and px.index[-1].date() > datetime.date.today():
        px = px.iloc[:-1]
    # Yahoo 版只作交叉校验 (它有系统性缺日, 不作主数据源)
    out = os.path.join(DATA, "ashare_weekly_panel_yahoo.csv")
    px.to_csv(out, encoding="utf-8-sig")
    ev_df = pd.DataFrame(allev)
    if len(ev_df):
        ev_df.to_csv(os.path.join(DATA, "ashare_exright_events.csv"),
                     index=False, encoding="utf-8-sig")
    with open(os.path.join(DATA, "ashare_universe.json"), "w", encoding="utf-8") as f:
        json.dump([dict(code=c, name=NAMES[c], ind=INDUS[c]) for c in CODES],
                  f, ensure_ascii=False, indent=1)
    return px, ev_df


def audit(px):
    """复权审计: 清洗后再扫一遍, 区分『市场级暴跌』(真实, 同周多数股票一起跌)
    与『个股级假摔』(残余未复权)。清洗后若仍有个股级事件, 说明不是除权而是停牌复牌等真实事件。"""
    import pandas as pd
    import numpy as np
    r = px.pct_change()
    THR = -0.30
    hits = []
    for col in r.columns:
        s = r[col]
        for d, v in s[s < THR].items():
            row = r.loc[d]
            mkt = float((row < -0.12).sum()) / max(int(row.notna().sum()), 1)
            hits.append(dict(date=d.date(), code=str(col).split("|")[-1],
                             name=str(col).split("|")[0], ret=float(v),
                             mkt_share=mkt))
    df = pd.DataFrame(hits)
    if len(df):
        df["verdict"] = np.where(df.mkt_share >= 0.30, "市场级暴跌(真实)",
                                 "个股级(停牌复牌/事件)")
        df = df.sort_values(["verdict", "ret"])
        df.to_csv(os.path.join(DATA, "ashare_adj_audit.csv"), index=False,
                  encoding="utf-8-sig")
    return df


def dividend_check(px):
    """检查 Yahoo 是否做了分红复权: 统计 2%~11% 的单日跌幅 (除息典型幅度)
    并按月份聚集度判断。若高股息股在 6~7 月反复出现 -2%~-6% 跳空, 说明分红未复权。"""
    import pandas as pd
    r = px.pct_change()
    rows = []
    for col in r.columns:
        s = r[col].dropna()
        gap = s[(s < -0.02) & (s > -0.12)]
        if not len(gap):
            continue
        mon = pd.Series(gap.index.month).value_counts()
        rows.append(dict(name=str(col).split("|")[0], n=len(gap),
                         top_months=",".join(str(m) for m in mon.index[:3]),
                         med=float(gap.median()), worst=float(gap.min())))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="强制重新下载")
    ap.add_argument("--audit", action="store_true", help="只跑审计")
    a = ap.parse_args()

    print("=" * 96)
    print("ashare_universe_build.py — A 股行业龙头池 (Yahoo 后复权)")
    print("=" * 96)
    print(f"  标的池: {len(CODES)} 只, 覆盖 {len(set(INDUS.values()))} 个行业")
    print(f"  代理: {PROXY}")
    if not a.audit:
        print("\n[1/3] 下载日线 (断点续传)")
        download(force=a.force)
    print("\n[2/3] 构建周线面板 (自建除权修复)")
    px, ev = build_panel()
    if px is None:
        print("  无数据")
        return
    print(f"  面板 {px.shape[0]} 周 × {px.shape[1]} 只, "
          f"{px.index[0].date()} ~ {px.index[-1].date()}")
    if ev is not None and len(ev):
        k = ev.kind.value_counts()
        for kk, n in k.items():
            print(f"  清洗事件 · {kk}: {n} 次")
        ex = ev[ev.kind == "除权/送转修复"]
        if len(ex):
            print("  除权修复明细:")
            for _, rr in ex.iterrows():
                print(f"    {rr['date']} {rr['code']} {rr['name']:<6} {rr['detail']}")

    print("\n[3/4] 复权审计 (清洗后残余)")
    df = audit(px)
    if len(df) == 0:
        print("  ✓ 无单周跌幅 < -30% 的记录")
    else:
        for kk, n in df.verdict.value_counts().items():
            print(f"  {kk}: {n} 次")
        for _, rr in df.head(8).iterrows():
            print(f"    {rr['date']} {rr['code']} {rr['name']:<6} "
                  f"{rr['ret'] * 100:>7.1f}%  同周下跌占比 {rr['mkt_share'] * 100:.0f}%")

    print("\n[4/4] 分红复权抽查 (2%~11% 跳空的月份聚集度)")
    dc = dividend_check(px)
    if len(dc):
        print(f"  {'名称':<8}{'跳空数':>7}{'中位幅度':>10}{'最深':>9}  高发月")
        for _, rr in dc.sort_values("n", ascending=False).head(8).iterrows():
            print(f"  {rr['name']:<8}{rr['n']:>7}{rr['med'] * 100:>9.2f}%"
                  f"{rr['worst'] * 100:>8.2f}%  {rr['top_months']}")
    print("\n完成。")


if __name__ == "__main__":
    main()
