# -*- coding: utf-8 -*-
"""
test_cycles.py - 多周期框架测试 (v6.19)

重点保护的正确性属性(与 test_macro_overlay.py 同级):
  1. 前视偏差防护: cycle_phase_at 在 T 日只能看到 available_date <= T 的周期数据。
     这是整个周期层唯一不可妥协的属性 —— 一旦破坏, 回测结果全部作废。
  2. 相位有界: 每个周期相位 ∈ [-1, 1], 合成 regime ∈ [-1, 1]。
  3. 优雅降级: 文件缺失/列缺失时返回中性 0.0, 不抛异常、不改变基线。
  4. 额度守恒: tilt_multiplier 输出 ∈ [TILT_MIN, TILT_MAX], 不产生隐性杠杆。
"""
import os
import sys
import csv
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from cycles.phases import (  # noqa: E402
    load_cycles, cycle_phase_at, composite_regime, tilt_multiplier,
)
from cycles import specs  # noqa: E402

RAW_COLS = ["fed_funds", "t10y2y", "dtwexbgs", "hy_oas", "walcl",
            "vix", "cp", "cpi", "cs"]


def _write_raw(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "available_date"] + RAW_COLS)
        for r in rows:
            w.writerow([r["month"], r["avail"]] + [r.get(c, "") for c in RAW_COLS])


