"""
script_advisor.py - 剧本智能生成 (v6.14 AI增强 阶段1)

定位:
  读取行业动量 + 近期新闻 + 当前市况 -> 生成 user_script.md 草稿建议(方向+理由)。
  输出永远是"草稿", 用户确认后才手动写入 user_script.md。
  这是"剧本书写者"模式的 AI 辅助: 帮你看信息、提建议, 不替你拍板。

安全阀 (memory 硬约束):
  - AI 仅作建议, 不替代规则; 失败退回不写
  - shadow_mode: 默认只生成草稿到 records/, 绝不覆盖 user_script.md
  - enabled=false 时 --api 模式不可用, 仅 --interactive 生成 prompt 文件
  - LLM 走 OpenAI 兼容 API (DeepSeek/Qwen 等均支持), 未配置则退回 interactive

双模式:
  python script_advisor.py --interactive   # 生成自包含 prompt 文件, 供粘贴给任意 LLM
  python script_advisor.py --api           # 直接调 LLM API 生成草稿(需配置 ai_overlay.llm)
  python script_advisor.py --context       # 仅打印当前上下文摘要(不生成草稿)
"""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market_data as md
import llm_client  # 统一 LLM 调用: env(LLM_BASE_URL/LLM_API_KEY/LLM_MODEL) 优先, 优雅降级
import jsonl_utils as _jsonl

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "strategy_config.json")
RECORD_ROOT = os.path.join(HERE, "records")
USER_SCRIPT = os.path.join(HERE, "user_script.md")
THEME_FILE = os.path.join(HERE, "weekly_theme.json")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_ai_cfg(cfg):
    """读取 ai_overlay 配置段, 不存在则返回安全默认。"""
    return cfg.get("ai_overlay", {
        "enabled": False, "shadow_mode": True,
        "llm": {"base_url": "", "api_key": "", "model": "", "timeout_sec": 30, "max_tokens": 2000},
        "script_advisor": {"enable": True, "max_news_items": 20, "max_industries": 8},
    })


# ---------------------------------------------------------------- 上下文采集

def gather_context(cfg):
    """
    采集剧本生成的全部上下文:
      - 市况 (market_regime)
      - 行业动量排名 (weekly_theme.scan_industry_momentum)
      - 近期共振新闻 (news_feed)
      - 当前剧本方向 (user_script.md + weekly_theme.json)
    返回 dict, 任何子项失败均返回 None 不阻断整体。
    """
    ctx = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    # 1) 市况
    try:
        import selector
        regime, trend_msg = selector.market_regime(cfg)
        ctx["regime"] = regime
        ctx["trend_msg"] = trend_msg
    except Exception as e:
        ctx["regime"] = "unknown"
        ctx["trend_msg"] = f"市况读取失败: {e}"

    # 2) 行业动量
    try:
        import weekly_theme
        ind_mom = weekly_theme.scan_industry_momentum(cfg)
        ai_cfg = get_ai_cfg(cfg)
        max_ind = ai_cfg.get("script_advisor", {}).get("max_industries", 8)
        sorted_inds = sorted(ind_mom.items(),
                             key=lambda kv: kv[1].get("adj_chg", kv[1].get("avg_chg", 0)),
                             reverse=True)
        ctx["industry_rank"] = [
            {
                "industry": ind,
                "avg_chg": d.get("avg_chg", 0),
                "adj_chg": d.get("adj_chg", d.get("avg_chg", 0)),
                "adoption_phase": d.get("adoption_phase", "unknown"),
                "count": d.get("count", 0),
                "top_tickers": [
                    {"code": t["code"], "name": t.get("name", ""), "chg": t.get("chg", 0),
                     "turnover": t.get("turnover", 0)}
                    for t in d.get("tickers", [])[:3]
                ],
            }
            for ind, d in sorted_inds[:max_ind]
        ]
        # 标注"非进攻行业"(旧 weekly_theme.DEFENSIVE_INDUSTRY_BLACKLIST 已删除,
        # 改为从 config.universe_split.offensive_industries 白名单反推: 不在白名单=防御/避险板块)
        off_wl = set((cfg.get("universe_split") or {}).get("offensive_industries") or [])
        ctx["defensive_blacklist"] = [ind for ind in ind_mom if ind not in off_wl]
    except Exception as e:
        ctx["industry_rank"] = []
        ctx["industry_rank_error"] = str(e)

    # 3) 近期新闻
    try:
        import news_feed
        recs = news_feed._read()
        max_news = get_ai_cfg(cfg).get("script_advisor", {}).get("max_news_items", 20)
        # 优先共振新闻, 不足补普通
        resonance = [r for r in recs if r.get("tag") == "\u5171\u632f"]
        normal = [r for r in recs if r.get("tag") != "\u5171\u632f"]
        picked = (resonance + normal)[-max_news:]
        ctx["news"] = [
            {"ts": r.get("ts", ""), "title": r.get("title", ""),
             "resonance_with": r.get("resonance_with", [])}
            for r in picked
        ]
        ctx["news_total"] = len(recs)
        ctx["news_resonance_count"] = len(resonance)
    except Exception as e:
        ctx["news"] = []
        ctx["news_error"] = str(e)

    # 4) 当前剧本
    try:
        if os.path.exists(USER_SCRIPT):
            with open(USER_SCRIPT, "r", encoding="utf-8") as f:
                ctx["current_script"] = f.read()[:2000]
        else:
            ctx["current_script"] = "(user_script.md 不存在)"
    except Exception as e:
        ctx["current_script"] = f"读取失败: {e}"

    try:
        if os.path.exists(THEME_FILE):
            ctx["last_theme"] = json.load(open(THEME_FILE, encoding="utf-8"))
        else:
            ctx["last_theme"] = None
    except Exception:
        ctx["last_theme"] = None

    return ctx


