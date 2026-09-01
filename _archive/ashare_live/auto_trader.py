"""
auto_trader.py - mx-moni 条件触发自动买卖引擎 (v2 自动选股版)
策略: 低PE + 高热度 + 历史低位 三维评分 -> 自动选股TopN -> 达标自动买入
卖出: 每涨 step_pct 按比例自动卖出(分批止盈)

用法:
  python3.11 auto_trader.py --mode select   # 仅自动选股评分, 不交易
  python3.11 auto_trader.py --mode once     # 选股+条件检查+可能交易(单次)
  python3.11 auto_trader.py --mode loop     # 盘中循环轮询(交易时段)
  python3.11 auto_trader.py --mode sell     # 仅执行持仓分批止盈检查
  python3.11 auto_trader.py --mode reset    # 周度结算清仓(卖出全部持仓,重置缓存)
"""
import os
import sys
import json
import time
import logging
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market_data as md
import selector
import instrument  # v6.16 品种元数据单一真相源: 手数/时段/降级开关

logger = logging.getLogger(__name__)


def _read_temperature(cfg):
    """读取市场温度计(方案C)。任何异常均返回 None -> 不干预原仓位逻辑。"""
    try:
        import temperature_probe as tp
        return tp.get_market_temperature(cfg)
    except Exception as e:
        logger.warning("温度计读取失败(%s), 退回原仓位逻辑", e)
        return None


def _read_death_cross(cfg):
    """读取多指数周线死叉去风险信号(v6.10)。任何异常均返回 None -> 不干预原仓位逻辑。"""
    try:
        import death_cross as dc
        return dc.get_death_cross(cfg)
    except Exception as e:
        logger.warning("死叉读取失败(%s), 退回原仓位逻辑", e)
        return None


CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_config.json")
# 成本基准缓存落盘路径(跨进程/重启保留, 真实比赛多日交易必需)
COST_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cost_basis.json")

# 已买入标的的"成本基准价"缓存(持久化到文件, 重启不丢)
_cost_basis = {}
# 机动资金已用比例(占30% flex池), 用于加仓额度控制
_flex_used = 0.0
_flex_loaded = False


