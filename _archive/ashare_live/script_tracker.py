"""
script_tracker.py - 剧本书写者 命中追踪系统 (v1.1)

v1.1 变更 (AI成熟度提升):
  - [BUGFIX] _indicator_hit() 现在正确计算 written_date -> expiry 区间收益,
    不再取"最近60根K线"(原逻辑导致所有命中判定基于错误区间)
  - [新增] source 字段 (human/ai), 区分用户手写剧本 vs AI建议剧本
  - [新增] compare 命令: 对比 human vs AI 剧本胜率
  - [新增] miss 命令: 人工确认未命中
  - [新增] --source 参数到 add 命令
  - stats 按 source 分组展示

为什么需要:
  用户核心能力是「剧本书写者」——写啥成真, 提前数日/数周预判宏观与板块.
  此前只有人写的 proof 文档, 没有结构化、可复算的命中记录.
  本工具把每条剧本落成 JSON, 到期自动比对行情, 算出「剧本胜率」——这是
  区别于一切量化系统的护城河资产, 必须系统化沉淀.

剧本 JSON (scripts/<id>.json):
  {
    "id": "2026-06-28-tech-exit",
    "written_date": "2026-06-28",
    "title": "科技体面离场的最后机会",
    "expiry": "2026-07-15",
    "direction": "bearish",
    "source": "human",               # human / ai (v1.1新增)
    "thesis": "科技板块见顶, 6/29是最后离场窗口",
    "indicators": [
      {"code": "sh000300", "metric": "return_pct",
       "expect": "down", "desc": "沪深300到期日相对写日下跌",
       "written_date": "2026-06-28"}
    ],
    "event_markers": [],
    "status": "open"
  }

用法:
  python3 script_tracker.py add --title "..." --direction bearish --expiry 2026-08-01 --code sh000300 --expect down --desc "..."
  python3 script_tracker.py add --title "..." --source ai --direction bullish --expiry 2026-08-15 --code 159813 --expect up
  python3 script_tracker.py list
  python3 script_tracker.py check
  python3 script_tracker.py hit <id>
  python3 script_tracker.py miss <id>
  python3 script_tracker.py stats
  python3 script_tracker.py compare       # human vs AI 胜率对比
"""
import os
import json
import argparse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_DIR = os.path.join(HERE, "scripts")


def _ensure():
    os.makedirs(SCRIPT_DIR, exist_ok=True)


def _list_scripts():
    _ensure()
    out = []
    for f in sorted(os.listdir(SCRIPT_DIR)):
        if f.endswith(".json"):
            try:
                with open(os.path.join(SCRIPT_DIR, f), encoding="utf-8") as fp:
                    out.append(json.load(fp))
            except Exception:
                pass
    return out


