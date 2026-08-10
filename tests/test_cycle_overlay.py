# -*- coding: utf-8 -*-
"""
test_cycle_overlay.py - 12 层周期 composite_regime 统一叠加层接入测试 (v6.20)

重点保护的正确性属性(与 macro_overlay / 各引擎基线一致):
  1. 额度守恒(无隐性杠杆): 任何 scale 下进攻仓只能从防御仓/稳定币匀额度, 绝不借入;
     apply_to_alloc 保证现金 >= 0, apply_to_crypto_target 保证稳定币 >= 0。
  2. 基线不污染: cycle_overlay=False 或 cycle_tilt=0 时, 结果与未引入该特性完全一致。
  3. 优雅降级: cycles 数据缺失 / 模块加载失败 -> 乘数 1.0, 不改变回测。
  4. 有界: cycle_scale_at ∈ [TILT_MIN, TILT_MAX] = [0.5, 1.5]。
"""
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from cycles.overlay import (  # noqa: E402
    cycle_scale_at, apply_to_alloc, apply_to_crypto_target, cap_offense, get_cycle_state,
)


class TestOverlayConservation(unittest.TestCase):
    """额度守恒 / 无隐性杠杆 —— 这是叠加层唯一不可妥协的属性。"""

    def test_apply_to_alloc_lever_free_and_conserved(self):
        for scale in (0.5, 0.8, 1.0, 1.2, 1.5, 2.0):
            o, d, c = apply_to_alloc(60.0, 20.0, 20.0, scale)
            self.assertGreaterEqual(c, -1e-9, f"scale={scale} 现金为负 = 隐性杠杆")
            self.assertLessEqual(o, 80.0 + 1e-9, f"scale={scale} 进攻超 80% 上限")
            self.assertAlmostEqual(o + d + c, 100.0, places=6,
                                   msg=f"scale={scale} 三栏之和不为 100%")

    def test_apply_to_alloc_scale1_is_baseline(self):
        o, d, c = apply_to_alloc(60.0, 20.0, 20.0, 1.0)
        self.assertAlmostEqual(o, 60.0, places=6)
        self.assertAlmostEqual(d, 20.0, places=6)
        self.assertAlmostEqual(c, 20.0, places=6)

    def test_apply_to_alloc_tailwind_funded_by_defense(self):
        # 顺风加仓只能从防御仓匀, 匀不出就不加(封顶, 不杠杆)
        o, d, c = apply_to_alloc(60.0, 20.0, 20.0, 1.5)
        self.assertAlmostEqual(o, 80.0, places=6)   # 60 + min(20, 20)
        self.assertAlmostEqual(d, 0.0, places=6)
        self.assertAlmostEqual(c, 20.0, places=6)

    def test_apply_to_crypto_conserved_and_nonneg_stable(self):
        off = {"BTC": 0.3, "ETH": 0.3}
        for scale in (0.5, 0.8, 1.0, 1.2, 1.5):
            no, ns = apply_to_crypto_target(off, 0.4, scale)
            self.assertGreaterEqual(ns, -1e-9, f"scale={scale} 稳定币为负 = 杠杆")
            self.assertAlmostEqual(sum(no.values()) + ns, 1.0, places=6,
                                   msg=f"scale={scale} 进攻+稳定币不为 1")
        # scale=1 必须原样
        no, ns = apply_to_crypto_target(off, 0.4, 1.0)
        self.assertAlmostEqual(no["BTC"], 0.3, places=6)
        self.assertAlmostEqual(ns, 0.4, places=6)

    def test_cap_offense_lever_free(self):
        # 现金=0, 进攻=100 -> 顺风乘子再多也被裁到 100(不借入)
        self.assertLessEqual(cap_offense(120.0, 0.0, 100.0, 0.0), 100.0 + 1e-9)
        # 现金=5, 进攻=80 -> 上限 85
        self.assertAlmostEqual(cap_offense(96.0, 5.0, 80.0, 0.0), 85.0, places=6)
        # baseline(scale=1) 不被裁
        self.assertAlmostEqual(cap_offense(80.0, 5.0, 80.0, 0.0), 80.0, places=6)