def load_cost_cache():
    """从文件加载成本基准(重启不丢)。"""
    global _cost_basis, _flex_used, _flex_loaded
    if _flex_loaded:
        return
    try:
        if os.path.exists(COST_CACHE_PATH):
            with open(COST_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                _cost_basis = data.get("cost_basis", {})
                _flex_used = data.get("flex_used", 0.0)
    except Exception:
        pass
    _flex_loaded = True


def save_cost_cache():
    """保存成本基准到文件。"""
    try:
        with open(COST_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"cost_basis": _cost_basis, "flex_used": _flex_used}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def ensure_trade_window(market="A"):
    """
    硬守卫: 非交易时段禁止发出真实下单指令。返回 True 表示可交易。
    v6.16: 支持分市场时段(A/ETF/KZZ 09:30-11:30,13:00-15:00; HK 09:30-12:00,13:00-16:00)。
           无参调用保持 A 股语义, 既有调用点行为不变。
    """
    if not md.is_trade_time(market=market):
        print(f"[{datetime.now():%H:%M:%S}] ⚠️ 非交易时段({market} {instrument.session_of(market)}), "
              f"跳过真实下单(闭市无法排单, 需开盘时段成交)")
        return False
    return True


def resolve_qty(qty, code, cfg, market=None, ctx=""):
    """
    手数取整统一入口(带安全兜底)。

    包裹 instrument.round_qty: 若港股每手股数未登记(UnknownLotError), 打印告警并返回 0
    -> 调用方按"数量不足"跳过, 绝不发废单。这是"宁可不交易, 不可发废单"的落点。
    """
    try:
        return instrument.round_qty(qty, code, cfg, market=market)
    except instrument.UnknownLotError as e:
        print(f"  [{code}] ⛔ {ctx}手数未登记, 拒单: {e}")
        return 0


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def call_mx_moni(text):
    """
    下单通道已停用 —— 纯记账 / 模拟盘模式。

    v6.x 决策: 系统不再向券商发送任何真实委托。所有买入/卖出指令仅记录在
    本地账本(local_records) 与成本基准(_cost_basis) 中, 用于盈亏核算与回测验证。
    原实现通过 subprocess 调起 mx-moni skill 发单, 现整体摘除(零网络请求)。
    """
    return f"[纯记账·模拟盘] 已记录指令(不发送真实下单): {text}"


def _safe_log_trade(mode, code, name, side, price, qty, resp="", note=""):
    """统一封装 local_records.log_trade 调用。

    旧实现 7+ 处 `try: import local_records; log_trade(...); except Exception: pass`
    重复且吞掉所有错误(账本写入失败时静默, 回测数据缺笔不知)。
    抽出统一入口, 内部 except 仅记 warning 不上抛, 不影响交易主流程。
    """
    try:
        import local_records
        local_records.log_trade(mode, code, name, side, price, qty, resp, note)
    except Exception as e:
        logger.warning("local_records.log_trade 写入失败 (%s %s %s): %s", mode, side, code, e)


def buy(detail, cfg, cash_amount, is_add=False):
    """
    触发买入: 限价(当前价)买入。
    数量按 instrument.lot_of 解析的每手股数取整:
        A/ETF 100 股/份 · 可转债 10 张 · 港股逐只不同(per_code, 如小米 200/移动 500)。
    cash_amount: 本次投入金额(元)
    is_add: 是否加仓(计入flex池跟踪)
    """
    global _flex_used
    load_cost_cache()
    code, name = detail["code"], detail.get("name") or detail["code"]
    # v6.16: detail 未带 market 时按代码形态回退推断, 不再无脑默认 "A"
    market = instrument.market_of(code, detail)

    # v6.16 降级开关: 市场不在 market.tradable_markets 白名单 -> 只选不买(观察仓)。
    # 当前 tradable_markets = ["A","ETF","KZZ"], 港股走此分支。
    if not instrument.is_tradable(market, cfg):
        return (f"[{code} {name}] 📋 已选中({market}), 但下单通道未开通"
                f"(market.tradable_markets 不含 {market}), 记为观察仓, 不下单")

    rt = md.get_realtime([code]).get(code, {})
    price = rt.get("price")
    if not price:
        return f"[{code}] 无法获取实时价, 跳过买入"
    qty = resolve_qty(cash_amount / price, code, cfg, market=market, ctx="买入")
    if qty <= 0:
        return f"[{code}] 资金不足或手数不可解析, 跳过"
    kind = "加仓" if is_add else "底仓"
    cmd = f"买入 {code} {price:.2f} {qty}"
    resp = call_mx_moni(cmd)
    if code in _cost_basis:
        # 加仓: 加权平均成本
        old = _cost_basis[code]
        new_qty = old["qty"] + qty
        old["price"] = (old["price"] * old["qty"] + price * qty) / new_qty
        old["qty"] = new_qty
        old.setdefault("market", market)
    else:
        # v6.16: 持久化 market —— 卖出侧只拿得到 code, 不存 market 就无法知道资产类型,
        #        这正是 8 处 //100*100 硬编码的根因。
        _cost_basis[code] = {"price": price, "qty": qty, "sold_ratio": 0.0, "market": market}
    if is_add:
        _flex_used += cash_amount
    save_cost_cache()
    # v6.5: 本地成交记录(连续留存, 不依赖模拟盘刷新)
    _safe_log_trade("once" if not is_add else "add", code, name, "BUY", price, qty, resp, kind)
    return f"[{code} {name}] {kind}买入指令: {cmd}\n响应: {resp}"


def check_stop_loss(code, cfg, defensive=False):
    """
    硬止损: 亏损达阈值则清仓(防跌停无法卖出的事后追杀)。
    防御模式阈值更敏感(-5%); 进攻模式用硬上限(-8%)。
    若当日已跌停(无法卖出), 标记 stop_locked, 不强行下单, 等次日开盘低开再清。
    返回: True 表示已清仓/锁定, 调用方跳过止盈。
    """
    load_cost_cache()
    if code not in _cost_basis:
        return False
    base = _cost_basis[code]
    rt = md.get_realtime([code]).get(code, {})
    price = rt.get("price")
    if not price:
        return False
    loss_pct = (price - base["price"]) / base["price"] * 100
    thr = cfg["risk"].get("stop_loss_pct", -5) if defensive else cfg["risk"].get("stop_loss_hard_pct", -8)
    # loss_pct 为负(亏损). 仅当未破线(loss_pct > thr, 如 -3% > -5%) 才不处理
    if loss_pct > thr:
        return False
    # 已破线(loss_pct <= thr, 如 -6% <= -5%): 进入止损处理
    # 跌停判定: 当前价贴近跌停价, 跌停封死无法卖出
    limit_down = rt.get("limit_down")
    if limit_down and price <= limit_down * 1.005:
        base["stop_locked"] = True
        print(f"  [{code}] 触及止损{loss_pct:.1f}% 但已跌停封死, 锁定 STOP_LOCKED, 等次日开盘清")
        save_cost_cache()
        return True
    # 正常止损清仓 (v6.16 漏钱洞#1: 原 //100*100 使 60 张转债 -> sell_qty=0 静默失败)
    remain_qty = base["qty"] * (1 - base["sold_ratio"])
    market = instrument.market_of(code, base)
    sell_qty = resolve_qty(remain_qty, code, cfg, market=market, ctx="硬止损")
    if sell_qty <= 0:
        return False
    cmd = f"卖出 {code} {price:.2f} {sell_qty}"
    resp = call_mx_moni(cmd)
    print(f"  [{code}] ⛔ 硬止损 亏损{loss_pct:.1f}% 清仓{sell_qty}股\n  指令:{cmd}\n  响应:{resp}")
    del _cost_basis[code]
    save_cost_cache()
    return True


def check_sell(code, cfg):
    """
    阶梯止盈(保名次 + 冲前10): 根据 tiers 阶梯表, 涨幅达档位则卖出对应比例。
    设计: 早期少卖锁利防回撤掉榜; +10%区间保留>=55%仓位吃满冲前10;
          保留尾仓应对极端行情(冲第一500元)。
    兼容旧版 step_pct/portion_per_step 配置(自动转为单档阶梯)。
    """
    load_cost_cache()
    if code not in _cost_basis:
        return None
    rt = md.get_realtime([code]).get(code, {})
    price = rt.get("price")
    base = _cost_basis[code]
    if not price:
        return None
    gain_pct = (price - base["price"]) / base["price"] * 100

    # 解析阶梯表(优先 tiers, 回退旧 step/portion)
    sell = cfg["sell_rules"]
    if sell.get("mode") == "tiered" and sell.get("tiers"):
        tiers = sorted(sell["tiers"], key=lambda t: t["gain_pct"])
    elif sell.get("step_pct") and sell.get("portion_per_step"):
        # 旧版: 多档等距(按3次卖完估算)
        step, por = sell["step_pct"], sell["portion_per_step"]
        tiers = [{"gain_pct": step * (i + 1), "sell_portion": por} for i in range(int(1 / por))]
    else:
        return None

    # 找到当前应触发的最后一个档位(涨幅已越过但尚未卖出的档)
    # base["tier_idx"] 记录已处理到的档位序号
    idx = base.get("tier_idx", 0)
    triggered = None
    while idx < len(tiers) and gain_pct >= tiers[idx]["gain_pct"]:
        triggered = tiers[idx]
        idx += 1
    if triggered is None:
        return None

    # sell_portion = 该档累计卖出占总仓的"绝对比例";
    # 本次实卖 = (本档目标 - 已卖) * 总仓, 取整到100股
    target_cum = triggered["sell_portion"]
    if target_cum <= base["sold_ratio"]:
        base["tier_idx"] = idx  # 已达标, 跳过推进序号
        return None
    # v6.16 漏钱洞#2: 阶梯止盈同样收口到 round_qty(转债 lot=10, 港股逐只 per_code)
    market = instrument.market_of(code, base)
    sell_qty = resolve_qty(base["qty"] * (target_cum - base["sold_ratio"]),
                           code, cfg, market=market, ctx="阶梯止盈")
    if sell_qty <= 0:
        base["tier_idx"] = idx
        return None
    cmd = f"卖出 {code} {price:.2f} {sell_qty}"
    resp = call_mx_moni(cmd)
    base["sold_ratio"] = target_cum
    base["tier_idx"] = idx
    save_cost_cache()
    _safe_log_trade("sell", code, base.get("name", code), "SELL", price, sell_qty, resp,
                    f"止盈+{triggered['gain_pct']}%档")
    remain = (1 - base["sold_ratio"]) * 100
    return (f"[{code}] 盈利{gain_pct:.1f}% 触发+{triggered['gain_pct']}%档, "
            f"卖出{sell_qty}股(累计已卖{target_cum*100:.0f}%, 剩余{remain:.0f}%仓位)\n"
            f"指令:{cmd}\n响应:{resp}")


def weekly_reset(cfg):
    """
    周度结算清仓: 卖出所有持仓(市价), 清空成本缓存。
    比赛一周结算一次, 结算后重置, 下周重新选股建仓。
    非交易时段跳过(闭市无法下单, 需开盘后执行)。
    """
    # v6.16 修复: 缺 global 声明时 `_flex_used = 0.0` 只是局部赋值, 模块级变量不动
    #             -> 机动资金已用比例跨周累积, 持续压制加仓额度。
    global _flex_used
    load_cost_cache()
    if not _cost_basis:
        print("[周度重置] 当前无持仓, 无需清仓")
        return
    if not ensure_trade_window():
        return
    print(f"\n[{datetime.now():%H:%M:%S}] 周度结算清仓, 共 {len(_cost_basis)} 只持仓")
    for code, base in list(_cost_basis.items()):
        rt = md.get_realtime([code]).get(code, {})
        price = rt.get("price")
        if not price:
            print(f"  [{code}] 无实时价, 跳过(下次开盘再清)")
            continue
        # v6.16 漏钱洞#3: 周度清仓收口(原 150 张转债只卖 100, 剩 50 张成孤儿仓)
        remain_qty = base["qty"] * (1 - base["sold_ratio"])
        market = instrument.market_of(code, base)
        sell_qty = resolve_qty(remain_qty, code, cfg, market=market, ctx="周度清仓")
        if sell_qty <= 0:
            continue
        cmd = f"卖出 {code} {price:.2f} {sell_qty}"
        resp = call_mx_moni(cmd)
        print(f"  [{code}] 清仓 {sell_qty} 股\n  指令:{cmd}\n  响应:{resp}")
    _cost_basis.clear()
    _flex_used = 0.0
    save_cost_cache()
    # 同步清空网格状态(周度结算后全仓清0, 下周重建不应继承旧层数)
    try:
        grid_state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".grid_state.json")
        if os.path.exists(grid_state_path):
            os.remove(grid_state_path)
            print("[周度重置] 网格状态(.grid_state.json)已清空")
    except Exception:
        pass
    print("[周度重置] 成本缓存已清空, 下周重新选股")


