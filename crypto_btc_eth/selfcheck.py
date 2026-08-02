"""Correctness self-checks for the N-asset rebalancing backtest.

Four invariants are verified, mirroring the acceptance criteria:

(a) The buy-and-hold line's terminal NAV equals ``sum_i q_i * p_i_end`` exactly
    -- no fee drift beyond the single entry fee, and no quantity ever moves.
(b) Immediately after every rebalance *every* leg sits within the rebalance
    band of its target weight (fees push bought legs marginally below target).
(c) Fees are charged only in weeks that actually trade; in every other week the
    coin quantities are unchanged and the NAV moves purely with prices.
(d) The weekly price panel itself is clean (no NaN / duplicates / gaps).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backtest import LineResult
from config import BacktestConfig, price_column

# Tolerances: (a) is an exact algebraic identity, so only float noise is allowed.
ABS_TOL_NAV: float = 1e-8
REL_TOL_NAV: float = 1e-10
# Quantities are only allowed to move when a trade is recorded.
QTY_TOL: float = 1e-18


@dataclass
class CheckResult:
    """Outcome of a single invariant check.

    Attributes:
        code: Short identifier, e.g. ``"a"``.
        title: Human-readable description of what was verified.
        passed: Whether the invariant held.
        detail: Evidence string printed in the report.
        violations: Up to a handful of concrete counter-examples.
    """

    code: str
    title: str
    passed: bool
    detail: str = ""
    violations: list[str] = field(default_factory=list)


@dataclass
class SelfCheckReport:
    """Aggregate of every invariant check.

    Attributes:
        checks: Individual check outcomes in declaration order.
    """

    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True only when every individual check passed."""
        return all(check.passed for check in self.checks)

    @property
    def verdict(self) -> str:
        """Returns ``"YES"`` or ``"NO"`` for the IS_PASS line."""
        return "YES" if self.passed else "NO"

    def to_dict(self) -> dict:
        """Returns a JSON-serialisable summary of the report."""
        return {
            "is_pass": self.verdict,
            "checks": [
                {
                    "code": check.code,
                    "title": check.title,
                    "passed": check.passed,
                    "detail": check.detail,
                    "violations": check.violations,
                }
                for check in self.checks
            ],
        }


def check_buy_hold_identity(line2: LineResult, prices: pd.DataFrame,
                            config: BacktestConfig) -> CheckResult:
    """(a) Verifies the buy-and-hold terminal NAV has no fee drift.

    Args:
        line2: Buy-and-hold line result.
        prices: Weekly close panel used by the run.
        config: Backtest parameters (supplies the coin universe).

    Returns:
        The populated :class:`CheckResult`.
    """
    coins = config.coins
    last_prices = prices.iloc[-1]
    expected = sum(line2.initial_quantities[coin]
                   * float(last_prices[price_column(coin)]) for coin in coins)
    actual = line2.final_nav()
    diff = abs(actual - expected)
    tolerance = ABS_TOL_NAV + REL_TOL_NAV * abs(expected)
    violations: list[str] = []

    quantity_drift = [
        f"{record.date:%Y-%m-%d}: {coin} qty changed"
        for record in line2.records
        for coin in coins
        if abs(record.quantities.get(coin, 0.0)
               - line2.initial_quantities[coin]) > QTY_TOL
    ]
    if quantity_drift:
        violations.extend(quantity_drift[:5])

    extra_fees = [
        f"{record.date:%Y-%m-%d}: fee {record.fee_paid:.6f}"
        for record in line2.records[1:] if record.fee_paid != 0.0
    ]
    if extra_fees:
        violations.extend(extra_fees[:5])

    passed = diff <= tolerance and not violations
    terms = " + ".join(f"q_{coin.lower()}*p_{coin.lower()}" for coin in coins)
    detail = (f"final NAV {actual:.10f} USD vs {terms} "
              f"{expected:.10f} USD | abs diff {diff:.3e} (tol {tolerance:.3e}) | "
              f"fees after t0 = {sum(r.fee_paid for r in line2.records[1:]):.10f} USD")
    return CheckResult(
        code="a",
        title=f"Line2 终值 == Σ q_i×末价_i（{len(coins)} 币, 除建仓费外无费用漂移）",
        passed=passed,
        detail=detail,
        violations=violations,
    )


def check_post_rebalance_weights(line1: LineResult,
                                 config: BacktestConfig) -> CheckResult:
    """(b) Verifies post-rebalance weights land inside the band for every coin.

    After a rebalance the sold legs sit exactly on their target *value* while
    the portfolio total has shrunk by the fee, and the bought legs are short by
    ``deficit_i * fee_rate``.  Both effects are bounded by

        max_i target_i * fee_rate / (1 - fee_rate)

    which for the 2-coin equal-weight case is the familiar ``fee_rate / 2``.

    Args:
        line1: Rebalanced line result.
        config: Backtest parameters.

    Returns:
        The populated :class:`CheckResult`.
    """
    coins = config.coins
    targets = config.target_weights
    band = config.rebalance_band
    violations: list[str] = []
    worst_deviation = 0.0
    worst_coin = ""
    checked = 0
    first_date = line1.records[0].date if line1.records else None

    for record in line1.records:
        if not record.traded or record.date == first_date:
            continue
        checked += 1
        for coin in coins:
            deviation = abs(record.weights_post.get(coin, 0.0) - targets[coin])
            if deviation > worst_deviation:
                worst_deviation = deviation
                worst_coin = coin
            if deviation >= band:
                violations.append(
                    f"{record.date:%Y-%m-%d}: post w_{coin.lower()}="
                    f"{record.weights_post.get(coin, 0.0):.6f} dev={deviation:.6f}"
                )

    # A rebalance may only shave off at most this much relative weight.
    max_target = max(targets[coin] for coin in coins)
    theoretical_cap = max_target * config.fee_rate / (1.0 - config.fee_rate)
    passed = not violations and worst_deviation <= max(theoretical_cap, 1e-9)
    if worst_deviation > theoretical_cap and not violations:
        violations.append(
            f"worst deviation {worst_deviation:.3e} exceeds theoretical "
            f"fee-induced cap {theoretical_cap:.3e}"
        )
        passed = False
    detail = (f"{checked} rebalances x {len(coins)} legs inspected | worst "
              f"|w_i-target_i| after trade = {worst_deviation:.3e}"
              f"{f' ({worst_coin})' if worst_coin else ''} | band = {band:.4f} | "
              f"fee-induced cap = {theoretical_cap:.3e}")
    return CheckResult(
        code="b",
        title=f"再平衡后各币市值≈目标权重（{len(coins)} 币, 偏差远小于再平衡阈值）",
        passed=passed,
        detail=detail,
        violations=violations[:5],
    )


