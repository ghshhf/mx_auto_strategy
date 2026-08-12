"""删除 METIS 列 (data/ 下 3 个周线面板). 与 add_*.py 同模式, 仅做删除."""
import csv, os

HERE = os.path.dirname(os.path.abspath(__file__))
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
