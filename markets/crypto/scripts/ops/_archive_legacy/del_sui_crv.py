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
"""del_sui_crv.py - 删 SUI + CRV (池定义/映射/JSON/CSV列), 并下调 assert 下限 40->38.
对照仓库既有 del_*.py 惯例 (如 del_imx_add_ron.py). 不改 OPTIONS_AVAILABLE_COINS
(那描述的是真实交易所期权市场上架情况, 与组合持仓无关).
"""
import io
import json

import pandas as pd

HERE = '.'


# ---------- 1) crypto_adoption_v2.py (池定义 + 断言) ----------
p = 'crypto_adoption_v2.py'
lines = io.open(p, encoding='utf-8').read().splitlines()
out = []
for ln in lines:
    s = ln
    # THEME_COINS 列表内删币
    if '"L1公链":' in s:
        s = s.replace("'SUI', ", '')
    if '"DeFi":' in s:
        s = s.replace("'CRV', ", '')
    if '"DeFi借贷":' in s:
        s = s.replace("'CRV', ", '')
    if '"DEX":' in s:
        s = s.replace("'CRV', ", '')
    # COIN_META 条目整行删除
    if s.strip().startswith("'SUI': {") or s.strip().startswith("'CRV': {"):
        continue
    # 断言下限 40 -> 38 (删2币后进攻=39)
    if 'assert len(OFFENSE_COINS)' in s:
        s = s.replace('>= 40', '>= 38').replace('不足 40', '不足 38')
    # 注释同步 (2026-08-13 45->40; 2026-08-17 删SUI/CRV 再降至38)
    if '下调至 40;' in s:
        s = s.replace('下调至 40;', '下调至 40; 2026-08-17 删SUI/CRV 再降至 38;')
    out.append(s)
io.open(p, 'w', encoding='utf-8', newline='').write('\n'.join(out) + '\n')
print('[ok]', p)


# ---------- 2) 映射文件 (面板重建用) ----------
def clean_map(p, rules):
    lines = io.open(p, encoding='utf-8').read().splitlines()
    out = []
    for ln in lines:
        s = ln
        for contains, remove in rules:
            if contains in s and remove in s:
                s = s.replace(remove, '')
        out.append(s)
    io.open(p, 'w', encoding='utf-8', newline='').write('\n'.join(out) + '\n')
    print('[ok]', p)


clean_map('data_sources.py', [
    ("'SUI': 'sui',", "'SUI': 'sui', "),
    ("'SUI': 20947,", "'SUI': 20947, "),
    ("'CRV': 'curve-dao-token',", "'CRV': 'curve-dao-token', "),
    ("'CRV': 6538,", "'CRV': 6538, "),
])
clean_map('sync_crypto_panel.py', [
    ("'SUI': 20947,", "'SUI': 20947, "),
    ("'CRV': 6538,", "'CRV': 6538, "),
])
clean_map('fetch_mcaps.py', [
    ("'SUI': 'sui',", "'SUI': 'sui', "),
    ("'CRV': 'curve-dao-token',", "'CRV': 'curve-dao-token', "),
])


# ---------- 3) CSV 面板删列 ----------
for p in ['data/weekly_adjclose_crypto50.csv',
          'data/weekly_adjclose_crypto50_v3.csv',
          'data/weekly_adjclose_crypto50_10y.csv']:
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    dropped = [c for c in ('SUI', 'CRV') if c in df.columns]
    if dropped:
        df = df.drop(columns=dropped)
        df.to_csv(p, index=True)
    print(f'[ok] {p}: 删{dropped} -> 共{df.shape[1]}列')


# ---------- 4) JSON 清理 (防御式 load) ----------
for p in ['held_weeks.json', 'mcap_snapshot.json']:
    try:
        d = json.load(io.open(p, encoding='utf-8'))
        before = len(d)
        d = [r for r in d if not (isinstance(r, dict) and r.get('sym') in ('SUI', 'CRV'))]
        io.open(p, 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=2))
        print(f'[ok] {p}: {before} -> {len(d)} 条 (删 SUI/CRV)')
    except Exception as e:
        print(f'[skip] {p}: json 解析失败, 跳过 ({e})')

print('\n[done] SUI/CRV 已全量删除 (池定义/映射/JSON/CSV)')
