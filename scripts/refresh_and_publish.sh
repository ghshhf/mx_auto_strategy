#!/usr/bin/env bash
# mx_auto_strategy — 本地刷新并发布网页
#
# 用途: 在本机(已配置好代理)重新生成 docs/ 下的数据与报告，并推送到 main，
#       随后 GitHub Pages 自动重发。
#
# 前置:
#   1) 已用代理刷新过行情面板(见 README「数据刷新」):
#        - A股: markets/ashare/data/ashare_panel_close_em.csv (tencent_hfq_rebuild.py)
#        - 美股: markets/us/data/weekly_adjclose_full_ext.csv
#        - 加密: markets/crypto/data/weekly_adjclose_crypto50_10y.csv (已提交, 可跳过)
#   2) Git 已配置代理(推送 GitHub 走代理)，或用 SSH。
#
# 用法:
#   bash scripts/refresh_and_publish.sh
set -e
cd "$(dirname "$0")/.."
export PYTHONPATH=.
PY="${PYTHON:-python}"

echo "== 1/4 重新生成各市场 NAV =="
if [ -f markets/crypto/data/weekly_adjclose_crypto50_10y.csv ]; then
  "$PY" markets/crypto/export_nav_crypto.py
else
  echo "跳过: 加密面板缺失"
fi
if [ -f markets/ashare/data/ashare_panel_close_em.csv ]; then
  "$PY" markets/ashare/export_nav.py
else
  echo "跳过: A股面板缺失 (先用代理跑 tencent_hfq_rebuild.py)"
fi
if [ -f markets/us/data/weekly_adjclose_full_ext.csv ]; then
  "$PY" markets/us/export_nav_us.py
else
  echo "跳过: 美股面板缺失 (先用代理刷新 weekly_adjclose_full_ext.csv)"
fi

echo "== 2/4 组合层 =="
"$PY" portfolio_blend.py

echo "== 3/4 刷新报告 =="
"$PY" markets/crypto/build_crypto_opt_report.py

echo "== 4/4 提交并推送 =="
git add docs/
if git diff --cached --quiet; then
  echo "docs/ 无变化，跳过提交。"
  exit 0
fi
git commit -m "chore: refresh web docs (local)"
git push
echo "完成。GitHub Pages 将在 1-2 分钟内自动重发 https://ghshhf.github.io/mx_auto_strategy/"
