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
import argparse
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market_data as md
import selector


def _read_temperature(cfg):
    """读取市场温度计(方案C)。任何异常均返回 None -> 不干预原仓位逻辑。"""
    try:
        import temperature_probe as tp
        return tp.get_market_temperature(cfg)
    except Exception as e:
        print(f"  [温度计] 读取失败({e}), 退回原仓位逻辑")
        return None


def _read_concentration(cfg):
    """读取公募基金行业集中度探针(防御端)。任何异常均返回 None -> 不干预原仓位逻辑。"""
    try:
        import concentration_probe as cp
        return cp.get_fund_concentration(cfg)
    except Exception as e:
        print(f"  [集中度] 读取失败({e}), 退回原仓位逻辑")
        return None

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_config.json")
MX_MONI_PY = "/root/.codebuddy/skills/mx-moni/mx_moni.py"
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


def ensure_trade_window():
    """硬守卫: 非交易时段禁止发出真实下单指令。返回 True 表示可交易。"""
    if not md.is_trade_time():
        print(f"[{datetime.now():%H:%M:%S}] ⚠️ 非交易时段, 跳过真实下单(闭市无法排单, 需开盘时段成交)")
        return False
    return True


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def call_mx_moni(text):
    """调用 mx_moni skill 执行一句话指令(买入/卖出/查询)。"""
    env = os.environ.copy()
    env["MX_APIKEY"] = os.environ.get("MX_APIKEY", "")
    env["MX_API_URL"] = env.get("MX_API_URL", "https://mkapi2.dfcfs.com/finskillshub")
    try:
        out = subprocess.run(
            ["python3.11", MX_MONI_PY, text],
            capture_output=True, text=True, timeout=60, env=env
        )
        return out.stdout.strip() or out.stderr.strip()
    except Exception as e:
        return f"调用mx_moni失败: {e}"


