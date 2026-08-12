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
