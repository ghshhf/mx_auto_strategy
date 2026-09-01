"""Dynamic Top-N coin-selection backtest over a ~100-coin universe (walk-forward).

This is the pool-expansion the user asked for:
  * candidate pool = ~100 curated major coins (top market-cap names as of ~2026)
  * 5-year window (2021-08-01 ~ 2026-08-02), 100 USD start, same selector as the
    5-coin experiment (momentum + trend gate, Top-3, rebalance on change / 4w)
  * compare against naive equal-weight of the SAME universe (rolling + hold)

Honesty constraints (carried over from the 5-coin experiment, now scaled):
  * The trend filter (price >= MA) is the OPPOSITE of a "buy dying coins" rule:
    it refuses to hold coins in a death spiral, so we never deliberately buy
    something about to be delisted -- no manual blacklist needed.
  * Selection at week i uses ONLY closes up to week i (walk-forward). No future
    data enters a decision.
  * The one-sided fee mechanic is copied verbatim from backtest.run_rolling_rebalance
    (via run_dynamic_select), so cost accounting matches the validated engine.

Mechanical "扣" (exclusions) -- no subjective coin picking:
  * Stablecoins (USDT/USDC/DAI/...): excluded because they are not return assets
    and would pollute a momentum screen.
  * Coins without real Yahoo -USD history covering the full 5y window (listed
    after 2021-08, or no ticker): dropped because we only use REAL data.
  * Survivorship bias is REDUCED (100 names vs 5) but NOT eliminated -- Yahoo only
    carries coins that are still listed, so dead/delisted coins cannot be fetched.
    This is disclosed, not hidden.
"""
from __future__ import annotations

import json
import os
import sys
import datetime as _dt

import pandas as pd

import config
from config import BacktestConfig, price_column, default_rebalance_band
import data_sources
from data_sources import build_daily_series, resample_weekly
from backtest import run_backtest
from metrics import compute_line_metrics, compute_buy_hold_reference
from dynamic_select_rebalance import run_dynamic_select, self_check

HERE = os.path.dirname(os.path.abspath(__file__))
UNI_CACHE_CSV = os.path.join(HERE, "universe100_daily_raw.csv")
UNI_METRICS_JSON = os.path.join(HERE, "dynamic_metrics_100.json")
UNI_NAV_CSV = os.path.join(HERE, "dynamic_nav_100.csv")
UNI_CHART_HTML = os.path.join(HERE, "dynamic_nav_100.html")
UNI_PANEL_CSV = os.path.join(HERE, "universe100_panel.csv")
UNI_PANEL_META = os.path.join(HERE, "universe100_panel.meta.json")

# --- Experiment parameters (consistent with the 5-coin run) ---------------- #
START = "2021-08-01"
END = "2026-08-02"
CAPITAL = 100.0
FEE = 0.001
LOOKBACK = 12          # momentum trailing window (weeks, ~3 months)
MA_WINDOW = 20         # trend filter (weeks, ~5 months)
TOP_N = 3              # hold the strongest 3 of the pool
REBALANCE_EVERY = 4    # periodic harvest cadence (weeks)

# ~100 curated candidates (top market-cap names as of ~2026). Stablecoins are
# included on purpose and then mechanically excluded, so the "扣" is visible.
CANDIDATE_100 = [
    # Layer 1: majors listed pre-2021 (strong Yahoo -USD coverage expected)
    "BTC", "ETH", "XRP", "BNB", "TRX", "ADA", "DOGE", "SOL", "LTC", "BCH",
    "DOT", "LINK", "XLM", "ETC", "XMR", "ATOM", "FIL", "EOS", "THETA", "VET",
    "XTZ", "XEM", "DASH", "ZEC", "NEO", "QTUM", "OMG", "ZRX", "REP", "DCR",
    "WAVES", "UNI", "AAVE", "MKR", "COMP", "YFI", "SNX", "SUSHI", "BAL", "GRT",
    "ALGO", "IOST", "KSM", "EGLD", "ZIL", "ENJ", "BAT", "ICX", "ONT", "HOT",
    "NANO", "SC", "DGB", "REN", "KNC", "LRC", "CVC", "ANT", "NMR", "MLN",
    "GNO", "MTL", "BNT", "RLC", "KEEP", "NU", "OCEAN",
    # Layer 2: 2020-2021 listings (may or may not cover the full 5y window)
    "AVAX", "MATIC", "NEAR", "APT", "ARB", "OP", "INJ", "RNDR", "SAND", "MANA",
    "AXS", "FTM", "CHZ", "CRV", "ONE", "HBAR", "ROSE", "KAVA", "RUNE", "FLOW",
    "CAKE", "TIA", "SEI", "STRK", "JTO", "JUP", "PYTH", "WIF", "PEPE", "BONK",
    "ONDO", "WLD", "SUPER", "ORDI", "AKT", "GALA", "FLOKI", "DYDX", "QNT", "CRO",
    "KCS", "CHR", "DENT", "IOTA", "RVN", "WIN",
    # Layer 3: stablecoins (intentionally listed, then mechanically excluded)
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "FDUSD", "USDE", "FRAX", "GUSD", "USDP",
]
STABLECOINS = {
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "FDUSD", "USDE", "FRAX",
    "GUSD", "USDP", "UST", "USDD", "LUSD", "SUSD",
}


