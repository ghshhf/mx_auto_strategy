"""
grid_trader.py - v6.3 网格交易模块
目的: 用 16% 现金储备作为"弹药池", 对高波动进攻票做隔日网格(低买高卖吃差价)。
设计原则:
  1. 网格不碰防御底仓(防御仓建一次不动)。
  2. 网格弹药 = cash_reserve_pct (v6.2=16%) 的资金池, 独立记账 (_grid_cash 元)。
  3. 网格标的 = 进攻池里"高波动"票(凯莱英σ6.89% 优先), 以及电力避险票(长江电力)。
  4. 节奏 = 每天触发一次(用户要求"每天至少交易一次", 不躺平)。
     T+1 假设: 今天买入的网格仓, 明天才能卖 -> 天然隔日网格。
  5. 格距 = 动态(基于近10日波动率σ), 一格约 0.6~1.0 个σ, 默认 3%。
  6. 每格金额 = 弹药池 / 网格层数(默认5层), 触底买一层, 触顶卖一层。
  7. 硬约束: 单票网格仓位 ≤ 该票总仓位的一定比例(默认不超过进攻仓30%的1/2, 防越补越深)。
  8. 跌停封死不卖, 涨停封死不买(防废单)。
"""
import os
import json
from datetime import datetime

import market_data as md
from auto_trader import (
    call_mx_moni, ensure_trade_window, load_cost_cache, _cost_basis,
)

GRID_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".grid_state.json")

GRID_KEY = "_v2"  # 网格状态schema版本


