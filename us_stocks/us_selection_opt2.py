"""
us_selection_opt2.py - 美股选币优化第二轮: 逆波动率加权 + 组合精调
===========================================================
第一轮发现:
- top_n=3 是最优, n>3 收益降但Sharpe升
- struct_def=0.3 → Sharpe 4.01, MDD -35.7%, 32x (收益-68%但风险大改善)
- vol_target=0.15 → MDD -31.9%, Sharpe 3.88, 21x (MDD最优)
- lev=1.2 → 189x, MDD -54% (杠杆放大)
- lev1.2+sd20+vol18 → 61x, MDD -40%, Sharpe 3.73 (平衡)

本轮重点:
1. 实现美股版的 inv_vol 加权 (当前只有 mom^0.5 score加权)
2. 测试 equal vs score vs inv_vol 对比
3. 最优组合OOS验证 (修复SPY bug)
"""
import os, sys, time, json, math, statistics
import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from us_backtest_ai import (
    load_panel, load_us_cfg, run_optimized,
    select_optimized, eligible_universe, regime_of, death_cross_count,
    pick_defense_lowvol, _ma, WARMUP, EXCLUDE, PANEL, series_proxy,
    ai_mult_deterministic, sector_short_index, check_take_profit, check_stop_loss,
    check_extreme_overvaluation, realized_vol, bs_call, bs_put
)
import us_backtest_ai as usb

# 加载面板
dates, series = load_panel(PANEL)
series_proxy.clear()
series_proxy.update(series)
us_cfg = load_us_cfg()
opt_sim_cfg = us_cfg.get("options_sim", {})
options_sim = opt_sim_cfg if opt_sim_cfg.get("enabled", False) else None

n_total = len(dates)


