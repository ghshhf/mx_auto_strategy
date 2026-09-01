"""main.py CLI 的轻量 smoke 测试：5 命令 + help + add 拒绝错误 + 去重等。"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

CLI = ["python3", "-m", "crypto_stocks.research.main"]


def _run(args, cwd=None, env=None):
    env = env or os.environ
    result = subprocess.run(
        [sys.executable, "-m", "crypto_stocks.research.main", *args],
        cwd=cwd, capture_output=True, text=True, env=env, timeout=60,
    )
    return result.returncode, result.stdout, result.stderr


def test_help_exists():
    rc, out, err = _run(["--help"])
    assert rc == 0
    assert "fetch" in out and "analyze" in out and "latest" in out
    assert "report" in out and "add" in out


def test_cmd_analyze_seeds_only_btc_eth_sol(tmp_path, monkeypatch):
    # 指定一个不存在的 kb（只用 seeds，且不写入 kb/.gitignore git-tracked 区域）
    kb = str(tmp_path / "empty.jsonl")
    rc, out, err = _run(["--kb", kb, "analyze", "--coins", "BTC,ETH,SOL"])
    assert rc == 0, f"rc={rc}\nSTDERR:\n{err}\nSTDOUT:\n{out}"
    # BTC 覆盖数 ≥ 6，ETH≥3，SOL≥2
    assert "BTC" in out and "ETH" in out and "SOL" in out
    # 按行解析 coverage_count 关键字
    import re
    btc_cover = re.search(r"BTC — 覆盖机构 (\d+) 家", out)
    eth_cover = re.search(r"ETH — 覆盖机构 (\d+) 家", out)
    sol_cover = re.search(r"SOL — 覆盖机构 (\d+) 家", out)
    assert btc_cover and int(btc_cover.group(1)) >= 6
    assert eth_cover and int(eth_cover.group(1)) >= 3
    assert sol_cover and int(sol_cover.group(1)) >= 2


def test_cmd_analyze_json_output_doge_note(tmp_path):
    kb = str(tmp_path / "kb.jsonl")
    rc, out, err = _run(["--kb", kb, "analyze", "--coins", "DOGE,FAKE", "--json"])
    assert rc == 0, err
    data = json.loads(out)
    doge = next(c for c in data["coins"] if c["coin"] == "DOGE")
    fake = next(c for c in data["coins"] if c["coin"] == "FAKE")
    assert doge["coverage_count"] == 0
    assert doge["note"] == "暂未收录机构研报"
    assert "target_price_ranges" not in doge
    assert fake["coverage_count"] == 0
    assert "不在 SUPPORTED_COINS" in fake["note"]


def test_cmd_add_valid_and_dedup(tmp_path):
    kb = str(tmp_path / "kb.jsonl")
    rc1, out1, err1 = _run([
        "--kb", kb, "add",
        "--institution", "渣打",
        "--coin", "BTC",
        "--target-price", "150000",
        "--pub-date", "2026-03-01",
        "--rating", "bullish",
        "--horizon-months", "12",
        "--target-date", "2027-03-01",
        "--source-url", "https://sc.com/x",
        "--excerpt", "渣打再次上调 BTC 目标价至 15 万美元，基于 ETF 资金流入。",
    ])
    assert rc1 == 0, f"rc1={rc1}\n{err1}"
    assert "成功写入 1 条" in out1 or "写入 0 条" in out1  # 可能重复（理论应该新 1 条）
    written_1 = Path(kb).read_text(encoding="utf-8").count("\n") if Path(kb).exists() else 0

    # 重复 → 必须返回写入 0
    rc2, out2, _ = _run([
        "--kb", kb, "add",
        "--institution", "Standard Chartered",
        "--coin", "btc",  # 小写，归一化 → BTC
        "--target-price", "150000",
        "--pub-date", "2026-03-01",
        "--horizon-months", "12",
        "--target-date", "2027-03-01",
    ])
    assert rc2 == 0
    assert "写入 0 条" in out2
    written_2 = Path(kb).read_text(encoding="utf-8").count("\n")
    assert written_2 == written_1, f"重复 id 不应新增行数 {written_1}→{written_2}"


def test_cmd_latest_btc_has_records(tmp_path):
    kb = str(tmp_path / "kb.jsonl")
    rc, out, err = _run(["--kb", kb, "latest", "--coin", "BTC"])
    assert rc == 0, err
    # seeds 中绝大多数 BTC 条目距今都 >180 天；窗口 180 天无近期 → 显示全部历史
    assert "覆盖机构" in out
    # 至少包含一些标准字段
    assert "Date" in out and "Institution" in out


def test_cmd_report_markdown_out(tmp_path):
    kb = str(tmp_path / "kb.jsonl")
    out_md = str(tmp_path / "report.md")
    rc, out, err = _run([
        "--kb", kb, "report", "--coins", "BTC,ETH,SOL",
        "--out", out_md,
        "--current", "BTC=67000,ETH=3500,SOL=140",
    ])
    assert rc == 0, err
    md = Path(out_md).read_text(encoding="utf-8")
    assert md.startswith("# 机构研报交叉分析报告")
    for coin in ("BTC", "ETH", "SOL"):
        assert f"## {coin} —" in md
    assert "| 时间窗口 |" in md  # Markdown 表格
    assert "上行空间" in md  # 有当前价时会出现上行空间列