# ---------------------------------------------------------------- 上下文格式化

def format_context_text(ctx):
    """把上下文 dict 格式化为 LLM 可读的紧凑文本。"""
    lines = []
    lines.append(f"# 剧本生成上下文 ({ctx['timestamp']})")
    lines.append("")

    # 市况
    lines.append("## 1. 当前市况")
    lines.append(f"- 判定: **{ctx.get('regime', 'unknown')}**")
    lines.append(f"- 详情: {ctx.get('trend_msg', '')}")
    lines.append("")

    # 行业动量
    lines.append("## 2. 行业动量排名 (近5交易日)")
    if ctx.get("industry_rank"):
        lines.append("| 排名 | 行业 | 真实涨幅 | 倾斜后 | 渗透相位 | 标的数 | 龙头 |")
        lines.append("|---|---|---|---|---|---|---|")
        for i, ind in enumerate(ctx["industry_rank"], 1):
            top = ind["top_tickers"][0] if ind["top_tickers"] else {}
            tag = " [防御黑名单]" if ind["industry"] in ctx.get("defensive_blacklist", []) else ""
            lines.append(f"| {i} | {ind['industry']}{tag} | {ind['avg_chg']:+.1f}% | "
                         f"{ind['adj_chg']:+.1f}% | {ind['adoption_phase']} | {ind['count']} | "
                         f"{top.get('name', '')}({top.get('chg', 0):+.1f}%) |")
    else:
        lines.append(f"(行业动量读取失败: {ctx.get('industry_rank_error', '未知')})")
    lines.append("")

    # 新闻
    lines.append("## 3. 近期新闻 (优先共振)")
    if ctx.get("news"):
        lines.append(f"(库存 {ctx.get('news_total', 0)} 条, 共振 {ctx.get('news_resonance_count', 0)} 条)")
        for n in ctx["news"]:
            rh = ",".join(n.get("resonance_with", []))
            mark = "\U0001f525" if rh else "  "
            lines.append(f"{mark} [{n['ts'][:16]}] {n['title']}" + (f"  <-{rh}" if rh else ""))
    else:
        lines.append(f"(新闻读取失败: {ctx.get('news_error', '无存档, 先跑 news_feed.py fetch')})")
    lines.append("")

    # 当前剧本
    lines.append("## 4. 当前剧本 (user_script.md)")
    lines.append("```")
    lines.append(ctx.get("current_script", "(无)"))
    lines.append("```")
    lines.append("")

    # 上周主题
    if ctx.get("last_theme"):
        lt = ctx["last_theme"]
        lines.append("## 5. 上周主题 (weekly_theme.json)")
        lines.append(f"- 模式: {lt.get('mode', '?')}")
        lines.append(f"- 进攻: {lt.get('offensive', [])}")
        if lt.get("main_lines"):
            for ml in lt["main_lines"]:
                lines.append(f"  - {ml.get('industry', '')} {ml.get('avg_chg', 0):+.1f}%")
        lines.append("")

    return "\n".join(lines)


