"""
回归测试: instrument.py 品种元数据单一真相源 (T01)。

覆盖:
  - market_of 各代码形态推断 + meta 显式优先 + 存量缓存无 market 字段的回退
  - lot_of 三级优先级 (per_code > lot_rules[market].lot > default_lot)
  - 港股未登记每手股数 -> UnknownLotError (拒单, 不猜 100)
  - round_qty floor/ceil/nearest 与边界输入
  - 分市场交易时段 (A 09:30-11:30,13:00-15:00 / HK 09:30-12:00,13:00-16:00)
  - is_tradable 降级开关

全部为纯函数测试, 不发网络请求。
"""
import os
import sys
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import instrument  # noqa: E402


def _cfg():
    """测试专用配置: 与 strategy_config.json 的 instrument 段保持同构。"""
    return {
        "instrument": {
            "default_lot": 100,
            "strict_unknown_lot": True,
            "lot_rules": {
                "A": {"lot": 100, "unit": "股", "sessions": "09:30-11:30,13:00-15:00"},
                "ETF": {"lot": 100, "unit": "份", "sessions": "09:30-11:30,13:00-15:00"},
                "KZZ": {"lot": 10, "unit": "张", "sessions": "09:30-11:30,13:00-15:00"},
                "HK": {"lot": None, "unit": "股", "sessions": "09:30-12:00,13:00-16:00"},
            },
            "per_code": {
                "_comment": "说明键, 必须被忽略",
                "00700": 100,
                "03690": 100,
                "01810": 200,
                "00941": 500,
                "00388": 100,
            },
        },
        "market": {"tradable_markets": ["A", "ETF", "KZZ"]},
    }


class TestMarketOf(unittest.TestCase):
    def test_hk_five_digit(self):
        for code in ["00700", "01810", "00941", "00388", "03690"]:
            self.assertEqual(instrument.market_of(code), "HK", code)

    def test_hk_prefixed(self):
        self.assertEqual(instrument.market_of("hk00700"), "HK")
        self.assertEqual(instrument.market_of("HK00388"), "HK")

    def test_kzz_11_and_12(self):
        for code in ["113050", "113052", "110059", "123456", "127045", "128136"]:
            self.assertEqual(instrument.market_of(code), "KZZ", code)

    def test_etf(self):
        for code in ["510300", "512880", "159915", "588000", "561000"]:
            self.assertEqual(instrument.market_of(code), "ETF", code)

    def test_a_share(self):
        for code in ["600519", "601398", "000858", "300760", "002821"]:
            self.assertEqual(instrument.market_of(code), "A", code)

    def test_a_share_with_exchange_prefix(self):
        self.assertEqual(instrument.market_of("sh600519"), "A")
        self.assertEqual(instrument.market_of("sz000001"), "A")
        self.assertEqual(instrument.market_of("sh113050"), "KZZ")

    def test_meta_market_takes_priority(self):
        # candidate_pool 显式标注优先于形态推断
        self.assertEqual(instrument.market_of("600519", {"market": "ETF"}), "ETF")
        self.assertEqual(instrument.market_of("113050", {"market": "KZZ"}), "KZZ")

    def test_meta_invalid_market_falls_back_to_shape(self):
        self.assertEqual(instrument.market_of("113050", {"market": "US"}), "KZZ")
        self.assertEqual(instrument.market_of("00700", {"market": ""}), "HK")

    def test_legacy_cost_basis_without_market(self):
        # 存量 .cost_basis.json 无 market 字段 -> 形态推断, 无需数据迁移
        legacy = {"price": 118.5, "qty": 150, "sold_ratio": 0.0}
        self.assertEqual(instrument.market_of("113050", legacy), "KZZ")
        self.assertEqual(instrument.market_of("600519", legacy), "A")

    def test_garbage_input_defaults_to_a(self):
        self.assertEqual(instrument.market_of(""), "A")
        self.assertEqual(instrument.market_of(None), "A")
        self.assertEqual(instrument.market_of("ABCDEF"), "A")