def _regime_alloc(cfg, regime):
    """读取市况三档仓位模板 (单一真相源: strategy_config.REGIME_ALLOC)。

    M6: 旧实现 `cfg.get("REGIME_ALLOC") or {硬编码}` 把硬编码 fallback 又写回来,
        违背"单一真相源"设计, 配置缺失时静默降级。改为缺失即抛错快速失败。
    """
    alloc = cfg.get("REGIME_ALLOC")
    if not alloc:
        raise ValueError("strategy_config.json 缺少 REGIME_ALLOC 段 (市况三档仓位模板)")
    return alloc.get(regime, alloc["balance"])


def _total_capital(cfg):
    """读取账户总资金 (M5: 旧实现硬编码 1_000_000, 与 grid_trader.py 重复,
    用户实际资金非100万时仓位计算全错)。"""
    acct = cfg.get("account") or {}
    cap = acct.get("capital")
    if cap is None:
        # 向后兼容: 旧 config 无 capital 字段时退回原 100 万默认值, 加日志提醒配置化
        logger.warning("account.capital 未配置, 退回默认 1_000_000 (请在 strategy_config.json 配置化)")
        return 1_000_000
    return float(cap)


def _phase_regime(cfg):
    """阶段 0: 市况识别 + 温度计 + 死叉去风险。返回结构化上下文。"""
    regime, trend_msg = selector.market_regime(cfg)
    defensive = (regime == "weak")
    print(f"  {trend_msg}")

    _temp = _read_temperature(cfg)
    if _temp:
        print(f"  [温度计] 市场温度: {_temp['label']}({_temp['score']:.0f}/100) "
              f"脆弱={_temp['fragile']} VIX参考={_temp['vix_tag']} "
              f"进攻刻度x{_temp['offense_multiplier']:.2f}  [{'影子' if _temp['shadow'] else '生效'}]")

    _dc = _read_death_cross(cfg)
    defense_only = False
    if _dc:
        if _dc.get("triggered"):
            print(f"  [死叉] 大盘结构性去风险: {_dc['count']}/{_dc['available']} 指数周线死叉 "
                  f"(阈值{_dc['threshold']})"
                  + (f" -> 进攻转全防御" if _dc.get("apply") else "  [影子, 不执行]"))
        else:
            print(f"  [死叉] {_dc['label']}: {_dc['detail']}")
        defense_only = bool(_dc.get("apply") and _dc.get("triggered"))

    return {
        "regime": regime,
        "defensive": defensive,
        "defense_only": defense_only,
        "temp": _temp,
        "death_cross": _dc,
    }


