# -*- coding: utf-8 -*-
"""
回归测试: 交易成本建模 (backtest_engine costs 参数)
验证:
  1. costs=False 时零成本 (与旧版可比)
  2. costs=True 时净倍数 < 毛倍数
  3. 自定义费率生效
  4. stats 含 total_cost_deducted 字段
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ashare_backtest"))
from backtest_engine import run


def _make_panel(tmpdir):
    """创建最小面板: 2 只票 + HS300, 60 周数据."""
    import csv
    path = os.path.join(tmpdir, "test_panel.csv")
    codes = ["600519", "000300"]
    dates = [f"2020-{w:02d}-0" + str((w % 4) + 1) for w in range(1, 61)]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date"] + codes)
        for i, d in enumerate(dates):
            # 600519: 100→160 (1.6x), HS300: 100→120 (1.2x)
            w.writerow([d, 100 + i, 100 + i * 0.2])
    return path


class TestCosts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = os.path.join(os.path.dirname(__file__), "_tmp_costs")
        os.makedirs(cls.tmpdir, exist_ok=True)
        cls.panel = _make_panel(cls.tmpdir)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_costs_false_zero_deduction(self):
        """costs=False 时成本扣除为 0"""
        s, _, _, _ = run(offense_mode="fixed", death_cross=False,
                         panel_path=self.panel, costs=False,
                         start_capital=100000)
        self.assertEqual(s["total_cost_deducted"], 0)
        self.assertFalse(s["costs"])

    def test_costs_true_has_deduction(self):
        """costs=True 时成本扣除 > 0"""
        s, _, _, _ = run(offense_mode="fixed", death_cross=False,
                         panel_path=self.panel, costs=True,
                         start_capital=100000)
        self.assertTrue(s["costs"])
        self.assertGreater(s["total_cost_deducted"], 0)

    def test_net_less_than_gross(self):
        """含成本倍数 <= 毛收益倍数 (成本只会降低收益)"""
        s_gross, _, _, _ = run(offense_mode="fixed", death_cross=False,
                               panel_path=self.panel, costs=False,
                               start_capital=100000)
        s_net, _, _, _ = run(offense_mode="fixed", death_cross=False,
                             panel_path=self.panel, costs=True,
                             start_capital=100000)
        self.assertLessEqual(s_net["final_multiple"], s_gross["final_multiple"] + 0.001)

    def test_custom_rates(self):
        """自定义费率: 高费率 → 更多扣除"""
        s_low, _, _, _ = run(offense_mode="fixed", death_cross=False,
                             panel_path=self.panel, costs=True,
                             commission_rate=0.0001, stamp_duty_rate=0.0001,
                             slippage=0.0001, start_capital=100000)
        s_high, _, _, _ = run(offense_mode="fixed", death_cross=False,
                              panel_path=self.panel, costs=True,
                              commission_rate=0.01, stamp_duty_rate=0.01,
                              slippage=0.01, start_capital=100000)
        self.assertGreater(s_high["total_cost_deducted"],
                           s_low["total_cost_deducted"])

    def test_zero_rates_same_as_no_costs(self):
        """费率全 0 等价于 costs=False"""
        s_zero, _, _, _ = run(offense_mode="fixed", death_cross=False,
                              panel_path=self.panel, costs=True,
                              commission_rate=0, stamp_duty_rate=0,
                              slippage=0, start_capital=100000)
        s_off, _, _, _ = run(offense_mode="fixed", death_cross=False,
                             panel_path=self.panel, costs=False,
                             start_capital=100000)
        self.assertEqual(s_zero["final_multiple"], s_off["final_multiple"])

    def test_stats_has_cost_fields(self):
        """stats 字典包含成本相关字段"""
        s, _, _, _ = run(offense_mode="fixed", death_cross=False,
                         panel_path=self.panel, costs=True,
                         start_capital=100000)
        self.assertIn("costs", s)
        self.assertIn("total_cost_deducted", s)


if __name__ == "__main__":
    unittest.main()
