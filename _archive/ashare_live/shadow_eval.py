"""
shadow_eval.py - AI shadow 模式 A/B 评估框架 (v1.0)

目的:
  ai_score 在 shadow 模式下会计算 AI 乘数但不改变实际排序。
  本模块每次 shadow 运行时记录"规则排序" vs "AI调整排序"的快照,
  后续可计算两组的前N名等权组合前向收益, 量化 AI 是否真加分。

  这是 shadow->active 晋升的数据基础: 没有 A/B 证据, 就不该开 live。

数据流:
  1. ai_score.augment() shadow 模式 -> shadow_eval.record()
  2. 快照存入 records/shadow_eval_snapshots.jsonl
  3. python shadow_eval.py evaluate --horizon 20
     -> 对每条快照, 拉 horizon 日前的 top-N 等权前向收益
     -> 对比 rule_top vs ai_top 的平均收益
  4. python shadow_eval.py report
     -> 汇总所有已评估快照, 输出 A/B 对比报告

快照格式 (records/shadow_eval_snapshots.jsonl):
  {
    "ts": "2026-08-07 14:30:00",
    "tag": "defensive",
    "rule_top": [{"code":"600036","score":0.85}, ...],
    "ai_top": [{"code":"601398","score":0.88,"multiplier":1.15}, ...],
    "overlap": ["600036"],          // 两组都选中的
    "ai_only": ["601398"],          // 仅 AI 选中的
    "rule_only": ["600519"],        // 仅规则选中的
    "evaluated": false,             // evaluate 后置 true
    "eval": null                    // evaluate 后填入结果
  }

用法:
  # 由 ai_score.augment() 自动调用
  from shadow_eval import record
  record(tag, rule_ranking, ai_ranking, top_n=3)

  # 手动评估
  python shadow_eval.py evaluate --horizon 20
  python shadow_eval.py report
  python shadow_eval.py status
"""
import os
import sys
import json
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
RECORD_ROOT = os.path.join(HERE, "records")
SNAPSHOT_FILE = os.path.join(RECORD_ROOT, "shadow_eval_snapshots.jsonl")


def _ensure():
    os.makedirs(RECORD_ROOT, exist_ok=True)


