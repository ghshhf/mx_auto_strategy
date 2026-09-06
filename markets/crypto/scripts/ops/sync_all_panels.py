"""
sync_all_panels.py - 强制走用户 3067 代理, 单次取数增量同步全部三个周K面板.
绕过沙箱注入的 61350 代理(Binance 返回 502), 并对取数失败做指数退避重试.
仅追加末日之后行, 不动历史.

2026-09-07 重构: 三面板(c50/v3/10y)币池相同(32币), 旧实现逐面板各拉一遍行情,
造成 3 倍网络冗余 + 末行 <0.3% 漂移(两次取数间隙价差). 现改为:
  1. 读三面板 header, 取币种并集 + 最早末日;
  2. 对并集**单次** fetch_coin_from (含 5 次退避重试);
  3. 预取结果交给 sync_crypto_panel.sync_file(prefetched=...) 复用,
     各面板按自身 header 列名写回, 与列顺序无关, 末行严格同源一致.
"""
import os
import sys
import time
import csv

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))  # 仓库根
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # markets/crypto/

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


def _read_panel(fname):
    """返回 (coins列表, 末日str). coins = header[1:], 保持文件自身列序."""
    path = os.path.join(sp.DATA, fname)
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    return rows[0][1:], rows[-1][0]


def main():
    # 1) 币种并集 + 最早末日 (任一面板落后都能补齐)
    coins_union = []
    seen = set()
    last_dates = []
    for fn in TARGETS:
        coins, last = _read_panel(fn)
        last_dates.append(last)
        for c in coins:
            if c not in seen:
                seen.add(c)
                coins_union.append(c)
    start_date = min(last_dates)
    print(f"币种并集={len(coins_union)}  各面板末日={last_dates}  取数起点={start_date}")

    # 2) 单次取数 (并集币, 从最早末日开始)
    syms = chd.all_coin_symbols()
    master = {}
    missing_cfg = []
    for coin in coins_union:
        cfg = syms.get(coin)
        if not cfg:
            missing_cfg.append(coin)
            continue
        w = sp.fetch_coin_from(start_date, cfg['binance'], cfg['okx'],
                               cmc_id=sp._CMC_ID_MAP.get(coin))
        master[coin] = {d: p for d, p in w.items() if d > start_date}
        time.sleep(0.05)
    if missing_cfg:
        print(f"  [警告] 无符号映射: {missing_cfg}")

    # 3) 单次结果复用到三面板 (sync_file 内部按各自末日过滤 + 列名写回)
    for fn in TARGETS:
        sp.sync_file(fn, prefetched=master)

    print("\nALL SYNC DONE")


if __name__ == '__main__':
    main()