def _phase_select(cfg, ctx):
    """阶段 1+2: 防御选股 + 进攻选股。返回 (chosen_def, chosen_off)。"""
    regime = ctx["regime"]
    defense_only = ctx["defense_only"]

    chosen_def = selector.select(cfg, verbose=True, defensive_only=True)
    if not chosen_def:
        print("  防御池无达标标的")

    chosen_off = []
    if not defense_only:
        import weekly_theme
        theme = weekly_theme.pick_theme(cfg, verbose=True)
        if theme.get("offensive"):
            pool_map = {p["code"]: p for p in cfg.get("auto_select", {}).get("candidate_pool", [])}
            off_pool_map = {p["code"]: p for p in cfg.get("auto_select", {}).get("offensive_pool", [])}
            theme_codes = list(theme["offensive"][:2])

            # 弱势市: 若主线票含个股(高波动), 用可转债替代1只作为类进攻底仓
            # H2: 旧表达式 `market=="KZZ" and industry!="可转债" or market=="KZZ"`
            #     运算符优先级 bug 导致条件恒等于 market=="KZZ", industry 过滤是死代码。
            #     且池子里转债 industry 字段就是 "可转债", 旧条件意图(取银行转债)与实现相反。
            #     改为直接用 config.convertible_bond.weak_regime_pick 作为候选。
            if regime == "weak":
                cb_cfg = cfg.get("convertible_bond") or {}
                kzz_picks = cb_cfg.get("weak_regime_pick", ["113050", "113052"])
                kzz_pick = next((c for c in kzz_picks if c in pool_map), None)
                if kzz_pick and theme_codes:
                    theme_codes = [kzz_pick] + theme_codes[:1]  # 可转债 + 1只主线
                    print(f"  🛡️ 弱势市进攻: 可转债替代部分个股暴露 (债底保护)")

            for code in theme_codes[:2]:
                meta = pool_map.get(code) or off_pool_map.get(code) or {
                    "name": code, "industry": "进攻", "tech": True}
                rt = md.get_realtime([code]).get(code, {})
                cur, pct = md.price_percentile(code, 250)
                # L21: 旧实现进攻票直接给 final_score=1.0 绕过 selector 评分,
                #      使 ai_score.augment 的乘数对进攻票失效。改为基于 selector
                #      真实评分 (无评分时退回 0.5 中性, 不再硬塞满分)
                off_score = 0.5
                try:
                    score_val, _ = selector.score_one(code, cfg, rt=rt, kline=None)
                    if score_val and score_val > 0:
                        off_score = score_val
                except Exception:
                    pass
                chosen_off.append({
                    "code": code, "name": meta.get("name", code),
                    "industry": meta.get("industry", "进攻"), "tech": meta.get("tech", True),
                    "market": meta.get("market", "A"),
                    "turnover_pct": rt.get("turnover_pct"), "hist_pct": pct,
                    "final_score": off_score, "_offensive": True,
                    "_theme": theme.get("mode", "auto"), "_regime": regime
                })
            tag = {"weak": "弱势-可转债替代", "balance": "平衡-主线",
                   "bull": "强势-主线+弹性"}[regime]
            print(f"  🔥 进攻采用[{tag}]: {[c['name'] for c in chosen_off]}")
        else:
            chosen_off = selector.select_offensive(cfg, top_n=2, verbose=True)
    else:
        print(f"  🛡️ 死叉去风险: 跳过进攻选股, 本周全防御(进攻仓=0)")

    # v6.14 AI 加权打分 (enabled=false 时 pass-through, 零影响)
    try:
        import ai_score
        if chosen_def:
            chosen_def = ai_score.augment(chosen_def, cfg, tag="defensive")
        if chosen_off:
            chosen_off = ai_score.augment(chosen_off, cfg, tag="offensive")
    except Exception as e:
        print(f"  [ai_score] 模块异常({e}), 跳过 AI 打分, 使用纯规则结果")

    return chosen_def, chosen_off


