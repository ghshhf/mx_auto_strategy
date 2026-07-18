"""
weekly_theme.py - 每周自动选题材 (进攻主线识别)

核心职责:
  每周一运行时, 扫描候选池所有票的上周(最近5交易日)涨幅,
  按行业聚合出"上周最强行业", 作为本周进攻主线。
  从主线行业中挑高弹性票(换手高+动量强)作为进攻端 2 只。

设计原则(用户铁律):
  - 这不是让你追高杀跌, 而是"跟随上一周已经证明有资金的方向"
  - 防御端(3只蓝筹)始终不动, 稳住基本盘
  - 进攻端(2只)自适应切换, 只在有主线信号时出击, 无信号则退回医疗/电力稳健组合
  - 不碰合约/杠杆, 单票<=18%, 独立-10%止损

输出:
  - 返回 theme 结构 {week_label, main_lines:[{industry, chg, tickers:[...]}], offensive:[code,...]}
  - 落盘 weekly_theme.json 供下周参考 + 本地 records 留存
"""
import sys
import os
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market_data as md

THEME_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weekly_theme.json")
EVENT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "event_override.json")

# 防御/避险/价值行业黑名单: 这些板块即使上周涨了也不作为"进攻主线"
# 原因: 石油(地缘避险,不可能一直涨)、银行/电力/家电/食品/白酒/建筑/建材/保险/化工
#       本质是低beta价值或避险资产, 放进进攻端逻辑错位, 且弹性不足以冲名次。
# 进攻主线只从真正的"题材弹性行业"里挑 (科技/半导体/军工/稀土/券商/地产链/消费电子/有色/医药创新等)
DEFENSIVE_INDUSTRY_BLACKLIST = {
    "石油", "银行", "电力", "家电", "食品", "白酒", "建筑", "建材",
    "保险", "化工", "石化", "公用事业", "电信", "铁路", "公路", "港口",
}

# 事件注入层 (非主要路径, 用户手动提示才生效):
# event_override.json 格式:
# {
#   "week_label": "2026-W29",          # 生效周 (可选, 不填则本周生效)
#   "boost_industries": ["半导体","军工"],   # 事件受益行业, 加权前置
#   "avoid_industries": ["新能源","锂矿"],   # 事件利空行业, 排除或降权
#   "note": "锂电池征消费税, 宁德/天齐承压, 转半导体/军工"
# }
# 若文件不存在或 week_label 不匹配本周, 完全按自适应主线走 (不动它)。
EVENT_BOOST_WEIGHT = 1.5   # 受益行业动量得分乘子
EVENT_AVOID_DROP = -999     # 利空行业动量置为极负, 实质排除


def load_event_override():
    """读取事件注入 (不存在/格式错/周不匹配 -> 返回 None)。"""
    if not os.path.exists(EVENT_FILE):
        return None
    try:
        ev = json.load(open(EVENT_FILE, encoding="utf-8"))
    except Exception:
        return None
    wl = ev.get("week_label")
    if wl:
        cur = datetime.now().strftime("%Y-W%W")
        if wl != cur:
            return None  # 非本周事件, 忽略
    return ev


def _last_n_trading_days(n=5):
    """从今天往前推, 取最近 n 个交易日的日期字符串(yyyymmdd)。
    简化: 跳过周末, 向前数 n 个交易日。"""
    days = []
    d = datetime.now()
    while len(days) < n:
        if d.weekday() < 5:  # 周一到周五
            days.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return list(reversed(days))