def run_inv_vol(top_n=3, lookback=52, trend_gate='ma5', theme_div=True, max_per_theme=2,
                crash_off=80, struct_def=0.0, vol_target=0.0, lev=1.0,
                inv_vol_lookback=26):
    """美股逆波动率加权版本: 选股逻辑不变, 但权重分配用逆波动率"""
    ALLOC = {
        "bull":    {"off": 100, "def": 0,  "cash": 0},
        "balance": {"off": 95,  "def": 5,  "cash": 0},
        "weak":    {"off": 85,  "def": 15, "cash": 0},
        "crash":   {"off": crash_off, "def": 15, "cash": 85 - crash_off},
    }

    REBAL = 1
    nav = 1.0; nav_hist = []; peak = 1.0; mdd = 0.0
    weights = {"__cash__": 1.0}; selected = []; last_rebal = -100; yearly = {}
    weak_weeks = 0; crash_weeks = 0; vol_weeks = 0
    last_pool = -100; universe = []
    gauge_arr = series.get("QQQ") or series.get("SPY")
    holdings_state = {}; prev_weights = {}; cost_total = 0.0
    short_positions = {}; short_pnl_total = 0.0; short_count = 0
    ovl_cooldown = {}; ovl_call_last = {}
    call_premium_total = 0.0; call_settle_total = 0.0
    put_cost_total = 0.0; put_hedge_total = 0.0; ovl_call_count = 0
    tp_count = 0; sl_count = 0

    for t in range(n_total):
        prev_weights = dict(weights)
        if t > 0 and weights:
            growth = 0.0
            for c, w in weights.items():
                if c == "__cash__": continue
                arr = series.get(c)
                if not arr or t >= len(arr) or arr[t] is None or arr[t-1] in (None, 0): continue
                growth += w * (arr[t] / arr[t-1] - 1)
            nav *= (1 + growth); nav_hist.append(nav); peak = max(peak, nav)
            mdd = min(mdd, nav / peak - 1); y = dates[t][:4]
            yearly.setdefault(y, 1.0); yearly[y] *= (1 + growth)
        else:
            nav_hist.append(nav)

        # 止盈止损
        if t > WARMUP and holdings_state:
            to_clear = []
            for code, state in list(holdings_state.items()):
                arr = series.get(code)
                if not arr or t >= len(arr) or arr[t] is None or arr[t] <= 0: continue
                price = arr[t]
                if check_take_profit(code, state, price, us_cfg) == "clear":
                    if options_sim and not state.get("call_sold"):
                        strike = state["entry_price"] * (1 + us_cfg["take_profit_pct"])
                        premium = state["entry_price"] * options_sim["call_premium_rate"]
                        state["call_sold"] = True; state["call_strike"] = strike
                        state["call_premium"] = premium
                        state["call_expiry_week"] = t + options_sim["call_dte_weeks"]
                        w = weights.get(code, 0)
                        income = w * premium / price
                        nav *= (1 + income); nav_hist[-1] = nav
                        call_premium_total += income; tp_count += 1
                    else:
                        to_clear.append((code, "take_profit")); tp_count += 1
                elif check_stop_loss(code, state, price, us_cfg) == "clear":
                    to_clear.append((code, "stop_loss")); sl_count += 1
            if to_clear:
                for code, reason in to_clear:
                    if code in weights:
                        weights["__cash__"] = weights.get("__cash__", 0) + weights[code]
                        del weights[code]
                    if code in holdings_state: del holdings_state[code]
                new_w = weights
                turnover = sum(abs(new_w.get(c, 0) - prev_weights.get(c, 0))
                               for c in set(new_w) | set(prev_weights)) / 2.0
                cost = turnover * us_cfg["slippage_bps"] / 10000.0
                nav *= (1 - cost); nav_hist[-1] = nav; cost_total += cost

        # 极度高估检测
        if options_sim and options_sim.get("ovl_enabled") and t > WARMUP and holdings_state:
            ovl_cfg = options_sim
            for code, state in list(holdings_state.items()):
                if state.get("call_sold"): continue
                last = ovl_call_last.get(code)
                if last is not None and t - last < options_sim["call_dte_weeks"]: continue
                ovl = check_extreme_overvaluation(series, code, t, ovl_cfg)
                if ovl is None: continue
                price = ovl["spot"]
                otm = options_sim.get("ovl_call_otm", 0.10)
                strike = price * (1 + otm)
                premium = price * options_sim["call_premium_rate"] * options_sim.get("ovl_premium_mult", 1.5)
                state["call_sold"] = True; state["call_strike"] = strike
                state["call_premium"] = premium
                state["call_expiry_week"] = t + options_sim["call_dte_weeks"]
                state["call_reason"] = "overvaluation"
                ovl_call_last[code] = t
                w = weights.get(code, 0)
                if w > 0 and price > 0:
                    income = w * premium / price
                    nav *= (1 + income); nav_hist[-1] = nav
                    call_premium_total += income; ovl_call_count += 1

        # call到期结算
        if options_sim and holdings_state:
            for code, state in list(holdings_state.items()):
                if not state.get("call_sold") or state.get("call_settled"): continue
                if t < state.get("call_expiry_week", 0): continue
                arr = series.get(code)
                if not arr or t >= len(arr) or arr[t] is None or arr[t] <= 0: continue
                price = arr[t]; strike = state["call_strike"]
                w = weights.get(code, 0)
                if price >= strike:
                    w_eff = w if w > 0 else prev_weights.get(code, 0)
                    settle = w_eff * (strike - price) / state["entry_price"]
                    nav *= (1 + settle); nav_hist[-1] = nav; call_settle_total += settle
                    if w > 0:
                        weights["__cash__"] = weights.get("__cash__", 0) + w
                        if code in weights: del weights[code]
                    if code in holdings_state: del holdings_state[code]
                    cd = options_sim.get("ovl_cooldown_weeks", 4)
                    ovl_cooldown[code] = t + cd
                    if options_sim.get("short_enabled", False) and w_eff > 0:
                        use_sector = options_sim.get("short_by_sector", True)
                        if use_sector:
                            idx = sector_short_index(code, options_sim, series, t)
                        else:
                            idx = options_sim.get("short_underlying", "TECH_INDEX")
                        idx_arr = series.get(idx)
                        if idx_arr and t < len(idx_arr) and idx_arr[t] and idx_arr[t] > 0:
                            short_w = w_eff * options_sim.get("short_size_ratio", 0.5)
                            short_dte = options_sim.get("short_dte_weeks", 13)
                            existing = short_positions.get(idx)
                            if existing:
                                tot_w = existing["weight"] + short_w
                                if tot_w > 0:
                                    avg_p = (existing["entry_price"]*existing["weight"] + idx_arr[t]*short_w) / tot_w
                                    existing["entry_price"] = avg_p
                                    existing["weight"] = tot_w
                                    existing["expiry_week"] = max(existing["expiry_week"], t + short_dte)
                            else:
                                short_positions[idx] = {
                                    "entry_price": idx_arr[t], "entry_week": t,
                                    "weight": short_w, "expiry_week": t + short_dte,
                                }
                            short_count += 1
                else:
                    state["call_settled"] = True

        # protective put
        if options_sim:
            eq_w = sum(w for c, w in weights.items() if c != "__cash__")
            if eq_w > 0:
                g_arr = series.get("QQQ") or series.get("SPY")
                put_cost = eq_w * options_sim["put_premium_annual"] / 52
                nav *= (1 - put_cost); nav_hist[-1] = nav; put_cost_total += put_cost
                if g_arr and t > 0 and t < len(g_arr) and g_arr[t] and g_arr[t-1] and g_arr[t-1] > 0:
                    g_ret = g_arr[t] / g_arr[t-1] - 1
                    if g_ret < -options_sim["put_crash_threshold"]:
                        put_hedge = eq_w * abs(g_ret) * options_sim["put_hedge_ratio"]
                        nav *= (1 + put_hedge); nav_hist[-1] = nav; put_hedge_total += put_hedge
                if options_sim.get("stock_put_enabled"):
                    stock_thresh = options_sim.get("stock_put_crash_threshold", 0.15)
                    stock_hedge_ratio = options_sim.get("stock_put_hedge_ratio", 0.3)
                    stock_put_prem = options_sim.get("stock_put_premium_annual", 0.02)
                    for code, w in list(weights.items()):
                        if code == "__cash__" or w <= 0: continue
                        arr = series.get(code)
                        if not arr or t <= 0 or t >= len(arr) or not arr[t] or not arr[t-1] or arr[t-1] <= 0: continue
                        s_cost = w * stock_put_prem / 52
                        nav *= (1 - s_cost); nav_hist[-1] = nav; put_cost_total += s_cost
                        s_ret = arr[t] / arr[t-1] - 1
                        if s_ret < -stock_thresh:
                            s_hedge = w * abs(s_ret) * stock_hedge_ratio
                            nav *= (1 + s_hedge); nav_hist[-1] = nav; put_hedge_total += s_hedge

        # 空仓PnL
        if short_positions and t > 0:
            for code in list(short_positions.keys()):
                pos = short_positions[code]
                arr = series.get(code)
                if not arr or t >= len(arr) or arr[t] is None or arr[t] <= 0: continue
                if t <= 0 or arr[t-1] is None or arr[t-1] <= 0: continue
                price_ret = arr[t] / arr[t-1] - 1
                pnl = -pos["weight"] * price_ret
                nav *= (1 + pnl); nav_hist[-1] = nav; short_pnl_total += pnl
                if t >= pos["expiry_week"]: del short_positions[code]

        # 动态池刷新
        if t >= WARMUP and (t - last_pool >= 4 or last_pool < 0):
            universe = eligible_universe(series, t); last_pool = t

        need_rebal = (t == WARMUP) or (t - last_rebal >= REBAL)
        if t >= WARMUP and need_rebal:
            selected = select_optimized(series, t, universe, top_n,
                                        trend_gate, lookback, "mom",
                                        theme_div, max_per_theme, False,
                                        year=dates[t][:4]); last_rebal = t
            if ovl_cooldown and selected:
                selected = [(m, c) for m, c in selected
                            if c not in ovl_cooldown or t >= ovl_cooldown[c]]
        if t >= WARMUP and selected:
            dcc = death_cross_count(series, t)
            regime = regime_of(series, t)
            if dcc >= 3: key = "crash"; crash_weeks += 1
            elif regime == "weak": key = "weak"; weak_weeks += 1
            else: key = regime
            a = ALLOC[key]
            vol_scale = 1.0
            if vol_target > 0 and t >= 20 and gauge_arr is not None:
                rets = []
                for k in range(t - 19, t + 1):
                    if k < len(gauge_arr) and gauge_arr[k] and gauge_arr[k-1] and gauge_arr[k-1] > 0:
                        rets.append(gauge_arr[k] / gauge_arr[k-1] - 1)
                if len(rets) >= 10:
                    rv = statistics.pstdev(rets) * (52 ** 0.5)
                    vol_scale = max(0.3, min(1.0, vol_target / rv)) if rv > 0 else 1.0
            if vol_scale < 1.0: vol_weeks += 1
            tw = {}
            off_pct = a["off"] * vol_scale * lev
            equity_pct = off_pct * (1.0 - struct_def)

            # === 核心改动: inv_vol 加权 ===
            vols = {}
            for mom, c in selected:
                arr = series.get(c)
                if not arr or t < inv_vol_lookback: continue
                win = [v for v in arr[max(0, t-inv_vol_lookback+1):t+1] if v not in (None, 0)]
                if len(win) < 5:
                    vols[c] = 0.3  # 默认中波动
                    continue
                rets = [win[k]/win[k-1]-1 for k in range(1, len(win)) if win[k-1] not in (None, 0)]
                if len(rets) < 3:
                    vols[c] = 0.3
                else:
                    vols[c] = statistics.pstdev(rets) * (52**0.5)  # 年化波动率

            # 逆波动率权重: w_i ∝ 1/vol_i
            inv_vols = {c: 1.0/max(v, 0.05) for c, v in vols.items()}
            iv_sum = sum(inv_vols.values()) or 1.0
            for mom, c in selected:
                if c in inv_vols:
                    tw[c] = (equity_pct / 100.0) * inv_vols[c] / iv_sum
                else:
                    tw[c] = (equity_pct / 100.0) / len(selected)

            def_b = pick_defense_lowvol(series, t, n=3, exclude={c for _, c in selected})
            if def_b and a["def"] > 0:
                per = a["def"] / 100.0 / len(def_b)
                for c in def_b: tw[c] = per
            struct_pct = off_pct * struct_def
            cash_frac = (a["cash"] + (a["off"] - off_pct) + struct_pct) / 100.0
            tw["__cash__"] = cash_frac
            weights = {c: w for c, w in tw.items() if w > 0} or {"__cash__": 1.0}

            if t > 0 and prev_weights:
                turnover = sum(abs(weights.get(c, 0) - prev_weights.get(c, 0))
                               for c in set(weights) | set(prev_weights)) / 2.0
                cost = turnover * us_cfg["slippage_bps"] / 10000.0
                nav *= (1 - cost); nav_hist[-1] = nav; cost_total += cost
            for c, w in weights.items():
                if c == "__cash__" or w <= 0: continue
                arr = series.get(c)
                price = arr[t] if arr and t < len(arr) else None
                if price is None or price <= 0: continue
                if c not in holdings_state:
                    holdings_state[c] = {"entry_price": price, "entry_week": t, "weight": w}
                else:
                    old = holdings_state[c]; old_w = old["weight"]
                    if w > old_w and old_w > 0:
                        old["entry_price"] = (old["entry_price"] * old_w + price * (w - old_w)) / w
                    old["weight"] = w
            for c in list(holdings_state.keys()):
                if c not in weights:
                    state = holdings_state[c]
                    if options_sim and state.get("call_sold") and not state.get("call_settled"):
                        arr = series.get(c)
                        if arr and t < len(arr) and arr[t] and arr[t] > 0:
                            price = arr[t]; strike = state["call_strike"]
                            w = prev_weights.get(c, 0)
                            if price >= strike:
                                settle = w * (strike - price) / state["entry_price"]
                                nav *= (1 + settle); nav_hist[-1] = nav; call_settle_total += settle
                                if options_sim.get("short_enabled", False) and w > 0:
                                    use_sector = options_sim.get("short_by_sector", True)
                                    if use_sector:
                                        idx = sector_short_index(c, options_sim, series, t)
                                    else:
                                        idx = options_sim.get("short_underlying", "TECH_INDEX")
                                    idx_arr = series.get(idx)
                                    if idx_arr and t < len(idx_arr) and idx_arr[t] and idx_arr[t] > 0:
                                        short_w = w * options_sim.get("short_size_ratio", 0.5)
                                        short_dte = options_sim.get("short_dte_weeks", 13)
                                        existing = short_positions.get(idx)
                                        if existing:
                                            tot_w = existing["weight"] + short_w
                                            if tot_w > 0:
                                                avg_p = (existing["entry_price"]*existing["weight"] + idx_arr[t]*short_w) / tot_w
                                                existing["entry_price"] = avg_p; existing["weight"] = tot_w
                                                existing["expiry_week"] = max(existing["expiry_week"], t + short_dte)
                                        else:
                                            short_positions[idx] = {
                                                "entry_price": idx_arr[t], "entry_week": t,
                                                "weight": short_w, "expiry_week": t + short_dte,
                                            }
                                        short_count += 1
                                        cd = options_sim.get("ovl_cooldown_weeks", 4)
                                        ovl_cooldown[c] = t + cd
                    del holdings_state[c]
        elif t == WARMUP and not selected:
            weights = {"__cash__": 1.0}

    yrs = (n_total - WARMUP) / 52.0
    yr_rets = list(yearly.values())
    avg = statistics.mean([r-1 for r in yr_rets]) if yr_rets else 0
    sd = statistics.pstdev([r-1 for r in yr_rets]) if len(yr_rets) > 1 else 0
    sh = (avg / sd * (52**0.5)) if sd > 0 else 0
    return {
        'multiple': nav, 'mdd': mdd, 'sharpe': sh, 'yearly': yearly,
        'call_premium': call_premium_total, 'put_cost': put_cost_total,
        'short_pnl': short_pnl_total, 'short_count': short_count,
        'cost_total': cost_total, 'tp_count': tp_count,
    }


