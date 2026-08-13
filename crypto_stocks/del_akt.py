# -*- coding: utf-8 -*-
"""删 AKT 全链路: AI+加密/DePIN赛道/COIN_META/CG+CMC映射/held_weeks/mcap_snapshot/3CSV. """
import io
import json

import pandas as pd

print("== 代码/映射文件 ==")
p = 'crypto_adoption_v2.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace('"AI+加密": [\'FET\', \'RENDER\', \'TAO\', \'AKT\'],', '"AI+加密": [\'FET\', \'RENDER\', \'TAO\'],')
s = s.replace('"DePIN":   [\'RENDER\', \'AKT\'],', '"DePIN":   [\'RENDER\'],')
s = s.replace("    'AKT': {'name': 'Akash', 'role': 'offense', 'theme': 'AI+加密', 'launch': 2021},\n", "")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

p = 'data_sources.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace("'AKT': 'akash-network', 'XLM': 'stellar',", "'XLM': 'stellar',")
s = s.replace("'AAVE': 7278, 'ADA': 2010, 'AKT': 7431, 'APT': 21794, 'AR': 5632,",
              "'AAVE': 7278, 'ADA': 2010, 'APT': 21794, 'AR': 5632,")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

p = 'sync_crypto_panel.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace("'AAVE': 7278,   'ADA': 2010,    'AKT': 7431,", "'AAVE': 7278,   'ADA': 2010,")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

p = 'fetch_mcaps.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace("'AKT': 'akash-network', 'XLM': 'stellar', 'LTC': 'litecoin',",
              "'XLM': 'stellar', 'LTC': 'litecoin',")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

print("== JSON 删块 ==")
for j in ['held_weeks.json', 'mcap_snapshot.json']:
    d = json.load(io.open(j, encoding='utf-8'))
    d = [r for r in d if not (isinstance(r, dict) and r.get('sym') == 'AKT')]
    io.open(j, 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=2))
    print(f"  [ok] {j} ({len(d)} 条)")

print("== CSV 删列 ==")
for p in ['data/weekly_adjclose_crypto50.csv',
          'data/weekly_adjclose_crypto50_v3.csv',
          'data/weekly_adjclose_crypto50_10y.csv']:
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    if 'AKT' in df.columns:
        df = df.drop(columns=['AKT'])
        df.to_csv(p, index=True)
    print(f"  [ok] {p}: 共{df.shape[1]}列")

print("\n[done]")