def scan_industry_momentum(cfg):
    """扫描候选池, 按行业聚合上周涨幅。
    返回: {industry: {"chg": avg_chg, "tickers": [{code,name,chg,turnover}]}}"""
    asel = cfg.get("auto_select", {})
    pool = asel.get("candidate_pool", [])
    n = 5  # 上周约5个交易日
    # 往前推一天避免使用今天未收盘数据
    days = _last_n_trading_days(n + 1)[1:]  # 跳过今天, 取真正"上周"5天
    if not days:
        days = _last_n_trading_days(n)

    industry_data = {}
    for p in pool:
        code = p["code"]
        ind = p.get("industry", "未知")
        kl = md.get_kline(code, "day", 30)
        if len(kl) < n + 1:
            continue
        # 取最近 n 天区间涨幅: 倒数第n天收盘 -> 最后收盘
        ref_close = kl[-(n + 1)]["close"]
        last_close = kl[-1]["close"]
        chg = (last_close / ref_close - 1) * 100
        # 实时换手
        rt = md.get_realtime([code]).get(code, {})
        to = rt.get("turnover_pct") or 0
        industry_data.setdefault(ind, {"chg_sum": 0.0, "count": 0, "tickers": []})
        industry_data[ind]["chg_sum"] += chg
        industry_data[ind]["count"] += 1
        industry_data[ind]["tickers"].append({
            "code": code, "name": p.get("name", ""),
            "chg": round(chg, 2), "turnover": to,
            "tech": p.get("tech", False)
        })

    # 行业平均涨幅
    result = {}
    for ind, d in industry_data.items():
        if d["count"] == 0:
            continue
        result[ind] = {
            "avg_chg": round(d["chg_sum"] / d["count"], 2),
            "count": d["count"],
            "tickers": sorted(d["tickers"], key=lambda t: t["chg"], reverse=True)
        }
    return result


def load_user_direction_overlay():
    """读取用户方向叠加层 (user_direction_overlay 模式才生效)。
    对应 weekly_theme.json 中的 mode=user_direction_overlay 字段。
    若不存在 / mode 不匹配 / 无 user_direction -> 返回 None (完全走自适应)。"""
    if not os.path.exists(THEME_FILE):
        return None
    try:
        th = json.load(open(THEME_FILE, encoding="utf-8"))
    except Exception:
        return None
    if th.get("mode") != "user_direction_overlay":
        return None
    ud = th.get("user_direction", "")
    if not ud:
        return None
    # 从 main_lines 提取用户指定的行业方向
    dirs = [m.get("industry") for m in th.get("main_lines", []) if m.get("industry")]
    # 从 defensive_3 提取用户指定的防御3只 (支持两种格式: 字符串数组 或 {ticker:}对象数组)
    raw_def3 = th.get("defensive_3", [])
    def3 = []
    for d in raw_def3:
        if isinstance(d, str):
            def3.append(d)
        elif isinstance(d, dict) and d.get("ticker"):
            def3.append(d["ticker"])
    return {"raw": ud, "directions": dirs, "defensive_3": def3}


# 行业别名映射: 用户口语方向 -> 池子内真实行业标签
INDUSTRY_ALIAS = {
    "医疗": "医药", "medicine": "医药",
    "电力": "电力", "电网": "电网",
}

def _resolve_industry(ind):
    """把用户写的行业名解析为池子内真实标签(支持口语别名)。"""
    return INDUSTRY_ALIAS.get(ind, ind)


