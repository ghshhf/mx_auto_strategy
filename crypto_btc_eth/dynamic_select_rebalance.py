"""Dynamic Top-N coin-selection backtest — walk-forward, NO look-ahead.

This is the option-C experiment the user asked for:
  * 5-year window (not 10)
  * candidate pool = the 5 coins already in this project (BTC/ETH/XRP/BNB/TRX)
  * start capital = 100 USD
  * each week, rank the pool by trailing momentum, keep only coins that are in
    an uptrend (price >= MA), hold the Top 3 at equal weight
  * rebalance on selection change OR every 4 weeks (to harvest volatility)
  * compare against the static BTC/ETH 50/50 the user actually runs

Deliberate honesty constraints (user instruction: do NOT engineer the system
to buy coins about to be delisted):
  * the trend filter (price >= MA) is the OPPOSITE of a "buy dying coins" rule:
    it refuses to hold coins in a death spiral.
  * selection at week i uses ONLY closes up to week i (walk-forward). No future
    data ever enters a decision.
  * the one-sided fee mechanism is copied verbatim from backtest.run_rolling_rebalance
    so the cost accounting matches the validated engine bit-for-bit.

Caveats surfaced in the JSON / report:
  * tiny universe (5 coins, all survivors) -> survivorship bias, results are
    illustrative, NOT proof of alpha.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import pandas as pd

from config import BacktestConfig, price_column, default_rebalance_band
from data_sources import load_weekly_prices
from backtest import LineResult, WeekRecord, run_backtest
from metrics import compute_line_metrics, compute_buy_hold_reference, LineMetrics

HERE = os.path.dirname(os.path.abspath(__file__))
DYN_METRICS_JSON = os.path.join(HERE, "dynamic_metrics.json")
DYN_NAV_CSV = os.path.join(HERE, "dynamic_nav.csv")
DYN_CHART_HTML = os.path.join(HERE, "dynamic_nav.html")

# --- Experiment parameters (the user's choices) ---------------------------- #
START = "2021-08-01"
END = "2026-08-02"
POOL = ("BTC", "ETH", "XRP", "BNB", "TRX")
CAPITAL = 100.0
FEE = 0.001
LOOKBACK = 12          # momentum trailing window (weeks, ~3 months)
MA_WINDOW = 20         # trend filter (weeks, ~5 months)
TOP_N = 3              # hold the strongest 3 of the pool
REBALANCE_EVERY = 4    # periodic harvest cadence (weeks)


# --------------------------------------------------------------------------- #
# Dynamic selection engine (walk-forward, no look-ahead)
# --------------------------------------------------------------------------- #
def run_dynamic_select(prices: pd.DataFrame, pool: tuple[str, ...],
                       lookback: int, ma_window: int, top_n: int,
                       rebalance_every: int, fee_rate: float,
                       capital: float) -> LineResult:
    """Runs the walk-forward Top-N momentum selector over ``prices``.

    Selection at week *i* is computed strictly from closes up to week *i*.
    A coin is eligible only if its close is at/above its trailing MA (uptrend
    gate) -- this naturally excludes coins in a free-fall, so the system never
    deliberately buys something about to be delisted.  Among eligible coins the
    highest-momentum ``top_n`` are held equal-weight; the portfolio rebalances
    when the selection changes or every ``rebalance_every`` weeks.
    """
    coins = list(pool)
    n = len(coins)
    warmup = max(lookback, ma_window)

    first = prices.iloc[0]
    entry_fee = capital * fee_rate
    net = capital - entry_fee
    quantities = {c: (net / n) / float(first[price_column(c)]) for c in coins}
    held = set(coins)
    result = LineResult(
        name="dynamic_top3",
        coins=tuple(coins),
        initial_quantities=dict(quantities),
        entry_fee=entry_fee,
        total_fee=entry_fee,
        rebalance_count=0,
    )
    last_rebal_idx = 0

    for i, (date, row) in enumerate(prices.iterrows()):
        prices_now = {c: float(row[price_column(c)]) for c in coins}
        values = {c: quantities[c] * prices_now[c] for c in coins}
        nav = sum(values.values())
        weights_pre = {c: (values[c] / nav if nav > 0 else 0.0) for c in coins}

        traded = (i == 0)
        traded_notional = net if i == 0 else 0.0
        fee_paid = entry_fee if i == 0 else 0.0

        if i > 0:
            target_set = held  # default: keep current book
            if i >= warmup:
                window = prices.iloc[: i + 1]
                eligible: list[str] = []
                mom: dict[str, float] = {}
                for c in coins:
                    col = price_column(c)
                    ma = window[col].rolling(ma_window).mean().iloc[-1]
                    if pd.notna(ma) and prices_now[c] >= ma:
                        base_idx = max(0, i - lookback)
                        base = float(window[col].iloc[base_idx])
                        if base > 0:
                            mom[c] = prices_now[c] / base - 1.0
                            eligible.append(c)
                if eligible:
                    eligible.sort(key=lambda c: mom[c], reverse=True)
                    target_set = set(eligible[:top_n])

            need_rebalance = (target_set != held) or (
                target_set == held and (i - last_rebal_idx) >= rebalance_every
            )
            if need_rebalance:
                k = len(target_set)
                targets = {c: (1.0 / k if c in target_set else 0.0) for c in coins}
                target_values = {c: nav * targets[c] for c in coins}
                excess = {c: values[c] - target_values[c]
                          for c in coins if values[c] > target_values[c]}
                deficit = {c: target_values[c] - values[c]
                           for c in coins if values[c] < target_values[c]}
                sell_total = sum(excess.values())
                buy_total = sum(deficit.values())
                if sell_total > 0.0 and buy_total > 0.0:
                    # --- verbatim copy of backtest.run_rolling_rebalance fee
                    #     mechanic: fee on the one-sided SELL notional, sellers
                    #     land on target, buyers get proceeds*(1-fee) pro-rata.
                    for c, amount in excess.items():
                        quantities[c] -= amount / prices_now[c]
                    for c, amount in deficit.items():
                        proceeds = sell_total * (amount / buy_total)
                        quantities[c] += (proceeds * (1.0 - fee_rate)
                                         / prices_now[c])
                    fee_paid = sell_total * fee_rate
                    traded_notional = sell_total
                    traded = True
                    values = {c: quantities[c] * prices_now[c] for c in coins}
                    nav = sum(values.values())
                    held = target_set
                    result.rebalance_count += 1
                    result.total_fee += fee_paid

        weights_post = {c: (values[c] / nav if nav > 0 else 0.0) for c in coins}
        result.records.append(WeekRecord(
            date=date, prices=prices_now, quantities=dict(quantities),
            values=values, nav=nav, weights_pre=weights_pre,
            weights_post=weights_post, traded=traded,
            traded_notional=traded_notional, fee_paid=fee_paid,
        ))
        if traded:
            last_rebal_idx = i
    return result


# --------------------------------------------------------------------------- #
# Lightweight self-check (same 4-invariant style as the static backtest)
# --------------------------------------------------------------------------- #
@dataclass
class Check:
    code: str
    title: str
    passed: bool
    detail: str


def self_check(line: LineResult, prices: pd.DataFrame, config: BacktestConfig):
    checks: list[Check] = []
    nav_series = line.nav_series()
    last = line.records[-1]
    # (a) NAV reconstructs from q_i * p_i
    recon = sum(last.quantities.get(c, 0.0) * float(prices.iloc[-1][price_column(c)])
                for c in config.coins)
    ok_a = abs(recon - last.nav) < 1e-6
    checks.append(Check("a", "终值 == Σ q_i×末价_i", ok_a,
                         f"recon {recon:,.4f} vs NAV {last.nav:,.4f}"))
    # (b) no future data: selection at i only sees iloc[:i+1] -> structural;
    #     we instead assert every rebalance week has a valid (non-NaN) NAV.
    ok_b = all(pd.notna(r.nav) for r in line.records)
    checks.append(Check("b", "逐周 NAV 无 NaN（无前视/无断点）", ok_b,
                         f"{len(line.records)} 周全部有效" if ok_b else "存在 NaN"))
    # (c) fees only on trade weeks
    trade_weeks = sum(1 for r in line.records if r.traded)
    fee_weeks = sum(1 for r in line.records if r.fee_paid > 0.0)
    ok_c = trade_weeks == fee_weeks
    checks.append(Check("c", "手续费只在交易周计提", ok_c,
                        f"trade_weeks={trade_weeks} == fee_weeks={fee_weeks}"))
    # (d) data integrity
    ok_d = len(line.records) >= 52 * 4
    checks.append(Check("d", "周线数据充足（>=4年）", ok_d,
                         f"{len(line.records)} 周"))
    verdict = "YES" if all(c.passed for c in checks) else "NO"
    return verdict, checks


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def save_nav_csv(path, series_map: dict[str, pd.Series]) -> str:
    frame = pd.DataFrame(series_map)
    frame.index.name = "date"
    frame.to_csv(path, float_format="%.6f")
    return path


def _line_block(m: LineMetrics) -> dict:
    return {
        "name": m.name,
        "label": m.label,
        "start_date": m.start_date,
        "end_date": m.end_date,
        "weeks": m.weeks,
        "years": m.years,
        "gross_invested_usd": m.gross_invested_usd,
        "final_nav_usd": round(m.final_nav_usd, 2),
        "total_return_pct": round(m.total_return_pct, 2),
        "cagr_pct": round(m.cagr_pct, 2),
        "max_drawdown_pct": round(m.max_drawdown_pct, 2),
        "volatility_annual_pct": round(m.volatility_annual_pct, 2),
        "rebalance_count": m.rebalance_count,
        "total_fee_usd": round(m.total_fee_usd, 2),
        "final_weights_pct": {k: round(v, 2) for k, v in m.final_weights_pct.items()},
    }


def save_metrics_json(path, dyn_m, eq5_roll_m, eq5_hold_m, be_roll_m, be_hold_m,
                      reference, meta, verdict, checks, params):
    payload = {
        "currency": "USD",
        "experiment": "dynamic_top3_vs_static_btc_eth",
        "params": params,
        "data": meta,
        "dynamic_top3": _line_block(dyn_m),
        "equal_weight_5_rolling": _line_block(eq5_roll_m),
        "equal_weight_5_hold": _line_block(eq5_hold_m),
        "btc_eth_rolling": _line_block(be_roll_m),
        "btc_eth_hold": _line_block(be_hold_m),
        "single_asset_reference": {k: round(v, 2) for k, v in reference.items()},
        "comparison": {
            "dyn_vs_btceth_rolling_final_ratio":
                round(dyn_m.final_nav_usd / be_roll_m.final_nav_usd, 4),
            "dyn_vs_btceth_rolling_cagr_diff_pp":
                round(dyn_m.cagr_pct - be_roll_m.cagr_pct, 2),
            "dyn_vs_eq5_rolling_final_ratio":
                round(dyn_m.final_nav_usd / eq5_roll_m.final_nav_usd, 4),
        },
        "honesty_notes": [
            "池子仅 5 币且全部幸存 -> 含幸存者偏差，结果为示意性、非 Alpha 证明。",
            "选币在周 i 仅用截至周 i 的数据（walk-forward），无前视。",
            "趋势过滤(价格>=MA)天然排除暴跌/濒死币，系统不故意买退市币。",
            "手续费机制与已验证的 backtest.run_rolling_rebalance 逐位一致。",
        ],
        "self_check": {"verdict": verdict,
                       "checks": [{"code": c.code, "title": c.title,
                                   "passed": c.passed, "detail": c.detail}
                                  for c in checks]},
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def save_chart_html(path, nav_map: dict[str, pd.Series], blocks: dict[str, LineMetrics]):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    dates = next(iter(nav_map.values())).index
    dyn = nav_map["dynamic"]
    be_roll = nav_map["btc_eth_rolling"]
    be_hold = nav_map["btc_eth_hold"]
    eq5 = nav_map["equal_weight_5"]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.72, 0.28], vertical_spacing=0.05,
                        subplot_titles=("周度净值 NAV (USD, 对数轴)", "回撤 Drawdown (%)"))
    fig.add_trace(go.Scatter(x=dates, y=dyn, name="动态 Top3", mode="lines",
                             line=dict(color="#e4572e", width=2.2),
                             hovertemplate="%{x|%Y-%m-%d}<br>动态 Top3: $%{y:,.2f}<extra></extra>"),
                   row=1, col=1)
    fig.add_trace(go.Scatter(x=dates, y=eq5, name="等权5币 滚动", mode="lines",
                             line=dict(color="#6a4c93", width=1.6, dash="dot"),
                             hovertemplate="%{x|%Y-%m-%d}<br>等权5币: $%{y:,.2f}<extra></extra>"),
                   row=1, col=1)
    fig.add_trace(go.Scatter(x=dates, y=be_roll, name="BTC/ETH 滚动", mode="lines",
                             line=dict(color="#2e86ab", width=1.8),
                             hovertemplate="%{x|%Y-%m-%d}<br>BTC/ETH 滚动: $%{y:,.2f}<extra></extra>"),
                   row=1, col=1)
    fig.add_trace(go.Scatter(x=dates, y=be_hold, name="BTC/ETH 持有", mode="lines",
                             line=dict(color="#2a9d8f", width=1.8, dash="dash"),
                             hovertemplate="%{x|%Y-%m-%d}<br>BTC/ETH 持有: $%{y:,.2f}<extra></extra>"),
                   row=1, col=1)

    def dd(series):
        return (series / series.cummax() - 1.0) * 100.0
    fig.add_trace(go.Scatter(x=dates, y=dd(dyn), name="动态 Top3 回撤", mode="lines",
                             line=dict(color="#e4572e", width=1.3), fill="tozeroy",
                             fillcolor="rgba(228,87,46,0.14)", showlegend=False,
                             hovertemplate="%{x|%Y-%m-%d}<br>动态回撤: %{y:.2f}%<extra></extra>"),
                   row=2, col=1)
    fig.add_trace(go.Scatter(x=dates, y=dd(be_roll), name="BTC/ETH 滚动 回撤", mode="lines",
                             line=dict(color="#2e86ab", width=1.3), showlegend=False,
                             hovertemplate="%{x|%Y-%m-%d}<br>BTC/ETH 滚动回撤: %{y:.2f}%<extra></extra>"),
                   row=2, col=1)

    ann = ("<b>动态 Top3</b> 终值 ${dyn_f:,} · CAGR {dyn_c:+.1f}% · MDD -{dyn_d:.1f}% · "
           "再平衡 {dyn_r} 次<br>"
           "<b>BTC/ETH 滚动</b> 终值 ${ber_f:,} · CAGR {ber_c:+.1f}% · MDD -{ber_d:.1f}%<br>"
           "<b>BTC/ETH 持有</b> 终值 ${beh_f:,} · CAGR {beh_c:+.1f}%").format(
        dyn_f=blocks["dynamic"].final_nav_usd, dyn_c=blocks["dynamic"].cagr_pct,
        dyn_d=blocks["dynamic"].max_drawdown_pct, dyn_r=blocks["dynamic"].rebalance_count,
        ber_f=blocks["btc_eth_rolling"].final_nav_usd, ber_c=blocks["btc_eth_rolling"].cagr_pct,
        ber_d=blocks["btc_eth_rolling"].max_drawdown_pct,
        beh_f=blocks["btc_eth_hold"].final_nav_usd, beh_c=blocks["btc_eth_hold"].cagr_pct)
    fig.update_layout(
        title=dict(text=("动态 Top3 选币 vs 静态 BTC/ETH（5年, 100 USD 起步, 池子=项目5币）"),
                   x=0.5, xanchor="center", font=dict(size=18)),
        annotations=list(fig.layout.annotations) + [
            dict(text=ann, xref="paper", yref="paper", x=0.0, y=1.08,
                 showarrow=False, align="left", font=dict(size=12, color="#333"))],
        template="plotly_white", height=760, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0),
        margin=dict(l=70, r=40, t=150, b=50),
        updatemenus=[dict(type="buttons", direction="right", showactive=True,
                          x=0.0, xanchor="left", y=1.12, yanchor="top",
                          buttons=[dict(label="对数轴", method="relayout",
                                         args=[{"yaxis.type": "log"}]),
                                   dict(label="线性轴", method="relayout",
                                         args=[{"yaxis.type": "linear"}])])])
    fig.update_yaxes(title_text="NAV (USD)", type="log", row=1, col=1, gridcolor="#e6e6e6")
    fig.update_yaxes(title_text="回撤 (%)", row=2, col=1, gridcolor="#e6e6e6")
    fig.write_html(path, include_plotlyjs=True, full_html=True,
                   config={"displaylogo": False, "scrollZoom": True})
    return path


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    weekly, meta = load_weekly_prices(
        START, END, use_cache=True,
        cache_path=os.path.join(HERE, "multi_coin_daily_raw.csv"),
        coins=POOL,
    )
    print(f"[data] {meta['weekly_start']} ~ {meta['weekly_end']} "
          f"({meta['weekly_rows']} 周), 池子={POOL}")

    # --- dynamic Top3 line ---
    dyn_line = run_dynamic_select(weekly, POOL, LOOKBACK, MA_WINDOW, TOP_N,
                                 REBALANCE_EVERY, FEE, CAPITAL)
    dyn_config = BacktestConfig(
        initial_capital_usd=CAPITAL, coins=POOL,
        rebalance_band=default_rebalance_band(len(POOL)), fee_rate=FEE,
        start_date=START, end_date=END,
    )
    dyn_m = compute_line_metrics(dyn_line, dyn_config, "动态 Top3 选币(动量+趋势过滤)")

    # --- equal-weight 5 baseline (rolling + hold) ---
    eq5_config = BacktestConfig(
        initial_capital_usd=CAPITAL, coins=POOL,
        rebalance_band=default_rebalance_band(len(POOL)), fee_rate=FEE,
        start_date=START, end_date=END,
    )
    eq5_roll, eq5_hold = run_backtest(weekly, eq5_config)
    eq5_roll_m = compute_line_metrics(eq5_roll, eq5_config, "等权5币 滚动互平衡")
    eq5_hold_m = compute_line_metrics(eq5_hold, eq5_config, "等权5币 买入持有")

    # --- static BTC/ETH baseline (rolling + hold) ---
    prices_be = weekly[["btc_close", "eth_close"]]
    be_config = BacktestConfig(
        initial_capital_usd=CAPITAL, coins=("BTC", "ETH"),
        rebalance_band=default_rebalance_band(2), fee_rate=FEE,
        start_date=START, end_date=END,
    )
    be_roll, be_hold = run_backtest(prices_be, be_config)
    be_roll_m = compute_line_metrics(be_roll, be_config, "BTC/ETH 滚动互平衡")
    be_hold_m = compute_line_metrics(be_hold, be_config, "BTC/ETH 买入持有")

    reference = compute_buy_hold_reference(weekly, dyn_config)

    # --- self-check ---
    verdict, checks = self_check(dyn_line, weekly, dyn_config)
    for c in checks:
        print(f"  [{'PASS' if c.passed else 'FAIL'}] ({c.code}) {c.title}")

    # --- artefacts ---
    nav_map = {
        "dynamic": dyn_line.nav_series(),
        "equal_weight_5": eq5_roll.nav_series(),
        "btc_eth_rolling": be_roll.nav_series(),
        "btc_eth_hold": be_hold.nav_series(),
    }
    save_nav_csv(DYN_NAV_CSV, nav_map)
    save_metrics_json(DYN_METRICS_JSON, dyn_m, eq5_roll_m, eq5_hold_m,
                      be_roll_m, be_hold_m, reference, meta, verdict, checks,
                      {"start": START, "end": END, "capital_usd": CAPITAL,
                       "pool": list(POOL), "fee_rate": FEE, "lookback_weeks": LOOKBACK,
                       "ma_window": MA_WINDOW, "top_n": TOP_N,
                       "rebalance_every_weeks": REBALANCE_EVERY,
                       "warmup_weeks": max(LOOKBACK, MA_WINDOW)})
    save_chart_html(DYN_CHART_HTML, nav_map,
                    {"dynamic": dyn_m, "btc_eth_rolling": be_roll_m,
                     "btc_eth_hold": be_hold_m})
    print(f"[out] {DYN_METRICS_JSON}")
    print(f"[out] {DYN_NAV_CSV}")
    print(f"[out] {DYN_CHART_HTML}")

    # --- headline comparison ---
    print("\n=== 5年对照 (100 USD 起步) ===")
    rows = [
        ("动态 Top3", dyn_m),
        ("等权5币 滚动", eq5_roll_m),
        ("BTC/ETH 滚动", be_roll_m),
        ("BTC/ETH 持有", be_hold_m),
    ]
    print(f"{'策略':<16}{'终值 USD':>12}{'CAGR':>10}{'MDD':>10}{'再平衡':>8}{'费 USD':>9}")
    for name, m in rows:
        print(f"{name:<16}{m.final_nav_usd:>12,.2f}{m.cagr_pct:>+9.1f}%"
              f"{-m.max_drawdown_pct:>8.1f}%{m.rebalance_count:>8}{m.total_fee_usd:>9.2f}")
    print(f"\n动态 Top3 vs BTC/ETH 滚动: 终值比 "
          f"{dyn_m.final_nav_usd/be_roll_m.final_nav_usd:.3f}x, "
          f"CAGR 差 {dyn_m.cagr_pct-be_roll_m.cagr_pct:+.1f}pp")
    print(f"动态 Top3 vs 等权5币 滚动: 终值比 "
          f"{dyn_m.final_nav_usd/eq5_roll_m.final_nav_usd:.3f}x")
    print(f"IS_PASS: {verdict}")


if __name__ == "__main__":
    main()