class TestCycleScaleAt(unittest.TestCase):
    """cycle_scale_at 有界 + 优雅降级。"""

    def test_bounded_with_real_data(self):
        if not os.path.exists(os.path.join(BASE, "cycles", "data", "cycles_raw.csv")):
            self.skipTest("cycles 数据缺失")
        for d in ("2009-03-01", "2020-04-01", "2022-10-01", "2026-08-01"):
            s = cycle_scale_at(d)
            self.assertGreaterEqual(s, 0.5 - 1e-9)
            self.assertLessEqual(s, 1.5 + 1e-9)

    def test_neutral_when_no_state(self):
        """数据缺失 -> 乘数 1.0, 不改变基线。"""
        import cycles.overlay as O
        saved_state, saved_raw = O._STATE, O.RAW
        O._STATE = None
        O.RAW = "/nonexistent/cycles_raw.csv"
        try:
            self.assertEqual(O.cycle_scale_at("2026-01-01"), 1.0)
            # 强制重载也应为 None -> 1.0
            O._STATE = None
            self.assertEqual(get_cycle_state(), None)
            self.assertEqual(O.cycle_scale_at("2026-01-01"), 1.0)
        finally:
            O._STATE, O.RAW = saved_state, saved_raw


class TestEngineIntegration(unittest.TestCase):
    """接入三引擎: cycle_tilt=0 必须 == 基线(关闭)。数据缺失则跳过。"""

    def test_a_share_tilt0_equals_baseline(self):
        panel = os.path.join(BASE, "ashare_backtest", "data", "ashare_panel_close_em.csv")
        if not os.path.exists(panel):
            self.skipTest("A股面板数据不存在(需 tencent_hfq_rebuild)")
        sys.path.insert(0, os.path.join(BASE, "ashare_backtest"))
        from backtest_engine import run  # noqa: F401
        kw = dict(offense_mode="momentum", momentum_lookback=26, use_tech=True,
                  core_satellite=True, core_frac=0.5, death_cross=True, costs=True,
                  use_core_sub=True, panel_path=panel, record_plan=True)
        a, _, _, _ = run(**kw)
        b, _, _, _ = run(cycle_overlay=True, cycle_tilt=0.0, **kw)
        self.assertEqual(a["final_multiple"], b["final_multiple"])

    def test_us_tilt0_equals_baseline(self):
        p = os.path.join(BASE, "us_stocks", "data", "weekly_adjclose_full_ext.csv")
        if not os.path.exists(p):
            self.skipTest("美股面板数据不存在")
        import importlib
        us = importlib.import_module("us_stocks.us_backtest_ai")
        dates, series = us.load_panel(p)
        cfg = us.load_us_cfg()
        N = 104
        ds = dates[-N:]; ss = {k: v[-N:] for k, v in series.items()}
        a = us.run_optimized(ss, ds, False, cfg, cycle_overlay=False)
        b = us.run_optimized(ss, ds, False, cfg, cycle_overlay=True, cycle_tilt=0.0)
        self.assertAlmostEqual(a[1]["multiple"], b[1]["multiple"], places=9)

    def test_crypto_tilt0_equals_baseline(self):
        import pandas as pd
        p = os.path.join(BASE, "crypto_stocks", "data", "weekly_adjclose_crypto50.csv")
        if not os.path.exists(p):
            self.skipTest("加密面板数据不存在")
        import crypto_stocks.crypto_options_bt as cb
        px = pd.read_csv(p, index_col=0, parse_dates=True).sort_index().iloc[-156:]
        a = cb.run_bt(px.copy(), cycle_overlay=False)
        b = cb.run_bt(px.copy(), cycle_overlay=True, cycle_tilt=0.0)
        self.assertAlmostEqual(a["multiple"], b["multiple"], places=9)


if __name__ == "__main__":
    unittest.main()
