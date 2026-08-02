"""Two-line N-asset equal-weight backtest engine.

Line 1 -- "rolling cross-rebalance"
    Start at the target weights, and every week that *any* leg drifts more than
    ``rebalance_band`` away from its target, trade the whole portfolio back to
    the exact target weights.  Every rebalance pays ``fee_rate`` on the traded
    (one-sided) notional.

Line 2 -- "buy & hold baseline"
    Buy the target weights once at t0 and never touch the position again.

Both lines are charged one entry fee at t0, deducted from the gross principal,
so they start from an identical net asset value.

The engine is generic in ``n``; the original BTC/ETH pair is the ``n == 2``
special case and reproduces the legacy numbers bit-for-bit.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from config import BacktestConfig, price_column


@dataclass
class WeekRecord:
    """One weekly snapshot of a single strategy line.

    Attributes:
        date: Observation date of the weekly close.
        prices: Close price in USD per coin.
        quantities: Units held per coin after any action taken this week.
        values: USD value per coin after any action taken this week.
        nav: Total USD net asset value after any action.
        weights_pre: Portfolio weight per coin *before* acting this week.
        weights_post: Portfolio weight per coin *after* acting this week.
        traded: Whether a trade happened this week.
        traded_notional: One-sided USD notional actually moved this week (the
            sum of the over-weight legs' excess), i.e. the fee base.
        fee_paid: USD fee charged this week.
    """

    date: pd.Timestamp
    prices: dict[str, float] = field(default_factory=dict)
    quantities: dict[str, float] = field(default_factory=dict)
    values: dict[str, float] = field(default_factory=dict)
    nav: float = 0.0
    weights_pre: dict[str, float] = field(default_factory=dict)
    weights_post: dict[str, float] = field(default_factory=dict)
    traded: bool = False
    traded_notional: float = 0.0
    fee_paid: float = 0.0

    # ------------------------------------------------------------------ #
    # Legacy 2-coin accessors (read-only).  They keep the original BTC/ETH
    # tooling and the independent QA suite working against the new layout.
    # ------------------------------------------------------------------ #
    @property
    def btc_price(self) -> float:
        """Returns the BTC close of this week (0.0 when BTC is not held)."""
        return self.prices.get("BTC", 0.0)

    @property
    def eth_price(self) -> float:
        """Returns the ETH close of this week (0.0 when ETH is not held)."""
        return self.prices.get("ETH", 0.0)

    @property
    def qty_btc(self) -> float:
        """Returns the BTC units held after this week's action."""
        return self.quantities.get("BTC", 0.0)

    @property
    def qty_eth(self) -> float:
        """Returns the ETH units held after this week's action."""
        return self.quantities.get("ETH", 0.0)

    @property
    def btc_value(self) -> float:
        """Returns the USD value of the BTC leg after this week's action."""
        return self.values.get("BTC", 0.0)

    @property
    def eth_value(self) -> float:
        """Returns the USD value of the ETH leg after this week's action."""
        return self.values.get("ETH", 0.0)

    @property
    def weight_eth_pre(self) -> float:
        """Returns the ETH weight observed before acting this week."""
        return self.weights_pre.get("ETH", 0.0)

    @property
    def weight_eth_post(self) -> float:
        """Returns the ETH weight after acting this week."""
        return self.weights_post.get("ETH", 0.0)


@dataclass
class LineResult:
    """Full output of one strategy line.

    Attributes:
        name: Human-readable line name.
        coins: Ordered coin universe traded by this line.
        records: Chronological weekly snapshots.
        initial_quantities: Units bought per coin at t0.
        entry_fee: USD fee paid at t0.
        total_fee: USD fees paid over the whole run (entry fee included).
        rebalance_count: Number of post-t0 rebalances executed.
    """

    name: str
    coins: tuple[str, ...] = ()
    records: list[WeekRecord] = field(default_factory=list)
    initial_quantities: dict[str, float] = field(default_factory=dict)
    entry_fee: float = 0.0
    total_fee: float = 0.0
    rebalance_count: int = 0

    def nav_series(self) -> pd.Series:
        """Returns the weekly NAV as a pandas Series indexed by date."""
        return pd.Series(
            [record.nav for record in self.records],
            index=pd.DatetimeIndex([record.date for record in self.records],
                                   name="date"),
            name=self.name,
            dtype=float,
        )

    def final_nav(self) -> float:
        """Returns the last weekly NAV, or 0.0 when the run is empty."""
        return self.records[-1].nav if self.records else 0.0

    # ------------------------------------------------------------------ #
    # Legacy 2-coin accessors (read-only).
    # ------------------------------------------------------------------ #
    @property
    def initial_qty_btc(self) -> float:
        """Returns the BTC units bought at t0."""
        return self.initial_quantities.get("BTC", 0.0)

    @property
    def initial_qty_eth(self) -> float:
        """Returns the ETH units bought at t0."""
        return self.initial_quantities.get("ETH", 0.0)


def _row_prices(row: pd.Series, coins: tuple[str, ...]) -> dict[str, float]:
    """Extracts the per-coin close prices from one weekly panel row.

    Args:
        row: A single row of the weekly close panel.
        coins: Ordered coin universe.

    Returns:
        Mapping of coin to USD close price.
    """
    return {coin: float(row[price_column(coin)]) for coin in coins}


def _weights(values: dict[str, float], nav: float) -> dict[str, float]:
    """Returns the portfolio weight of every leg, or all-zero when NAV is 0."""
    if nav <= 0.0:
        return {coin: 0.0 for coin in values}
    return {coin: value / nav for coin, value in values.items()}


def _open_position(prices: pd.DataFrame,
                   config: BacktestConfig) -> tuple[dict[str, float], float, float]:
    """Opens the initial target-weight position at the first weekly bar.

    The entry fee is taken out of the gross principal first, and the remaining
    net capital is split across the coins by ``config.target_weights``.

    Args:
        prices: Weekly close panel carrying one ``<coin>_close`` column per coin.
        config: Backtest parameters.

    Returns:
        ``(quantities, entry_fee, net_capital)``.
    """
    first = prices.iloc[0]
    gross = config.initial_capital_usd
    entry_fee = gross * config.fee_rate
    net_capital = gross - entry_fee
    quantities: dict[str, float] = {}
    for coin in config.coins:
        budget = net_capital * config.target_weights[coin]
        quantities[coin] = budget / float(first[price_column(coin)])
    return quantities, entry_fee, net_capital


def run_buy_and_hold(prices: pd.DataFrame, config: BacktestConfig) -> LineResult:
    """Runs Line 2: buy the target weights once at t0 and hold forever.

    Args:
        prices: Weekly close panel indexed by date.
        config: Backtest parameters.

    Returns:
        A :class:`LineResult` with one record per weekly bar.
    """
    quantities, entry_fee, _net = _open_position(prices, config)
    coins = config.coins
    result = LineResult(
        name="line2_buy_and_hold",
        coins=coins,
        initial_quantities=dict(quantities),
        entry_fee=entry_fee,
        total_fee=entry_fee,
        rebalance_count=0,
    )
    first_date = prices.index[0]
    for date, row in prices.iterrows():
        prices_now = _row_prices(row, coins)
        values = {coin: quantities[coin] * prices_now[coin] for coin in coins}
        nav = sum(values.values())
        weights = _weights(values, nav)
        is_first = (date == first_date)
        result.records.append(
            WeekRecord(
                date=date,
                prices=prices_now,
                quantities=dict(quantities),
                values=values,
                nav=nav,
                weights_pre=dict(weights),
                weights_post=dict(weights),
                traded=is_first,
                traded_notional=nav if is_first else 0.0,
                fee_paid=entry_fee if is_first else 0.0,
            )
        )
    return result


def run_rolling_rebalance(prices: pd.DataFrame,
                          config: BacktestConfig) -> LineResult:
    """Runs Line 1: weekly banded rebalancing back to the exact target weights.

    Trigger
    -------
    A rebalance fires in week *t* when
    ``max_i |w_i(t) - target_i| >= rebalance_band``, i.e. as soon as *any*
    single leg leaves its tolerance band.

    Mechanics of one rebalance, with pre-trade leg values ``v_i``, portfolio
    total ``T`` and targets ``V_i* = target_i * T``:

    * over-weight legs (``v_i > V_i*``) sell their excess ``e_i = v_i - V_i*``
      and land exactly on ``V_i*``;
    * the pooled proceeds ``S = sum(e_i)`` pay ``S * fee_rate`` in fees and the
      remainder is allocated to the under-weight legs pro-rata to their deficit
      ``d_j = V_j* - v_j`` (note ``sum(d_j) == S`` by construction), so leg *j*
      lands on ``V_j* - d_j * fee_rate``;
    * the portfolio total becomes ``T - S * fee_rate``.

    The residual asymmetry (bought legs sit a hair below target, sold legs a
    hair above, because the total shrank by the fee) is exactly what a real
    venue produces, and is bounded by ``max_i target_i * fee_rate / (1 - fee)``
    -- orders of magnitude below ``rebalance_band``.

    For ``n == 2`` the pro-rata allocation degenerates to ``S * d/d == S``, so
    this reproduces the legacy BTC/ETH arithmetic exactly.

    Args:
        prices: Weekly close panel indexed by date.
        config: Backtest parameters.

    Returns:
        A :class:`LineResult` with one record per weekly bar.
    """
    quantities, entry_fee, net_capital = _open_position(prices, config)
    coins = config.coins
    targets = config.target_weights
    band = config.rebalance_band
    fee_rate = config.fee_rate
    result = LineResult(
        name="line1_rolling_rebalance",
        coins=coins,
        initial_quantities=dict(quantities),
        entry_fee=entry_fee,
        total_fee=entry_fee,
        rebalance_count=0,
    )
    first_date = prices.index[0]

    for date, row in prices.iterrows():
        prices_now = _row_prices(row, coins)
        values = {coin: quantities[coin] * prices_now[coin] for coin in coins}
        nav = sum(values.values())
        weights_pre = _weights(values, nav)

        traded = False
        traded_notional = 0.0
        fee_paid = 0.0

        if date == first_date:
            # t0: the position was just opened exactly on the target weights.
            traded = True
            traded_notional = net_capital
            fee_paid = entry_fee
        else:
            max_deviation = max(abs(weights_pre[coin] - targets[coin])
                                for coin in coins)
            if max_deviation >= band and nav > 0.0:
                target_values = {coin: nav * targets[coin] for coin in coins}
                excess = {coin: values[coin] - target_values[coin]
                          for coin in coins if values[coin] > target_values[coin]}
                deficit = {coin: target_values[coin] - values[coin]
                           for coin in coins if values[coin] < target_values[coin]}
                sell_total = sum(excess.values())
                buy_total = sum(deficit.values())
                if sell_total > 0.0 and buy_total > 0.0:
                    for coin, amount in excess.items():
                        quantities[coin] -= amount / prices_now[coin]
                    for coin, amount in deficit.items():
                        # Pro-rata split of the pooled proceeds keeps cash
                        # conservation exact even with float rounding.
                        proceeds = sell_total * (amount / buy_total)
                        quantities[coin] += (proceeds * (1.0 - fee_rate)
                                             / prices_now[coin])
                    fee_paid = sell_total * fee_rate
                    traded_notional = sell_total
                    traded = True
                    result.rebalance_count += 1
                    result.total_fee += fee_paid
                    values = {coin: quantities[coin] * prices_now[coin]
                              for coin in coins}
                    nav = sum(values.values())

        weights_post = _weights(values, nav)
        result.records.append(
            WeekRecord(
                date=date,
                prices=prices_now,
                quantities=dict(quantities),
                values=values,
                nav=nav,
                weights_pre=weights_pre,
                weights_post=weights_post,
                traded=traded,
                traded_notional=traded_notional,
                fee_paid=fee_paid,
            )
        )
    return result


def run_backtest(prices: pd.DataFrame,
                 config: BacktestConfig) -> tuple[LineResult, LineResult]:
    """Runs both strategy lines over the same weekly price panel.

    Args:
        prices: Weekly close panel carrying one ``<coin>_close`` column per coin.
        config: Backtest parameters.

    Returns:
        ``(line1, line2)`` -- the rebalanced line and the buy-and-hold baseline.

    Raises:
        ValueError: If the panel is missing required columns or is too short.
    """
    required = set(config.price_columns)
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"Weekly price panel is missing columns: {sorted(missing)}")
    if len(prices) < 2:
        raise ValueError("Weekly price panel needs at least two bars")
    line1 = run_rolling_rebalance(prices, config)
    line2 = run_buy_and_hold(prices, config)
    return line1, line2