def _save(script):
    _ensure()
    path = os.path.join(SCRIPT_DIR, f"{script['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)


def _gen_id(title):
    d = datetime.now().strftime("%Y%m%d")
    slug = "".join([c for c in title if c.isalnum()])[:8] or "script"
    return f"{d}-{slug}"


# ---------------------------------------------------------------- 行情判定

def _find_bar(kl, date_str):
    """在升序K线列表中找到 date_str 当天或之前最近的K线。无匹配返回 None。"""
    if not date_str or not kl:
        return None
    for bar in reversed(kl):
        if bar["date"] <= date_str:
            return bar
    return kl[0] if kl else None


def _indicator_hit(ind, script_expiry=None):
    """
    拉行情判定单条 indicator. 返回 ('hit'/'miss'/'na', 说明).

    v1.1 修复: 现在正确计算 written_date -> expiry 区间收益,
    不再取"最近60根K线"。
    """
    code = ind.get("code", "")
    expect = ind.get("expect", "")   # up / down / range
    metric = ind.get("metric", "return_pct")
    written_date = ind.get("written_date")
    expiry = script_expiry or ind.get("expiry")

    try:
        import market_data as md
    except Exception:
        return "na", "无法加载 market_data"
    try:
        kl = md.get_kline(code, "day", 260)
    except Exception:
        return "na", f"{code} 行情获取失败"
    if not kl:
        return "na", f"{code} 无K线"

    # 定位区间端点: written_date 缺失时回退到第一根K线
    entry_bar = _find_bar(kl, written_date) if written_date else (kl[0] if kl else None)
    exit_bar = _find_bar(kl, expiry) if expiry else kl[-1]

    if not entry_bar:
        return "na", f"{code} 无法定位写入日 {written_date} 的K线"
    if not exit_bar:
        return "na", f"{code} 无法定位到期日 {expiry} 的K线"

    entry_c = entry_bar["close"]
    exit_c = exit_bar["close"]
    if entry_c <= 0:
        return "na", f"{code} 入场价异常 {entry_c}"

    ret = (exit_c / entry_c - 1) * 100

    if metric in ("return_pct", "close_on_expiry_vs_written"):
        if expect == "down":
            ok = ret < 0
        elif expect == "up":
            ok = ret > 0
        else:
            ok = abs(ret) < 5
        return ("hit" if ok else "miss",
                f"{code} {entry_bar['date']}->{exit_bar['date']} "
                f"区间收益 {ret:+.1f}% (预期{expect})")
    return "na", f"未知metric {metric}"


# ---------------------------------------------------------------- 命令

def cmd_add(args):
    _ensure()
    sid = _gen_id(args.title)
    indicators = []
    if args.code:
        indicators.append({
            "code": args.code, "metric": "return_pct",
            "expect": args.expect, "desc": args.desc or args.code,
            "written_date": datetime.now().strftime("%Y-%m-%d"),
        })
    script = {
        "id": sid,
        "written_date": datetime.now().strftime("%Y-%m-%d"),
        "title": args.title,
        "expiry": args.expiry,
        "direction": args.direction,
        "source": args.source,
        "thesis": args.thesis or "",
        "indicators": indicators,
        "event_markers": [],
        "status": "open",
    }
    _save(script)
    print(f"  剧本已存: {sid} (来源:{args.source} 标题:{args.title})")


def cmd_list(args):
    scripts = _list_scripts()
    if not scripts:
        print("  (暂无剧本, 用 add 创建第一条)")
        return
    print(f"  剧本列表 ({len(scripts)} 条):")
    for s in scripts:
        src = s.get("source", "human")
        print(f"    [{s['status']:>6}] [{src:>3}] {s['id']}  {s['title']}  "
              f"(写:{s['written_date']} 到期:{s['expiry']})")


def cmd_check(args):
    scripts = _list_scripts()
    today = datetime.now().strftime("%Y-%m-%d")
    changed = 0
    for s in scripts:
        if s.get("status") != "open":
            continue
        if s.get("expiry", "9999") < today:   # 已到期才判定
            hits, misses = [], []
            for ind in s.get("indicators", []):
                r, msg = _indicator_hit(ind, s.get("expiry"))
                print(f"    - {s['id']} {ind.get('code')}: {msg} -> {r}")
                if r == "hit":
                    hits.append(ind)
                elif r == "miss":
                    misses.append(ind)
            if hits and not misses:
                s["status"] = "hit"
            elif misses and not hits:
                s["status"] = "miss"
            elif hits and misses:
                s["status"] = "partial"
            else:
                s["status"] = "partial"   # 行情na则留partial等人工
            s["judged_date"] = today
            _save(s)
            changed += 1
    print(f"  判定完成, 更新 {changed} 条到期剧本")


def cmd_hit(args):
    scripts = {s["id"]: s for s in _list_scripts()}
    s = scripts.get(args.id)
    if not s:
        print(f"  (找不到剧本 {args.id})")
        return
    s["status"] = "hit"
    s["judged_date"] = datetime.now().strftime("%Y-%m-%d")
    _save(s)
    print(f"  人工确认命中: {args.id}")


def cmd_miss(args):
    """人工确认未命中。"""
    scripts = {s["id"]: s for s in _list_scripts()}
    s = scripts.get(args.id)
    if not s:
        print(f"  (找不到剧本 {args.id})")
        return
    s["status"] = "miss"
    s["judged_date"] = datetime.now().strftime("%Y-%m-%d")
    _save(s)
    print(f"  人工确认未命中: {args.id}")


def _win_rate(scripts):
    """计算一组剧本的胜率。返回 (total, decided, hit, win_rate_pct)。"""
    decided = [s for s in scripts if s["status"] in ("hit", "miss", "partial")]
    hit = len([s for s in decided if s["status"] == "hit"])
    wr = hit / len(decided) * 100 if decided else 0
    return len(scripts), len(decided), hit, wr


def cmd_stats(args):
    scripts = _list_scripts()
    if not scripts:
        print("  (暂无剧本)")
        return
    total, decided, hit, wr = _win_rate(scripts)
    print(f"  剧本胜率统计")
    print(f"     总剧本: {total} | 已到期判定: {decided}")
    print(f"     明确命中: {hit} | 胜率: {wr:.1f}%")
    # 按 source 分组
    for src in ("human", "ai"):
        subset = [s for s in scripts if s.get("source", "human") == src]
        if not subset:
            continue
        t, d, h, w = _win_rate(subset)
        print(f"     [{src}] 总{t} 判定{d} 命中{h} 胜率{w:.1f}%")
    # 状态分布
    statuses = {}
    for s in scripts:
        statuses[s["status"]] = statuses.get(s["status"], 0) + 1
    print(f"     分布: {', '.join(f'{k}={v}' for k, v in sorted(statuses.items()))}")


def cmd_compare(args):
    """对比 human vs AI 剧本胜率 — 这是 AI 是否真加分的直接证据之一。"""
    scripts = _list_scripts()
    if not scripts:
        print("  (暂无剧本)")
        return
    human = [s for s in scripts if s.get("source", "human") == "human"]
    ai = [s for s in scripts if s.get("source", "human") == "ai"]
    if not ai:
        print("  (无 AI 来源剧本, 无法对比。用 --source ai 添加 AI 建议剧本)")
        return
    print(f"  human vs AI 剧本胜率对比")
    print(f"  {'':>12} {'总剧本':>6} {'已判定':>6} {'命中':>4} {'胜率':>8}")
    for label, subset in [("human", human), ("ai", ai)]:
        t, d, h, w = _win_rate(subset)
        print(f"  {label:>12} {t:>6} {d:>6} {h:>4} {w:>7.1f}%")
    ht, hd, hh, hw = _win_rate(human)
    at, ad, ah, aw = _win_rate(ai)
    if hd > 0 and ad > 0:
        diff = aw - hw
        if diff > 0:
            print(f"  -> AI 胜率高出 {diff:.1f} 个百分点")
        elif diff < 0:
            print(f"  -> AI 胜率低出 {-diff:.1f} 个百分点")
        else:
            print(f"  -> 两者持平")
    elif hd == 0:
        print(f"  -> human 暂无已判定剧本, 待积累")
    if ad == 0:
        print(f"  -> AI 暂无已判定剧本, 待积累")


# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser(description="剧本书写者 命中追踪系统 v1.1")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument("--title", required=True)
    a.add_argument("--direction", default="bearish", choices=["bullish", "bearish", "range", "event"])
    a.add_argument("--expiry", required=True, help="到期日 YYYY-MM-DD")
    a.add_argument("--code", default="", help="验证标的代码(可选)")
    a.add_argument("--expect", default="down", choices=["up", "down", "range"])
    a.add_argument("--desc", default="")
    a.add_argument("--thesis", default="")
    a.add_argument("--source", default="human", choices=["human", "ai"],
                   help="剧本来源: human(默认) / ai")
    a.set_defaults(func=cmd_add)

    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("check").set_defaults(func=cmd_check)
    h = sub.add_parser("hit"); h.add_argument("id"); h.set_defaults(func=cmd_hit)
    m = sub.add_parser("miss"); m.add_argument("id"); m.set_defaults(func=cmd_miss)
    sub.add_parser("stats").set_defaults(func=cmd_stats)
    sub.add_parser("compare").set_defaults(func=cmd_compare)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