# --------------------------------------------------------------------------- #
# Universe construction (real data only, mechanical exclusions)
# --------------------------------------------------------------------------- #
def build_universe(start: str, end: str) -> tuple[pd.DataFrame, dict]:
    """Fetches every candidate coin, keeps only those with full-window real
    data, and returns an inner-joined weekly close panel + provenance meta.
    """
    # Inject every candidate into the Yahoo symbol map (mutating the shared dict
    # object that data_sources also references).
    config.YAHOO_SYMBOLS.update({s: f"{s}-USD" for s in CANDIDATE_100})

    # Cache reuse: if a prior run already built the panel, skip the network fetch.
    if os.path.exists(UNI_PANEL_CSV) and os.path.exists(UNI_PANEL_META):
        try:
            cached = pd.read_csv(UNI_PANEL_CSV, parse_dates=["date"]).set_index("date")
            with open(UNI_PANEL_META, "r", encoding="utf-8") as handle:
                cached_meta = json.load(handle)
        except (ValueError, json.JSONDecodeError, OSError):
            cached = None  # truncated/corrupt cache -> fall through to re-fetch
        else:
            covers = (cached.index.min() <= pd.Timestamp(start) + pd.Timedelta(days=7)
                      and cached.index.max() >= pd.Timestamp(end) - pd.Timedelta(days=3))
            if covers:
                print(f"[cache] 复用已抓面板 {UNI_PANEL_CSV} ({len(cached.columns)} 币)",
                      file=sys.stderr)
                return cached, cached_meta

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    min_weeks = 250  # ~4.8y; anything shorter did not cover the window

    kept: dict[str, pd.Series] = {}
    dropped_stable: list[str] = []
    dropped_nodata: list[dict] = []
    sources: dict[str, list[str]] = {}

    investable = [s for s in CANDIDATE_100 if s not in STABLECOINS]
    print(f"[uni] {len(CANDIDATE_100)} 候选 -> {len(investable)} 可投(已扣 "
          f"{len(CANDIDATE_100) - len(investable)} 稳定币), 开始逐个抓真实周线...",
          file=sys.stderr)

    for sym in investable:
        col = price_column(sym)
        try:
            daily, src, _spl = build_daily_series(sym, start, end)
        except Exception as exc:  # noqa: BLE001
            dropped_nodata.append({"coin": sym, "reason": f"fetch failed: {exc}"})
            print(f"  [drop] {sym}: 抓取失败 -> {exc}", file=sys.stderr)
            continue
        if daily is None or daily.empty:
            dropped_nodata.append({"coin": sym, "reason": "empty series"})
            print(f"  [drop] {sym}: 空序列", file=sys.stderr)
            continue
        weekly = resample_weekly(pd.DataFrame({col: daily}))
        weekly = weekly[[col]].dropna()
        if weekly.empty:
            dropped_nodata.append({"coin": sym, "reason": "no weekly bars"})
            continue
        first, last = weekly.index[0], weekly.index[-1]
        covers = (first <= start_ts + pd.Timedelta(days=7)
                  and last >= end_ts - pd.Timedelta(days=3)
                  and len(weekly) >= min_weeks)
        if not covers:
            dropped_nodata.append({
                "coin": sym,
                "reason": f"window gap (first={first:%Y-%m-%d}, last={last:%Y-%m-%d}, "
                          f"weeks={len(weekly)})",
            })
            print(f"  [drop] {sym}: 未覆盖整窗 (首 {first:%Y-%m-%d} 末 {last:%Y-%m-%d} "
                  f"{len(weekly)}周)", file=sys.stderr)
            continue
        kept[col] = weekly[col]
        sources[sym] = src
        print(f"  [keep] {sym}: {len(weekly)} 周 ({first:%Y-%m-%d}~{last:%Y-%m-%d})",
              file=sys.stderr)

    if not kept:
        raise RuntimeError("No coin produced a full-window weekly panel.")

    panel = pd.concat(kept.values(), axis=1, sort=False).dropna(how="any")
    panel.index.name = "date"
    panel = panel.sort_index()
    coins = tuple(c[:-6].upper() for c in panel.columns)

    meta = {
        "candidates_total": len(CANDIDATE_100),
        "stablecoins_excluded": sorted(STABLECOINS & set(CANDIDATE_100)),
        "investable_attempted": len(investable),
        "kept_count": len(coins),
        "dropped_nodata_count": len(dropped_nodata),
        "dropped_nodata": dropped_nodata,
        "panel_start": panel.index[0].strftime("%Y-%m-%d"),
        "panel_end": panel.index[-1].strftime("%Y-%m-%d"),
        "panel_weeks": int(len(panel)),
        "coins": list(coins),
        "sources": sources,
    }

    # Persist the assembled panel so re-runs skip the network fetch.
    panel.to_csv(UNI_PANEL_CSV, float_format="%.8f")
    with open(UNI_PANEL_META, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)

    return panel, meta


