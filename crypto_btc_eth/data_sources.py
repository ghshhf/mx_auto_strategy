"""Real market-data acquisition for BTC/ETH (weekly USD closes).

Source priority
---------------
1. **Yahoo Finance** (``yfinance`` library first, raw ``/v8/finance/chart``
   endpoint as automatic fallback) -- daily ``BTC-USD`` / ``ETH-USD`` closes.
2. **Bitfinex** public candles (``tBTCUSD`` / ``tETHUSD``) -- used to splice the
   history that Yahoo does not carry.  Yahoo's ``ETH-USD`` series only starts
   2017-11-09, so the 2016-08 .. 2017-11 window is filled from Bitfinex, which
   has continuous daily ETH/USD data from 2016-03.
3. **Kraken** public OHLC -- last-resort fallback.

Everything returned by this module is *real exchange data*.  Nothing is
synthesised, interpolated across gaps, or back-filled with fabricated prices.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time
import urllib.request
from typing import Callable

import pandas as pd

from config import (
    BITFINEX_SYMBOLS,
    COINBASE_CHUNK_DAYS,
    COINBASE_SYMBOLS,
    DAILY_CACHE_CSV,
    DAILY_CACHE_META,
    HTTP_RETRIES,
    HTTP_TIMEOUT,
    KRAKEN_SYMBOLS,
    PROXY_CANDIDATES,
    PROXY_PROBE_URL,
    USER_AGENT,
    WEEKLY_RULE,
    YAHOO_SYMBOLS,
    price_column,
)

UTC = _dt.timezone.utc

# Module-level state: resolved once by :func:`ensure_proxy`.
_ACTIVE_PROXY: str | None = None
_PROXY_RESOLVED: bool = False


# --------------------------------------------------------------------------- #
# Proxy / HTTP plumbing
# --------------------------------------------------------------------------- #
def _build_opener(proxy: str | None) -> urllib.request.OpenerDirector:
    """Builds a urllib opener bound to ``proxy`` (or forced-direct if None)."""
    handler = (
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        if proxy
        else urllib.request.ProxyHandler({})
    )
    return urllib.request.build_opener(handler)


def _probe(proxy: str | None, timeout: int = 12) -> bool:
    """Returns True if ``PROXY_PROBE_URL`` is reachable through ``proxy``."""
    try:
        opener = _build_opener(proxy)
        request = urllib.request.Request(
            PROXY_PROBE_URL, headers={"User-Agent": USER_AGENT}
        )
        with opener.open(request, timeout=timeout) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return False


def ensure_proxy(verbose: bool = True) -> str | None:
    """Resolves and installs the outbound proxy exactly once per process.

    Tries every entry of :data:`config.PROXY_CANDIDATES` in order, then a direct
    connection.  The winning proxy is exported into ``HTTP(S)_PROXY`` so that
    third-party libraries (``yfinance`` / ``curl_cffi`` / ``requests``) pick it
    up as well, and is installed as the default urllib opener.

    Args:
        verbose: Whether to print the resolution result to stderr.

    Returns:
        The proxy URL that works, or ``None`` when a direct connection works.

    Raises:
        RuntimeError: If neither any candidate proxy nor a direct connection can
            reach the probe URL.
    """
    global _ACTIVE_PROXY, _PROXY_RESOLVED
    if _PROXY_RESOLVED:
        return _ACTIVE_PROXY

    # A stale/incorrect proxy inherited from the shell would poison every
    # library call, so start from a clean slate.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                "ALL_PROXY", "all_proxy"):
        os.environ.pop(key, None)

    candidates: list[str | None] = [*PROXY_CANDIDATES, None]
    for candidate in candidates:
        if _probe(candidate):
            _ACTIVE_PROXY = candidate
            _PROXY_RESOLVED = True
            if candidate:
                for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy",
                            "https_proxy"):
                    os.environ[key] = candidate
            urllib.request.install_opener(_build_opener(candidate))
            if verbose:
                label = candidate if candidate else "direct (no proxy)"
                print(f"  [net] outbound route = {label}", file=sys.stderr)
            return _ACTIVE_PROXY

    raise RuntimeError(
        "No outbound route available: tried "
        f"{list(PROXY_CANDIDATES)} and a direct connection."
    )


def http_get(url: str, timeout: int = HTTP_TIMEOUT,
             retries: int = HTTP_RETRIES) -> str:
    """Fetches ``url`` as text through the resolved proxy, with retries.

    Args:
        url: Absolute HTTP(S) URL.
        timeout: Per-attempt socket timeout in seconds.
        retries: Number of attempts before giving up.

    Returns:
        The decoded response body.

    Raises:
        RuntimeError: If every attempt fails.
    """
    ensure_proxy(verbose=False)
    opener = _build_opener(_ACTIVE_PROXY)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
            )
            with opener.open(request, timeout=timeout) as response:
                return response.read().decode("utf-8", "ignore")
        except Exception as error:  # noqa: BLE001
            last_error = error
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"GET failed after {retries} attempts: {url} -> {last_error}")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _to_epoch(date_str: str) -> int:
    """Converts an ISO ``YYYY-MM-DD`` string to a UTC epoch second."""
    return int(_dt.datetime.strptime(date_str, "%Y-%m-%d")
               .replace(tzinfo=UTC).timestamp())


def _clean_series(series: pd.Series, name: str) -> pd.Series:
    """Normalises a raw close series: UTC-naive daily index, sorted, no NaN."""
    series = series.dropna()
    series = series[series > 0.0]
    series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
    series = series[~series.index.duplicated(keep="last")].sort_index()
    series.name = name
    return series.astype(float)


# --------------------------------------------------------------------------- #
# Source 1: Yahoo Finance
# --------------------------------------------------------------------------- #
def _yahoo_via_chart_api(symbol: str, start: str, end: str) -> pd.Series:
    """Downloads daily closes straight from Yahoo's public chart endpoint."""
    period1 = _to_epoch(start)
    period2 = _to_epoch(end) + 86_400
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={period1}&period2={period2}&interval=1d"
        f"&includePrePost=false&events=div%2Csplit"
    )
    payload = json.loads(http_get(url))
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError(f"Yahoo chart API returned no result for {symbol}")
    block = result[0]
    stamps = block.get("timestamp") or []
    quote = (block.get("indicators") or {}).get("quote") or [{}]
    closes = quote[0].get("close") or []
    if not stamps or not closes:
        raise RuntimeError(f"Yahoo chart API returned empty candles for {symbol}")
    index = [_dt.datetime.fromtimestamp(int(t), UTC) for t in stamps]
    return _clean_series(pd.Series(closes, index=index), symbol)


