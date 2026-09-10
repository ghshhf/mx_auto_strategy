# -*- coding: utf-8 -*-
"""
refresh_weekly_yahoo.py —— A 股周线面板补新 (weekly_yahoo_*.csv)
================================================================
背景: data/weekly_yahoo_*.csv 是 archive 轮动回测的输入面板, 由
archive/ashare_rotation_*.py 首次生成; 本脚本负责增量补齐到最新周。

机制: 读文件名 -> Yahoo 符号映射(6 位代码自动判 SH/SZ) -> chart API 拉全历史
      日线(后复权优先) -> 按周重采样(周五标记, 取每周最后收盘) -> 与旧面板合并
      (同日期取新值, 旧历史不动) -> 落盘。
用法: python refresh_weekly_yahoo.py          # 面板名 -> csv 路径映射内置
"""
import os, json, datetime, urllib.request

PROXY = "http://127.0.0.1:3067"
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
UA = {"User-Agent": "Mozilla/5.0"}

# 文件名前缀 -> (中文名, yahoo 符号)  (与 archive 脚本一致)
PANELS = {
    "002236_601318_10y": [("大华股份", "002236.SZ"), ("中国平安", "601318.SS")],
    "002415_000651_10y": [("海康威视", "002415.SZ"), ("格力电器", "000651.SZ")],
    "600519_600036_10y": [("贵州茅台", "600519.SS"), ("招商银行", "600036.SS")],
    "600519_600276_20y": [("贵州茅台", "600519.SS"), ("恒瑞医药", "600276.SS")],
}


def fetch_daily(sym, start):
    p1 = int(datetime.datetime(2004, 1, 1, tzinfo=datetime.timezone.utc).timestamp())
    p2 = int(datetime.datetime.now(datetime.timezone.utc).timestamp() + 86400)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={p1}&period2={p2}&interval=1d"
    req = urllib.request.Request(url, headers=UA)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(
        {"http": PROXY, "https": PROXY}))
    for attempt in range(3):
        try:
            r = opener.open(req, timeout=60)
            res = json.loads(r.read())["chart"]["result"][0]
            ts = res["timestamp"]
            cl = res["indicators"]["quote"][0]["close"]
            adj = res["indicators"].get("adjclose", [{"adjclose": [None] * len(cl)}])[0]["adjclose"]
            out = {}
            for t, c, a in zip(ts, cl, adj):
                if c is None:
                    continue
                d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).date()
                if d.isoformat() < start:
                    continue
                out[d] = a if (a is not None and a > 0) else c
            return out
        except Exception as e:
            print(f"  {sym} attempt{attempt+1} fail: {str(e)[:90]}")
    return {}


def to_weekly_fri(daily):
    """周线, 标记为该周最后交易日实际日期(通常周五), 取最后收盘。"""
    weeks = {}
    for d, p in sorted(daily.items()):
        iso = d.isocalendar()
        weeks[(iso[0], iso[1])] = (d, p)  # 每周最后一根覆盖
    return weeks


def refresh(panel, names_syms):
    path = os.path.join(HERE, f"weekly_yahoo_{panel}.csv")
    import csv as _csv
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(_csv.reader(f))
    header, old = rows[0], rows[1:]
    names = header[1:]
    start = old[0][0]
    base = {r[0]: r[1:] for r in old}
    print(f"\n== {os.path.basename(path)}  旧末行={old[-1][0]}  起始={start}")

    merged = dict(base)
    for (name, sym), col_idx in zip(names_syms, [1, 2]):
        daily = fetch_daily(sym, start)
        if not daily:
            print(f"  ! {name}({sym}) 拉取为空, 跳过该列")
            continue
        wk = to_weekly_fri(daily)
        # 只增量: 覆盖 >= 旧末行所在周的日期(同日取新值, 防复权口径漂移)
        cut = datetime.date.fromisoformat(old[-1][0]) - datetime.timedelta(days=6)
        n_new = 0
        for d, p in sorted(daily.items()):
            iso = d.isocalendar()
            if (iso[0], iso[1]) in wk:
                wd, wp = wk[(iso[0], iso[1])]
                if wd >= cut:
                    key = wd.isoformat()
                    col = col_idx - 1
                    if key not in merged:
                        merged[key] = [None, None]
                    merged[key][col] = f"{wp:.10f}"
                    n_new += 1
        print(f"  {name}({sym}): 最新 {max(daily).isoformat()}, 增补 {n_new} 个周值")

    # 写回: 按 Friday 周五标记排序, 保留完整行
    out_rows = [header]
    for k in sorted(merged):
        v = merged[k]
        if v[0] is None or v[1] is None:
            continue
        out_rows.append([k, v[0], v[1]])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        w.writerows(out_rows)
    print(f"  落盘 {len(out_rows)-1} 行, 末行={out_rows[-1][0]}")


if __name__ == "__main__":
    for panel, ns in PANELS.items():
        try:
            refresh(panel, ns)
        except Exception as e:
            print(f"!! {panel}: {e}")
