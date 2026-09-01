# -*- coding: utf-8 -*-
"""一次性重构脚本(二): 模块路径字符串替换。

斜杠形式(路径串):
  crypto_stocks/ -> markets/crypto/
  ashare_backtest/ -> markets/ashare/
  us_stocks/ -> markets/us/
点形式(import 串, 仅 tests):
  crypto_stocks. -> markets.crypto.
"""
import pathlib

ROOT = pathlib.Path("E:/xmanbian/mx_auto_strategy_repo")

SLASH = [
    ("crypto_stocks/", "markets/crypto/"),
    ("ashare_backtest/", "markets/ashare/"),
    ("us_stocks/", "markets/us/"),
]
DOT = [("crypto_stocks.", "markets.crypto.")]

# 斜杠替换目标文件集合
slash_files = []
slash_files += ROOT.glob(".github/workflows/*.yml")
slash_files += [ROOT / "Makefile", ROOT / "scripts/refresh_and_publish.sh",
                ROOT / "portfolio_blend.py"]
slash_files += ROOT.glob("docs/**/*.md")
slash_files += ROOT.glob("*.md")
slash_files += ROOT.glob("markets/**/*.py")
slash_files += ROOT.glob("tests/**/*.py")

# 点形式仅 tests
dot_files = list(ROOT.glob("tests/**/*.py"))

changed = []


def apply_replace(p, repls):
    try:
        t = p.read_text(encoding="utf-8")
    except Exception as e:
        print("SKIP", p, e)
        return
    o = t
    for a, b in repls:
        t = t.replace(a, b)
    if t != o:
        p.write_text(t, encoding="utf-8")
        changed.append(str(p))


for p in slash_files:
    if p.is_file():
        apply_replace(p, SLASH)

for p in dot_files:
    apply_replace(p, DOT)

print(f"path-string replaced in {len(changed)} files:")
for c in changed:
    print("  ", c)
