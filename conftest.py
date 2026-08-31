# -*- coding: utf-8 -*-
"""pytest 根 conftest: 把仓库根加入 sys.path。

使 `pytest tests/` 无需 PYTHONPATH=. 即可 import 项目模块
(与 CI 中 PYTHONPATH=. 等效; 两者共存无副作用)。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
