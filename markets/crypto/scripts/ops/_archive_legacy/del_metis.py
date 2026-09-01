
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
"""删除 METIS 列 (data/ 下 3 个周线面板). 与 add_*.py 同模式, 仅做删除."""
import csv, os

HERE = _CS_ROOT  # [relocated] 原指向脚本目录, 迁移后指向 crypto_stocks 根
DATA = os.path.join(HERE, "data")
TARGET = "METIS"
FILES = [
    "weekly_adjclose_crypto50.csv",
    "weekly_adjclose_crypto50_v3.csv",
    "weekly_adjclose_crypto50_10y.csv",
]

for fn in FILES:
    path = os.path.join(DATA, fn)
    if not os.path.exists(path):
        print(f"[skip] {fn} 不存在")
        continue
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.reader(f)
        rows = list(r)
    header = rows[0]
    if TARGET not in header:
        print(f"[skip] {fn} 无 {TARGET} 列")
        continue
    idx = header.index(TARGET)
    new_header = header[:idx] + header[idx + 1:]
    new_rows = [new_header]
    for row in rows[1:]:
        new_rows.append(row[:idx] + row[idx + 1:])
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(new_rows)
    print(f"[ok] {fn}: 列数 {len(header)} -> {len(new_header)} (删 {TARGET})")
print("完成。")