class TestLotOf(unittest.TestCase):
    def setUp(self):
        self.cfg = _cfg()

    def test_per_code_wins_for_hk(self):
        self.assertEqual(instrument.lot_of("01810", self.cfg), 200)
        self.assertEqual(instrument.lot_of("00941", self.cfg), 500)
        self.assertEqual(instrument.lot_of("00700", self.cfg), 100)
        self.assertEqual(instrument.lot_of("00388", self.cfg), 100)
        self.assertEqual(instrument.lot_of("03690", self.cfg), 100)

    def test_market_rule_for_kzz(self):
        self.assertEqual(instrument.lot_of("113050", self.cfg), 10)
        self.assertEqual(instrument.lot_of("123456", self.cfg), 10)

    def test_market_rule_for_a_and_etf(self):
        self.assertEqual(instrument.lot_of("600519", self.cfg), 100)
        self.assertEqual(instrument.lot_of("510300", self.cfg), 100)

    def test_per_code_overrides_market_rule(self):
        cfg = _cfg()
        cfg["instrument"]["per_code"]["113050"] = 20
        self.assertEqual(instrument.lot_of("113050", cfg), 20)

    def test_comment_key_in_per_code_is_ignored(self):
        # per_code 里的 "_comment" 不得被当成代码解析
        self.assertNotIn("_comment", instrument._per_code_map(_cfg()["instrument"]))

    def test_unregistered_hk_raises_in_strict_mode(self):
        with self.assertRaises(instrument.UnknownLotError):
            instrument.lot_of("00005", self.cfg)   # 汇丰, 未登记
        with self.assertRaises(instrument.UnknownLotError):
            instrument.lot_of("09988", self.cfg)   # 阿里巴巴-W, 未登记

    def test_unregistered_hk_falls_back_when_not_strict(self):
        cfg = _cfg()
        cfg["instrument"]["strict_unknown_lot"] = False
        self.assertEqual(instrument.lot_of("00005", cfg), 100)

    def test_explicit_market_argument_respected(self):
        # 显式传 market 时不再走形态推断
        self.assertEqual(instrument.lot_of("600519", self.cfg, market="KZZ"), 10)

    def test_assert_lot_known(self):
        self.assertIsNone(instrument.assert_lot_known("01810", self.cfg))
        with self.assertRaises(instrument.UnknownLotError):
            instrument.assert_lot_known("00005", self.cfg)


