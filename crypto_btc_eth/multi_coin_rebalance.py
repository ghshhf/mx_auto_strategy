#!/usr/bin/env python3
"""5 币等权配对再平衡回测 — 一键入口 (真实数据, USD 记账).

用法::

    python multi_coin_rebalance.py                       # 拉数 -> 回测 -> 落盘 -> 自检
    python multi_coin_rebalance.py --no-cache            # 强制重新下载行情
    python multi_coin_rebalance.py --start 2017-11-01 --end 2026-08-02
    python multi_coin_rebalance.py --coins BTC,ETH,XRP,BNB,TRX --capital 500

产物 (与本脚本同目录)::

    multi_coin_weekly.csv   周线收盘价     date, btc_close, eth_close, xrp_close, bnb_close, trx_close
    nav_multi_coin.csv      两条线净值     date, nav_line1, nav_line2
    metrics_multi_coin.json 全部指标 + 自检结论
    nav_multi_coin.html     plotly 交互双线净值 + 回撤 + 各币权重

两条线::

    线1 「滚动互平衡」 每周检查, 任一币权重偏离目标 >= 阈值 即交易回等权, 按成交额收费
    线2 「买入持有」   t0 建仓后全程不动

数据源: Yahoo Finance (各币 -USD 日线) 为主; Binance 经代理返回 451 故 BNB 取 BNB-USD.
全部为交易所真实成交价, 无任何合成数据.
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
    FIVE_COINS,
    MULTI_CHART_HTML,
    MULTI_DAILY_CACHE_CSV,
    MULTI_METRICS_JSON,
    MULTI_NAV_CSV,
    MULTI_PRICE_CSV,
    BacktestConfig,
    default_rebalance_band,
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

LINE1_LABEL: str = "线1 滚动互平衡 (等权 banded rebalance)"
LINE2_LABEL: str = "线2 买入持有 (等权 buy & hold)"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses command-line arguments.

    Args:
        argv: Argument vector; ``None`` means ``sys.argv[1:]``.

    Returns:
        The populated namespace.
    """
    parser = argparse.ArgumentParser(
        description="多币等权配对再平衡回测 (真实数据, USD)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--coins", default=",".join(FIVE_COINS),
                        help="币清单, 逗号分隔 (如 BTC,ETH,XRP,BNB,TRX)")
    parser.add_argument("--start", default="2017-11-01",
                        help="回测起始日期 (ISO)")
    parser.add_argument("--end", default="",
                        help="回测结束日期 (ISO); 留空表示今天")
    parser.add_argument("--capital", type=float, default=500.0,
                        help="初始总投入 (USD), 等权分摊到每币")
    parser.add_argument("--band", type=float, default=None,
                        help="再平衡阈值 (权重绝对偏离); 留空按 0.01*(2/N) 自动")
    parser.add_argument("--fee", type=float, default=0.001,
                        help="手续费率 (0.001 = 0.1%)")
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
        ValueError: If any parameter is out of a sane range.
    """
    coins = tuple(c.strip().upper() for c in args.coins.split(",") if c.strip())
    if len(coins) < 2:
        raise ValueError("--coins 至少需要 2 个币")
    if args.capital <= 0.0:
        raise ValueError("--capital must be positive")
    if not 0.0 <= args.fee < 0.05:
        raise ValueError("--fee must be within [0, 0.05)")
    band = args.band if args.band is not None else default_rebalance_band(len(coins))
    if not 0.0 < band < 0.5:
        raise ValueError("--band must be within (0, 0.5)")
    end = args.end or _dt.date.today().strftime("%Y-%m-%d")
    _dt.datetime.strptime(args.start, "%Y-%m-%d")
    _dt.datetime.strptime(end, "%Y-%m-%d")
    if end <= args.start:
        raise ValueError("--end must be later than --start")
    return BacktestConfig(
        initial_capital_usd=float(args.capital),
        coins=coins,
        rebalance_band=float(band),
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
    print(f"{' / '.join(config.coins)} 等权配对再平衡回测  (真实数据 · USD 记账)")
    print(f"请求区间: {config.start_date} ~ {config.end_date} | "
          f"总投入 {config.initial_capital_usd:.0f} USD "
          f"(每币 {config.initial_capital_usd / len(config.coins):.0f} USD)")
    print()

    try:
        weekly, meta = load_weekly_prices(
            start=config.start_date,
            end=config.end_date,
            use_cache=not args.no_cache,
            cache_path=MULTI_DAILY_CACHE_CSV,
            coins=config.coins,
        )
    except Exception as error:  # noqa: BLE001
        print(f"[数据获取失败] {error}", file=sys.stderr)
        traceback.print_exc()
        return 2

    save_weekly_csv(weekly, MULTI_PRICE_CSV)
    print_data_report(meta)

    line1, line2 = run_backtest(weekly, config)
    metrics1 = compute_line_metrics(line1, config, LINE1_LABEL)
    metrics2 = compute_line_metrics(line2, config, LINE2_LABEL)
    reference = compute_buy_hold_reference(weekly, config)

    nav_frame = build_nav_frame(line1, line2)
    save_nav_csv(nav_frame, MULTI_NAV_CSV)

    print_metrics_table(metrics1, metrics2, reference, config)
    print_annual_table(metrics1, metrics2)

    self_check = run_self_checks(line1, line2, weekly, config)
    print_self_check(self_check)

    save_metrics_json(MULTI_METRICS_JSON, metrics1, metrics2, reference, meta,
                      config, self_check)

    chart_path = ""
    if not args.no_chart:
        try:
            chart_path = save_chart_html(MULTI_CHART_HTML, nav_frame, line1,
                                         metrics1, metrics2, config)
        except Exception as error:  # noqa: BLE001
            print(f"[警告] plotly 图表生成失败: {error}", file=sys.stderr)
            traceback.print_exc()

    print("=" * 78)
    print("产物 / ARTEFACTS")
    print("=" * 78)
    for description, path in (
        ("周线收盘价", MULTI_PRICE_CSV),
        ("两线净值", MULTI_NAV_CSV),
        ("指标 JSON", MULTI_METRICS_JSON),
        ("交互图表", chart_path or "(skipped)"),
        ("日线缓存", MULTI_DAILY_CACHE_CSV),
    ):
        print(f"  {description:<12}: {path}")
    print()

    return 0 if self_check.passed else 1


if __name__ == "__main__":
    sys.exit(main())
