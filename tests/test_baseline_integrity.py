# -*- coding: utf-8 -*-
"""
test_baseline_integrity.py - v6.18 诚实基线完整性闸门 (CI 拦截, 数据缺失则跳过)
================================================================================
把 v6.18 建立的"诚实纪律"锁死成一道 CI 关卡:

  1. run() 默认配置(use_tech=False + trend_filter=False + 核心卫星 + 死叉 + 成本)
     必须精确复现权威真值 18.185x / MDD -33.31% (容差内)。
     -> 任何人把默认翻回 use_tech=True(含前视相位表)或破坏基线, 此测试 FAIL。
  2. 基线对参数不敏感(参数扫描已证): 容差放宽到 [15,22]x / MDD [-40,-25]%,
     防止"微调基线配置刷出更好看数字"的自欺重新溜入。

数据依赖: 腾讯后复权面板 ashare_backtest/data/ashare_panel_close_em.csv (gitignore, 不入库)。
面板缺失时 pytest.skip (与 test_data_contract.py 同模式), CI 不误报。

显著性闸门的另一半(增强层样本外 |t|>=2 才准入基线)由 walk_forward.py 提供,
PR 评审时人工执行; 本测试负责"基线本身不被悄悄篡改"这一最底层防线。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "ashare_backtest"))

from backtest_engine import run

# 权威真值 (v6.18, 腾讯后复权面板含成本)
TRUTH_MULT = 18.185
TRUTH_MDD = -33.31
# 稳健区间 (来自 param_scan.py: lookback 网格 11.7~19.6x, MDD -31.5~-35.9%)
MULT_LO, MULT_HI = 15.0, 22.0
MDD_LO, MDD_HI = -40.0, -25.0


def _panel_path():
    base = os.path.join(ROOT, "ashare_backtest", "data")
    for name in ("ashare_panel_close_em.csv", "ashare_panel_close.csv"):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    return None


@unittest.skipIf(_panel_path() is None, "面板数据缺失 (gitignore), 跳过基线完整性闸门")
class TestBaselineIntegrity(unittest.TestCase):

    def _baseline(self):
        # 不显式传 use_tech/trend_filter -> 依赖引擎默认值(应为诚实 False)
        s, _, _, _ = run(
            offense_mode="momentum", momentum_lookback=26,
            core_satellite=True, core_frac=0.5, death_cross=True,
            costs=True, use_core_sub=True, panel_path=_panel_path(),
        )
        return s

    def test_default_is_honest_baseline(self):
        """引擎默认必须=诚实基线, 复现 18.185x / -33.31% (容差内)。"""
        s = self._baseline()
        self.assertAlmostEqual(s["final_multiple"], TRUTH_MULT, delta=2.0,
                               msg=f"倍数偏离权威真值: {s['final_multiple']} vs {TRUTH_MULT}")
        self.assertAlmostEqual(s["mdd"], TRUTH_MDD, delta=5.0,
                               msg=f"MDD 偏离权威真值: {s['mdd']} vs {TRUTH_MDD}")

    def test_baseline_in_robust_band(self):
        """基线落在参数稳健区间内 (防微调配置刷数)。"""
        s = self._baseline()
        self.assertGreaterEqual(s["final_multiple"], MULT_LO)
        self.assertLessEqual(s["final_multiple"], MULT_HI)
        self.assertGreaterEqual(s["mdd"], MDD_LO)
        self.assertLessEqual(s["mdd"], MDD_HI)

    def test_no_lookahead_default(self):
        """默认禁用 tech 相位(前视)与趋势过滤(已证有害)。

        直接核验签名默认值, 防止有人把 run() 默认翻回 use_tech=True
        (含 2026 回看标注的 PHASE_HISTORY 前视相位表, 虚增 +37.2%)。
        """
        import inspect
        sig = inspect.signature(run)
        self.assertIs(sig.parameters["use_tech"].default, False,
                      "run() 默认 use_tech 必须为 False (诚实基线)")
        self.assertIs(sig.parameters["trend_filter"].default, False,
                      "run() 默认 trend_filter 必须为 False (已证有害)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
