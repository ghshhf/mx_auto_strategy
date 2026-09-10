"""run_all.py 的比对逻辑单测 (不跑重脚本, 不联网, CI 安全).

覆盖三件事:
  1. 容差判定: 倍数走相对容差, MDD/CAGR/Sharpe 走绝对容差;
  2. 前缀过滤: 被跳过的阶段(如 --no-deep 的 reconcile)其基线指标不参与比对,
     否则会全员 MISSING 而假红;
  3. NEW / MISSING 的判定方向不能反 —— 基线缺=NEW, 本次缺=MISSING(算失败)。
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# run_all 顶层会 os.makedirs 等副作用, 但 import 是安全的 (无模块级执行)
import run_all  # noqa: E402


class _Args:
    tol_mult = 0.02
    tol_pct = 0.5
    tol_sharpe = 0.05


class TestCompare(unittest.TestCase):
    def setUp(self):
        self.args = _Args()
        self.base = {
            'crypto.nav.mult': 5630.108,
            'crypto.nav.mdd': -70.4,
            'crypto.nav.sharpe': 1.60,
            'crypto.10y.FULL_default.mult': 6059.0,   # 属 reconcile 前缀
            'us.no_options.cagr': 29.2,
        }

    def test_identical_passes(self):
        rows = run_all.compare(self.base, dict(self.base), self.args)
        self.assertTrue(all(r[4] == 'OK' for r in rows), rows)

    def test_mult_uses_relative_tolerance(self):
        # +1% 在 2% 相对容差内 -> OK
        cur = dict(self.base)
        cur['crypto.nav.mult'] = self.base['crypto.nav.mult'] * 1.01
        rows = {r[0]: r[4] for r in run_all.compare(self.base, cur, self.args)}
        self.assertEqual(rows['crypto.nav.mult'], 'OK')

        # +5% 超出 -> FAIL
        cur['crypto.nav.mult'] = self.base['crypto.nav.mult'] * 1.05
        rows = {r[0]: r[4] for r in run_all.compare(self.base, cur, self.args)}
        self.assertEqual(rows['crypto.nav.mult'], 'FAIL')

    def test_pct_metrics_use_absolute_tolerance(self):
        cur = dict(self.base)
        cur['crypto.nav.mdd'] = -70.9          # 差 0.5pp, 恰好等于容差
        rows = {r[0]: r[4] for r in run_all.compare(self.base, cur, self.args)}
        self.assertEqual(rows['crypto.nav.mdd'], 'OK')

        cur['crypto.nav.mdd'] = -71.5          # 差 1.1pp -> FAIL
        rows = {r[0]: r[4] for r in run_all.compare(self.base, cur, self.args)}
        self.assertEqual(rows['crypto.nav.mdd'], 'FAIL')

    def test_sharpe_tolerance(self):
        cur = dict(self.base)
        cur['crypto.nav.sharpe'] = 1.63        # 差 0.03 <= 0.05 -> OK
        rows = {r[0]: r[4] for r in run_all.compare(self.base, cur, self.args)}
        self.assertEqual(rows['crypto.nav.sharpe'], 'OK')

        cur['crypto.nav.sharpe'] = 1.70        # 差 0.10 -> FAIL
        rows = {r[0]: r[4] for r in run_all.compare(self.base, cur, self.args)}
        self.assertEqual(rows['crypto.nav.sharpe'], 'FAIL')

    def test_skipped_stage_prefixes_are_excluded(self):
        """--no-deep 时 reconcile 指标整批缺席, 不应判 MISSING/FAIL。"""
        cur = {k: v for k, v in self.base.items()
               if not k.startswith(('crypto.10y.', 'crypto.12y.'))}
        active = ('ashare.', 'us.', 'crypto.nav.', 'blend.')
        rows = run_all.compare(self.base, cur, self.args, active_prefixes=active)
        keys = [r[0] for r in rows]
        self.assertNotIn('crypto.10y.FULL_default.mult', keys)
        self.assertTrue(all(r[4] == 'OK' for r in rows), rows)

    def test_missing_metric_inside_active_stage_is_failure(self):
        """阶段跑了但指标消失 -> 真失败。"""
        cur = dict(self.base)
        cur.pop('us.no_options.cagr')
        rows = {r[0]: r[4] for r in run_all.compare(self.base, cur, self.args)}
        self.assertEqual(rows['us.no_options.cagr'], 'MISSING')

    def test_new_metric_is_flagged_not_failed(self):
        cur = dict(self.base)
        cur['crypto.nav.cagr'] = 135.2          # 基线里没有
        rows = {r[0]: r[4] for r in run_all.compare(self.base, cur, self.args)}
        self.assertEqual(rows['crypto.nav.cagr'], 'NEW')


class TestHelpers(unittest.TestCase):
    def test_years_and_cagr(self):
        dates = ['2020-01-01', '2021-01-01', '2022-01-01']
        yrs = run_all._years(dates)
        self.assertAlmostEqual(yrs, 2.0, delta=0.02)
        # 4 倍 / 2 年 -> CAGR = 100%
        self.assertAlmostEqual(run_all._cagr(4.0, 2.0), 100.0, delta=0.1)

    def test_prefix_map_covers_all_stages(self):
        stages = {s for s, _, _ in run_all.STAGES}
        self.assertEqual(stages, set(run_all.PREFIX))
        for pfx in run_all.PREFIX.values():
            self.assertTrue(pfx and all(isinstance(p, str) for p in pfx))
        # 前缀之间不能互相包含, 否则过滤会误伤
        flat = [p for v in run_all.PREFIX.values() for p in v]
        for a in flat:
            for b in flat:
                if a != b:
                    self.assertFalse(b.startswith(a), f'{b} 被 {a} 前缀覆盖')

    def test_module_imports_without_side_effects(self):
        self.assertIsInstance(run_all, types.ModuleType)
        self.assertTrue(callable(run_all.main))
        self.assertTrue(callable(run_all.compare))


if __name__ == '__main__':
    unittest.main()
