"""
回归测试: auto_trader.py 核心路径 (M5/M6)。

覆盖:
  - _regime_alloc: 三档仓位模板读取; 缺 REGIME_ALLOC -> ValueError 快速失败;
                   未知 regime 退回 balance
  - _total_capital: 从 account.capital 读取; 缺失退回 1_000_000 默认(向后兼容)

全部为纯函数测试, 不发网络请求、不触交易。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import auto_trader as at  # noqa: E402


def _cfg_with_alloc():
    return {
        "REGIME_ALLOC": {
            "weak": {"def": 60, "off": 24, "cash": 16},
            "balance": {"def": 45, "off": 45, "cash": 10},
            "bull": {"def": 35, "off": 60, "cash": 5},
        },
        "account": {"capital": 500000},
    }


class TestRegimeAlloc(unittest.TestCase):
    def test_three_regimes(self):
        cfg = _cfg_with_alloc()
        self.assertEqual(at._regime_alloc(cfg, "weak"), {"def": 60, "off": 24, "cash": 16})
        self.assertEqual(at._regime_alloc(cfg, "balance"), {"def": 45, "off": 45, "cash": 10})
        self.assertEqual(at._regime_alloc(cfg, "bull"), {"def": 35, "off": 60, "cash": 5})

    def test_unknown_regime_falls_back_to_balance(self):
        cfg = _cfg_with_alloc()
        # 未知 regime 退回 balance (alloc.get(regime, alloc["balance"]))
        self.assertEqual(at._regime_alloc(cfg, "nonexistent"),
                         {"def": 45, "off": 45, "cash": 10})

    def test_missing_regime_alloc_raises(self):
        # M6: 旧实现 `cfg.get("REGIME_ALLOC") or {硬编码}` 把硬编码 fallback 写回,
        # 违背单一真相源。改为缺失即抛 ValueError 快速失败。
        with self.assertRaises(ValueError):
            at._regime_alloc({}, "balance")

    def test_empty_regime_alloc_raises(self):
        # REGIME_ALLOC 段存在但为空 -> 同样抛错
        with self.assertRaises(ValueError):
            at._regime_alloc({"REGIME_ALLOC": {}}, "balance")


class TestTotalCapital(unittest.TestCase):
    def test_reads_from_config(self):
        cfg = {"account": {"capital": 500000}}
        self.assertEqual(at._total_capital(cfg), 500000.0)

    def test_returns_float(self):
        cfg = {"account": {"capital": "1200000"}}  # 字符串也能转
        self.assertEqual(at._total_capital(cfg), 1200000.0)
        self.assertIsInstance(at._total_capital(cfg), float)

    def test_missing_capital_falls_back_to_million(self):
        # M5: 旧实现硬编码 1_000_000。无 account.capital 时退回默认 + 日志提醒。
        self.assertEqual(at._total_capital({}), 1_000_000)
        self.assertEqual(at._total_capital({"account": {}}), 1_000_000)

    def test_missing_account_section(self):
        self.assertEqual(at._total_capital({"risk": {}}), 1_000_000)


class TestSafeLogTrade(unittest.TestCase):
    """M20: _safe_log_trade 统一封装, 异常不上抛(不杀交易主流程)。"""

    def test_does_not_raise_on_import_failure(self):
        # local_records 依赖文件系统, 这里只验证异常被吞掉不上抛
        # (无论 local_records 是否可用, _safe_log_trade 都不应抛)
        try:
            at._safe_log_trade("once", "600519", "茅台", "BUY", 1688.0, 100, "resp", "底仓")
        except Exception as e:
            self.fail(f"_safe_log_trade 不应上抛异常, 但抛了: {e}")


if __name__ == "__main__":
    unittest.main()
