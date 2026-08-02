"""Performance statistics computed from a weekly NAV series."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from backtest import LineResult
from config import BacktestConfig, price_column

DAYS_PER_YEAR: float = 365.25


@dataclass
class DrawdownInfo:
    """Maximum drawdown descriptor.

    Attributes:
        max_drawdown_pct: Worst peak-to-trough decline, expressed as a positive
            percentage (``57.3`` means -57.3%).
        peak_date: Date of the peak that precedes the worst trough.
        trough_date: Date of the worst trough.
        recovery_date: First date the NAV regained the peak, or empty when the
            drawdown has not been recovered yet.
        peak_nav: NAV at the peak.
        trough_nav: NAV at the trough.
    """

    max_drawdown_pct: float = 0.0
    peak_date: str = ""
    trough_date: str = ""
    recovery_date: str = ""
    peak_nav: float = 0.0
    trough_nav: float = 0.0


@dataclass
class LineMetrics:
    """Headline statistics for one strategy line.

    Attributes:
        name: Line identifier.
        label: Human-readable Chinese label.
        start_date: First weekly bar.
        end_date: Last weekly bar.
        weeks: Number of weekly bars.
        years: Elapsed calendar years between the first and last bar.
        gross_invested_usd: Gross USD committed at t0 (before the entry fee).
        initial_nav_usd: NAV right after the entry fee, i.e. deployed capital.
        final_nav_usd: NAV at the last weekly bar.
        total_return_pct: ``final / gross_invested - 1`` in percent.
        cagr_pct: Compound annual growth rate in percent, on the gross basis.
        max_drawdown_pct: Worst weekly peak-to-trough decline, positive percent.
        drawdown: Detailed drawdown descriptor.
        rebalance_count: Number of post-t0 rebalances.
        total_fee_usd: All fees paid, entry fee included.
        fee_pct_of_principal: Total fees as a percentage of the gross principal.
        annual_returns_pct: Calendar-year returns in percent.
        best_year: ``(year, return_pct)`` of the strongest calendar year.
        worst_year: ``(year, return_pct)`` of the weakest calendar year.
        volatility_annual_pct: Annualised standard deviation of weekly returns.
        final_weights_pct: Each coin's share of the final NAV, in percent.
    """

    name: str
    label: str
    start_date: str
    end_date: str
    weeks: int
    years: float
    gross_invested_usd: float
    initial_nav_usd: float
    final_nav_usd: float
    total_return_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    drawdown: DrawdownInfo
    rebalance_count: int
    total_fee_usd: float
    fee_pct_of_principal: float
    annual_returns_pct: dict[str, float] = field(default_factory=dict)
    best_year: tuple[str, float] = ("", 0.0)
    worst_year: tuple[str, float] = ("", 0.0)
    volatility_annual_pct: float = 0.0
    final_weights_pct: dict[str, float] = field(default_factory=dict)

    @property
    def final_weight_eth_pct(self) -> float:
        """Returns the terminal ETH weight in percent (legacy accessor)."""
        return self.final_weights_pct.get("ETH", 0.0)

    def to_dict(self) -> dict:
        """Returns a JSON-serialisable dictionary of every field."""
        payload = asdict(self)
        payload["best_year"] = list(self.best_year)
        payload["worst_year"] = list(self.worst_year)
        return payload


def compute_drawdown_series(nav: pd.Series) -> pd.Series:
    """Returns the running drawdown of ``nav`` as negative percentages."""
    running_peak = nav.cummax()
    return (nav / running_peak - 1.0) * 100.0


def compute_max_drawdown(nav: pd.Series) -> DrawdownInfo:
    """Computes the worst peak-to-trough decline of a NAV series.

    Args:
        nav: Weekly NAV series indexed by date.

    Returns:
        A populated :class:`DrawdownInfo`.
    """
    if nav.empty:
        return DrawdownInfo()
    running_peak = nav.cummax()
    drawdown = nav / running_peak - 1.0
    trough_date = drawdown.idxmin()
    max_dd = float(drawdown.loc[trough_date])
    peak_nav = float(running_peak.loc[trough_date])
    before_trough = nav.loc[:trough_date]
    peak_candidates = before_trough[before_trough >= peak_nav - 1e-12]
    peak_date = peak_candidates.index[-1] if len(peak_candidates) else nav.index[0]
    after_trough = nav.loc[trough_date:]
    recovered = after_trough[after_trough >= peak_nav]
    recovery_date = recovered.index[0].strftime("%Y-%m-%d") if len(recovered) else ""
    return DrawdownInfo(
        max_drawdown_pct=abs(max_dd) * 100.0,
        peak_date=pd.Timestamp(peak_date).strftime("%Y-%m-%d"),
        trough_date=pd.Timestamp(trough_date).strftime("%Y-%m-%d"),
        recovery_date=recovery_date,
        peak_nav=peak_nav,
        trough_nav=float(nav.loc[trough_date]),
    )


def compute_annual_returns(nav: pd.Series) -> dict[str, float]:
    """Computes calendar-year returns in percent from a weekly NAV series.

    The first (partial) year is measured from the t0 NAV; every later year is
    measured from the last NAV of the preceding year.  The final year is marked
    with a ``*`` suffix when it is still incomplete.

    Args:
        nav: Weekly NAV series indexed by date.

    Returns:
        Mapping of year label to percentage return.
    """
    if nav.empty:
        return {}
    returns: dict[str, float] = {}
    year_end = nav.groupby(nav.index.year).last()
    years = list(year_end.index)
    last_date = nav.index[-1]
    for position, year in enumerate(years):
        if position == 0:
            base = float(nav.iloc[0])
        else:
            base = float(year_end.iloc[position - 1])
        if base <= 0.0:
            continue
        value = float(year_end.iloc[position])
        label = str(int(year))
        is_partial_head = (position == 0 and nav.index[0].dayofyear > 7)
        is_partial_tail = (position == len(years) - 1
                           and not (last_date.month == 12 and last_date.day >= 25))
        if is_partial_head or is_partial_tail:
            label = f"{label}*"
        returns[label] = (value / base - 1.0) * 100.0
    return returns


def compute_line_metrics(line: LineResult, config: BacktestConfig,
                         label: str) -> LineMetrics:
    """Builds the full metric bundle for one strategy line.

    Args:
        line: Engine output for the line.
        config: Backtest parameters (for the gross principal and fee rate).
        label: Human-readable Chinese label used in reports.

    Returns:
        A populated :class:`LineMetrics`.

    Raises:
        ValueError: If the line produced no records.
    """
    nav = line.nav_series()
    if nav.empty:
        raise ValueError(f"Line {line.name} produced no NAV records")

    start = nav.index[0]
    end = nav.index[-1]
    years = max((end - start).days / DAYS_PER_YEAR, 1e-9)
    gross = config.initial_capital_usd
    final_nav = float(nav.iloc[-1])
    total_return = (final_nav / gross - 1.0) * 100.0
    cagr = ((final_nav / gross) ** (1.0 / years) - 1.0) * 100.0

    drawdown = compute_max_drawdown(nav)
    annual = compute_annual_returns(nav)
    if annual:
        best_key = max(annual, key=lambda k: annual[k])
        worst_key = min(annual, key=lambda k: annual[k])
        best = (best_key, annual[best_key])
        worst = (worst_key, annual[worst_key])
    else:
        best = ("", 0.0)
        worst = ("", 0.0)

    weekly_returns = nav.pct_change().dropna()
    volatility = (float(np.std(weekly_returns.to_numpy(), ddof=1))
                  * np.sqrt(52.0) * 100.0) if len(weekly_returns) > 1 else 0.0

    last_record = line.records[-1]
    if last_record.nav > 0.0:
        final_weights = {coin: last_record.values.get(coin, 0.0)
                         / last_record.nav * 100.0
                         for coin in config.coins}
    else:
        final_weights = {coin: 0.0 for coin in config.coins}

    return LineMetrics(
        name=line.name,
        label=label,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        weeks=int(len(nav)),
        years=round(years, 4),
        gross_invested_usd=gross,
        initial_nav_usd=float(nav.iloc[0]),
        final_nav_usd=final_nav,
        total_return_pct=total_return,
        cagr_pct=cagr,
        max_drawdown_pct=drawdown.max_drawdown_pct,
        drawdown=drawdown,
        rebalance_count=line.rebalance_count,
        total_fee_usd=line.total_fee,
        fee_pct_of_principal=line.total_fee / gross * 100.0,
        annual_returns_pct={k: round(v, 2) for k, v in annual.items()},
        best_year=(best[0], round(best[1], 2)),
        worst_year=(worst[0], round(worst[1], 2)),
        volatility_annual_pct=volatility,
        final_weights_pct=final_weights,
    )


def compute_buy_hold_reference(prices: pd.DataFrame,
                               config: BacktestConfig) -> dict[str, float]:
    """Computes 100%-single-coin references for context.

    For every coin in the universe the whole gross principal is deployed into
    that coin alone at t0 (paying the same 0.1% entry fee) and held to the end.

    Args:
        prices: Weekly close panel indexed by date.
        config: Backtest parameters.

    Returns:
        Mapping with ``all_<coin>_final_usd`` plus ``<coin>_price_start`` /
        ``<coin>_price_end`` for every coin (keys use the lower-case ticker).
    """
    net = config.initial_capital_usd * (1.0 - config.fee_rate)
    first = prices.iloc[0]
    last = prices.iloc[-1]
    reference: dict[str, float] = {}
    for coin in config.coins:
        column = price_column(coin)
        start_price = float(first[column])
        end_price = float(last[column])
        key = coin.lower()
        reference[f"all_{key}_final_usd"] = net / start_price * end_price
        reference[f"{key}_price_start"] = start_price
        reference[f"{key}_price_end"] = end_price
    return reference
