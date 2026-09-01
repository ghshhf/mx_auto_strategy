"""回归测试: selector.apply_trend_filter 趋势过滤安全阀 (纯函数)。"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import selector  # noqa: E402


def _d(code, trend_ok):
    return {"code": code, "final_score": 1.0, "_trend_ok": trend_ok}


class TestTrendFilter(unittest.TestCase):
    def test_keeps_uptrend_only(self):
        scored = [_d("A", True), _d("B", False), _d("C", True)]
        out = selector.apply_trend_filter(scored, top_n=1, enabled=True)
        self.assertEqual([d["code"] for d in out], ["A", "C"])

    def test_safety_valve_falls_back_when_too_few(self):
        # 过滤后不足 top_n -> 必须退回原列表, 不强求
        scored = [_d("A", True), _d("B", False), _d("C", False)]
        out = selector.apply_trend_filter(scored, top_n=2, enabled=True)
        self.assertEqual([d["code"] for d in out], ["A", "B", "C"])

    def test_disabled_returns_original(self):
        scored = [_d("A", True), _d("B", False)]
        out = selector.apply_trend_filter(scored, top_n=1, enabled=False)
        self.assertEqual(len(out), 2)

    def test_no_filter_when_under_topn(self):
        scored = [_d("A", True)]
        out = selector.apply_trend_filter(scored, top_n=3, enabled=True)
        self.assertEqual(len(out), 1)

    def test_missing_trend_flag_treated_as_pass(self):
        # A 缺 _trend_ok -> 视为通过(数据不足不过滤); B 显式 False -> 被滤掉
        scored = [{"code": "A", "final_score": 1.0}, _d("B", False)]
        out = selector.apply_trend_filter(scored, top_n=1, enabled=True)
        self.assertEqual([d["code"] for d in out], ["A"])


if __name__ == "__main__":
    unittest.main()
