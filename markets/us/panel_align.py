"""面板日期对齐工具 (as-of 前向填充)。

背景
----
``extend_panel_*.py`` 四个脚本各自复制了一份「把源序列对齐到面板周日期」的实现,
算法相同但细节有差异, 其中两处还埋了隐患:
  - ``extend_panel_bonds.py`` / ``extend_panel_gld.py`` 用 ``list(src_map.keys())``,
    **未排序**, 依赖 dict 插入序恰好有序这一隐含前提; 源数据一旦乱序就会静默错配。
  - ``extend_panel_us_tickers.py`` 的 ``align(series, dates)`` 参数顺序与其余三个
    相反, 且返回格式化字符串而非原值, 极易误用。

本模块统一为单一实现: 源键**强制排序** + bisect 查找, 并同时支持原值与格式化输出。

语义
----
对面板中每个日期 d, 取源序列中 **<= d 的最近一条**记录的值 (前向填充);
若 d 早于源序列首条记录 (如标的尚未上市), 填 ``empty`` (默认 None)。

用法
----
    from panel_align import align_asof, align_asof_str

    align_asof(panel_dates, src_map)                      # -> [值|None]
    align_asof_str(panel_dates, src_map)                  # -> ["123.45000"|""]
"""
from __future__ import annotations

import bisect
from typing import Any, Hashable, Mapping, Sequence

__all__ = ["align_asof", "align_asof_str"]


def align_asof(
    panel_dates: Sequence[Hashable],
    src_map: Mapping[Hashable, Any],
    *,
    fmt: str | None = None,
    empty: Any = None,
) -> list:
    """把 ``src_map`` (``{日期: 值}``) 前向填充对齐到 ``panel_dates``。

    panel_dates : 面板日期序列 (无需预先有序)。
    src_map     : 源数据映射, 键为日期。内部会排序, 不依赖插入序。
    fmt         : 给定则按该格式串格式化输出 (如 "%.5f"); 否则原值透传。
    empty       : d 早于源首条记录时填入的值 (默认 None)。

    返回与 panel_dates 等长的列表。
    """
    keys = sorted(src_map)                      # 强制排序, 杜绝乱序静默错配
    out: list = []
    for d in panel_dates:
        i = bisect.bisect_right(keys, d) - 1    # <= d 的最近一条
        if i < 0:                               # d 早于源首条 -> 上市前
            out.append(empty)
            continue
        v = src_map[keys[i]]
        out.append(fmt % v if fmt is not None and v is not None else v)
    return out


def align_asof_str(
    panel_dates: Sequence[Hashable],
    src_map: Mapping[Hashable, Any],
    fmt: str = "%.5f",
    empty: str = "",
) -> list[str]:
    """``align_asof`` 的字符串特化版: 输出固定小数位字符串, 上市前填空串。

    面向需要直接写入 CSV 的场景 (值统一格式, 缺失用空单元格表示)。
    """
    return align_asof(panel_dates, src_map, fmt=fmt, empty=empty)
