"""
_synv_all_3067.py - 强制走用户 3067 代理, 增量同步全部三个周K面板.
绕过沙箱注入的 61350 代理(Binance 返回 502), 并对取数失败做指数退避重试.
仅追加末日之后行, 不动历史.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # 仓库根
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # crypto_stocks/

# 2026-09-01: 原逻辑用 os.environ[...] = '3067' **强制覆盖** 全部代理环境变量,
# 那是为绕过沙箱注入的 61350 (对 Binance 返 502) 的临时手段, 但副作用是会盖掉
# 用户/CI 已配好的有效代理。现 sync_crypto_panel / crypto_hist_data 已改由
# net_config 存活探测解析, 本脚本只需补齐缺失的环境变量即可 (setdefault 语义)。
import net_config  # noqa: E402

net_config.apply_env(force=False)

import sync_crypto_panel as sp  # noqa: E402
import crypto_hist_data as chd  # noqa: E402

print(f"[代理] chd={chd._PROXY}  sp={sp._PROXY}", file=sys.stderr)

# ---- 对取数失败做重试 (绕过偶发 502) ----
_orig_fetch = sp.fetch_coin_from


def _retry_fetch(start_date, binance_sym, okx_sym, cmc_id=None):
    last = {}
    for attempt in range(5):
        try:
            w = _orig_fetch(start_date, binance_sym, okx_sym, cmc_id=cmc_id)
            if w:
                return w
        except Exception as e:  # noqa: BLE001
            print(f"    [retry {attempt}] {binance_sym}: {e}", file=sys.stderr)
        time.sleep(1.5 * (attempt + 1))
    return last


sp.fetch_coin_from = _retry_fetch

TARGETS = [
    'weekly_adjclose_crypto50.csv',
    'weekly_adjclose_crypto50_v3.csv',
    'weekly_adjclose_crypto50_10y.csv',
]

for fn in TARGETS:
    sp.sync_file(fn)

print("\nALL SYNC DONE")
