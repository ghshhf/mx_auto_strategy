
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
import csv, os

DATA = os.path.join(os.path.dirname(__file__), "data")
FILES = [
    "weekly_adjclose_crypto50.csv",
    "weekly_adjclose_crypto50_v3.csv",
    "weekly_adjclose_crypto50_10y.csv",
]
COL = "RIO"

for fn in FILES:
    path = os.path.join(DATA, fn)
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    header = rows[0]
    if COL not in header:
        print(f"[skip] {fn}: 无 {COL} 列 (列数={len(header)})")
        continue
    idx = header.index(COL)
    new_header = header[:idx] + header[idx + 1 :]
    new_rows = [new_header]
    for r in rows[1:]:
        new_rows.append(r[:idx] + r[idx + 1 :] if len(r) > idx else r)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(new_rows)
    print(f"[ok] {fn}: 删除 {COL}  原列数={len(header)} -> 新列数={len(new_header)}")