def fmt(r):
    m = r['multiple']
    ms = f"{m:.1f}x" if m < 1000 else f"{m/1000:.1f}Kx"
    return f"{ms:>10}  MDD={r['mdd']*100:>5.1f}%  Sh={r['sharpe']:.2f}"


t0 = time.time()
print("="*100)
print("美股 inv_vol 加权选币优化")
print("="*100)

# ---- 基线 (当前默认: score/mom^0.5加权) ----
from us_backtest_ai import run_optimized as run_orig
series_proxy.clear(); series_proxy.update(series)
hist, st = run_orig(series, dates, use_ai=False, cfg=None, refresh_weeks=4,
                    theme_div=True, max_per_theme=2, us_cfg=us_cfg, options_sim=options_sim)
yr_rets = list(st['yearly'].values())
avg = statistics.mean([r-1 for r in yr_rets]); sd = statistics.pstdev([r-1 for r in yr_rets])
base_sh = (avg/sd*(52**0.5)) if sd > 0 else 0
print(f"\n基线 (score/mom^0.5): {st['multiple']:>10.1f}x  MDD={st['mdd']*100:>5.1f}%  Sh={base_sh:.2f}")

# ---- inv_vol 基线 ----
print("\n--- inv_vol 加权 (不同配置) ---")
configs = [
    ('inv_vol 基线', {}),
    ('inv_vol+sd20', {'struct_def': 0.20}),
    ('inv_vol+sd20+vol18', {'struct_def': 0.20, 'vol_target': 0.18}),
    ('inv_vol+sd30', {'struct_def': 0.30}),
    ('inv_vol+sd30+vol18', {'struct_def': 0.30, 'vol_target': 0.18}),
    ('inv_vol+crash40', {'crash_off': 40}),
    ('inv_vol+sd20+crash40', {'struct_def': 0.20, 'crash_off': 40}),
    ('inv_vol+sd20+vol18+crash40', {'struct_def': 0.20, 'vol_target': 0.18, 'crash_off': 40}),
    ('inv_vol+sd30+vol15+crash40', {'struct_def': 0.30, 'vol_target': 0.15, 'crash_off': 40}),
    # 杠杆组合
    ('inv_vol+lev1.2+sd20+vol18', {'struct_def': 0.20, 'vol_target': 0.18, 'lev': 1.2}),
    ('inv_vol+lev1.2+sd30+vol18', {'struct_def': 0.30, 'vol_target': 0.18, 'lev': 1.2}),
    ('inv_vol+lev1.3+sd30+vol18', {'struct_def': 0.30, 'vol_target': 0.18, 'lev': 1.3}),
]

