# -*- coding: utf-8 -*-
"""markets/dca/fetch_history.py —— 多市场长历史抓取器（**渠道固化，唯一入口**）

设计原则
--------
1. **落盘优先**：抓到即写 ``markets/dca/data/history/{SYM}.csv``，二次运行直接读盘，
   不重复出网（`--force` 可强制刷新）。
2. **多源回退**：Yahoo query2 -> query1 -> 东财 push2his -> 腾讯 fqkline。
3. **不做静默降级**：任一标的抓失败会明确记进 ``data/FETCH_LOG.json``，不假装成功。
4. 代理统一走仓库的 ``net_config``（唯一真源），不硬编码。

用法
----
    python markets/dca/fetch_history.py            # 增量：已有的跳过
    python markets/dca/fetch_history.py --force    # 全量重抓
    python markets/dca/fetch_history.py --only ^GSPC,^NDX
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import ssl
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from net_config import proxy_opener, proxy_url  # noqa: E402  仓库唯一代理源

ssl._create_default_https_context = ssl._create_unverified_context

DATA = os.path.join(HERE, "data")
HIST = os.path.join(DATA, "history")
os.makedirs(HIST, exist_ok=True)

EPOCH = dt.datetime(1970, 1, 1)


def ts2date(ts: int) -> str:
    """Windows 上时间戳为负（1970 前）时 datetime.fromtimestamp 会 OSError，故手算。"""
    return (EPOCH + dt.timedelta(seconds=int(ts))).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- 标的清单
# kind: us_index / hk_index / cn_etf / us_etf / fx / commodity
UNIVERSE: list[tuple[str, str, str]] = [
    # ---- 美股宽基（40 年推演主腿）----
    ("^GSPC",    "标普500 价格指数",              "us_index"),
    ("^SP500TR", "标普500 全收益(含分红再投)",     "us_index"),
    ("^NDX",     "纳斯达克100 价格指数",           "us_index"),
    ("QQQ",      "纳斯达克100 ETF",                "us_etf"),
    ("^DJI",     "道琼斯工业平均",                 "us_index"),
    ("^IXIC",    "纳斯达克综合",                   "us_index"),
    ("SPY",      "标普500 ETF",                    "us_etf"),
    ("VOO",      "Vanguard 标普500 ETF",           "us_etf"),
    # ---- 港股（长历史）----
    ("^HSI",     "恒生指数",                       "hk_index"),
    ("^HSCE",    "恒生中国企业指数",                "hk_index"),
    ("^HSTECH",  "恒生科技指数",                    "hk_index"),
    ("3110.HK",  "Global X 恒生高股息率ETF",        "hk_etf"),
    ("2800.HK",  "盈富基金",                       "hk_etf"),
    ("3186.HK",  "恒生中国企业ETF",                 "hk_etf"),
    # ---- A股（用户指定腿 + 长历史代理）----
    ("515100.SS", "红利低波100ETF(用户指定)",       "cn_etf"),
    ("510880.SS", "上证红利ETF(长历史代理)",         "cn_etf"),
    ("510300.SS", "沪深300ETF",                    "cn_etf"),
    ("159915.SZ", "创业板ETF",                     "cn_etf"),
    ("512880.SS", "证券ETF",                       "cn_etf"),
    ("000300.SS", "沪深300指数",                    "cn_index"),
    ("000001.SS", "上证综指",                       "cn_index"),
    # ---- 美股红利（风格对照）----
    ("SCHD", "Schwab 美股红利",     "us_etf"),
    ("VYM",  "Vanguard 高股息",     "us_etf"),
    ("DVY",  "iShares 道指精选红利", "us_etf"),
    ("NOBL", "标普500 股息贵族",     "us_etf"),
    # ---- 其他 ----
    ("CNY=X", "美元兑人民币",  "fx"),
    ("GC=F",  "黄金期货",     "commodity"),
    ("^TNX",  "美债10年收益率", "rate"),
]


# ---------------------------------------------------------------- 抓取器
def _yahoo(sym: str, interval: str = "1d", host: str = "query2") -> list[dict]:
    p1 = 0 if sym in ("CNY=X",) else -2208988800  # 1900-01-01
    url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={p1}&period2={int(time.time())}"
           f"&interval={interval}&events=div%2Csplit")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with proxy_opener().open(req, timeout=90) as r:
        j = json.loads(r.read().decode())
    res = j.get("chart", {}).get("result")
    if not res:
        return []
    r0 = res[0]
    ts = r0.get("timestamp") or []
    q = r0["indicators"]["quote"][0]
    clo = q.get("close") or []
    adj = (r0["indicators"].get("adjclose") or [{}])[0].get("adjclose") or clo
    out = []
    for i, t in enumerate(ts):
        c = clo[i] if i < len(clo) else None
        a = adj[i] if i < len(adj) else None
        if c is None and a is None:
            continue
        out.append({"date": ts2date(t),
                    "close": c,
                    "adjclose": a if a is not None else c})
    return out


def _eastmoney(sym: str, interval: str = "1d") -> list[dict]:
    """东财 push2his。**fqt=2 后复权**（不用 fqt=1 前复权，见下）。
    klt: 101=日 102=周。

    ⚠️ 为什么必须后复权：前复权把历史价格按累计分红往下调，对长期高分红品种
    （如 510880 上证红利 ETF）会把 2008 年前后的价格压到 **负数**（实测
    -0.109 / -0.279），序列彻底崩坏，回测会出现 -99% 的假浮亏。
    后复权向上调整，永远为正，且同样含分红再投资。
    """
    code, mkt = sym.split(".")
    secid = ("1." if mkt in ("SS", "SH-A") else "0.") + code
    klt = {"1d": "101", "1wk": "102"}[interval]
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
           f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
           f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
           f"&klt={klt}&fqt=2&beg=0&end=20500101")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
    with proxy_opener().open(req, timeout=60) as r:
        j = json.loads(r.read().decode())
    kl = (j.get("data") or {}).get("klines") or []
    out = []
    for line in kl:
        p = line.split(",")
        # 日期,开,收,高,低,成交量,成交额,振幅
        out.append({"date": p[0], "close": float(p[2]), "adjclose": float(p[2])})
    return out


def _tencent(sym: str, interval: str = "1d") -> list[dict]:
    """腾讯 fqkline，**hfq 后复权**。单次上限 ~640 条，需按 end 分段回退拼接。"""
    code, mkt = sym.split(".")
    tc = ("sh" if mkt == "SS" else "sz") + code
    step = {"1d": "day", "1wk": "week"}[interval]
    fq = "hfq"
    allrows: dict[str, dict] = {}
    end = ""
    for _ in range(80):
        if end:
            url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                   f"?param={tc},{step},,{end},640,{fq}&_var=kline")
        else:
            url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                   f"?param={tc},{step},,,640,{fq}&_var=kline")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with proxy_opener().open(req, timeout=45) as r:
            txt = r.read().decode()
        txt = txt[txt.find("=") + 1:]
        j = json.loads(txt)
        d = j.get("data", {}).get(tc, {})
        rows = d.get(f"{fq}{step}") or d.get(step) or []
        if not rows:
            break
        for row in rows:
            allrows[row[0]] = {"date": row[0], "close": float(row[2]),
                               "adjclose": float(row[2])}
        first = rows[0][0]
        if first == end or len(rows) < 2:
            break
        end = first
    return [allrows[k] for k in sorted(allrows)]


def fetch_one(sym: str, interval: str = "1d") -> tuple[list[dict], str]:
    """按序尝试各渠道，返回 (数据, 命中的渠道名)。"""
    attempts: list[tuple[str, callable]] = []
    if sym.endswith((".SS", ".SZ")):
        attempts = [("eastmoney", _eastmoney), ("tencent", _tencent),
                    ("yahoo2", lambda s, i="1d": _yahoo(s, i, "query2"))]
    else:
        attempts = [("yahoo2", lambda s, i="1d": _yahoo(s, i, "query2")),
                    ("yahoo1", lambda s, i="1d": _yahoo(s, i, "query1"))]
    errs = []
    for name, fn in attempts:
        try:
            rows = fn(sym, interval)
            if len(rows) > 20:
                return rows, name
            errs.append(f"{name}: 仅 {len(rows)} 条")
        except Exception as e:
            errs.append(f"{name}: {type(e).__name__} {str(e)[:50]}")
        time.sleep(0.4)
    raise RuntimeError(" | ".join(errs))


def clean_spikes(rows: list[dict], thr: float = 0.45) -> list[str]:
    """删除「孤立毛刺」：某点相对前后都跳 >45% 且方向相反（= 单点异常）。

    历史案例：腾讯 hfq 的 510880 在 2008-01-03 出现 3.0390 -> 0.9610 -> 3.1410，
    单日 -68%/+227%，是复权因子在分红登记日的台阶错误。删掉该点（19.7 年里
    少一个交易日的买入），对结果影响可忽略；不删则会污染最深浮亏。
    """
    import math
    dropped = []
    i = 1
    while i < len(rows) - 1:
        p0, p1, p2 = rows[i-1]["adjclose"], rows[i]["adjclose"], rows[i+1]["adjclose"]
        if p0 > 0 and p1 > 0 and p2 > 0:
            a, b = math.log(p1 / p0), math.log(p2 / p1)
            if abs(a) > thr and abs(b) > thr and a * b < 0 and abs(a + b) < 0.35:
                dropped.append(f"{rows[i]['date']} ({p1:.4f}, 前后 {p0:.4f}/{p2:.4f})")
                rows.pop(i)
                continue
        i += 1
    return dropped


def save_csv(sym: str, rows: list[dict]) -> str:
    safe = sym.replace("^", "IDX_").replace("=", "_").replace("/", "_")
    path = os.path.join(HIST, f"{safe}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "close", "adjclose"])
        for r in rows:
            w.writerow([r["date"], r["close"], r["adjclose"]])
    return path


def validate(sym: str, rows: list[dict]) -> list[str]:
    """抓完立刻体检。历史教训：前复权序列会出负价（510880 在 2008 段 -0.279），
    若不拦住，回测会给出 -99% 的假浮亏。"""
    bad = []
    vals = [r["adjclose"] for r in rows]
    neg = [(r["date"], r["adjclose"]) for r in rows if r["adjclose"] <= 0]
    if neg:
        bad.append(f"非正价格 {len(neg)} 处（首处 {neg[0][0]}={neg[0][1]:.4f}）")
    if len(vals) > 30:
        import statistics
        jumps = 0
        for i in range(1, min(len(vals), 3000)):
            if vals[i - 1] > 0 and abs(vals[i] / vals[i - 1] - 1) > 0.6:
                jumps += 1
        if jumps > 3:
            bad.append(f"疑似断点 {jumps} 次单日|涨跌|>60%")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="强制重抓")
    ap.add_argument("--interval", default="1d", choices=["1d", "1wk"])
    ap.add_argument("--only", default="", help="逗号分隔的代码子集")
    args = ap.parse_args()

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    print(f"代理: {proxy_url()}")
    log, ok, skip, fail = {}, 0, 0, 0
    for sym, name, kind in UNIVERSE:
        if only and sym not in only:
            continue
        safe = sym.replace("^", "IDX_").replace("=", "_").replace("/", "_")
        path = os.path.join(HIST, f"{safe}.csv")
        if os.path.exists(path) and not args.force:
            with open(path, encoding="utf-8") as f:
                n = sum(1 for _ in f) - 1
            print(f"  [skip] {sym:11s} {name:22s} 已有 {n} 条")
            log[sym] = dict(name=name, kind=kind, rows=n, source="cache",
                            file=os.path.relpath(path, REPO))
            skip += 1
            continue
        try:
            rows, src = fetch_one(sym, args.interval)
            dropped = clean_spikes(rows)
            issues = validate(sym, rows)
            save_csv(sym, rows)
            span = f"{rows[0]['date']} -> {rows[-1]['date']}"
            tag = "" if not issues else "  ⚠ " + "; ".join(issues)
            if dropped:
                tag += f"  [清洗 {len(dropped)} 点: {dropped[0]}]"
            print(f"  [ ok ] {sym:11s} {name:22s} {len(rows):6d} 条  {span}  via {src}{tag}")
            log[sym] = dict(name=name, kind=kind, rows=len(rows), source=src,
                            start=rows[0]["date"], end=rows[-1]["date"],
                            file=os.path.relpath(path, REPO),
                            dropped_spikes=dropped or None,
                            issues=issues or None)
            ok += 1
        except Exception as e:
            print(f"  [FAIL] {sym:11s} {name:22s} {e}")
            log[sym] = dict(name=name, kind=kind, error=str(e)[:200])
            fail += 1
        time.sleep(0.5)

    with open(os.path.join(DATA, "FETCH_LOG.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    print(f"\n完成: 新抓 {ok} / 命中缓存 {skip} / 失败 {fail}")
    print(f"日志: {os.path.join(DATA, 'FETCH_LOG.json')}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
