"""
ai_score.py - AI选股加权打分 (v6.14 AI增强 阶段3)

定位:
  在 selector 三维规则评分之上叠加 LLM 基本面/质评乘数(0.8~1.2), 作「放大器」。
  不替代规则, 仅微调排序。乘数 >1 = 质评加分, <1 = 质评减分, 1.0 = 中性。

安全阀 (memory 硬约束):
  - ai_overlay.enabled=false -> 直接返回原列表 (pass-through, 零影响)
  - ai_score.enable=false -> 同上
  - shadow_mode=true(默认) -> 计算 AI 乘数并打印对比, 但不改变实际排序
  - LLM 失败/超时/未配置 -> 全部乘数=1.0 (纯规则)
  - 乘数硬钳 [0.8, 1.2], 防止 LLM 输出极端值
  - 只评 Top N(默认10只), 不评全池(控成本/延迟)
  - LLM 输入/输出落盘 records/ai_score_snapshot.jsonl 供审计
  - 回测禁用实时 LLM(前视偏差+不可复现), AI 仅 live shadow 评估

集成方式:
  from ai_score import augment
  chosen_def = selector.select(cfg, ...)
  chosen_def = augment(chosen_def, cfg, tag="defensive")  # enabled=false 时原样返回

CLI:
  python ai_score.py --test   # 用 selector 跑一遍防御选股, shadow 打印 AI 对比
"""
import os
import sys
import json
import math
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm_client  # 统一 LLM 调用: env(LLM_BASE_URL/LLM_API_KEY/LLM_MODEL) 优先, 优雅降级

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "strategy_config.json")
RECORD_ROOT = os.path.join(HERE, "records")
AUDIT_LOG = os.path.join(RECORD_ROOT, "ai_score_snapshot.jsonl")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_ai_cfg(cfg):
    return cfg.get("ai_overlay", {
        "enabled": False, "shadow_mode": True,
        "llm": {"base_url": "", "api_key": "", "model": "", "timeout_sec": 30, "max_tokens": 2000},
        "ai_score": {"enable": True, "multiplier_min": 0.8, "multiplier_max": 1.2, "max_candidates": 10},
    })


def _is_enabled(cfg):
    """检查 AI 打分是否实际启用。"""
    ai_cfg = get_ai_cfg(cfg)
    return (ai_cfg.get("enabled", False) and
            ai_cfg.get("ai_score", {}).get("enable", True))