def build_prompt(ctx):
    """构建给 LLM 的完整 system + user prompt。"""
    system = (
        "你是一位严谨的A股量化策略顾问。你的任务是根据市场上下文, "
        "为「剧本书写者」自动交易系统生成下周 user_script.md 草稿建议。\n\n"
        "规则:\n"
        "1. 防御端由系统自治(银行/电力/红利蓝筹), 你只需建议进攻方向(1-2个行业)\n"
        "2. 进攻方向必须是行业动量为正的真实题材板块(非防御黑名单)\n"
        "3. 结合新闻共振确认方向, 无共振则标注'弱信号'\n"
        "4. 弱势市建议保守(可转债替代/降进攻), 强势市可博弹性\n"
        "5. 输出格式严格如下, 不要多余解释:\n\n"
        "```\n"
        "# 用户剧本入口（User Script）\n\n"
        "> AI辅助生成草稿, 待用户确认\n\n"
        "---\n\n"
        "## 当前剧本（{week_label}）\n\n"
        "**进攻方向（AI建议）：** {行业A} 或 {行业B}\n\n"
        "**防御端（系统自治）：** 银行 + 电力 + 红利低波\n\n"
        "**目标：** {根据市况给目标}\n\n"
        "**市况背景：** {市况描述}\n\n"
        "**AI建议理由：**\n{3-5条要点}\n\n"
        "---\n\n"
        "## 风险提示\n{潜在风险}\n"
        "```\n"
    )
    user = format_context_text(ctx)
    user += "\n\n---\n\n请根据以上上下文, 生成下周 user_script.md 草稿。"
    return system, user


# ---------------------------------------------------------------- LLM API 调用

def call_llm(cfg, system_prompt, user_prompt):
    """
    调用 OpenAI 兼容 API。失败返回 (None, error)。统一走 llm_client (env 优先, 优雅降级)。
    """
    return llm_client.call_llm(cfg, system_prompt, user_prompt, temperature=0.7)


# ---------------------------------------------------------------- 草稿落盘

