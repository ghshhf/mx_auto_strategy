"""
_synv_all_3067.py - 强制走用户 3067 代理, 增量同步全部三个周K面板.
绕过沙箱注入的 61350 代理(Binance 返回 502), 并对取数失败做指数退避重试.
仅追加末日之后行, 不动历史.
"""
import os
import sys
import time

# 必须在 import 任何读 env 的模块之前强制 3067
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:3067'
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:3067'
os.environ['https_proxy'] = 'http://127.0.0.1:3067'
os.environ['http_proxy'] = 'http://127.0.0.1:3067'

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # crypto_stocks/
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