def _phase_allocate(cfg, ctx, chosen_def, chosen_off):
    """阶段 3: 仓位分配。返回 (base_pct, off_pct, cash_pct)。"""
    regime = ctx["regime"]
    defense_only = ctx["defense_only"]
    _temp = ctx["temp"]

    alloc = _regime_alloc(cfg, regime)
    base_pct = alloc["def"]
    off_pct = alloc["off"]
    cash_pct = alloc["cash"]

    # v6.9 温度计调制: 仅削进攻仓, 释放部分转入现金(防御底仓不动)
    if _temp and _temp.get("apply") and _temp["offense_multiplier"] < 1.0:
        freed = off_pct * (1.0 - _temp["offense_multiplier"])
        off_pct = round(off_pct * _temp["offense_multiplier"], 1)
        cash_pct = round(cash_pct + freed, 1)
    # v6.10 死叉全防御: 触发则进攻仓清零, 释放额度转入防御底仓
    if defense_only:
        freed_off = off_pct
        off_pct = 0.0
        base_pct = round(base_pct + freed_off, 1)
    print(f"  [仓位] 市况: {regime} -> 防御{base_pct}% / 进攻{off_pct}% / 现金{cash_pct}%"
          + (f"  (温度计x{_temp['offense_multiplier']:.2f})" if _temp and _temp.get("apply") else "")
          + ("  🛡️死叉全防御" if defense_only else ""))

    per_def = base_pct / len(chosen_def) if chosen_def else 0
    per_off = off_pct / len(chosen_off) if chosen_off else 0
    if ctx["defensive"]:
        print(f"  \U0001f6e1\ufe0f 防御模式仓位: {len(chosen_def)}只x{per_def:.0f}%={base_pct}%防御 + "
              f"{len(chosen_off)}只x{per_off:.0f}%={off_pct}%进攻 + {cash_pct:.0f}%现金储备(不加仓)")
    else:
        print(f"  \u2694\ufe0f 进攻模式仓位: {len(chosen_def)}只x{per_def:.0f}%={base_pct}%防御 + "
              f"{len(chosen_off)}只x{per_off:.0f}%={off_pct}%进攻 + {cash_pct:.0f}%现金")
    return base_pct, off_pct, cash_pct


