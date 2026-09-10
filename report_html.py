"""共用报告页 HTML 模板 (深色主题 + Plotly) —— 单一事实来源。

背景
----
仓库顶层 6 个脚本 (``portfolio_blend.py`` 与 ``blend_*.py``) 原先各自内联一份
约 60 行**完全相同**的 ``<style>`` + Plotly CDN + ``Plotly.newPlot`` 样板，
改一次配色/图例要同步 6 处，且已出现漂移（h1 字号 22/23/24px 三种、
``.hl`` 是否加粗两种）。本模块把样板收敛为单一来源。

同时修掉旧内联模板的两个隐患：

1. **JS 注入脆弱**：旧代码把 Python ``dict`` 的 ``repr`` 直接插值进 JS
   (``const D = {dates:..., series:{series}}``)。资产名一旦含 ``'`` 或换行，
   生成的 JS 立即语法错误、整页白屏。现统一走 :func:`jsdata`（``json.dumps``）。
2. **NaN/Inf 非法字面量**：``repr`` 与 ``json.dumps`` 都会产出 ``nan``/``Infinity``
   这类非 JS 合法字面量。:func:`jsdata` 统一清洗为 ``null``。
3. **HTML 未转义**：资产名/文案直接插值进 ``<td>``。现提供 :func:`esc`。

用法见各 ``blend_*.py`` 的 ``_html()``。
"""

from __future__ import annotations

import html
import json
import math

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"

# 页级样式: 6 份旧模板的并集。
#   .hl  = 高亮绿 (仅着色, sector_watchlist 原样)
#   .hlb = 高亮绿 + 加粗 (defense_engine_check 原样)
#   .warm= 橙色警示      .c/.r = 数值列右对齐
CSS = (
    "body{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;"
    "background:#0f1117;color:#e6e9ef;margin:0;padding:32px;}"
    "h1{font-size:24px;margin:0 0 4px;} .sub{color:#9aa3b2;margin-bottom:20px;}"
    ".card{background:#171a23;border:1px solid #262b38;border-radius:14px;"
    "padding:20px;margin-bottom:20px;}"
    "table{border-collapse:collapse;width:100%;font-size:14px;}"
    "th,td{border-bottom:1px solid #2a3040;padding:8px 10px;text-align:left;}"
    "td.r{text-align:right;font-variant-numeric:tabular-nums;color:#ffd479;}"
    "td.c{text-align:right;color:#7ee787;}"
    ".note{color:#9aa3b2;font-size:13px;line-height:1.7;}"
    ".hl{color:#7ee787;} .hlb{color:#7ee787;font-weight:600;} .warm{color:#ffb86c;}"
)


def esc(value: object) -> str:
    """把任意值安全地放进 HTML 文本节点。"""
    return html.escape(str(value), quote=True)


def _clean(obj):
    """递归把 NaN/Inf 换成 None, 使产出是合法 JSON (JS 字面量)。"""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def jsdata(obj) -> str:
    """把 Python 对象序列化为可直接嵌入 ``<script>`` 的 JS 字面量。

    相比旧的 ``repr(dict)``: 引号规范、非 ASCII 不转义破坏、NaN/Inf 安全。
    """
    # separators 紧凑化: 默认 ', ' 分隔会让大面板的 HTML 无谓膨胀 (~8%)。
    return json.dumps(_clean(obj), ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def dates_of(index) -> list[str]:
    """DatetimeIndex -> 'YYYY-MM-DD' 字符串列表 (供 x 轴与副标题复用)。"""
    return [str(d.date()) for d in index]


def series_of(df, ndigits: int = 4) -> dict:
    """DataFrame -> {列名: 数值列表}, 供 :func:`jsdata` 注入。"""
    return {c: [round(float(x), ndigits) for x in df[c].values] for c in df.columns}


def metrics_rows(metrics_map, mult_fmt: str = "{:.2f}x", num_cls: str = "r") -> str:
    """指标表行: 名称 | 倍数 | CAGR | MDD | Sharpe。

    ``metrics_map`` 为 ``{名称: {'multiple','cagr','mdd','sharpe'}}``。
    ``num_cls`` 为空串时不给数值列加右对齐类 (portfolio_blend 原样式)。
    """
    cls = f" class='{num_cls}'" if num_cls else ""
    return "".join(
        f"<tr><td>{esc(name)}</td><td{cls}>{mult_fmt.format(m['multiple'])}</td>"
        f"<td>{m['cagr'] * 100:.1f}%</td><td{cls}>{m['mdd'] * 100:.1f}%</td>"
        f"<td>{m['sharpe']:.2f}</td></tr>"
        for name, m in metrics_map.items()
    )


def metric_table(headers, rows_html: str) -> str:
    """包一层 ``<table>``，``headers`` 为表头文本列表。"""
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    return f"<table><tr>{th}</tr>{rows_html}</table>"


def card(title: str, inner: str) -> str:
    """一张卡片；``title`` 为空时只渲染内容。"""
    head = f"<h3 style='margin-top:0'>{title}</h3>" if title else ""
    return f"<div class='card'>{head}{inner}</div>"


def nav_chart(div_id: str, traces_js: str, height: int = 460,
              y_title: str = "净值(对数,起点=1)") -> str:
    """对数轴净值图: 返回 <div> 容器 + Plotly 调用脚本。

    ``traces_js`` 是 JS 数组字面量表达式 (由 :func:`line_traces` 产出)。

    注意: 这里**刻意使用字符串拼接而非 f-string** —— Plotly layout 本身是
    ``{...}`` 字面量, 用 f-string 需要把每一处 ``{`` 写成 ``{{``, 极易出错。
    """
    layout = (
        "{paper_bgcolor:'#171a23',plot_bgcolor:'#171a23',font:{color:'#e6e9ef'},"
        "yaxis:{type:'log',title:'" + y_title + "'}, xaxis:{title:''},"
        "legend:{orientation:'h',y:1.08}, margin:{t:20,b:40,l:60,r:20}}, "
        "{responsive:true}"
    )
    return (
        "<div id='" + div_id + "' style='width:100%;height:" + str(height) + "px'></div>"
        "<script>Plotly.newPlot('" + div_id + "', " + traces_js + ", " + layout + ");</script>"
    )


def data_block(**maps) -> str:
    """声明前端数据源: ``data_block(dates=..., series=...)`` -> ``<script>const D = {...}</script>``。

    必须排在引用 ``D`` 的 :func:`nav_chart` 之前。
    """
    body = ",".join(f"{k}:{jsdata(v)}" for k, v in maps.items())
    return "<script>const D = {" + body + "};</script>"


def line_traces(series_map, x_expr: str = "D.dates", y_root: str = "D.series") -> str:
    """``{名称: 数组}`` -> Plotly traces 的 JS 数组字面量。

    名称走 :func:`jsdata` 转义, 因此含引号/中文的列名不会破坏 JS。
    """
    parts = [
        "{x:" + x_expr + ", y:" + y_root + "[" + jsdata(k) + "], name:" + jsdata(k) + ", mode:'lines'}"
        for k in series_map
    ]
    return "[" + ",".join(parts) + "]"


def page(title: str, h1: str, sub: str, body: str, plotly: bool = True) -> str:
    """整页骨架。``body`` 为已拼好的卡片/表格 HTML (可含内联 <script>)。"""
    head = f"<script src='{PLOTLY_CDN}'></script>" if plotly else ""
    return (
        "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
        f"<title>{esc(title)}</title>{head}"
        f"<style>{CSS}</style></head><body>"
        f"<h1>{h1}</h1>"
        f"<div class='sub'>{sub}</div>"
        f"{body}</body></html>"
    )