def check_fee_and_price_only_weeks(line1: LineResult,
                                   config: BacktestConfig) -> CheckResult:
    """(c) Verifies non-trading weeks charge no fee and only reprice holdings.

    Args:
        line1: Rebalanced line result.
        config: Backtest parameters (supplies the coin universe).

    Returns:
        The populated :class:`CheckResult`.
    """
    coins = config.coins
    violations: list[str] = []
    non_trading_weeks = 0
    max_nav_error = 0.0

    for index, record in enumerate(line1.records):
        if record.traded:
            if record.fee_paid <= 0.0:
                violations.append(
                    f"{record.date:%Y-%m-%d}: trade recorded but fee={record.fee_paid}"
                )
            continue
        non_trading_weeks += 1
        if record.fee_paid != 0.0:
            violations.append(
                f"{record.date:%Y-%m-%d}: no trade but fee={record.fee_paid:.10f}"
            )
        if index > 0:
            previous = line1.records[index - 1]
            moved = [coin for coin in coins
                     if abs(record.quantities.get(coin, 0.0)
                            - previous.quantities.get(coin, 0.0)) > QTY_TOL]
            if moved:
                violations.append(
                    f"{record.date:%Y-%m-%d}: quantities changed without a trade "
                    f"({', '.join(moved)})"
                )
            expected_nav = sum(previous.quantities.get(coin, 0.0)
                               * record.prices.get(coin, 0.0) for coin in coins)
            error = abs(record.nav - expected_nav)
            max_nav_error = max(max_nav_error, error)
            if error > ABS_TOL_NAV + REL_TOL_NAV * abs(expected_nav):
                violations.append(
                    f"{record.date:%Y-%m-%d}: NAV {record.nav:.10f} != "
                    f"price-only {expected_nav:.10f}"
                )

    traded_weeks = sum(1 for record in line1.records if record.traded)
    fee_weeks = sum(1 for record in line1.records if record.fee_paid > 0.0)
    if traded_weeks != fee_weeks:
        violations.append(
            f"traded weeks {traded_weeks} != fee-charging weeks {fee_weeks}"
        )

    passed = not violations
    detail = (f"{non_trading_weeks} non-trading weeks: zero fees and NAV driven by "
              f"prices only (max NAV error {max_nav_error:.3e}) | trading weeks = "
              f"{traded_weeks} = fee weeks {fee_weeks}")
    return CheckResult(
        code="c",
        title="手续费只在实际交易周计提；无交易周 NAV 仅随价格变动",
        passed=passed,
        detail=detail,
        violations=violations[:5],
    )


def check_data_integrity(prices: pd.DataFrame) -> CheckResult:
    """(d) Sanity-checks the weekly price panel itself (extra guard rail)."""
    violations: list[str] = []
    if prices.isna().any().any():
        violations.append("weekly panel contains NaN values")
    if (prices <= 0.0).any().any():
        violations.append("weekly panel contains non-positive prices")
    if not prices.index.is_monotonic_increasing:
        violations.append("weekly panel index is not sorted ascending")
    if prices.index.duplicated().any():
        violations.append("weekly panel index contains duplicate dates")
    gaps = prices.index.to_series().diff().dt.days.dropna()
    oversized = gaps[gaps > 10]
    if len(oversized) > 0:
        violations.append(
            f"{len(oversized)} weekly gaps exceed 10 days "
            f"(first at {oversized.index[0]:%Y-%m-%d}, {int(oversized.iloc[0])}d)"
        )
    passed = not violations
    detail = (f"{len(prices)} weekly bars {prices.index[0]:%Y-%m-%d}~"
              f"{prices.index[-1]:%Y-%m-%d} x {len(prices.columns)} 列, median "
              f"spacing {gaps.median() if len(gaps) else 0:.0f} days, no NaN/"
              f"duplicate/non-positive values")
    return CheckResult(
        code="d",
        title="周线数据完整性（无缺失/重复/非正价格，间隔均为一周）",
        passed=passed,
        detail=detail,
        violations=violations[:5],
    )


def run_self_checks(line1: LineResult, line2: LineResult, prices: pd.DataFrame,
                    config: BacktestConfig) -> SelfCheckReport:
    """Runs every invariant check and aggregates the outcome.

    Args:
        line1: Rebalanced line result.
        line2: Buy-and-hold line result.
        prices: Weekly close panel used by both lines.
        config: Backtest parameters.

    Returns:
        A :class:`SelfCheckReport` whose ``verdict`` drives the IS_PASS line.
    """
    return SelfCheckReport(checks=[
        check_buy_hold_identity(line2, prices, config),
        check_post_rebalance_weights(line1, config),
        check_fee_and_price_only_weeks(line1, config),
        check_data_integrity(prices),
    ])