def _phase_buy(cfg, chosen_def, chosen_off, base_pct, off_pct):
    """阶段 4+5: 防御底仓 + 进攻底仓 + 机动加仓。"""
    total = _total_capital(cfg)
    # 防御底仓买入
    for d in chosen_def:
        if d["code"] not in _cost_basis:
            amt = base_pct / len(chosen_def) / 100 * total
            print(buy(d, cfg, amt, is_add=False))

    # 进攻底仓买入 (独立标记为 offensive)
    for d in chosen_off:
        if d["code"] not in _cost_basis:
            off_amt = off_pct / len(chosen_off) / 100 * total
            print(buy(d, cfg, off_amt, is_add=False))
            load_cost_cache()
            if d["code"] in _cost_basis:
                _cost_basis[d["code"]]["_offensive"] = True
                save_cost_cache()


def _phase_manage_positions(cfg, ctx):
    """阶段 6: 持仓检查 (止损 + 止盈)。"""
    defensive = ctx["defensive"]
    for code in list(_cost_basis.keys()):
        base = _cost_basis.get(code, {})
        is_offensive = base.get("_offensive", False)
        # 止损: 进攻仓用更宽松的止损线(-10%), 防御仓-5%(防御)/-8%(进攻模式)
        if is_offensive:
            sl_triggered = check_stop_loss_offensive(code, cfg)
        else:
            sl_triggered = check_stop_loss(code, cfg, defensive=defensive)
        if sl_triggered:
            continue  # 已止损, 跳过止盈
        msg = check_sell(code, cfg)
        if msg:
            print(msg)