def buy(detail, cfg, cash_amount, is_add=False):
    """
    触发买入: 限价(当前价)买入。
    股票: 数量取整到100股; 可转债(KZZ): 1手=10张, 取整到10。
    cash_amount: 本次投入金额(元)
    is_add: 是否加仓(计入flex池跟踪)
    """
    global _flex_used
    load_cost_cache()
    code, name = detail["code"], detail.get("name") or detail["code"]
    market = detail.get("market", "A")
    rt = md.get_realtime([code]).get(code, {})
    price = rt.get("price")
    if not price:
        return f"[{code}] 无法获取实时价, 跳过买入"
    # 交易单位: 股票100股/手, 可转债10张/手(1张=100元面值)
    unit = 10 if market == "KZZ" else 100
    qty = int(cash_amount // price // unit * unit)
    if qty <= 0:
        return f"[{code}] 资金不足, 跳过"
    kind = "加仓" if is_add else "底仓"
    cmd = f"买入 {code} {price:.2f} {qty}"
    resp = call_mx_moni(cmd)
    if code in _cost_basis:
        # 加仓: 加权平均成本
        old = _cost_basis[code]
        new_qty = old["qty"] + qty
        old["price"] = (old["price"] * old["qty"] + price * qty) / new_qty
        old["qty"] = new_qty
    else:
        _cost_basis[code] = {"price": price, "qty": qty, "sold_ratio": 0.0}
    if is_add:
        _flex_used += cash_amount
    save_cost_cache()
    # v6.5: 本地成交记录(连续留存, 不依赖模拟盘刷新)
    try:
        import local_records
        local_records.log_trade("once" if not is_add else "add", code, name, "BUY", price, qty, resp, kind)
    except Exception:
        pass
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
    # 正常止损清仓
    remain_qty = base["qty"] * (1 - base["sold_ratio"])
    sell_qty = int(remain_qty // 100 * 100)
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
    sell_qty = int(base["qty"] * (target_cum - base["sold_ratio"]) // 100 * 100)
    if sell_qty <= 0:
        base["tier_idx"] = idx
        return None
    cmd = f"卖出 {code} {price:.2f} {sell_qty}"
    resp = call_mx_moni(cmd)
    base["sold_ratio"] = target_cum
    base["tier_idx"] = idx
    save_cost_cache()
    try:
        import local_records
        local_records.log_trade("sell", code, base.get("name", code), "SELL", price, sell_qty, resp, f"止盈+{triggered['gain_pct']}%档")
    except Exception:
        pass
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
        remain_qty = base["qty"] * (1 - base["sold_ratio"])
        sell_qty = int(remain_qty // 100 * 100)
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


def run_once(cfg, do_trade=True):
    print(f"\n[{datetime.now():%H:%M:%S}] 单次策略执行 (v5 路线B: 稳中求进)")
    load_cost_cache()

    # 0) 市况三档识别 (v6.7 自适应仓位)
    regime, trend_msg = selector.market_regime(cfg)
    defensive = (regime == "weak")
    print(f"  {trend_msg}")

    # v6.9 市场冷热温度计(方案C): 仅作"进攻时机刻度", 不硬砍防御底仓
    _temp = _read_temperature(cfg)
    if _temp:
        print(f"  [温度计] 市场温度: {_temp['label']}({_temp['score']:.0f}/100) "
              f"脆弱={_temp['fragile']} VIX参考={_temp['vix_tag']} "
              f"进攻刻度x{_temp['offense_multiplier']:.2f}  [{'影子' if _temp['shadow'] else '生效'}]")

    # v6.9+ 公募基金行业集中度探针(防御端): 监测全市场/公募对少数行业的抱团集中度
    _conc = _read_concentration(cfg)
    if _conc:
        hinfo = ""
        if _conc.get("holdings_available"):
            top = _conc.get("holdings_top_industries", [])[:3]
            hinfo = "\n          [真实持仓层 {}只基金] ".format(_conc.get("holdings_fund_count", 0)) \
                    + ", ".join(f"{k}({v}%)" for k, v in top)
        print(f"  [集中度] 行业集中度: {_conc['label']}({_conc['score']:.0f}/100) "
              f"科技簇={_conc['hot_cluster_share_pct']:.1f}% "
              f"防御收紧x{_conc['defensive_tighten']:.2f}  [{'影子' if _conc['shadow'] else '生效'}]"
              + (f"{hinfo}" if hinfo else ""))

    # 1) 防御选股: 从防御行业白名单选 Top N (低beta跨行业, 排除进攻题材票)
    chosen_def = selector.select(cfg, verbose=True, defensive_only=True)
    if not chosen_def:
        print("  防御池无达标标的")

    # 2) 进攻选股: 市况依赖 (v6.7)
    #    weak   -> 优先可转债(债底保护, 弱势类进攻)
    #    balance-> 本周自适应主线(个股/港股/ETF)
    #    bull   -> 本周主线 + 高弹性(可转债/港股/ETF弹性标的), 博名次
    import weekly_theme
    theme = weekly_theme.pick_theme(cfg, verbose=True)
    chosen_off = []
    if theme.get("offensive"):
        pool_map = {p["code"]: p for p in cfg.get("auto_select", {}).get("candidate_pool", [])}
        off_pool_map = {p["code"]: p for p in cfg.get("auto_select", {}).get("offensive_pool", [])}
        theme_codes = theme["offensive"][:2]

        # 弱势市: 若主线票含个股(高波动), 用可转债替代1只作为类进攻底仓
        if regime == "weak":
            kzz = [p["code"] for p in cfg.get("auto_select", {}).get("candidate_pool", [])
                   if p.get("market") == "KZZ" and p.get("industry") != "可转债" or
                   (p.get("market") == "KZZ")]
            # 取流动性最好的银行转债(南银/兴业)其一
            kzz_pick = next((c for c in ["113050", "113052"] if c in kzz), None)
            if kzz_pick and theme_codes:
                theme_codes = [kzz_pick] + theme_codes[:1]  # 可转债 + 1只主线, 降低纯股暴露
                print(f"  🛡️ 弱势市进攻: 可转债替代部分个股暴露 (债底保护)")

        for code in theme_codes[:2]:
            meta = pool_map.get(code) or off_pool_map.get(code) or {"name": code, "industry": "进攻", "tech": True}
            rt = md.get_realtime([code]).get(code, {})
            cur, pct = md.price_percentile(code, 250)
            chosen_off.append({
                "code": code, "name": meta.get("name", code),
                "industry": meta.get("industry", "进攻"), "tech": meta.get("tech", True),
                "market": meta.get("market", "A"),
                "turnover_pct": rt.get("turnover_pct"), "hist_pct": pct,
                "final_score": 1.0, "_offensive": True, "_theme": theme.get("mode", "auto"),
                "_regime": regime
            })
        tag = {"weak": "弱势-可转债替代", "balance": "平衡-主线", "bull": "强势-主线+弹性"}[regime]
        print(f"  🔥 进攻采用[{tag}]: {[c['name'] for c in chosen_off]}")
    else:
        chosen_off = selector.select_offensive(cfg, top_n=2, verbose=True)

    all_chosen = (chosen_def or []) + (chosen_off or [])
    if not all_chosen:
        print("  本轮无任何标的")
        return

    # 仓位分配 (v6.7 市况自适应): 弱势收敛进攻/强势加仓博名次
    total = 1_000_000
    # 三档仓位模板 (防御% / 进攻% / 现金%): 和为100
    REGIME_ALLOC = {
        "weak":    {"def": 60, "off": 24, "cash": 16},  # 弱势: 守, 不赌
        "balance": {"def": 54, "off": 30, "cash": 16},  # 平衡: 标准框架
        "bull":    {"def": 44, "off": 40, "cash": 16},  # 强势: 攻, 博名次
    }
    alloc = REGIME_ALLOC.get(regime, REGIME_ALLOC["balance"])
    base_pct = alloc["def"]
    off_pct = alloc["off"]
    cash_pct = alloc["cash"]
    # v6.9 温度计调制: 仅削进攻仓, 释放部分转入现金(防御底仓不动)
    if _temp and _temp.get("apply") and _temp["offense_multiplier"] < 1.0:
        freed = off_pct * (1.0 - _temp["offense_multiplier"])
        off_pct = round(off_pct * _temp["offense_multiplier"], 1)
        cash_pct = round(cash_pct + freed, 1)

    # v6.9+ 公募基金行业集中度探针(防御端): 市场整体拥挤 -> 收紧总风险敞口(防御+进攻按比例减, 释放转现金)
    conc_note = ""
    if _conc and _conc.get("apply") and _conc["defensive_tighten"] < 1.0:
        tighten = _conc["defensive_tighten"]
        gross = base_pct + off_pct
        freed_g = round(gross * (1.0 - tighten), 1)
        base_pct = round(base_pct * tighten, 1)
        off_pct = round(off_pct * tighten, 1)
        cash_pct = round(cash_pct + freed_g, 1)
        conc_note = f"  (集中度x{tighten:.2f} 总敞口{gross:.0f}->{round(gross*tighten,1):.0f}%)"
    print(f"  [仓位] 市况: {regime} -> 防御{base_pct}% / 进攻{off_pct}% / 现金{cash_pct}%"
          + (f"  (温度计x{_temp['offense_multiplier']:.2f})" if _temp and _temp.get("apply") else "")
          + conc_note)

    per_def = base_pct / len(chosen_def) if chosen_def else 0   # 每只防御仓金额占比
    per_off = off_pct / len(chosen_off) if chosen_off else 0   # 每只进攻仓金额占比(v6: 2只均分30%)
    off_amt_total = off_pct / 100 * total                      # 进攻仓总金额

    if defensive:
        print(f"  \U0001f6e1\ufe0f 防御模式仓位: {len(chosen_def)}只x{per_def:.0f}%={base_pct}%防御 + "
              f"{len(chosen_off)}只x{per_off:.0f}%={off_pct}%进攻 + {cash_pct:.0f}%现金储备(不加仓)")
    else:
        print(f"  \u2694\ufe0f 进攻模式仓位: {len(chosen_def)}只x{per_def:.0f}%={base_pct}%防御 + "
              f"{len(chosen_off)}只x{per_off:.0f}%={off_pct}%进攻 + {cash_pct:.0f}%现金")

    if not do_trade:
        return

    # 硬守卫: 非交易时段禁止真实下单
    if not ensure_trade_window():
        return

    # 3) 防御底仓买入
    for d in chosen_def:
        if d["code"] not in _cost_basis:
            amt = per_def / 100 * total
            print(buy(d, cfg, amt, is_add=False))

    # 4) 进攻底仓买入 (独立标记为 offensive, v6: 多只进攻均分)
    for d in chosen_off:
        if d["code"] not in _cost_basis:
            off_amt = per_off / 100 * total
            print(buy(d, cfg, off_amt, is_add=False))
            # 标记为进攻仓
            load_cost_cache()
            if d["code"] in _cost_basis:
                _cost_basis[d["code"]]["_offensive"] = True
                save_cost_cache()

    # 5) 机动加仓(仅进攻模式且非防御): 防御模式不加仓
    if not defensive:
        add_rule = cfg.get("buy_rules", {}).get("add_position", {})
        max_add = add_rule.get("max_add_times_per_stock", 2)
        flex_total = cfg["risk"].get("flex_position_pct", 20) / 100 * total
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
            # 进攻仓加仓条件更宽松(给波动空间): 回撤-5%或突破+5%
            pull = add_rule.get("on_pullback_pct", -3) if not is_off else -5
            brk = add_rule.get("on_breakout_pct", 3) if not is_off else 5
            if chg <= pull or chg >= brk:
                amt = flex_total * 0.5
                tag = "[进攻]" if is_off else ""
                print(buy({"code": code, "name": base.get("name", code)}, cfg, amt, is_add=True))
                base["add_cnt"] = add_cnt + 1

    # 6) 持仓检查: 止损(区分防御/进攻) + 止盈(阶梯)
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
    # 正常止损清仓
    remain_qty = base["qty"] * (1 - base["sold_ratio"])
    sell_qty = int(remain_qty // 100 * 100)
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
        print("进入盘中循环(交易时段每%d秒检查) Ctrl+C退出" % cfg["polling"]["quote_interval_sec"])
        iv = cfg["polling"]["quote_interval_sec"]
        while True:
            if md.is_trade_time():
                run_once(cfg, do_trade=True)
            else:
                print(f"[{datetime.now():%H:%M:%S}] 非交易时段, 等待...")
            time.sleep(iv)


if __name__ == "__main__":
    main()

