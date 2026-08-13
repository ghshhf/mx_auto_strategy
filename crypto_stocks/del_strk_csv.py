"""删 STRK 列：从 3 个面板 CSV 移除 STRK，保留表头/编码/换行格式。"""
import csv, io, os

FILES = [
    'data/weekly_adjclose_crypto50.csv',
    'data/weekly_adjclose_crypto50_v3.csv',
    'data/weekly_adjclose_crypto50_10y.csv',
]
COL = 'STRK'


def drop_col(path):
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    if not rows:
        return 0
    header = rows[0]
    if COL not in header:
        print(f'  [跳过] {path}: 无 {COL} 列')
        return 0
    idx = header.index(COL)
    new_rows = []
    for r in rows:
        new_rows.append(r[:idx] + r[idx + 1:])
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerows(new_rows)
    print(f'  [完成] {path}: {len(header)} -> {len(new_rows[0])} 列 (移除 {COL})')
    return len(header) - len(new_rows[0])


if __name__ == '__main__':
    for p in FILES:
        drop_col(p)