def _write_qual(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cycle_id", "assessment_date", "phase", "note"])
        for r in rows:
            w.writerow([r["cycle_id"], r["avail"], r["phase"], r.get("note", "")])


class TestCyclesLookahead(unittest.TestCase):
    """前视偏差防护 —— 本文件最重要的测试。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.raw = os.path.join(self.tmp, "raw.csv")
        self.qual = os.path.join(self.tmp, "qual.csv")

    def _normal_rows(self):
        # 2019 全年"常态"数据, avail = month + 2 (滞后 2 月)
        rows = []
        for m in range(1, 13):
            y, mo = (2019, m)
            mo += 2
            if mo > 12:
                y += 1
                mo -= 12
            ym = f"2019-{m:02d}"
            rows.append({"month": ym, "avail": f"{y:04d}-{mo:02d}-01",
                         "fed_funds": 2.0, "t10y2y": 0.2, "dtwexbgs": 100.0,
                         "hy_oas": 350.0, "walcl": 4000.0, "vix": 15.0,
                         "cp": 0.0, "cpi": 2.0, "cs": 5.0})
        return rows

    def test_future_row_is_invisible(self):
        """available_date 晚于查询日的行必须完全不可见。"""
        rows = self._normal_rows()
        # 一条极端"未来"数据(avail 2020-03-01): 若被偷看, fed 会被顶到 -1
        rows.append({"month": "2020-01", "avail": "2020-03-01",
                     "fed_funds": 8.0, "t10y2y": -1.5, "dtwexbgs": 130.0,
                     "hy_oas": 1200.0, "walcl": 2000.0, "vix": 60.0,
                     "cp": -10.0, "cpi": 9.0, "cs": 2.0})
        _write_raw(self.raw, rows)
        st = load_cycles(self.raw, None)
        # 查询日 2020-02-15: 只能看到 2019 全年(avail 最晚 2020-02-01), 看不到 2020-03-01
        ph_before = cycle_phase_at(st, "2020-02-15")
        comp_before = composite_regime(st, "2020-02-15")

        # 把"未来"行改成完全相反极端, 再查同一日 —— 结果必须不变(证明未偷看)
        rows[-1].update({"fed_funds": 0.0, "t10y2y": 2.0, "dtwexbgs": 70.0,
                         "hy_oas": 200.0, "walcl": 9000.0, "vix": 10.0,
                         "cp": 20.0, "cpi": 0.5, "cs": 15.0})
        _write_raw(self.raw, rows)
        st2 = load_cycles(self.raw, None)
        ph_after = cycle_phase_at(st2, "2020-02-15")
        comp_after = composite_regime(st2, "2020-02-15")
        self.assertEqual(ph_before, ph_after, "偷看了未来的周期数据 (前视偏差!)")
        self.assertEqual(comp_before, comp_after)

    def test_before_any_data_is_neutral(self):
        """早于所有数据可用日 -> 全部中性 0.0, 不得报错。"""
        rows = self._normal_rows()
        _write_raw(self.raw, rows)
        st = load_cycles(self.raw, None)
        ph = cycle_phase_at(st, "2018-01-01")
        self.assertTrue(all(abs(v) < 1e-9 for v in ph.values()))
        self.assertEqual(composite_regime(st, "2018-01-01"), 0.0)


class TestCyclesBounds(unittest.TestCase):
    """相位有界性。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.raw = os.path.join(self.tmp, "raw.csv")
        self.qual = os.path.join(self.tmp, "qual.csv")

    def test_phases_clipped_to_unit_range(self):
        rows = [{"month": "2020-01", "avail": "2020-03-01",
                 "fed_funds": 99.0, "t10y2y": -9.0, "dtwexbgs": 999.0,
                 "hy_oas": 99999.0, "walcl": 1.0, "vix": 999.0,
                 "cp": -999.0, "cpi": 999.0, "cs": -999.0},
                {"month": "2020-02", "avail": "2020-04-01",
                 "fed_funds": 0.0, "t10y2y": 3.0, "dtwexbgs": 50.0,
                 "hy_oas": 100.0, "walcl": 9000.0, "vix": 9.0,
                 "cp": 30.0, "cpi": 0.1, "cs": 20.0}]
        _write_raw(self.raw, rows)
        st = load_cycles(self.raw, None)
        ph = cycle_phase_at(st, "2020-04-01")
        for k, v in ph.items():
            self.assertGreaterEqual(v, -1.0, f"{k} 越下界")
            self.assertLessEqual(v, 1.0, f"{k} 越上界")
        comp = composite_regime(st, "2020-04-01")
        self.assertGreaterEqual(comp, -1.0)
        self.assertLessEqual(comp, 1.0)

    def test_qualitative_phase_respected(self):
        """定性周期相位直接采用分析师判定(限幅 [-1,1])。"""
        _write_raw(self.raw, [{"month": "2020-01", "avail": "2020-03-01",
                               "fed_funds": 2.0, "t10y2y": 0.2, "dtwexbgs": 100.0,
                               "hy_oas": 350.0, "walcl": 4000.0, "vix": 15.0,
                               "cp": 0.0, "cpi": 2.0, "cs": 5.0}])
        _write_qual(self.qual, [
            {"cycle_id": "semiconductor", "avail": "2020-02-01", "phase": 0.4},
            {"cycle_id": "ai_innovation", "avail": "2020-02-01", "phase": -0.3},
        ])
        st = load_cycles(self.raw, self.qual)
        ph = cycle_phase_at(st, "2020-03-01")
        self.assertAlmostEqual(ph["semiconductor"], 0.4, places=4)
        self.assertAlmostEqual(ph["ai_innovation"], -0.3, places=4)


class TestCyclesGracefulDegradation(unittest.TestCase):
    """缺数据时静默降级, 绝不影响基线。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.raw = os.path.join(self.tmp, "raw.csv")

    def test_missing_file_returns_neutral(self):
        st = load_cycles(os.path.join(self.tmp, "nope.csv"), None)
        self.assertEqual(composite_regime(st, "2020-01-01"), 0.0)

    def test_missing_columns_are_skipped(self):
        """仅含部分量化列 -> 缺失周期归中性, 不报错。"""
        # 至少 3 行且 fed_funds 有趋势, 才能让 z 分数非零
        _write_raw(self.raw, [
            {"month": "2020-01", "avail": "2020-03-01", "fed_funds": 1.0,
             "t10y2y": 0.2, "dtwexbgs": "", "hy_oas": "", "walcl": "",
             "vix": "", "cp": "", "cpi": "", "cs": ""},
            {"month": "2020-02", "avail": "2020-04-01", "fed_funds": 2.0,
             "t10y2y": 0.2, "dtwexbgs": "", "hy_oas": "", "walcl": "",
             "vix": "", "cp": "", "cpi": "", "cs": ""},
            {"month": "2020-03", "avail": "2020-05-01", "fed_funds": 3.0,
             "t10y2y": 0.2, "dtwexbgs": "", "hy_oas": "", "walcl": "",
             "vix": "", "cp": "", "cpi": "", "cs": ""},
        ])
        st = load_cycles(self.raw, None)
        ph = cycle_phase_at(st, "2020-06-01")
        # 有数据的周期给出非零相位, 无数据的周期 = 0
        self.assertNotEqual(ph["fed_rate"], 0.0)
        self.assertEqual(ph["liquidity"], 0.0)
        self.assertEqual(ph["credit"], 0.0)


class TestCyclesTiltBounds(unittest.TestCase):
    """额度守恒: tilt_multiplier 不制造隐性杠杆。"""

    def test_multiplier_within_bounds(self):
        for r in (-1.0, 0.0, 1.0, 5.0, -5.0):
            m = tilt_multiplier(r, specs.DEFAULT_TILT)
            self.assertGreaterEqual(m, specs.TILT_MIN)
            self.assertLessEqual(m, specs.TILT_MAX)

    def test_multiplier_endpoints(self):
        self.assertAlmostEqual(tilt_multiplier(1.0, 0.5), 1.5, places=6)
        self.assertAlmostEqual(tilt_multiplier(-1.0, 0.5), 0.5, places=6)
        self.assertAlmostEqual(tilt_multiplier(0.0, 0.5), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
