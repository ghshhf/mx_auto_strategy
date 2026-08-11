"""
crypto_query.py - 加密面板交互查询 CLI (v1)
================================================================
"更好的查数据": 不重跑回测, 直接对 data/weekly_adjclose_crypto50.csv 做探查。
纯标准库, 任何环境可跑。

子命令:
  show <COIN> [--n 12]              最近 n 周收盘价
  corr <A> <B>                     日期对齐 Pearson 相关 + beta (PITFALLS §4 防错对齐)
  drawdown <COIN> [--start DATE]   最大回撤 / 谷底 / 恢复
  gaps <COIN>                      上市前留空 vs 中途缺口
  coverage [--panel PATH]          每币非空周数 / 总周数

用法:
  python crypto_query.py show BTC --n 10
  python crypto_query.py corr BTC ETH
  python crypto_query.py corr TRB BTC
  python crypto_query.py drawdown SOL --start 2020-01-01
  python crypto_query.py gaps TRB
  python crypto_query.py coverage
"""
import os
import sys
import csv
import math
import argparse
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
DEFAULT_PANEL = os.path.join(DATA, 'weekly_adjclose_crypto50.csv')


def _load_panel(path):
    """返回 (dates, coins, table) ; table[coin] = {date: close(float)}"""
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return [], [], {}
    header = rows[0]
    coins = header[1:]
    table = {c: {} for c in coins}
    dates = []
    for r in rows[1:]:
        d = r[0]
        dates.append(d)
        for i, c in enumerate(coins):
            v = r[i + 1].strip()
            if v:
                try:
                    table[c][d] = float(v)
                except ValueError:
                    pass
    return dates, coins, table


def _returns(table, coin, start=None):
    """按日期升序返回 (dates, simple returns)。"""
    items = sorted((k, v) for k, v in table[coin].items())
    if start:
        items = [(d, p) for d, p in items if d >= start]
    rets = []
    ds = []
    for i in range(1, len(items)):
        p0, p1 = items[i - 1][1], items[i][1]
        if p0 > 0:
            rets.append(p1 / p0 - 1.0)
            ds.append(items[i][0])
    return ds, rets


def cmd_show(args, panel):
    dates, coins, table = panel
    coin = args.coin.upper()
    if coin not in table:
        print(f"[错误] 面板无 {coin}; 可用: {', '.join(coins[:20])}...")
        return
    series = sorted(table[coin].items())
    if args.start:
        series = [(d, p) for d, p in series if d >= args.start]
    tail = series[-args.n:]
    print(f"{coin}  最近 {len(tail)} 周 (共 {len(series)} 周):")
    for d, p in tail:
        print(f"  {d}  {p:,.4f}")


def cmd_corr(args, panel):
    """日期对齐 Pearson + beta (PITFALLS §4: 取公共日期交集, 对收益序列算, 绝不按索引对齐)。"""
    dates, coins, table = panel
    a, b = args.a.upper(), args.b.upper()
    for s in (a, b):
        if s not in table:
            print(f"[错误] 面板无 {s}")
            return
    # 用对齐后的 (date, ret) 取日期交集, 避免两币上市日不同导致的索引错位
    da, ra = _aligned(table, a)
    db, rb = _aligned(table, b)
    ra_map = dict(zip(da, ra))
    rb_map = dict(zip(db, rb))
    common = sorted(set(ra_map) & set(rb_map))
    if len(common) < 3:
        print(f"[警告] {a}/{b} 公共周不足 ({len(common)}), 无法可靠计算相关")
        return
    xa = [ra_map[d] for d in common]
    xb = [rb_map[d] for d in common]
    corr = _pearson(xa, xb)
    beta = _cov(xa, xb) / _var(xb) if _var(xb) > 0 else float('nan')
    same = sum(1 for u, v in zip(xa, xb) if u * v > 0)
    print(f"{a} vs {b}  公共周={len(common)}")
    print(f"  Pearson r = {corr:.4f}")
    print(f"  beta({a} on {b}) = {beta:.4f}")
    print(f"  同向周占比 = {same / len(common):.1%}")


def _aligned(table, coin):
    """返回 (dates, returns) 按日期升序, 仅含有效收益。"""
    items = sorted(table[coin].items())
    ds, rs = [], []
    for i in range(1, len(items)):
        p0, p1 = items[i - 1][1], items[i][1]
        if p0 > 0:
            rs.append(p1 / p0 - 1.0)
            ds.append(items[i][0])
    return ds, rs


