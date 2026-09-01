#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 docs/data/reports.json —— 门户「报告中心」的唯一数据源。

设计目的
--------
此前 docs/index.html 的报告清单是硬编码数组, 新生成的报告必须手工改 HTML 才能上线,
导致 31 个报告躺在 docs/ 之外、网页端打不开。改为自动扫描后:

  - 任何落在 docs/reports/<market>/ 下的 .html 都会自动出现在门户
  - 任何落在 docs/ 下的 .md 都会自动出现在「文档」分组 (经 report.html 渲染)
  - 新增/删除报告无需改动前端代码

扫描范围
--------
  docs/reports/ashare/*   -> A股
  docs/reports/us/*       -> 美股
  docs/reports/crypto/*   -> 加密 (含子目录报告, 取其 index.html)
  docs/reports/*.html     -> 跨市场 / 周期 (顶层)
  docs/*.md               -> 文档 (Markdown)

标题优先取 HTML 的 <title>, 取不到则用文件名做可读化回退。

用法:
    python scripts/build_report_index.py
"""
import json
import os
import re
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
REPORTS = os.path.join(DOCS, "reports")
OUT = os.path.join(DOCS, "data", "reports.json")

# 分组键 -> (显示名, 扫描目录, 是否递归)
GROUPS = [
    ("ashare", "A股", os.path.join(REPORTS, "ashare"), False),
    ("us", "美股", os.path.join(REPORTS, "us"), False),
    ("crypto", "加密", os.path.join(REPORTS, "crypto"), True),
    ("cross", "跨市场 / 周期", REPORTS, False),
]

# 门户自身与渲染器, 不作为报告列出
SKIP_HTML = {"index.html", "report.html"}

TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)


def read_title(path):
    """从 HTML 提取 <title>; 失败返回 None。"""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(8192)
    except OSError:
        return None
    m = TITLE_RE.search(head)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip()


def humanize(name):
    """文件名 -> 可读标题 (回退用)。"""
    base = os.path.splitext(name)[0]
    base = re.sub(r"[_\-]+", " ", base).strip()
    return base[:80]


def rel_from_docs(path):
    return os.path.relpath(path, DOCS).replace("\\", "/")


def collect_html(directory, recursive):
    """收集目录下所有报告 html, 返回 entry 列表。"""
    entries = []
    if not os.path.isdir(directory):
        return entries
    if recursive:
        walker = os.walk(directory)
    else:
        walker = [(directory, [], os.listdir(directory))]

    for dirpath, _dirnames, filenames in walker:
        for fn in sorted(filenames):
            if not fn.endswith(".html") or fn in SKIP_HTML:
                continue
            full = os.path.join(dirpath, fn)
            # 子目录报告: 只取每层的 index.html, 避免同一报告的多个页面重复列出
            if dirpath != directory and fn != "index.html":
                continue
            size_kb = round(os.path.getsize(full) / 1024)
            entries.append({
                "path": rel_from_docs(full),
                "title": read_title(full) or humanize(fn),
                "size_kb": size_kb,
            })
    return entries


def collect_md():
    """docs/ 根下的 Markdown 文档。"""
    entries = []
    if not os.path.isdir(DOCS):
        return entries
    for fn in sorted(os.listdir(DOCS)):
        if not fn.endswith(".md"):
            continue
        full = os.path.join(DOCS, fn)
        if not os.path.isfile(full):
            continue
        entries.append({
            "path": "report.html?r=" + fn,
            "title": humanize(fn),
            "size_kb": round(os.path.getsize(full) / 1024),
        })
    return entries


def collect_data():
    """门户数据层的 JSON, 便于直接下载核对。"""
    entries = []
    data_dir = os.path.join(DOCS, "data")
    if not os.path.isdir(data_dir):
        return entries
    for fn in sorted(os.listdir(data_dir)):
        if not fn.endswith(".json") or fn == "reports.json":
            continue
        full = os.path.join(data_dir, fn)
        entries.append({
            "path": "data/" + fn,
            "title": "数据层 · " + fn,
            "size_kb": round(os.path.getsize(full) / 1024),
        })
    return entries


def main():
    groups = []
    seen = set()

    for key, label, directory, recursive in GROUPS:
        items = collect_html(directory, recursive)
        # 顶层 cross 分组需排除已归入三个市场的子目录
        if key == "cross":
            items = [e for e in items if not e["path"].startswith(
                ("reports/ashare/", "reports/us/", "reports/crypto/"))]
        for e in items:
            seen.add(e["path"])
        groups.append({"key": key, "label": label, "items": items})

    # 未落入已知市场目录的其它报告 (兜底, 防止将来漏配)
    stray = []
    for dirpath, _dirnames, filenames in os.walk(REPORTS):
        for fn in sorted(filenames):
            if not fn.endswith(".html") or fn in SKIP_HTML:
                continue
            full = os.path.join(dirpath, fn)
            rel = rel_from_docs(full)
            if rel in seen:
                continue
            stray.append({
                "path": rel,
                "title": read_title(full) or humanize(fn),
                "size_kb": round(os.path.getsize(full) / 1024),
            })
    if stray:
        groups.append({"key": "other", "label": "其它", "items": stray})

    docs_items = collect_md()
    if docs_items:
        groups.append({"key": "docs", "label": "文档 (Markdown)", "items": docs_items})

    data_items = collect_data()
    if data_items:
        groups.append({"key": "data", "label": "数据层 (JSON)", "items": data_items})

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": sum(len(g["items"]) for g in groups),
        "groups": groups,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print("[reports.json] 已生成 %s" % os.path.relpath(OUT, ROOT))
    for g in groups:
        print("  %-16s %2d 项" % (g["label"], len(g["items"])))
    print("  合计 %d 项" % payload["total"])


if __name__ == "__main__":
    main()
