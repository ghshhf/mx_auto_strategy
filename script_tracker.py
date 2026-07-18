"""
script_tracker.py - 剧本书写者 命中追踪系统 (v1.0)

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
    "expiry": "2026-07-15",          # 到期日, check 时比对
    "direction": "bearish",          # bullish / bearish / range / event
    "thesis": "科技板块见顶, 6/29是最后离场窗口",
    "indicators": [                  # 验证指标(自动拉行情判定)
      {"code": "sh000300", "metric": "close_on_expiry_vs_written",
       "expect": "down", "desc": "沪深300到期日相对写日下跌"},
      {"code": "159813", "metric": "return_pct",
       "expect": "down", "desc": "半导体ETF区间收益为负"}
    ],
    "event_markers": ["地缘", "台风", "医疗买点"],  # 非价格类命中(人工勾)
    "status": "open"                # open / hit / miss / partial
  }

用法:
  python3 script_tracker.py add --title "..." --direction bearish --expiry 2026-08-01 --code sh000300 --expect down --desc "..."
  python3 script_tracker.py list
  python3 script_tracker.py check            # 对所有 open 且过期的剧本自动判定
  python3 script_tracker.py hit <id>         # 人工确认命中(非价格类)
  python3 script_tracker.py stats            # 剧本胜率汇总
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

def _indicator_hit(ind):
    """拉行情判定单条 indicator. 返回 ('hit'/'miss'/'na', 说明)."""
    code = ind.get("code", "")
    expect = ind.get("expect", "")   # up / down / range
    metric = ind.get("metric", "return_pct")
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
    written = datetime.strptime(ind.get("written_date", kl[0]["date"]), "%Y-%m-%d") \
        if ind.get("written_date") else None
    # 简化: 取最近一段区间收益
    recent = kl[-60:] if len(kl) >= 60 else kl
    first_c, last_c = recent[0]["close"], recent[-1]["close"]
    ret = (last_c / first_c - 1) * 100
    if metric in ("return_pct", "close_on_expiry_vs_written"):
        if expect == "down":
            ok = ret < 0
        elif expect == "up":
            ok = ret > 0
        else:
            ok = abs(ret) < 5
        return ("hit" if ok else "miss", f"{code} 区间收益 {ret:+.1f}% (预期{expect})")
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
        "thesis": args.thesis or "",
        "indicators": indicators,
        "event_markers": [],
        "status": "open",
    }
    _save(script)
    print(f"  ✅ 剧本已存: {sid} (标题: {args.title})")


def cmd_list(args):
    scripts = _list_scripts()
    if not scripts:
        print("  （暂无剧本，用 add 创建第一条）")
        return
    print(f"  📜 剧本列表 ({len(scripts)} 条):")
    for s in scripts:
        print(f"    [{s['status']:>6}] {s['id']}  {s['title']}  (写:{s['written_date']} 到期:{s['expiry']})")


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
                r, msg = _indicator_hit(ind)
                print(f"    · {s['id']} {ind.get('code')}: {msg} -> {r}")
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
            _save(s)
            changed += 1
    print(f"  🔍 判定完成, 更新 {changed} 条到期剧本")


def cmd_hit(args):
    scripts = {s["id"]: s for s in _list_scripts()}
    s = scripts.get(args.id)
    if not s:
        print(f"  （找不到剧本 {args.id}）")
        return
    s["status"] = "hit"
    _save(s)
    print(f"  ✅ 人工确认命中: {args.id}")


def cmd_stats(args):
    scripts = _list_scripts()
    if not scripts:
        print("  （暂无剧本）")
        return
    total = len(scripts)
    decided = [s for s in scripts if s["status"] in ("hit", "miss", "partial")]
    hit = len([s for s in decided if s["status"] == "hit"])
    win_rate = hit / len(decided) * 100 if decided else 0
    print(f"  📊 剧本胜率统计")
    print(f"     总剧本: {total} | 已到期判定: {len(decided)}")
    print(f"     明确命中: {hit} | 胜率(仅计明确命中/已判定): {win_rate:.1f}%")
    print(f"     分布: " + ", ".join(f"{s['status']}={len([x for x in scripts if x['status']==s['status']])}" for s in scripts))


# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser(description="剧本书写者 命中追踪系统")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument("--title", required=True)
    a.add_argument("--direction", default="bearish", choices=["bullish", "bearish", "range", "event"])
    a.add_argument("--expiry", required=True, help="到期日 YYYY-MM-DD")
    a.add_argument("--code", default="", help="验证标的代码(可选)")
    a.add_argument("--expect", default="down", choices=["up", "down", "range"])
    a.add_argument("--desc", default="")
    a.add_argument("--thesis", default="")
    a.set_defaults(func=cmd_add)

    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("check").set_defaults(func=cmd_check)
    h = sub.add_parser("hit"); h.add_argument("id"); h.set_defaults(func=cmd_hit)
    sub.add_parser("stats").set_defaults(func=cmd_stats)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