def record(tag, rule_ranking, ai_ranking, top_n=3):
    """
    记录一条 shadow 评估快照。

    参数:
      tag: "defensive" / "offensive"
      rule_ranking: 规则评分排序后的候选列表 (已含 final_score)
      ai_ranking: AI 乘数调整后排序的候选列表 (已含 ai_adjusted_score)
      top_n: 取前N名做对比 (默认3, 对应选股 top3)

    快照会在 evaluate 时被回填评估结果。
    """
    _ensure()
    rule_top = [{"code": d["code"], "name": d.get("name", ""),
                 "score": d.get("final_score", 0)} for d in rule_ranking[:top_n]]
    ai_top = [{"code": d["code"], "name": d.get("name", ""),
               "score": d.get("ai_adjusted_score", d.get("final_score", 0)),
               "multiplier": d.get("ai_multiplier", 1.0)} for d in ai_ranking[:top_n]]

    rule_codes = {d["code"] for d in rule_top}
    ai_codes = {d["code"] for d in ai_top}

    snapshot = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "tag": tag,
        "top_n": top_n,
        "rule_top": rule_top,
        "ai_top": ai_top,
        "overlap": sorted(rule_codes & ai_codes),
        "ai_only": sorted(ai_codes - rule_codes),
        "rule_only": sorted(rule_codes - ai_codes),
        "evaluated": False,
        "eval": None,
    }

    with open(SNAPSHOT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")

    changed = len(ai_codes - rule_codes) + len(rule_codes - ai_codes)
    if changed > 0:
        print(f"  [shadow_eval] 快照已存: rule_top={[d['code'] for d in rule_top]} "
              f"ai_top={[d['code'] for d in ai_top]} "
              f"差异={changed}只")
    return snapshot


def _load_snapshots():
    """加载所有快照。返回 list。"""
    if not os.path.exists(SNAPSHOT_FILE):
        return []
    out = []
    with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def _save_snapshots(snapshots):
    """全量覆写快照文件。"""
    _ensure()
    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        for s in snapshots:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


def _forward_return(code, start_date, horizon_days):
    """
    计算某标的从 start_date 起 horizon_days 个交易日的前向收益(%)。
    返回 (return_pct, error_msg)。error_msg 非空时 return_pct 为 None。
    """
    try:
        import market_data as md
        kl = md.get_kline(code, "day", 260)
    except Exception as e:
        return None, f"行情获取失败: {e}"
    if not kl:
        return None, f"{code} 无K线"

    # 找 start_date 当天或之前最近的K线作为入场
    entry_idx = None
    for i in range(len(kl) - 1, -1, -1):
        if kl[i]["date"] <= start_date:
            entry_idx = i
            break
    if entry_idx is None:
        entry_idx = 0

    exit_idx = entry_idx + horizon_days
    if exit_idx >= len(kl):
        exit_idx = len(kl) - 1

    entry_c = kl[entry_idx]["close"]
    exit_c = kl[exit_idx]["close"]
    if entry_c <= 0:
        return None, f"{code} 入场价异常"

    ret = (exit_c / entry_c - 1) * 100
    return ret, None


def evaluate(horizon=20):
    """
    对所有未评估的快照计算前向收益。

    参数:
      horizon: 前向收益天数(交易日), 默认20(约1个月)

    逻辑:
      对每条快照:
        - rule_top 等权组合前向收益 = mean(各标的前向收益)
        - ai_top 等权组合前向收益 = mean(各标的前向收益)
        - 记录差额 ai_return - rule_return
    """
    snapshots = _load_snapshots()
    if not snapshots:
        print("  (无快照, 需先在 shadow 模式运行 ai_score)")
        return

    pending = [s for s in snapshots if not s.get("evaluated")]
    if not pending:
        print(f"  所有 {len(snapshots)} 条快照已评估, 用 --force 重新评估")
        return

    print(f"  评估 {len(pending)} 条未评估快照 (horizon={horizon}交易日)...")
    today = datetime.now().strftime("%Y-%m-%d")
    evaluated_count = 0

    for s in snapshots:
        if s.get("evaluated"):
            continue

        start_date = s["date"]
        # 如果快照日期距今不足 horizon 个交易日, 跳过(前向窗口未满)
        # 简化判断: 日期差 < horizon * 1.5 自然日则跳过
        try:
            d_start = datetime.strptime(start_date, "%Y-%m-%d")
            d_now = datetime.now()
            calendar_days = (d_now - d_start).days
            if calendar_days < int(horizon * 1.4):
                print(f"    跳过 {s['ts']} (距今{calendar_days}天, 不足{horizon}交易日窗口)")
                continue
        except Exception:
            pass

        # 计算 rule_top 等权前向收益
        rule_returns = []
        for d in s["rule_top"]:
            r, err = _forward_return(d["code"], start_date, horizon)
            if err:
                print(f"    {s['ts']} rule {d['code']}: {err}")
            else:
                rule_returns.append(r)

        # 计算 ai_top 等权前向收益
        ai_returns = []
        for d in s["ai_top"]:
            r, err = _forward_return(d["code"], start_date, horizon)
            if err:
                print(f"    {s['ts']} ai {d['code']}: {err}")
            else:
                ai_returns.append(r)

        if not rule_returns or not ai_returns:
            print(f"    {s['ts']} 行情不足, 跳过")
            continue

        rule_avg = sum(rule_returns) / len(rule_returns)
        ai_avg = sum(ai_returns) / len(ai_returns)
        diff = ai_avg - rule_avg

        s["evaluated"] = True
        s["eval"] = {
            "evaluated_date": today,
            "horizon": horizon,
            "rule_avg_return": round(rule_avg, 2),
            "ai_avg_return": round(ai_avg, 2),
            "diff": round(diff, 2),
            "ai_wins": diff > 0,
            "rule_returns": [round(r, 2) for r in rule_returns],
            "ai_returns": [round(r, 2) for r in ai_returns],
        }
        evaluated_count += 1
        marker = "AI胜" if diff > 0 else ("规则胜" if diff < 0 else "持平")
        print(f"    {s['ts']} {s['tag']}: rule={rule_avg:+.2f}% ai={ai_avg:+.2f}% "
              f"diff={diff:+.2f}% [{marker}]")

    _save_snapshots(snapshots)
    print(f"  评估完成, 已评估 {evaluated_count} 条")


def report():
    """输出 A/B 对比报告。"""
    snapshots = _load_snapshots()
    if not snapshots:
        print("  (无快照)")
        return

    evaluated = [s for s in snapshots if s.get("evaluated") and s.get("eval")]
    if not evaluated:
        print(f"  共 {len(snapshots)} 条快照, 但无已评估记录")
        print("  先运行: python shadow_eval.py evaluate --horizon 20")
        return

    total = len(evaluated)
    ai_wins = sum(1 for s in evaluated if s["eval"]["ai_wins"])
    rule_wins = total - ai_wins
    avg_diff = sum(s["eval"]["diff"] for s in evaluated) / total

    # 按 tag 分组
    by_tag = {}
    for s in evaluated:
        tag = s.get("tag", "unknown")
        by_tag.setdefault(tag, []).append(s)

    print(f"  Shadow A/B 评估报告")
    print(f"  {'='*50}")
    print(f"  总快照: {len(snapshots)} | 已评估: {total} | 待评估: {len(snapshots) - total}")
    print(f"  AI 胜: {ai_wins} | 规则胜: {rule_wins} | AI胜率: {ai_wins/total*100:.1f}%")
    print(f"  平均超额收益(AI-规则): {avg_diff:+.2f}%")
    print(f"  {'='*50}")

    for tag, subset in sorted(by_tag.items()):
        t = len(subset)
        aw = sum(1 for s in subset if s["eval"]["ai_wins"])
        ad = sum(s["eval"]["diff"] for s in subset) / t
        print(f"  [{tag}] 共{t}条 AI胜{aw} AI胜率{aw/t*100:.1f}% 平均超额{ad:+.2f}%")

    print(f"  {'='*50}")
    print(f"  详细记录:")
    for s in evaluated[-10:]:  # 最近10条
        e = s["eval"]
        marker = "AI胜" if e["ai_wins"] else "规则胜"
        print(f"    {s['ts']} [{s['tag']}] "
              f"rule={e['rule_avg_return']:+.2f}% ai={e['ai_avg_return']:+.2f}% "
              f"diff={e['diff']:+.2f}% [{marker}]")


def status():
    """查看评估进度。"""
    snapshots = _load_snapshots()
    if not snapshots:
        print("  (无快照, 需先在 shadow 模式运行 ai_score)")
        return
    total = len(snapshots)
    evaluated = len([s for s in snapshots if s.get("evaluated")])
    pending = total - evaluated
    print(f"  Shadow 评估进度")
    print(f"     总快照: {total}")
    print(f"     已评估: {evaluated}")
    print(f"     待评估: {pending}")
    if pending > 0:
        print(f"     运行 'python shadow_eval.py evaluate --horizon 20' 评估待处理快照")


# ---------------------------------------------------------------- CLI

def main():
    import argparse
    ap = argparse.ArgumentParser(description="AI shadow A/B 评估框架")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ev = sub.add_parser("evaluate")
    ev.add_argument("--horizon", type=int, default=20, help="前向收益天数(交易日), 默认20")
    ev.add_argument("--force", action="store_true", help="强制重新评估所有快照")
    ev.set_defaults(func=lambda a: _cmd_evaluate(a))

    sub.add_parser("report").set_defaults(func=lambda a: report())
    sub.add_parser("status").set_defaults(func=lambda a: status())

    args = ap.parse_args()
    args.func(args)


def _cmd_evaluate(args):
    if args.force:
        snapshots = _load_snapshots()
        for s in snapshots:
            s["evaluated"] = False
            s["eval"] = None
        _save_snapshots(snapshots)
        print("  已重置所有快照评估状态")
    evaluate(horizon=args.horizon)


if __name__ == "__main__":
    main()
