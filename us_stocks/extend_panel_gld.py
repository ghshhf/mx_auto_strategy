"""
extend_panel_gld.py - 把 westock-data 抓取的 GLD/JPM 真实周线并入美股全面板

数据源: westock-data kline usGLD.AM / usJPM.N --period week --fq hfq (markdown 表)
对齐: 面板周频日期为基准, 对 GLD/JPM 取"<=面板日的最新收盘价"(前向填充), 容忍 1 周错位。
产物: data/weekly_adjclose_full_ext.csv (原 146 列 + GLD + JPM)

运行: python extend_panel_gld.py
"""
import os, csv, re
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SRC = os.path.join(DATA, "weekly_adjclose_full.csv")
DST = os.path.join(DATA, "weekly_adjclose_full_ext.csv")
GLD_FILES = [os.path.join(DATA, "raw_gld_pre.txt"), os.path.join(DATA, "raw_gld.txt")]
JPM_FILES = [os.path.join(DATA, "raw_jpm_pre.txt"), os.path.join(DATA, "raw_jpm.txt")]


def parse_md(paths):
    """解析 westock-data kline 输出的 markdown 表 -> {date_str: close_float}。支持多文件合并(后者覆盖前者同日期)。"""
    out = {}
    if isinstance(paths, str):
        paths = [paths]
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("|"):
                    continue
                cols = [c.strip() for c in line.strip("|").split("|")]
                if len(cols) < 3:
                    continue
                if cols[0] == "date" or not re.match(r"^\d{4}-\d{2}-\d{2}$", cols[0]):
                    continue
                try:
                    out[cols[0]] = float(cols[2])  # 'last' = 收盘
                except (ValueError, IndexError):
                    pass
    # 排序(升序)
    return dict(sorted(out.items()))


def align(panel_dates, src_map):
    """对面板每个日期, 取 src_map 中 <= 该日期的最新值(前向填充)。"""
    src_dates = list(src_map.keys())
    j = 0
    out = []
    for d in panel_dates:
        while j + 1 < len(src_dates) and src_dates[j + 1] <= d:
            j += 1
        out.append(src_map[src_dates[j]] if src_dates and src_dates[j] <= d else None)
    return out


def main():
    gld = parse_md(GLD_FILES)
    jpm = parse_md(JPM_FILES)
    print(f"GLD 源: {len(gld)} 周 ({list(gld)[0]}~{list(gld)[-1]})")
    print(f"JPM 源: {len(jpm)} 周 ({list(jpm)[0]}~{list(jpm)[-1]})")

    rows = list(csv.reader(open(SRC, encoding="utf-8")))
    hdr, data = rows[0], rows[1:]
    panel_dates = [r[0] for r in data]

    gld_col = align(panel_dates, gld)
    jpm_col = align(panel_dates, jpm)
    n_ok = sum(1 for v in gld_col if v is not None)
    print(f"面板: {panel_dates[0]}~{panel_dates[-1]} ({len(panel_dates)} 周) | GLD 对齐非空 {n_ok}")

    new_hdr = hdr + ["GLD", "JPM"]
    with open(DST, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(new_hdr)
        for i, r in enumerate(data):
            w.writerow(r + ["" if gld_col[i] is None else f"{gld_col[i]:.4f}",
                            "" if jpm_col[i] is None else f"{jpm_col[i]:.4f}"])
    print(f"已写出扩展面板: {os.path.basename(DST)} ({len(new_hdr)} 列)")


if __name__ == "__main__":
    main()
