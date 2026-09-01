# -*- coding: utf-8 -*-
"""L1公链 拆分出「支付链」细分赛道(用户优化方向: 单赛道多币→更细分类).
支付链 = XLM(Stellar跨境支付)/TRX(Tron稳定币结算)/GRAM(TON支付生态)/LTC(数字白银支付)
机制: 独立赛道权重 → 不再被 SOL/ADA 的通用L1叙事压死, 弱币有独立被选机会.
"""
import io

p = 'crypto_adoption_v2.py'
s = io.open(p, encoding='utf-8').read()

# 1. THEME_COINS: L1 12币 -> L1公链 8 + 支付链 4
old_l1 = '"L1公链":  [\'SOL\', \'ADA\', \'AVAX\', \'DOT\', \'NEAR\', \'APT\', \'SUI\', \'GRAM\', \'TRX\', \'INJ\', \'XLM\', \'LTC\'],'
new_l1 = ('"L1公链":  [\'SOL\', \'ADA\', \'AVAX\', \'SUI\', \'INJ\', \'DOT\', \'NEAR\', \'APT\'],\n'
          '    "支付链":  [\'XLM\', \'TRX\', \'GRAM\', \'LTC\'],  # 2026-08-13 从L1拆分: 稳定币结算/跨境支付叙事')
assert old_l1 in s, "L1 行未找到"
s = s.replace(old_l1, new_l1)

# 2. PHASE_HISTORY 加「支付链」叙事周期
old_ph = '"RWA":      [(2023, 2024, "early"), (2025, 2026, "accelerating")],'
new_ph = ('"RWA":      [(2023, 2024, "early"), (2025, 2026, "accelerating")],\n'
          '    "支付链":   [(2017, 2019, "early"), (2020, 2022, "saturating"), (2023, 2026, "accelerating")],'
          '  # 2026-08-13新增: 第一波支付币(2017-19) -> DeFi时代退潮 -> 稳定币结算加速')
assert old_ph in s, "PHASE_HISTORY RWA 行未找到"
s = s.replace(old_ph, new_ph)

# 3. CRYPTO_THEMES 加「支付链」条目(多行格式, 插在 RWA 条目前)
lines = s.split('\n')
rwa_idx = None
for i, line in enumerate(lines):
    if line.strip() == '"RWA": {':
        rwa_idx = i
        break
assert rwa_idx is not None, "RWA 条目行未找到"
pay_block = ('    # ---- 支付链 (2026-08-13 从L1拆分: 稳定币结算/跨境支付) ----\n'
             '    "支付链": {\n'
             '        "penetration": 8, "phase": "accelerating", "as_of": "2026Q3",\n'
             '        "note": "稳定币结算+跨境支付加速, XLM/TRX/LTC/GRAM 支付叙事",\n'
             '    },')
lines.insert(rwa_idx, pay_block)
s = '\n'.join(lines)

# 4. COIN_META: 4 币 theme L1公链 -> 支付链 (按行处理)
lines = s.split('\n')
changed = []
for i, line in enumerate(lines):
    for c in ['XLM', 'TRX', 'GRAM', 'LTC']:
        if f"'{c}': {{'name':" in line and "'theme': 'L1公链'" in line:
            lines[i] = line.replace("'theme': 'L1公链'", "'theme': '支付链'")
            changed.append(c)
s = '\n'.join(lines)
assert len(changed) == 4, f"COIN_META 替换数异常: {changed}"
print("  COIN_META theme 更新:", changed)

io.open(p, 'w', encoding='utf-8', newline='').write(s)
print("[ok] 拆分完成: L1公链 8币 + 支付链 4币")

# 校验
import sys
sys.path.insert(0, '.')
import importlib
import crypto_adoption_v2 as ca2
importlib.reload(ca2)
print("L1公链:", ca2.THEME_COINS['L1公链'])
print("支付链:", ca2.THEME_COINS['支付链'])
print("支付链相位历史:", ca2.PHASE_HISTORY.get('支付链'))
print("支付链 2026 multiplier:", ca2.get_adoption('支付链', 2026)['multiplier'])
print("offense n=", len(ca2.OFFENSE_COINS))
