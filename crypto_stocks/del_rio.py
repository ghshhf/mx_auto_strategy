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
