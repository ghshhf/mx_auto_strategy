"""Reporting layer: terminal tables, CSV/JSON artefacts and the plotly chart."""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import pandas as pd

from backtest import LineResult
from config import BacktestConfig
from metrics import LineMetrics, compute_drawdown_series
from selfcheck import SelfCheckReport

LINE1_COLOR: str = "#e4572e"
LINE2_COLOR: str = "#2e86ab"
GRID_COLOR: str = "#e6e6e6"


# --------------------------------------------------------------------------- #
# Terminal output
# --------------------------------------------------------------------------- #
def _rule(width: int = 78, char: str = "=") -> str:
    """Returns a horizontal rule of ``width`` ``char`` characters."""
    return char * width


def _fmt_money(value: float) -> str:
    """Formats a USD amount with thousands separators and two decimals."""
    return f"{value:,.2f}"


def _fmt_pct(value: float, decimals: int = 2) -> str:
    """Formats a percentage with an explicit sign."""
    return f"{value:+,.{decimals}f}%"


def print_data_report(meta: dict[str, Any]) -> None:
    """Prints the data-provenance block to stdout.

    Args:
        meta: Metadata dictionary produced by ``data_sources.load_weekly_prices``.
    """
    print(_rule())
    print("数据源报告 / DATA PROVENANCE")
    print(_rule())
    print(f"  出网路由         : {meta['proxy']}")
    print(f"  日线原始区间     : {meta['daily_start']} ~ {meta['daily_end']} "
          f"({meta['daily_rows']} 个交易日)")
    print(f"  周线区间         : {meta['weekly_start']} ~ {meta['weekly_end']} "
          f"({meta['weekly_rows']} 周, 规则 {meta['weekly_rule']} 周五收盘)")
    for asset, entries in meta["sources"].items():
        for index, entry in enumerate(entries):
            label = asset if index == 0 else ""
            print(f"  {label:<16} : {entry}")
    for asset, splice in (meta.get("splices") or {}).items():
        print(f"  {asset + ' 拼接点':<16} : {splice['last_filler_date']} "
              f"{splice['last_filler_close']:,.4f} -> {splice['boundary_date']} "
              f"{splice['first_primary_close']:,.4f} "
              f"({splice['boundary_return_pct']:+.2f}% 单日, 无跳空断层)")
    gaps = meta.get("daily_gaps") or []
    if gaps:
        detail = ", ".join(f"{g['resumed']} 前缺 {g['missing_days']} 天" for g in gaps[:5])
        print(f"  {'日线缺口':<16} : 共 {meta.get('daily_missing_days', 0)} 天 ({detail})")
    else:
        print(f"  {'日线缺口':<16} : 无 (逐日连续)")
    non_friday = meta.get("weekly_non_friday_bars") or []
    if non_friday:
        print(f"  {'非周五周线':<16} : {', '.join(non_friday)} "
              f"(最后一根为进行中的当周, 取最新收盘)")
    print()


