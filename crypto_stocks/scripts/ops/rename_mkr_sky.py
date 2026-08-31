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
"""MKR -> SKY 全链路改名(MakerDAO 2024-09 改名 Sky, 1MKR=24000SKY).
历史价格列直接改名(收益率序列不变, 回测等价, 同 TON->GRAM 处理).
"""
import io
import json

import pandas as pd


def patch(path, pairs):
    with io.open(path, encoding='utf-8') as f:
        s = f.read()
    for old, new in pairs:
        if old not in s:
            print(f"  [warn] {path}: 未找到 {old!r}")
        s = s.replace(old, new)
    with io.open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(s)
    print(f"  [ok] {path}")


print("== 代码/映射文件 ==")
patch('crypto_adoption_v2.py', [
    ("'MKR',", "'SKY',"),                      # DeFi 赛道
    ("'MKR': {'name': 'Maker',", "'SKY': {'name': 'Sky',"),  # COIN_META
])
patch('data_sources.py', [
    ("'MKR': 'maker'", "'SKY': 'sky'"),        # COINGECKO_IDS
    ("'MKR': 1518", "'SKY': 33038"),           # CMC_IDS (SKY cmc id=33038)
])
patch('sync_crypto_panel.py', [
    ("'MKR': 1518", "'SKY': 33038"),
])
patch('fetch_mcaps.py', [
    ("'MKR': 'maker'", "'SKY': 'sky'"),
])

print("== held_weeks.json ==")
with io.open('held_weeks.json', encoding='utf-8') as f:
    d = json.load(f)
for r in d:
    if isinstance(r, dict) and r.get('sym') == 'MKR':
        r['sym'] = 'SKY'
        r['mcap_usd'] = 1300000000.0
with io.open('held_weeks.json', 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
print("  [ok] held_weeks.json MKR->SKY")

print("== mcap_snapshot.json ==")
with io.open('mcap_snapshot.json', encoding='utf-8') as f:
    d = json.load(f)
for r in d:
    if isinstance(r, dict) and r.get('sym') == 'MKR':
        r['sym'] = 'SKY'
        r['mcap'] = 1300000000
        r['yi'] = 13.0
        r['price'] = 0.056
with io.open('mcap_snapshot.json', 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
print("  [ok] mcap_snapshot.json MKR->SKY(市值$1.3B)")

print("== CSV 列改名 ==")
for path in ['data/weekly_adjclose_crypto50.csv',
             'data/weekly_adjclose_crypto50_v3.csv',
             'data/weekly_adjclose_crypto50_10y.csv']:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if 'MKR' in df.columns:
        df = df.rename(columns={'MKR': 'SKY'})
        df.to_csv(path, index=True)
    print(f"  [ok] {path}: SKY列存在={'SKY' in df.columns}, 共{df.shape[1]}列")

print("\n[done]")
