#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""统一语法检查入口 — Makefile `make lint` 与 CI lint job 共用。

优先使用 ruff --target-version py311 --select E9:
  - E9 = 语法错误族 (ruff >= 0.16 中 E999 已并入, 语法错误始终报告)
  - 能捕获 py3.11 不兼容语法 (如 PEP 701 f-string 嵌套同引号, 2026-08-31 P0 事故根因)
  - 输出精确的 文件名:行号:列号
ruff 不可用时回退为 compile() 全仓编译 (仅当解释器恰为 3.11 时才有同等检出力)。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUDE_DIRS = {".git", "__pycache__", "node_modules"}


def find_py_files():
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                files.append(os.path.join(dirpath, fn))
    return files


def run_ruff():
    """返回 (可用, 失败数)。"""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--target-version", "py311",
             "--select", "E9", "--no-cache", ROOT],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except Exception:
        return False, 0
    if proc.returncode == 0:
        print("[ruff py311] 全仓语法检查通过 (%d 个 .py)" % len(find_py_files()))
        return True, 0
    out = (proc.stdout or "") + (proc.stderr or "")
    print(out)
    fails = sum(1 for line in out.splitlines() if "invalid-syntax" in line or "E9" in line)
    return True, max(fails, 1)


def run_compile_fallback():
    files = find_py_files()
    failed = 0
    for path in files:
        try:
            with open(path, "rb") as f:
                src = f.read()
            compile(src, path, "exec")
        except SyntaxError as e:
            failed += 1
            rel = os.path.relpath(path, ROOT)
            print("SYNTAX ERROR: %s:%s:%s %s" % (rel, e.lineno, e.offset, e.msg))
        except Exception as e:  # 解码/IO 异常也视为失败
            failed += 1
            print("READ ERROR: %s %s" % (os.path.relpath(path, ROOT), e))
    print("[compile fallback] %d 个 .py 检查完成, %d 个失败" % (len(files), failed))
    if sys.version_info[:2] != (3, 11):
        print("!! 注意: 当前解释器 %s 非 3.11, py3.11 专属语法(PEP 701 等)可能漏检, 建议安装 ruff。"
              % sys.version.split()[0])
    return failed


def main():
    available, fails = run_ruff()
    if available:
        sys.exit(0 if fails == 0 else 1)
    failed = run_compile_fallback()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
