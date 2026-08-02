"""Global configuration for the N-asset equal-weight rebalancing backtest.

All monetary amounts are denominated in USD.  Nothing in this module performs
I/O; it only declares constants and immutable configuration objects so that the
rest of the package can stay side-effect free at import time.

The engine is generic in the number of coins.  ``N == 2`` (the original
BTC/ETH pair) is just the degenerate case of the same equal-weight machinery,
so the legacy pipeline keeps producing bit-identical numbers.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
HERE: str = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR: str = HERE

# --- Legacy 2-coin (BTC/ETH) artefacts -- must stay untouched. -------------- #
PRICE_CSV: str = os.path.join(OUTPUT_DIR, "btc_eth_weekly.csv")
NAV_CSV: str = os.path.join(OUTPUT_DIR, "nav_btc_eth.csv")
METRICS_JSON: str = os.path.join(OUTPUT_DIR, "metrics_btc_eth.json")
CHART_HTML: str = os.path.join(OUTPUT_DIR, "nav_btc_eth.html")
DAILY_CACHE_CSV: str = os.path.join(OUTPUT_DIR, "btc_eth_daily_raw.csv")
DAILY_CACHE_META: str = os.path.join(OUTPUT_DIR, "btc_eth_daily_raw.meta.json")

# --- N-coin artefacts. ------------------------------------------------------ #
MULTI_PRICE_CSV: str = os.path.join(OUTPUT_DIR, "multi_coin_weekly.csv")
MULTI_NAV_CSV: str = os.path.join(OUTPUT_DIR, "nav_multi_coin.csv")
MULTI_METRICS_JSON: str = os.path.join(OUTPUT_DIR, "metrics_multi_coin.json")
MULTI_CHART_HTML: str = os.path.join(OUTPUT_DIR, "nav_multi_coin.html")
MULTI_DAILY_CACHE_CSV: str = os.path.join(OUTPUT_DIR, "multi_coin_daily_raw.csv")
MULTI_DAILY_CACHE_META: str = os.path.join(
    OUTPUT_DIR, "multi_coin_daily_raw.meta.json"
)

# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #
# Sandbox reality (measured 2026-08-02): the local proxy 3067/3066 reaches
# Yahoo Finance / Coinbase / Bitfinex / Kraken / CoinGecko.  api.binance.com
# answers HTTP 451 (geo block) through the same proxy, so Binance is NOT used
# here -- BNB is sourced from Yahoo ``BNB-USD`` instead.
PROXY_CANDIDATES: tuple[str, ...] = (
    "http://127.0.0.1:3067",
    "http://127.0.0.1:3066",
)
PROXY_PROBE_URL: str = (
    "https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD"
    "?range=5d&interval=1d"
)
HTTP_TIMEOUT: int = 45
HTTP_RETRIES: int = 3
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# --------------------------------------------------------------------------- #
# Instruments
# --------------------------------------------------------------------------- #
# Yahoo Finance is the primary venue for every coin: it is the only source in
# this sandbox that carries all five USD pairs with a common history.
YAHOO_SYMBOLS: dict[str, str] = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "XRP": "XRP-USD",
    "BNB": "BNB-USD",
    "TRX": "TRX-USD",
}
# Coinbase Exchange lists only BTC-USD / ETH-USD among our five (XRP was
# delisted for years, BNB and TRX have never been listed there).
COINBASE_SYMBOLS: dict[str, str] = {"BTC": "BTC-USD", "ETH": "ETH-USD"}
# Bitfinex carries BTC/ETH/XRP against USD; BNB and TRX are not quoted in USD.
BITFINEX_SYMBOLS: dict[str, str] = {
    "BTC": "tBTCUSD",
    "ETH": "tETHUSD",
    "XRP": "tXRPUSD",
}
# Kraken weekly OHLC is the emergency last resort for the two majors only.
KRAKEN_SYMBOLS: dict[str, str] = {"BTC": "XBTUSD", "ETH": "ETHUSD"}

# Coinbase Exchange caps each candle request at 300 rows.
COINBASE_CHUNK_DAYS: int = 280

# Weekly bars are anchored on Friday close (bin = Saturday .. Friday).
WEEKLY_RULE: str = "W-FRI"

# --------------------------------------------------------------------------- #
# Coin universes
# --------------------------------------------------------------------------- #
DEFAULT_COINS: tuple[str, ...] = ("BTC", "ETH")
FIVE_COINS: tuple[str, ...] = ("BTC", "ETH", "XRP", "BNB", "TRX")


def price_column(coin: str) -> str:
    """Returns the weekly-panel column name that holds ``coin``'s close.

    Args:
        coin: Upper-case coin ticker such as ``"BTC"``.

    Returns:
        The lower-case column name, e.g. ``"btc_close"``.
    """
    return f"{coin.lower()}_close"


def default_rebalance_band(n_assets: int) -> float:
    """Returns the anti-erosion default rebalance band for ``n_assets`` coins.

    The trigger fires when *any* single leg leaves its tolerance band, so the
    relevant statistic is ``max_i |w_i - target_i|``.  That maximum grows with
    the number of independent drift channels, which means a *flat* band makes a
    5-coin book trade far more often than a 2-coin book.  To hold the expected
    turnover constant the band has to **widen** with ``n``, and the natural
    scale for the maximum of ``n`` mean-zero drifts is ``sqrt(n / 2)``:

    * ``n <= 2`` -> ``0.0100`` (1.00 percentage point, the legacy value)
    * ``n == 5`` -> ``0.0158`` (1.58 percentage points)

    Measured on the real weekly panels this reproduces the baseline almost
    exactly -- BTC/ETH at a 1.00pp band trades in 49.0% of weeks (256 / 522),
    and the 5-coin book at the 1.58pp band trades in 48.0% of weeks (219 / 456).

    Note:
        An earlier revision scaled the band by ``2 / n`` (0.40pp at ``n == 5``).
        That inverted the relationship and pushed 5-coin turnover to 94.7% of
        weeks -- roughly double the baseline it was meant to match.

    Args:
        n_assets: Number of coins in the portfolio (>= 1).

    Returns:
        The default absolute weight-deviation trigger.
    """
    if n_assets <= 2:
        return 0.01
    return 0.01 * math.sqrt(float(n_assets) / 2.0)


@dataclass(frozen=True)
class BacktestConfig:
    """Immutable parameter set that fully determines a backtest run.

    Attributes:
        initial_capital_usd: Gross capital committed at t0 (before entry fee).
        coins: Ordered coin universe, e.g. ``("BTC", "ETH", "XRP")``.  A list is
            accepted and normalised to a tuple.
        target_weights: Target portfolio weight per coin.  Leave empty for an
            equal-weight portfolio (``1 / n`` each), which is the default.
        rebalance_band: Absolute weight deviation that triggers a rebalance.
            ``0.01`` means "rebalance once *any* leg is more than 1 percentage
            point away from its target weight".
        fee_rate: Proportional trading fee applied to traded notional (0.001 ==
            0.1%).
        start_date: Inclusive ISO date from which weekly bars are built.
        end_date: Inclusive ISO date of the last bar; empty string means "today".
    """

    initial_capital_usd: float = 200.0
    coins: tuple[str, ...] = DEFAULT_COINS
    target_weights: dict[str, float] = field(default_factory=dict)
    rebalance_band: float = 0.01
    fee_rate: float = 0.001
    start_date: str = "2016-08-01"
    end_date: str = ""

    def __post_init__(self) -> None:
        """Normalises ``coins`` and fills in equal weights when unspecified.

        Raises:
            ValueError: If the coin universe is empty, contains duplicates, or
                the supplied weights do not cover every coin / sum to 1.
        """
        coins = tuple(str(coin).upper() for coin in self.coins)
        if not coins:
            raise ValueError("BacktestConfig.coins must not be empty")
        if len(set(coins)) != len(coins):
            raise ValueError(f"BacktestConfig.coins has duplicates: {coins}")
        object.__setattr__(self, "coins", coins)

        weights = dict(self.target_weights or {})
        if not weights:
            share = 1.0 / float(len(coins))
            weights = {coin: share for coin in coins}
        missing = [coin for coin in coins if coin not in weights]
        if missing:
            raise ValueError(f"target_weights is missing coins: {missing}")
        extra = [coin for coin in weights if coin not in coins]
        if extra:
            raise ValueError(f"target_weights has unknown coins: {extra}")
        total = sum(weights[coin] for coin in coins)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"target_weights must sum to 1.0, got {total!r}")
        # Preserve the coin ordering so downstream iteration is deterministic.
        object.__setattr__(self, "target_weights",
                           {coin: float(weights[coin]) for coin in coins})

    # ----------------------------------------------------------------- #
    # Derived accessors
    # ----------------------------------------------------------------- #
    @property
    def n_assets(self) -> int:
        """Returns the number of coins in the portfolio."""
        return len(self.coins)

    @property
    def price_columns(self) -> tuple[str, ...]:
        """Returns the weekly-panel close columns, in coin order."""
        return tuple(price_column(coin) for coin in self.coins)

    def target_weight(self, coin: str) -> float:
        """Returns the target weight of ``coin`` (0.0 when it is not held)."""
        return self.target_weights.get(coin.upper(), 0.0)

    # ----------------------------------------------------------------- #
    # Backwards-compatible 2-coin accessors (kept so the original BTC/ETH
    # tooling and the QA suite keep working unchanged).
    # ----------------------------------------------------------------- #
    @property
    def target_weight_eth(self) -> float:
        """Returns the target ETH weight (legacy 2-coin accessor)."""
        return self.target_weight("ETH")

    def target_weight_btc(self) -> float:
        """Returns the target BTC weight (legacy 2-coin accessor)."""
        return self.target_weight("BTC")


DEFAULT_CONFIG: BacktestConfig = BacktestConfig()
