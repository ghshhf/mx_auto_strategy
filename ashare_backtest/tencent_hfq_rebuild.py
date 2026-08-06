# -*- coding: utf-8 -*-
"""
tencent_hfq_rebuild.py
======================
用腾讯 web.ifzq.gtimg.cn (后复权 hfq) 重建 A 股周线面板，产出可信的多年级回测数据。

为什么要这个脚本（替代 eastmoney_hfq_rebuild.py）：
  东方财富 push2his.eastmoney.com 已无法通过代理访问。经实测，腾讯
  web.ifzq.gtimg.cn 的 fqkline 接口通过代理 127.0.0.1:3067 完美可用，
  且返回字段顺序正确: [date, open, close, high, low, volume]
  （东方财富 fields2 存在字段映射 bug，close 实为 weekly-low）。

依赖（零第三方库，任意 Python 3.8+ 直接跑，无需 pip install）：
  仅标准库 urllib / csv / json / time / os / sys / argparse。
  需要代理 http://127.0.0.1:3067 能访问 https://web.ifzq.gtimg.cn

产出（与 backtest_engine.load_panel(panel_path=...) 直接兼容）：
  data/ashare_weekly_em/<code>.csv           逐标的原始周线(OHLC+量额)
  data/ashare_panel_close_em.csv             合并宽表(index=date, columns=code, value=close)

之后跑真实 10 年：
  python run_10y.py

特性：
  - 断点续传：已拉取的 <code>.csv 自动跳过，可反复重跑补全。
  - 自动纳入代理票：宁德->比亚迪(002594)、中际->浪潮(000977)、凯莱英->恒瑞(600276)
    以及引擎内置 DEF16/OFF4/指数/可转债，确保核心仓时间扩展所需标的齐全。
  - 重试退避：单标的失败自动重试（指数退避），降低偶发网络抖动丢数。
  - 进度条：stderr 实时进度（不影响 stdout 日志）。
  - 拉取后自检(--verify)：扫描单周涨跌幅 > 50% 的伪迹，金标准数据应接近 0。
"""
import os
import sys
import csv
import json
import time
import argparse
import urllib.request
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, BASE)
import backtest_engine as _E  # 仅取内置篮子常量，无副作用

DATA = os.path.join(BASE, "data")
WK = os.path.join(DATA, "ashare_weekly_em")
os.makedirs(WK, exist_ok=True)

START = "2010-01-01"
END = "2026-12-31"
MAX_COUNT = "1000"
API = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

PROXY_HOST = "http://127.0.0.1:3067"

# 指数(周线死叉 + 三档识别) 与 可转债(弱势进攻替代)
INDICES = [("000300", "sh"), ("000905", "sh"), ("000001", "sh"),
           ("399006", "sz"), ("000016", "sh"), ("000852", "sh")]
CONVERTIBLES = [("113050", "sh"), ("113052", "sh")]

# 引擎内置篮子里所有会被回测触碰的标的，确保一个不漏地拉取
ENGINE_CODES = list(_E.DEF16) + list(_E.OFF4) + list(_E.CORE_SUB.values())


def market_prefix(code, market=None):
    """根据代码和 market 标记返回腾讯行情前缀: sh / sz / hk。

    规则:
      HK  -> hk
      显式 sh/sz (指数如 000300=沪, 399006=深) -> 直接使用
      6/9/5 开头 -> sh (沪市主板/B股/ETF)
      0/3/8/4 开头 -> sz (深市主板/创业板/中小板)
      11 开头 -> sh (沪市可转债 110/113/118)
      12/15 开头 -> sz (深市可转债 123/127/128 / 深市ETF 159)
    """
    if market == "HK":
        return "hk"
    if market in ("sh", "sz"):   # 指数等显式指定市场的标的
        return market
    c = code.strip()
    if c.startswith("11"):          # 沪市可转债
        return "sh"
    if c.startswith(("12", "15")):  # 深市可转债 / 深市ETF
        return "sz"
    first = c[0] if c else "6"
    if first in ("6", "9", "5"):
        return "sh"
    if first in ("0", "3", "8", "4"):
        return "sz"
    return "sh"


def build_opener():
    """构建带代理的 opener（代理对所有 http/https 请求生效）。"""
    proxy = urllib.request.ProxyHandler(
        {"http": PROXY_HOST, "https": PROXY_HOST})
    return urllib.request.build_opener(proxy)


def fetch_one(code, prefix, retries=4, backoff=1.5):
    """返回 list[(date,open,high,low,close,volume,amount)] 或 None。后复权周线。

    腾讯返回字段顺序: [date, open, close, high, low, volume]
    CSV 存储顺序:     [date, open, high, low, close, volume, amount]
    """
    param = f"{prefix}{code},week,{START},{END},{MAX_COUNT},hfq"
    url = API + "?param=" + urllib.parse.quote(param, safe=",")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    opener = build_opener()
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with opener.open(req, timeout=30) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
            if obj.get("code") != 0 or not obj.get("data"):
                return None
            key = f"{prefix}{code}"
            blk = obj["data"].get(key)
            if not blk:
                return None
            # A股/ETF 有 hfqweek; HK/可转债 只有 week(无复权需求)
            klines = blk.get("hfqweek") or blk.get("week")
            if not klines:
                return None
            rows = []
            for kl in klines:
                try:
                    # 腾讯: [date, open, close, high, low, volume]
                    d = kl[0]
                    o = float(kl[1]); c = float(kl[2])
                    h = float(kl[3]); l = float(kl[4])
                    v = float(kl[5]) if len(kl) > 5 and kl[5] else 0.0
                    # CSV: date, open, high, low, close, volume, amount
                    rows.append((d, o, h, l, c, v, 0.0))
                except (ValueError, IndexError):
                    continue
            return rows if rows else None
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff * attempt)
    print(f"  [ERR] {prefix}{code} 重试 {retries} 次仍失败: {last_err}", file=sys.stderr)
    return None