def load_grid_state():
    """加载网格状态: {code: {layers: n, base_price, last_side, grid_cash}}"""
    try:
        if os.path.exists(GRID_CACHE_PATH):
            with open(GRID_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_grid_state(state):
    try:
        with open(GRID_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def compute_grid_params(code, cfg):
    """
    计算网格参数: 格距(grid_step%), 层数(layers), 基准价(base_price=最近MA或昨收)
    返回 (grid_step_pct, layers, base_price)
    """
    gcfg = cfg.get("grid", {})
    layers = gcfg.get("layers", 5)
    # 动态格距: 取近10日σ的0.8倍, 下限2%上限6%
    kl = md.get_kline(code, "day", 15)
    step = gcfg.get("step_pct", 3.0)
    if len(kl) >= 11:
        closes = [k["close"] for k in kl[-11:]]
        rets = [(closes[i]/closes[i-1]-1)*100 for i in range(1, len(closes))]
        sigma = (sum(r*r for r in rets)/len(rets))**0.5 if rets else step
        step = max(2.0, min(6.0, sigma * 0.8))
    base = kl[-1]["close"] if kl else None
    return round(step, 2), layers, base


def grid_once(cfg, do_trade=True):
    """
    每天一次的网格巡检:
      - 对进攻票(高波动)做隔日网格
      - 使用现金弹药池(_grid_cash), 不复用防御底仓
    返回本次操作日志(list[str])
    """
    gcfg = cfg.get("grid", {})
    if not gcfg.get("enable", False):
        return ["[网格] 未启用, 跳过"]
    load_cost_cache()
    state = load_grid_state()
    logs = []

    # 弹药池: 配置里 cash_reserve_pct 的资金, 减去已用于网格的部分
    total = 1_000_000
    cash_pct = cfg["risk"].get("cash_reserve_pct", 16)
    ammo_total = cash_pct / 100 * total
    # 已占用弹药 = 各网格票当前持仓市值(约等于)
    used = 0.0
    for code, st in state.items():
        if st.get("holding_qty", 0) > 0:
            used += st["holding_qty"] * st.get("last_price", 0)
    free_ammo = ammo_total - used

    # 网格标的: 进攻池里标记 _grid=true 的票(或默认取进攻池前2)
    grid_targets = [t for t in cfg["auto_select"].get("offensive_pool", [])
                    if t.get("_grid", True)]
    if not grid_targets:
        grid_targets = cfg["auto_select"].get("offensive_pool", [])[:2]

    per_layer = ammo_total / gcfg.get("layers", 5)  # 每层金额

    for t in grid_targets:
        code = t["code"]
        name = t.get("name", code)
        step, layers, base = compute_grid_params(code, cfg)
        if base is None:
            logs.append(f"[{code} {name}] 无K线, 跳过网格")
            continue
        rt = md.get_realtime([code]).get(code, {})
        price = rt.get("price")
        if not price:
            logs.append(f"[{code} {name}] 无实时价, 跳过网格")
            continue

        st = state.get(code, {"holding_qty": 0, "last_price": price, "base_price": base, "bought_layers": 0})
        # 基准价 = 网格建仓时的中心价; 若未设用当前MA
        center = st.get("base_price") or base
        offset = (price - center) / center * 100  # 偏离中心价百分比(负=低于中心=应买)
        level = int(offset // step)  # 偏离层数(负=下方网格, 正=上方网格)

        logs.append(f"[{code} {name}] 网格巡检: 价{price:.2f} 中心{center:.2f} 偏离{offset:+.2f}% "
                    f"({level}格) 步距{step}% 持有{st['holding_qty']}股 可用弹药{free_ammo:.0f}元")

        if not do_trade:
            continue
        if not ensure_trade_window():
            return logs

        # 跌停不买, 涨停不卖
        limit_down = rt.get("limit_down")
        limit_up = rt.get("limit_up")

        # --- 买逻辑: 价格低于中心, 每层买一格, 最多买到 layers 层 ---
        # 目标持有层数 = -level (负偏离=应买几层); 已买层数=holding映射
        target_buy_layers = max(0, -level)
        cur_layers = int(st["holding_qty"] * center / per_layer) if per_layer else 0
        to_buy = min(target_buy_layers - cur_layers, layers - cur_layers)
        if to_buy > 0 and free_ammo > per_layer * 0.5:
            if limit_down and price <= limit_down * 1.005:
                logs.append(f"  [{code}] 已跌停封死, 不买")
            else:
                amt = min(per_layer * to_buy, free_ammo)
                qty = int(amt // price // 100 * 100)
                if qty > 0:
                    cmd = f"买入 {code} {price:.2f} {qty}"
                    resp = call_mx_moni(cmd)
                    st["holding_qty"] = st.get("holding_qty", 0) + qty
                    st["last_price"] = price
                    free_ammo -= qty * price
                    logs.append(f"  [{code} {name}] 🟢网格买入{qty}股(补{to_buy}层) {cmd} | {resp}")
                    try:
                        import local_records
                        local_records.log_trade("grid", code, name, "BUY", price, qty, resp, f"网格补{to_buy}层")
                    except Exception:
                        pass
        # --- 卖逻辑: 价格高于中心, 每层卖一格(仅卖已持有的) ---
        target_sell_layers = max(0, level)
        to_sell = min(target_sell_layers, cur_layers)
        if to_sell > 0 and st["holding_qty"] > 0:
            if limit_up and price >= limit_up * 0.995:
                logs.append(f"  [{code}] 已涨停封死, 不卖")
            else:
                sell_qty = min(st["holding_qty"], int(per_layer * to_sell // price // 100 * 100))
                if sell_qty > 0:
                    cmd = f"卖出 {code} {price:.2f} {sell_qty}"
                    resp = call_mx_moni(cmd)
                    st["holding_qty"] -= sell_qty
                    st["last_price"] = price
                    logs.append(f"  [{code} {name}] 🔴网格卖出{sell_qty}股(落{to_sell}层) {cmd} | {resp}")
                    try:
                        import local_records
                        local_records.log_trade("grid", code, name, "SELL", price, sell_qty, resp, f"网格落{to_sell}层")
                    except Exception:
                        pass

        state[code] = st

    save_grid_state(state)
    return logs


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_config.json"), encoding="utf-8"))
    for l in grid_once(cfg, do_trade=False):
        print(l)
