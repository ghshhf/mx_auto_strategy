#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扩展美股面板: 追加缺失的主要美股/ADR 周线后复权收盘价。
====================================================================
预承诺规则(防前视/幸存者偏差陷阱):
  选股标准 = 规模/知名度驱动(巨型/大型美股 + 主要EM成长平台),
  而非历史收益表现。即"任何宽泛美股+ADR动量宇宙本应包含的名字"。
  这些票是人工核对面板后发现的明显缺漏(台积电/Visa/主要拉美东南亚
  中概成长平台/电商SaaS/金融科技), 不是看收益后挑的赢家。

数据源: westock-data (腾讯自选股) kline --period week --fq hfq, 经代理 3067。
  hfq(后复权) 与 qfq 在周度收益率上完全等价(仅整体缩放常数不同, 比值抵消),
  选 hfq 以对齐项目"后复权金标准"哲学。回测只用列内周收益率 + 跨列动量比值,
  尺度无关, 故与新列是否同源面板无关, 只需每列自身除权一致。

对齐: 面板周日期 -> kline 最近 <= 该日期的收盘(ffill); 上市前(无数据)填空。
  SE 2017-10 / PDD 2018-07 / NU 2021-12 IPO 前自动为空, 引擎 eligible_universe
  要求 >=1 年历史, 这些票自然延后入池, 无前视。

用法: python extend_panel_us_tickers.py
"""
import csv, os, sys, subprocess, time

HERE = os.path.dirname(os.path.abspath(__file__))
# 2026-09-01: 代理改由 net_config 统一解析 (原为硬编码 3067); 对齐改委托 panel_align
sys.path.insert(0, os.path.dirname(HERE))   # 仓库根 -> net_config
sys.path.insert(0, HERE)                    # us_stocks/ -> panel_align
from net_config import proxy_url  # noqa: E402
from panel_align import align_asof_str  # noqa: E402

PANEL = os.path.join(HERE, "data", "weekly_adjclose_full_ext.csv")
NODE = "C:/Users/21393/.workbuddy/binaries/node/versions/24.14.0/node.exe"
WSK = ("C:/Users/21393/AppData/Local/Programs/WorkBuddy/resources/"
       "app.asar.unpacked/resources/builtin-skills/westock-data/scripts/index.js")
PROXY = proxy_url()

# 预承诺扩池名单(规模/知名度驱动, 非收益驱动) —— MA 已在面板, 此处仅补缺失 8 只。
TICKERS = ["TSM", "V", "MELI", "SE", "PDD", "NU", "SHOP", "SQ"]
START = "2016-02-16"
END = "2026-07-20"


def fetch_weekly_hfq(code):
    """返回 {date: close} 周线后复权收盘(last列)。"""
    env = dict(os.environ)
    env["HTTPS_PROXY"] = PROXY
    env["HTTP_PROXY"] = PROXY
    cmd = [NODE, WSK, "kline", "us" + code, "--period", "week", "--fq", "hfq",
           "--start", START, "--end", END]
    out = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=150)
    if out.returncode != 0:
        raise RuntimeError(f"{code} rc={out.returncode} err={out.stderr[:200]}")
    series = {}
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 4:
            continue
        d = parts[0]
        if d == "date" or not (len(d) == 10 and d[4] == "-"):
            continue
        try:
            series[d] = float(parts[2])  # 'last' = 后复权收盘
        except ValueError:
            continue
    if not series:
        raise RuntimeError(f"{code} 未解析到任何周线")
    return series


def align(series, dates):
    """将 kline {date:close} 对齐到面板周日期序列: ffill, 上市前空字符串。

    注意参数顺序与 panel_align 相反 (本函数历史签名为 (series, dates), 保留以免
    破坏调用方)。2026-09-01: 实现改委托共享 align_asof_str (行为等价)。
    """
    return align_asof_str(dates, series, fmt="%.5f", empty="")


def main():
    rows = list(csv.reader(open(PANEL, encoding="utf-8")))
    hdr, data = rows[0], rows[1:]
    dates = [r[0] for r in data]
    new_cols = [t for t in TICKERS if t not in hdr]
    print(f"面板列数={len(hdr)} 行数={len(data)} | 计划新增={new_cols}")

    series_map = {}
    for t in new_cols:
        s = None
        for attempt in range(3):
            try:
                s = fetch_weekly_hfq(t)
                break
            except Exception as e:
                print(f"  [retry {attempt + 1}] {t}: {e}")
                time.sleep(3)
        if not s:
            print(f"  !! {t} 拉取失败, 跳过")
            continue
        series_map[t] = s
        print(f"  {t}: {len(s)} 周 | 首 {min(s)}={s[min(s)]:.2f} 末 {max(s)}={s[max(s)]:.2f}")

    new_rows = [list(r) for r in data]
    added = []
    for t in new_cols:
        if t not in series_map:
            continue
        col = align(series_map[t], dates)
        nonblank = sum(1 for c in col if c)
        for i, r in enumerate(new_rows):
            r.append(col[i])
        hdr.append(t)
        added.append(t)
        print(f"  对齐 {t}: 有效周 {nonblank}/{len(dates)}")

    if added:
        with open(PANEL, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(hdr)
            w.writerows(new_rows)
        print(f"写回完成: 新列 {added} | 总列数={len(hdr)}")
    else:
        print("无新增列, 面板未改动")


if __name__ == "__main__":
    main()
