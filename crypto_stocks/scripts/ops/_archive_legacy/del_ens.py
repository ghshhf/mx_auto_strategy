# -*- coding: utf-8 -*-

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
"""删 ENS 全链路: 基础设施赛道/COIN_META/CG+CMC映射/held_weeks/mcap_snapshot/3CSV. """
import io
import json

import pandas as pd

print("== 代码/映射文件 ==")
# crypto_adoption_v2.py
p = 'crypto_adoption_v2.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace('"基础设施": [\'LINK\', \'ENS\', \'API3\', \'GRT\'],',
              '"基础设施": [\'LINK\', \'API3\', \'GRT\'],')
s = s.replace("    'ENS': {'name': 'ENS', 'role': 'offense', 'theme': '\u57fa\u7840\u8bbe\u65bd', 'launch': 2021},\n", "")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

# data_sources.py
p = 'data_sources.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace("'DYDX': 'dydx', 'ENS': 'ethereum-name-service', 'GALA': 'gala', 'ZEC': 'zcash',",
              "'DYDX': 'dydx', 'GALA': 'gala', 'ZEC': 'zcash',")
s = s.replace("'ENS': 13855, 'ETH': 1027,", "'ETH': 1027,")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

# sync_crypto_panel.py
p = 'sync_crypto_panel.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace("'DYDX': 28324,   'ENS': 13855,    'ETH': 1027,", "'DYDX': 28324,    'ETH': 1027,")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

# fetch_mcaps.py
p = 'fetch_mcaps.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace("'ENS': 'ethereum-name-service', 'GALA': 'gala', 'ZEC': 'zcash',",
              "'GALA': 'gala', 'ZEC': 'zcash',")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

print("== JSON 删块 ==")
for j in ['held_weeks.json', 'mcap_snapshot.json']:
    d = json.load(io.open(j, encoding='utf-8'))
    d = [r for r in d if not (isinstance(r, dict) and r.get('sym') == 'ENS')]
    io.open(j, 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=2))
    print(f"  [ok] {j} ({len(d)} 条)")

print("== CSV 删列 ==")
for p in ['data/weekly_adjclose_crypto50.csv',
          'data/weekly_adjclose_crypto50_v3.csv',
          'data/weekly_adjclose_crypto50_10y.csv']:
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    if 'ENS' in df.columns:
        df = df.drop(columns=['ENS'])
        df.to_csv(p, index=True)
    print(f"  [ok] {p}: 共{df.shape[1]}列")

print("\n[done]")