def print_metrics_table(metrics1: LineMetrics, metrics2: LineMetrics,
                        reference: dict[str, float],
                        config: BacktestConfig) -> None:
    """Prints the side-by-side metric comparison table.

    Args:
        metrics1: Metrics of the rebalanced line.
        metrics2: Metrics of the buy-and-hold line.
        reference: Single-asset reference values.
        config: Backtest parameters.
    """
    print(_rule())
    print("回测参数 / PARAMETERS")
    print(_rule())
    weight_desc = " / ".join(
        f"{coin} {weight:.0%}" for coin, weight in config.target_weights.items()
    )
    print(f"  初始投入         : {_fmt_money(config.initial_capital_usd)} USD ({weight_desc})")
    print(f"  再平衡阈值       : max|w_i - target_i| >= {config.rebalance_band:.2%} (逐周检查)")
    print(f"  手续费率         : {config.fee_rate:.3%} (建仓一次 + 每次再平衡按成交额)")
    print(f"  记账单位         : USD")
    print()

    print(_rule())
    print("指标对照 / METRICS  (线1 = 滚动互平衡, 线2 = 买入持有)")
    print(_rule())
    header = f"  {'指标':<22}{'线1 滚动互平衡':>20}{'线2 买入持有':>20}{'差异':>14}"
    print(header)
    print("  " + "-" * 74)

    rows: list[tuple[str, str, str, str]] = [
        ("期初投入 (USD)", _fmt_money(metrics1.gross_invested_usd),
         _fmt_money(metrics2.gross_invested_usd), "-"),
        ("建仓后净值 (USD)", _fmt_money(metrics1.initial_nav_usd),
         _fmt_money(metrics2.initial_nav_usd), "-"),
        ("终值 (USD)", _fmt_money(metrics1.final_nav_usd),
         _fmt_money(metrics2.final_nav_usd),
         _fmt_money(metrics1.final_nav_usd - metrics2.final_nav_usd)),
        ("总收益率", _fmt_pct(metrics1.total_return_pct),
         _fmt_pct(metrics2.total_return_pct),
         f"{metrics1.total_return_pct - metrics2.total_return_pct:+,.2f}pp"),
        ("年化 CAGR", _fmt_pct(metrics1.cagr_pct), _fmt_pct(metrics2.cagr_pct),
         f"{metrics1.cagr_pct - metrics2.cagr_pct:+,.2f}pp"),
        ("最大回撤", f"-{metrics1.max_drawdown_pct:,.2f}%",
         f"-{metrics2.max_drawdown_pct:,.2f}%",
         f"{metrics2.max_drawdown_pct - metrics1.max_drawdown_pct:+,.2f}pp"),
        ("年化波动率", f"{metrics1.volatility_annual_pct:,.2f}%",
         f"{metrics2.volatility_annual_pct:,.2f}%",
         f"{metrics1.volatility_annual_pct - metrics2.volatility_annual_pct:+,.2f}pp"),
        ("再平衡次数", f"{metrics1.rebalance_count:,}",
         f"{metrics2.rebalance_count:,}", "-"),
        ("累计手续费 (USD)", _fmt_money(metrics1.total_fee_usd),
         _fmt_money(metrics2.total_fee_usd),
         _fmt_money(metrics1.total_fee_usd - metrics2.total_fee_usd)),
        ("最好自然年", f"{metrics1.best_year[0]}  {metrics1.best_year[1]:+,.2f}%",
         f"{metrics2.best_year[0]}  {metrics2.best_year[1]:+,.2f}%", "-"),
        ("最差自然年", f"{metrics1.worst_year[0]}  {metrics1.worst_year[1]:+,.2f}%",
         f"{metrics2.worst_year[0]}  {metrics2.worst_year[1]:+,.2f}%", "-"),
        ("期末各币权重", " / ".join(f"{c} {w:,.1f}%"
                            for c, w in metrics1.final_weights_pct.items()),
         " / ".join(f"{c} {w:,.1f}%"
                   for c, w in metrics2.final_weights_pct.items()), "-"),
    ]
    for name, value1, value2, delta in rows:
        print(f"  {name:<22}{value1:>20}{value2:>20}{delta:>14}")
    print("  " + "-" * 74)
    print(f"  最大回撤区间  线1: {metrics1.drawdown.peak_date} -> "
          f"{metrics1.drawdown.trough_date}"
          f"{'  (已收复 ' + metrics1.drawdown.recovery_date + ')' if metrics1.drawdown.recovery_date else '  (未收复)'}")
    print(f"                线2: {metrics2.drawdown.peak_date} -> "
          f"{metrics2.drawdown.trough_date}"
          f"{'  (已收复 ' + metrics2.drawdown.recovery_date + ')' if metrics2.drawdown.recovery_date else '  (未收复)'}")
    print()

    print(_rule())
    print("单币参照 / SINGLE-ASSET REFERENCE (同样扣 0.1% 建仓费)")
    print(_rule())
    for coin in config.coins:
        key = coin.lower()
        print(f"  100% {coin} 终值    : {_fmt_money(reference[f'all_{key}_final_usd'])} USD  "
              f"({coin} {_fmt_money(reference[f'{key}_price_start'])} -> "
              f"{_fmt_money(reference[f'{key}_price_end'])})")
    print()