class TestRoundQty(unittest.TestCase):
    def setUp(self):
        self.cfg = _cfg()

    def test_kzz_leak_scenarios(self):
        """转债漏钱洞两个经典场景: 旧代码 //100*100 分别得 0 与 100。"""
        self.assertEqual(instrument.round_qty(60, "113050", self.cfg), 60)
        self.assertEqual(instrument.round_qty(150, "113050", self.cfg), 150)
        self.assertEqual(instrument.round_qty(155, "113050", self.cfg), 150)
        self.assertEqual(instrument.round_qty(9, "113050", self.cfg), 0)

    def test_hk_lot_rounding(self):
        self.assertEqual(instrument.round_qty(650, "01810", self.cfg), 600)   # lot=200
        self.assertEqual(instrument.round_qty(1200, "00941", self.cfg), 1000)  # lot=500
        self.assertEqual(instrument.round_qty(499, "00941", self.cfg), 0)
        self.assertEqual(instrument.round_qty(350, "00700", self.cfg), 300)   # lot=100

    def test_a_share_behaviour_unchanged(self):
        """A 股必须与改造前 int(q // 100 * 100) 逐位一致(防回归)。"""
        for q in [0, 1, 99, 100, 101, 650, 999, 1000, 123456, 12345.67]:
            self.assertEqual(
                instrument.round_qty(q, "600519", self.cfg),
                int(q // 100 * 100),
                f"A 股取整回归失败 qty={q}",
            )

    def test_etf_behaviour_unchanged(self):
        for q in [0, 99, 100, 1050, 9999]:
            self.assertEqual(instrument.round_qty(q, "510300", self.cfg), int(q // 100 * 100))

    def test_modes(self):
        self.assertEqual(instrument.round_qty(155, "113050", self.cfg, mode="floor"), 150)
        self.assertEqual(instrument.round_qty(155, "113050", self.cfg, mode="ceil"), 160)
        self.assertEqual(instrument.round_qty(155, "113050", self.cfg, mode="nearest"), 160)
        self.assertEqual(instrument.round_qty(154, "113050", self.cfg, mode="nearest"), 150)
        # 恰好整手时 ceil 不应多进一手
        self.assertEqual(instrument.round_qty(150, "113050", self.cfg, mode="ceil"), 150)

    def test_float_precision(self):
        # cash/price 常产生浮点毛刺, 不能因 1e-12 误差少一手
        self.assertEqual(instrument.round_qty(100.0000000001, "600519", self.cfg), 100)
        self.assertEqual(instrument.round_qty(99.9999999999, "600519", self.cfg), 100)

    def test_non_positive_and_garbage(self):
        self.assertEqual(instrument.round_qty(0, "600519", self.cfg), 0)
        self.assertEqual(instrument.round_qty(-500, "600519", self.cfg), 0)
        self.assertEqual(instrument.round_qty(None, "600519", self.cfg), 0)
        self.assertEqual(instrument.round_qty("abc", "600519", self.cfg), 0)
        self.assertEqual(instrument.round_qty(float("nan"), "600519", self.cfg), 0)

    def test_unregistered_hk_raises(self):
        with self.assertRaises(instrument.UnknownLotError):
            instrument.round_qty(1000, "00005", self.cfg)


class TestSessions(unittest.TestCase):
    def setUp(self):
        self.cfg = _cfg()

    def test_parse_sessions(self):
        out = instrument.parse_sessions("09:30-12:00,13:00-16:00")
        self.assertEqual(len(out), 2)
        self.assertEqual((out[0][0].hour, out[0][0].minute), (9, 30))
        self.assertEqual((out[1][1].hour, out[1][1].minute), (16, 0))

    def test_parse_sessions_bad_input_falls_back(self):
        out = instrument.parse_sessions("garbage")
        self.assertEqual(out, instrument.parse_sessions(instrument.DEFAULT_SESSIONS))

    def test_session_of(self):
        self.assertEqual(instrument.session_of("A", self.cfg), "09:30-11:30,13:00-15:00")
        self.assertEqual(instrument.session_of("HK", self.cfg), "09:30-12:00,13:00-16:00")

    def test_a_share_window(self):
        # 2026-08-03 是周一
        self.assertTrue(instrument.is_trade_time("A", datetime(2026, 8, 3, 10, 0), self.cfg))
        self.assertTrue(instrument.is_trade_time("A", datetime(2026, 8, 3, 14, 59), self.cfg))
        self.assertFalse(instrument.is_trade_time("A", datetime(2026, 8, 3, 11, 45), self.cfg))
        self.assertFalse(instrument.is_trade_time("A", datetime(2026, 8, 3, 15, 30), self.cfg))

    def test_hk_extra_90_minutes(self):
        """港股 11:30-12:00 与 15:00-16:00 共 1.5h, 改造前被 A 股时段误判为闭市。"""
        self.assertTrue(instrument.is_trade_time("HK", datetime(2026, 8, 3, 11, 45), self.cfg))
        self.assertTrue(instrument.is_trade_time("HK", datetime(2026, 8, 3, 15, 30), self.cfg))
        self.assertFalse(instrument.is_trade_time("HK", datetime(2026, 8, 3, 12, 30), self.cfg))
        self.assertFalse(instrument.is_trade_time("HK", datetime(2026, 8, 3, 16, 30), self.cfg))

    def test_weekend_closed_for_all_markets(self):
        # 2026-08-08 周六 / 2026-08-09 周日
        for mk in instrument.VALID_MARKETS:
            self.assertFalse(instrument.is_trade_time(mk, datetime(2026, 8, 8, 10, 0), self.cfg))
            self.assertFalse(instrument.is_trade_time(mk, datetime(2026, 8, 9, 10, 0), self.cfg))


class TestTradableSwitch(unittest.TestCase):
    def setUp(self):
        self.cfg = _cfg()

    def test_hk_not_tradable_by_default(self):
        """本期只做 A(行情+选股): 港股不进下单执行路径。"""
        self.assertFalse(instrument.is_tradable("HK", self.cfg))

    def test_a_etf_kzz_tradable(self):
        for mk in ["A", "ETF", "KZZ"]:
            self.assertTrue(instrument.is_tradable(mk, self.cfg), mk)

    def test_enable_hk_is_one_line(self):
        cfg = _cfg()
        cfg["market"]["tradable_markets"] = ["A", "ETF", "KZZ", "HK"]
        self.assertTrue(instrument.is_tradable("HK", cfg))

    def test_missing_config_means_all_tradable(self):
        # 向后兼容: 老配置没有 tradable_markets 时不应意外禁掉 A 股下单
        self.assertTrue(instrument.is_tradable("A", {"market": {}}))
        self.assertTrue(instrument.is_tradable("HK", {}))


class TestRealConfigConsistency(unittest.TestCase):
    """针对仓库真实 strategy_config.json 的契约校验。"""

    @classmethod
    def setUpClass(cls):
        cls.cfg = instrument.load_config(force=True)

    def test_instrument_section_present(self):
        self.assertIn("instrument", self.cfg)
        self.assertIn("lot_rules", self.cfg["instrument"])
        self.assertTrue(self.cfg["instrument"].get("strict_unknown_lot"))

    def test_five_hk_codes_registered(self):
        for code in ["00700", "03690", "01810", "00941", "00388"]:
            self.assertGreater(instrument.lot_of(code, self.cfg), 0, code)

    def test_hk_not_in_tradable_markets(self):
        self.assertNotIn("HK", instrument.tradable_markets(self.cfg))

    def test_candidate_pool_markets_all_valid(self):
        pool = self.cfg.get("auto_select", {}).get("candidate_pool", [])
        self.assertGreater(len(pool), 0)
        for p in pool:
            mk = instrument.market_of(p["code"], p)
            self.assertIn(mk, instrument.VALID_MARKETS, p["code"])

    def test_declared_market_matches_shape_inference(self):
        """候选池显式 market 标注应与代码形态推断一致(不一致说明池子数据有误)。"""
        pool = self.cfg.get("auto_select", {}).get("candidate_pool", [])
        mismatched = [
            (p["code"], p.get("market"), instrument.market_of(p["code"]))
            for p in pool
            if p.get("market") and p["market"] != instrument.market_of(p["code"])
        ]
        self.assertEqual(mismatched, [], f"候选池 market 标注与代码形态不符: {mismatched}")

    def test_every_pool_code_has_resolvable_lot(self):
        """全候选池每手股数必须可解析 —— 否则运行期会拒单。"""
        pool = self.cfg.get("auto_select", {}).get("candidate_pool", [])
        unresolvable = []
        for p in pool:
            try:
                instrument.lot_of(p["code"], self.cfg)
            except instrument.UnknownLotError:
                unresolvable.append(p["code"])
        self.assertEqual(unresolvable, [], f"以下标的每手股数未登记: {unresolvable}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