def _overlay_pick(cfg, overlay, verbose=True):
    """用户方向叠加模式: 用户给方向(电力/医疗), AI叠加动量验证挑具体票。
    防御端3只强制采用用户指定的 defensive_3 (若提供), 否则退回默认蓝筹。
    进攻端从用户方向(排除防御3只占用)里挑动量最强票, 不重复。"""
    ind_mom = scan_industry_momentum(cfg)
    asel = cfg.get("auto_select", {})
    pool = {p["code"]: p for p in asel.get("candidate_pool", [])}
    week_label = datetime.now().strftime("%Y-W%W")

    # 防御3只(用户指定优先)
    defensive = [c for c in overlay.get("defensive_3", []) if c in pool][:3]
    if len(defensive) < 3:
        for fb in ["601398", "600900", "512890", "601939", "600519"]:
            if fb in pool and fb not in defensive:
                defensive.append(fb)
            if len(defensive) >= 3:
                break

    # 1. 进攻端: 从用户方向(解析别名)里, 排除防御占用的票, 挑动量最强
    offensive = []
    used = set(defensive)  # 防御占用的票进攻端不再选
    matched_dirs = []
    for ind in overlay["directions"]:
        real_ind = _resolve_industry(ind)
        matched_dirs.append(real_ind)
        # 该行业动量扫描里的票
        cands = [t for t in ind_mom.get(real_ind, {}).get("tickers", [])
                 if t["code"] not in used and t["code"] in pool]
        if not cands:
            # 退而从候选池直接找该行业票
            cands = [{"code": p["code"], "name": p["name"], "turnover": 0, "chg": 0}
                     for p in pool.values()
                     if p.get("industry") == real_ind and p["code"] not in used]
        if cands:
            best = max(cands, key=lambda t: (t.get("turnover") or 0) * 0.6 + max(0, t.get("chg", 0)) * 0.4)
            offensive.append(best["code"])
            used.add(best["code"])

    # 2. 防御端3只: 优先用用户指定的 defensive_3, 校验在池子里
    defensive = [c for c in overlay.get("defensive_3", []) if c in pool][:3]
    if len(defensive) < 3:
        # 不足3只则补默认蓝筹(银行/电力/红利ETF)
        for fb in ["601398", "600900", "512890", "601939", "600519"]:
            if fb in pool and fb not in defensive:
                defensive.append(fb)
            if len(defensive) >= 3:
                break

    # 3. 若用户方向没产出进攻票, 退回稳健组合
    if not offensive:
        offensive = _fallback_theme(cfg, verbose=False).get("offensive", ["002821", "600900"])
        offensive = [c for c in offensive if c in pool][:2]

    theme = {
        "week_label": week_label,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "user_direction_overlay",
        "strategy": "用户预判叠加模式 (用户给方向, AI叠加动量挑票)",
        "user_direction": overlay["raw"],
        "main_lines": [
            {"industry": ind,
             "avg_chg": round(ind_mom.get(ind, {}).get("avg_chg", 0), 2),
             "top_ticker": pool.get(offensive[i], {}).get("name", "")}
            for i, ind in enumerate(matched_dirs[:len(offensive)])
        ],
        "defensive_3": defensive,
        "offensive": offensive,
        "all_industry_rank": [
            {"industry": ind, "avg_chg": d["avg_chg"]}
            for ind, d in sorted(ind_mom.items(), key=lambda kv: kv[1]["avg_chg"], reverse=True)[:8]
        ],
    }
    _save(theme)
    if verbose:
        print(f"  🎯 [用户叠加模式] 方向: {overlay['raw']}")
        print(f"  🛡️ 防御3只: {defensive} (用户指定优先)")
        print(f"  🔥 进攻 {len(offensive)} 票: {offensive} -> " +
              " / ".join(f"{pool.get(c,{}).get('name','')}({c})" for c in offensive))
    return theme