def _yahoo_via_yfinance(symbol: str, start: str, end: str) -> pd.Series:
    """Downloads daily closes with the ``yfinance`` library (preferred path)."""
    import yfinance  # Imported lazily so the raw API path works without it.

    end_exclusive = (
        _dt.datetime.strptime(end, "%Y-%m-%d") + _dt.timedelta(days=1)
    ).strftime("%Y-%m-%d")
    frame = yfinance.download(
        tickers=symbol,
        start=start,
        end=end_exclusive,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if frame is None or frame.empty:
        raise RuntimeError(f"yfinance returned an empty frame for {symbol}")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    if "Close" not in frame.columns:
        raise RuntimeError(f"yfinance frame for {symbol} has no Close column")
    return _clean_series(frame["Close"], symbol)


def fetch_yahoo_daily(symbol: str, start: str, end: str) -> tuple[pd.Series, str]:
    """Fetches Yahoo daily closes, preferring yfinance and falling back to REST.

    Args:
        symbol: Yahoo ticker, e.g. ``"BTC-USD"``.
        start: Inclusive ISO start date.
        end: Inclusive ISO end date.

    Returns:
        ``(series, source_label)`` where *series* is a daily close series.

    Raises:
        RuntimeError: If both the library and the REST endpoint fail.
    """
    try:
        series = _yahoo_via_yfinance(symbol, start, end)
        return series, "yahoo/yfinance"
    except Exception as error:  # noqa: BLE001
        print(f"  [warn] yfinance failed for {symbol} ({error}); "
              f"falling back to Yahoo chart API", file=sys.stderr)
    series = _yahoo_via_chart_api(symbol, start, end)
    return series, "yahoo/chart-api"


# --------------------------------------------------------------------------- #
# Source 2: Coinbase Exchange (genuine USD spot, no USDT basis)
# --------------------------------------------------------------------------- #
def fetch_coinbase_daily(product: str, start: str, end: str) -> pd.Series:
    """Fetches daily closes from Coinbase Exchange public candles.

    Coinbase serves at most 300 candles per call, so the window is walked in
    :data:`config.COINBASE_CHUNK_DAYS` slices.  ``ETH-USD`` history on this venue
    reaches back to 2016-05 and is gap-free, which makes it the preferred filler
    for the stretch Yahoo does not cover.

    Args:
        product: Coinbase product id such as ``"ETH-USD"``.
        start: Inclusive ISO start date.
        end: Inclusive ISO end date.

    Returns:
        A daily close series (empty when the venue has no data / is unreachable).
    """
    cursor = _dt.datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=UTC)
    finish = _dt.datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=UTC)
    collected: dict[_dt.datetime, float] = {}
    while cursor <= finish:
        chunk_end = min(cursor + _dt.timedelta(days=COINBASE_CHUNK_DAYS), finish)
        url = (
            f"https://api.exchange.coinbase.com/products/{product}/candles"
            f"?granularity=86400"
            f"&start={cursor:%Y-%m-%dT00:00:00Z}&end={chunk_end:%Y-%m-%dT00:00:00Z}"
        )
        try:
            rows = json.loads(http_get(url))
        except Exception as error:  # noqa: BLE001
            print(f"  [warn] Coinbase {product} chunk failed: {error}",
                  file=sys.stderr)
            break
        if not isinstance(rows, list):
            break
        for row in rows:
            # Coinbase row layout: [time, low, high, open, close, volume]
            collected[_dt.datetime.fromtimestamp(int(row[0]), UTC)] = float(row[4])
        if chunk_end >= finish:
            break
        cursor = chunk_end
        time.sleep(0.35)
    if not collected:
        return pd.Series(dtype=float, name=product)
    return _clean_series(pd.Series(collected), product)


