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
"""删 IMX + 加 RON(映射/JSON/CSV列)。RON: CG='ronin', CMC=14101, GameFi赛道. """
import io
import json

import pandas as pd

print("== 删 IMX + 加 RON 映射 ==")
p = 'crypto_adoption_v2.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace('"GameFi":  [\'GALA\', \'IMX\', \'ILV\'],', '"GameFi":  [\'GALA\', \'ILV\', \'RON\'],')
s = s.replace("    'IMX': {'name': 'Immutable', 'role': 'offense', 'theme': 'GameFi', 'launch': 2021},\n", "")
s = s.replace("    'ILV': {'name': 'Illuvium',", "    'RON': {'name': 'Ronin', 'role': 'offense', 'theme': 'GameFi', 'launch': 2021},\n    'ILV': {'name': 'Illuvium',")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

p = 'data_sources.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace("'IMX': 'immutable-x', 'FIL': 'filecoin', 'CRV': 'curve-dao-token',",
              "'FIL': 'filecoin', 'CRV': 'curve-dao-token', 'RON': 'ronin',")
s = s.replace("'ILV': 8719, 'IMX': 10603, 'JUP': 29210,",
              "'ILV': 8719, 'JUP': 29210,")
s = s.replace("'RENDER': 5690,", "'RENDER': 5690, 'RON': 14101,")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

p = 'sync_crypto_panel.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace("'ILV': 8719,     'IMX': 10603,   'JUP': 29210,",
              "'ILV': 8719,     'JUP': 29210,")
s = s.replace("'RENDER': 5690,", "'RENDER': 5690,    'RON': 14101,")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

p = 'fetch_mcaps.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace("'IMX': 'immutable-x', 'FIL': 'filecoin',",
              "'FIL': 'filecoin',")
s = s.replace("'RENDER': 'render-token',", "'RENDER': 'render-token', 'RON': 'ronin',")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

print("== JSON ==")
d = json.load(io.open('held_weeks.json', encoding='utf-8'))
d = [r for r in d if not (isinstance(r, dict) and r.get('sym') == 'IMX')]
d.append({"sym": "RON", "held": 0, "mcap_usd": None, "sector": "GameFi"})
io.open('held_weeks.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=2))
print(f"  [ok] held_weeks.json ({len(d)} 条, RON已加)")

d = json.load(io.open('mcap_snapshot.json', encoding='utf-8'))
d = [r for r in d if not (isinstance(r, dict) and r.get('sym') == 'IMX')]
io.open('mcap_snapshot.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=2))
print(f"  [ok] mcap_snapshot.json ({len(d)} 条, IMX已删, RON待fetch补)")

print("== CSV 删 IMX 列 ==")
for p in ['data/weekly_adjclose_crypto50.csv',
          'data/weekly_adjclose_crypto50_v3.csv',
          'data/weekly_adjclose_crypto50_10y.csv']:
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    if 'IMX' in df.columns:
        df = df.drop(columns=['IMX'])
        df.to_csv(p, index=True)
    print(f"  [ok] {p}: 共{df.shape[1]}列")

print("\n[done] 映射/JSON/CSV 已处理; RON 数据列待 add_ron_data.py")
