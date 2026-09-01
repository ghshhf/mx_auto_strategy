# -*- coding: utf-8 -*-
"""
fetch_hk_now.py — 专拉 5 只港股周线(东方财富后复权 fqt=2)，写入 ashare_weekly_em/<code>.csv
然后重合并面板。激进重试，专为沙箱代理抖动设计。
"""
import os, sys, csv, json, time, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
WK = os.path.join(DATA, "ashare_weekly_em")
os.makedirs(WK, exist_ok=True)

# 代理统一走 net_config 解析 (存活探测 + 回退默认 3067, 规避沙箱注入坏代理)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # 仓库根, 供 net_config
import net_config  # noqa: E402

START = "20100101"
END = "20260726"
API = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
PROXY = net_config.proxy_url()

# (code, market) —— 与 strategy_config.json candidate_pool 对齐
HK = [("00700", "HK"), ("03690", "HK"), ("01810", "HK"), ("00941", "HK"), ("00388", "HK")]

def secid(code, market):
    if market == "HK":
        return f"116.{code}"
    pre = "1" if market == "sh" else "0"
    return f"{pre}.{code}"

def fetch_one(full_secid, retries=15, backoff=4.0):
    params = {
        "secid": full_secid,
        "fields1": "f1,f2,f3",
        "fields2": "f51,f53,f55,f56,f57,f58,f59,f60,f61",
        "klt": "102",
        "fqt": "2",
        "beg": START,
        "end": END,
    }
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    ph = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    opener = urllib.request.build_opener(ph)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with opener.open(req, timeout=30) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
            if not obj.get("data") or not obj["data"].get("klines"):
                print(f"  [空] {full_secid} 无数据", file=sys.stderr)
                return None
            rows = []
            for kl in obj["data"]["klines"]:
                p = kl.split(",")
                try:
                    d = p[0]; o = float(p[1]); h = float(p[2]); l = float(p[3]); c = float(p[4])
                    v = float(p[5]) if len(p) > 5 and p[5] else 0.0
                    a = float(p[6]) if len(p) > 6 and p[6] else 0.0
                    rows.append((d, o, h, l, c, v, a))
                except (ValueError, IndexError):
                    continue
            return rows if rows else None
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff)
    print(f"  [ERR] {full_secid} 重试 {retries} 次仍失败: {last_err}", file=sys.stderr)
    return None

def save(code, rows):
    with open(os.path.join(WK, f"{code}.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume", "amount"])
        for r in rows:
            w.writerow(r)

def build_panel():
    files = [f for f in os.listdir(WK) if f.endswith(".csv")]
    series = {}
    for fn in files:
        code = fn[:-4]
        dates = []; closes = []
        with open(os.path.join(WK, fn), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    dates.append(row["date"]); closes.append(float(row["close"]))
                except (ValueError, KeyError):
                    continue
        series[code] = (dates, closes)
    all_dates = sorted({d for ds, _ in series.values() for d in ds})
    cols = {}
    for code, (dates, closes) in series.items():
        dmap = {d: c for d, c in zip(dates, closes)}
        cols[code] = [dmap.get(d, "") for d in all_dates]
    out = os.path.join(DATA, "ashare_panel_close_em.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date"] + list(cols.keys()))
        for i, d in enumerate(all_dates):
            w.writerow([d] + [cols[c][i] for c in cols])
    print(f"[panel] 合并 {len(series)} 只, {len(all_dates)} 周 -> {out}")

def main():
    print(f"[HK] 开始拉取 {len(HK)} 只港股(激进重试, 代理 {PROXY})", file=sys.stderr)
    ok = []
    for code, mkt in HK:
        sid = secid(code, mkt)
        rows = fetch_one(sid)
        if rows:
            save(code, rows)
            ok.append(code)
            print(f"  [OK] {code} ({len(rows)} 周, {rows[0][0]}~{rows[-1][0]})", file=sys.stderr)
        else:
            print(f"  [FAIL] {code}", file=sys.stderr)
    print(f"[HK] 成功 {len(ok)}/{len(HK)}: {ok}", file=sys.stderr)
    if ok:
        build_panel()
        print("[HK] 面板已重合并含港股列", file=sys.stderr)
    else:
        print("[HK] 全部失败, 面板未变(仍纯 A 股)", file=sys.stderr)

if __name__ == "__main__":
    main()