# --------------------------------------------------------------------------- #
# Source 3: Bitfinex
# --------------------------------------------------------------------------- #
def fetch_bitfinex_daily(pair: str, start: str, end: str) -> pd.Series:
    """Fetches daily closes from Bitfinex public candles (paginated).

    Args:
        pair: Bitfinex symbol such as ``"tETHUSD"``.
        start: Inclusive ISO start date.
        end: Inclusive ISO end date.

    Returns:
        A daily close series (possibly empty if the pair has no history).
    """
    start_ms = _to_epoch(start) * 1000
    end_ms = (_to_epoch(end) + 86_400) * 1000
    collected: dict[_dt.datetime, float] = {}
    cursor = start_ms
    for _ in range(40):  # 40 * 10000 daily candles is far beyond any need.
        url = (
            f"https://api-pub.bitfinex.com/v2/candles/trade:1D:{pair}/hist"
            f"?start={cursor}&end={end_ms}&limit=10000&sort=1"
        )
        try:
            rows = json.loads(http_get(url))
        except Exception as error:  # noqa: BLE001
            print(f"  [warn] Bitfinex {pair} page failed: {error}", file=sys.stderr)
            break
        if not isinstance(rows, list) or not rows:
            break
        for row in rows:
            stamp_ms, _open, close = int(row[0]), float(row[1]), float(row[2])
            collected[_dt.datetime.fromtimestamp(stamp_ms / 1000.0, UTC)] = close
        next_cursor = int(rows[-1][0]) + 86_400_000
        if next_cursor <= cursor or next_cursor >= end_ms:
            break
        cursor = next_cursor
        time.sleep(0.3)
    if not collected:
        return pd.Series(dtype=float, name=pair)
    return _clean_series(pd.Series(collected), pair)


