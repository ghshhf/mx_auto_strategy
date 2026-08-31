# mx_auto_strategy — 统一构建入口 (与 CI / publish 工作流对齐)
#
# 用法:
#   make test     运行单元测试          (CI test job 同款)
#   make lint     全仓语法检查 py3.11   (CI lint job 同款, 共用 scripts/lint_all.py)
#   make docs     离线重算 NAV + 组合层 (publish 工作流 regenerate 步骤同款)
#   make verify   lint + test (推送前自检)
#
# Windows 无 make 时, 直接照抄各 target 下的命令执行即可。
# PYTHON 可指定解释器: make PYTHON="C:/path/to/python.exe" test

PYTHON ?= python

.PHONY: help test lint docs verify

help:
	@echo "make test    - 运行单元测试 (pytest, CI test job 对齐)"
	@echo "make lint    - 全仓语法检查 py3.11 (scripts/lint_all.py, CI lint job 对齐)"
	@echo "make docs    - 离线重算 NAV + 组合层 (publish 工作流对齐; A股/美股面板缺失时自动跳过)"
	@echo "make verify  - lint + test (推送前自检)"

test:
	$(PYTHON) -m pytest tests/ -v --tb=short

lint:
	$(PYTHON) scripts/lint_all.py

docs:
	$(PYTHON) crypto_stocks/export_nav_crypto.py
	if [ -f ashare_backtest/data/ashare_panel_close_em.csv ]; then $(PYTHON) ashare_backtest/export_nav.py; fi
	if [ -f us_stocks/data/weekly_adjclose_full_ext.csv ]; then $(PYTHON) us_stocks/export_nav_us.py; fi
	$(PYTHON) portfolio_blend.py

verify: lint test
