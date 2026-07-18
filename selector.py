"""
selector.py - 自动选股引擎
从 candidate_pool 批量获取行情/PE/价格分位 -> 三维评分 -> 排序挑 Top N
依赖: market_data.py (腾讯行情)
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market_data as md


def is_defensive_market(cfg):
    """
    趋势过滤(兼容旧调用): 用防御基准(默认沪深300)的 N日MA 判断当前是否下跌趋势。
    返回 (is_defensive, detail) — 二态兼容, 内部调用 market_regime。
    """
    regime, detail = market_regime(cfg)
    return (regime == "weak"), detail


def market_regime(cfg):
    """
    市况三档识别 (v6.7 自适应仓位核心):
      weak   弱势市: 价格 < MA*(1-band)         -> 防御收敛, 进攻压制
      balance 平衡市: MA*(1-band) <= 价格 <= MA*(1+band) -> 标准框架
      bull   强势市: 价格 > MA*(1+band)         -> 防御让位, 进攻加仓博名次
    返回 (regime_str, detail_str)
    """
    bench = cfg.get("auto_select", {}).get("defensive_benchmark", "sh000300")
    ma_days = cfg.get("auto_select", {}).get("defensive_ma_days", 20)
    band = cfg.get("risk", {}).get("regime_band_pct", 3.0) / 100.0  # 默认±3%为平衡带
    try:
        kl = md.get_kline(bench, "day", ma_days + 5)
        if len(kl) < ma_days:
            return "balance", f"基准{ma_days}日数据不足({len(kl)}), 默认平衡市"
        closes = [k["close"] for k in kl[-ma_days:]]
        ma = sum(closes) / len(closes)
        last = closes[-1]
        dev = (last - ma) / ma * 100
        if last < ma * (1 - band):
            return "weak", f"基准{bench} {last:.0f} < MA{ma:.0f}×(1-{band*100:.0f}%)={ma*(1-band):.0f} 偏离{dev:+.1f}% -> 弱势市(防御收敛)"
        elif last > ma * (1 + band):
            return "bull", f"基准{bench} {last:.0f} > MA{ma:.0f}×(1+{band*100:.0f}%)={ma*(1+band):.0f} 偏离{dev:+.1f}% -> 强势市(进攻加仓)"
        else:
            return "balance", f"基准{bench} {last:.0f} 在MA{ma:.0f}±{band*100:.0f}%平衡带内(偏离{dev:+.1f}%) -> 平衡市"
    except Exception as e:
        return "balance", f"趋势判断异常:{e}, 默认平衡市"


def score_one(code, cfg):
    """
    单只股票三维评分(0~1): 低PE + 高热度 + 历史低位
    返回 (score, detail)
    """
    sc = cfg["scoring"]
    rt = md.get_realtime([code]).get(code, {})
    cur, pct = md.price_percentile(code, sc["history_window_days"])

    # 1) PE 维度: 越低越好 (pe_low_cap~pe_high_cap 线性映射)
    pe = rt.get("pe_ttm") or rt.get("pe_dynamic")
    pe_score = 0.5
    if pe is not None and pe > 0:
        span = sc["pe_high_cap"] - sc["pe_low_cap"]
        pe_score = max(0.0, min(1.0, 1.0 - (pe - sc["pe_low_cap"]) / span))

    # 2) 热度维度: 换手率近似 (换手>=10%视为满分)
    to = rt.get("turnover_pct")
    pop_score = 0.5
    if to is not None:
        pop_score = max(0.0, min(1.0, to / 10.0))

    # 3) 历史低位维度: 分位越低越好
    pos_score = 0.5
    if pct is not None:
        pos_score = 1.0 - pct

    w = sc["pe_weight"]
    # v6.1: 防御避险因子(逆势走强=弱市避风港, 权重10%, 从低位维度挤占)
    # 计算近20日相对沪深300的超额收益
    safe_score = 0.5
    try:
        kl = md.get_kline(code, "day", 25)
        if len(kl) >= 20:
            chg20 = (kl[-1]["close"] / kl[-20]["close"] - 1) * 100
            # 弱市(沪深300下跌)中, 标的涨幅越高=避险属性越强
            if chg20 >= 0:
                safe_score = min(1.0, 0.5 + chg20 / 10 * 0.5)  # 0~10% => 0.5~1.0
            else:
                safe_score = max(0.0, 0.5 + chg20 / 10 * 0.5)  # 下跌 => <0.5
    except Exception:
        pass

    # 权重: PE40% + 热度35% + 低位25%(其中20%原低位, 5%避险) — 简化: 低位25%内部已含避险
    score = w * pe_score + sc["popularity_weight"] * pop_score + sc["low_position_weight"] * (0.75 * pos_score + 0.25 * safe_score)
    return score, {
        "code": code,
        "name": rt.get("name"),
        "pe": pe,
        "pe_score": round(pe_score, 3),
        "turnover_pct": to,
        "pop_score": round(pop_score, 3),
        "hist_pct": pct,
        "pos_score": round(pos_score, 3),
        "safe_score": round(safe_score, 3),
        "final_score": round(score, 3),
    }


def select(cfg, top_n=None, verbose=True, defensive_only=False):
    """
    自动选股: 遍历候选池 -> 评分 -> 跨行业分散挑 Top N
    支持趋势模式: 下跌趋势(防御模式)下科技为软偏好(可0只), 否则优先科技
    defensive_only=True: 只从 universe_split.defensive_industries 白名单挑(防御底仓),
                        排除军工/消费电子等进攻题材票误入防御端。
    返回: [detail, ...] 最终选中(已带 industry/tech 标记)
    """
    asel = cfg.get("auto_select", {})
    pool = asel.get("candidate_pool", [])
    top_n = top_n or asel.get("top_n", 5)
    threshold = cfg["scoring"]["buy_score_min"]
    batch = asel.get("max_codes_per_batch", 50)
    min_ind = asel.get("min_industries", 4)
    req_tech = asel.get("require_tech", False)        # 硬约束(默认False)
    prefer_tech = asel.get("prefer_tech", True)        # 软偏好

    # v6.6: 防御端行业白名单过滤
    if defensive_only:
        def_inds = set(cfg.get("universe_split", {}).get("defensive_industries", []))
        pool = [p for p in pool if p.get("industry") in def_inds]
        if verbose:
            print(f"  🛡️ 防御端白名单过滤: 候选降至 {len(pool)} 只 (仅防御行业)")

    # 趋势判断 -> 防御模式
    defensive, trend_msg = is_defensive_market(cfg)
    if verbose:
        print(f"[{datetime.now():%H:%M:%S}] 自动选股: 候选池 {len(pool)} 只, 目标 Top {top_n}, "
              f"阈值 {threshold}, 至少 {min_ind} 行业, 科技硬约束={req_tech}/软偏好={prefer_tech}")
        print(f"  📉 趋势: {trend_msg}")

    ranked = []
    for i in range(0, len(pool), batch):
        chunk = pool[i:i + batch]
        codes = [p["code"] for p in chunk]
        rt_map = md.get_realtime(codes)
        for p in chunk:
            code = p["code"]
            if code in rt_map:
                rt_map[code]["name"] = p["name"]
            _, detail = score_one(code, cfg)
            detail["industry"] = p.get("industry", "未知")
            detail["tech"] = p.get("tech", False)
            if detail.get("pe") is not None or detail.get("hist_pct") is not None:
                ranked.append(detail)

    ranked.sort(key=lambda d: d["final_score"], reverse=True)
    passed = [d for d in ranked if d["final_score"] >= threshold]

    # 跨行业分散: 每个行业只取评分最高的1只(行业冠军), 再从中选TopN
    # 严格保证: 每行业最多1只 + 至少含1只科技
    industry_champ = {}
    for d in passed:  # passed已按评分降序, 同行业先到者即冠军
        ind = d["industry"]
        if ind not in industry_champ:
            industry_champ[ind] = d
    champs = sorted(industry_champ.values(), key=lambda d: d["final_score"], reverse=True)

    chosen = []
    used_ind = set()
    # 科技处理: 硬约束(req_tech)必含1只; 软偏好(prefer_tech)且非防御模式时优先1只;
    #           防御模式(下跌趋势)下科技为出血点, 软偏好失效, 可不选科技
    want_tech = req_tech or (prefer_tech and not defensive)
    if want_tech:
        for d in champs:
            if d["tech"] and d["industry"] not in used_ind:
                chosen.append(d); used_ind.add(d["industry"])
                break
    # 第二轮: 依次取不同行业的冠军, 直至满 top_n
    for d in champs:
        if len(chosen) >= top_n:
            break
        if d["industry"] in used_ind:
            continue
        chosen.append(d); used_ind.add(d["industry"])
    # 第三轮兜底: 若行业数仍不足 min_industries, 放宽允许第2只同行业
    if len(used_ind) < min_ind:
        for d in champs:
            if len(used_ind) >= min_ind or len(chosen) >= top_n:
                break
            chosen.append(d); used_ind.add(d["industry"])

    # 最终按评分排序展示
    chosen.sort(key=lambda d: d["final_score"], reverse=True)

    if verbose:
        print(f"  有效样本: {len(ranked)} | 达标: {len(passed)} | 行业冠军数: {len(champs)} "
              f"| 选中: {len(chosen)} | 行业数: {len(used_ind)}")
        for d in chosen:
            tag = "🔧科技" if d["tech"] else ""
            print(f"  ✅ {d['code']} {d['name']} [{d['industry']}] {tag} 评分={d['final_score']} "
                  f"PE={d['pe']} 分位={d['hist_pct']} 换手={d['turnover_pct']}")
        if champs:
            print("  --- 各行业冠军评分(前10) ---")
            for d in champs[:10]:
                if d not in chosen:
                    print(f"  ·  {d['code']} {d['name']} [{d['industry']}] 评分={d['final_score']}")
    return chosen


def select_offensive(cfg, top_n=1, verbose=True):
    """
    进攻选股: 从 offensive_pool 中选高弹性标的(动量趋势 + 高换手 + 超跌反弹空间)。
    v6.1 升级: 新增"近20日涨幅动量"因子, 适配医疗/电力等有独立行情的主题板块。
    评分: 动量(近20日涨幅)35% + 弹性(换手率)25% + 超跌反弹空间(历史分位)25% + 热度(成交)15%
    返回: [detail, ...] 进攻选中
    """
    asel = cfg.get("auto_select", {})
    pool = asel.get("offensive_pool", [])
    top_n = top_n or asel.get("_offensive_top_n", 1)

    if verbose:
        print(f"[{datetime.now():%H:%M:%S}] 🔥 进攻选股: 候选池 {len(pool)} 只, 目标 Top {top_n}")

    scored = []
    for p in pool:
        code = p["code"]
        rt = md.get_realtime([code]).get(code, {})
        cur, pct = md.price_percentile(code, 250)

        # 动量因子: 近20日涨幅(弱市中独立上涨=有主题资金介入)
        kl = md.get_kline(code, "day", 25)
        momentum_score = 0.5
        chg20 = 0
        if len(kl) >= 20:
            chg20 = (kl[-1]["close"] / kl[-20]["close"] - 1) * 100
            # -10%~+30% 映射到 0.2~1.0, 涨幅越高动量越强
            if chg20 >= 0:
                momentum_score = min(1.0, 0.5 + chg20 / 30 * 0.5)  # 0%~30% => 0.5~1.0
            else:
                momentum_score = max(0.1, 0.5 + chg20 / 20 * 0.4)  # -20%~0% => 0.1~0.5

        # 弹性因子: 换手率
        to = rt.get("turnover_pct") or 0
        elastic_score = min(1.0, to / 8.0) if to else 0.3  # 换手>=8%满分

        # 超跌反弹空间: 分位越低=反弹空间越大(但不能是极端低位)
        bounce_score = 0.5
        if pct is not None:
            if 0.05 <= pct <= 0.40:
                bounce_score = 1.0 - (pct - 0.05) / 0.35 * 0.7  # 0.3~1.0
            elif pct < 0.05:
                bounce_score = 0.4  # 极端低位可能有基本面问题
            else:
                bounce_score = max(0.1, 1.0 - pct)  # 高位递减

        # 热度: 换手率二次方放大
        hot_score = min(1.0, (to / 6.0) ** 1.5) if to else 0.2

        # v6.1 权重: 动量35% + 弹性25% + 反弹25% + 热度15%
        score = 0.35 * momentum_score + 0.25 * elastic_score + 0.25 * bounce_score + 0.15 * hot_score

        detail = {
            "code": code,
            "name": p["name"],
            "industry": p.get("industry", "进攻"),
            "tech": p.get("tech", True),
            "pe": rt.get("pe_ttm"),
            "turnover_pct": to,
            "hist_pct": pct,
            "chg20": round(chg20, 2),
            "final_score": round(score, 3),
            "_offensive": True,
            "_momentum": round(momentum_score, 3),
            "_elastic": round(elastic_score, 3),
            "_bounce": round(bounce_score, 3),
            "_hot": round(hot_score, 3),
        }
        scored.append(detail)

    scored.sort(key=lambda d: d["final_score"], reverse=True)
    chosen = scored[:top_n]

    # v6.1: 行业平衡 — 若TopN都来自同一行业(如全医疗), 强制将末位替换为其他强势行业(如电力)的第二高评分标的
    # 避免单一主题过度集中, 确保"医疗+电力"双主线覆盖
    if len(chosen) >= 2:
        top_ind = chosen[0]["industry"]
        if all(d["industry"] == top_ind for d in chosen):
            # 找非 top_ind 中评分最高的标的替换最后一只
            for alt in scored:
                if alt["industry"] != top_ind:
                    chosen[-1] = alt
                    break

    if verbose:
        print(f"  进攻评分完成: {len(scored)} 只候选")
        for d in chosen:
            print(f"  🔥 {d['code']} {d['name']} [{d['industry']}] 评分={d['final_score']} "
                  f"20日涨幅={d['chg20']}% 分位={d['hist_pct']} "
                  f"动量={d['_momentum']} 弹性={d['_elastic']} 反弹={d['_bounce']}")
        if len(scored) > top_n:
            print("  --- 备选 ---")
            for d in scored[top_n:top_n+4]:
                print(f"    · {d['code']} {d['name']} 评分={d['final_score']} 20日涨幅={d['chg20']}%")

    return chosen


if __name__ == "__main__":
    import json
    cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_config.json"), encoding="utf-8"))
    asel = cfg.get("auto_select", {})
    print("=" * 50)
    print("防御选股:")
    select(cfg, verbose=True)
    print("\n" + "=" * 50)
    print("进攻选股:")
    off_top_n = asel.get("_offensive_top_n", 2)
    select_offensive(cfg, top_n=off_top_n, verbose=True)