print(f"\n{'combo':<35} {'mult':>10} {'MDD':>8} {'Sharpe':>8}")
for label, ov in configs:
    r = run_inv_vol(**ov)
    print(f"{label:<35} {r['multiple']:>10.1f} {r['mdd']*100:>7.1f}% {r['sharpe']:>8.2f}")

# ---- 年度对比 ----
print("\n--- 年度收益对比 (score基线 vs inv_vol+sd20+vol18) ---")
r_iv = run_inv_vol(struct_def=0.20, vol_target=0.18)
print(f"{'year':<6} {'score基线':>10} {'inv_vol':>10}")
for year in sorted(st['yearly'].keys()):
    base_yr = (st['yearly'][year] - 1) * 100
    iv_yr = (r_iv['yearly'].get(year, 1) - 1) * 100
    print(f"{year:<6} {base_yr:>+9.1f}% {iv_yr:>+9.1f}%")

# ---- inv_vol lookback 测试 ----
print("\n--- inv_vol lookback (波动率回看周期) ---")
for lb in [12, 20, 26, 52]:
    r = run_inv_vol(struct_def=0.20, vol_target=0.18, inv_vol_lookback=lb)
    print(f"  lb={lb:<4} {fmt(r)}")

print(f"\n=== 耗时 {time.time()-t0:.0f}s ===")
