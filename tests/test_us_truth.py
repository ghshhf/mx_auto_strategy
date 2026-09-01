# -*- coding: utf-8 -*-
"""
test_us_truth.py - 美股真值回归闸门 (CI 拦截, 面板缺失则跳过)
================================================================================

把美股引擎当前权威真值锁死成一道 CI 关卡, 防止引擎数值静默漂移:

  1. run_optimized(期权层未启用 / options_sim=None) 必须复现无期权真值
     21.446x / MDD -48.57% (容差内)。
     -> 任何改动若把无期权真值推离 ~21.4x (±1x), 此测试 FAIL。
  2. 稳健区间 [20,23]x / MDD [-55,-38]% (用户认可区间 20-23x / -40%):
     防"微调配置刷出更好看数字"(如偷偷放宽止盈/改成本模型)的自欺重新溜入。
  3. options_sim(BS LEAPS 模拟层, call_vol=0.26) 落在 [80,130]x 宽区间:
     该路径对隐含波动率极敏感(call_vol 0.25->93x / 0.26->100x / 0.30->131x),
     仅做崩溃级护栏, 不锁精确值。若有人误关 options_sim 或 IV 配置损坏导致
     跌至 ~31x(flat 4.5%)或回归无期权 21x, 此测试 FAIL。

数据依赖: 美股面板 markets/us/data/weekly_adjclose_full_ext.csv (已入库, 非 gitignore)。
面板缺失时 pytest.skip (与 A股 test_baseline_integrity.py 同模式), CI 不误报。

⚠️ 当你有意更新美股引擎(换面板 / 改参数 / 调期权 IV 假设)导致真值变化时,
   同步更新下方 TRUTH_MULT / TRUTH_MDD / 区间常量即可 —— 这是预期内的
   "有意为之", 而非静默漂移。引擎重算后建议顺带刷新 docs/data/nav_us.json。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "markets", "us"))

import us_backtest_ai as U

# 权威真值 (当前引擎实输出, 无期权层, 确定性无 LLM; 二次复跑确认一致)
# 注: README 旧记 22.48x 为早期口径, 本闸门钉的是当前代码实际产出 21.446x。
TRUTH_MULT = 21.446
TRUTH_MDD = -48.57
# 稳健区间 (用户认可 20-23x / -40%; 含成本, 纯动量结构性 -48% MDD)
MULT_LO, MULT_HI = 20.0, 23.0
MDD_LO, MDD_HI = -55.0, -38.0
# options_sim 宽区间 (IV 极敏感, 仅崩溃护栏; 正常 ~100x)
SIM_LO, SIM_HI = 80.0, 130.0


def _panel_path():
    p = os.path.join(ROOT, "markets", "us", "data", "weekly_adjclose_full_ext.csv")
    return p if os.path.exists(p) else None


@unittest.skipIf(_panel_path() is None, "美股面板缺失, 跳过美股真值闸门")
class TestUsTruth(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # 引擎较重: 全类只跑一次, 三个测试共享, 避免 CI 重复开销。
        cls.dates, cls.series = U.load_panel(_panel_path())
        # 复位 series_proxy 全局: 消除 test_us_backtest.py 合成面板泄漏导致的
        # 测试顺序依赖(其用例 set 了全局未清理)。按生产 CLI 惯例填入真实面板,
        # 使 finalize 内的 SPY 基准计算正确, 且与 CI 全量收集顺序无关。
        U.series_proxy.clear()
        U.series_proxy.update(cls.series)
        cls.us_cfg = U.load_us_cfg()
        # 无期权真值 (期权层空壳 + options_sim=None)
        cls.opt_hist, cls.opt_st = U.run_optimized(
            cls.series, cls.dates, use_ai=False, cfg=None,
            refresh_weeks=4, theme_div=True, max_per_theme=2,
            us_cfg=cls.us_cfg, options_sim=None)
        # 期权模拟层 (BS LEAPS, 读 strategy_config.json options_sim 块)
        sim_cfg = cls.us_cfg.get("options_sim") or {}
        cls.sim_hist, cls.sim_st = U.run_optimized(
            cls.series, cls.dates, use_ai=False, cfg=None,
            refresh_weeks=4, theme_div=True, max_per_theme=2,
            us_cfg=cls.us_cfg,
            options_sim=sim_cfg if sim_cfg.get("enabled") else None)

    def test_no_options_is_truth(self):
        """无期权层必须复现 21.446x / MDD -48.57% (容差内)。"""
        self.assertAlmostEqual(
            self.opt_st["multiple"], TRUTH_MULT, delta=1.0,
            msg=f"无期权倍数偏离权威真值: {self.opt_st['multiple']:.3f} vs {TRUTH_MULT}")
        self.assertAlmostEqual(
            self.opt_st["mdd"] * 100, TRUTH_MDD, delta=3.0,
            msg=f"无期权 MDD 偏离权威真值: {self.opt_st['mdd']*100:.2f}% vs {TRUTH_MDD}%")

    def test_no_options_robust_band(self):
        """无期权真值落在稳健区间 [20,23]x / MDD[-55,-38]% (防微调刷数)。"""
        m = self.opt_st["multiple"]
        self.assertGreaterEqual(m, MULT_LO,
                               msg=f"无期权倍数 {m:.3f} 跌破稳健下界 {MULT_LO}x")
        self.assertLessEqual(m, MULT_HI,
                            msg=f"无期权倍数 {m:.3f} 超出稳健上界 {MULT_HI}x (警惕配置刷数)")
        d = self.opt_st["mdd"] * 100
        self.assertGreaterEqual(d, MDD_LO,
                               msg=f"无期权 MDD {d:.2f}% 优于 {MDD_LO}% (警惕成本/信号被偷偷放宽)")
        self.assertLessEqual(d, MDD_HI,
                            msg=f"无期权 MDD {d:.2f}% 差于 {MDD_HI}% (警惕引擎退化)")

    def test_options_sim_crash_guard(self):
        """期权模拟层落在 [80,130]x 宽区间 (IV 极敏感, 仅崩溃护栏)。"""
        m = self.sim_st["multiple"]
        self.assertGreaterEqual(
            m, SIM_LO,
            msg=(f"期权模拟 {m:.2f}x 过低: 可能 options_sim 被误关 / IV 配置损坏 "
                 f"(正常约 100x; flat 4.5% 兜底约 31.7x 亦非预期)"))
        self.assertLessEqual(
            m, SIM_HI,
            msg=f"期权模拟 {m:.2f}x 过高: 可能 IV 配置异常 (call_vol 0.30->131x 为已知上沿)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
