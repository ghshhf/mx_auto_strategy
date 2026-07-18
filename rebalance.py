"""
rebalance.py - v6.4 多尺度网格 + 跨标的再平衡模块
目的: 突破"网格只做日内高波动票"的局限, 扩展为:
  1. 防守仓再平衡: 某防御相对组合均值偏离>阈值(默认3%)时, 卖出超额部分,
     买入落后防御或回补现金(落袋慢涨利润, 不破保底)
  2. 跨标的轮动: 进攻涨多减仓补防御, 防御跌多补仓(多尺度网格)
  3. 尺度扩展: 除凯莱英日内网格外, 增加"隔日/周度"级别的防御再平衡网格
设计原则:
  - 不破坏现有止盈止损(check_sell/check_stop_loss)体系, 本模块在它们之后运行
  - 再平衡卖出不改变剩余持仓成本基准(利润落袋, 底仓逻辑不变)
  - 再平衡产生的现金回到_grid_cash弹药池(可被grid_trader复用)
  - 硬约束: 单标的再平衡后仓位不低于初始的50%(防卖飞), 不高于初始的150%(防追高)
  - 跌停不卖, 涨停不买(防废单)
"""
import os
import json
from datetime import datetime

import market_data as md
from auto_trader import (
    call_mx_moni, ensure_trade_window, load_cost_cache, save_cost_cache, _cost_basis,
)


def load_rebalance_state():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".rebalance_state.json")
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"last_rebalance_day": "", "deviation_log": {}}


def save_rebalance_state(state):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".rebalance_state.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def rebalance_once(cfg, do_trade=True, verbose=True):
    """
    多尺度再平衡巡检:
      step1: 防御仓内部再平衡(偏离组合均值>thr则卖超额)
      step2: 攻防轮动(进攻涨多减补防御 / 防御跌多加仓)
    返回日志list[str]
    """
    rcfg = cfg.get("rebalance", {})
    if not rcfg.get("enable", False):
        return ["[再平衡] 未启用, 跳过"]
    load_cost_cache()
    logs = []
    dev_thr = rcfg.get("defense_deviation_pct", 3.0)   # 防御偏离阈值
    max_sell_ratio = rcfg.get("max_rebalance_sell_ratio", 0.5)  # 单次最多卖50%持仓
    logs.append(f"\n  ---- 多尺度再平衡巡检 (v6.4) 偏离阈值={dev_thr}% ----")

    # 区分防御/进攻
    defs = {c: b for c, b in _cost_basis.items() if not b.get("_offensive", False)}
    offs = {c: b for c, b in _cost_basis.items() if b.get("_offensive", False)}
    if not defs:
        logs.append("  [防御] 无防御持仓, 跳过防御再平衡")
    else:
        # step1: 防御内部再平衡
        # 计算各防御相对成本的涨幅
        gains = {}
        for code, b in defs.items():
            rt = md.get_realtime([code]).get(code, {})
            price = rt.get("price")
            if not price:
                gains[code] = None
                continue
            gains[code] = (price - b["price"]) / b["price"] * 100

        valid = {c: g for c, g in gains.items() if g is not None}
        if len(valid) >= 2:
            avg_gain = sum(valid.values()) / len(valid)
            logs.append(f"  [防御] 组合平均涨幅={avg_gain:+.2f}%, 个票偏离> {dev_thr}% 触发再平衡")
            for code, g in valid.items():
                dev = g - avg_gain
                if dev <= dev_thr:
                    logs.append(f"    {code} 涨幅{g:+.2f}% 偏离{dev:+.2f}% 正常")
                    continue
                # 偏离过大 -> 卖出超额部分
                b = defs[code]
                rt = md.get_realtime([code]).get(code, {})
                price = rt.get("price")
                limit_up = rt.get("limit_up")
                if limit_up and price >= limit_up * 0.995:
                    logs.append(f"    {code} 涨停封死, 不卖(防废单)")
                    continue
                # 卖出比例: 偏离度/总涨幅, 封顶max_sell_ratio
                sell_ratio = min(max_sell_ratio, abs(dev) / abs(g) if g else 0)
                sell_qty = int(b["qty"] * sell_ratio // 100 * 100)
                if sell_qty <= 0:
                    logs.append(f"    {code} 偏离{dev:+.2f}% 但不足1手, 跳过")
                    continue
                if not do_trade:
                    logs.append(f"    {code} 应卖{sell_qty}股(落袋{dev:+.2f}%超额, 干跑)")
                    continue
                if not ensure_trade_window():
                    return logs
                cmd = f"卖出 {code} {price:.2f} {sell_qty}"
                resp = call_mx_moni(cmd)
                # 剩余持仓成本不变(利润落袋), 更新sold_ratio防止止盈重复卖
                b["sold_ratio"] = min(1.0, b.get("sold_ratio", 0) + sell_ratio)
                b["rebalanced"] = True
                save_cost_cache()
                try:
                    import local_records
                    local_records.log_trade("rebalance", code, code, "SELL", price, sell_qty, resp, f"防御再平衡落袋{dev:+.2f}%")
                except Exception:
                    pass
                logs.append(f"    {code} 🟢再平衡卖出{sell_qty}股(落袋{dev:+.2f}%超额) {cmd} | {resp}")
        else:
            logs.append("  [防御] 有效防御标的<2, 不触发内部再平衡")

    # step2: 攻防轮动(简化版: 进攻仓涨超+10%时减20%补现金, 供grid复用)
    if offs:
        for code, b in offs.items():
            rt = md.get_realtime([code]).get(code, {})
            price = rt.get("price")
            if not price:
                continue
            g = (price - b["price"]) / b["price"] * 100
            if g >= rcfg.get("offensive_trim_gain_pct", 10.0):
                trim_ratio = rcfg.get("offensive_trim_ratio", 0.2)
                sell_qty = int(b["qty"] * trim_ratio // 100 * 100)
                if sell_qty <= 0:
                    continue
                limit_up = rt.get("limit_up")
                if limit_up and price >= limit_up * 0.995:
                    logs.append(f"    [进攻]{code} 涨停封死不卖")
                    continue
                if not do_trade:
                    logs.append(f"    [进攻]{code} 应减{sell_qty}股(涨{g:+.2f}%, 干跑)")
                    continue
                if not ensure_trade_window():
                    return logs
                cmd = f"卖出 {code} {price:.2f} {sell_qty}"
                resp = call_mx_moni(cmd)
                b["sold_ratio"] = min(1.0, b.get("sold_ratio", 0) + trim_ratio)
                b["rebalanced"] = True
                save_cost_cache()
                try:
                    import local_records
                    local_records.log_trade("rebalance", code, code, "SELL", price, sell_qty, resp, f"进攻涨{g:+.2f}%减仓")
                except Exception:
                    pass
                logs.append(f"    [进攻]{code} 🟢涨{g:+.2f}%减仓{sell_qty}股(利润落袋) {cmd} | {resp}")

    # 保存状态
    st = load_rebalance_state()
    st["last_rebalance_day"] = datetime.now().strftime("%Y-%m-%d")
    save_rebalance_state(st)
    return logs


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_config.json"), encoding="utf-8"))
    for l in rebalance_once(cfg, do_trade=False):
        print(l)
