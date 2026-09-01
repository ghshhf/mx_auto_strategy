# -*- coding: utf-8 -*-
"""一次性重构脚本: 修正 markets/ 下模块因目录加深一级导致的 '仓库根' 解析。

规则:
- 非 _qa 文件:
    * `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` (2级, 原=根) -> 3级
    * `os.path.dirname(HERE)` (原=根) -> 2级
- _qa 文件 (ashare/_qa/qa_0x):
    * BT = os.path.dirname(HERE) 保留(=模块目录, 移动后仍是 markets/ashare, 正确)
    * ROOT = os.path.dirname(BT) -> 2级(=根)
    * 2级 __file__ 形式保留(=模块目录)
- sync_all_panels.py:
    * ROOT = 3级 HERE -> 4级
    * crypto_stocks 目录行(2级 HERE) 保留
"""
import os
import pathlib

ROOT = pathlib.Path("E:/xmanbian/mx_auto_strategy_repo")
M = ROOT / "markets"

TWO_LEVEL_FILE = "os.path.dirname(os.path.dirname(os.path.abspath(__file__)))"
THREE_LEVEL_FILE = "os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))"
DIRNAME_HERE = "os.path.dirname(HERE)"
TWO_DIRNAME_HERE = "os.path.dirname(os.path.dirname(HERE))"
DIRNAME_BT = "os.path.dirname(BT)"
TWO_DIRNAME_BT = "os.path.dirname(os.path.dirname(BT))"
SYNC_ROOT_OLD = "os.path.dirname(os.path.dirname(os.path.dirname(HERE)))"
SYNC_ROOT_NEW = "os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))"


def is_qa(p: pathlib.Path) -> bool:
    rel = p.relative_to(M).parts
    return len(rel) >= 2 and rel[0] == "ashare" and rel[1] == "_qa"


def is_sync(p: pathlib.Path) -> bool:
    return str(p.as_posix()).endswith("markets/crypto/scripts/ops/sync_all_panels.py")


changed = []
for p in sorted(M.rglob("*.py")):
    if is_sync(p):
        t = p.read_text(encoding="utf-8")
        o = t
        t = t.replace(SYNC_ROOT_OLD, SYNC_ROOT_NEW)
        if t != o:
            p.write_text(t, encoding="utf-8")
            changed.append((str(p), "sync ROOT 3->4"))
        continue
    t = p.read_text(encoding="utf-8")
    o = t
    if is_qa(p):
        t = t.replace(DIRNAME_BT, TWO_DIRNAME_BT)
    else:
        t = t.replace(TWO_LEVEL_FILE, THREE_LEVEL_FILE)
        t = t.replace(DIRNAME_HERE, TWO_DIRNAME_HERE)
    if t != o:
        p.write_text(t, encoding="utf-8")
        changed.append((str(p), "dirname bump"))

print(f"changed {len(changed)} files:")
for c in changed:
    print("  ", c[1], "->", c[0])
