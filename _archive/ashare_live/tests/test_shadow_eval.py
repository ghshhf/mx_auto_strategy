"""
回归测试: shadow_eval A/B 评估框架
- record() 快照格式与差异计算
- evaluate() 前向收益计算 (mock K线)
- report() 汇总输出
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import shadow_eval


# 模拟 K 线 (升序, 20根约1个月)
def _make_mock_kl(start_price=100, days=30, trend=-0.5, start_date=None):
    """生成模拟K线, trend=每日涨跌幅%

    start_date 必须覆盖被测快照的日期，否则 _forward_return 会把最后一根 K 线
    同时当作入场与出场，收益恒为 0，使断言失真（曾导致 evaluate 测试假通过）。
    """
    kl = []
    price = start_price
    from datetime import datetime, timedelta
    d = start_date or datetime(2026, 6, 1)
    for i in range(days):
        price *= (1 + trend / 100)
        # 跳过周末
        while d.weekday() >= 5:
            d += timedelta(days=1)
        kl.append({
            "date": d.strftime("%Y-%m-%d"),
            "open": round(price * 0.99, 2),
            "close": round(price, 2),
            "high": round(price * 1.01, 2),
            "low": round(price * 0.98, 2),
            "vol": 1000 + i * 10,
        })
        d += timedelta(days=1)
    return kl


class TestRecord(unittest.TestCase):
    """测试 record() 快照记录"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_file = shadow_eval.SNAPSHOT_FILE
        shadow_eval.SNAPSHOT_FILE = os.path.join(self.tmpdir, "test_snapshots.jsonl")
        shadow_eval.RECORD_ROOT = self.tmpdir

    def tearDown(self):
        shadow_eval.SNAPSHOT_FILE = self._orig_file
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_record_basic(self):
        rule_ranking = [
            {"code": "600036", "name": "招行", "final_score": 0.85},
            {"code": "601398", "name": "工行", "final_score": 0.80},
            {"code": "601288", "name": "农行", "final_score": 0.75},
        ]
        ai_ranking = [
            {"code": "600036", "name": "招行", "final_score": 0.85, "ai_adjusted_score": 0.94, "ai_multiplier": 1.1},
            {"code": "601398", "name": "工行", "final_score": 0.80, "ai_adjusted_score": 0.88, "ai_multiplier": 1.1},
            {"code": "601328", "name": "交行", "final_score": 0.70, "ai_adjusted_score": 0.84, "ai_multiplier": 1.2},
        ]
        snap = shadow_eval.record("defensive", rule_ranking, ai_ranking, top_n=3)

        self.assertEqual(snap["tag"], "defensive")
        self.assertEqual(len(snap["rule_top"]), 3)
        self.assertEqual(len(snap["ai_top"]), 3)
        self.assertIn("600036", snap["overlap"])
        self.assertIn("601328", snap["ai_only"])
        self.assertIn("601288", snap["rule_only"])
        self.assertFalse(snap["evaluated"])

    def test_record_no_diff(self):
        """规则和AI排序完全一致时, ai_only 和 rule_only 为空"""
        ranking = [
            {"code": "600036", "final_score": 0.85, "ai_adjusted_score": 0.85, "ai_multiplier": 1.0},
            {"code": "601398", "final_score": 0.80, "ai_adjusted_score": 0.80, "ai_multiplier": 1.0},
        ]
        snap = shadow_eval.record("defensive", ranking, ranking, top_n=2)
        self.assertEqual(len(snap["overlap"]), 2)
        self.assertEqual(len(snap["ai_only"]), 0)
        self.assertEqual(len(snap["rule_only"]), 0)

    def test_record_persistence(self):
        """快照写入文件并可读回"""
        ranking = [{"code": "600036", "final_score": 0.85}]
        shadow_eval.record("defensive", ranking, ranking, top_n=1)
        snaps = shadow_eval._load_snapshots()
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]["rule_top"][0]["code"], "600036")


class TestForwardReturn(unittest.TestCase):
    """测试 _forward_return 前向收益计算"""

    MOCK_KL = _make_mock_kl(start_price=100, days=30, trend=-0.5)

    @patch("market_data.get_kline", return_value=MOCK_KL)
    def test_basic_forward_return(self, mock_kl):
        """从第0根到第20根, trend=-0.5%/天"""
        ret, err = shadow_eval._forward_return("sh000300", "2026-06-01", 20)
        self.assertIsNone(err)
        # 20天后: 100 * (0.995)^20 = 90.46, ret = -9.54%
        self.assertAlmostEqual(ret, -9.54, places=1)

    @patch("market_data.get_kline", return_value=MOCK_KL)
    def test_horizon_exceeds_data(self, mock_kl):
        """horizon 超过K线数量时用最后一根"""
        ret, err = shadow_eval._forward_return("sh000300", "2026-06-01", 100)
        self.assertIsNone(err)
        # 30根K线, 用最后一根: 100 * (0.995)^30 = 86.09, ret = -13.91%
        self.assertAlmostEqual(ret, -13.91, places=0)

    @patch("market_data.get_kline", return_value=[])
    def test_empty_kline(self, mock_kl):
        ret, err = shadow_eval._forward_return("sh000300", "2026-06-01", 20)
        self.assertIsNotNone(err)
        self.assertIsNone(ret)