def print_annual_table(metrics1: LineMetrics, metrics2: LineMetrics) -> None:
    """Prints the calendar-year return comparison table."""
    print(_rule())
    print("自然年收益 / CALENDAR-YEAR RETURNS   (* = 不完整年度)")
    print(_rule())
    years = sorted(set(metrics1.annual_returns_pct) | set(metrics2.annual_returns_pct))
    print(f"  {'年度':<10}{'线1 滚动互平衡':>20}{'线2 买入持有':>20}{'超额':>14}")
    print("  " + "-" * 62)
    for year in years:
        value1 = metrics1.annual_returns_pct.get(year, 0.0)
        value2 = metrics2.annual_returns_pct.get(year, 0.0)
        print(f"  {year:<10}{value1:>19,.2f}%{value2:>19,.2f}%"
              f"{value1 - value2:>12,.2f}pp")
    print()


def print_self_check(report: SelfCheckReport) -> None:
    """Prints the invariant self-check block and the IS_PASS verdict."""
    print(_rule())
    print("质量自检 / SELF-CHECK")
    print(_rule())
    for check in report.checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"  [{status}] ({check.code}) {check.title}")
        print(f"         {check.detail}")
        for violation in check.violations:
            print(f"         ! {violation}")
    print()
    print(f"IS_PASS: {report.verdict}")
    print()


# --------------------------------------------------------------------------- #
# File artefacts
# --------------------------------------------------------------------------- #
def build_nav_frame(line1: LineResult, line2: LineResult) -> pd.DataFrame:
    """Combines both lines into a single NAV frame indexed by date."""
    nav1 = line1.nav_series()
    nav2 = line2.nav_series()
    frame = pd.DataFrame({"nav_line1": nav1, "nav_line2": nav2})
    frame.index.name = "date"
    return frame


def save_nav_csv(frame: pd.DataFrame, path: str) -> str:
    """Writes the NAV frame to ``path`` and returns the path."""
    frame.to_csv(path, float_format="%.6f")
    return path


