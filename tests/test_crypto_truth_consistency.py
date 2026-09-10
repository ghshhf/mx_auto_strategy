# -*- coding: utf-8 -*-
"""
test_crypto_truth_consistency.py — 加密**发布真值口径**一致性 (2026-09-10 新增)

背景（事故复盘）
----------------
面板从 34 → 32 → 27 币演进过两轮，但 `export_nav_crypto.py` 里
`source` 字符串把币数**硬编码为 "34币"**，导致：

  - `docs/data/nav_crypto.json`（站点展示用）长期挂着 "34币" 标注；
  - `docs/TRUTH.md` 写 32 币 5,662.51x；
  - `crypto_research/` 里的权威结论写 27 币 6,043x；

三处互不相同，对外发布页实际是错的。根因 = **口径数字与数据源之间没有校验**。

本测试钉死「发布数据标注 == 面板实际列数 == 运营池规模」这条链，
任一端漂移（改池后没重跑导出、或导出脚本又把数字写死）都会在 CI 红灯。

与 `test_crypto_panel_quality.py` 的区别：那个防**数据**漂移（三面板数值对齐），
本文件防**口径/元数据**漂移。
"""
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRYPTO = os.path.join(ROOT, "markets", "crypto")
sys.path.insert(0, CRYPTO)


def _panel_cols():
    import pandas as pd
    px = pd.read_csv(os.path.join(CRYPTO, "data", "weekly_adjclose_crypto50_10y.csv"),
                     index_col=0, parse_dates=True)
    return list(px.columns)


def _nav_json():
    with open(os.path.join(ROOT, "docs", "data", "nav_crypto.json"), encoding="utf-8") as f:
        return json.load(f)


class TestTruthConsistency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nav = _nav_json()
        cls.cols = _panel_cols()

    def test_nav_declares_coin_count(self):
        # 字段缺失会让下面的断言「静默跳过」, 必须先钉住契约本身
        self.assertIn("n_coins", self.nav, "nav_crypto.json 须带 n_coins 字段")

    def test_declared_coin_count_matches_panel(self):
        self.assertEqual(
            self.nav["n_coins"], len(self.cols),
            f"nav_crypto.json 标注 {self.nav['n_coins']} 币, 面板实际 {len(self.cols)} 币 "
            "—— 改池后忘了重跑 export_nav_crypto.py",
        )

    def test_source_string_coin_count_matches_panel(self):
        # 事故原点: source 曾硬编码 "34币" 而面板已是 27 币
        m = re.search(r"(\d+)\s*币", self.nav.get("source", ""))
        self.assertIsNotNone(m, f"source 字符串里找不到币数: {self.nav.get('source')!r}")
        self.assertEqual(
            int(m.group(1)), len(self.cols),
            f"source 写 {m.group(1)} 币, 面板实际 {len(self.cols)} 币 —— 不得写死币数",
        )

    def test_panel_matches_operational_pool(self):
        # 运营池 = _screen_current_pool.json 的 never/once/twice/thrice 并集
        with open(os.path.join(CRYPTO, "_screen_current_pool.json"), encoding="utf-8") as f:
            pool = json.load(f)
        expected = set()
        for k in ("never", "once", "twice", "thrice"):
            expected |= set(pool.get(k) or [])
        self.assertEqual(set(self.cols), expected,
                         "面板列集合须与运营池完全一致 (增/删币后须同步三面板)")

    def test_truth_multiple_is_sane(self):
        # 防呆: 导出失败/窗口错切会静默产出个位数倍数, 不应被当作真值发布
        mult = self.nav["truth"]["cycle"]["final_mult"]
        self.assertGreater(mult, 100,
                           f"10y cycle 倍数 {mult}x 异常偏低, 导出可能失败")
        self.assertLess(mult, 1000000,
                        f"10y cycle 倍数 {mult}x 异常偏高, 疑似期权时代口径复活")

    def test_mdd_and_sharpe_present(self):
        c = self.nav["truth"]["cycle"]
        self.assertLess(c["mdd"], 0, "MDD 须为负")
        self.assertGreater(c["sharpe"], 0.5)


if __name__ == "__main__":
    unittest.main()