class TestEvaluate(unittest.TestCase):
    """测试 evaluate() 评估逻辑"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_file = shadow_eval.SNAPSHOT_FILE
        shadow_eval.SNAPSHOT_FILE = os.path.join(self.tmpdir, "test_eval.jsonl")
        shadow_eval.RECORD_ROOT = self.tmpdir

    def tearDown(self):
        shadow_eval.SNAPSHOT_FILE = self._orig_file
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("market_data.get_kline")
    def test_evaluate_marks_evaluated(self, mock_kl):
        """评估后快照 evaluated=True, eval 非空"""
        # 快照日期：45 天前，既满足 horizon 窗口，也作为 mock K 线的起点
        from datetime import datetime, timedelta
        old_dt = datetime.now() - timedelta(days=45)

        # rule 标的涨, ai 标的跌
        kl_up = _make_mock_kl(start_price=100, days=30, trend=0.5, start_date=old_dt)
        kl_down = _make_mock_kl(start_price=100, days=30, trend=-0.5, start_date=old_dt)

        def mock_get_kline(code, *a, **kw):
            if "up" in code:
                return kl_up
            return kl_down

        mock_kl.side_effect = mock_get_kline

        # 创建一条足够旧的快照
        rule = [{"code": "up001", "final_score": 0.85}]
        ai = [{"code": "down001", "final_score": 0.80, "ai_adjusted_score": 0.90, "ai_multiplier": 1.2}]
        shadow_eval.record("defensive", rule, ai, top_n=1)

        # 手动设置快照日期为45天前
        snaps = shadow_eval._load_snapshots()
        old_date = old_dt.strftime("%Y-%m-%d")
        old_ts = old_dt.strftime("%Y-%m-%d %H:%M:%S")
        snaps[0]["date"] = old_date
        snaps[0]["ts"] = old_ts
        shadow_eval._save_snapshots(snaps)

        shadow_eval.evaluate(horizon=20)

        snaps = shadow_eval._load_snapshots()
        self.assertTrue(snaps[0]["evaluated"])
        self.assertIsNotNone(snaps[0]["eval"])
        self.assertFalse(snaps[0]["eval"]["ai_wins"])  # AI选了跌的, 规则选了涨的
        self.assertLess(snaps[0]["eval"]["diff"], 0)   # 差额必须为负, 否则是 0 收益假通过

    @patch("market_data.get_kline")
    def test_evaluate_ai_wins(self, mock_kl):
        """AI选了涨的, 规则选了跌的 -> AI胜"""
        from datetime import datetime, timedelta
        old_dt = datetime.now() - timedelta(days=45)

        kl_up = _make_mock_kl(start_price=100, days=30, trend=0.5, start_date=old_dt)
        kl_down = _make_mock_kl(start_price=100, days=30, trend=-0.5, start_date=old_dt)

        def mock_get_kline(code, *a, **kw):
            if "up" in code:
                return kl_up
            return kl_down

        mock_kl.side_effect = mock_get_kline

        rule = [{"code": "down001", "final_score": 0.85}]
        ai = [{"code": "up001", "final_score": 0.80, "ai_adjusted_score": 0.90, "ai_multiplier": 1.2}]
        shadow_eval.record("defensive", rule, ai, top_n=1)

        snaps = shadow_eval._load_snapshots()
        from datetime import datetime
        old_date = old_dt.strftime("%Y-%m-%d")
        snaps[0]["date"] = old_date
        shadow_eval._save_snapshots(snaps)

        shadow_eval.evaluate(horizon=20)

        snaps = shadow_eval._load_snapshots()
        self.assertTrue(snaps[0]["eval"]["ai_wins"])
        self.assertGreater(snaps[0]["eval"]["diff"], 0)


class TestPromotionGate(unittest.TestCase):
    """测试 ai_promotion_gate 门槛检查"""

    def test_gate_config_defaults(self):
        import ai_promotion_gate
        cfg = {"ai_overlay": {}}
        gate = ai_promotion_gate._get_gate_cfg(cfg)
        self.assertEqual(gate["min_samples"], 20)
        self.assertEqual(gate["min_ai_win_rate"], 55.0)
        self.assertEqual(gate["min_avg_outperformance"], 1.0)

    def test_gate_config_override(self):
        import ai_promotion_gate
        cfg = {"ai_overlay": {"promotion_gate": {"min_samples": 5}}}
        gate = ai_promotion_gate._get_gate_cfg(cfg)
        self.assertEqual(gate["min_samples"], 5)
        # 其他保持默认
        self.assertEqual(gate["min_ai_win_rate"], 55.0)


if __name__ == "__main__":
    unittest.main()
