import os

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
FILES = [
    'weekly_adjclose_crypto50.csv',
    'weekly_adjclose_crypto50_v3.csv',
    'weekly_adjclose_crypto50_10y.csv',
]

for fn in FILES:
    fp = os.path.join(DATA, fn)
    with open(fp, 'r', encoding='utf-8-sig', newline='') as fh:
        lines = fh.read().splitlines()
    header = lines[0].split(',')
    if 'BEAM' not in header:
        print(f'{fn}: no BEAM column (skip)')
        continue
    idx = header.index('BEAM')
    header.pop(idx)
    out = [','.join(header)]
    for line in lines[1:]:
        if not line.strip():
            out.append(line)
            continue
        parts = line.split(',')
        if len(parts) > idx:
            parts.pop(idx)
        out.append(','.join(parts))
    with open(fp, 'w', encoding='utf-8-sig', newline='') as fh:
        fh.write('\n'.join(out) + '\n')
    print(f'{fn}: dropped BEAM -> {len(header)} cols')
