# -*- coding: utf-8 -*-
"""
test_crypto_panel_quality.py — 加密三面板数据质量回归测试 (P3)

锁死 2026-09-04 的修复成果, 防止未来 sync/增币时再次引入合成漂移:
  1. 三面板 (c50 / 10y / v3) 列集合必须完全一致 (34 币)
  2. 在 10y 有值处, c50 与 v3 必须 == 10y (修复后三面板对齐; 任何偏差 = 合成漂移)
  3. 每币活跃区间内无内部空洞 (NaN 洞 = 未对齐)

注: 不测"极端单周跳变" —— 加密资产在 mania 阶段单周涨跌 >80% 是真实行情
(如 BNB 2017 +144% / XLM 2021 +108% / AVAX 2021 +133%), 简单阈值法会误报,
不能用作合成/拼接错误的判别信号。拼接错误改由上游 repair_panels 的
-3 口径 + 交易所交叉校验把关。

运行:
  E:/xmanbian/_venv/mx_quant/Scripts/python.exe -m pytest tests/test_crypto_panel_quality.py -q
"""
import os
import sys
import unittest

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL_DIR = os.path.join(ROOT, "markets", "crypto", "data")
sys.path.insert(0, os.path.join(ROOT, "markets", "crypto"))


def _load(name):
    return pd.read_csv(os.path.join(PANEL_DIR, name), index_col=0,
                       parse_dates=True).sort_index()


class TestPanelQuality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c50 = _load("weekly_adjclose_crypto50.csv")
        cls.ten = _load("weekly_adjclose_crypto50_10y.csv")
        cls.v3 = _load("weekly_adjclose_crypto50_v3.csv")

    def test_three_panels_same_columns(self):
        cols = set(self.ten.columns)
        self.assertEqual(set(self.c50.columns), cols,
                         "c50 列须与 10y 真值基准完全一致")
        self.assertEqual(set(self.v3.columns), cols,
                         "v3 列须与 10y 真值基准完全一致")
        # 34 币池
        self.assertEqual(len(cols), 34,
                         f"当前应为 34 币池, 实际 {len(cols)} 币")

    def test_c50_v3_match_10y(self):
        ten = self.ten
        for col in ten.columns:
            tc = ten[col].dropna()
            if len(tc) == 0:
                continue
            for panel, pname in [(self.c50, "c50"), (self.v3, "v3")]:
                pc = panel[col].reindex(tc.index)
                rel = ((pc - tc).abs() / tc.abs().replace(0, np.nan)).dropna()
                max_rel = float(rel.max()) if len(rel) else 0.0
                self.assertLess(
                    max_rel, 0.01,
                    f"{pname}.{col} 与 10y 最大相对偏差 {max_rel:.4f} 超阈 "
                    f"(合成漂移? 修复后三面板应严格对齐)")

    def test_no_internal_holes_in_active_range(self):
        ten = self.ten
        for col in ten.columns:
            s = ten[col]
            first, last = s.first_valid_index(), s.last_valid_index()
            if first is None:
                continue
            n_hole = int(s.loc[first:last].isna().sum())
            self.assertEqual(n_hole, 0,
                             f"{col} 活跃区间内有 {n_hole} 个内部空洞 (未对齐?)")

if __name__ == "__main__":
    unittest.main(verbosity=2)
