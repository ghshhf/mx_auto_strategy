# -*- coding: utf-8 -*-

# --- [relocated 2026-08-31] 目录重构引导: 等效于在 markets/crypto/ 根目录下运行 ---
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
"""删 POLYX 全链路: RWA赛道/COIN_META/CG+CMC映射/held_weeks/mcap_snapshot/3CSV. """
import io
import json

import pandas as pd

print("== 代码/映射文件 ==")
p = 'crypto_adoption_v2.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace('"RWA":     [\'ONDO\', \'CFG\', \'POLYX\'],', '"RWA":     [\'ONDO\', \'CFG\'],')
s = s.replace("    'POLYX': {'name': 'Polymesh', 'role': 'offense', 'theme': 'RWA', 'launch': 2022},\n", "")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

p = 'data_sources.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace("'CFG': 'centrifuge', 'POLYX': 'polymesh',", "'CFG': 'centrifuge',")
s = s.replace("'POLYX': 20362, 'RENDER': 5690,", "'RENDER': 5690,")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

p = 'sync_crypto_panel.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace("'POLYX': 20362,  'RENDER': 5690,", "'RENDER': 5690,")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

p = 'fetch_mcaps.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace("'CFG': 'centrifuge', 'POLYX': 'polymesh',", "'CFG': 'centrifuge',")
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print(f"  [ok] {p}")

print("== JSON 删块 ==")
for j in ['held_weeks.json', 'mcap_snapshot.json']:
    d = json.load(io.open(j, encoding='utf-8'))
    d = [r for r in d if not (isinstance(r, dict) and r.get('sym') == 'POLYX')]
    io.open(j, 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=2))
    print(f"  [ok] {j} ({len(d)} 条)")

print("== CSV 删列 ==")
for p in ['data/weekly_adjclose_crypto50.csv',
          'data/weekly_adjclose_crypto50_v3.csv',
          'data/weekly_adjclose_crypto50_10y.csv']:
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    if 'POLYX' in df.columns:
        df = df.drop(columns=['POLYX'])
        df.to_csv(p, index=True)
    print(f"  [ok] {p}: 共{df.shape[1]}列")

print("\n[done]")
