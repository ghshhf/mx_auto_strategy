"""
jsonl_utils.py - JSONL 读写统一入口 (v6.17)

职责: 收敛全仓重复的 JSONL 读/追加实现。
  - read_jsonl:  逐行解析, 跳过空行/坏行(静默), 返回 list[dict]
  - append_jsonl: 确保 dir 存在 + 追加一行 JSON

M21: 旧实现 local_records.load_equity_curve/load_trade_log、
     manual_log._read_jsonl 三处 read 逻辑完全一致;
     local_records.log_trade/log_equity、script_advisor.save_audit、
     ai_score._save_audit 四处 append 逻辑仅路径不同。抽出统一入口消除漂移。
"""
import os
import json


def read_jsonl(path):
    """读取 JSONL 文件, 返回 list[dict]。文件不存在/空返回 []。
    逐行解析, 跳过空行与 JSON 解析失败的行(不抛错, 与旧实现行为一致)。"""
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def append_jsonl(path, record):
    """把一条记录追加到 JSONL 文件(自动建目录)。"""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
