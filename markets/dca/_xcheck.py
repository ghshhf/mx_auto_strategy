# -*- coding: utf-8 -*-
"""交叉验证 A股腿：腾讯 hfq vs 东财 fqt=2，谁的序列更干净、总回报是否一致"""
import csv, io, json, os, sys
import urllib.request
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
from net_config import proxy_opener  # noqa


def em(sym, tries=5):
    import time
    code, mkt = sym.split(".")
    secid = ("1." if mkt == "SS" else "0.") + code
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
           f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
           f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&fqt=2"
           f"&beg=0&end=20500101")
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://quote.eastmoney.com/"})
            with proxy_opener().open(req, timeout=60) as r:
                j = json.loads(r.read().decode())
            kl = (j.get("data") or {}).get("klines") or []
            if kl:
                return [{"date": l.split(",")[0], "v": float(l.split(",")[2])}
                        for l in kl]
            last = "空"
        except Exception as e:
            last = f"{type(e).__name__}"
        time.sleep(2.5 * (k + 1))
    raise RuntimeError(f"东财失败({last})")


def tc(sym):
    p = os.path.join(HERE, "data", "history", f"{sym}.csv")
    return [{"date": r["date"], "v": float(r["adjclose"])}
            for r in csv.DictReader(open(p, encoding="utf-8"))]


def audit(name, rows):
    d = [r["date"] for r in rows]
    a = np.array([r["v"] for r in rows])
    ret = a[1:] / a[:-1] - 1
    spike = np.where(np.abs(ret) > 0.4)[0]
    print(f"  {name:12s} n={len(a):5d} {d[0]}->{d[-1]}  "
          f"首 {a[0]:.4f} 末 {a[-1]:.4f}  总 {a[-1]/a[0]:.3f}×  "
          f"min {a.min():.4f}  非正 {(a<=0).sum()}  单日|涨跌|>40% {len(spike)} 处")
    for i in spike[:5]:
        print(f"      {d[i+1]}  {a[i]:.4f} -> {a[i+1]:.4f}  {ret[i]:+.2%}")
    return a, d


print("=== 510880 上证红利ETF ===")
a_em, d_em = audit("东财fqt2", em("510880.SS"))
a_tc, d_tc = audit("腾讯hfq", tc("510880.SS"))
m = {x: v for x, v in zip(d_em, a_em)}
common = [x for x in d_tc if x in m]
r0 = m[common[0]] / dict(zip(d_tc, a_tc))[common[0]]
print(f"  重叠 {len(common)} 天，起点比值(东财/腾讯) {r0:.4f}")
for k in [0, len(common)//3, 2*len(common)//3, len(common)-1]:
    x = common[k]
    print(f"    {x}  东财 {m[x]:.4f}  腾讯 {dict(zip(d_tc,a_tc))[x]:.4f}  "
          f"比 {(m[x]/dict(zip(d_tc,a_tc))[x])/r0:.4f}")

print("\n=== 515100 红利低波100ETF ===")
audit("东财fqt2", em("515100.SS"))
audit("腾讯hfq", tc("515100.SS"))

print("\n=== 000300 沪深300 ===")
audit("东财fqt2", em("000300.SS"))
audit("腾讯hfq", tc("000300.SS"))
