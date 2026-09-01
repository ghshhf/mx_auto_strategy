"""
ai_promotion_gate.py - AI shadow->active 晋升门槛检查 (v1.0)

目的:
  定义量化的晋升标准, 避免"感觉 AI 好用就开 live"的主观决策。
  只有当 shadow_eval 积累了足够样本且 AI 明确优于纯规则时, 才建议晋升。

门槛 (可在 strategy_config.json 的 ai_overlay.promotion_gate 配置):
  - min_samples: 最少已评估 shadow 快照数 (默认 20)
  - min_ai_win_rate: AI 超出的样本占比 (默认 55%)
  - min_avg_outperformance: AI 平均超额收益最低值 (默认 1.0%)
  - min_script_samples: AI 来源剧本最少已判定数 (默认 5, 从 script_tracker)
  - min_script_win_rate: AI 剧本最低胜率 (默认 50%)

晋升判定:
  全部门槛同时满足 -> 建议晋升 (输出 PROMOTE)
  任一不满足 -> 维持 shadow (输出 HOLD, 显示差距)

用法:
  python ai_promotion_gate.py check    # 检查是否满足晋升门槛
  python ai_promotion_gate.py status   # 查看各门槛进度
"""
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "strategy_config.json")


def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_gate_cfg(cfg):
    """读取晋升门槛配置, 合并默认值。"""
    ai_cfg = cfg.get("ai_overlay", {})
    gate = ai_cfg.get("promotion_gate", {})
    defaults = {
        "min_samples": 20,
        "min_ai_win_rate": 55.0,
        "min_avg_outperformance": 1.0,
        "min_script_samples": 5,
        "min_script_win_rate": 50.0,
    }
    defaults.update(gate)
    return defaults


def _load_shadow_evals():
    """加载已评估的 shadow 快照。"""
    import shadow_eval
    snapshots = shadow_eval._load_snapshots()
    return [s for s in snapshots if s.get("evaluated") and s.get("eval")]


def _load_scripts():
    """加载所有剧本。"""
    sys.path.insert(0, HERE)
    import script_tracker
    return script_tracker._list_scripts()


def check():
    """
    检查是否满足全部晋升门槛。

    返回 dict:
      {
        "promote": bool,
        "gates": [
          {"name": ..., "threshold": ..., "actual": ..., "pass": bool, "detail": ...},
          ...
        ]
      }
    """
    cfg = _load_config()
    gate = _get_gate_cfg(cfg)
    evals = _load_shadow_evals()
    scripts = _load_scripts()

    gates = []

    # Gate 1: shadow 评估样本量
    n_evals = len(evals)
    g1_pass = n_evals >= gate["min_samples"]
    gates.append({
        "name": "shadow_eval_samples",
        "threshold": gate["min_samples"],
        "actual": n_evals,
        "pass": g1_pass,
        "detail": f"已评估 {n_evals}/{gate['min_samples']} 条 shadow 快照",
    })

    # Gate 2: AI 胜率 (前向收益 AI > 规则 的占比)
    if evals:
        ai_wins = sum(1 for s in evals if s["eval"]["ai_wins"])
        ai_wr = ai_wins / len(evals) * 100
    else:
        ai_wr = 0
    g2_pass = ai_wr >= gate["min_ai_win_rate"]
    gates.append({
        "name": "ai_win_rate",
        "threshold": gate["min_ai_win_rate"],
        "actual": round(ai_wr, 1),
        "pass": g2_pass,
        "detail": f"AI 前向收益胜率 {ai_wr:.1f}%/{gate['min_ai_win_rate']:.1f}%",
    })

    # Gate 3: AI 平均超额收益
    if evals:
        avg_diff = sum(s["eval"]["diff"] for s in evals) / len(evals)
    else:
        avg_diff = 0
    g3_pass = avg_diff >= gate["min_avg_outperformance"]
    gates.append({
        "name": "avg_outperformance",
        "threshold": gate["min_avg_outperformance"],
        "actual": round(avg_diff, 2),
        "pass": g3_pass,
        "detail": f"AI 平均超额 {avg_diff:+.2f}%/{gate['min_avg_outperformance']:+.2f}%",
    })

    # Gate 4: AI 剧本样本量
    ai_scripts = [s for s in scripts if s.get("source", "human") == "ai"]
    ai_decided = [s for s in ai_scripts if s["status"] in ("hit", "miss", "partial")]
    g4_pass = len(ai_decided) >= gate["min_script_samples"]
    gates.append({
        "name": "script_samples",
        "threshold": gate["min_script_samples"],
        "actual": len(ai_decided),
        "pass": g4_pass,
        "detail": f"AI 剧本已判定 {len(ai_decided)}/{gate['min_script_samples']} 条",
    })

    # Gate 5: AI 剧本胜率
    if ai_decided:
        ai_hits = len([s for s in ai_decided if s["status"] == "hit"])
        ai_script_wr = ai_hits / len(ai_decided) * 100
    else:
        ai_script_wr = 0
    g5_pass = ai_script_wr >= gate["min_script_win_rate"]
    gates.append({
        "name": "script_win_rate",
        "threshold": gate["min_script_win_rate"],
        "actual": round(ai_script_wr, 1),
        "pass": g5_pass,
        "detail": f"AI 剧本胜率 {ai_script_wr:.1f}%/{gate['min_script_win_rate']:.1f}%",
    })

    all_pass = all(g["pass"] for g in gates)
    return {"promote": all_pass, "gates": gates}


def status():
    """查看各门槛进度。"""
    result = check()
    gate_cfg = _get_gate_cfg(_load_config())
    evals = _load_shadow_evals()
    scripts = _load_scripts()

    print(f"  AI Shadow->Active 晋升进度")
    print(f"  {'='*55}")
    for g in result["gates"]:
        status_mark = "[PASS]" if g["pass"] else "[HOLD]"
        print(f"  {status_mark} {g['name']}")
        print(f"         {g['detail']}")
    print(f"  {'='*55}")
    if result["promote"]:
        print(f"  >>> 建议: 晋升 (将 ai_overlay.shadow_mode 改为 false)")
        print(f"  >>> 但仍建议保持 enabled=true + shadow_mode=false 先做 paper trading 验证")
    else:
        n_hold = sum(1 for g in result["gates"] if not g["pass"])
        print(f"  >>> 建议: 维持 shadow ({n_hold} 项门槛未达标)")
        print(f"  >>> 继续积累样本, 定期运行 check 查看进度")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="AI 晋升门槛检查")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").set_defaults(func=lambda a: _cmd_check(a))
    sub.add_parser("status").set_defaults(func=lambda a: status())
    args = ap.parse_args()
    args.func(args)


def _cmd_check(args):
    result = check()
    status()
    # 退出码: 0=可晋升, 1=不可晋升
    sys.exit(0 if result["promote"] else 1)


if __name__ == "__main__":
    main()
