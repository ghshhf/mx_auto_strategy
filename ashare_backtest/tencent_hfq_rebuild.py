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

# ---------------------- 港股拆股/合股修正 ----------------------
# 实测: 腾讯 fqkline 对港股(hk 前缀)无论 param 传 hfq/qfq/空, 都只返回
# 未复权的 "week" 序列 —— A 股返回 "hfqweek", 港股没有对应键。
# 因此港股的拆股/合股必须自行修正, 否则会在除权周产生巨大伪跳变,
# 并污染其后 52 周的动量窗口。
#   实例: 00700 腾讯控股 2014-05-15 执行 1拆5,
#         原始周线 2014-05-09 收 478.80 -> 2014-05-16 收 106.50 (-77.8%)。
#
# 修正口径(前复权): 除权日**之前**的所有价格 ÷ ratio, 使收益率序列连续。
#   ratio > 1 = 拆股(1拆N);  ratio < 1 = 合股。
# 面板只取 close, 因此 close 序列修正后即完全正确;
# 跨越除权日的那根周 K 线其 open/high 仍是除权前口径, 会被单独降尺度处理
# (见 _adjust_hk_splits), 该根 K 的盘中 OHLC 属近似值, 已在此显式声明。
#
# 本表是**显式白名单**: 只修正已核实的公司行动, 绝不用启发式比值去"猜"拆股
# (2015 牛市周涨 61% / 新股连续 5 个涨停 1.1^5=+61.1% 都会被比值法误判)。
HK_SPLITS = {
    "00700": [("2014-05-15", 5.0)],   # 腾讯控股 1拆5
}
# 未登记在 HK_SPLITS 里的港股大跳变阈值: 超过则告警提示人工核实, 不静默修正。
HK_JUMP_ALERT = 0.45


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


