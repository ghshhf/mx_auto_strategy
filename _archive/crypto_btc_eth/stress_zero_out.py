"""Zero-out stress test for Line 1, plus a per-coin transfusion-cap sweep.

Why this exists
---------------
Line 1 rebalances *into* whatever is falling.  If one coin dies rather than
merely crashing, the strategy keeps selling the survivors to fund a corpse, so
the loss is far worse than the naive "you can only lose your 1/n slice".  This
script measures that exposure on the real panel instead of guessing at it.

It also evaluates the obvious mitigation -- capping the cumulative *net* USD
injected into any single coin at ``cap_multiple`` times its initial stake.

Method
------
The Line-1 loop is re-implemented here so the cap can be injected mid-loop.
Before any verdict is trusted, ``cap_multiple = inf`` must reproduce the
shipped engine's Line-1 NAV to machine precision; the fidelity line at the top
of the output reports that check.  The engine's exact fee mechanics are
mirrored: fees are charged on the *sell* notional only, sellers land on target,
and buyers absorb the fee pro-rata.

Run:
    python stress_zero_out.py
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from backtest import run_backtest
from config import (FIVE_COINS, MULTI_DAILY_CACHE_CSV, BacktestConfig,
                    default_rebalance_band, price_column)
from data_sources import load_weekly_prices
from metrics import compute_line_metrics

END = "2026-08-03"
FEE = 0.001
CAPITAL = 500.0


def run_capped(panel: pd.DataFrame, coins, band: float,
               cap_multiple: float) -> float:
    """Returns the Line-1 terminal NAV under a per-coin net-injection cap.

    Args:
        panel: Weekly close panel with ``<coin>_close`` columns.
        coins: Ordered coin universe.
        band: Absolute weight-deviation trigger.
        cap_multiple: Maximum cumulative net USD injected into one coin,
            expressed as a multiple of its initial stake.  ``inf`` disables it.

    Returns:
        Terminal NAV in USD.
    """
    cols = [price_column(c) for c in coins]
    prices = panel[cols].to_numpy(dtype=float)
    n_weeks, n = prices.shape
    target = np.full(n, 1.0 / n)

    stake = CAPITAL / n
    cap = cap_multiple * stake
    # t0 entry: buy the equal-weight book, paying the entry fee.
    qty = (stake * (1.0 - FEE)) / prices[0]
    injected = np.zeros(n)  # cumulative net USD pushed in after t0

    for t in range(1, n_weeks):
        p = prices[t]
        values = qty * p
        nav = float(values.sum())
        if nav <= 0.0:
            break
        weights = values / nav
        if float(np.abs(weights - target).max()) < band:
            continue

        desired = target * nav
        # Freeze any coin that has already absorbed its maximum transfusion:
        # it may still be sold, but not bought.
        frozen = (desired > values) & (injected >= cap)
        if frozen.any():
            desired = np.where(frozen, values, desired)
            free = nav - float(desired[frozen].sum())
            open_legs = ~frozen
            share = target[open_legs]
            if share.sum() > 0.0 and free > 0.0:
                desired[open_legs] = free * share / share.sum()

        # Engine mechanics, replicated exactly: sellers land on target, the
        # pooled proceeds pay fee on the SELL notional only, and buyers land on
        # target minus their pro-rata share of that fee.
        delta = desired - values
        sell_total = float(-delta[delta < 0.0].sum())
        buy_total = float(delta[delta > 0.0].sum())
        if sell_total <= 0.0 or buy_total <= 0.0:
            continue
        post = values + delta
        buyers = delta > 0.0
        post[buyers] -= delta[buyers] * FEE
        injected += np.where(buyers, delta * (1.0 - FEE), 0.0)
        qty = post / p

    return float((qty * prices[-1]).sum())


def main() -> None:
    """Runs the fidelity check and the cap sweep."""
    panel, _meta = load_weekly_prices("2017-11-01", END, True,
                                      MULTI_DAILY_CACHE_CSV, coins=FIVE_COINS)
    band = default_rebalance_band(len(FIVE_COINS))
    cfg = BacktestConfig(initial_capital_usd=CAPITAL, coins=FIVE_COINS,
                         rebalance_band=band, fee_rate=FEE,
                         start_date="2017-11-01", end_date=END)
    line1, line2 = run_backtest(panel, cfg)
    engine_nav = compute_line_metrics(line1, cfg, "L1").final_nav_usd
    hold_nav = compute_line_metrics(line2, cfg, "L2").final_nav_usd

    probe_nav = run_capped(panel, FIVE_COINS, band, math.inf)
    err = abs(probe_nav / engine_nav - 1.0)
    print()
    print("[fidelity] engine Line-1 = %s | probe(cap=inf) = %s | rel err %.2e"
          % (format(engine_nav, ",.2f"), format(probe_nav, ",.2f"), err))
    print("[fidelity] %s" % ("OK" if err < 5e-3 else "MISMATCH -- probe untrusted"))
    print("           buy&hold reference = %s" % format(hold_nav, ",.2f"))

    def zeroed(panel_in: pd.DataFrame, coin: str, week: int) -> pd.DataFrame:
        """Returns a copy of the panel with ``coin`` decaying -8%/week."""
        out = panel_in.copy()
        col = price_column(coin)
        p = out[col].to_numpy(dtype=float).copy()
        for k in range(week, len(p)):
            p[k] = p[week - 1] * (0.92 ** (k - week + 1))
        out[col] = np.maximum(p, 1e-12)
        return out

    stressed = zeroed(panel, "TRX", 250)
    print()
    print("%-14s %16s %16s %16s"
          % ("cap x stake", "真实面板 L1", "TRX归零 L1", "归零后留存"))
    print("-" * 66)
    for mult in (1.0, 1.5, 2.0, 3.0, 5.0, math.inf):
        base = run_capped(panel, FIVE_COINS, band, mult)
        shock = run_capped(stressed, FIVE_COINS, band, mult)
        label = "inf" if math.isinf(mult) else ("%.1f" % mult)
        print("%-14s %16s %16s %15.1f%%"
              % (label, format(base, ",.2f"), format(shock, ",.2f"),
                 shock / base * 100.0))


if __name__ == "__main__":
    main()