def save_code_csv(code, rows):
    path = os.path.join(WK, f"{code}.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume", "amount"])
        for r in rows:
            w.writerow(r)


def load_config():
    cp = os.path.join(ROOT, "strategy_config.json")
    if not os.path.exists(cp):
        return {}
    return json.load(open(cp, encoding="utf-8"))


def collect_codes(cfg):
    """汇总所有需拉取的标的: 配置池 + 引擎内置篮子 + 指数 + 可转债。"""
    codes = {}
    for p in cfg.get("auto_select", {}).get("candidate_pool", []):
        codes[p["code"]] = p.get("market")
    for p in cfg.get("auto_select", {}).get("offensive_pool", []):
        codes.setdefault(p["code"], p.get("market"))
    for c in ENGINE_CODES:
        codes.setdefault(c, None)
    for c, m in INDICES:
        codes[c] = m
    for c, m in CONVERTIBLES:
        codes[c] = m
    return codes


def build_panel(verify=False):
    files = [f for f in os.listdir(WK) if f.endswith(".csv")]
    series = {}
    for fn in files:
        code = fn[:-4]
        dates = []; closes = []
        with open(os.path.join(WK, fn), encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                try:
                    dates.append(row["date"])
                    closes.append(float(row["close"]))
                except (ValueError, KeyError):
                    continue
        series[code] = (dates, closes)
    all_dates = sorted({d for ds, _ in series.values() for d in ds})
    close_cols = {}
    for code, (dates, closes) in series.items():
        dmap = {d: c for d, c in zip(dates, closes)}
        close_cols[code] = [dmap.get(d, "") for d in all_dates]
    out = os.path.join(DATA, "ashare_panel_close_em.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date"] + list(close_cols.keys()))
        for i, d in enumerate(all_dates):
            w.writerow([d] + [close_cols[c][i] for c in close_cols])
    print(f"[panel] 合并 {len(series)} 只标的, {len(all_dates)} 个周日期 -> {out}")
    if verify:
        scan_anomalies(series)
    return out


def scan_anomalies(series, thr=0.5):
    """自检: 扫描单周涨跌幅 > thr 的伪迹(金标准应接近 0)。"""
    bad = 0
    for code, (dates, closes) in series.items():
        for k in range(1, len(closes)):
            a, b = closes[k - 1], closes[k]
            if a and a > 0 and b and b > 0:
                chg = abs(b / a - 1.0)
                if chg > thr:
                    bad += 1
    if bad == 0:
        print(f"[verify] 伪迹自检通过: 0 处单周异常跳变 (>50%), 数据可信 ✅")
    else:
        print(f"[verify] ⚠ 发现 {bad} 处单周异常跳变 (>50%), 数据可能含伪迹, 请核查源站返回。")


def progress(cur, total, done, skip, fail):
    pct = (cur * 100 // total) if total else 100
    bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
    print(f"\r  [{bar}] {cur}/{total}  新增 {done} 跳过 {skip} 失败 {fail}",
          end="", file=sys.stderr, flush=True)


def main():
    ap = argparse.ArgumentParser(
        description="腾讯后复权重建 A 股周线面板（干净多年数据）")
    ap.add_argument("--budget", type=float, default=600,
                    help="本轮最大运行秒数(断点续传, 默认 600)")
    ap.add_argument("--sleep", type=float, default=0.08,
                    help="每标的间隔秒(防限频, 默认 0.08)")
    ap.add_argument("--force", action="store_true",
                    help="强制重拉(忽略已存在的 <code>.csv)")
    ap.add_argument("--verify", action="store_true",
                    help="构建面板后做伪迹自检")
    args = ap.parse_args()

    cfg = load_config()
    codes = collect_codes(cfg)
    total = len(codes)
    print(f"[fetch] 待拉取 {total} 只, 口径=腾讯后复权(hfq)")
    t0 = time.time(); done = skip = fail = 0; cur = 0
    for code, market in codes.items():
        cur += 1
        fpath = os.path.join(WK, f"{code}.csv")
        if not args.force and os.path.exists(fpath) and os.path.getsize(fpath) > 50:
            skip += 1
            progress(cur, total, done, skip, fail)
            continue
        if time.time() - t0 > args.budget:
            print(f"\n  ⏱ 预算到点, 暂停(本轮新增 {done}); 重跑可续传", file=sys.stderr)
            break
        prefix = market_prefix(code, market)
        rows = fetch_one(code, prefix)
        if rows is None:
            fail += 1
            progress(cur, total, done, skip, fail)
            time.sleep(0.3)
            continue
        save_code_csv(code, rows); done += 1
        if done % 5 == 0:
            print(f"  [OK] {done} 只, 最近 {code} ({len(rows)} 周, {rows[0][0]}~{rows[-1][0]})",
                  file=sys.stderr)
        progress(cur, total, done, skip, fail)
        time.sleep(args.sleep)
    print("", file=sys.stderr)
    print(f"[fetch] 本轮: 新增 {done}, 跳过 {skip}, 失败 {fail}")

    out = build_panel(verify=args.verify)

    print("\n=== 下一步 ===")
    print(f"面板已生成: {out}")
    print("运行:")
    print("    python run_10y.py")
    print("即可用干净面板 + 核心仓时间扩展 跑真实 ~10 年 NAV。")


if __name__ == "__main__":
    main()
