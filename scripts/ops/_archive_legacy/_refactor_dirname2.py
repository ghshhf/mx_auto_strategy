# -*- coding: utf-8 -*-
"""一次性重构脚本(三): 修正用 BASE / ROOT 变量名存'模块目录'、再 dirname 取'仓库根'的写法。

移动后模块目录变成 markets/<mod> (2级深), 原本 dirname(模块目录)=根 现在变成 dirname=markets,
需统一多算一级 -> dirname(dirname(变量))。

覆盖:
- os.path.dirname(BASE)  -> os.path.dirname(os.path.dirname(BASE))   (13处, BASE=模块目录)
- os.path.dirname(ROOT)  -> os.path.dirname(os.path.dirname(ROOT))   (3处, 仅 crypto 脚本 REPO 行, ROOT=模块目录)
"""
import pathlib

ROOT = pathlib.Path("E:/xmanbian/mx_auto_strategy_repo")
M = ROOT / "markets"

O_DIRNAME_BASE = "os.path.dirname(BASE)"
N_DIRNAME_BASE = "os.path.dirname(os.path.dirname(BASE))"
O_DIRNAME_ROOT = "os.path.dirname(ROOT)"
N_DIRNAME_ROOT = "os.path.dirname(os.path.dirname(ROOT))"

changed = []
for p in sorted(M.rglob("*.py")):
    t = p.read_text(encoding="utf-8")
    o = t
    t = t.replace(O_DIRNAME_BASE, N_DIRNAME_BASE)
    t = t.replace(O_DIRNAME_ROOT, N_DIRNAME_ROOT)
    if t != o:
        p.write_text(t, encoding="utf-8")
        n_base = o.count(O_DIRNAME_BASE)
        n_root = o.count(O_DIRNAME_ROOT)
        changed.append((str(p), n_base, n_root))

print(f"changed {len(changed)} files:")
for c in changed:
    print(f"  base={c[1]} root={c[2]} -> {c[0]}")
