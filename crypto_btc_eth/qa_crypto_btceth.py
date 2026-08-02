"""Independent QA verification suite for the BTC/ETH pair-rebalancing backtest.

Written by QA (Edward) as a *fresh-eyes* cross-check of the engineer's
deliverable.  Nothing in production code is imported for the cross-recompute
tests -- those re-implement the strategy from scratch straight off the CSVs so
that a shared bug in ``backtest.py`` cannot hide behind a shared assumption.

Test groups
-----------
A. Fee conservation on a hand-built micro price path.
B. Rebalance-threshold semantics (1 percentage point, *not* 1% relative).
C. Line-2 buy-and-hold identity checked against ``nav_btc_eth.csv``.
D. Max-drawdown maths (hand-computed series + O(n^2) brute force on real NAV).
E. Data honesty of ``btc_eth_weekly.csv`` / daily raw / meta provenance.
F. Independent plain-loop recompute of both terminal NAVs.

Run:
    python qa_crypto_btceth.py            # verbose unittest run
"""
from __future__ import annotations

import csv
import decimal
import json
import math
import os
import sys
import unittest
from datetime import date, datetime

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from backtest import run_backtest, run_buy_and_hold, run_rolling_rebalance  # noqa: E402
from config import BacktestConfig  # noqa: E402
import metrics as metrics_mod  # noqa: E402

WEEKLY_CSV = os.path.join(HERE, "btc_eth_weekly.csv")
DAILY_CSV = os.path.join(HERE, "btc_eth_daily_raw.csv")
META_JSON = os.path.join(HERE, "btc_eth_daily_raw.meta.json")
NAV_CSV = os.path.join(HERE, "nav_btc_eth.csv")
METRICS_JSON = os.path.join(HERE, "metrics_btc_eth.json")

# Headline numbers the engineer reported; QA must reproduce them independently.
CLAIMED_LINE1_FINAL = 48999.07
CLAIMED_LINE2_FINAL = 27533.44
CLAIMED_REBALANCES = 256
CLAIMED_TOTAL_FEE = 150.54
CLAIMED_WEEKLY_ROWS = 523


