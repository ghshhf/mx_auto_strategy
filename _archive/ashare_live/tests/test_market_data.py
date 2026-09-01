"""
回归测试: market_data.py 核心路径 (M10/M11)。

覆盖:
  - _pad: 空码/非字符串/含非数字字符 -> UnknownCodeError; 各市场前缀补全
  - _parse_quote: 字段数不足 -> None; 价格非正 -> None; 港股换手率派生
  - _derive_turnover: A 股用自报值, 港股由成交额/市值派生

全部为纯函数测试, 不发网络请求。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import market_data as md  # noqa: E402


class TestPad(unittest.TestCase):
    def test_empty_raises(self):
        for bad in ["", "   ", None, 123, "  \t "]:
            with self.assertRaises(md.UnknownCodeError, msg=f"code={bad!r}"):
                md._pad(bad)

    def test_non_digit_raises(self):
        for bad in ["60A519", "abc", "600519!"]:
            with self.assertRaises(md.UnknownCodeError):
                md._pad(bad)

    def test_prefixed_passthrough(self):
        for c in ["sh600519", "sz000001", "hk00700"]:
            self.assertEqual(md._pad(c), c)

    def test_a_share_prefix(self):
        self.assertEqual(md._pad("600519"), "sh600519")  # 6 -> sh
        self.assertEqual(md._pad("000001"), "sh000001")  # 指数优先(在 INDEX_PREFIX)
        self.assertEqual(md._pad("300760"), "sz300760")  # 3 -> sz

    def test_etf_prefix(self):
        self.assertEqual(md._pad("510300"), "sh510300")  # 51 -> sh
        self.assertEqual(md._pad("159915"), "sz159915")  # 15 -> sz

    def test_kzz_prefix(self):
        self.assertEqual(md._pad("113050"), "sh113050")  # 沪市转债 11xxxx
        self.assertEqual(md._pad("123158"), "sz123158")  # 深市转债 12xxxx

    def test_hk_five_digit(self):
        self.assertEqual(md._pad("00700"), "hk00700")

    def test_index_prefix(self):
        self.assertEqual(md._pad("000300"), "sh000300")
        self.assertEqual(md._pad("399006"), "sz399006")


def _fake_parts(price="100.0", n=88, **overrides):
    """构造一个 N 字段的腾讯行情字段数组, 默认全空串, 指定位填值。"""
    parts = [""] * n
    parts[1] = "测试名"
    parts[3] = str(price)
    parts[4] = "99.0"
    parts[5] = "100.0"
    for i, v in overrides.items():
        parts[int(i)] = str(v)
    return parts


class TestParseQuote(unittest.TestCase):
    def test_too_few_fields_returns_none(self):
        # A 股需 >=47 字段, 只给 10 个 -> None
        self.assertIsNone(md._parse_quote("sh600519", ["x"] * 10))

    def test_non_positive_price_returns_none(self):
        for bad_price in ["0", "0.0", "-1.5", ""]:
            parts = _fake_parts(price=bad_price)
            self.assertIsNone(md._parse_quote("sh600519", parts),
                              msg=f"price={bad_price!r}")

    def test_a_share_basic(self):
        parts = _fake_parts(price="1688.5", **{"39": "25.3", "38": "0.44"})
        q = md._parse_quote("sh600519", parts)
        self.assertIsNotNone(q)
        self.assertEqual(q["name"], "测试名")
        self.assertAlmostEqual(q["price"], 1688.5)
        self.assertEqual(q["pe_ttm"], 25.3)
        self.assertEqual(q["turnover_pct"], 0.44)
        self.assertEqual(q["market"], "A")

    def test_hk_turnover_derived(self):
        # 港股 [38] 恒 0, 换手率由 [37]成交额/[44]总市值 派生
        # amount=2e9 元, total_mv=2000 亿 -> 2e9/1e8/2000*100 = 1.0%
        parts = _fake_parts(price="350.0", n=78, **{"37": "2000000000", "44": "2000", "38": "0"})
        q = md._parse_quote("hk00700", parts)
        self.assertIsNotNone(q)
        self.assertEqual(q["market"], "HK")
        self.assertAlmostEqual(q["turnover_pct"], 1.0, places=4)
        # 港股 pb 显式 None ([46] 是英文名)
        self.assertIsNone(q["pb"])

    def test_hk_turnover_none_when_missing(self):
        # total_mv 缺失 -> None (selector 走中性回退)
        parts = _fake_parts(price="350.0", n=78, **{"37": "2000000000", "44": ""})
        q = md._parse_quote("hk00700", parts)
        self.assertIsNotNone(q)
        self.assertIsNone(q["turnover_pct"])


class TestDeriveTurnover(unittest.TestCase):
    def test_a_share_uses_self_reported(self):
        def fnum(i):
            return 0.44 if i == 38 else None
        self.assertEqual(md._derive_turnover(fnum, is_hk=False), 0.44)

    def test_hk_derives_from_amount_mv(self):
        def fnum(i):
            return {37: 5e8, 44: 1000.0}.get(i)
        # 5e8 元 / 1e8 / 1000 亿 * 100 = 0.5%
        self.assertAlmostEqual(md._derive_turnover(fnum, is_hk=True), 0.5, places=4)

    def test_hk_none_on_bad_data(self):
        def fnum(i):
            return {37: 5e8, 44: 0}.get(i)  # total_mv=0
        self.assertIsNone(md._derive_turnover(fnum, is_hk=True))


if __name__ == "__main__":
    unittest.main()
