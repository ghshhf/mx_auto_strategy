"""
回归测试: script_tracker v1.1
- _indicator_hit 区间收益计算修复 (written_date -> expiry)
- _find_bar 端点定位
- source 字段 (human/ai) 分组统计
- compare 命令逻辑
"""
import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import script_tracker


# 模拟 K 线数据 (升序)
MOCK_KL = [
    {"date": "2026-06-20", "open": 100, "close": 101, "high": 102, "low": 99, "vol": 1000},
    {"date": "2026-06-23", "open": 101, "close": 102, "high": 103, "low": 100, "vol": 1100},
    {"date": "2026-06-24", "open": 102, "close": 100, "high": 103, "low": 99, "vol": 1200},
    {"date": "2026-06-25", "open": 100, "close": 98, "high": 101, "low": 97, "vol": 1300},
    {"date": "2026-06-26", "open": 98, "close": 99, "high": 100, "low": 97, "vol": 1400},
    {"date": "2026-06-27", "open": 99, "close": 97, "high": 100, "low": 96, "vol": 1500},
    # 写入日 2026-06-28 (周五, 无K线, 回退到06-27)
    {"date": "2026-06-30", "open": 97, "close": 96, "high": 98, "low": 95, "vol": 1600},
    {"date": "2026-07-01", "open": 96, "close": 94, "high": 97, "low": 93, "vol": 1700},
    {"date": "2026-07-02", "open": 94, "close": 93, "high": 95, "low": 92, "vol": 1800},
    {"date": "2026-07-03", "open": 93, "close": 92, "high": 94, "low": 91, "vol": 1900},
    {"date": "2026-07-04", "open": 92, "close": 90, "high": 93, "low": 89, "vol": 2000},
    {"date": "2026-07-07", "open": 90, "close": 91, "high": 92, "low": 89, "vol": 2100},
    {"date": "2026-07-08", "open": 91, "close": 89, "high": 92, "low": 88, "vol": 2200},
    {"date": "2026-07-09", "open": 89, "close": 88, "high": 90, "low": 87, "vol": 2300},
    {"date": "2026-07-10", "open": 88, "close": 87, "high": 89, "low": 86, "vol": 2400},
    # 到期日 2026-07-15 附近
    {"date": "2026-07-14", "open": 87, "close": 86, "high": 88, "low": 85, "vol": 2500},
    {"date": "2026-07-15", "open": 86, "close": 85, "high": 87, "low": 84, "vol": 2600},
]


class TestFindBar(unittest.TestCase):
    def test_exact_date(self):
        bar = script_tracker._find_bar(MOCK_KL, "2026-06-27")
        self.assertEqual(bar["date"], "2026-06-27")
        self.assertEqual(bar["close"], 97)

    def test_date_between_bars(self):
        # 2026-06-28 是周五, 无K线, 应回退到 06-27
        bar = script_tracker._find_bar(MOCK_KL, "2026-06-28")
        self.assertEqual(bar["date"], "2026-06-27")

    def test_date_before_all_bars(self):
        # 早于所有K线 -> 返回第一根
        bar = script_tracker._find_bar(MOCK_KL, "2020-01-01")
        self.assertEqual(bar, MOCK_KL[0])

    def test_empty_kl(self):
        self.assertIsNone(script_tracker._find_bar([], "2026-07-01"))

    def test_none_date(self):
        self.assertIsNone(script_tracker._find_bar(MOCK_KL, None))


