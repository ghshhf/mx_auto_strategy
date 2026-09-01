#!/usr/bin/env python3
"""BTC/ETH 50:50 配对再平衡回测 — 一键入口 (真实数据, USD 记账).

用法::

    python btc_eth_rebalance.py                    # 拉数 -> 回测 -> 落盘 -> 自检
    python btc_eth_rebalance.py --no-cache         # 强制重新下载行情
    python btc_eth_rebalance.py --start 2016-08-01 --end 2026-08-02
    python btc_eth_rebalance.py --band 0.02 --fee 0.001 --capital 200

产物 (与本脚本同目录)::

    btc_eth_weekly.csv     周线收盘价     date, btc_close, eth_close
    nav_btc_eth.csv        两条线净值     date, nav_line1, nav_line2
    metrics_btc_eth.json   全部指标 + 自检结论
    nav_btc_eth.html       plotly 交互双线净值 + 回撤 + 权重

两条线::

    线1 「滚动互平衡」 每周检查, |w_eth - 50%| >= 阈值 即交易回 50/50, 按成交额收费
    线2 「买入持有」   t0 建仓后全程不动

数据源: Yahoo Finance (BTC-USD / ETH-USD 日线) 为主, Bitfinex 补 Yahoo 缺失的
2016-08 ~ 2017-11 ETH 段, Kraken 兜底. 全部为交易所真实成交价, 无任何合成数据.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from backtest import run_backtest                                  # noqa: E402
from config import (                                               # noqa: E402
    CHART_HTML,
    DAILY_CACHE_CSV,
    METRICS_JSON,
    NAV_CSV,
    PRICE_CSV,
    BacktestConfig,
)
from data_sources import load_weekly_prices, save_weekly_csv       # noqa: E402
from metrics import compute_buy_hold_reference, compute_line_metrics  # noqa: E402
from report import (                                               # noqa: E402
    build_nav_frame,
    print_annual_table,
    print_data_report,
    print_metrics_table,
    print_self_check,
    save_chart_html,
    save_metrics_json,
    save_nav_csv,
)
from selfcheck import run_self_checks                              # noqa: E402

LINE1_LABEL: str = "线1 滚动互平衡 (50/50 banded rebalance)"
LINE2_LABEL: str = "线2 买入持有 (50/50 buy & hold)"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses command-line arguments.

    Args:
        argv: Argument vector; ``None`` means ``sys.argv[1:]``.

    Returns:
        The populated namespace.
    """
    parser = argparse.ArgumentParser(
        description="BTC/ETH 50:50 配对再平衡回测 (真实数据, USD)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--start", default="2016-08-01",
                        help="回测起始日期 (ISO)")
    parser.add_argument("--end", default="",
                        help="回测结束日期 (ISO); 留空表示今天")
    parser.add_argument("--capital", type=float, default=200.0,
                        help="初始投入 (USD)")
    parser.add_argument("--band", type=float, default=0.01,
                        help="再平衡阈值 (权重绝对偏离, 0.01 = 1 个百分点)")
    parser.add_argument("--fee", type=float, default=0.001,
                        help="手续费率 (0.001 = 0.1%%)")
    parser.add_argument("--no-cache", action="store_true",
                        help="忽略本地日线缓存, 强制重新下载")
    parser.add_argument("--no-chart", action="store_true",
                        help="跳过 plotly HTML 生成")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> BacktestConfig:
    """Builds the immutable backtest configuration from CLI arguments.

    Args:
        args: Parsed CLI namespace.

    Returns:
        A validated :class:`config.BacktestConfig`.

    Raises:
        ValueError: If any numeric parameter is out of a sane range.
    """
    if args.capital <= 0.0:
        raise ValueError("--capital must be positive")
    if not 0.0 <= args.fee < 0.05:
        raise ValueError("--fee must be within [0, 0.05)")
    if not 0.0 < args.band < 0.5:
        raise ValueError("--band must be within (0, 0.5)")
    end = args.end or _dt.date.today().strftime("%Y-%m-%d")
    _dt.datetime.strptime(args.start, "%Y-%m-%d")
    _dt.datetime.strptime(end, "%Y-%m-%d")
    if end <= args.start:
        raise ValueError("--end must be later than --start")
    return BacktestConfig(
        initial_capital_usd=float(args.capital),
        coins=("BTC", "ETH"),
        rebalance_band=float(args.band),
        fee_rate=float(args.fee),
        start_date=args.start,
        end_date=end,
    )


def main(argv: list[str] | None = None) -> int:
    """Runs the whole pipeline: fetch -> backtest -> report -> self-check.

    Args:
        argv: Argument vector; ``None`` means ``sys.argv[1:]``.

    Returns:
        Process exit code: ``0`` when every self-check passed, ``1`` otherwise,
        ``2`` on an unhandled failure.
    """
    args = parse_args(argv)
    try:
        config = build_config(args)
    except ValueError as error:
        print(f"[参数错误] {error}", file=sys.stderr)
        return 2

    print()
    print("BTC / ETH 50:50 配对再平衡回测  (真实数据 · USD 记账)")
    print(f"请求区间: {config.start_date} ~ {config.end_date}")
    print()

    try:
        weekly, meta = load_weekly_prices(
            start=config.start_date,
            end=config.end_date,
            use_cache=not args.no_cache,
            cache_path=DAILY_CACHE_CSV,
        )
    except Exception as error:  # noqa: BLE001
        print(f"[数据获取失败] {error}", file=sys.stderr)
        traceback.print_exc()
        return 2

    save_weekly_csv(weekly, PRICE_CSV)
    print_data_report(meta)

    line1, line2 = run_backtest(weekly, config)
    metrics1 = compute_line_metrics(line1, config, LINE1_LABEL)
    metrics2 = compute_line_metrics(line2, config, LINE2_LABEL)
    reference = compute_buy_hold_reference(weekly, config)

    nav_frame = build_nav_frame(line1, line2)
    save_nav_csv(nav_frame, NAV_CSV)

    print_metrics_table(metrics1, metrics2, reference, config)
    print_annual_table(metrics1, metrics2)

    self_check = run_self_checks(line1, line2, weekly, config)
    print_self_check(self_check)

    save_metrics_json(METRICS_JSON, metrics1, metrics2, reference, meta,
                      config, self_check)

    chart_path = ""
    if not args.no_chart:
        try:
            chart_path = save_chart_html(CHART_HTML, nav_frame, line1,
                                         metrics1, metrics2, config)
        except Exception as error:  # noqa: BLE001
            print(f"[警告] plotly 图表生成失败: {error}", file=sys.stderr)
            traceback.print_exc()

    print("=" * 78)
    print("产物 / ARTEFACTS")
    print("=" * 78)
    for description, path in (
        ("周线收盘价", PRICE_CSV),
        ("两线净值", NAV_CSV),
        ("指标 JSON", METRICS_JSON),
        ("交互图表", chart_path or "(skipped)"),
        ("日线缓存", DAILY_CACHE_CSV),
    ):
        print(f"  {description:<12}: {path}")
    print()

    return 0 if self_check.passed else 1


if __name__ == "__main__":
    sys.exit(main())
