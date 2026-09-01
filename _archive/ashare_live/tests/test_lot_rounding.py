"""
回归测试: 8 处手数硬编码收口 (T03, 转债漏钱洞)。

背景 —— 改造前全仓 8 处 `//100*100`:
    auto_trader.py : 183 硬止损 / 238 阶梯止盈 / 278 周度清仓 / 534 进攻仓止损
    grid_trader.py : 141 网格买入 / 161 网格卖出
    rebalance.py   :  97 防御再平衡卖出 / 131 进攻仓减仓

后果:
    - 转债 60 张   -> 60//100*100 = 0    止损静默失败, 亏损无限扩大
    - 转债 150 张  -> 150//100*100 = 100 卖 100 后 del 持仓, 剩 50 张成孤儿仓
    - 港股小米 600 股(lot=200) -> 手数口径错误

本测试:
  1. 静态断言: 源码中不得再出现 //100*100 / //10*10 硬编码
  2. 语义断言: 各场景的取整结果符合预期(纯函数, 不发网络请求、不下单)
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import instrument  # noqa: E402

# 被收口的 8 处所在文件
GUARDED_FILES = ["auto_trader.py", "grid_trader.py", "rebalance.py"]

# 旧硬编码模式: //100*100 或 //10*10 (允许任意空格)
HARDCODED_LOT_RE = re.compile(r"//\s*100\s*\*\s*100|//\s*10\s*\*\s*10")


def _cfg():
    return instrument.load_config(force=True)


class TestNoHardcodedLotRounding(unittest.TestCase):
    """CI 断言: 收口后源码不得再出现手数硬编码(防新代码再挖同一个洞)。"""

    def test_no_hardcoded_rounding_in_guarded_files(self):
        offenders = []
        for fname in GUARDED_FILES:
            path = os.path.join(HERE, fname)
            with open(path, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    # 跳过注释行(注释里引用旧写法用于说明, 属正常)
                    if line.lstrip().startswith("#"):
                        continue
                    if HARDCODED_LOT_RE.search(line):
                        offenders.append(f"{fname}:{lineno}: {line.strip()}")
        self.assertEqual(offenders, [], "仍存在手数硬编码:\n" + "\n".join(offenders))

    def test_guarded_files_import_instrument(self):
        for fname in GUARDED_FILES:
            path = os.path.join(HERE, fname)
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
            self.assertIn("import instrument", src, f"{fname} 未接入 instrument")


class TestConvertibleBondLeak(unittest.TestCase):
    """转债漏钱洞: lot=10, 旧代码按 100 取整导致静默失败/孤儿仓。"""

    def setUp(self):
        self.cfg = _cfg()
        self.code = "113050"  # 南银转债

    def test_market_is_kzz(self):
        self.assertEqual(instrument.market_of(self.code), "KZZ")
        self.assertEqual(instrument.lot_of(self.code, self.cfg), 10)

    def test_stop_loss_60_lots_now_sellable(self):
        """漏钱洞#1/#4: 60 张全仓止损, 旧代码得 0(静默失败)。"""
        remain_qty = 60 * (1 - 0.0)
        self.assertEqual(int(remain_qty // 100 * 100), 0, "前提校验: 旧写法确实是 0")
        self.assertEqual(instrument.round_qty(remain_qty, self.code, self.cfg), 60)

    def test_weekly_reset_150_lots_no_orphan(self):
        """漏钱洞#3: 150 张周度清仓, 旧代码只卖 100, 剩 50 张成孤儿仓。"""
        remain_qty = 150 * (1 - 0.0)
        self.assertEqual(int(remain_qty // 100 * 100), 100, "前提校验: 旧写法确实是 100")
        self.assertEqual(instrument.round_qty(remain_qty, self.code, self.cfg), 150)

    def test_tiered_take_profit_partial(self):
        """漏钱洞#2: 阶梯止盈卖 30% —— 150 张 * 0.3 = 45 张 -> 取整 40 张(旧代码 0)。"""
        qty, target_cum, sold_ratio = 150, 0.30, 0.0
        raw = qty * (target_cum - sold_ratio)
        self.assertEqual(int(raw // 100 * 100), 0)
        self.assertEqual(instrument.round_qty(raw, self.code, self.cfg), 40)

    def test_rebalance_trim(self):
        """漏钱洞#7/#8: 再平衡减仓 20% —— 150 张 * 0.2 = 30 张(旧代码 0)。"""
        raw = 150 * 0.2
        self.assertEqual(int(raw // 100 * 100), 0)
        self.assertEqual(instrument.round_qty(raw, self.code, self.cfg), 30)

    def test_grid_buy_kzz(self):
        """漏钱洞#5: 网格买入 —— buy() 认 KZZ=10 但网格按 100 算, 两套口径不一致。"""
        amt, price = 20000.0, 118.5   # 约 168 张
        old = int(amt // price // 100 * 100)
        new = instrument.round_qty(amt / price, self.code, self.cfg)
        self.assertEqual(old, 100)
        self.assertEqual(new, 160)
        self.assertGreater(new, old)

    def test_grid_sell_kzz(self):
        """漏钱洞#6: 网格卖出。"""
        per_layer, to_sell, price = 8000.0, 1, 118.5  # 约 67 张
        old = int(per_layer * to_sell // price // 100 * 100)
        new = instrument.round_qty(per_layer * to_sell / price, self.code, self.cfg)
        self.assertEqual(old, 0)
        self.assertEqual(new, 60)


class TestHongKongLot(unittest.TestCase):
    """港股每手股数逐只不同, 不能一律按 100。"""

    def setUp(self):
        self.cfg = _cfg()

    def test_xiaomi_lot_200(self):
        self.assertEqual(instrument.lot_of("01810", self.cfg), 200)
        self.assertEqual(instrument.round_qty(600, "01810", self.cfg), 600)
        self.assertEqual(instrument.round_qty(650, "01810", self.cfg), 600)
        # 旧代码会得 600 / 600 —— 巧合相同, 但 700 股就会错
        self.assertEqual(instrument.round_qty(700, "01810", self.cfg), 600)
        self.assertEqual(int(700 // 100 * 100), 700, "前提校验: 旧写法得 700(非整手, 废单)")

    def test_china_mobile_lot_500(self):
        self.assertEqual(instrument.lot_of("00941", self.cfg), 500)
        self.assertEqual(instrument.round_qty(1200, "00941", self.cfg), 1000)
        self.assertEqual(int(1200 // 100 * 100), 1200, "前提校验: 旧写法得 1200(非整手, 废单)")

    def test_tencent_lot_100(self):
        self.assertEqual(instrument.lot_of("00700", self.cfg), 100)
        self.assertEqual(instrument.round_qty(350, "00700", self.cfg), 300)

    def test_unregistered_hk_refuses_order(self):
        """未登记港股必须拒单, 绝不猜 100。"""
        with self.assertRaises(instrument.UnknownLotError):
            instrument.round_qty(1000, "09988", self.cfg)


class TestAShareNoRegression(unittest.TestCase):
    """A 股/ETF 行为必须与改造前逐位一致 —— 这是本次改造的回归底线。"""

    def setUp(self):
        self.cfg = _cfg()

    def test_a_share_stop_loss(self):
        for qty, sold in [(1000, 0.0), (1000, 0.3), (777, 0.0), (99, 0.0), (12345, 0.55)]:
            remain = qty * (1 - sold)
            self.assertEqual(
                instrument.round_qty(remain, "600519", self.cfg),
                int(remain // 100 * 100),
                f"A 股止损取整回归失败 qty={qty} sold={sold}",
            )

    def test_a_share_grid_buy(self):
        for amt, price in [(20000.0, 118.5), (50000.0, 7.99), (3000.0, 1350.6)]:
            self.assertEqual(
                instrument.round_qty(amt / price, "600519", self.cfg),
                int(amt // price // 100 * 100),
                f"A 股网格买入取整回归失败 amt={amt} price={price}",
            )

    def test_etf_rebalance(self):
        for qty, ratio in [(10000, 0.2), (5500, 0.5), (150, 0.2)]:
            self.assertEqual(
                instrument.round_qty(qty * ratio, "510300", self.cfg),
                int(qty * ratio // 100 * 100),
                f"ETF 再平衡取整回归失败 qty={qty} ratio={ratio}",
            )


class TestResolveQtySafety(unittest.TestCase):
    """auto_trader.resolve_qty: UnknownLotError 必须降级为 0(跳过), 不得炸穿主流程。"""

    def setUp(self):
        self.cfg = _cfg()

    def test_resolve_qty_swallows_unknown_lot(self):
        import auto_trader
        self.assertEqual(
            auto_trader.resolve_qty(1000, "09988", self.cfg, market="HK", ctx="单测"), 0
        )

    def test_resolve_qty_matches_round_qty_for_known(self):
        import auto_trader
        self.assertEqual(
            auto_trader.resolve_qty(150, "113050", self.cfg, market="KZZ"),
            instrument.round_qty(150, "113050", self.cfg, market="KZZ"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