# --------------------------------------------------------------------------- #
# Reporting helpers (100-coin variant)
# --------------------------------------------------------------------------- #
def _line_block(m) -> dict:
    return {
        "name": m.name, "label": m.label,
        "start_date": m.start_date, "end_date": m.end_date,
        "weeks": m.weeks, "years": m.years,
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


def save_metrics_json(path, dyn_m, eq_roll_m, eq_hold_m, reference, meta,
                      verdict, checks, params):
    ref_items = {k: v for k, v in reference.items() if k.startswith("all_")}
    ref_top = dict(sorted(ref_items.items(), key=lambda kv: kv[1],
                          reverse=True)[:5])
    payload = {
        "currency": "USD",
        "experiment": "dynamic_top3_vs_equal_weight_N (100-coin universe)",
        "params": params,
        "universe": {k: meta[k] for k in (
            "candidates_total", "stablecoins_excluded", "investable_attempted",
            "kept_count", "dropped_nodata_count", "panel_start", "panel_end",
            "panel_weeks", "coins", "dropped_nodata")},
        "dynamic_top3": _line_block(dyn_m),
        "equal_weight_N_rolling": _line_block(eq_roll_m),
        "equal_weight_N_hold": _line_block(eq_hold_m),
        "single_asset_reference_top5": {k: round(v, 2) for k, v in ref_top.items()},
        "comparison": {
            "dyn_vs_eqN_rolling_final_ratio":
                round(dyn_m.final_nav_usd / eq_roll_m.final_nav_usd, 4),
            "dyn_vs_eqN_rolling_cagr_diff_pp":
                round(dyn_m.cagr_pct - eq_roll_m.cagr_pct, 2),
            "eqN_rolling_vs_eqN_hold_final_ratio":
                round(eq_roll_m.final_nav_usd / eq_hold_m.final_nav_usd, 4),
        },
        "honesty_notes": [
            f"池子从 5 币扩到 {meta['kept_count']} 币(候选 {meta['candidates_total']}), "
            f"幸存者偏差被削弱但未消除: Yahoo 只载仍在市的币, 退市币无法抓取。",
            "选币在周 i 仅用截至周 i 的数据(walk-forward), 无前视。",
            "趋势过滤(价格>=MA)天然排除暴跌/濒死币, 系统不故意买退市币, 无手工黑名单。",
            "稳定币与窗口内无真实数据的币被机械剔除, 不含任何按收益主观挑币。",
            "手续费机制与已验证的 backtest.run_rolling_rebalance 逐位一致。",
            "等权基准用带宽触发再平衡(换手与带宽匹配), 动态线用换仓/4周触发, 节奏不完全同频, 仅作同池对照。",
        ],
        "self_check": {"verdict": verdict,
                       "checks": [{"code": c.code, "title": c.title,
                                   "passed": c.passed, "detail": c.detail}
                                  for c in checks]},
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def save_chart_html(path, nav_map: dict[str, pd.Series], blocks: dict):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    dates = next(iter(nav_map.values())).index
    dyn = nav_map["dynamic"]
    eqr = nav_map["eq_rolling"]
    eqh = nav_map["eq_hold"]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.72, 0.28], vertical_spacing=0.05,
                        subplot_titles=("周度净值 NAV (USD, 对数轴)", "回撤 Drawdown (%)"))
    fig.add_trace(go.Scatter(x=dates, y=dyn, name="动态 Top3", mode="lines",
                             line=dict(color="#e4572e", width=2.2),
                             hovertemplate="%{x|%Y-%m-%d}<br>动态 Top3: $%{y:,.2f}<extra></extra>"),
                   row=1, col=1)
    fig.add_trace(go.Scatter(x=dates, y=eqr, name="等权N币 滚动", mode="lines",
                             line=dict(color="#6a4c93", width=1.6, dash="dot"),
                             hovertemplate="%{x|%Y-%m-%d}<br>等权N滚动: $%{y:,.2f}<extra></extra>"),
                   row=1, col=1)
    fig.add_trace(go.Scatter(x=dates, y=eqh, name="等权N币 持有", mode="lines",
                             line=dict(color="#2a9d8f", width=1.8, dash="dash"),
                             hovertemplate="%{x|%Y-%m-%d}<br>等权N持有: $%{y:,.2f}<extra></extra>"),
                   row=1, col=1)

    def dd(series):
        return (series / series.cummax() - 1.0) * 100.0
    fig.add_trace(go.Scatter(x=dates, y=dd(dyn), name="动态 Top3 回撤", mode="lines",
                             line=dict(color="#e4572e", width=1.3), fill="tozeroy",
                             fillcolor="rgba(228,87,46,0.14)", showlegend=False,
                             hovertemplate="%{x|%Y-%m-%d}<br>动态回撤: %{y:.2f}%<extra></extra>"),
                   row=2, col=1)
    fig.add_trace(go.Scatter(x=dates, y=dd(eqr), name="等权N滚动 回撤", mode="lines",
                             line=dict(color="#6a4c93", width=1.3), showlegend=False,
                             hovertemplate="%{x|%Y-%m-%d}<br>等权N滚动回撤: %{y:.2f}%<extra></extra>"),
                   row=2, col=1)

    n = blocks["dynamic"].rebalance_count
    ann = (f"<b>动态 Top3</b> 终值 ${blocks['dynamic'].final_nav_usd:,.2f} · "
           f"CAGR {blocks['dynamic'].cagr_pct:+.1f}% · MDD -{blocks['dynamic'].max_drawdown_pct:.1f}% · "
           f"再平衡 {n} 次<br>"
           f"<b>等权N滚动</b> 终值 ${blocks['eq_rolling'].final_nav_usd:,.2f} · "
           f"CAGR {blocks['eq_rolling'].cagr_pct:+.1f}% · MDD -{blocks['eq_rolling'].max_drawdown_pct:.1f}%<br>"
           f"<b>等权N持有</b> 终值 ${blocks['eq_hold'].final_nav_usd:,.2f} · "
           f"CAGR {blocks['eq_hold'].cagr_pct:+.1f}%").format(
        ) if False else (
        f"<b>动态 Top3</b> 终值 ${blocks['dynamic'].final_nav_usd:,.2f} · "
        f"CAGR {blocks['dynamic'].cagr_pct:+.1f}% · MDD -{blocks['dynamic'].max_drawdown_pct:.1f}% · "
        f"再平衡 {blocks['dynamic'].rebalance_count} 次<br>"
        f"<b>等权N滚动</b> 终值 ${blocks['eq_rolling'].final_nav_usd:,.2f} · "
        f"CAGR {blocks['eq_rolling'].cagr_pct:+.1f}% · MDD -{blocks['eq_rolling'].max_drawdown_pct:.1f}%<br>"
        f"<b>等权N持有</b> 终值 ${blocks['eq_hold'].final_nav_usd:,.2f} · "
        f"CAGR {blocks['eq_hold'].cagr_pct:+.1f}%")
    fig.update_layout(
        title=dict(text=("动态 Top3 选币 vs 等权N币（5年, 100 USD 起步, 池子=100候选）"),
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
    panel, meta = build_universe(START, END)
    coins = tuple(c[:-6].upper() for c in panel.columns)
    print(f"[data] 池子落地 {meta['kept_count']} 币, "
          f"{meta['panel_start']}~{meta['panel_end']} ({meta['panel_weeks']} 周)")
    print(f"[data] 扣掉: {meta['dropped_nodata_count']} 币无整窗数据 + "
          f"{len(meta['stablecoins_excluded'])} 稳定币")

    # --- dynamic Top3 line ---
    dyn_line = run_dynamic_select(panel, coins, LOOKBACK, MA_WINDOW, TOP_N,
                                 REBALANCE_EVERY, FEE, CAPITAL)
    dyn_config = BacktestConfig(
        initial_capital_usd=CAPITAL, coins=coins,
        rebalance_band=default_rebalance_band(len(coins)), fee_rate=FEE,
        start_date=START, end_date=END,
    )
    dyn_m = compute_line_metrics(dyn_line, dyn_config, "动态 Top3 选币(动量+趋势过滤)")

    # --- equal-weight N baseline (rolling + hold) ---
    eq_config = BacktestConfig(
        initial_capital_usd=CAPITAL, coins=coins,
        rebalance_band=default_rebalance_band(len(coins)), fee_rate=FEE,
        start_date=START, end_date=END,
    )
    eq_roll, eq_hold = run_backtest(panel, eq_config)
    eq_roll_m = compute_line_metrics(eq_roll, eq_config, "等权N币 滚动互平衡")
    eq_hold_m = compute_line_metrics(eq_hold, eq_config, "等权N币 买入持有")

    reference = compute_buy_hold_reference(panel, dyn_config)

    # --- self-check ---
    verdict, checks = self_check(dyn_line, panel, dyn_config)
    for c in checks:
        print(f"  [{'PASS' if c.passed else 'FAIL'}] ({c.code}) {c.title}")

    # --- artefacts ---
    nav_map = {
        "dynamic": dyn_line.nav_series(),
        "eq_rolling": eq_roll.nav_series(),
        "eq_hold": eq_hold.nav_series(),
    }
    pd.DataFrame(nav_map).to_csv(UNI_NAV_CSV, float_format="%.6f")
    save_metrics_json(UNI_METRICS_JSON, dyn_m, eq_roll_m, eq_hold_m, reference,
                      meta, verdict, checks,
                      {"start": START, "end": END, "capital_usd": CAPITAL,
                       "candidates": len(CANDIDATE_100),
                       "kept_pool": list(coins), "fee_rate": FEE,
                       "lookback_weeks": LOOKBACK, "ma_window": MA_WINDOW,
                       "top_n": TOP_N, "rebalance_every_weeks": REBALANCE_EVERY,
                       "warmup_weeks": max(LOOKBACK, MA_WINDOW)})
    save_chart_html(UNI_CHART_HTML, nav_map,
                    {"dynamic": dyn_m, "eq_rolling": eq_roll_m, "eq_hold": eq_hold_m})
    print(f"[out] {UNI_METRICS_JSON}")
    print(f"[out] {UNI_NAV_CSV}")
    print(f"[out] {UNI_CHART_HTML}")

    # --- headline comparison ---
    print(f"\n=== 100币池 5年对照 (100 USD 起步, 实落 {meta['kept_count']} 币) ===")
    rows = [("动态 Top3", dyn_m), ("等权N币 滚动", eq_roll_m), ("等权N币 持有", eq_hold_m)]
    print(f"{'策略':<16}{'终值 USD':>12}{'CAGR':>10}{'MDD':>10}{'再平衡':>8}{'费 USD':>9}")
    for name, m in rows:
        print(f"{name:<16}{m.final_nav_usd:>12,.2f}{m.cagr_pct:>+9.1f}%"
              f"{-m.max_drawdown_pct:>8.1f}%{m.rebalance_count:>8}{m.total_fee_usd:>9.2f}")
    print(f"\n动态 Top3 vs 等权N滚动: 终值比 "
          f"{dyn_m.final_nav_usd/eq_roll_m.final_nav_usd:.3f}x, "
          f"CAGR 差 {dyn_m.cagr_pct-eq_roll_m.cagr_pct:+.1f}pp")
    print(f"等权N滚动 vs 等权N持有: 终值比 "
          f"{eq_roll_m.final_nav_usd/eq_hold_m.final_nav_usd:.3f}x")
    print(f"IS_PASS: {verdict}")


if __name__ == "__main__":
    main()