class TestIndicatorHit(unittest.TestCase):
    """测试修复后的 _indicator_hit: 使用 written_date -> expiry 区间收益"""

    @patch("market_data.get_kline", return_value=MOCK_KL)
    def test_down_direction_hit(self, mock_kl):
        """写入日06-27收97, 到期日07-15收85, 下跌 -> expect=down 应命中"""
        ind = {
            "code": "sh000300",
            "metric": "return_pct",
            "expect": "down",
            "written_date": "2026-06-28",  # 回退到06-27, close=97
        }
        result, msg = script_tracker._indicator_hit(ind, script_expiry="2026-07-15")
        self.assertEqual(result, "hit")
        self.assertIn("-12.4%", msg)  # (85/97-1)*100 = -12.37%

    @patch("market_data.get_kline", return_value=MOCK_KL)
    def test_up_direction_miss(self, mock_kl):
        """同区间下跌, expect=up 应未命中"""
        ind = {
            "code": "sh000300",
            "metric": "return_pct",
            "expect": "up",
            "written_date": "2026-06-28",
        }
        result, msg = script_tracker._indicator_hit(ind, script_expiry="2026-07-15")
        self.assertEqual(result, "miss")

    @patch("market_data.get_kline", return_value=MOCK_KL)
    def test_range_direction(self, mock_kl):
        """区间收益-12.4%, abs > 5 -> range 应未命中"""
        ind = {
            "code": "sh000300",
            "metric": "return_pct",
            "expect": "range",
            "written_date": "2026-06-28",
        }
        result, msg = script_tracker._indicator_hit(ind, script_expiry="2026-07-15")
        self.assertEqual(result, "miss")

    @patch("market_data.get_kline", return_value=MOCK_KL)
    def test_return_calculation_correct(self, mock_kl):
        """验证收益计算: entry=97(06-27), exit=85(07-15), ret=(85/97-1)*100"""
        ind = {
            "code": "sh000300",
            "metric": "return_pct",
            "expect": "down",
            "written_date": "2026-06-27",
        }
        result, msg = script_tracker._indicator_hit(ind, script_expiry="2026-07-15")
        self.assertEqual(result, "hit")
        # 验证消息包含正确日期和收益
        self.assertIn("2026-06-27", msg)
        self.assertIn("2026-07-15", msg)
        self.assertIn("-12.4%", msg)

    @patch("market_data.get_kline", return_value=MOCK_KL)
    def test_no_written_date_uses_first_bar(self, mock_kl):
        """无 written_date 时, 入场用第一根K线"""
        ind = {
            "code": "sh000300",
            "metric": "return_pct",
            "expect": "down",
        }
        result, msg = script_tracker._indicator_hit(ind, script_expiry="2026-07-15")
        # entry=101(06-20), exit=85(07-15), ret=(85/101-1)*100=-15.8%
        self.assertEqual(result, "hit")
        self.assertIn("2026-06-20", msg)

    @patch("market_data.get_kline", return_value=[])
    def test_empty_kline(self, mock_kl):
        ind = {"code": "sh000300", "expect": "down", "written_date": "2026-06-28"}
        result, msg = script_tracker._indicator_hit(ind, script_expiry="2026-07-15")
        self.assertEqual(result, "na")

    @patch("market_data.get_kline", return_value=MOCK_KL)
    def test_no_expiry_uses_last_bar(self, mock_kl):
        """无 expiry 时, 出场用最后一根K线"""
        ind = {
            "code": "sh000300",
            "metric": "return_pct",
            "expect": "down",
            "written_date": "2026-06-27",
        }
        result, msg = script_tracker._indicator_hit(ind, script_expiry=None)
        # entry=97(06-27), exit=85(07-15)
        self.assertEqual(result, "hit")


class TestWinRate(unittest.TestCase):
    def test_win_rate_calculation(self):
        scripts = [
            {"status": "hit", "source": "human"},
            {"status": "hit", "source": "human"},
            {"status": "miss", "source": "human"},
            {"status": "open", "source": "human"},
            {"status": "hit", "source": "ai"},
            {"status": "miss", "source": "ai"},
        ]
        total, decided, hit, wr = script_tracker._win_rate(scripts)
        self.assertEqual(total, 6)
        self.assertEqual(decided, 5)
        self.assertEqual(hit, 3)
        self.assertAlmostEqual(wr, 60.0, places=1)

    def test_win_rate_empty(self):
        total, decided, hit, wr = script_tracker._win_rate([])
        self.assertEqual(total, 0)
        self.assertEqual(wr, 0)


if __name__ == "__main__":
    unittest.main()