# --------------------------------------------------------------------------- #
# Source 4: Kraken (last resort)
# --------------------------------------------------------------------------- #
def fetch_kraken_weekly(pair: str, start: str) -> pd.Series:
    """Fetches weekly closes from Kraken public OHLC (Thursday-anchored bins).

    Kraken caps the response at ~720 candles, which at weekly resolution still
    covers ~13.8 years, so this is a viable emergency fallback.

    Args:
        pair: Kraken pair such as ``"ETHUSD"``.
        start: Inclusive ISO start date.

    Returns:
        A weekly close series (possibly empty when the request fails).
    """
    since = _to_epoch(start)
    url = (f"https://api.kraken.com/0/public/OHLC?pair={pair}"
           f"&interval=10080&since={since}")
    try:
        payload = json.loads(http_get(url))
    except Exception as error:  # noqa: BLE001
        print(f"  [warn] Kraken {pair} failed: {error}", file=sys.stderr)
        return pd.Series(dtype=float, name=pair)
    result = payload.get("result") or {}
    keys = [k for k in result if k != "last"]
    if not keys:
        return pd.Series(dtype=float, name=pair)
    rows = result[keys[0]]
    data = {
        _dt.datetime.fromtimestamp(int(r[0]), UTC): float(r[4]) for r in rows
    }
    if not data:
        return pd.Series(dtype=float, name=pair)
    return _clean_series(pd.Series(data), pair)


# --------------------------------------------------------------------------- #
# Series assembly
# --------------------------------------------------------------------------- #
def build_daily_series(asset: str, start: str,
                       end: str) -> tuple[pd.Series, list[str], dict]:
    """Builds one continuous daily close series for ``asset`` from real sources.

    Yahoo is the primary source and always wins on overlapping dates.  When
    Yahoo's history begins after ``start`` -- which is the case for ``ETH-USD``,
    whose Yahoo series only starts 2017-11-09 -- the missing head is spliced in
    from the fallback venues, in priority order:

    1. **Coinbase Exchange** ``ETH-USD`` / ``BTC-USD`` -- a real USD spot pair
       with gap-free daily history back to 2016-05.
    2. **Bitfinex** ``tETHUSD`` / ``tBTCUSD`` -- fills anything Coinbase misses
       (note: Bitfinex was offline 2016-08-03 .. 2016-08-09 after its hack).
    3. **Kraken** weekly OHLC -- only if nothing above returned data.

    Args:
        asset: ``"BTC"`` or ``"ETH"``.
        start: Inclusive ISO start date.
        end: Inclusive ISO end date.

    Returns:
        ``(series, sources, splice)`` -- the merged daily series, the
        human-readable provenance list, and a splice-continuity diagnostic.

    Raises:
        RuntimeError: If no source produced any usable data.
    """
    sources: list[str] = []
    splice: dict = {}
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    primary = pd.Series(dtype=float)
    try:
        primary, label = fetch_yahoo_daily(YAHOO_SYMBOLS[asset], start, end)
        if not primary.empty:
            sources.append(
                f"{label}:{YAHOO_SYMBOLS[asset]} "
                f"[{primary.index[0]:%Y-%m-%d}~{primary.index[-1]:%Y-%m-%d}] "
                f"{len(primary)}d"
            )
    except Exception as error:  # noqa: BLE001
        print(f"  [warn] Yahoo unavailable for {asset}: {error}", file=sys.stderr)

    merged = primary.copy()
    primary_start = primary.index[0] if not primary.empty else None

    if primary.empty or primary_start > start_ts:
        gap_end_ts = (primary_start - pd.Timedelta(days=1)
                      if primary_start is not None else end_ts)
        gap_end = gap_end_ts.strftime("%Y-%m-%d")
        if primary.empty:
            print(f"  [gap] {asset}: Yahoo returned nothing; filling "
                  f"{start}~{gap_end} from fallback venues", file=sys.stderr)
        else:
            print(f"  [gap] {asset}: Yahoo starts {primary_start:%Y-%m-%d} > "
                  f"requested {start}; filling {start}~{gap_end} from fallback "
                  f"venues", file=sys.stderr)

        fillers: list[tuple[str, Callable[[], pd.Series]]] = []
        if asset in COINBASE_SYMBOLS:
            fillers.append((
                f"coinbase:{COINBASE_SYMBOLS[asset]}",
                lambda: fetch_coinbase_daily(COINBASE_SYMBOLS[asset], start, gap_end),
            ))
        if asset in BITFINEX_SYMBOLS:
            fillers.append((
                f"bitfinex:{BITFINEX_SYMBOLS[asset]}",
                lambda: fetch_bitfinex_daily(BITFINEX_SYMBOLS[asset], start, gap_end),
            ))
        for name, fetcher in fillers:
            if not merged.empty and merged.index.min() <= start_ts:
                break  # The head is already fully covered.
            try:
                fragment = fetcher()
            except Exception as error:  # noqa: BLE001
                print(f"  [warn] {name} failed: {error}", file=sys.stderr)
                continue
            if fragment.empty:
                continue
            fragment = fragment[(fragment.index >= start_ts)
                                & (fragment.index <= gap_end_ts)]
            if not merged.empty:
                fragment = fragment[~fragment.index.isin(merged.index)]
            if fragment.empty:
                continue
            sources.append(
                f"{name} [{fragment.index[0]:%Y-%m-%d}~"
                f"{fragment.index[-1]:%Y-%m-%d}] {len(fragment)}d (gap fill)"
            )
            merged = (pd.concat([fragment, merged]).sort_index()
                      if not merged.empty else fragment)

    if merged.empty and asset in KRAKEN_SYMBOLS:
        weekly = fetch_kraken_weekly(KRAKEN_SYMBOLS[asset], start)
        if not weekly.empty:
            sources.append(f"kraken:{KRAKEN_SYMBOLS[asset]} (weekly, last resort)")
            merged = weekly

    if merged.empty:
        raise RuntimeError(f"No real price data could be obtained for {asset}")

    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    merged = merged[(merged.index >= start_ts) & (merged.index <= end_ts)]

    # Continuity diagnostic across the hand-off between the filler and Yahoo.
    if primary_start is not None and merged.index.min() < primary_start:
        before = merged.index[merged.index < primary_start]
        if len(before) > 0:
            previous_date = before[-1]
            previous_price = float(merged.loc[previous_date])
            boundary_price = float(merged.loc[primary_start])
            splice = {
                "boundary_date": primary_start.strftime("%Y-%m-%d"),
                "last_filler_date": previous_date.strftime("%Y-%m-%d"),
                "last_filler_close": previous_price,
                "first_primary_close": boundary_price,
                "boundary_return_pct": (boundary_price / previous_price - 1.0) * 100.0,
            }

    merged.name = asset
    return merged, sources, splice


