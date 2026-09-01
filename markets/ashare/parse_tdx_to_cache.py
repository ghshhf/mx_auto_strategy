# -*- coding: utf-8 -*-
"""
parse_tdx_to_cache.py
=====================
把 DeferExecuteTool 直连 tdx_kline 落盘的 *.txt 文件解析进本地缓存。

tdx_kline 返回超 token 上限会自动存成 tool-results/ 下的文本文件, 结构:
  第一行: 【名称】代码 | 现价 ... | K线数量: N根 ...
  "详细K线数据:" 之后: JSON {Setcode,Code,Period,Rows:[{Data,Close,Volume,...}]}

本脚本:
  1. 扫描 tool-results 下所有 tdx_kline_*.txt
  2. 从表头解析 名称/代码, 从 JSON 提取 [日期,收盘,量]
  3. 按代码归并所有分页(startxh 翻页得到多文件), 按日期去重
  4. 写入 data/ashare/bars/<code>.json (经 data_store 统一格式)
     - 个股: <6位代码>.json  (如 600519.json)
     - 指数: sh<代码>.json   (如 sh000001.json, 与 analog_core 约定一致)

可重复运行: 新拉的分页文件会被并入已缓存数据(按日期去重), 不覆盖已有历史。
"""
import os
import sys
import json
import glob
import re
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(BASE))
sys.path.insert(0, BASE)
import data_store as ds

# tool-results 目录 (DeferExecuteTool 落盘位置, 跨会话稳定)
TOOL_RESULTS = r"C:/Users/admin/.workbuddy/projects/d/2b9f3d48-ae9a-41c3-b0e0-3dd07382e0e5/tool-results"

HEADER_RE = re.compile(r"【(.+?)】(\d+)\s*\|")
DATE_RE = re.compile(r"^\d{8}$")


def _parse_file(path):
    try:
        txt = open(path, encoding="utf-8", errors="ignore").read()
    except Exception as e:
        print(f"  ! 读失败 {os.path.basename(path)}: {e}", file=sys.stderr)
        return None, None, []
    m = HEADER_RE.search(txt)
    if not m:
        return None, None, []
    name, code = m.group(1).strip(), m.group(2).strip()
    i = txt.find("详细K线数据:")
    if i < 0:
        return name, code, []
    blob = txt[i + len("详细K线数据:"):].strip()
    s = blob.find("{")
    if s < 0:
        return name, code, []
    try:
        j = json.loads(blob[s:])
    except Exception as e:
        print(f"  ! JSON 解析失败 {os.path.basename(path)}: {e}", file=sys.stderr)
        return name, code, []
    rows = j.get("Rows") or []
    out = []
    for r in rows:
        d = r.get("Data")
        c = r.get("Close")
        v = r.get("Volume")
        if d is None or c is None:
            continue
        if not DATE_RE.match(str(d)):
            continue
        try:
            dd = f"{str(d)[:4]}-{str(d)[4:6]}-{str(d)[6:8]}"
            out.append([dd, float(c), float(v if v is not None else 0.0)])
        except (ValueError, TypeError):
            continue
    return name, code, out


def collect():
    """扫描全部文件, 返回 {code: {name, bars:[...]}} (去重合并)。"""
    files = glob.glob(os.path.join(TOOL_RESULTS, "tdx_kline_*.txt"))
    files += glob.glob(os.path.join(TOOL_RESULTS, "mcp-connector-proxy-tdx-connector_tdx_kline-*.txt"))
    # 去重 (glob 两次可能重叠)
    files = sorted(set(files))
    print(f"扫描到 {len(files)} 个 tdx_kline 文件")
    by_code = {}
    for f in files:
        name, code, bars = _parse_file(f)
        if not code or not bars:
            continue
        rec = by_code.setdefault(code, {"name": name, "bars": []})
        rec["name"] = name
        rec["bars"].extend(bars)
    # 去重 + 排序
    for code, rec in by_code.items():
        seen = {}
        for d, c, v in rec["bars"]:
            seen[d] = [d, c, v]
        rec["bars"] = sorted(seen.values(), key=lambda x: x[0])
    return by_code


def save_all(by_code, dry=False):
    n = 0
    for code, rec in sorted(by_code.items()):
        new_bars = [{"d": d, "c": c, "v": v} for d, c, v in rec["bars"]]
        if not new_bars:
            continue
        # 指数 000001 -> sh000001
        out_code = ("sh" + code) if code == "000001" else code
        # 关键: 与本地已有缓存按日期 UNION, 绝不覆盖(否则会清掉 2005 起的长历史)
        existing = ds.load_bars(out_code) or []
        merged = {}
        for b in existing:
            merged[b["d"]] = [b["d"], b["c"], b["v"]]
        for b in new_bars:
            merged[b["d"]] = [b["d"], b["c"], b["v"]]
        merged_bars = sorted(merged.values(), key=lambda x: x[0])
        if dry:
            print(f"  [dry] {out_code} {rec['name']}: +{len(new_bars)} -> 共 {len(merged_bars)} 条 "
                  f"{merged_bars[0][0]}->{merged_bars[-1][0]}")
        else:
            ds.save_bars(out_code,
                         [{"d": x[0], "c": x[1], "v": x[2]} for x in merged_bars],
                         source="tdx")
            print(f"  写 {out_code} {rec['name']}: 共 {len(merged_bars)} 条 "
                  f"{merged_bars[0][0]}->{merged_bars[-1][0]}")
        n += 1
    return n


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只统计不落盘")
    args = ap.parse_args()
    by_code = collect()
    print(f"涉及 {len(by_code)} 个标的:")
    for code, rec in sorted(by_code.items()):
        nm = rec["name"]
        bs = rec["bars"]
        rng = f"{bs[0][0]}->{bs[-1][0]}" if bs else "-"
        print(f"  {code} {nm}: {len(bs)} 条 {rng}")
    print("\n落盘到本地缓存 ...")
    save_all(by_code, dry=args.dry)