def _phase_add_positions(cfg, ctx):
    """阶段 5: 机动加仓 (仅进攻模式且非防御/非死叉去风险)。

    M7: 进攻仓加仓阈值 -5/+5 旧硬编码, 现可从 config.buy_rules.add_position
        的 offensive_on_pullback_pct / offensive_on_breakout_pct 配置。
    """
    if ctx["defensive"] or ctx["defense_only"]:
        return
    total = _total_capital(cfg)
    add_rule = cfg.get("buy_rules", {}).get("add_position", {})
    max_add = add_rule.get("max_add_times_per_stock", 2)
    flex_total = cfg["risk"].get("flex_position_pct", 20) / 100 * total
    # 进攻仓加仓阈值可配置, 未配置则退回旧默认 (-5/+5)
    off_pull = add_rule.get("offensive_on_pullback_pct", -5)
    off_brk = add_rule.get("offensive_on_breakout_pct", 5)
    for code, base in list(_cost_basis.items()):
        add_cnt = base.get("add_cnt", 0)
        is_off = base.get("_offensive", False)
        if add_cnt >= max_add or _flex_used >= flex_total:
            continue
        rt = md.get_realtime([code]).get(code, {})
        price = rt.get("price")
        if not price:
            continue
        chg = (price - base["price"]) / base["price"] * 100
        # 进攻仓加仓条件更宽松(给波动空间): 默认回撤-5%或突破+5%
        pull = off_pull if is_off else add_rule.get("on_pullback_pct", -3)
        brk = off_brk if is_off else add_rule.get("on_breakout_pct", 3)
        if chg <= pull or chg >= brk:
            amt = flex_total * 0.5
            tag = "[进攻]" if is_off else ""
            # v6.16: 加仓 detail 必须带 market, 否则 buy() 里手数退化为 100
            print(buy({"code": code, "name": base.get("name", code),
                       "market": instrument.market_of(code, base)},
                      cfg, amt, is_add=True))
            base["add_cnt"] = add_cnt + 1


def run_once(cfg, do_trade=True):
    """单次策略执行 (v5 路线B: 稳中求进)。

    H6: 旧实现是 ~210 行 God Function 完成市况/温度/死叉/选股/分配/买入/加仓/
        止损/止盈/网格/再平衡, 圈复杂度极高且零测试。拆成 6 个 _phase_* 函数,
        run_once 只做编排, 每阶段返回可断言的中间结果, 便于单测。
    """
    print(f"\n[{datetime.now():%H:%M:%S}] 单次策略执行 (v5 路线B: 稳中求进)")
    load_cost_cache()

    ctx = _phase_regime(cfg)
    chosen_def, chosen_off = _phase_select(cfg, ctx)
    all_chosen = (chosen_def or []) + (chosen_off or [])
    if not all_chosen:
        print("  本轮无任何标的")
        return

    base_pct, off_pct, _ = _phase_allocate(cfg, ctx, chosen_def, chosen_off)

    if not do_trade:
        return

    # 硬守卫: 非交易时段禁止真实下单
    if not ensure_trade_window():
        return

    _phase_buy(cfg, chosen_def, chosen_off, base_pct, off_pct)
    _phase_add_positions(cfg, ctx)
    _phase_manage_positions(cfg, ctx)

    # 7) 网格交易(v6.3): 用16%现金储备对高波动进攻票做隔日网格, 每天触发一次
    if cfg.get("grid", {}).get("enable", False):
        import grid_trader
        print(f"\n  ---- 网格巡检 (v6.3) ----")
        for gl in grid_trader.grid_once(cfg, do_trade=do_trade):
            print(f"  {gl}")

    # 8) 多尺度再平衡(v6.4): 防御内部再平衡 + 攻防轮动, 落袋慢涨利润
    if cfg.get("rebalance", {}).get("enable", False):
        import rebalance
        for rl in rebalance.rebalance_once(cfg, do_trade=do_trade):
            print(rl)


