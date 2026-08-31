
# --- [relocated 2026-08-31] 目录重构引导: 等效于在 crypto_stocks/ 根目录下运行 ---
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
"""
rename_ton_gram_csv.py - 将面板 CSV 的 TON 列改名为 GRAM (2026-06-15 TON->Gram 更名)
========================================================================================
仅改表头(标识符), 所有历史价格行原样保留. 同一资产 1:1 无迁移, 价格序列连续.
GRAMUSDT 在 Binance 仅含 2026-06 之后历史, 故更名前的 TON 全历史必须靠此列保留.
"""
import csv, os

HERE = _CS_ROOT  # [relocated] 原指向脚本目录, 迁移后指向 crypto_stocks 根
DATA = os.path.join(HERE, 'data')
FILES = [
    'weekly_adjclose_crypto50.csv',
    'weekly_adjclose_crypto50_v3.csv',
    'weekly_adjclose_crypto50_10y.csv',
]

for fn in FILES:
    path = os.path.join(DATA, fn)
    if not os.path.exists(path):
        print(f"[skip] {fn} 不存在")
        continue
    with open(path, newline='', encoding='utf-8-sig') as f:
        r = csv.reader(f)
        rows = list(r)
    header = rows[0]
    if 'TON' not in header:
        print(f"[skip] {fn} 无 TON 列 (当前列: {header[:3]}...共{len(header)})")
        continue
    idx = header.index('TON')
    header[idx] = 'GRAM'
    rows[0] = header
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        csv.writer(f).writerows(rows)
    n = len(rows) - 1
    print(f"[ok] {fn}: TON->GRAM  行数={n} (历史价格已保留)")