def save_metrics_json(path: str, metrics1: LineMetrics, metrics2: LineMetrics,
                      reference: dict[str, float], meta: dict[str, Any],
                      config: BacktestConfig,
                      self_check: SelfCheckReport) -> str:
    """Serialises every metric and self-check outcome to JSON.

    Args:
        path: Destination file path.
        metrics1: Metrics of the rebalanced line.
        metrics2: Metrics of the buy-and-hold line.
        reference: Single-asset reference values.
        meta: Data-provenance metadata.
        config: Backtest parameters.
        self_check: Self-check report.

    Returns:
        The written path.
    """
    payload = {
        "generated_by": os.path.basename(sys.argv[0]) or "btc_eth_rebalance.py",
        "currency": "USD",
        "config": {
            "initial_capital_usd": config.initial_capital_usd,
            "coins": list(config.coins),
            "target_weights": dict(config.target_weights),
            "rebalance_band": config.rebalance_band,
            "fee_rate": config.fee_rate,
            "requested_start": config.start_date,
            "requested_end": config.end_date or "today",
        },
        "data": meta,
        "line1_rolling_rebalance": metrics1.to_dict(),
        "line2_buy_and_hold": metrics2.to_dict(),
        "single_asset_reference": reference,
        "comparison": {
            "final_nav_diff_usd": metrics1.final_nav_usd - metrics2.final_nav_usd,
            "final_nav_ratio": (metrics1.final_nav_usd / metrics2.final_nav_usd
                                if metrics2.final_nav_usd else 0.0),
            "cagr_diff_pp": metrics1.cagr_pct - metrics2.cagr_pct,
            "max_drawdown_diff_pp": (metrics2.max_drawdown_pct
                                     - metrics1.max_drawdown_pct),
        },
        "self_check": self_check.to_dict(),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def save_chart_html(path: str, nav_frame: pd.DataFrame, line1: LineResult,
                    metrics1: LineMetrics, metrics2: LineMetrics,
                    config: BacktestConfig) -> str:
    """Renders the interactive plotly report (NAV + drawdown) to ``path``.

    The figure has three stacked panels:
      1. Weekly NAV of both lines, with the maximum-drawdown windows shaded and
         a log/linear y-axis toggle.
      2. Running drawdown of both lines.
      3. Line 1's ETH weight before each week's action, with the rebalance band.

    Args:
        path: Destination ``.html`` file.
        nav_frame: Frame with ``nav_line1`` / ``nav_line2`` columns.
        line1: Rebalanced line result (used for weights and trade markers).
        metrics1: Metrics of the rebalanced line.
        metrics2: Metrics of the buy-and-hold line.
        config: Backtest parameters.

    Returns:
        The written path.
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    dates = nav_frame.index
    drawdown1 = compute_drawdown_series(nav_frame["nav_line1"])
    drawdown2 = compute_drawdown_series(nav_frame["nav_line2"])
    rebalance_dates = [record.date for record in line1.records[1:] if record.traded]
    rebalance_navs = [record.nav for record in line1.records[1:] if record.traded]

    weights_index = pd.DatetimeIndex([record.date for record in line1.records])
    is_two = config.n_assets == 2
    if is_two:
        weights = pd.Series(
            [record.weight_eth_pre * 100.0 for record in line1.records],
            index=weights_index,
        )
        panel3_title = "线1 再平衡前 ETH 权重 (%)"
    else:
        weights_frame = pd.DataFrame(
            {coin: [record.weights_pre.get(coin, 0.0) * 100.0
                    for record in line1.records]
             for coin in config.coins},
            index=weights_index,
        )
        panel3_title = "线1 再平衡前 各币权重 (%)"

    coin_label = " / ".join(f"{c} {w:.0%}" for c, w in config.target_weights.items())
    figure = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.56, 0.24, 0.20], vertical_spacing=0.045,
        subplot_titles=(
            f"周度净值 NAV (USD) — 初始投入 {config.initial_capital_usd:.0f} USD, "
            f"{coin_label}",
            "回撤 Drawdown (%)",
            panel3_title,
        ),
    )

    figure.add_trace(
        go.Scatter(
            x=dates, y=nav_frame["nav_line1"], name="线1 滚动互平衡",
            mode="lines", line=dict(color=LINE1_COLOR, width=2.1),
            hovertemplate="%{x|%Y-%m-%d}<br>线1 NAV: $%{y:,.2f}<extra></extra>",
        ), row=1, col=1)
    figure.add_trace(
        go.Scatter(
            x=dates, y=nav_frame["nav_line2"], name="线2 买入持有",
            mode="lines", line=dict(color=LINE2_COLOR, width=2.1, dash="solid"),
            hovertemplate="%{x|%Y-%m-%d}<br>线2 NAV: $%{y:,.2f}<extra></extra>",
        ), row=1, col=1)
    figure.add_trace(
        go.Scatter(
            x=rebalance_dates, y=rebalance_navs, name="再平衡点",
            mode="markers",
            marker=dict(color=LINE1_COLOR, size=4.5, symbol="circle-open",
                        line=dict(width=1)),
            hovertemplate="再平衡 %{x|%Y-%m-%d}<br>NAV: $%{y:,.2f}<extra></extra>",
            visible="legendonly",
        ), row=1, col=1)

    figure.add_trace(
        go.Scatter(
            x=dates, y=drawdown1, name="线1 回撤", mode="lines",
            line=dict(color=LINE1_COLOR, width=1.4), fill="tozeroy",
            fillcolor="rgba(228,87,46,0.16)", showlegend=False,
            hovertemplate="%{x|%Y-%m-%d}<br>线1 回撤: %{y:.2f}%<extra></extra>",
        ), row=2, col=1)
    figure.add_trace(
        go.Scatter(
            x=dates, y=drawdown2, name="线2 回撤", mode="lines",
            line=dict(color=LINE2_COLOR, width=1.4), fill="tozeroy",
            fillcolor="rgba(46,134,171,0.14)", showlegend=False,
            hovertemplate="%{x|%Y-%m-%d}<br>线2 回撤: %{y:.2f}%<extra></extra>",
        ), row=2, col=1)

    if is_two:
        figure.add_trace(
            go.Scatter(
                x=weights.index, y=weights.to_numpy(), name="ETH 权重(交易前)",
                mode="lines", line=dict(color="#6a4c93", width=1.2), showlegend=False,
                hovertemplate="%{x|%Y-%m-%d}<br>ETH 权重: %{y:.2f}%<extra></extra>",
            ), row=3, col=1)
        for level, dash in ((50.0, "solid"),
                            (50.0 + config.rebalance_band * 100.0, "dot"),
                            (50.0 - config.rebalance_band * 100.0, "dot")):
            figure.add_hline(y=level, line=dict(color="#999999", width=1, dash=dash),
                             row=3, col=1)
    else:
        for coin in config.coins:
            figure.add_trace(
                go.Scatter(
                    x=weights_frame.index, y=weights_frame[coin].to_numpy(),
                    name=f"{coin} 权重(交易前)", mode="lines",
                    stackgroup="weights", line=dict(width=0.5),
                    hovertemplate=f"%{{x|%Y-%m-%d}}<br>{coin} 权重: %{{y:.2f}}%<extra></extra>",
                ), row=3, col=1)
        target = 100.0 / config.n_assets
        for level, dash in ((target, "solid"),
                            (target + config.rebalance_band * 100.0, "dot"),
                            (target - config.rebalance_band * 100.0, "dot")):
            figure.add_hline(y=level, line=dict(color="#999999", width=1, dash=dash),
                             row=3, col=1)

    for metrics, color in ((metrics1, "rgba(228,87,46,0.10)"),
                           (metrics2, "rgba(46,134,171,0.10)")):
        if metrics.drawdown.peak_date and metrics.drawdown.trough_date:
            figure.add_vrect(
                x0=metrics.drawdown.peak_date, x1=metrics.drawdown.trough_date,
                fillcolor=color, line_width=0, layer="below", row=1, col=1)

    figure.update_yaxes(title_text="NAV (USD)", type="log", row=1, col=1,
                        gridcolor=GRID_COLOR)
    figure.update_yaxes(title_text="回撤 (%)", row=2, col=1, gridcolor=GRID_COLOR)
    figure.update_yaxes(title_text="权重 (%)", row=3, col=1,
                        gridcolor=GRID_COLOR)
    figure.update_xaxes(gridcolor=GRID_COLOR, row=3, col=1)

    annotation = (
        f"<b>线1 滚动互平衡</b>  终值 ${metrics1.final_nav_usd:,.2f} · "
        f"CAGR {metrics1.cagr_pct:+.2f}% · 最大回撤 -{metrics1.max_drawdown_pct:.2f}% · "
        f"再平衡 {metrics1.rebalance_count} 次<br>"
        f"<b>线2 买入持有</b>  终值 ${metrics2.final_nav_usd:,.2f} · "
        f"CAGR {metrics2.cagr_pct:+.2f}% · 最大回撤 -{metrics2.max_drawdown_pct:.2f}%"
    )
    figure.update_layout(
        title=dict(
            text=(f"{coin_label} 配对再平衡回测 "
                  f"({metrics1.start_date} ~ {metrics1.end_date}, "
                  f"{metrics1.weeks} 周, 记账单位 USD)"),
            x=0.5, xanchor="center", font=dict(size=19),
        ),
        annotations=list(figure.layout.annotations) + [
            dict(text=annotation, xref="paper", yref="paper", x=0.0, y=1.075,
                 showarrow=False, align="left", font=dict(size=12, color="#333333")),
        ],
        template="plotly_white",
        height=920,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.015, xanchor="right",
                    x=1.0),
        margin=dict(l=70, r=40, t=150, b=60),
        updatemenus=[dict(
            type="buttons", direction="right", showactive=True,
            x=0.0, xanchor="left", y=1.13, yanchor="top",
            buttons=[
                dict(label="对数轴", method="relayout",
                     args=[{"yaxis.type": "log"}]),
                dict(label="线性轴", method="relayout",
                     args=[{"yaxis.type": "linear"}]),
            ],
        )],
    )
    figure.write_html(path, include_plotlyjs=True, full_html=True,
                      config={"displaylogo": False, "scrollZoom": True})
    return path