def resample_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """Resamples daily closes to Friday-anchored weekly closes.

    Each weekly bin spans Saturday..Friday and is stamped with the date of the
    **last actually observed** daily bar inside the bin.  For complete weeks
    that is the Friday itself; for the final (still running) week it is the last
    trading day available, which keeps the reported dates honest instead of
    projecting a future Friday.

    Args:
        daily: Frame indexed by date with columns ``btc_close`` / ``eth_close``.

    Returns:
        A weekly frame with a ``date`` index and the same close columns.
    """
    working = daily.copy()
    working["_observed"] = working.index
    weekly = working.resample(WEEKLY_RULE).last().dropna(how="any")
    observed = weekly.pop("_observed")
    weekly.index = pd.DatetimeIndex(pd.to_datetime(observed.to_numpy()), name="date")
    return weekly.sort_index()


def load_weekly_prices(start: str, end: str, use_cache: bool = True,
                       cache_path: str = DAILY_CACHE_CSV,
                       coins: tuple[str, ...] = ("BTC", "ETH")
                       ) -> tuple[pd.DataFrame, dict]:
    """Returns the weekly close panel for ``coins`` plus provenance metadata.

    Args:
        start: Inclusive ISO start date of the study window.
        end: Inclusive ISO end date of the study window.
        use_cache: When True, a previously downloaded daily panel that fully
            covers the requested window *and* carries every requested coin
            column is reused instead of hitting the network.
        cache_path: Location of the raw daily cache CSV.  The provenance metadata
            is written alongside it (``<name>.meta.json``).
        coins: Ordered coin universe, e.g. ``("BTC", "ETH")`` or the five-coin
            tuple.  Every coin must have a ``YAHOO_SYMBOLS`` entry.

    Returns:
        ``(weekly_frame, meta)``.  *weekly_frame* has one ``<coin>_close`` column
        per coin, indexed by date; *meta* documents the data sources and the
        realised coverage.
    """
    coins = tuple(str(coin).upper() for coin in coins)
    if not coins:
        raise ValueError("load_weekly_prices requires a non-empty coin universe")
    price_cols = [price_column(coin) for coin in coins]
    meta_path = (cache_path[:-4] + ".meta.json") if cache_path.lower().endswith(".csv") \
        else (cache_path + ".meta.json")

    daily: pd.DataFrame | None = None
    sources: dict[str, list[str]] = {}
    splices: dict[str, dict] = {}
    route: str = ""

    if use_cache and os.path.exists(cache_path):
        cached = pd.read_csv(cache_path, parse_dates=["date"]).set_index("date")
        if set(price_cols).issubset(set(cached.columns)):
            covers_start = cached.index.min() <= pd.Timestamp(start) + pd.Timedelta(days=7)
            fresh_enough = cached.index.max() >= pd.Timestamp(end) - pd.Timedelta(days=3)
            if covers_start and fresh_enough and not cached.empty:
                daily = cached[price_cols].copy()
                # Replay the provenance recorded when the cache was written, so a
                # cached run reports the same real sources as a live run.
                if os.path.exists(meta_path):
                    with open(meta_path, "r", encoding="utf-8") as handle:
                        saved = json.load(handle)
                    sources = saved.get("sources", {})
                    splices = saved.get("splices", {})
                    route = f"{saved.get('proxy', 'unknown')} (本次复用本地缓存, 未联网)"
                else:
                    sources = {"cache": [f"{cache_path} (无 provenance 记录)"]}
                    route = "cache (no network, provenance unknown)"
                print(f"  [cache] reusing daily panel {cache_path}", file=sys.stderr)

    if daily is None:
        ensure_proxy(verbose=True)
        series_map: dict[str, pd.Series] = {}
        src_map: dict[str, list[str]] = {}
        spl_map: dict[str, dict] = {}
        for coin in coins:
            series, src, spl = build_daily_series(coin, start, end)
            series_map[coin] = series
            src_map[coin] = src
            if spl:
                spl_map[coin] = spl
        daily = pd.DataFrame(
            {price_column(coin): series_map[coin] for coin in coins}
        ).dropna(how="any")
        daily.index.name = "date"
        daily.to_csv(cache_path, float_format="%.10g")
        sources = src_map
        splices = spl_map
        route = _ACTIVE_PROXY or "direct"
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump({"sources": sources, "splices": splices, "proxy": route,
                       "fetched_at": _dt.datetime.now(UTC).isoformat(),
                       "coins": list(coins)},
                      handle, ensure_ascii=False, indent=2)

    daily = daily[(daily.index >= pd.Timestamp(start)) & (daily.index <= pd.Timestamp(end))]
    if daily.empty:
        raise RuntimeError("Daily panel is empty after applying the date filter")

    weekly = resample_weekly(daily)
    if len(weekly) < 52:
        raise RuntimeError(f"Only {len(weekly)} weekly bars produced; refusing to "
                           "run a backtest on such a short sample")

    day_gaps = daily.index.to_series().diff().dt.days.dropna()
    oversized = day_gaps[day_gaps > 1]
    meta = {
        "coins": list(coins),
        "sources": sources,
        "splices": splices,
        "daily_rows": int(len(daily)),
        "daily_start": daily.index[0].strftime("%Y-%m-%d"),
        "daily_end": daily.index[-1].strftime("%Y-%m-%d"),
        "daily_missing_days": int(oversized.sum() - len(oversized)) if len(oversized) else 0,
        "daily_gaps": [
            {"resumed": date.strftime("%Y-%m-%d"), "missing_days": int(gap) - 1}
            for date, gap in oversized.items()
        ],
        "weekly_rows": int(len(weekly)),
        "weekly_start": weekly.index[0].strftime("%Y-%m-%d"),
        "weekly_end": weekly.index[-1].strftime("%Y-%m-%d"),
        "weekly_rule": WEEKLY_RULE,
        "weekly_non_friday_bars": [
            date.strftime("%Y-%m-%d") for date in weekly.index if date.dayofweek != 4
        ],
        "proxy": route or (_ACTIVE_PROXY or "direct"),
    }
    return weekly, meta


def save_weekly_csv(weekly: pd.DataFrame, path: str) -> str:
    """Writes the weekly close panel to ``path`` and returns the path."""
    out = weekly.copy()
    out.index.name = "date"
    out.to_csv(path, float_format="%.8f")
    return path