def _mean(x):
    return sum(x) / len(x)


def _var(x):
    m = _mean(x)
    return sum((v - m) ** 2 for v in x) / (len(x) - 1)


def _cov(x, y):
    m, n = _mean(x), _mean(y)
    return sum((u - m) * (v - n) for u, v in zip(x, y)) / (len(x) - 1)


def _pearson(x, y):
    sx, sy = _var(x), _var(y)
    if sx <= 0 or sy <= 0:
        return float('nan')
    return _cov(x, y) / math.sqrt(sx * sy)


def cmd_drawdown(args, panel):
    dates, coins, table = panel
    coin = args.coin.upper()
    if coin not in table:
        print(f"[错误] 面板无 {coin}")
        return
    series = sorted((k, v) for k, v in table[coin].items() if (not args.start or k >= args.start))
    if len(series) < 2:
        print("[警告] 数据不足")
        return
    # 第一遍: 找最大回撤 + 谷底 + 谷前峰值
    peak = series[0][1]
    peak_date = series[0][0]
    max_dd = 0.0
    trough = None
    peak_before = None
    peak_before_date = None
    for d, p in series:
        if p > peak:
            peak = p
            peak_date = d
        dd = p / peak - 1.0
        if dd < max_dd:
            max_dd = dd
            trough = (d, p)
            peak_before = peak
            peak_before_date = peak_date
    # 第二遍: 仅从谷底之后找首次回到谷前峰值的日期
    recovered = None
    if trough:
        for d, p in series:
            if d > trough[0] and p >= peak_before:
                recovered = d
                break
    print(f"{coin} 回撤分析 ({series[0][0]} ~ {series[-1][0]}):")
    print(f"  最大回撤 = {max_dd:.2%}  (谷底 {trough[0]} @ {trough[1]:,.4f})")
    print(f"  该谷顶峰值 = {peak_before:,.4f} @ {peak_before_date}")
    if recovered:
        print(f"  创新高恢复日 = {recovered}")
    else:
        print(f"  截至末日未恢复 (末值 {series[-1][1]:,.4f})")


def cmd_gaps(args, panel):
    dates, coins, table = panel
    coin = args.coin.upper()
    if coin not in table:
        print(f"[错误] 面板无 {coin}")
        return
    all_dates = dates
    present = set(table[coin].keys())
    first = min(present) if present else None
    last = max(present) if present else None
    # 上市前留空
    pre = [d for d in all_dates if d < first] if first else []
    # 中途缺口 (面板有日期但该币为空)
    mid = [d for d in all_dates if d >= first and d <= last and d not in present] if first else []
    print(f"{coin}: 非空周 {len(present)} / 总周 {len(all_dates)}")
    print(f"  首值 {first}  末值 {last}")
    print(f"  上市前留空周 = {len(pre)} (正常, 交易所无数据)")
    print(f"  中途缺口周 = {len(mid)}" + (f" 示例: {mid[:8]}" if mid else " (无, 连续)"))


def cmd_coverage(args, panel):
    dates, coins, table = panel
    total = len(dates)
    print(f"面板覆盖度 (总周 {total}):")
    for c in coins:
        n = len(table[c])
        flag = "  ⚠上市晚" if n < total * 0.5 else ""
        print(f"  {c:8} {n:5}/{total}  {n/total:6.1%}{flag}")


def main():
    ap = argparse.ArgumentParser(description="加密面板查询 CLI")
    ap.add_argument('--panel', default=DEFAULT_PANEL, help='面板 CSV 路径')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('show'); p.add_argument('coin'); p.add_argument('--n', type=int, default=12); p.add_argument('--start', default=None)
    p = sub.add_parser('corr'); p.add_argument('a'); p.add_argument('b')
    p = sub.add_parser('drawdown'); p.add_argument('coin'); p.add_argument('--start', default=None)
    p = sub.add_parser('gaps'); p.add_argument('coin')
    p = sub.add_parser('coverage')

    args = ap.parse_args()
    panel = _load_panel(args.panel)
    if not panel[0]:
        print(f"[错误] 面板为空或无法读取: {args.panel}")
        sys.exit(1)
    {'show': cmd_show, 'corr': cmd_corr, 'drawdown': cmd_drawdown,
     'gaps': cmd_gaps, 'coverage': cmd_coverage}[args.cmd](args, panel)


if __name__ == '__main__':
    main()
