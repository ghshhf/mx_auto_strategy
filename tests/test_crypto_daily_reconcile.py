# -*- coding: utf-8 -*-
"""
test_crypto_daily_reconcile.py — 日线-周线对账闸门 (离线, P3)
================================================================
锁定 2026-09-18 审计修复成果 (GRAM 2026-06-26 +10% 跨所拼接错值):
面板周值必须与**日线缓存** (data/daily_cache_crypto50.csv, 由
`markets/crypto/audit_daily_vs_weekly.py` 在线审计时写出) 一致.

缓存不存在时 skip —— 本测试不联网, 联网全量审计请手动跑:
  python markets/crypto/audit_daily_vs_weekly.py
建议节奏: 每次周面板同步后跑一次在线审计 (更新缓存), 此后 CI/本地
可随时用缓存做离线复检.

运行 (仓库根):
  python -m pytest tests/test_crypto_daily_reconcile.py -q
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "markets", "crypto"))

PANEL = os.path.join(ROOT, "markets", "crypto", "data", "weekly_adjclose_crypto50.csv")
CACHE = os.path.join(ROOT, "markets", "crypto", "data", "daily_cache_crypto50.csv")

THRESH = 0.005
KNOWN_EXCEPTIONS = {
    # (coin, label) -> 归因说明; 面板源口径与日线不同且已裁定保留
    # 目前为空: GRAM 2026-06-26 已于 2026-09-18 修复 (1.6 -> 1.778).
}


def _week_label(day_str):
    from datetime import datetime, timedelta, timezone
    dt = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    monday = dt - timedelta(days=dt.weekday())
    return (monday - timedelta(days=3)).strftime("%Y-%m-%d")


class TestDailyReconcile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(CACHE):
            raise unittest.SkipTest(
                "日线缓存不存在 (先跑: python markets/crypto/audit_daily_vs_weekly.py)")
        import csv
        with open(CACHE, newline='', encoding='utf-8') as f:
            rows = list(csv.reader(f))
        header = rows[0]
        cls.daily = {}
        for r in rows[1:]:
            for i, c in enumerate(header[1:]):
                if r[i + 1] != '':
                    cls.daily.setdefault(c, {})[r[0]] = float(r[i + 1])
        import csv as _csv
        with open(PANEL, newline='', encoding='utf-8-sig') as f:
            prows = list(_csv.reader(f))
        cls.coins = prows[0][1:]
        cls.panel = {}
        for r in prows[1:]:
            for i, c in enumerate(cls.coins):
                if r[i + 1] != '':
                    cls.panel[(c, r[0])] = float(r[i + 1])
        # 预聚合: 每币 {周标签: 窗口内最后一个日线收盘} (O(N), 勿在循环里逐格重算)
        cls.weekly = {}
        for coin, days in cls.daily.items():
            wk = {}
            for d, v in days.items():
                wk[_week_label(d)] = v   # 后写覆盖 => 窗口内最后一个交易日
            cls.weekly[coin] = wk
        # 缓存覆盖末日: 周窗口的周日 > 该日 => 未收盘周(快照对快照), 不判错
        all_days = [d for days in cls.daily.values() for d in days]
        cls.cache_max_date = max(all_days)

    def test_panel_matches_daily_aggregate(self):
        from datetime import datetime, timedelta, timezone
        bad = []
        for (coin, lbl), pv in self.panel.items():
            # 未收盘周跳过 (与 audit_daily_vs_weekly.py 同规则, 以缓存覆盖末日为基准)
            wk_end = (datetime.strptime(lbl, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                      + timedelta(days=9)).strftime("%Y-%m-%d")
            if wk_end > self.cache_max_date:
                continue
            av = self.weekly.get(coin, {}).get(lbl)
            if av is None:
                continue
            dev = abs(pv / av - 1) if av else float('inf')
            if dev > THRESH and (coin, lbl) not in KNOWN_EXCEPTIONS:
                bad.append((coin, lbl, pv, av, dev))
        bad.sort(key=lambda x: -x[4])
        self.assertLessEqual(
            len(bad), 0,
            f"面板与日线聚合偏差>{THRESH*100:.1f}% 的格子 {len(bad)} 个, 前5: "
            + "; ".join(f"{c} {l} {p}!={a} ({d*100:.1f}%)" for c, l, p, a, d in bad[:5]))


if __name__ == '__main__':
    unittest.main()
