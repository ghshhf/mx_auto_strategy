"""
extend_panel_bonds.py - 把债券 ETF(TLT/IEF/AGG/BND/SHY) 真实周线并入美股全面板

为什么需要: 用户指定美股极端防御用"债券+分红"而非黄金。当前面板(weekly_adjclose_full_ext.csv)
已有 GLD/JPM 但无债券 ETF。本脚本复用 extend_panel_gld.py 的同款对齐机制, 把债券 ETF 周线
并入面板, 使 us_backtest_ai.py 的 crash 档自动把现金仓改配债券作危机对冲。

数据获取(与 GLD 同款, 用 westock-data 技能):
  westock-data kline usTLT.AM --period week --fq hfq   # 输出 markdown 表
  westock-data kline usIEF.AM --period week --fq hfq
  westock-data kline usAGG.AM --period week --fq hfq
  westock-data kline usBND.AM --period week --fq hfq
  分别存入 data/raw_tlt.txt / raw_ief.txt / raw_agg.txt / raw_bnd.txt (可多文件覆盖同日期),
  然后运行: python extend_panel_bonds.py

对齐: 面板周频日期为基准, 对债券取"<=面板日的最新收盘价"(前向填充), 容忍 1 周错位。
产物: data/weekly_adjclose_full_ext.csv (原列 + 债券列)
"""
import os, csv, re

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SRC = os.path.join(DATA, "weekly_adjclose_full_ext.csv")   # 在已有扩展面板上再扩
DST = SRC
BOND_FILES = {
    "TLT": [os.path.join(DATA, "raw_tlt.txt")],
    "IEF": [os.path.join(DATA, "raw_ief.txt")],
    "AGG": [os.path.join(DATA, "raw_agg.txt")],
    "BND": [os.path.join(DATA, "raw_bnd.txt")],
    "SHY": [os.path.join(DATA, "raw_shy.txt")],
}


def parse_md(paths):
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
                    out[cols[0]] = float(cols[2])
                except (ValueError, IndexError):
                    pass
    return dict(sorted(out.items()))


def align(panel_dates, src_map):
    src_dates = list(src_map.keys())
    j = 0
    out = []
    for d in panel_dates:
        while j + 1 < len(src_dates) and src_dates[j + 1] <= d:
            j += 1
        out.append(src_map[src_dates[j]] if src_dates and src_dates[j] <= d else None)
    return out


def main():
    rows = list(csv.reader(open(SRC, encoding="utf-8")))
    hdr, data = rows[0], rows[1:]
    panel_dates = [r[0] for r in data]

    new_cols = {}
    for code, files in BOND_FILES.items():
        if code in hdr:
            print(f"  {code} 已在面板, 跳过")
            continue
        m = parse_md(files)
        if not m:
            print(f"  {code}: 无源文件(跳过) -> 需先用 westock-data 抓取 raw_{code.lower()}.txt")
            continue
        col = align(panel_dates, m)
        n_ok = sum(1 for v in col if v is not None)
        print(f"  {code}: 源 {len(m)} 周, 对齐非空 {n_ok}")
        new_cols[code] = col

    if not new_cols:
        print("无新债券列可并入(均已存在或缺少源文件)。退出。")
        return

    new_hdr = hdr + list(new_cols.keys())
    with open(DST, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(new_hdr)
        for i, r in enumerate(data):
            ext = ["" if new_cols[c][i] is None else f"{new_cols[c][i]:.4f}" for c in new_cols]
            w.writerow(r + ext)
    print(f"已写出扩展面板: {os.path.basename(DST)} ({len(new_hdr)} 列)")


if __name__ == "__main__":
    main()
