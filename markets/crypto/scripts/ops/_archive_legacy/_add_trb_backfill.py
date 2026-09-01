
# --- [relocated 2026-08-31] 目录重构引导: 等效于在 markets/crypto/ 根目录下运行 ---
import os as _os, sys as _sys
_SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))
_d = _SCRIPT_DIR
while _os.path.basename(_d) != 'crypto_stocks' and _d != _os.path.dirname(_d):
    _d = _os.path.dirname(_d)
_CS_ROOT = _d if _os.path.basename(_d) == 'crypto_stocks' else _SCRIPT_DIR
if _CS_ROOT != _SCRIPT_DIR:
    if _CS_ROOT not in _sys.path:
        _sys.path.insert(0, _CS_ROOT)
    _os.chdir(_CS_ROOT)
# --- [relocated] 引导结束 ---
"""回填 TRB (Tellor) 历史周K到加密面板 CSV (Binance 主源, OKX/CMC 兜底).

对齐规则: 用项目现有 weekly_adjclose_crypto50.csv / _10y.csv 的日期列,
为 TRB 抓取全历史周线, 作为新列按日期对齐插入; 上市前留空.

用法:
  python _add_trb_backfill.py
"""
import os
import csv
import sys

HERE = _CS_ROOT  # [relocated] 原指向脚本目录, 迁移后指向 crypto_stocks 根
DATA = os.path.join(HERE, 'data')
sys.path.insert(0, HERE)
import crypto_hist_data as chd  # noqa: E402
import sync_crypto_panel as sc  # noqa: E402 (提供 CMC 兜底)

FILES = ['weekly_adjclose_crypto50.csv', 'weekly_adjclose_crypto50_10y.csv']
COIN = 'TRB'


def fetch_trb_weekly():
    """三级降级: Binance -> OKX -> CMC."""
    syms = chd.all_coin_symbols()
    cfg = syms[COIN]
    cmc_id = sc._CMC_ID_MAP.get(COIN)
    # Level 1: Binance
    rows = chd.fetch_binance_full(cfg['binance'], cfg['start'])
    if len(rows) >= 2:
        w = chd.rows_to_weekly_close(rows)
        print(f"  [Binance] {COIN}: {len(w)} 周 (首 {min(w)} ~ 末 {max(w)})")
        return w
    # Level 2: OKX
    print(f"  Binance 不足({len(rows)}), 试 OKX ...")
    rows = chd.fetch_okx_weekly(cfg['okx'], cfg['start'])
    if len(rows) >= 2:
        w = chd.rows_to_weekly_close(rows)
        print(f"  [OKX] {COIN}: {len(w)} 周")
        return w
    # Level 3: CMC
    if cmc_id and sc._CMC_KEY:
        w = sc.fetch_cmc_weekly(cmc_id, cfg['start'])
        if w:
            print(f"  [CMC] {COIN}: {len(w)} 周")
            return w
    print(f"  [警告] {COIN} 三源均不足")
    return {}


def backfill(fname, trb_w):
    path = os.path.join(DATA, fname)
    if not os.path.exists(path):
        print(f"[跳过] {fname} 不存在")
        return
    with open(path, encoding='utf-8-sig', newline='') as f:
        r = list(csv.reader(f))
    header, body = r[0], r[1:]
    if COIN in header:
        print(f"  {fname}: {COIN} 已存在, 跳过")
        return
    dates = [row[0] for row in body]
    col = [('' if d not in trb_w else trb_w[d]) for d in dates]
    header.append(COIN)
    for i, row in enumerate(body):
        row.append(col[i])
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f).writerows([header] + body)
    n = sum(1 for v in col if v != '')
    print(f"  -> {fname}: 追加 {COIN} 列, 非空 {n}/{len(dates)} 周, 现共 {len(header) - 1} 币")


if __name__ == '__main__':
    trb_w = fetch_trb_weekly()
    if not trb_w:
        print("无数据, 中止。")
        sys.exit(1)
    for fn in FILES:
        print(f"\n=== {fn} ===")
        backfill(fn, trb_w)
    print("\n完成。")
