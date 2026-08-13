# -*- coding: utf-8 -*-
"""删 GMX 全链路: 链上永续交易所赛道/COIN_META/fetch_mcaps CG/held_weeks/mcap_snapshot/3CSV.
注: GMX 原无 CMC id 映射, 不动 CMC 文件. 删后链上永续剩 DYDX 单币.
"""
import io
import json

import pandas as pd

print("== 代码/映射文件 ==")
p = 'crypto_adoption_v2.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace('"链上永续交易所": [\'DYDX\', \'GMX\'],', '"链上永续交易所": [\'DYDX\'],')
s = s.replace("    'GMX': {'name': 'GMX', 'role': 'offense', 'theme': '链上永续交易所', 'launch': 2021},\n", "")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

p = 'fetch_mcaps.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace("'GMX': 'gmx', 'API3': 'api3',", "'API3': 'api3',")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

print("== JSON 删块 ==")
for j in ['held_weeks.json', 'mcap_snapshot.json']:
    d = json.load(io.open(j, encoding='utf-8'))
    d = [r for r in d if not (isinstance(r, dict) and r.get('sym') == 'GMX')]
    io.open(j, 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=2))
    print(f"  [ok] {j} ({len(d)} 条)")

print("== CSV 删列 ==")
for p in ['data/weekly_adjclose_crypto50.csv',
          'data/weekly_adjclose_crypto50_v3.csv',
          'data/weekly_adjclose_crypto50_10y.csv']:
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    if 'GMX' in df.columns:
        df = df.drop(columns=['GMX'])
        df.to_csv(p, index=True)
    print(f"  [ok] {p}: 共{df.shape[1]}列")

print("\n[done]")
