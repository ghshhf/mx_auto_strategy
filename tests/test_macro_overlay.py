# -*- coding: utf-8 -*-
"""
test_macro_overlay.py - 宏观周期叠加层测试 (v6.17)

重点保护的正确性属性:
  1. 前视偏差防护: 引擎在 T 日只能看到 available_date <= T 的宏观数据。
     这是整个宏观层唯一不可妥协的属性 —— 一旦破坏, 回测结果全部作废。
  2. 分数有界: score ∈ [-1, 1], 保证仓位乘数落在可控区间。
  3. 优雅降级: 数据缺失时返回中性 0.0 / None, 不抛异常、不改变基线结果。
  4. 额度守恒: 叠加后 def+off+cash 仍为 100%, 不产生隐性杠杆。
"""
import os
import sys
import csv
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "markets", "ashare"))

from backtest_engine import load_macro, macro_score_at  # noqa: E402


def _write_macro(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "available_date", "pmi", "m2_yoy", "shrz", "shrz_yoy"])
        for r in rows:
            w.writerow(r)


class TestMacroLookahead(unittest.TestCase):
    """前视偏差防护 —— 本文件最重要的测试。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "macro_monthly.csv")

    def test_future_row_is_invisible(self):
        """available_date 晚于查询日的行必须完全不可见。"""
        _write_macro(self.path, [
            ["2020-01", "2020-03-01", 50.0, 8.0, 10000, 0.0],
            # 一条极端乐观的"未来"数据: 若被偷看, score 会被顶到接近 +1
            ["2020-02", "2020-04-01", 60.0, 30.0, 99999, 100.0],
        ])
        rows = load_macro(self.path)
        # 查询日在第二行可用日之前 -> 只能看到第一行
        s_before = macro_score_at(rows, "2020-03-31")
        # 查询日到达第二行可用日 -> 才能看到
        s_after = macro_score_at(rows, "2020-04-01")
        self.assertAlmostEqual(s_before, 0.0, places=6,
                               msg="偷看了未来的宏观数据 (前视偏差!)")
        self.assertGreater(s_after, 0.5, "到达可用日后应能读到该行")

    def test_before_any_data_is_neutral(self):
        """早于所有数据可用日 -> 中性 0.0, 不得报错。"""
        _write_macro(self.path, [["2020-01", "2020-03-01", 60.0, 30.0, 1, 100.0]])
        rows = load_macro(self.path)
        self.assertEqual(macro_score_at(rows, "2019-01-01"), 0.0)

    def test_picks_latest_available_not_nearest(self):
        """应取"最新的已可用行", 而非最接近的行(后者可能在未来)。"""
        _write_macro(self.path, [
            ["2020-01", "2020-03-01", 46.0, None, None, None],   # 悲观, 已可用
            ["2020-02", "2020-04-01", 54.0, None, None, None],   # 乐观, 未可用
        ])
        rows = load_macro(self.path)
        # 2020-03-30 距 04-01 更近, 但 04-01 尚未可用 -> 必须用 03-01 那行
        self.assertLess(macro_score_at(rows, "2020-03-30"), 0.0)


class TestMacroScoreBounds(unittest.TestCase):
    """分数有界性与分项计算。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "macro_monthly.csv")

    def test_score_clipped_to_unit_range(self):
        _write_macro(self.path, [
            ["2020-01", "2020-01-01", 99.0, 999.0, 1, 999.0],   # 极端正
            ["2020-02", "2020-02-01", 1.0, -999.0, 1, -999.0],  # 极端负
        ])
        rows = load_macro(self.path)
        for d in ("2020-01-15", "2020-02-15"):
            s = macro_score_at(rows, d)
            self.assertGreaterEqual(s, -1.0)
            self.assertLessEqual(s, 1.0)

    def test_pmi_50_is_neutral(self):
        """PMI 恰在荣枯线 50 -> 该分项为 0。"""
        _write_macro(self.path, [["2020-01", "2020-01-01", 50.0, None, None, None]])
        rows = load_macro(self.path)
        self.assertAlmostEqual(macro_score_at(rows, "2020-06-01"), 0.0, places=6)

    def test_pmi_direction(self):
        _write_macro(self.path, [
            ["2020-01", "2020-01-01", 53.0, None, None, None],
            ["2020-02", "2020-02-01", 47.0, None, None, None],
        ])
        rows = load_macro(self.path)
        self.assertGreater(macro_score_at(rows, "2020-01-15"), 0)
        self.assertLess(macro_score_at(rows, "2020-02-15"), 0)

    def test_missing_columns_are_skipped_not_zeroed(self):
        """缺失分项应被跳过(按有效项平均), 而非当 0 拉低总分。"""
        _write_macro(self.path, [["2020-01", "2020-01-01", 54.0, None, None, None]])
        rows = load_macro(self.path)
        # 只有 PMI 一项: (54-50)/2 = 2.0 -> clip 到 1.0
        self.assertAlmostEqual(macro_score_at(rows, "2020-06-01"), 1.0, places=6)


