# -*- coding: utf-8 -*-
"""
QA-01 独立回归验证: IPO 伪迹拦截 / 真实大涨保留
======================================================
由 QA 独立编写, 不复用工程师的 _diag_ipo_artifacts.py / _sweep_firewall.py。

验证项:
  A. 扫描 data/ashare_weekly_em/ 全部 csv, 列出单周 > +50% 跳变 (code, date, chg)
     - 同时给出「面板口径」(引擎真正消费的序列) 与「原始收盘口径」
  B. 判定每处跳变是 IPO 伪迹(上市后第 1~4 根) 还是 真实大涨(上市后 >=100 根)
  C. 在 10y 窗口逐周调用 momentum_select(lb=26, plain, trend_filter=True),
     统计每个跳变代码在「跳变后 26 周打分窗口内」是否曾进 Top5
  D. 用旧参数(MAX_WEEKLY_JUMP=1.6 / 关闭冷却期)复跑同一逻辑, 给出 修复前 vs 修复后 对照
"""
import os
import sys
import csv
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import backtest_engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(BT))
PANEL = os.path.join(E.DATA, "ashare_panel_close_em.csv")
WK = os.path.join(E.DATA, "ashare_weekly_em")

WIN_START = "2016-08-05"
JUMP_THR = 0.50
LOOKBACK = 26

# 主理人点名的两组标的
IPO_EXPECT = ["300750", "603259", "603986", "603501", "300502",
              "300760", "002821", "601021", "601985"]
REAL_EXPECT = ["300059", "300033", "300308"]


def sep(t):
    print("\n" + "=" * 96)
    print(t)
    print("=" * 96)


# ---------------- A. 扫描原始周线文件 ----------------
sep("A. 扫描 data/ashare_weekly_em/ 单周 > +50% 跳变")

