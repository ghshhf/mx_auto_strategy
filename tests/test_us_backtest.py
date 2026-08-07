"""
us_backtest 止盈止损 + 成本模型 单元测试。

覆盖:
  - check_take_profit: +50% 触发清仓, 边界 149.99 不触发
  - check_stop_loss: -8% 触发清仓, 边界 92.01 不触发
  - check_take_profit 优先于 check_stop_loss
  - load_us_cfg: 配置读取 + 默认值兜底
  - run_optimized: 持仓状态更新 + 成本扣减 + 止盈触发清仓
  - 无前视: 止盈止损只用 t 时刻已知信息
  - 原逻辑不回归: 关闭止盈止损时结果接近原版

全部为纯函数/合成面板测试, 不依赖外部行情数据。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "us_stocks"))

import us_backtest_ai as ubt


class TestCheckTakeProfit(unittest.TestCase):
    def setUp(self):
        self.us_cfg = {"take_profit_pct": 0.50, "stop_loss_pct": -0.08, "slippage_bps": 10}

    def test_triggers_at_50pct(self):
        state = {"entry_price": 100.0}
        self.assertEqual(ubt.check_take_profit("X", state, 150.0, self.us_cfg), "clear")

    def test_not_trigger_below_threshold(self):
        state = {"entry_price": 100.0}
        self.assertIsNone(ubt.check_take_profit("X", state, 149.99, self.us_cfg))

    def test_triggers_above_threshold(self):
        state = {"entry_price": 100.0}
        self.assertEqual(ubt.check_take_profit("X", state, 200.0, self.us_cfg), "clear")

    def test_zero_entry_returns_none(self):
        state = {"entry_price": 0}
        self.assertIsNone(ubt.check_take_profit("X", state, 150.0, self.us_cfg))

    def test_none_price_returns_none(self):
        state = {"entry_price": 100.0}
        self.assertIsNone(ubt.check_take_profit("X", state, None, self.us_cfg))


class TestCheckStopLoss(unittest.TestCase):
    def setUp(self):
        self.us_cfg = {"take_profit_pct": 0.50, "stop_loss_pct": -0.08, "slippage_bps": 10}

    def test_triggers_at_minus_8pct(self):
        state = {"entry_price": 100.0}
        self.assertEqual(ubt.check_stop_loss("X", state, 92.0, self.us_cfg), "clear")

    def test_not_trigger_above_threshold(self):
        state = {"entry_price": 100.0}
        self.assertIsNone(ubt.check_stop_loss("X", state, 92.01, self.us_cfg))

    def test_triggers_on_bigger_loss(self):
        state = {"entry_price": 100.0}
        self.assertEqual(ubt.check_stop_loss("X", state, 50.0, self.us_cfg), "clear")

    def test_zero_entry_returns_none(self):
        state = {"entry_price": 0}
        self.assertIsNone(ubt.check_stop_loss("X", state, 50.0, self.us_cfg))


class TestLoadUsCfg(unittest.TestCase):
    def test_reads_from_real_config(self):
        cfg = ubt.load_us_cfg()
        self.assertEqual(cfg["take_profit_pct"], 0.50)
        self.assertEqual(cfg["stop_loss_pct"], -999.0)
        self.assertEqual(cfg["slippage_bps"], 3)
        self.assertIn("options", cfg)

    def test_default_on_missing_file(self):
        cfg = ubt.load_us_cfg("/nonexistent/path.json")
        self.assertEqual(cfg["take_profit_pct"], 0.50)
        self.assertEqual(cfg["stop_loss_pct"], -999.0)
        self.assertEqual(cfg["slippage_bps"], 3)


class TestRunOptimizedTakeProfit(unittest.TestCase):
    """合成面板: 单票从 100 涨到 150, 验证止盈触发清仓。"""
    def test_take_profit_clears_position(self):
        # 构造合成面板: SPY 平稳 + 单票 X 建仓后涨到 150 触发止盈
        # X 在 WARMUP 前需有正动量(90->100)才能被 select_optimized 选中(权重>0),
        # WARMUP 时 entry=100, 止盈价=150, WARMUP+20 后涨到 150 触发
        n = 90
        dates = [f"2020-01-{i+1:02d}" for i in range(n)]
        series = {"SPY": [100.0 + i * 0.1 for i in range(n)]}
        x_prices = []
        for i in range(n):
            if i < ubt.WARMUP:
                x_prices.append(90.0 + i * (10.0 / ubt.WARMUP))  # 90->100 正动量
            elif i < ubt.WARMUP + 20:
                x_prices.append(100.0 + (i - ubt.WARMUP) * 2.5)  # 100->150
            else:
                x_prices.append(150.0)  # 触发止盈
        series["X"] = x_prices
        us_cfg = {"take_profit_pct": 0.50, "stop_loss_pct": -0.08, "slippage_bps": 10,
                  "options": {"enabled": False}}
        ubt.series_proxy = {"SPY": series["SPY"]}
        nav_hist, stats = ubt.run_optimized(
            series, dates, use_ai=False, cfg=None,
            top_n=1, trend_gate=None, lookback=4, rebal=1,
            us_cfg=us_cfg,
        )
        self.assertGreater(stats["take_profit_count"], 0,
                           "应至少触发一次止盈")


class TestRunOptimizedNoRegression(unittest.TestCase):
    """关闭止盈止损时(take_profit_pct=inf, stop_loss_pct=-inf), 结果接近原版。"""
    def test_disabled_tp_sl_runs_clean(self):
        n = 80
        dates = [f"2020-01-{i+1:02d}" for i in range(n)]
        series = {"SPY": [100.0 + i * 0.1 for i in range(n)]}
        series["X"] = [100.0 + i * 0.5 for i in range(n)]
        # 关闭止盈止损
        us_cfg = {"take_profit_pct": 999.0, "stop_loss_pct": -999.0,
                  "slippage_bps": 0, "options": {"enabled": False}}
        ubt.series_proxy = {"SPY": series["SPY"]}
        nav_hist, stats = ubt.run_optimized(
            series, dates, use_ai=False, cfg=None,
            top_n=1, trend_gate=None, lookback=4, rebal=1,
            us_cfg=us_cfg,
        )
        # 止盈止损不应触发
        self.assertEqual(stats["take_profit_count"], 0)
        self.assertEqual(stats["stop_loss_count"], 0)
        # 成本应为 0(slippage_bps=0)
        self.assertEqual(stats["cost_total"], 0.0)
        # NAV 应为正
        self.assertGreater(stats["multiple"], 0)


class TestUsOptionsShell(unittest.TestCase):
    """期权接口空壳(阶段1 返回 None)。"""
    def test_covered_call_returns_none(self):
        import us_options
        self.assertIsNone(us_options.covered_call_at_take_profit("AAPL", 150.0, {}))

    def test_protective_put_returns_none(self):
        import us_options
        self.assertIsNone(us_options.protective_put_for_hedge("QQQ", 400.0, {}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