def save_draft(content, mode_tag):
    """把草稿/prompt 落盘到 records/, 返回文件路径。"""
    os.makedirs(RECORD_ROOT, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"script_advisor_{mode_tag}_{ts}.md"
    path = os.path.join(RECORD_ROOT, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ---------------------------------------------------------------- 命令入口

def cmd_interactive(cfg):
    """生成自包含 prompt 文件, 供用户粘贴给任意 LLM。"""
    print("[script_advisor] interactive 模式: 生成 prompt 文件...")
    ctx = gather_context(cfg)
    system, user = build_prompt(ctx)

    # prompt 文件 = system + user, 可直接粘贴
    prompt_text = (
        "# === System Prompt ===\n" + system +
        "\n\n# === User Prompt ===\n" + user
    )
    path = save_draft(prompt_text, "prompt")

    print(f"\n{'='*60}")
    print(f"Prompt 文件已生成: {path}")
    print(f"{'='*60}")
    print(f"\n使用方法:")
    print(f"  1. 打开上述文件, 复制全部内容")
    print(f"  2. 粘贴给任意 LLM (ChatGPT/DeepSeek/Qwen/WorkBuddy 等)")
    print(f"  3. LLM 输出的草稿复制到 user_script.md (替换「当前剧本」段落)")
    print(f"  4. 确认无误后保存\n")

    # 同时打印上下文摘要
    print(f"\n--- 上下文摘要 ---")
    print(format_context_text(ctx))


def cmd_api(cfg):
    """直接调 LLM API 生成草稿。"""
    ai_cfg = get_ai_cfg(cfg)
    if not ai_cfg.get("enabled", False):
        print("[script_advisor] ai_overlay.enabled=false, --api 模式不可用")
        print("  请在 strategy_config.json 中设置 ai_overlay.enabled=true 并配置 llm.base_url/api_key/model")
        print("  或使用 --interactive 模式生成 prompt 文件")
        return

    print("[script_advisor] api 模式: 调用 LLM 生成草稿...")
    ctx = gather_context(cfg)
    system, user = build_prompt(ctx)

    content, err = call_llm(cfg, system, user)
    if err:
        print(f"  [script_advisor] LLM 调用失败: {err}")
        print(f"  退回 interactive: 生成 prompt 文件供手动使用")
        prompt_text = "# === System Prompt ===\n" + system + "\n\n# === User Prompt ===\n" + user
        path = save_draft(prompt_text, "prompt_fallback")
        print(f"  Prompt 文件: {path}")
        return

    # 落盘草稿
    path = save_draft(content, "draft")
    shadow = ai_cfg.get("shadow_mode", True)
    print(f"\n{'='*60}")
    print(f"AI 草稿已生成: {path}")
    print(f"shadow_mode={shadow} -> {'仅存档, 不覆盖 user_script.md' if shadow else '可直接复制到 user_script.md'}")
    print(f"{'='*60}")
    print(f"\n--- 草稿内容 ---\n")
    print(content)
    print(f"\n--- 落盘审计 ---")
    # 审计快照
    audit = {
        "ts": ctx["timestamp"],
        "mode": "api",
        "shadow": shadow,
        "draft_path": path,
        "context_summary": {
            "regime": ctx.get("regime"),
            "top_industries": [i["industry"] for i in ctx.get("industry_rank", [])[:3]],
            "news_count": len(ctx.get("news", [])),
        },
    }
    save_audit(audit)
    print(f"  审计快照: {os.path.join(RECORD_ROOT, 'script_advisor_audit.jsonl')}")

    # 自动创建 script_tracker 追踪记录 (source=ai)
    _auto_track_ai_script(cfg, ctx, content)


def _auto_track_ai_script(cfg, ctx, content):
    """
    为 AI 生成的草稿自动创建一条 script_tracker 记录 (source=ai)。
    这样 AI 建议也能被追踪胜率, 与 human 剧本对比。

    方向从草稿文本推断; 指标用沪深300 (默认基准)。
    用户可后续手动修改 scripts/<id>.json 补充更精确的指标。
    """
    try:
        import script_tracker
    except Exception:
        return None

    # 从草稿文本推断方向
    text_lower = content.lower() if content else ""
    if any(k in content for k in ("看涨", "进攻", "加仓", "博弹性", "强势")) or "bullish" in text_lower:
        direction = "bullish"
        expect = "up"
    elif any(k in content for k in ("看跌", "离场", "保守", "降仓", "弱势")) or "bearish" in text_lower:
        direction = "bearish"
        expect = "down"
    else:
        direction = "range"
        expect = "range"

    # 到期日: 默认2周后
    from datetime import timedelta
    expiry = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

    # 用沪深300作为默认验证标的
    today = datetime.now().strftime("%Y-%m-%d")
    indicators = [{
        "code": "sh000300",
        "metric": "return_pct",
        "expect": expect,
        "desc": f"沪深300 {today}->{expiry} 预期{expect}",
        "written_date": today,
    }]

    sid = script_tracker._gen_id("AIadvisor")
    script = {
        "id": sid,
        "written_date": today,
        "title": f"AI建议({direction})",
        "expiry": expiry,
        "direction": direction,
        "source": "ai",
        "thesis": content[:200] if content else "",
        "indicators": indicators,
        "event_markers": [],
        "status": "open",
    }
    script_tracker._save(script)
    print(f"  [script_advisor] 自动追踪已创建: {sid} (source=ai, direction={direction})")
    print(f"    可用 'python script_tracker.py list' 查看, 到期后 'check' 自动判定")
    return sid


def cmd_context(cfg):
    """仅打印上下文摘要, 不生成草稿。"""
    print("[script_advisor] context 模式: 打印上下文摘要...")
    ctx = gather_context(cfg)
    print(format_context_text(ctx))


def save_audit(record):
    """追加审计记录到 records/script_advisor_audit.jsonl"""
    # M21: 复用 jsonl_utils.append_jsonl (自动建目录 + 统一序列化)
    _jsonl.append_jsonl(os.path.join(RECORD_ROOT, "script_advisor_audit.jsonl"), record)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="剧本智能生成 (AI辅助, 草稿输出, 用户确认)")
    ap.add_argument("--mode", default="interactive", choices=["interactive", "api", "context"],
                    help="interactive=生成prompt文件 / api=调LLM生成草稿 / context=仅看上下文")
    args = ap.parse_args()

    cfg = load_config()
    if args.mode == "interactive":
        cmd_interactive(cfg)
    elif args.mode == "api":
        cmd_api(cfg)
    elif args.mode == "context":
        cmd_context(cfg)


if __name__ == "__main__":
    main()