def _build_candidates_text(candidates):
    """把候选列表格式化为 LLM 可读的紧凑表格。"""
    lines = ["| 序号 | 代码 | 名称 | 行业 | PE | 历史分位 | 换手% | 20日涨幅% | 规则评分 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for i, d in enumerate(candidates, 1):
        pe = d.get("pe")
        pe_str = f"{pe:.1f}" if pe is not None else "N/A"
        pct = d.get("hist_pct")
        pct_str = f"{pct:.0%}" if pct is not None else "N/A"
        to = d.get("turnover_pct")
        to_str = f"{to:.2f}" if to is not None else "N/A"
        chg = d.get("chg20")
        chg_str = f"{chg:+.1f}" if chg is not None else "N/A"
        score = d.get("final_score", 0)
        off_tag = " [进攻]" if d.get("_offensive") else ""
        lines.append(
            f"| {i} | {d['code']} | {d.get('name', '')} | {d.get('industry', '')}{off_tag} | "
            f"{pe_str} | {pct_str} | {to_str} | {chg_str} | {score:.3f} |"
        )
    return "\n".join(lines)


def _build_prompt(candidates, tag):
    """构建 system + user prompt。"""
    system = (
        "你是一位严谨的A股基本面量化分析师。你的任务是对候选股票做质评打分。\n\n"
        "规则:\n"
        "1. 对每只股票输出一个质量乘数(multiplier), 范围 0.8~1.2\n"
        "2. 乘数 1.0 = 中性(与规则评分一致), >1 = 质评优秀(加分), <1 = 质评存疑(减分)\n"
        "3. 评估维度: 行业前景/估值合理性/动量质量/换手健康度\n"
        "4. 不要因为PE高就一律减分(科技股PE高是常态), 要结合行业和动量综合判断\n"
        "5. 输出必须是合法 JSON 数组, 每条含 code/multiplier/reason/risk/catalyst, 不要多余文字:\n"
        '[{"code":"600036","multiplier":1.1,"reason":"低PE银行龙头+稳健","risk":"息差承压","catalyst":"高股息防御偏好"},...]\n'
        "6. 每只股票必须出现在输出中, code 与输入一致; reason/risk/catalyst 用中文简短短语"
    )

    user = (
        f"候选股票({tag}端, 共{len(candidates)}只):\n\n"
        f"{_build_candidates_text(candidates)}\n\n"
        f"请对每只股票输出质量乘数。"
    )
    return system, user


def _call_llm(cfg, system_prompt, user_prompt):
    """调用 OpenAI 兼容 API, 返回 (content_str, error_str)。统一走 llm_client (env 优先, 优雅降级)。"""
    return llm_client.call_llm(cfg, system_prompt, user_prompt, temperature=0.3)


def _parse_multipliers(content, candidates):
    """解析 LLM 输出的 JSON 乘数, 返回 {code: {multiplier, reason, risk, catalyst}}。失败返回空 dict。"""
    if not content:
        return {}

    # 尝试提取 JSON 数组 (LLM 可能包裹在 markdown 代码块中)
    text = content.strip()
    if "```" in text:
        # 提取代码块内容
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                text = part
                break

    try:
        arr = json.loads(text)
    except json.JSONDecodeError:
        # 尝试找到第一个 [ 到最后一个 ]
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            try:
                arr = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return {}
        else:
            return {}

    if not isinstance(arr, list):
        return {}

    result = {}
    for item in arr:
        if isinstance(item, dict) and "code" in item and "multiplier" in item:
            try:
                m = float(item["multiplier"])
            except (ValueError, TypeError):
                continue
            if math.isnan(m) or math.isinf(m):  # 拒绝 NaN/Inf, 避免污染打分
                continue
            result[str(item["code"])] = {
                "multiplier": m,
                "reason": str(item.get("reason", "")),
                "risk": str(item.get("risk", "")),
                "catalyst": str(item.get("catalyst", "")),
            }
    return result


def _save_audit(record):
    """追加审计快照到 records/ai_score_snapshot.jsonl"""
    os.makedirs(RECORD_ROOT, exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def augment(candidates, cfg, tag="defensive"):
    """
    对规则评分后的候选列表做 AI 加权打分。

    参数:
      candidates: selector 返回的 detail list (已含 final_score)
      cfg: 配置 dict
      tag: "defensive" / "offensive" (用于日志和审计)

    返回:
      排序后的候选列表。
      - enabled=false / ai_score.enable=false -> 原样返回
      - shadow_mode=true -> 计算 AI 乘数并打印对比, 但返回原排序
      - shadow_mode=false + enabled=true -> 用 AI 乘数重排

    任何异常均返回原列表 (纯规则, 零影响)。
    """
    if not candidates:
        return candidates

    ai_cfg = get_ai_cfg(cfg)

    # 未启用 -> 直接返回
    if not _is_enabled(cfg):
        return candidates

    shadow = ai_cfg.get("shadow_mode", True)
    score_cfg = ai_cfg.get("ai_score", {})
    m_min = score_cfg.get("multiplier_min", 0.8)
    m_max = score_cfg.get("multiplier_max", 1.2)
    max_cand = score_cfg.get("max_candidates", 10)

    # 只评 Top N (控成本)
    to_eval = candidates[:max_cand]

    # 构建 prompt 并调用 LLM
    system, user = _build_prompt(to_eval, tag)
    content, err = _call_llm(cfg, system, user)

    if err:
        # LLM 不可用 -> 全部乘数 1.0, 原样返回
        print(f"  [ai_score] LLM 不可用({err}), 乘数=1.0, 退回纯规则")
        _save_audit({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "tag": tag,
            "shadow": shadow,
            "error": err,
            "candidates": len(to_eval),
            "multipliers": {},
        })
        return candidates

    # 解析乘数
    mult_map = _parse_multipliers(content, to_eval)

    if not mult_map:
        print(f"  [ai_score] LLM 输出解析失败, 乘数=1.0, 退回纯规则")
        _save_audit({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "tag": tag,
            "shadow": shadow,
            "error": "LLM 输出解析失败",
            "raw_output": content[:500],
            "candidates": len(to_eval),
            "multipliers": {},
        })
        return candidates

    # 应用乘数 + 决策摘要字段
    print(f"  [ai_score] {'SHADOW(仅打印)' if shadow else 'LIVE'} {tag}端 AI 加权打分:")
    augmented = []
    for d in candidates:
        code = d["code"]
        entry = mult_map.get(code)
        m = entry["multiplier"] if entry else 1.0
        # 硬钳
        m = max(m_min, min(m_max, m))
        orig_score = d.get("final_score", 0)
        aug_score = round(orig_score * m, 3)
        d_copy = dict(d)
        d_copy["ai_multiplier"] = round(m, 3)
        d_copy["ai_adjusted_score"] = aug_score
        d_copy["ai_reason"] = entry.get("reason", "") if entry else ""
        d_copy["ai_risk"] = entry.get("risk", "") if entry else ""
        d_copy["ai_catalyst"] = entry.get("catalyst", "") if entry else ""
        augmented.append(d_copy)

        if entry or m != 1.0:
            arrow = "\u2192" if m != 1.0 else "="
            tail = f" | {d_copy['ai_reason']}" if d_copy["ai_reason"] else ""
            print(f"    {code} {d.get('name', '')}: {orig_score:.3f} x{m:.2f} {arrow} {aug_score:.3f}{tail}")

    # 审计快照
    _save_audit({
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tag": tag,
        "shadow": shadow,
        "candidates": [
            {"code": d["code"], "name": d.get("name", ""),
             "orig": d.get("final_score", 0),
             "multiplier": d.get("ai_multiplier", 1.0),
             "adjusted": d.get("ai_adjusted_score", d.get("final_score", 0)),
             "reason": d.get("ai_reason", ""),
             "risk": d.get("ai_risk", ""),
             "catalyst": d.get("ai_catalyst", "")}
            for d in augmented
        ],
        "raw_llm_output": content[:1000],
    })

    # shadow: 返回原排序; live: 按 AI 调整分重排
    if shadow:
        # 记录 shadow A/B 快照供 shadow_eval 评估
        try:
            import shadow_eval
            # augmented 按 ai_adjusted_score 排序得到 AI 视角的 top-N
            ai_sorted = sorted(augmented,
                               key=lambda d: d.get("ai_adjusted_score", d.get("final_score", 0)),
                               reverse=True)
            shadow_eval.record(tag, candidates, ai_sorted, top_n=3)
        except Exception as e:
            print(f"  [ai_score] shadow_eval 记录失败(不影响主流程): {e}")
        print(f"  [ai_score] SHADOW 模式: 保持原排序, AI 乘数仅作参考")
        return candidates  # 原列表, 不改排序
    else:
        augmented.sort(key=lambda d: d.get("ai_adjusted_score", d.get("final_score", 0)), reverse=True)
        print(f"  [ai_score] LIVE 模式: 按 AI 调整分重排")
        return augmented


# ---------------------------------------------------------------- CLI 测试

def main():
    import argparse
    ap = argparse.ArgumentParser(description="AI选股加权打分 (shadow 模式测试)")
    ap.add_argument("--test", action="store_true", help="用 selector 跑防御选股, shadow 打印 AI 对比")
    args = ap.parse_args()

    if not args.test:
        ap.print_help()
        return

    cfg = load_config()
    ai_cfg = get_ai_cfg(cfg)

    print("=" * 60)
    print("AI选股加权打分 - shadow 测试")
    print(f"  ai_overlay.enabled = {ai_cfg.get('enabled', False)}")
    print(f"  ai_overlay.shadow_mode = {ai_cfg.get('shadow_mode', True)}")
    print(f"  ai_score.enable = {ai_cfg.get('ai_score', {}).get('enable', True)}")
    print("=" * 60)

    if not _is_enabled(cfg):
        print("\n  ai_overlay.enabled=false 或 ai_score.enable=false")
        print("  -> augment() 直接返回原列表 (pass-through, 零影响)")
        print("  如需启用: 在 strategy_config.json 设 ai_overlay.enabled=true + 配置 llm")
        print("  未配置 LLM 时, augment() 也会退回乘数=1.0 (纯规则)\n")
        return

    # 跑一遍防御选股
    import selector
    chosen = selector.select(cfg, verbose=True, defensive_only=True)
    if not chosen:
        print("  防御选股无结果, 跳过 AI 打分")
        return

    print(f"\n  防御选股 {len(chosen)} 只, 进入 AI 加权打分...\n")
    augmented = augment(chosen, cfg, tag="defensive")

    print(f"\n  最终排序:")
    for d in augmented:
        m = d.get("ai_multiplier", 1.0)
        s = d.get("ai_adjusted_score", d.get("final_score", 0))
        print(f"    {d['code']} {d.get('name', '')}  规则={d['final_score']:.3f}  "
              f"AI乘数={m:.2f}  调整={s:.3f}")


if __name__ == "__main__":
    main()
