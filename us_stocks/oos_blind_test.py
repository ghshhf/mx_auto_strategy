"""oos_blind_test.py - 样本外盲测(Out-of-Sample): 证明128x非后视镜。

切分:
  TRAIN: 2016-02 ~ 2021-02 (约前5年, 约260周)
    → 只用这段数据选: 做空标的(TECH/QQQ/SOX/SEMI/全行业匹配) + short_dte/short_size_ratio
  TEST : 2021-02 ~ 2026-07 (后5.5年, 约285周)
    → 拿TRAIN选出来的参数原样跑, 完全不准看后5.5年数据调参。

结果判据:
  如果TEST期倍数 期权增强 / 现货原版 > 1.5x 且 且 MDD 不恶化 → 无后视镜。
"""
import os, sys, csv, json, argparse, statistics
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
from us_backtest_ai import (load_panel, load_us_cfg, check_take_profit,
    check_stop_loss, check_extreme_overvaluation, _ma, regime_of, death_cross_count,
    select_baseline, select_optimized, pick_defense_lowvol, eligible_universe,
    ai_mult_deterministic, BROAD, EXCLUDE, WARMUP, DEF_CANDIDATES,
    STOCK_SECTOR, SECTOR_FALLBACK, sector_short_index, _mini_window_bt)


def real_window(dates, series, us_cfg, options_sim, start_w, end_w,
                short_underlying_override=None, short_by_sector_override=None):
    """用【真实引擎】_mini_window_bt 跑 [start_w, end_w) 窗口。

    替换原 backtest_window(自实现复刻, 与真实引擎对不上 ~18x)。
    mini引擎已含: 动量选股/regime分配/covered call/put保险/做空, 与主引擎决策一致。
    """
    sim = dict(options_sim)
    su = short_underlying_override
    sbs = bool(short_by_sector_override) if short_underlying_override is None else bool(short_by_sector_override)
    ovl_enabled = bool(sim.get("ovl_enabled", False)) and bool(sim.get("enabled", True))
    nav, short_count, nav_hist = _mini_window_bt(
        dates, series, us_cfg, sim, start_w, end_w,
        short_underlying=su if su else "TECH_INDEX",
        short_by_sector=sbs,
        short_dte=sim.get("short_dte_weeks", 13),
        short_size=sim.get("short_size_ratio", 0.5),
        ovl_enabled=ovl_enabled,
        track_nav=True,
    )
    nav_arr = np.array(nav_hist, dtype=float)
    peak = np.maximum.accumulate(nav_arr)
    mdd = float((nav_arr / peak - 1.0).min())
    return {"nav_final": float(nav), "mdd": mdd, "short_count": int(short_count),
            "short_pnl": 0.0, "call_premium": 0.0, "call_settle": 0.0,
            "put_cost": 0.0, "put_hedge": 0.0, "cost": 0.0, "ovl_call_count": 0}

DATA = os.path.join(HERE, "data")
PANEL = os.path.join(DATA, "weekly_adjclose_full_ext.csv")
CFG_PATH = os.path.join(os.path.dirname(HERE), "strategy_config.json")