def _adjust_hk_splits(code, rows):
    """对港股序列做拆股/合股修正 (腾讯港股无复权数据, 必须自行处理)。

    rows: list[(date, open, high, low, close, volume, amount)] 按日期升序。
    返回 (修正后 rows, 修正条数)。

    规则:
      1. 对 HK_SPLITS[code] 中每个 (除权日, ratio):
         - 除权日**之前**结束的周 K: 全部 OHLC ÷ ratio (前复权口径)。
         - **跨越**除权日的那根周 K (周内含除权日): close/low 已是除权后口径,
           但 open/high 可能仍是除权前口径 -> 仅当 open > close * 1.5 时
           把 open/high ÷ ratio, 并重新收敛 high/low 保证 high>=max(o,c)、
           low<=min(o,c)。该根 K 的盘中极值属近似值。
      2. 修正后仍存在 >HK_JUMP_ALERT 的跳变 -> 打印告警(不静默处理)。
    """
    splits = HK_SPLITS.get(code) or []
    n_fixed = 0
    if splits:
        for eff_date, ratio in splits:
            if not ratio or ratio <= 0:
                continue
            out = []
            prev_date = None
            for (d, o, h, l, c, v, a) in rows:
                if d < eff_date:
                    out.append((d, o / ratio, h / ratio, l / ratio,
                                c / ratio, v, a))
                    n_fixed += 1
                elif prev_date is not None and prev_date < eff_date:
                    # 跨越除权日的第一根 K 线
                    if c > 0 and o > c * 1.5:
                        o, h = o / ratio, h / ratio
                        h = max(h, o, c)
                        l = min(l, o, c)
                        n_fixed += 1
                    out.append((d, o, h, l, c, v, a))
                else:
                    out.append((d, o, h, l, c, v, a))
                prev_date = d
            rows = out

    # 残余跳变告警 (未登记的公司行动 / 源站脏数据)
    prev_c = None
    for (d, o, h, l, c, v, a) in rows:
        if prev_c and prev_c > 0 and c > 0:
            ch = c / prev_c - 1
            if abs(ch) > HK_JUMP_ALERT:
                print(f"  [HK-ALERT] {code} {d} 单周 {ch*100:+.1f}% "
                      f"({prev_c:.3f} -> {c:.3f}) 未登记于 HK_SPLITS, 请人工核实"
                      f"是否为拆股/合股/供股。", file=sys.stderr)
        prev_c = c
    return rows, n_fixed


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
    """合并逐标的周线为两张宽表: close 面板 + volume 面板。

    volume 面板供 backtest_engine 的量能确认过滤器使用 (放量突破 vs 缩量假突破)，
    与 close 面板共享完全相同的日期索引和列顺序, 保证按 (i, code) 对齐。
    """
    files = [f for f in os.listdir(WK) if f.endswith(".csv")]
    series = {}
    vols = {}
    for fn in files:
        code = fn[:-4]
        dates = []; closes = []; vs = []
        with open(os.path.join(WK, fn), encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                try:
                    d = row["date"]
                    c = float(row["close"])
                except (ValueError, KeyError):
                    continue
                try:
                    v = float(row.get("volume") or 0.0)
                except ValueError:
                    v = 0.0
                dates.append(d); closes.append(c); vs.append(v)
        series[code] = (dates, closes)
        vols[code] = (dates, vs)
    all_dates = sorted({d for ds, _ in series.values() for d in ds})

    def _wide(src, path, label):
        cols = {}
        for code, (dates, vals) in src.items():
            dmap = {d: v for d, v in zip(dates, vals)}
            cols[code] = [dmap.get(d, "") for d in all_dates]
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date"] + list(cols.keys()))
            for i, d in enumerate(all_dates):
                w.writerow([d] + [cols[c][i] for c in cols])
        print(f"[panel] {label}: {len(src)} 只标的, {len(all_dates)} 个周日期 -> {path}")

    out = os.path.join(DATA, "ashare_panel_close_em.csv")
    vout = os.path.join(DATA, "ashare_panel_volume_em.csv")
    _wide(series, out, "收盘面板")
    _wide(vols, vout, "成交量面板")
    if verify:
        scan_anomalies(series)
    return out


# A 股单周理论涨幅上限: 5 个交易日连续涨停。
#   主板/中小板 ±10%  -> 1.10^5 - 1 = +61.05%
#   创业板/科创板 ±20% -> 1.20^5 - 1 = +148.8%
#   次新股上市初期不设涨跌幅, 单周涨幅可更高。
# 因此 ">50% 就是伪迹" 是错的判据: 连板 / 2015 牛市周 / 2024-09-24 行情
# 都会产生 +50%~+61% 的**真实**周涨幅。真正的伪迹特征是
#   ① 跌幅接近 1/N (拆股未复权), 或 ② 涨幅超过该板块理论连板上限。
LIMIT_UP_CAP = {
    "main": 1.10 ** 5 - 1.0,    # +61.05%
    "gem": 1.20 ** 5 - 1.0,     # +148.8%
}


def _board_cap(code):
    """按板块返回单周理论最大涨幅(留 2% 余量吸收浮点/除权尾差)。"""
    c = str(code)
    if c.startswith(("30", "688", "8", "4")):        # 创业板/科创板/北交所
        return LIMIT_UP_CAP["gem"] + 0.02
    if c.startswith(("11", "12", "15", "5")):        # 可转债/ETF 无涨跌幅或宽幅
        return 10.0
    if len(c) == 5:                                   # 港股无涨跌幅限制
        return 10.0
    return LIMIT_UP_CAP["main"] + 0.02                # 主板 +63%


# 常见拆股/合股比例, 用于识别"跌幅≈1/N"的未复权伪迹
_SPLIT_RATIOS = (2.0, 3.0, 4.0, 5.0, 10.0, 20.0)


def scan_anomalies(series, thr=0.5):
    """自检: 区分 [真实极端行情] 与 [疑似数据伪迹]。

    真实(不告警): 涨幅 <= 该板块 5 连板理论上限。
    疑似伪迹(告警):
      A) 跌幅接近 1/N (N in _SPLIT_RATIOS, 容差 15%) -> 疑似拆股未复权
      B) 涨幅超过板块理论连板上限                    -> 疑似数据错位
    """
    extreme, suspect = 0, []
    for code, (dates, closes) in series.items():
        cap = _board_cap(code)
        for k in range(1, len(closes)):
            a, b = closes[k - 1], closes[k]
            if not (a and a > 0 and b and b > 0):
                continue
            ratio = b / a
            chg = ratio - 1.0
            if abs(chg) <= thr:
                continue
            extreme += 1
            if chg > cap:
                suspect.append((code, dates[k], chg, "涨幅超板块连板上限"))
            elif chg < 0:
                for n in _SPLIT_RATIOS:
                    if abs(ratio * n - 1.0) < 0.15:
                        suspect.append((code, dates[k], chg,
                                        f"跌幅≈1/{n:g}, 疑似拆股未复权"))
                        break
    print(f"[verify] 单周振幅 >{thr*100:.0f}% 共 {extreme} 处 "
          f"(连板/牛市周属正常, 已按板块涨停上限判别)")
    if not suspect:
        print("[verify] 伪迹自检通过: 0 处疑似数据伪迹 ✅")
        return 0
    print(f"[verify] ⚠ {len(suspect)} 处疑似伪迹, 需核实:")
    for code, d, chg, why in suspect:
        print(f"         {code} {d} {chg*100:+.1f}%  <- {why}")
    return len(suspect)


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
        if prefix == "hk":
            rows, n_fix = _adjust_hk_splits(code, rows)
            if n_fix:
                print(f"  [HK-FIX] {code} 拆股修正 {n_fix} 根 K 线", file=sys.stderr)
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
