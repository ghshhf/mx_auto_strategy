# -*- coding: utf-8 -*-
"""归档区 pytest conftest: 把已归档的 A股 live 脚本目录加入 sys.path。

使 `python -m pytest _archive/ashare_live/tests/` 仍能 import 被归档的模块。
CI 与 `make test` 均不执行本目录，此文件仅用于本地追溯性运行。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))  # 仓库根

for p in (_HERE, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
