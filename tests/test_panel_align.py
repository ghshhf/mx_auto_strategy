"""panel_align 单元测试 (as-of 前向填充对齐)。

覆盖重点:
  - 基本前向填充 / 精确命中 / 边界(早于源首条)
  - **源键乱序**仍正确 (原 extend_panel_bonds/gld 用 list(dict.keys()) 未排序,
    是本次去重顺带修掉的隐患)
  - 字符串格式化分支 (extend_panel_us_tickers 依赖)
  - 空源 / 空面板
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "markets", "us"))

from panel_align import align_asof, align_asof_str  # noqa: E402


class TestAlignAsOf(unittest.TestCase):
    def test_forward_fill(self):
        """面板日落在两条源数据之间时, 取 <= 该日的最近一条。"""
        src = {"2020-01-03": 10.0, "2020-01-10": 20.0, "2020-01-17": 30.0}
        panel = ["2020-01-03", "2020-01-07", "2020-01-10", "2020-01-16", "2020-01-17"]
        self.assertEqual(
            align_asof(panel, src),
            [10.0, 10.0, 20.0, 20.0, 30.0],
        )

    def test_before_first_source(self):
        """面板日早于源首条 -> 填 empty (默认 None), 即"上市前"。"""
        src = {"2020-01-10": 20.0}
        panel = ["2020-01-01", "2020-01-03", "2020-01-10"]
        self.assertEqual(align_asof(panel, src), [None, None, 20.0])
        self.assertEqual(align_asof(panel, src, empty=""), ["", "", 20.0])

    def test_custom_empty_sentinel(self):
        src = {"2020-01-10": 1.5}
        self.assertEqual(align_asof(["2020-01-01"], src, empty=0), [0])

    def test_unsorted_source_keys(self):
        """源键乱序时结果必须与有序时一致。

        这是原 extend_panel_bonds.py / extend_panel_gld.py 的隐患:
        它们用 list(src_map.keys()) 而不排序, 依赖插入序恰好有序。
        """
        ordered = {"2020-01-03": 1.0, "2020-01-10": 2.0, "2020-01-17": 3.0}
        # 故意乱序插入
        shuffled = {"2020-01-10": 2.0, "2020-01-17": 3.0, "2020-01-03": 1.0}
        panel = ["2020-01-03", "2020-01-08", "2020-01-10", "2020-01-20"]
        self.assertEqual(align_asof(panel, ordered), align_asof(panel, shuffled))

    def test_exact_match_takes_that_day(self):
        """面板日与源日期相同时, 取该日(而非前一日)。"""
        src = {"2020-01-03": 1.0, "2020-01-10": 2.0}
        self.assertEqual(align_asof(["2020-01-10"], src), [2.0])

    def test_empty_source(self):
        self.assertEqual(align_asof(["2020-01-03"], {}), [None])

    def test_empty_panel(self):
        self.assertEqual(align_asof([], {"2020-01-03": 1.0}), [])

    def test_length_matches_panel(self):
        src = {f"2020-01-{d:02d}": float(d) for d in range(1, 29, 7)}
        panel = [f"2020-02-{d:02d}" for d in range(1, 29)]
        self.assertEqual(len(align_asof(panel, src)), len(panel))


class TestAlignAsOfStr(unittest.TestCase):
    def test_default_format_and_empty(self):
        src = {"2020-01-10": 123.456789}
        panel = ["2020-01-01", "2020-01-10"]
        # 默认 5 位小数, 上市前空串 (extend_panel_us_tickers 的契约)
        self.assertEqual(align_asof_str(panel, src), ["", "123.45679"])

    def test_custom_format(self):
        src = {"2020-01-10": 123.456789}
        self.assertEqual(align_asof_str(["2020-01-10"], src, fmt="%.2f"), ["123.46"])

    def test_matches_scalar_variant(self):
        """字符串版应与原值版取到同一条记录。"""
        src = {"2020-01-03": 1.0, "2020-01-10": 2.0}
        panel = ["2020-01-05", "2020-01-10", "2020-01-11"]
        raw = align_asof(panel, src)
        s = align_asof_str(panel, src, fmt="%.1f")
        self.assertEqual(s, ["%.1f" % v for v in raw])


if __name__ == "__main__":
    unittest.main()
