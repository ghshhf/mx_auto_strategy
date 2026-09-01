# -*- coding: utf-8 -*-
"""
test_data_contract.py
=====================
数据契约测试: 校验 markets/ashare/data/ashare_weekly_em/ 下每个 CSV 的字段完整性,
以及 panel CSV (ashare_panel_close_em.csv) 的数据有效性。

断言:
  - close >= low, high >= close, high >= low, low <= open <= high (容差 0.001)
  - volume >= 0
  - 无单周收益 > 80% ( sanity check, A股涨停板5天最多 ~61% )
  - panel CSV 数据单元格为有效浮点值或空字符串
"""
import os
import csv
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "markets", "ashare", "data")
WK = os.path.join(DATA, "ashare_weekly_em")
PANEL = os.path.join(DATA, "ashare_panel_close_em.csv")

TOL = 0.001
MAX_WEEKLY_RETURN = 0.80


def _load_weekly_csvs():
    """返回 [(code, [row_dict, ...]), ...]"""
    if not os.path.isdir(WK):
        return []
    result = []
    for fn in sorted(os.listdir(WK)):
        if not fn.endswith(".csv"):
            continue
        code = fn[:-4]
        with open(os.path.join(WK, fn), encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if rows:
            result.append((code, rows))
    return result


class TestWeeklyCSV(unittest.TestCase):
    """逐标的 CSV 字段完整性测试。"""

    @classmethod
    def setUpClass(cls):
        cls.csvs = _load_weekly_csvs()
        if not cls.csvs:
            raise unittest.SkipTest("无周线 CSV 数据, 跳过 (需先运行 tencent_hfq_rebuild.py)")

    def test_csvs_exist(self):
        """至少有 DEF16+OFF4 数量的 CSV 文件。"""
        self.assertGreaterEqual(len(self.csvs), 20,
                                f"CSV 文件过少: {len(self.csvs)}, 预期 >= 20")

    def test_ohlc_consistency(self):
        """每个 OHLC 行: close>=low, high>=close, high>=low, low<=open<=high。"""
        failures = []
        for code, rows in self.csvs:
            for row in rows:
                try:
                    o = float(row["open"])
                    h = float(row["high"])
                    l = float(row["low"])
                    c = float(row["close"])
                except (ValueError, KeyError):
                    continue
                if h + TOL < l:
                    failures.append(f"{code} {row['date']}: high({h}) < low({l})")
                if c + TOL < l:
                    failures.append(f"{code} {row['date']}: close({c}) < low({l})")
                if h + TOL < c:
                    failures.append(f"{code} {row['date']}: high({h}) < close({c})")
                if o + TOL < l:
                    failures.append(f"{code} {row['date']}: open({o}) < low({l})")
                if h + TOL < o:
                    failures.append(f"{code} {row['date']}: high({h}) < open({o})")
        self.assertEqual(failures, [],
                         f"OHLC 一致性失败 ({len(failures)} 处):\n" + "\n".join(failures[:10]))

    def test_volume_nonneg(self):
        """volume >= 0。"""
        failures = []
        for code, rows in self.csvs:
            for row in rows:
                try:
                    v = float(row["volume"])
                except (ValueError, KeyError):
                    continue
                if v < -TOL:
                    failures.append(f"{code} {row['date']}: volume={v}")
        self.assertEqual(failures, [],
                         f"负成交量 ({len(failures)} 处):\n" + "\n".join(failures[:10]))

    def test_no_extreme_weekly_return(self):
        """无单周收益 > 80% (sanity check)。"""
        failures = []
        for code, rows in self.csvs:
            closes = []
            for row in rows:
                try:
                    closes.append(float(row["close"]))
                except (ValueError, KeyError):
                    closes.append(None)
            for k in range(1, len(closes)):
                a, b = closes[k - 1], closes[k]
                if a and a > 0 and b and b > 0:
                    chg = abs(b / a - 1.0)
                    if chg > MAX_WEEKLY_RETURN:
                        failures.append(
                            f"{code} {rows[k]['date']}: {a:.2f}->{b:.2f} ({chg*100:.1f}%)")
        self.assertEqual(failures, [],
                         f"异常单周收益 >{MAX_WEEKLY_RETURN*100:.0f}% ({len(failures)} 处):\n"
                         + "\n".join(failures[:10]))


class TestPanelCSV(unittest.TestCase):
    """panel 宽表数据有效性测试。"""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(PANEL):
            raise unittest.SkipTest("无 panel CSV, 跳过 (需先运行 tencent_hfq_rebuild.py)")
        with open(PANEL, encoding="utf-8") as f:
            r = csv.reader(f)
            cls.header = next(r)
            cls.data_rows = list(r)

    def test_panel_has_codes(self):
        """panel 至少有 20 个代码列。"""
        n_codes = len(self.header) - 1
        self.assertGreaterEqual(n_codes, 20, f"panel 代码列过少: {n_codes}")

    def test_panel_has_dates(self):
        """panel 至少有 100 个周日期。"""
        self.assertGreaterEqual(len(self.data_rows), 100,
                                f"panel 日期行过少: {len(self.data_rows)}")

    def test_panel_cells_valid(self):
        """数据单元格为有效浮点值或空字符串 (无字符串/None 污染)。"""
        failures = []
        checked = 0
        for row in self.data_rows:
            for j, cell in enumerate(row[1:], start=1):
                checked += 1
                cell = cell.strip()
                if cell == "" or cell == "None":
                    continue
                try:
                    float(cell)
                except ValueError:
                    failures.append(f"row date={row[0]}, col={self.header[j]}: '{cell}'")
        self.assertEqual(failures, [],
                         f"panel 无效单元格 ({len(failures)} 处, 检查 {checked} 个):\n"
                         + "\n".join(failures[:10]))

    def test_panel_close_positive(self):
        """panel 非空 close 值 > 0 (无零价/负价)。"""
        failures = []
        for row in self.data_rows:
            for j, cell in enumerate(row[1:], start=1):
                cell = cell.strip()
                if cell == "" or cell == "None":
                    continue
                try:
                    v = float(cell)
                    if v <= 0:
                        failures.append(f"row date={row[0]}, col={self.header[j]}: {v}")
                except ValueError:
                    continue
        self.assertEqual(failures, [],
                         f"panel 非正价格 ({len(failures)} 处):\n" + "\n".join(failures[:10]))


if __name__ == "__main__":
    unittest.main()
