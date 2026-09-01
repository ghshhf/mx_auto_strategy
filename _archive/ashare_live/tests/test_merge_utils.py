"""回归测试: merge_utils 经济去重键 (防 merge 误判新增/漏增)。

关键不变量:
  - 仅 (action, code, qty) 相同才视为同一笔 -> 时间戳/价格浮动不影响去重
  - 不同 qty 视为不同交易 (历史教训: 价格舍入差曾误判新交易)
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import merge_utils  # noqa: E402


def _rec(action, code, qty, price=None, ts=None):
    r = {"action": action, "code": code, "qty": qty}
    if price is not None:
        r["price"] = price
    if ts is not None:
        r["ts"] = ts
    return r


class TestMergeDedup(unittest.TestCase):
    def test_same_economic_key_deduped_regardless_of_ts_price(self):
        # 同一笔交易, 时间戳差几天、价格差 0.003 -> 必须去重 (历史教训)
        a = _rec("buy", "600519", 100, price=1685.000, ts="2026-07-29 09:35")
        b = _rec("buy", "600519", 100, price=1685.003, ts="2026-07-30 14:02")
        self.assertEqual(merge_utils.record_key(a), merge_utils.record_key(b))
        out = merge_utils.dedup([a, b])
        self.assertEqual(len(out), 1)

    def test_diff_qty_is_new_trade(self):
        a = _rec("buy", "600519", 100, price=1685.0)
        b = _rec("buy", "600519", 200, price=1685.0)
        self.assertNotEqual(merge_utils.record_key(a), merge_utils.record_key(b))
        self.assertEqual(len(merge_utils.dedup([a, b])), 2)

    def test_diff_action_is_new_trade(self):
        a = _rec("buy", "600519", 100)
        b = _rec("sell", "600519", 100)
        self.assertEqual(len(merge_utils.dedup([a, b])), 2)

    def test_order_preserved_first_wins(self):
        a = _rec("buy", "600519", 100, ts="2026-07-29")
        b = _rec("buy", "600519", 100, ts="2026-07-30")
        out = merge_utils.dedup([a, b])
        self.assertEqual(out[0]["ts"], "2026-07-29")

    def test_merge_main_plus_master_no_false_new(self):
        # 模拟 main 已有 3 笔, master 增量 3 笔, 不应把已有当新
        main = [
            _rec("buy", "NVDA", 909, ts="2026-07-27"),
            _rec("buy", "MU", 200, ts="2026-07-27"),
            _rec("buy", "LLY", 150, ts="2026-07-27"),
        ]
        master = main + [
            _rec("buy", "KO", 1951, ts="2026-07-29"),
            _rec("buy", "GLD", 322, ts="2026-07-29"),
            _rec("sell", "NVDA", 100, ts="2026-07-29"),
        ]
        out = merge_utils.dedup(master)
        self.assertEqual(len(out), 6)  # 3 原有 + 3 新增, 无重复


if __name__ == "__main__":
    unittest.main()
