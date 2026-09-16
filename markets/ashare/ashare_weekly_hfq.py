# -*- coding: utf-8 -*-
"""
ashare_weekly_hfq.py —— 腾讯后复权(hfq) 周线面板 · A 股主数据源
=================================================================
为什么要换源 (Yahoo 被降级为交叉校验)
------------------------------------
Yahoo 的 A 股日线**系统性缺失交易日**。实测 000063 中兴通讯:
    2019-04-26 close 34.17  →  2019-05-06 open 29.30 / close 28.94
中间 2019-04-29 / 04-30 两个交易日**整段没有**, 于是 3 天累积跌幅被记录成
单日 -15.3%。主板限跌 10%, 不可能 —— 这会让"除权检测"误判, 把真实暴跌
当成除权去"修复", 人为伪造收益。周线层面同样会缺周, 破坏等间距。
(Yahoo 另有 300014 亿纬锂能 2017-05-11 10转10 未复权 -51.3% 的实例。)

接口
----
  https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
  param = sh600519,week,2003-01-01,2026-12-31,1600,hfq
  返回 data["sh600519"]["hfqweek"], 字段 [date, open, close, high, low, volume]
  —— 已是后复权; 交易周完整。经代理 127.0.0.1:3067 可达。

产出
----
  data/tencent_hfq_week/<code>.csv    逐标的后复权周线
  data/ashare_weekly_panel.csv        周线宽表 (index=周五, columns="名称|代码")
  data/ashare_hfq_audit.csv           质量审计 (周末伪跳变 / Yahoo 交叉对账)

用法
----
  python ashare_weekly_hfq.py            # 下载(断点续传) + 建面板 + 审计
  python ashare_weekly_hfq.py --audit    # 只跑审计
"""
import os
import sys
import json
import time
import urllib.parse
import urllib.request
import datetime
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
WK = os.path.join(DATA, "tencent_hfq_week")
sys.path.insert(0, HERE)

from ashare_universe_build import UNIVERSE, NAMES, INDUS, CODES, DAILY  # noqa: E402

PROXY = os.environ.get("MX_PROXY", "http://127.0.0.1:3067")
API = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
START, END, COUNT = "2003-01-01", "2026-12-31", "1600"
UA = {"User-Agent": "Mozilla/5.0"}


def prefix_of(code):
    return "sh" if code[0] == "6" else "sz"


def _fetch_window(code, start, end, count, retries=4, backoff=1.5):
    """单个时间窗 [start, end] 最多 count 条 -> [(date,o,c,h,l,v)]"""
    p = prefix_of(code)
    param = f"{p}{code},week,{start},{end},{count},hfq"
    url = API + "?param=" + urllib.parse.quote(param, safe=",")
    req = urllib.request.Request(url, headers=UA)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(
        {"http": PROXY, "https": PROXY}))
    err = None
    for a in range(1, retries + 1):
        try:
            with opener.open(req, timeout=30) as r:
                obj = json.loads(r.read().decode("utf-8"))
            if obj.get("code") != 0 or not obj.get("data"):
                return None
            blk = obj["data"].get(f"{p}{code}")
            if not blk:
                return None
            kl = blk.get("hfqweek") or blk.get("week")
            if not kl:
                return None
            rows = []
            for k in kl:
                try:
                    rows.append((k[0], float(k[1]), float(k[2]),
                                 float(k[3]), float(k[4]),
                                 float(k[5]) if len(k) > 5 and k[5] else 0.0))
                except (ValueError, IndexError, TypeError):
                    continue
            return rows or None
        except Exception as e:      # noqa: BLE001
            err = e
            if a < retries:
                time.sleep(backoff * a)
    print(f"    ✗ {code} {NAMES.get(code, '')} 窗口 {start}~{end} 失败: {str(err)[:60]}",
          flush=True)
    return None


def fetch_week(code, start=START, end=END, chunk=600):
    """腾讯后复权周线 **分段拉取** (单次接口上限约 640 条, 必须按 end 回退拼接)"""
    rows, seen = [], set()
    e = end
    for _ in range(15):
        part = _fetch_window(code, start, e, chunk)
        if not part:
            break
        new = [r for r in part if r[0] not in seen]
        if not new:
            break
        rows = new + rows
        seen.update(r[0] for r in new)
        earliest = min(r[0] for r in part)
        if earliest <= start or earliest[:4] <= start[:4]:
            break
        e = (datetime.date.fromisoformat(earliest) - datetime.timedelta(days=1)).isoformat()
        time.sleep(0.15)
    return rows or None


def download(force=False):
    os.makedirs(WK, exist_ok=True)
    got = skip = 0
    fail = []
    for i, code in enumerate(CODES, 1):
        path = os.path.join(WK, code + ".csv")
        if os.path.exists(path) and not force:
            skip += 1
            continue
        rows = fetch_week(code)
        if not rows or len(rows) < 40:
            fail.append(code)
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write("date,open,high,low,close,volume\n")
            for d, o, c, h, l, v in rows:
                f.write(f"{d},{o},{h},{l},{c},{v:.0f}\n")
        got += 1
        print(f"    [{i:>3}/{len(CODES)}] {code} {NAMES.get(code,''):<6} {len(rows):>4} 周 "
              f"{rows[0][0]} ~ {rows[-1][0]}", flush=True)
        time.sleep(0.2)
    print(f"\n  下载 {got} / 跳过 {skip} / 失败 {len(fail)}")
    if fail:
        print("  失败: " + " ".join(fail))
    return fail