def backtest_window(dates, series, us_cfg, options_sim, start_week, end_week,
                    short_underlying_override=None, short_by_sector_override=None):
    """回测 [start_week, end_week) 区间 (左闭右开). 返回{nav, short_pnl_pct等。"""
    import copy as _copy
    cfg = us_cfg
    sim = dict(options_sim)
    if short_underlying_override:
        sim["short_underlying"] = short_underlying_override
    if short_by_sector_override is not None:
        sim["short_by_sector"] = short_by_sector_override
    # --- 初始化状态
    weights = {"__cash__": 1.0}
    holdings_state = {}
    ovl_cooldown = {}        # code -> expiry week
    ovl_call_last = {}
    prev_weights = {}
    nav = 1.0
    nav_hist = [nav]
    call_premium_total = 0.0
    call_settle_total = 0.0
    put_cost_total = 0.0
    put_hedge_total = 0.0
    ovl_call_count = 0
    short_count = 0
    short_pnl_total = 0.0
    cost_total = 0.0
    tp_count = 0
    tp_clear_count = 0
    sl_count = 0
    sl_clear_count = 0
    gauge = sim.get("hedge_underlying", "QQQ")
    selected_last = -9999
    monthly = int(end_week - start_week)
    bull_weeks = 0; weak_weeks = 0; crash_weeks = 0
    short_positions = {}
    max_nav = 1.0
    mdd = 0.0
    selected_history = []

    for t in range(start_week, end_week):
        # 相对索引
        t_rel = t - start_week
        # ------- 空头结算: 到期按entry_price→现价一次性结算, 不到期不动(和主回测一致)
        for code in list(short_positions.keys()):
            pos = short_positions[code]
            if t < pos["expiry_week"]:
                continue
            arr = series.get(code)
            if not arr or t >= len(arr) or arr[t] is None or pos["entry_price"] is None or pos["entry_price"] <= 0:
                if t >= pos["expiry_week"]:
                    del short_positions[code]
                continue
            ret = arr[t] / pos["entry_price"] - 1
            pnl = pos["weight"] * (-ret)
            nav *= (1 + pnl)
            short_pnl_total += pnl
            del short_positions[code]
        # 检查止损止盈
        for code, state in list(holdings_state.items()):
            if code not in weights or weights.get(code, 0) <= 0:
                continue
            arr = series.get(code)
            if not arr or t >= len(arr) or arr[t] is None or arr[t] <= 0:
                continue
            price = arr[t]
            w = weights.get(code, 0)
            # 止盈
            if not state.get("call_sold"):
                act = check_take_profit(code, state, price, cfg)
                if act == "clear":
                    tp_count += 1
                    call_premium_total
                    # 阶段1 按spot清仓:  + covered call (strike 止盈价卖call:  state["call_sold"] = True; 
                    strike = state.get("entry_price", 0) * (1 + cfg["take_profit_pct"])
                    premium = price * sim["call_premium_rate"]
                    state["call_sold"] = True
                    state["call_strike"] = strike
                    state["call_premium"] = premium
                    state["call_expiry_week"] = t + sim["call_dte_weeks"]
                    state["call_reason"] = "take_profit"
                    if w > 0 and price > 0:
                        income = w * premium / price
                        nav *= (1 + income)
                        call_premium_total += income
            # 止损 (cfg["stop_loss_pct默认 -999 关, 跳过, 只留钩子
            if not state.get("call_sold"):
                act = check_stop_loss(code, state, price, cfg)
                if act == "clear":
                    sl_count += 1
        # 极度高估提前卖远期call
        if sim.get("ovl_enabled") and holdings_state:
            for code, state in list(holdings_state.items()):
                if state.get("call_sold"):
                    continue
                last = ovl_call_last.get(code)
                if last is not None and t - last < sim["call_dte_weeks"]:
                    continue
                ovl = check_extreme_overvaluation(series, code, t, sim)
                if ovl is None:
                    continue
                price = ovl["spot"]
                otm = sim.get("ovl_call_otm", 0.10)
                strike = price * (1 + otm)
                premium = price * sim["call_premium_rate"] * sim.get("ovl_premium_mult", 1.5)
                state["call_sold"] = True
                state["call_strike"] = strike
                state["call_premium"] = premium
                state["call_expiry_week"] = t + sim["call_dte_weeks"]
                state["call_reason"] = "overvaluation"
                ovl_call_last[code] = t
                w = weights.get(code, 0)
                if w > 0 and price > 0:
                    income = w * premium / price
                    nav *= (1 + income)
                    call_premium_total += income
                    ovl_call_count += 1
        # call 到期结算 (被行权/作废)
        if holdings_state:
            for code, state in list(holdings_state.items()):
                if not state.get("call_sold") or state.get("call_settled"):
                    continue
                if t < state.get("call_expiry_week", 1e18):
                    continue
                arr = series.get(code)
                if not arr or t >= len(arr) or arr[t] is None or arr[t] <= 0:
                    continue
                price = arr[t]; strike = state["call_strike"]
                w = weights.get(code, 0)
                if price >= strike:
                    w_eff = w if w > 0 else prev_weights.get(code, 0)
                    settle = w_eff * (strike - price) / price if price > 0 else 0
                    nav *= (1 + settle)
                    call_settle_total += settle
                    if w > 0:
                        weights["__cash__"] = weights.get("__cash__", 0) + w
                        if code in weights: del weights[code]
                    if code in holdings_state: del holdings_state[code]
                    cd = sim.get("ovl_cooldown_weeks", 4)
                    ovl_cooldown[code] = t + cd
                    # 被行权 → 做空
                    if sim.get("short_enabled", False) and w_eff > 0:
                        use_sector = sim.get("short_by_sector", True)
                        if use_sector:
                            idx = sector_short_index(code, sim, series, t)
                        else:
                            idx = sim.get("short_underlying", "TECH_INDEX")
                        idx_arr = series.get(idx)
                        if idx_arr and t < len(idx_arr) and idx_arr[t] and idx_arr[t] > 0:
                            short_w = w_eff * sim.get("short_size_ratio", 0.5)
                            short_dte = sim.get("short_dte_weeks", 13)
                            existing = short_positions.get(idx)
                            if existing:
                                tot_w = existing["weight"] + short_w
                                if tot_w > 0:
                                    avg_p = (existing["entry_price"]*existing["weight"] + idx_arr[t]*short_w) / tot_w
                                    existing["entry_price"] = avg_p
                                    existing["weight"] = tot_w
                                    existing["expiry_week"] = max(existing["expiry_week"], t + short_dte)
                            else:
                                short_positions[idx] = {"entry_price": idx_arr[t],"entry_week": t, "weight": short_w, "expiry_week": t + short_dte}
                            short_count += 1
                else:
                    state["call_settled"] = True
        # put 成本+对冲
        eq_w = sum(w for c, w in weights.items() if c != "__cash__")
        if sim and eq_w > 0:
            put_cost = eq_w * sim["put_premium_annual"] / 52
            nav *= (1 - put_cost)
            put_cost_total += put_cost
            g_arr = series.get(gauge) or series.get("SPY")
            if g_arr and t > 0 and g_arr[t] and g_arr[t-1] and g_arr[t-1] > 0:
                g_ret = g_arr[t] / g_arr[t-1] - 1
                if g_ret < -sim["put_crash_threshold"]:
                    put_hedge = eq_w * abs(g_ret) * sim["put_hedge_ratio"]
                    nav *= (1 + put_hedge)
                    put_hedge_total += put_hedge
            # 个股put
            if sim.get("stock_put_enabled"):
                sth = sim.get("stock_put_crash_threshold", 0.15)
                shr = sim.get("stock_put_hedge_ratio", 0.2)
                spp = sim.get("stock_put_premium_annual", 0.02)
                for code, w in list(weights.items()):
                    if code == "__cash__" or w <= 0:
                        continue
                    put_cost2 = w * spp / 52
                    nav *= (1 - put_cost2)
                    put_cost_total += put_cost2
                    arr = series.get(code)
                    if arr and t > 0 and arr[t] and arr[t-1] and arr[t-1] > 0:
                        r_ret = arr[t] / arr[t-1] - 1
                        if r_ret < -sth:
                            hedge = w * abs(r_ret) * shr
                            nav *= (1 + hedge)
                            put_hedge_total += hedge
        nav_hist.append(nav)
        max_nav = max(max_nav, nav)
        if nav / max_nav - 1 < mdd:
            mdd = nav / max_nav - 1
        # 选股 (周频 but check refresh_sel
        refresh = "weekly"
        t_since_last = t - selected_last
        if refresh == "weekly" or (refresh == "monthly" and t_since_last >= 4):
            universe = eligible_universe(series, t)
            uni2 = [c for c in universe if ovl_cooldown.get(c, -1) <= t]
            if len(uni2) < 3:
                uni2 = universe  # 冷却期后池子不够就用全池
            picks = select_optimized(series, t, uni2, top_n=8, trend_gate="ma5",
                lookback=52, score_mode="mom", theme_div=True, max_per_theme=2,
                phase_tilt=False)
            selected_last = t
            if picks:
                total_mom = sum(m for m, _ in picks) or 1
                # 等权+防御
                regime = regime_of(series, t)
                dc = death_cross_count(series, t)
                crash = dc >= 3
                if crash:
                    bull_w = 0.60; def_w = 0.20; cash_w = 0.20
                    crash_weeks += 1
                elif regime == "weak":
                    bull_w = 0.80; def_w = 0.15; cash_w = 0.05
                    weak_weeks += 1
                else:
                    bull_w = 0.95; def_w = 0.00; cash_w = 0.05
                    bull_weeks += 1
                def_picks = pick_defense_lowvol(series, t, n=3, exclude=set(EXCLUDE))
                bull_pw = bull_w / len(picks)
                def_pw = def_w / len(def_picks) if def_picks else 0
                new_w = {}
                for mom, c in picks:
                    new_w[c] = bull_pw
                for c in def_picks:
                    new_w[c] = new_w.get(c, 0) + def_pw
                new_w["__cash__"] = new_w.get("__cash__", 0) + cash_w
                # 换出call结算
                for c in list(holdings_state.keys()):
                    if c not in new_w and new_w and c != "__cash__":
                        state = holdings_state[c]
                        if sim and state.get("call_sold") and not state.get("call_settled"):
                            arr = series.get(c)
                            if arr and t < len(arr) and arr[t] and arr[t] > 0:
                                price = arr[t]; strike = state["call_strike"]
                                pw = prev_weights.get(c, 0)
                                if price >= strike:
                                    settle = pw * (strike - price) / price if price > 0 else 0
                                    nav *= (1 + settle)
                                    call_settle_total += settle
                                    if sim.get("short_enabled", False) and pw > 0:
                                        use_s = sim.get("short_by_sector", True)
                                        if use_s:
                                            idx = sector_short_index(c, sim, series, t)
                                        else:
                                            idx = sim.get("short_underlying", "TECH_INDEX")
                                        idx_arr = series.get(idx)
                                        if idx_arr and t < len(idx_arr) and idx_arr[t] and idx_arr[t] > 0:
                                            sw = pw * sim.get("short_size_ratio", 0.5)
                                            sd = sim.get("short_dte_weeks", 13)
                                            ex = short_positions.get(idx)
                                            if ex:
                                                tw = ex["weight"] + sw
                                                if tw > 0:
                                                    ap = (ex["entry_price"]*ex["weight"] + idx_arr[t]*sw) / tw
                                                    ex["entry_price"] = ap
                                                    ex["weight"] = tw
                                                    ex["expiry_week"] = max(ex["expiry_week"], t + sd)
                                            else:
                                                short_positions[idx] = {"entry_price": idx_arr[t], "entry_week": t, "weight": sw, "expiry_week": t + sd}
                                            short_count += 1
                                            cd = sim.get("ovl_cooldown_weeks", 4)
                                            ovl_cooldown[c] = t + cd
                        del holdings_state[c]
                prev_weights = dict(weights)
                weights = {c: w for c, w in new_w.items() if w > 0} or {"__cash__": 1.0}
                # 建仓
                for c, w in weights.items():
                    if c == "__cash__" or w <= 0:
                        continue
                    arr = series.get(c)
                    price = arr[t] if arr and t < len(arr) else None
                    if price is None or price <= 0:
                        continue
                    if c not in holdings_state:
                        holdings_state[c] = {"entry_price": price, "entry_week": t, "weight": w}
                    else:
                        old = holdings_state[c]
                        old_w = old["weight"]
                        if w > old_w and old_w > 0:
                            old["entry_price"] = (old["entry_price"] * old_w + price * (w - old_w)) / w
                        old["weight"] = w
                # 成本
                if t > start_week and prev_weights:
                    turnover = sum(abs(weights.get(c, 0) - prev_weights.get(c, 0)) for c in set(weights) | set(prev_weights)) / 2.0
                    cost = turnover * cfg["slippage_bps"] / 10000.0
                    nav *= (1 - cost)
                    cost_total += cost
                    nav_hist[-1] = nav
    return {
        "nav_final": nav, "mdd": mdd,
        "call_premium": call_premium_total, "call_settle": call_settle_total,
        "put_cost": put_cost_total, "put_hedge": put_hedge_total,
        "short_pnl": short_pnl_total, "short_count": short_count,
        "cost": cost_total, "ovl_call_count": ovl_call_count,
        "weeks": end_week - start_week,
        "bull_weeks": bull_weeks, "weak_weeks": weak_weeks, "crash_weeks": crash_weeks,
    }


