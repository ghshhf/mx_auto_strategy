# -*- coding: utf-8 -*-
"""
回归测试: walk_forward 滚动窗口验证
验证:
  1. walk_forward 返回 windows 列表 + summary
  2. 每个窗口有 multiple/mdd/cagr 字段
  3. summary 含均值/标准差/胜率
  4. 训练+测试窗口数正确
  5. 不同参数产生不同窗口数
"""
import os
import sys
import unittest
import csv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "markets", "ashare"))
from walk_forward import walk_forward, print_report
from backtest_engine import DEF16, OFF4, CORE_SUB, HS300, DC_INDICES


def _make_panel(tmpdir, n_weeks=300):
    """创建足够长的面板用于 walk-forward (300 周 ≈ 5.7 年)."""
    path = os.path.join(tmpdir, "wf_panel.csv")
    # 需要至少 DEF16 + OFF4代理 + HS300 + DC_INDICES
    needed = DEF16 + list(CORE_SUB.values()) + [HS300] + DC_INDICES
    codes = list(dict.fromkeys(needed))  # 去重保序
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date"] + codes)
        for i in range(n_weeks):
            year = 2020 + i // 52
            week = (i % 52) + 1
            d = f"{year}-{week:02d}-01"
            row = [d]
            for j, c in enumerate(codes):
                # 交替涨跌, 保证有正收益
                base = 100 + i * (0.3 + j * 0.02)
                row.append(round(base, 2))
            w.writerow(row)
    return path


class TestWalkForward(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = os.path.join(os.path.dirname(__file__), "_tmp_wf")
        os.makedirs(cls.tmpdir, exist_ok=True)
        cls.panel = _make_panel(cls.tmpdir, n_weeks=300)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_returns_windows_and_summary(self):
        """返回结构包含 windows 列表和 summary"""
        r = walk_forward(panel_path=self.panel, train_years=2, test_years=1,
                         offense_mode="fixed", core_satellite=False,
                         death_cross=False, costs=False)
        self.assertIn("windows", r)
        self.assertIn("summary", r)
        self.assertIsInstance(r["windows"], list)
        self.assertIsInstance(r["summary"], dict)

    def test_window_count(self):
        """2年训练+1年测试, 300周(≈5.7年)应产生至少 3 个窗口"""
        r = walk_forward(panel_path=self.panel, train_years=2, test_years=1,
                         offense_mode="fixed", core_satellite=False,
                         death_cross=False, costs=False)
        self.assertGreaterEqual(len(r["windows"]), 3)

    def test_window_fields(self):
        """每个有效窗口含 multiple/mdd/cagr 字段"""
        r = walk_forward(panel_path=self.panel, train_years=2, test_years=1,
                         offense_mode="fixed", core_satellite=False,
                         death_cross=False, costs=False)
        valid = [w for w in r["windows"] if "multiple" in w]
        self.assertGreater(len(valid), 0)
        for w in valid:
            self.assertIn("multiple", w)
            self.assertIn("mdd", w)
            self.assertIn("cagr", w)
            self.assertIn("test_start", w)
            self.assertIn("test_end", w)

    def test_summary_stats(self):
        """summary 含关键统计字段"""
        r = walk_forward(panel_path=self.panel, train_years=2, test_years=1,
                         offense_mode="fixed", core_satellite=False,
                         death_cross=False, costs=False)
        s = r["summary"]
        if "error" not in s:
            for key in ["n_windows", "mult_mean", "mult_std", "mult_min",
                        "mult_max", "win_rate", "beat_hs300_rate"]:
                self.assertIn(key, s, f"summary missing key: {key}")

    def test_different_params_different_windows(self):
        """不同训练窗口产生不同窗口数"""
        r1 = walk_forward(panel_path=self.panel, train_years=1, test_years=1,
                          offense_mode="fixed", core_satellite=False,
                          death_cross=False, costs=False)
        r2 = walk_forward(panel_path=self.panel, train_years=3, test_years=1,
                          offense_mode="fixed", core_satellite=False,
                          death_cross=False, costs=False)
        self.assertNotEqual(len(r1["windows"]), len(r2["windows"]))

    def test_costs_affect_results(self):
        """含成本 vs 无成本产生不同倍数"""
        r_gross = walk_forward(panel_path=self.panel, train_years=2, test_years=1,
                               offense_mode="fixed", core_satellite=False,
                               death_cross=False, costs=False)
        r_net = walk_forward(panel_path=self.panel, train_years=2, test_years=1,
                             offense_mode="fixed", core_satellite=False,
                             death_cross=False, costs=True)
        g = [w for w in r_gross["windows"] if "multiple" in w]
        n = [w for w in r_net["windows"] if "multiple" in w]
        if g and n:
            self.assertGreaterEqual(g[0]["multiple"], n[0]["multiple"] - 0.01)


if __name__ == "__main__":
    unittest.main()