def to_friday(idx):
    """把交易日归一到该周周五 (不同股票周五停牌时日期会偏, 必须对齐)"""
    import pandas as pd
    return idx + pd.to_timedelta((4 - idx.dayofweek) % 7, unit="D")


def build_panel():
    import pandas as pd
    series, meta = {}, []
    for code in CODES:
        path = os.path.join(WK, code + ".csv")
        if not os.path.exists(path):
            continue
        s = pd.read_csv(path, index_col=0, encoding="utf-8-sig")
        s.index = pd.to_datetime(s.index)
        s = s[~s.index.duplicated()].sort_index()
        w = s["close"].copy()
        w.index = to_friday(w.index)
        w = w[~w.index.duplicated(keep="last")]
        series[NAMES.get(code, code) + "|" + code] = w
        meta.append(dict(code=code, name=NAMES.get(code, ""), ind=INDUS.get(code, ""),
                         n=len(w), first=str(w.index[0].date()),
                         last=str(w.index[-1].date())))
    if not series:
        return None, None
    px = pd.DataFrame(series).sort_index()
    px.index.name = "date"
    # 剔除未走完的当周
    if len(px) and px.index[-1].date() > datetime.date.today():
        px = px.iloc[:-1]
    px.to_csv(os.path.join(DATA, "ashare_weekly_panel.csv"), encoding="utf-8-sig")
    return px, pd.DataFrame(meta)


def audit(px, mt):
    """质量审计: ① 周末伪跳变 (>±60%) ② 与 Yahoo 面板交叉对账(比值恒定)"""
    import pandas as pd
    import numpy as np
    rows = []

    # ---- ① 周末伪跳变
    r = px.pct_change()
    for col in r.columns:
        s = r[col].dropna()
        jump = s[s.abs() > 0.60]
        n_odd = int(((s < -0.20) | (s > 0.25)).sum())
        rows.append(dict(name=str(col).split("|")[0], code=str(col).split("|")[-1],
                         n_weeks=int(s.notna().sum()), n_jump60=len(jump),
                         n_odd=n_odd))
    ad = pd.DataFrame(rows).sort_values("n_odd", ascending=False)
    ad.to_csv(os.path.join(DATA, "ashare_hfq_audit.csv"), index=False,
              encoding="utf-8-sig")

    # ---- ② 与 Yahoo 交叉对账
    ypath = os.path.join(DATA, "ashare_weekly_panel_yahoo.csv")
    xr = None
    if os.path.exists(ypath):
        yh = pd.read_csv(ypath, index_col=0, encoding="utf-8-sig")
        yh.index = pd.to_datetime(yh.index)
        recs = []
        for col in px.columns:
            if col not in yh.columns:
                continue
            j = pd.concat([px[col], yh[col]], axis=1, keys=["t", "y"],
                          sort=False).dropna()
            if len(j) < 100:
                continue
            ratio = j["t"] / j["y"]
            # 若两源同口径(都复权), 比值应恒定; 用变动系数衡量
            cv = float(ratio.std() / ratio.mean()) if ratio.mean() else float("nan")
            # 排除 Yahoo 已知缺日/未复权的标的
            recs.append(dict(name=str(col).split("|")[0], n=len(j),
                             ratio_med=float(ratio.median()), cv=cv,
                             max_dev=float((ratio / ratio.median() - 1).abs().max())))
        xr = pd.DataFrame(recs).sort_values("cv", ascending=False)
        xr.to_csv(os.path.join(DATA, "ashare_crosscheck_yahoo.csv"),
                  index=False, encoding="utf-8-sig")
    return ad, xr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--audit", action="store_true")
    a = ap.parse_args()

    print("=" * 100)
    print("ashare_weekly_hfq.py — A 股行业龙头池 · 腾讯后复权(hfq)周线")
    print("=" * 100)
    print(f"  标的池 {len(CODES)} 只 / {len(set(INDUS.values()))} 个行业 · 代理 {PROXY}")
    if not a.audit:
        print("\n[1/3] 下载腾讯后复权周线 (分段拉取)")
        download(force=a.force)

    print("\n[2/3] 构建周线面板")
    px, mt = build_panel()
    if px is None:
        print("  无数据")
        return
    print(f"  面板 {px.shape[0]} 周 × {px.shape[1]} 只, "
          f"{px.index[0].date()} ~ {px.index[-1].date()}")
    full = mt.sort_values("first")
    print(f"  最早上市: {full.iloc[0]['name']} {full.iloc[0]['first']}")
    print(f"  最晚上市: {full.iloc[-1]['name']} {full.iloc[-1]['first']}")

    print("\n[3/3] 质量审计")
    ad, xr = audit(px, mt)
    bad = ad[ad.n_jump60 > 0]
    print(f"  单周 |涨跌| > 60% 的标的: {len(bad)} 只 (后复权数据应接近 0)")
    for _, rr in bad.iterrows():
        print(f"    {rr['name']:<8} {rr['n_jump60']} 次")
    if xr is not None and len(xr):
        print(f"  与 Yahoo 交叉对账 (比值变动系数 cv, 越小越一致): 共 {len(xr)} 只")
        print(f"    cv 中位 {xr.cv.median():.5f}   cv < 0.02 的 {int((xr.cv < 0.02).sum())} 只")
        print("    最不一致 (Yahoo 缺日/未复权所致):")
        for _, rr in xr.head(6).iterrows():
            print(f"      {rr['name']:<8} cv={rr['cv']:.4f}  最大偏离 {rr['max_dev']*100:>7.2f}%")
    print("\n完成。")


if __name__ == "__main__":
    main()