def pick_theme(cfg, verbose=True):
    """主入口: 选出本周进攻主线 + 进攻 2 票。
    若无明确主线(所有行业平均涨幅<0且无单票亮点), 退回稳健医疗/电力。

    叠加模式优先级:
      1. user_direction_overlay (weekly_theme.json 指定) -> 用户给方向, AI叠加挑票
      2. event_override.json 事件注入 -> 受益/规避加权
      3. 纯自适应主线 (默认)"""
    # 入口先检测用户方向叠加层
    overlay = load_user_direction_overlay()
    if overlay:
        if verbose:
            print("  📌 检测到用户方向叠加模式, 进入叠加选股分支")
        return _overlay_pick(cfg, overlay, verbose=verbose)

    ind_mom = scan_industry_momentum(cfg)
    if not ind_mom:
        return _fallback_theme(cfg, verbose)

    # 行业按平均涨幅排序
    sorted_inds = sorted(ind_mom.items(), key=lambda kv: kv[1]["avg_chg"], reverse=True)

    # 事件注入层 (非主要, 仅当用户提供 event_override.json 且本周生效)
    # 受益行业动量加权前置, 利空行业实质排除。无事件文件则完全不干扰自适应。
    ev = load_event_override()
    if ev:
        boost = set(ev.get("boost_industries", []))
        avoid = set(ev.get("avoid_industries", []))
        if verbose:
            print(f"  📌 事件注入生效: 受益={boost or '无'} 规避={avoid or '无'} | {ev.get('note','')}")
        for ind, d in sorted_inds:
            if ind in boost:
                d["avg_chg"] = d["avg_chg"] * EVENT_BOOST_WEIGHT + 5.0  # 加权前置
            elif ind in avoid:
                d["avg_chg"] = EVENT_AVOID_DROP  # 实质排除
        sorted_inds = sorted(ind_mom.items(), key=lambda kv: kv[1]["avg_chg"], reverse=True)

    # 强势主线: 平均涨幅 Top2 行业 (且平均涨幅>0 才算真主线)
    # 过滤掉防御/避险/价值行业(黑名单) — 石油等避险板块不进进攻主线
    main_lines = []
    for ind, d in sorted_inds:
        if ind in DEFENSIVE_INDUSTRY_BLACKLIST:
            continue  # 跳过避险板块, 不当进攻主线
        if d["avg_chg"] <= 0:
            continue  # 排除事件利空置负的行业
        if d["avg_chg"] > 0 and len(main_lines) < 2:
            main_lines.append((ind, d))

    if not main_lines:
        # 所有进攻型行业都在跌, 或无主线 -> 退回稳健组合(不硬冲)
        if verbose:
            skipped = [i for i, _ in sorted_inds if i in DEFENSIVE_INDUSTRY_BLACKLIST]
            print(f"  ⚠️ 上周进攻型行业无明确主线(避险板块 {skipped} 上涨但不计入进攻), "
                  f"进攻退回稳健医疗/电力")
        return _fallback_theme(cfg, verbose)

    # 从主线行业挑 2 只高弹性票(换手率优先, 兼顾涨幅)
    offensive = []
    used_codes = set()
    for ind, d in main_lines:
        # 该行业里挑换手最高或涨幅最高的 1 只(保证不重叠)
        tickers = [t for t in d["tickers"] if t["code"] not in used_codes]
        if not tickers:
            continue
        # 弹性评分: 换手率*0.6 + 涨幅*0.4
        def elastic(t):
            to = t["turnover"] or 0
            return to * 0.6 + max(0, t["chg"]) * 0.4
        best = max(tickers, key=elastic)
        offensive.append(best["code"])
        used_codes.add(best["code"])

    # 若主线只产出 1 只, 从次强行业补 1 只
    if len(offensive) < 2:
        for ind, d in sorted_inds:
            if ind in [m[0] for m in main_lines]:
                continue
            tickers = [t for t in d["tickers"] if t["code"] not in used_codes]
            if tickers:
                best = max(tickers, key=lambda t: (t["turnover"] or 0) * 0.6 + max(0, t["chg"]) * 0.4)
                offensive.append(best["code"])
                used_codes.add(best["code"])
                if len(offensive) >= 2:
                    break

    week_label = datetime.now().strftime("%Y-W%W")
    theme = {
        "week_label": week_label,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "main_lines": [
            {"industry": ind, "avg_chg": d["avg_chg"],
             "top_ticker": d["tickers"][0]["name"] if d["tickers"] else ""}
            for ind, d in main_lines
        ],
        "offensive": offensive,
        "all_industry_rank": [
            {"industry": ind, "avg_chg": d["avg_chg"]}
            for ind, d in sorted_inds[:8]
        ],
        "mode": "auto_theme"  # 自适应主线
    }

    _save(theme)
    if verbose:
        print(f"  🎯 本周进攻主线: " + " / ".join(
            f"{m['industry']}(+{m['avg_chg']}%)" for m in theme["main_lines"]))
        print(f"  🔥 进攻 2 票: {offensive}")
        print(f"  📊 行业涨幅排名 Top8:")
        for r in theme["all_industry_rank"]:
            print(f"     {r['industry']}: {r['avg_chg']:+}%")
    return theme


def _fallback_theme(cfg, verbose):
    """无主线时, 进攻退回医疗(凯莱英)+ 电力(长江电力) 稳健组合"""
    asel = cfg.get("auto_select", {})
    off_pool = {p["code"]: p for p in asel.get("offensive_pool", [])}
    fb = ["002821", "600900"]  # 凯莱英, 长江电力
    fb = [c for c in fb if c in off_pool][:2]
    week_label = datetime.now().strftime("%Y-W%W")
    theme = {
        "week_label": week_label,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "main_lines": [],
        "offensive": fb,
        "all_industry_rank": [],
        "mode": "fallback_stable"  # 无主线, 稳健
    }
    _save(theme)
    if verbose:
        print(f"  🛡️ 进攻退回稳健组合: {fb} (医疗/电力)")
    return theme


def _save(theme):
    try:
        with open(THEME_FILE, "w", encoding="utf-8") as f:
            json.dump(theme, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_last():
    """读取上周主题(供参考, 不强制沿用)"""
    if not os.path.exists(THEME_FILE):
        return None
    try:
        return json.load(open(THEME_FILE, encoding="utf-8"))
    except Exception:
        return None


if __name__ == "__main__":
    import json as _json
    cfg = _json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "strategy_config.json"), encoding="utf-8"))
    print("=" * 55)
    print("每周题材自动识别 (进攻主线)")
    print("=" * 55)
    t = pick_theme(cfg, verbose=True)
    print("\n落盘:", THEME_FILE)