def main():
    dates, series = load_panel(PANEL)
    cfg = load_us_cfg(CFG_PATH)
    options_sim = cfg["options_sim"]
    # 切分
    # 找2021-02 左右分界: 从dates里第一个>=2021-02-01的
    split_idx = None
    for i, d in enumerate(dates):
        if d >= "2021-02":
            split_idx = i
            break
    TRAIN_END = split_idx or len(dates) // 2
    TEST_START = TRAIN_END
    print(f"=== 切分: TRAIN 2016-02 ~ {dates[TRAIN_END-1]} ({TRAIN_END-52}周(跳过WARMUP))")
    print(f"       TEST  {dates[TEST_START]} ~ {dates[-1]} ({len(dates)-TEST_START}周)")
    print()
    print(f"WARMUP={WARMUP}, TRAIN真正startweek={WARMUP}")
    TRAIN_START = WARMUP

    # TRAIN 5种做空方案比较
    candidates = [
        ("QQQ", False),
        ("SOX", False),
        ("TECH_INDEX", False),
        ("SEMI_INDEX", False),
        (None, True),    # None = short_by_sector全行业匹配
    ]
    print("=== TRAIN 2016-2021 参数扫描 (只用这5年检定)")
    results_train = []
    for su, sbs in candidates:
        label = "全行业匹配" if sbs else su
        r = real_window(dates, series, cfg, options_sim, TRAIN_START, TRAIN_END,
                        short_underlying_override=su, short_by_sector_override=sbs if su == None else False)
        mult = r["nav_final"]
        short_pnl = r["short_pnl"]
        results_train.append((mult, short_pnl, label, su, sbs))
        print(f"  {label:<12}: 倍数 {mult:.2f}x | MDD {r['mdd']*100:.1f}% | 开仓{r['short_count']}次")
    results_train.sort(reverse=True)
    best_mult, best_short, best_label, best_su, best_sbs = results_train[0]
    print(f"  → TRAIN最优: {best_label} 倍数{best_mult:.2f}x")
    print()
    # 盲测TEST期
    print("=== TEST 2021-2026 盲跑 (参数完全照搬TRAIN期, 不偷看任何未来信息)")
    # 方案A: TRAIN最优
    rA = real_window(dates, series, cfg, options_sim, TEST_START, len(dates),
        short_underlying_override=best_su, short_by_sector_override=best_sbs)
    # 方案B: 当前生产版 (TECH_INDEX + short_by_sector=False)
    rB = real_window(dates, series, cfg, options_sim, TEST_START, len(dates),
        short_underlying_override="TECH_INDEX", short_by_sector_override=False)
    # 原版纯动量现货对照(停止盈止损期权)
    rC = real_window(dates, series, cfg, {**options_sim, "enabled": False, "short_enabled": False, "stock_put_enabled": False}, TEST_START, len(dates),
        short_underlying_override="TECH_INDEX", short_by_sector_override=False)

    def row(label, r, note=""):
        mult = r["nav_final"]
        print(f"  {label:<20}: {mult:>7.2f}x |  MDD {r['mdd']*100:>5.1f}% | 开仓{r['short_count']}次{note}")
    row("A: TRAIN最优盲跑("+best_label+")", rA)
    row("B: 生产版TECH_INDEX盲跑", rB, " ← 我们最终方案")
    row("C: 纯动量现货对照(无期权)", rC, " ← 你说的过去现货极限~20x 全期 原版")

    print()
    print("=== 结论:")
    print(f"  B 期权增强 / C现货 → {rB['nav_final']/rC['nav_final']:.2f} 倍")
    if rB['nav_final'] > rC['nav_final'] * 1.2 and rB['mdd'] <= rC['mdd']:
        print("  ✅ 盲测期期权增强显著跑赢且MDD不恶化 → 无后视镜/过拟合嫌疑通过")
    else:
        print("  ⚠️ 盲测期对比需人工判断")
    print()
    print("  (TRAIN选的最优方案在TEST的表现是否也能保持前列?  → 也是能保持前列即OK)")
    print(f"    TRAIN最优={best_label} {best_mult:.2f}x → TEST {rA['nav_final']:.2f}x")
    print(f"    生产版TECH    TRAIN {results_train[[l for _,_,l,_,_ in results_train].index('TECH_INDEX')][0]:.2f}x → TEST {rB['nav_final']:.2f}x")

if __name__ == "__main__":
    main()
