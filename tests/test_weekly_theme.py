"""
回归测试: weekly_theme.py 核心路径 (M3/M4/M8)。

覆盖:
  - _week_label: ISO 周标签格式 YYYY-Www (修复旧 strftime 跨年边界 bug)
  - _resolve_defensive: 用户指定优先, 不足按 fallback 列表补齐
  - _elastic_score / _make_elastic_scorer: 默认权重 0.6/0.4 + config 覆盖

全部为纯函数测试, 不发网络请求。
"""
import os
import sys
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import weekly_theme as wt  # noqa: E402


class TestWeekLabel(unittest.TestCase):
    def test_format(self):
        # 2026-08-07 是周五, ISO 周 = 2026-W32
        self.assertEqual(wt._week_label(datetime(2026, 8, 7)), "2026-W32")

    def test_iso_week_padding(self):
        # ISO 周应补零 (旧 strftime %W 不补零且跨年错位)
        # 2026-01-05 是周一; 2026-01-01 是周四属 W01, 故该周为 2026-W02
        self.assertEqual(wt._week_label(datetime(2026, 1, 5)), "2026-W02")

    def test_year_boundary(self):
        # 2025-12-29 周一, ISO 周属于 2026-W01 (跨年边界, 旧实现会错)
        self.assertEqual(wt._week_label(datetime(2025, 12, 29)), "2026-W01")


class TestResolveDefensive(unittest.TestCase):
    def _pool(self):
        # codes -> True 表示在池子里
        return {"601398": True, "600900": True, "512890": True,
                "601939": True, "600519": True, "000001": True}

    def test_user_specified_priority(self):
        overlay = {"defensive_3": ["601398", "600900", "512890"]}
        cfg = {}
        out = wt._resolve_defensive(overlay, self._pool(), cfg)
        self.assertEqual(out, ["601398", "600900", "512890"])

    def test_fallback_fills_missing(self):
        # 用户只指定 1 只在池内的, 其余从 fallback 补
        overlay = {"defensive_3": ["601398"]}
        cfg = {"weekly_theme": {"fallback_defensive": ["600900", "512890", "601939"]}}
        out = wt._resolve_defensive(overlay, self._pool(), cfg)
        self.assertEqual(out, ["601398", "600900", "512890"])

    def test_default_fallback_when_no_config(self):
        # 无 config 时用模块内置默认蓝筹
        overlay = {"defensive_3": []}
        cfg = {}
        out = wt._resolve_defensive(overlay, self._pool(), cfg)
        self.assertEqual(len(out), 3)
        # 默认 fallback 首项 601398 在池内, 应被选中
        self.assertIn("601398", out)

    def test_skips_codes_not_in_pool(self):
        overlay = {"defensive_3": ["999999", "601398"]}  # 999999 不在池
        cfg = {}
        out = wt._resolve_defensive(overlay, self._pool(), cfg)
        self.assertEqual(out[0], "601398")
        self.assertEqual(len(out), 3)
        self.assertNotIn("999999", out)

    def test_max_three(self):
        overlay = {"defensive_3": ["601398", "600900", "512890", "601939", "600519"]}
        cfg = {}
        out = wt._resolve_defensive(overlay, self._pool(), cfg)
        self.assertEqual(len(out), 3)


class TestElasticScore(unittest.TestCase):
    def test_default_weights(self):
        # turnover_w=0.6, chg_w=0.4: 10*0.6 + 5*0.4 = 8.0
        t = {"turnover": 10, "chg": 5}
        self.assertAlmostEqual(wt._elastic_score(t), 8.0)

    def test_negative_chg_clipped(self):
        # max(0, chg) -> 负涨幅不计入
        t = {"turnover": 10, "chg": -5}
        self.assertAlmostEqual(wt._elastic_score(t), 6.0)  # 10*0.6 + 0

    def test_missing_turnover(self):
        t = {"chg": 10}
        self.assertAlmostEqual(wt._elastic_score(t), 4.0)  # 0*0.6 + 10*0.4

    def test_custom_weights(self):
        t = {"turnover": 10, "chg": 5}
        self.assertAlmostEqual(wt._elastic_score(t, 0.5, 0.5), 7.5)  # 5 + 2.5


class TestMakeElasticScorer(unittest.TestCase):
    def test_default_when_no_config(self):
        scorer = wt._make_elastic_scorer({})
        t = {"turnover": 10, "chg": 5}
        self.assertAlmostEqual(scorer(t), 8.0)  # 默认 0.6/0.4

    def test_config_overrides_weights(self):
        cfg = {"weekly_theme": {"elastic_weights": {"turnover": 0.5, "chg": 0.5}}}
        scorer = wt._make_elastic_scorer(cfg)
        t = {"turnover": 10, "chg": 5}
        self.assertAlmostEqual(scorer(t), 7.5)  # 5 + 2.5

    def test_partial_config_uses_defaults(self):
        # 只配 turnover, chg 退回默认 0.4
        cfg = {"weekly_theme": {"elastic_weights": {"turnover": 1.0}}}
        scorer = wt._make_elastic_scorer(cfg)
        t = {"turnover": 10, "chg": 5}
        self.assertAlmostEqual(scorer(t), 12.0)  # 10*1.0 + 5*0.4


if __name__ == "__main__":
    unittest.main()