# 注意: eastmoney_hfq_rebuild.fetch_one 请求 fields2=f51,f53,f55,...
# (日期,收盘,最低,成交量,成交额,振幅,涨跌幅), 但按 open/close/high/low 落盘,
# 导致列标签错位: 文件里 "open" 列 = 真·收盘, "close" 列 = 真·最低, "amount" 列 = 真·涨跌幅。
# build_panel 读的是 row["close"], 所以面板 = 真·最低。两种口径都扫, 交叉验证。
raw = {}          # code -> [(date, panel_close_used, true_close)]
for fn in sorted(os.listdir(WK)):
    if not fn.endswith(".csv"):
        continue
    code = fn[:-4]
    rows = []
    with open(os.path.join(WK, fn), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                rows.append((r["date"], float(r["close"]), float(r["open"])))
            except (ValueError, KeyError, TypeError):
                continue
    raw[code] = rows

print(f"读入 {len(raw)} 个周线文件")


def scan(idx, label):
    hits = []
    for code, rows in raw.items():
        for k in range(1, len(rows)):
            a, b = rows[k - 1][idx], rows[k][idx]
            if a and a > 0 and b and b > 0:
                chg = b / a - 1.0
                if chg > JUMP_THR:
                    hits.append((code, rows[k][0], chg, k))
    hits.sort(key=lambda x: -x[2])
    print(f"\n[{label}] > +{JUMP_THR:.0%} 跳变共 {len(hits)} 处")
    return hits


hits_panel = scan(1, "面板口径 (引擎实际消费, = 文件 close 列)")
hits_true = scan(2, "原始收盘口径 (= 文件 open 列)")

# 每只票的上市索引 (原始周线文件的第 0 行 = 上市首周)
listed_len = {c: len(rs) for c, rs in raw.items()}

print(f"\n{'代码':<9}{'日期':<13}{'面板涨幅':>10}{'上市后第N根':>13}  判定")
print("-" * 96)
verdict = {}
for code, date, chg, k in hits_panel:
    kind = "IPO伪迹" if k <= 6 else ("真实大涨" if k >= 100 else "待定")
    verdict.setdefault(code, []).append((date, chg, k, kind))
    print(f"{code:<9}{date:<13}{chg:>9.1%}{k:>13}  {kind}")

# ---------------- B. 面板加载 + pool_meta ----------------
sep("B. 加载面板 & 候选池")
dates, codes, series = E.load_panel(PANEL)
cfg = json.load(open(os.path.join(ROOT, "strategy_config.json"), encoding="utf-8"))
pool_meta = {}
for p in cfg.get("auto_select", {}).get("candidate_pool", []):
    if p.get("industry") not in E.OFFENSE_BLACKLIST:
        pool_meta[p["code"]] = p
print(f"面板: {len(dates)} 周 {dates[0]} ~ {dates[-1]} | 代码 {len(codes)} 只")
print(f"候选池(剔黑名单后): {len(pool_meta)} 只")

i0 = next(i for i, d in enumerate(dates) if d >= WIN_START)
print(f"10y 窗口: i={i0} ({dates[i0]}) ~ i={len(dates)-1} ({dates[-1]}), 共 {len(dates)-i0} 周")

# 跳变代码 -> 面板索引位置
date2i = {d: i for i, d in enumerate(dates)}
jump_events = []   # (code, date, chg, panel_i)
for code, date, chg, k in hits_panel:
    if code in pool_meta and date in date2i:
        jump_events.append((code, date, chg, date2i[date]))
print(f"落在候选池内的跳变事件: {len(jump_events)} 处 "
      f"(涉及 {len({e[0] for e in jump_events})} 只票)")

# [QA 自查修正] 部分跳变(300033 2014-12-05 / 300059 2015-04-30 / 002179 2015-07-17 等)
# 早于 10y 窗口起点, 若只扫 10y 窗口会把它们误报成「被误伤」。
# 因此事件级判定用一个「全覆盖窗口」: 起点 = 最早跳变前 60 周, 保证每处跳变的
# 26 周影响区间都被真正评估过。10y 窗口仅用于统计整体 Top2 变化率。
i_scan = min([e[3] for e in jump_events] + [i0])
i_scan = max(60, i_scan - 60)
print(f"事件级全覆盖扫描窗口: i={i_scan} ({dates[i_scan]}) ~ {dates[-1]}, "
      f"共 {len(dates)-i_scan} 周")


# ---------------- C. 逐周跑 momentum_select ----------------
def run_sweep(tag):
    """返回 {i: [top5 codes]} 与 {code: set(命中周 i)}"""
    E._FIRST_LISTED_CACHE.clear()
    top5_by_i = {}
    hit_by_code = {}
    for i in range(i_scan, len(dates)):
        _, full = E.momentum_select(dates, series, pool_meta, i, LOOKBACK,
                                    use_tech=True, score_mode="plain",
                                    trend_filter=True)
        c5 = [c[0] for c in full]
        top5_by_i[i] = c5
        for c in c5:
            hit_by_code.setdefault(c, set()).add(i)
    n_weeks = len(dates) - i_scan
    n_sel = sum(1 for v in top5_by_i.values() if v)
    print(f"[{tag}] 扫描 {n_weeks} 周 ({dates[i_scan]}~{dates[-1]}), 其中 {n_sel} 周有候选; "
          f"共 {len(hit_by_code)} 只票曾进 Top5")
    return top5_by_i, hit_by_code


sep("C. 修复后 (当前代码) — 逐周 Top5 扫描")
print(f"参数: MIN_VALID_PRICE={E.MIN_VALID_PRICE} MAX_WEEKLY_JUMP={E.MAX_WEEKLY_JUMP} "
      f"MIN_WEEKLY_DROP={E.MIN_WEEKLY_DROP} IPO_SEASON_WEEKS={E.IPO_SEASON_WEEKS}")
after_top5, after_hits = run_sweep("修复后")

sep("D. 修复前 (旧参数: MAX_WEEKLY_JUMP=1.6, 冷却期关闭) — 逐周 Top5 扫描")
_bak = (E.MAX_WEEKLY_JUMP, E.IPO_SEASON_WEEKS)
E.MAX_WEEKLY_JUMP = 1.6
E.IPO_SEASON_WEEKS = -10 ** 9      # 等价于旧代码没有冷却期这道闸
print(f"参数: MAX_WEEKLY_JUMP={E.MAX_WEEKLY_JUMP} IPO_SEASON_WEEKS=(关闭)")
before_top5, before_hits = run_sweep("修复前")
E.MAX_WEEKLY_JUMP, E.IPO_SEASON_WEEKS = _bak


# ---------------- E. 判定 ----------------
def contaminated(hits, code, ji):
    """跳变发生在 i=ji, 其影响 26 周打分窗口 [ji, ji+26]; 该区间内是否进 Top5"""
    s = hits.get(code, set())
    return sorted(x for x in s if ji <= x <= ji + LOOKBACK)


sep("E. 伪迹拦截判定 (跳变后 26 周内是否进 Top5)")
print(f"{'代码':<9}{'跳变日':<13}{'涨幅':>8}{'第N根':>7}{'类型':<10}"
      f"{'修复前命中周':>14}{'修复后命中周':>14}  结论")
print("-" * 110)
fail_ipo, kept_real, lost_real = [], [], []
for code, date, chg, ji in sorted(jump_events, key=lambda x: (x[0], x[1])):
    k = next(kk for (d, c, kk, _t) in verdict[code] if d == date)
    kind = "IPO伪迹" if k <= 6 else ("真实大涨" if k >= 100 else "待定")
    b = contaminated(before_hits, code, ji)
    a = contaminated(after_hits, code, ji)
    if kind == "IPO伪迹":
        ok = (len(a) == 0)
        note = "OK 已拦截" if ok else "!! 仍漏网"
        if not ok:
            fail_ipo.append((code, date, a))
    else:
        ok = (len(a) > 0)
        note = "OK 仍保留" if ok else "!! 被误伤"
        (kept_real if ok else lost_real).append((code, date))
    print(f"{code:<9}{date:<13}{chg:>7.1%}{k:>7}{kind:<10}"
          f"{len(b):>14}{len(a):>14}  {note}")

sep("F. 结论汇总")
ipo_codes = {c for c, d, ch, ji in jump_events
             if next(kk for (dd, cc, kk, _t) in verdict[c] if dd == d) <= 6}
real_codes = {c for c, d, ch, ji in jump_events
              if next(kk for (dd, cc, kk, _t) in verdict[c] if dd == d) >= 100}
print(f"IPO 伪迹涉及票: {sorted(ipo_codes)}")
print(f"真实大涨涉及票: {sorted(real_codes)}")
print(f"\nIPO 伪迹漏网数: {len(fail_ipo)}  -> {'PASS 100% 拦截' if not fail_ipo else 'FAIL ' + repr(fail_ipo)}")
print(f"真实大涨保留: {len(kept_real)} 处 / 误伤: {len(lost_real)} 处 "
      f"-> {'PASS' if not lost_real else 'FAIL ' + repr(lost_real)}")

# 主理人点名标的: 10y 窗口内进 Top5 的周数
def n10(hits, c):
    return len([x for x in hits.get(c, ()) if x >= i0])


print(f"\n[10y 窗口 {dates[i0]}~{dates[-1]}] 点名标的进 Top5 周数")
print(f"{'代码':<10}{'类别':<10}{'修复前':>10}{'修复后':>10}{'差':>8}")
print("-" * 50)
for c in IPO_EXPECT:
    b, a = n10(before_hits, c), n10(after_hits, c)
    print(f"{c:<10}{'IPO伪迹':<10}{b:>10}{a:>10}{a-b:>+8}")
for c in REAL_EXPECT:
    b, a = n10(before_hits, c), n10(after_hits, c)
    print(f"{c:<10}{'真实':<10}{b:>10}{a:>10}{a-b:>+8}")

# 整体 Top1/Top2 变化率
diff_weeks = sum(1 for i in range(i0, len(dates))
                 if before_top5[i][:2] != after_top5[i][:2])
print(f"\n10y 窗口内 Top2 选股发生变化的周数: {diff_weeks} / {len(dates)-i0} "
      f"({diff_weeks/(len(dates)-i0):.1%})")

json.dump({"fail_ipo": fail_ipo, "lost_real": lost_real,
           "n_jump_events": len(jump_events),
           "diff_weeks": diff_weeks},
          open(os.path.join(HERE, "qa_01_result.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("\n[done] -> _qa/qa_01_result.json")