# --------------------------------------------------------------------------- #
# Shared loaders (module-level cache so 6 test classes read each file once)
# --------------------------------------------------------------------------- #
def load_weekly_rows() -> list[tuple[str, float, float]]:
    """Reads the weekly panel with the stdlib csv module (no pandas coercion)."""
    rows: list[tuple[str, float, float]] = []
    with open(WEEKLY_CSV, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["date", "btc_close", "eth_close"], (
            f"unexpected weekly header: {reader.fieldnames}")
        for record in reader:
            rows.append((record["date"],
                         float(record["btc_close"]),
                         float(record["eth_close"])))
    return rows


def load_nav_rows() -> list[tuple[str, float, float]]:
    """Reads the published NAV curve."""
    rows: list[tuple[str, float, float]] = []
    with open(NAV_CSV, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["date", "nav_line1", "nav_line2"], (
            f"unexpected nav header: {reader.fieldnames}")
        for record in reader:
            rows.append((record["date"],
                         float(record["nav_line1"]),
                         float(record["nav_line2"])))
    return rows


def load_daily_frame() -> pd.DataFrame:
    """Reads the raw daily cache indexed by date."""
    frame = pd.read_csv(DAILY_CSV, parse_dates=["date"])
    return frame.set_index("date").sort_index()


def load_metrics() -> dict:
    with open(METRICS_JSON, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_meta() -> dict:
    with open(META_JSON, "r", encoding="utf-8") as handle:
        return json.load(handle)


WEEKLY_ROWS = load_weekly_rows()
NAV_ROWS = load_nav_rows()
METRICS = load_metrics()
META = load_meta()

QA_CONFIG = BacktestConfig()


def make_frame(prices: list[tuple[str, float, float]]) -> pd.DataFrame:
    """Builds a weekly price panel from ``(date, btc, eth)`` triples."""
    frame = pd.DataFrame(prices, columns=["date", "btc_close", "eth_close"])
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date")


def eth_multiplier_for_deviation(deviation: float) -> float:
    """Returns the ETH price multiplier that lands ETH weight on ``0.5 + dev``.

    Starting from an exact 50/50 split with BTC held flat, scaling ETH by ``r``
    gives ``w_eth = r / (1 + r)``.  Inverting for ``w_eth = 0.5 + dev`` yields
    ``r = (0.5 + dev) / (0.5 - dev)``.
    """
    return (0.5 + deviation) / (0.5 - deviation)


# --------------------------------------------------------------------------- #
# Independent re-implementation used by group F (does NOT import backtest.py)
# --------------------------------------------------------------------------- #
def plain_loop_line1(rows, capital=200.0, fee=0.001, band=0.01, target=0.5):
    """From-scratch banded rebalance loop. Returns a result dictionary."""
    entry_fee = capital * fee
    net = capital - entry_fee
    _d0, btc0, eth0 = rows[0]
    q_btc = (net * (1.0 - target)) / btc0
    q_eth = (net * target) / eth0
    total_fee = entry_fee
    trades = 0
    navs = []
    for index, (_dt, btc_price, eth_price) in enumerate(rows):
        btc_value = q_btc * btc_price
        eth_value = q_eth * eth_price
        nav = btc_value + eth_value
        if index > 0 and abs(eth_value / nav - target) >= band:
            half = nav * target
            if eth_value > half:
                notional = eth_value - half
                q_eth -= notional / eth_price
                q_btc += notional * (1.0 - fee) / btc_price
            else:
                notional = half - eth_value
                q_btc -= notional / btc_price
                q_eth += notional * (1.0 - fee) / eth_price
            total_fee += notional * fee
            trades += 1
            nav = q_btc * btc_price + q_eth * eth_price
        navs.append(nav)
    return {"final_nav": navs[-1], "navs": navs, "trades": trades,
            "total_fee": total_fee, "q_btc": q_btc, "q_eth": q_eth}


def plain_loop_line2(rows, capital=200.0, fee=0.001, target=0.5):
    """From-scratch buy-and-hold loop. Returns a result dictionary."""
    net = capital * (1.0 - fee)
    _d0, btc0, eth0 = rows[0]
    q_btc = (net * (1.0 - target)) / btc0
    q_eth = (net * target) / eth0
    navs = [q_btc * btc_price + q_eth * eth_price
            for _dt, btc_price, eth_price in rows]
    return {"final_nav": navs[-1], "navs": navs, "q_btc": q_btc, "q_eth": q_eth}


def decimal_loop_line1(rows, capital="200", fee="0.001", band="0.01",
                       target="0.5"):
    """Same strategy, recomputed in 50-digit decimal arithmetic.

    A genuinely different numeric path: if the float64 engine were accumulating
    material rounding error over 523 bars and 256 trades, the two answers would
    separate here.
    """
    with decimal.localcontext() as context:
        context.prec = 50
        one = decimal.Decimal(1)
        fee_d = decimal.Decimal(fee)
        band_d = decimal.Decimal(band)
        target_d = decimal.Decimal(target)
        net = decimal.Decimal(capital) * (one - fee_d)
        _d0, btc0, eth0 = rows[0]
        q_btc = net * (one - target_d) / decimal.Decimal(repr(btc0))
        q_eth = net * target_d / decimal.Decimal(repr(eth0))
        nav = net
        trades = 0
        for index, (_dt, btc_price, eth_price) in enumerate(rows):
            btc_d = decimal.Decimal(repr(btc_price))
            eth_d = decimal.Decimal(repr(eth_price))
            btc_value = q_btc * btc_d
            eth_value = q_eth * eth_d
            nav = btc_value + eth_value
            if index > 0 and abs(eth_value / nav - target_d) >= band_d:
                half = nav * target_d
                if eth_value > half:
                    notional = eth_value - half
                    q_eth -= notional / eth_d
                    q_btc += notional * (one - fee_d) / btc_d
                else:
                    notional = half - eth_value
                    q_btc -= notional / btc_d
                    q_eth += notional * (one - fee_d) / eth_d
                trades += 1
                nav = q_btc * btc_d + q_eth * eth_d
        return {"final_nav": nav, "trades": trades}


def brute_force_max_drawdown(values: list[float]) -> float:
    """O(n^2) worst peak-to-trough decline, as a positive percentage."""
    worst = 0.0
    count = len(values)
    for i in range(count):
        peak = values[i]
        if peak <= 0.0:
            continue
        for j in range(i + 1, count):
            decline = values[j] / peak - 1.0
            if decline < worst:
                worst = decline
    return -worst * 100.0


# --------------------------------------------------------------------------- #
# Group A -- fee conservation on a controlled micro path
# --------------------------------------------------------------------------- #
class TestFeeConservation(unittest.TestCase):
    """Every USD of fee must be traceable to a trade, and only to a trade."""

    def setUp(self) -> None:
        # Week 0: open at 50/50.
        # Week 1: prices flat  -> deviation 0    -> must NOT trade.
        # Week 2: ETH doubles  -> w_eth = 2/3    -> must trade.
        # Week 3: prices flat  -> deviation ~0   -> must NOT trade.
        self.frame = make_frame([
            ("2020-01-03", 100.0, 100.0),
            ("2020-01-10", 100.0, 100.0),
            ("2020-01-17", 100.0, 200.0),
            ("2020-01-24", 100.0, 200.0),
        ])
        self.line = run_rolling_rebalance(self.frame, QA_CONFIG)

    def test_entry_fee_is_charged_once_on_gross_principal(self) -> None:
        first = self.line.records[0]
        self.assertTrue(first.traded)
        self.assertAlmostEqual(first.fee_paid, 200.0 * 0.001, places=12)
        self.assertAlmostEqual(first.nav, 199.8, places=12)
        self.assertAlmostEqual(first.weight_eth_post, 0.5, places=12)

    def test_flat_week_does_not_trade_and_charges_no_fee(self) -> None:
        flat = self.line.records[1]
        self.assertFalse(flat.traded, "flat prices must not trigger a rebalance")
        self.assertEqual(flat.fee_paid, 0.0)
        self.assertAlmostEqual(flat.nav, 199.8, places=12)
        self.assertAlmostEqual(flat.qty_btc, self.line.records[0].qty_btc, places=15)
        self.assertAlmostEqual(flat.qty_eth, self.line.records[0].qty_eth, places=15)

    def test_trade_week_fee_equals_notional_times_rate(self) -> None:
        pre = self.line.records[1]
        trade = self.line.records[2]
        self.assertTrue(trade.traded, "w_eth = 2/3 is 16.7pp off target, must trade")

        nav_pre = pre.qty_btc * 100.0 + pre.qty_eth * 200.0
        eth_value_pre = pre.qty_eth * 200.0
        expected_notional = eth_value_pre - nav_pre / 2.0

        self.assertAlmostEqual(trade.weight_eth_pre, 2.0 / 3.0, places=12)
        self.assertAlmostEqual(trade.traded_notional, expected_notional, places=10)
        self.assertAlmostEqual(trade.fee_paid, expected_notional * 0.001, places=12)
        # Fee conservation: the *only* NAV leakage on a trade week is the fee.
        self.assertAlmostEqual(trade.nav, nav_pre - expected_notional * 0.001,
                               places=10)
        # And the post-trade split is back on target bar the fee crumb.
        self.assertLess(abs(trade.weight_eth_post - 0.5), 0.001 / 2.0)

    def test_week_after_trade_is_price_only(self) -> None:
        trade = self.line.records[2]
        after = self.line.records[3]
        self.assertFalse(after.traded)
        self.assertEqual(after.fee_paid, 0.0)
        self.assertAlmostEqual(after.qty_btc, trade.qty_btc, places=15)
        self.assertAlmostEqual(after.qty_eth, trade.qty_eth, places=15)
        self.assertAlmostEqual(after.nav,
                               trade.qty_btc * 100.0 + trade.qty_eth * 200.0,
                               places=10)

    def test_total_fee_equals_sum_of_weekly_fees(self) -> None:
        weekly_sum = sum(record.fee_paid for record in self.line.records)
        self.assertAlmostEqual(self.line.total_fee, weekly_sum, places=12)
        self.assertEqual(self.line.rebalance_count, 1)

    def test_zero_fee_rebalance_conserves_nav_exactly(self) -> None:
        free = BacktestConfig(fee_rate=0.0)
        line = run_rolling_rebalance(self.frame, free)
        nav_pre = line.records[1].qty_btc * 100.0 + line.records[1].qty_eth * 200.0
        self.assertTrue(line.records[2].traded)
        self.assertAlmostEqual(line.records[2].nav, nav_pre, places=10)
        self.assertAlmostEqual(line.records[2].weight_eth_post, 0.5, places=12)


# --------------------------------------------------------------------------- #
# Group B -- threshold semantics
# --------------------------------------------------------------------------- #
class TestRebalanceThreshold(unittest.TestCase):
    """``band = 0.01`` must mean 1 percentage point of absolute weight."""

    def _run_with_deviation(self, deviation: float):
        multiplier = eth_multiplier_for_deviation(deviation)
        frame = make_frame([
            ("2020-01-03", 100.0, 100.0),
            ("2020-01-10", 100.0, 100.0 * multiplier),
        ])
        return run_rolling_rebalance(frame, QA_CONFIG)

    def test_construction_helper_is_exact(self) -> None:
        for deviation in (0.0099, 0.0101, 0.006, -0.0101):
            line = self._run_with_deviation(deviation)
            self.assertAlmostEqual(line.records[1].weight_eth_pre, 0.5 + deviation,
                                   places=13,
                                   msg=f"fixture mis-built for dev={deviation}")

    def test_deviation_0_99pp_does_not_rebalance(self) -> None:
        line = self._run_with_deviation(0.0099)
        self.assertFalse(line.records[1].traded)
        self.assertEqual(line.rebalance_count, 0)
        self.assertEqual(line.records[1].fee_paid, 0.0)

    def test_deviation_1_01pp_rebalances(self) -> None:
        line = self._run_with_deviation(0.0101)
        self.assertTrue(line.records[1].traded)
        self.assertEqual(line.rebalance_count, 1)
        self.assertGreater(line.records[1].fee_paid, 0.0)

    def test_band_is_absolute_pp_not_one_percent_relative(self) -> None:
        # A "1% relative of the 50% target" reading would put the trigger at
        # 0.5pp, so a 0.6pp drift would fire. Under the correct 1pp reading it
        # must stay put. This is the discriminating case.
        line = self._run_with_deviation(0.006)
        self.assertFalse(
            line.records[1].traded,
            "0.6pp drift traded -> band is being read as 1% relative (0.5pp), "
            "not as 1 percentage point")

    def test_exact_boundary_is_inclusive(self) -> None:
        just_below = self._run_with_deviation(0.01 - 1e-9)
        just_above = self._run_with_deviation(0.01 + 1e-9)
        self.assertFalse(just_below.records[1].traded)
        self.assertTrue(just_above.records[1].traded)

    def test_underweight_eth_triggers_and_buys_eth(self) -> None:
        line = self._run_with_deviation(-0.0101)
        record = line.records[1]
        self.assertTrue(record.traded)
        self.assertGreater(record.qty_eth, line.initial_qty_eth,
                           "ETH underweight must be bought, not sold")
        self.assertLess(record.qty_btc, line.initial_qty_btc)
        self.assertLess(abs(record.weight_eth_post - 0.5), 0.001)

    def test_every_real_trade_week_was_out_of_band(self) -> None:
        # On the production panel: no trade may fire inside the band, and no
        # in-band week may be skipped.
        frame = make_frame(WEEKLY_ROWS)
        line1, _line2 = run_backtest(frame, QA_CONFIG)
        false_positives = []
        false_negatives = []
        for index, record in enumerate(line1.records):
            if index == 0:
                continue
            out_of_band = abs(record.weight_eth_pre - 0.5) >= 0.01
            if record.traded and not out_of_band:
                false_positives.append(record.date)
            if out_of_band and not record.traded:
                false_negatives.append(record.date)
        self.assertEqual(false_positives, [], "traded while inside the band")
        self.assertEqual(false_negatives, [], "skipped a week outside the band")
        self.assertEqual(line1.rebalance_count, CLAIMED_REBALANCES)


# --------------------------------------------------------------------------- #
# Group C -- line 2 identity straight off the published NAV curve
# --------------------------------------------------------------------------- #
class TestBuyAndHoldFormula(unittest.TestCase):
    """``nav_line2[t] == q_eth * eth[t] + q_btc * btc[t]`` for every week."""

    @classmethod
    def setUpClass(cls) -> None:
        net = 200.0 * (1.0 - 0.001)
        _d0, btc0, eth0 = WEEKLY_ROWS[0]
        cls.q_btc = net * 0.5 / btc0
        cls.q_eth = net * 0.5 / eth0

    def test_row_alignment_between_weekly_and_nav_csv(self) -> None:
        self.assertEqual(len(WEEKLY_ROWS), len(NAV_ROWS))
        mismatched = [(a[0], b[0]) for a, b in zip(WEEKLY_ROWS, NAV_ROWS)
                      if a[0] != b[0]]
        self.assertEqual(mismatched, [])

    def test_line2_is_pure_quantity_times_price_every_week(self) -> None:
        worst_abs = 0.0
        worst_rel = 0.0
        worst_date = ""
        for (dt, btc_price, eth_price), (_nav_dt, _n1, nav2) in zip(WEEKLY_ROWS,
                                                                    NAV_ROWS):
            expected = self.q_eth * eth_price + self.q_btc * btc_price
            error = abs(nav2 - expected)
            relative = error / expected
            if relative > worst_rel:
                worst_abs, worst_rel, worst_date = error, relative, dt
        # nav csv is serialised to 6 decimals, so ~5e-7 absolute is pure I/O
        # rounding. Anything larger would be a real fee/quantity drift.
        self.assertLess(worst_abs, 1e-5,
                        f"line2 drifts from q*p at {worst_date} "
                        f"(abs {worst_abs:.3e}, rel {worst_rel:.3e})")

    def test_line2_pays_exactly_one_entry_fee_and_nothing_else(self) -> None:
        self.assertAlmostEqual(NAV_ROWS[0][2], 199.8, places=6)
        frame = make_frame(WEEKLY_ROWS)
        line2 = run_buy_and_hold(frame, QA_CONFIG)
        self.assertEqual(line2.rebalance_count, 0)
        self.assertAlmostEqual(line2.total_fee, 0.2, places=12)
        self.assertEqual(sum(r.fee_paid for r in line2.records[1:]), 0.0)
        drifted = [r.date for r in line2.records
                   if r.qty_btc != line2.initial_qty_btc
                   or r.qty_eth != line2.initial_qty_eth]
        self.assertEqual(drifted, [], "buy & hold quantities must never change")

    def test_line2_equals_average_of_the_two_single_asset_references(self) -> None:
        # Equal dollar split with no rebalancing => terminal NAV is exactly the
        # arithmetic mean of an all-BTC and an all-ETH position.
        reference = METRICS["single_asset_reference"]
        expected = (reference["all_btc_final_usd"]
                    + reference["all_eth_final_usd"]) / 2.0
        self.assertAlmostEqual(expected, METRICS["line2_buy_and_hold"]
                               ["final_nav_usd"], places=6)


# --------------------------------------------------------------------------- #
# Group D -- drawdown maths
# --------------------------------------------------------------------------- #
class TestDrawdownMath(unittest.TestCase):
    """Hand-computed drawdowns must match ``metrics.compute_max_drawdown``."""

    @staticmethod
    def _series(values: list[float]) -> pd.Series:
        index = pd.date_range("2020-01-03", periods=len(values), freq="7D")
        return pd.Series(values, index=index, dtype=float)

    def test_hand_computed_drawdown(self) -> None:
        # peak 120 -> trough 60 is -50.0%; the later 150 -> 80 leg is -46.67%.
        series = self._series([100.0, 120.0, 60.0, 90.0, 150.0, 80.0])
        info = metrics_mod.compute_max_drawdown(series)
        self.assertAlmostEqual(info.max_drawdown_pct, 50.0, places=10)
        self.assertEqual(info.peak_date, "2020-01-10")
        self.assertEqual(info.trough_date, "2020-01-17")
        self.assertEqual(info.recovery_date, "2020-01-31")
        self.assertAlmostEqual(info.peak_nav, 120.0, places=10)
        self.assertAlmostEqual(info.trough_nav, 60.0, places=10)

    def test_unrecovered_drawdown_reports_empty_recovery(self) -> None:
        series = self._series([100.0, 200.0, 50.0, 60.0])
        info = metrics_mod.compute_max_drawdown(series)
        self.assertAlmostEqual(info.max_drawdown_pct, 75.0, places=10)
        self.assertEqual(info.recovery_date, "")

    def test_monotonic_series_has_zero_drawdown(self) -> None:
        series = self._series([10.0, 11.0, 12.0, 13.0])
        info = metrics_mod.compute_max_drawdown(series)
        self.assertAlmostEqual(info.max_drawdown_pct, 0.0, places=12)

    def test_drawdown_series_is_percentage_from_running_peak(self) -> None:
        series = self._series([100.0, 80.0, 120.0, 60.0])
        running = metrics_mod.compute_drawdown_series(series).tolist()
        for got, want in zip(running, [0.0, -20.0, 0.0, -50.0]):
            self.assertAlmostEqual(got, want, places=10)

    def test_published_drawdowns_match_brute_force(self) -> None:
        nav1 = [row[1] for row in NAV_ROWS]
        nav2 = [row[2] for row in NAV_ROWS]
        got1 = brute_force_max_drawdown(nav1)
        got2 = brute_force_max_drawdown(nav2)
        self.assertAlmostEqual(got1, METRICS["line1_rolling_rebalance"]
                               ["max_drawdown_pct"], places=4)
        self.assertAlmostEqual(got2, METRICS["line2_buy_and_hold"]
                               ["max_drawdown_pct"], places=4)
        self.assertAlmostEqual(got1, 87.1876, places=3)
        self.assertAlmostEqual(got2, 90.4629, places=3)

    def test_published_cagr_and_total_return_formulas(self) -> None:
        for key, final in (("line1_rolling_rebalance", CLAIMED_LINE1_FINAL),
                           ("line2_buy_and_hold", CLAIMED_LINE2_FINAL)):
            block = METRICS[key]
            start = datetime.strptime(block["start_date"], "%Y-%m-%d").date()
            end = datetime.strptime(block["end_date"], "%Y-%m-%d").date()
            years = (end - start).days / 365.25
            self.assertAlmostEqual(years, block["years"], places=3)
            nav = block["final_nav_usd"]
            self.assertAlmostEqual(nav, final, places=2)
            self.assertAlmostEqual((nav / 200.0 - 1.0) * 100.0,
                                   block["total_return_pct"], places=6)
            self.assertAlmostEqual(((nav / 200.0) ** (1.0 / years) - 1.0) * 100.0,
                                   block["cagr_pct"], places=4)


# --------------------------------------------------------------------------- #
# Group E -- data honesty
# --------------------------------------------------------------------------- #
class TestDataHonesty(unittest.TestCase):
    """The price panel must be real, complete and provenance-consistent."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.daily = load_daily_frame()
        cls.boundary = pd.Timestamp(META["splices"]["ETH"]["boundary_date"])

    def test_weekly_shape_and_range(self) -> None:
        self.assertEqual(len(WEEKLY_ROWS), CLAIMED_WEEKLY_ROWS)
        self.assertEqual(WEEKLY_ROWS[0][0], "2016-08-05")
        self.assertEqual(WEEKLY_ROWS[-1][0], "2026-08-02")

    def test_weekly_has_no_nan_non_positive_or_duplicate(self) -> None:
        seen: set[str] = set()
        previous: date | None = None
        for dt, btc_price, eth_price in WEEKLY_ROWS:
            self.assertNotIn(dt, seen, f"duplicate weekly date {dt}")
            seen.add(dt)
            current = datetime.strptime(dt, "%Y-%m-%d").date()
            if previous is not None:
                self.assertGreater(current, previous, f"non-monotonic at {dt}")
            previous = current
            for name, value in (("btc", btc_price), ("eth", eth_price)):
                self.assertFalse(math.isnan(value), f"NaN {name} at {dt}")
                self.assertFalse(math.isinf(value), f"inf {name} at {dt}")
                self.assertGreater(value, 0.0, f"non-positive {name} at {dt}")

    def test_weekly_spacing_is_weekly(self) -> None:
        dates = [datetime.strptime(row[0], "%Y-%m-%d").date()
                 for row in WEEKLY_ROWS]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        oversized = [(dates[i + 1], gap) for i, gap in enumerate(gaps) if gap > 8]
        self.assertEqual(oversized, [], f"weekly gaps larger than 8 days: {oversized}")
        # One short final bin is expected (partial week) and is declared in meta.
        short = [(dates[i + 1], gap) for i, gap in enumerate(gaps) if gap < 7]
        self.assertLessEqual(len(short), 1, f"unexpected short bins: {short}")
        if short:
            self.assertEqual(short[0][0].isoformat(), WEEKLY_ROWS[-1][0])
            self.assertIn(WEEKLY_ROWS[-1][0],
                          METRICS["data"]["weekly_non_friday_bars"],
                          "the short final bin must be disclosed in metrics")

    def test_weekly_closes_are_real_daily_closes(self) -> None:
        # Every weekly bar must be an actual observed daily close on that date,
        # i.e. a resample, never a smoothed/interpolated construct.
        mismatches = []
        for dt, btc_price, eth_price in WEEKLY_ROWS:
            stamp = pd.Timestamp(dt)
            self.assertIn(stamp, self.daily.index, f"weekly date {dt} absent daily")
            row = self.daily.loc[stamp]
            if (abs(float(row["btc_close"]) - btc_price) > 1e-6
                    or abs(float(row["eth_close"]) - eth_price) > 1e-6):
                mismatches.append(dt)
        self.assertEqual(mismatches[:5], [],
                         f"{len(mismatches)} weekly bars differ from the daily close")

    def test_daily_cache_is_complete_and_positive(self) -> None:
        self.assertFalse(self.daily.isna().any().any(), "daily cache has NaN")
        self.assertTrue((self.daily > 0.0).all().all(), "daily cache has non-positive")
        span = (self.daily.index[-1] - self.daily.index[0]).days + 1
        self.assertEqual(len(self.daily), span, "daily cache has calendar holes")
        self.assertEqual(len(self.daily), METRICS["data"]["daily_rows"])

    def test_eth_gap_segment_is_filled_with_real_coinbase_spot(self) -> None:
        sources = META["sources"]["ETH"]
        self.assertTrue(any("coinbase" in s.lower() for s in sources),
                        f"meta does not declare a Coinbase filler: {sources}")
        self.assertTrue(any("yahoo" in s.lower() for s in sources))
        filler = self.daily.loc[self.daily.index < self.boundary, "eth_close"]

        # (1) The declared gap length must match the data.
        declared = [s for s in sources if "coinbase" in s.lower()][0]
        self.assertIn(f"{len(filler)}d", declared,
                      f"meta says {declared!r} but the gap holds {len(filler)} rows")
        self.assertEqual(len(filler), 465)

        # (2) Values exist and are positive -- no forward-filled zeros.
        self.assertTrue((filler > 0.0).all())
        self.assertFalse(filler.isna().any())

        # (3) Not interpolated: a linear/constant fill would show a tiny number
        #     of distinct daily increments and near-zero realised volatility.
        returns = filler.pct_change().dropna()
        self.assertGreater(returns.std(), 0.02,
                           "filler daily vol is too low to be real spot data")
        self.assertGreater(returns.abs().max(), 0.10,
                           "filler never moves >10% in a day -- looks synthetic")
        self.assertGreater((returns < 0).mean(), 0.30,
                           "filler is near-monotonic -- looks interpolated")
        self.assertGreater(filler.round(2).nunique() / len(filler), 0.80,
                           "filler has too many repeated levels")
        increments = filler.diff().dropna().round(6)
        longest_run = 1
        run = 1
        for previous, current in zip(increments[:-1], increments[1:]):
            run = run + 1 if current == previous else 1
            longest_run = max(longest_run, run)
        self.assertLess(longest_run, 4,
                        "constant-increment run detected -> linear interpolation")

        # (4) Splice boundary is continuous, not a jump artefact.
        splice = META["splices"]["ETH"]
        self.assertAlmostEqual(float(filler.iloc[-1]), splice["last_filler_close"],
                               places=6)
        first_primary = float(self.daily.loc[self.boundary, "eth_close"])
        self.assertAlmostEqual(first_primary, splice["first_primary_close"],
                               places=6)
        self.assertLess(abs(splice["boundary_return_pct"]), 25.0,
                        "splice boundary jump is implausible for one day")

    def test_prices_match_known_crypto_history(self) -> None:
        # Independent sanity anchors from public market history (wide bands).
        anchors = [
            ("2016-08-01", "btc_close", 500.0, 700.0),
            ("2016-08-01", "eth_close", 8.0, 15.0),
            ("2017-01-01", "eth_close", 6.0, 12.0),
            ("2017-06-12", "eth_close", 280.0, 460.0),
            ("2017-11-08", "eth_close", 280.0, 340.0),
            ("2017-12-16", "btc_close", 17000.0, 21000.0),
            ("2021-11-10", "btc_close", 58000.0, 72000.0),
            ("2021-11-10", "eth_close", 4100.0, 5100.0),
        ]
        for dt, column, low, high in anchors:
            stamp = pd.Timestamp(dt)
            if stamp not in self.daily.index:
                continue
            value = float(self.daily.loc[stamp, column])
            self.assertTrue(low <= value <= high,
                            f"{column} on {dt} = {value} outside plausible "
                            f"[{low}, {high}] -- data may be fabricated")

    def test_meta_and_metrics_provenance_agree(self) -> None:
        self.assertEqual(META["sources"], METRICS["data"]["sources"])
        self.assertEqual(META["splices"], METRICS["data"]["splices"])
        self.assertEqual(METRICS["data"]["weekly_rows"], len(WEEKLY_ROWS))
        self.assertEqual(METRICS["config"]["rebalance_band"], 0.01)
        self.assertEqual(METRICS["config"]["fee_rate"], 0.001)
        self.assertEqual(METRICS["config"]["initial_capital_usd"], 200.0)
        self.assertEqual(METRICS["config"]["target_weight_eth"], 0.5)

    def test_default_config_matches_the_brief(self) -> None:
        self.assertEqual(QA_CONFIG.initial_capital_usd, 200.0)
        self.assertEqual(QA_CONFIG.target_weight_eth, 0.5)
        self.assertEqual(QA_CONFIG.target_weight_btc(), 0.5)
        self.assertEqual(QA_CONFIG.rebalance_band, 0.01)
        self.assertEqual(QA_CONFIG.fee_rate, 0.001)


# --------------------------------------------------------------------------- #
# Group F -- independent recompute
# --------------------------------------------------------------------------- #
class TestCrossRecompute(unittest.TestCase):
    """A from-scratch loop must land on the same terminal NAVs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.line1 = plain_loop_line1(WEEKLY_ROWS)
        cls.line2 = plain_loop_line2(WEEKLY_ROWS)

    def test_line1_terminal_nav(self) -> None:
        published = METRICS["line1_rolling_rebalance"]["final_nav_usd"]
        got = self.line1["final_nav"]
        self.assertLess(abs(got - published), 1e-6,
                        f"plain loop {got!r} vs published {published!r}")
        self.assertAlmostEqual(round(got, 2), CLAIMED_LINE1_FINAL, places=2)
        self.assertAlmostEqual(got, NAV_ROWS[-1][1], places=5)

    def test_line2_terminal_nav(self) -> None:
        published = METRICS["line2_buy_and_hold"]["final_nav_usd"]
        got = self.line2["final_nav"]
        self.assertLess(abs(got - published), 1e-6,
                        f"plain loop {got!r} vs published {published!r}")
        self.assertAlmostEqual(round(got, 2), CLAIMED_LINE2_FINAL, places=2)
        self.assertAlmostEqual(got, NAV_ROWS[-1][2], places=5)

    def test_full_nav_paths_agree_not_just_the_endpoint(self) -> None:
        worst1 = max(abs(a - b[1]) for a, b in zip(self.line1["navs"], NAV_ROWS))
        worst2 = max(abs(a - b[2]) for a, b in zip(self.line2["navs"], NAV_ROWS))
        self.assertLess(worst1, 1e-5, f"line1 path max abs error {worst1:.3e}")
        self.assertLess(worst2, 1e-5, f"line2 path max abs error {worst2:.3e}")

    def test_trade_count_and_total_fee(self) -> None:
        self.assertEqual(self.line1["trades"], CLAIMED_REBALANCES)
        self.assertEqual(self.line1["trades"],
                         METRICS["line1_rolling_rebalance"]["rebalance_count"])
        self.assertAlmostEqual(self.line1["total_fee"],
                               METRICS["line1_rolling_rebalance"]["total_fee_usd"],
                               places=8)
        self.assertAlmostEqual(round(self.line1["total_fee"], 2),
                               CLAIMED_TOTAL_FEE, places=2)

    def test_production_engine_matches_plain_loop(self) -> None:
        frame = make_frame(WEEKLY_ROWS)
        line1, line2 = run_backtest(frame, QA_CONFIG)
        self.assertAlmostEqual(line1.final_nav(), self.line1["final_nav"], places=8)
        self.assertAlmostEqual(line2.final_nav(), self.line2["final_nav"], places=8)
        self.assertEqual(line1.rebalance_count, self.line1["trades"])
        self.assertAlmostEqual(line1.total_fee, self.line1["total_fee"], places=10)

    def test_rebalance_alpha_is_economically_coherent(self) -> None:
        # The rebalanced line must beat 50/50 buy & hold here, but it must NOT
        # exceed what a perfect (fee-free) rebalance could have produced.
        free = plain_loop_line1(WEEKLY_ROWS, fee=0.0)
        self.assertGreater(self.line1["final_nav"], self.line2["final_nav"])
        self.assertLess(self.line1["final_nav"], free["final_nav"],
                        "paying fees cannot beat the fee-free version")
        reference = METRICS["single_asset_reference"]
        self.assertAlmostEqual(
            self.line2["final_nav"],
            (reference["all_btc_final_usd"] + reference["all_eth_final_usd"]) / 2.0,
            places=4)

    def test_float64_engine_matches_50_digit_decimal_arithmetic(self) -> None:
        exact = decimal_loop_line1(WEEKLY_ROWS)
        self.assertEqual(exact["trades"], CLAIMED_REBALANCES,
                         "trade count is sensitive to float rounding at the band")
        error = abs(decimal.Decimal(repr(self.line1["final_nav"]))
                    - exact["final_nav"])
        self.assertLess(float(error), 1e-6,
                        f"float64 terminal NAV drifts from exact arithmetic by "
                        f"{error} (exact = {exact['final_nav']})")

    def test_fee_ledger_reconciles_with_traded_notional(self) -> None:
        frame = make_frame(WEEKLY_ROWS)
        line1, _ = run_backtest(frame, QA_CONFIG)
        rebalance_fees = sum(r.fee_paid for r in line1.records[1:])
        rebalance_notional = sum(r.traded_notional for r in line1.records[1:])
        self.assertAlmostEqual(rebalance_fees, rebalance_notional * 0.001,
                               places=10)
        self.assertAlmostEqual(line1.total_fee, 0.2 + rebalance_fees, places=10)
        self.assertEqual(sum(1 for r in line1.records[1:] if r.traded),
                         CLAIMED_REBALANCES)
        self.assertEqual(sum(1 for r in line1.records[1:] if r.fee_paid > 0.0),
                         CLAIMED_REBALANCES)

    def test_rebalances_are_spread_over_the_decade(self) -> None:
        # Guards against a degenerate path where all trades cluster in one
        # regime, which would make the headline number an artefact.
        frame = make_frame(WEEKLY_ROWS)
        line1, _ = run_backtest(frame, QA_CONFIG)
        by_year: dict[int, int] = {}
        for record in line1.records[1:]:
            if record.traded:
                by_year[record.date.year] = by_year.get(record.date.year, 0) + 1
        self.assertGreaterEqual(len(by_year), 10, f"trades only in {by_year}")
        self.assertLess(max(by_year.values()) / CLAIMED_REBALANCES, 0.30,
                        f"trades cluster in a single year: {by_year}")

    def test_annual_returns_chain_to_the_terminal_nav(self) -> None:
        for key in ("line1_rolling_rebalance", "line2_buy_and_hold"):
            block = METRICS[key]
            compounded = 1.0
            for value in block["annual_returns_pct"].values():
                compounded *= (1.0 + value / 100.0)
            implied = block["initial_nav_usd"] * compounded
            # annual_returns_pct is rounded to 2dp, so allow 0.5% slack.
            self.assertLess(abs(implied / block["final_nav_usd"] - 1.0), 0.005,
                            f"{key}: yearly returns chain to {implied:.2f} but "
                            f"final NAV is {block['final_nav_usd']:.2f}")

    def test_premium_matches_volatility_harvesting_theory(self) -> None:
        """The 1.78x edge must be explainable by textbook theory, not by code.

        For a continuously rebalanced equal-weight pair the log-growth advantage
        over buy & hold is ``Var(r_A - r_B) / 8`` per year.  If the engine were
        silently manufacturing return, the realised edge would overshoot this
        bound badly.
        """
        import numpy as np

        log_btc = np.diff(np.log([row[1] for row in WEEKLY_ROWS]))
        log_eth = np.diff(np.log([row[2] for row in WEEKLY_ROWS]))
        annual_var_spread = float(np.var(log_btc - log_eth, ddof=1)) * 52.0
        theoretical = annual_var_spread / 8.0

        years = METRICS["line1_rolling_rebalance"]["years"]
        observed = math.log(self.line1["final_nav"]
                            / self.line2["final_nav"]) / years
        self.assertGreater(observed, 0.0)
        # Weekly (not continuous) rebalancing inside a 1pp band, plus fees,
        # should capture most but not more than the theoretical premium.
        self.assertLess(observed / theoretical, 1.15,
                        f"realised edge {observed:.4f}/yr exceeds the "
                        f"theoretical ceiling {theoretical:.4f}/yr -> the "
                        f"engine may be manufacturing return")
        self.assertGreater(observed / theoretical, 0.60,
                           f"realised edge {observed:.4f}/yr is far below "
                           f"theory {theoretical:.4f}/yr")

    def test_no_future_data_beyond_today(self) -> None:
        last = datetime.strptime(WEEKLY_ROWS[-1][0], "%Y-%m-%d").date()
        self.assertLessEqual(last, date.today(),
                             "the panel contains dates in the future")

    def test_no_look_ahead_final_bar_only_affects_the_last_point(self) -> None:
        # Truncating the panel must leave every earlier NAV bit-identical:
        # proof that no future information leaks backwards.
        truncated = plain_loop_line1(WEEKLY_ROWS[:-50])
        for index, value in enumerate(truncated["navs"]):
            self.assertEqual(value, self.line1["navs"][index],
                             f"NAV at index {index} changed when the tail was cut")


if __name__ == "__main__":
    unittest.main(verbosity=2)