def check_stop_loss_offensive(code, cfg):
    """
    进攻仓独立止损: -10% 硬止损(比防守仓宽松, 给高弹性标的波动空间)。
    其余逻辑与 check_stop_loss 一致(跌停锁定等)。
    返回: True 表示已清仓/锁定
    """
    load_cost_cache()
    if code not in _cost_basis:
        return False
    base = _cost_basis[code]
    rt = md.get_realtime([code]).get(code, {})
    price = rt.get("price")
    if not price:
        return False
    loss_pct = (price - base["price"]) / base["price"] * 100
    thr = cfg["risk"].get("offensive_stop_loss_pct", -10)  # 默认-10%
    if loss_pct > thr:
        return False
    # 跌停锁定
    limit_down = rt.get("limit_down")
    if limit_down and price <= limit_down * 1.005:
        base["stop_locked"] = True
        print(f"  [{code}] 🔥进攻仓 触及止损{loss_pct:.1f}% 但已跌停封死, 锁定STOP_LOCKED")
        save_cost_cache()
        return True
    # 正常止损清仓 (v6.16 漏钱洞#4: 进攻仓止损同源收口)
    remain_qty = base["qty"] * (1 - base["sold_ratio"])
    market = instrument.market_of(code, base)
    sell_qty = resolve_qty(remain_qty, code, cfg, market=market, ctx="进攻仓止损")
    if sell_qty <= 0:
        return False
    cmd = f"卖出 {code} {price:.2f} {sell_qty}"
    resp = call_mx_moni(cmd)
    print(f"  [{code}] 🔥进攻仓 硬止损 亏损{loss_pct:.1f}% 清仓{sell_qty}股\n  指令:{cmd}\n  响应:{resp}")
    del _cost_basis[code]
    save_cost_cache()
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="select", choices=["select", "once", "loop", "sell", "reset", "grid", "rebalance"])
    args = ap.parse_args()
    cfg = load_config()

    if args.mode == "select":
        selector.select(cfg, verbose=True, defensive_only=True)
    elif args.mode == "once":
        load_cost_cache()
        run_once(cfg, do_trade=True)
    elif args.mode == "sell":
        load_cost_cache()
        if not ensure_trade_window():
            return
        for code in list(_cost_basis.keys()):
            msg = check_sell(code, cfg)
            if msg:
                print(msg)
    elif args.mode == "reset":
        load_cost_cache()
        weekly_reset(cfg)
    elif args.mode == "grid":
        load_cost_cache()
        import grid_trader
        if not ensure_trade_window():
            return
        for gl in grid_trader.grid_once(cfg, do_trade=True):
            print(gl)
    elif args.mode == "rebalance":
        load_cost_cache()
        import rebalance
        if not ensure_trade_window():
            return
        for rl in rebalance.rebalance_once(cfg, do_trade=True):
            print(rl)
    elif args.mode == "loop":
        print(f"进入盘中循环(交易时段每{cfg['polling']['quote_interval_sec']}秒检查) Ctrl+C退出")
        iv = cfg["polling"]["quote_interval_sec"]
        while True:
            if md.is_trade_time():
                # M26: 单轮异常隔离, 避免某轮行情炸裂/选股异常杀死整个 loop
                try:
                    run_once(cfg, do_trade=True)
                except Exception as e:
                    logger.exception("loop run_once 单轮异常, 跳过本轮: %s", e)
            else:
                print(f"[{datetime.now():%H:%M:%S}] 非交易时段, 等待...")
            time.sleep(iv)


if __name__ == "__main__":
    main()

