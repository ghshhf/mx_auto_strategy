"""
merge_utils.py - 交易记录经济去重键 (v6.13b, 防 merge 误判)

历史教训 (2026-07-30 合并 master 交易记录):
  - 键 (ts, action, code, qty, price) -> 整段 7/29 重建被当新记录 (+9 笔误增)
  - 键 (action, code, qty, price)     -> 价格舍入差 0.003 误判为新交易
  - 正确键 = (action, code, qty): 经济内容(买卖哪只 / 多少股)唯一标识一笔交易,
    时间戳与价格浮动不应影响去重判断。

用法:
  from merge_utils import record_key, dedup
  merged = dedup(main_records + master_records)  # 保序, 保留首次出现
"""
from datetime import datetime  # noqa: F401  (保留以便未来扩展带时间戳的键)


def record_key(rec):
    """返回一笔交易的经济去重键 (action, code, qty)。"""
    return (
        str(rec.get("action", "")).strip(),
        str(rec.get("code", "")).strip(),
        rec.get("qty", 0),
    )


def dedup(records):
    """按 (action, code, qty) 去重, 保留首次出现。返回去重后列表(保序)。"""
    seen = set()
    out = []
    for r in records:
        k = record_key(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out
