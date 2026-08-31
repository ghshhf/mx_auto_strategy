
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
"""删除 SEI 列：3 个面板 CSV 通用删列(保留 UTF-8-SIG + Unix 换行 + 首列名)。"""
FILES = [
    'data/weekly_adjclose_crypto50.csv',
    'data/weekly_adjclose_crypto50_v3.csv',
    'data/weekly_adjclose_crypto50_10y.csv',
]
TARGET = 'SEI'
for f in FILES:
    raw = open(f, encoding='utf-8-sig').read()
    lines = raw.split('\n')
    header = lines[0].split(',')
    if TARGET not in header:
        print(f'{f}: 无 {TARGET} 列, 跳过')
        continue
    idx = header.index(TARGET)
    new_lines = []
    for ln in lines:
        if ln == '':
            new_lines.append('')
            continue
        parts = ln.split(',')
        new_lines.append(','.join(parts[:idx] + parts[idx + 1:]))
    open(f, 'w', encoding='utf-8-sig').write('\n'.join(new_lines))
    print(f'{f}: 删 {TARGET} 列 -> {len(header) - 1} 列 (原 {len(header)})')