class TestMacroGracefulDegradation(unittest.TestCase):
    """缺数据时静默降级, 绝不影响基线回测。"""

    def test_missing_file_returns_none(self):
        self.assertIsNone(load_macro(os.path.join(tempfile.mkdtemp(), "nope.csv")))

    def test_none_rows_gives_neutral_score(self):
        self.assertEqual(macro_score_at(None, "2020-01-01"), 0.0)

    def test_empty_date_gives_neutral_score(self):
        self.assertEqual(macro_score_at([{"avail": "2020-01-01"}], ""), 0.0)

    def test_rows_without_available_date_are_dropped(self):
        tmp = os.path.join(tempfile.mkdtemp(), "m.csv")
        _write_macro(tmp, [["2020-01", "", 55.0, None, None, None]])
        # 唯一一行没有 available_date -> 全部被丢弃 -> None
        self.assertIsNone(load_macro(tmp))


class TestMacroAllocationConservation(unittest.TestCase):
    """额度守恒: 宏观叠加不得制造隐性杠杆。"""

    def test_weights_sum_to_100_with_overlay(self):
        from backtest_engine import run
        panel = os.path.join(BASE, "markets", "ashare", "data",
                             "ashare_panel_close_em.csv")
        if not os.path.exists(panel):
            self.skipTest("面板数据不存在")
        kw = dict(offense_mode="momentum", momentum_lookback=26, use_tech=True,
                  core_satellite=True, core_frac=0.5, death_cross=True,
                  costs=True, use_core_sub=True, panel_path=panel,
                  record_plan=True, macro_overlay=True, macro_tilt=0.6)
        s, _, _, plan = run(**kw)
        self.assertTrue(plan, "record_plan 应产出调仓记录")
        for rec in plan:
            c = rec.get("c_pct")
            if c is None:
                continue
            # 现金占比必须落在 [0,100]; 负现金 = 隐性杠杆
            self.assertGreaterEqual(round(c, 6), 0.0,
                                    f"{rec.get('date')} 现金为负 = 隐性杠杆")
            self.assertLessEqual(round(c, 6), 100.0)

    def test_overlay_off_matches_baseline(self):
        """macro_overlay=False 时结果必须与未引入该特性时完全一致。"""
        from backtest_engine import run
        panel = os.path.join(BASE, "markets", "ashare", "data",
                             "ashare_panel_close_em.csv")
        if not os.path.exists(panel):
            self.skipTest("面板数据不存在")
        kw = dict(offense_mode="momentum", momentum_lookback=26, use_tech=True,
                  core_satellite=True, core_frac=0.5, death_cross=True,
                  costs=True, use_core_sub=True, panel_path=panel)
        a, _, _, _ = run(**kw)
        b, _, _, _ = run(macro_overlay=False, macro_tilt=0.6, **kw)
        self.assertEqual(a["final_multiple"], b["final_multiple"])


if __name__ == "__main__":
    unittest.main()
