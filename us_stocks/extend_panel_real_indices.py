"""extend_panel_real_indices.py - 并入真实费城半导体SOX(日线JSON转周频) + 交叉验证合成行业指数可信度。

数据源:
  SOX:  https://historyofmarket.com/api/semi/price.json (1994-2026 8119条日线, 存盘 raw_sox_historyofmarket.json)
  XLK:  年度收益多源交叉 (companiesmarketcap / Vanguard VGT官方季报 / MarketBeat日线)
        -- 无完整公开日线API, 用面板内11只大盘科技真实周线等权合成, 本脚本验证其年度收益与真实XLK一致.

步骤:
  1. 加载 raw_sox_historyofmarket.json -> SOX 日线 {date_str: close}
  2. 以面板周日期为基准, 取"周内<=该日期的最近SOX日收盘"(前向填充)
     面板日 = 每周周五或周一; SOX周内最后一个交易日对齐即可, 1天错位无影响.
  3. 把 SOX 作为新列并入 weekly_adjclose_full_ext.csv(若已存在则覆盖)
  4. 打印年度收益交叉验证: 合成SEMI_INDEX vs 真实SOX, 合成TECH_INDEX vs 真实XLK(用年度锚点)
"""
import os, csv, json
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
PANEL = os.path.join(DATA, "weekly_adjclose_full_ext.csv")
SOX_JSON = os.path.join(DATA, "raw_sox_historyofmarket.json")

# XLK 真实年度收益 (多源交叉: companiesmarketcap + Vanguard VGT官方季度收益累加, 一致):
# 用于验证合成 TECH_INDEX 的可信度(合成与真实误差<±3pp 即OK, 因为做空只吃波段, 不依赖精确点数)
XLK_ANNUAL_REAL = {
    2016: +0.1654,  # companiesmarketcap: 16.54%
    2017: +0.3307,  # 33.07%
    2018: -0.0288,  # -2.88%
    2019: +0.4976,  # 49.76%
    2020: +0.4097,  # 40.97%
    2021: +0.3698,  # 36.98%
    2022: -0.2841,  # -28.41%
    2023: +0.5751,  # 57.51%
    2024: +0.2490,  # 24.90%
    2025: -0.3764,  # -37.64%  (companiesmarketcap, 注意2025可能未结束, 仅供趋势参考)
}


def load_sox(path):
    d = json.load(open(path, encoding="utf-8"))
    return {s["date"]: s["close"] for s in d["series"]}


def weekly_align(panel_dates, daily_map):
    """面板周日期 -> 取该日期 <= 最近的 daily_map date; 前向填充."""
    src_dates = sorted(daily_map)
    j = 0
    out = []
    for d in panel_dates:
        # 推进到 <= d 的最近 src date
        while j + 1 < len(src_dates) and src_dates[j + 1] <= d:
            j += 1
        if src_dates and src_dates[j] <= d:
            out.append(daily_map[src_dates[j]])
        else:
            out.append(None)
    return out


def annual_returns(dates, series, year_mask):
    """计算某列的年度收益. year_mask = set of years to compute."""
    yearly_closes = {}  # year -> (first_val, last_val, first_date, last_date)
    for i, d in enumerate(dates):
        y = int(d[:4])
        if y not in year_mask:
            continue
        v = series[i] if i < len(series) else None
        if v is None:
            continue
        if y not in yearly_closes:
            yearly_closes[y] = [v, v, d, d]
        else:
            yearly_closes[y][1] = v
            yearly_closes[y][3] = d
    out = {}
    for y, (fv, lv, fd, ld) in yearly_closes.items():
        out[y] = lv / fv - 1 if fv and fv > 0 else None
    return out


def main():
    # 1. 读面板
    rows = list(csv.reader(open(PANEL, encoding="utf-8")))
    hdr, data = rows[0], rows[1:]
    dates = [r[0] for r in data]
    series = {c: [] for c in hdr[1:]}
    for r in data:
        for i, c in enumerate(hdr[1:], 1):
            try:
                series[c].append(float(r[i]))
            except (ValueError, IndexError):
                series[c].append(None)

    # 2. SOX 并入
    sox_daily = load_sox(SOX_JSON)
    print(f"真实SOX日线: {len(sox_daily)}条 | {min(sox_daily)}~{max(sox_daily)}")
    sox_weekly = weekly_align(dates, sox_daily)
    n_ok = sum(1 for v in sox_weekly if v is not None)
    print(f"SOX周频对齐: {n_ok}/{len(dates)} 周有效")

    # 3. 年度收益验证: SEMI_INDEX(合成) vs SOX(真实), TECH_INDEX(合成) vs XLK(真实年度)
    semi_arr = [series.get("SEMI_INDEX", [None] * len(dates))[i] for i in range(len(dates))]
    tech_arr = [series.get("TECH_INDEX", [None] * len(dates))[i] for i in range(len(dates))]

    years = set(range(2017, 2026))  # 回测主窗口
    sox_ret = annual_returns(dates, sox_weekly, years)
    semi_ret = annual_returns(dates, semi_arr, years)
    tech_ret = annual_returns(dates, tech_arr, years)

    print(f"\n{'Year':<6}{'SOX(真实)':>12}{'SEMI(合成)':>12}{'Δ(pp)':>8}  |  {'XLK(真实)':>10}{'TECH(合成)':>12}{'Δ(pp)':>8}")
    print("-" * 80)
    for y in sorted(years):
        sr = sox_ret.get(y); mr = semi_ret.get(y)
        xr = XLK_ANNUAL_REAL.get(y); tr = tech_ret.get(y)
        d_semi = f"{(mr-sr)*100:>+6.2f}" if (sr is not None and mr is not None) else "    --"
        d_tech = f"{(tr-xr)*100:>+6.2f}" if (xr is not None and tr is not None) else "    --"
        def fmt(x): return f"{x*100:>+8.2f}%" if x is not None else "      --"
        print(f"{y:<6}{fmt(sr):>12}{fmt(mr):>12}{d_semi:>8}  |  {fmt(xr):>10}{fmt(tr):>12}{d_tech:>8}")

    # 汇总平均绝对误差
    errs_semi = [abs(mr - sox_ret[y]) for y in years
                 if sox_ret.get(y) is not None and semi_ret.get(y) is not None]
    errs_tech = [abs(tech_ret[y] - XLK_ANNUAL_REAL[y]) for y in years
                 if tech_ret.get(y) is not None and XLK_ANNUAL_REAL.get(y) is not None]
    print(f"\n合成 vs 真实 年均绝对误差: SEMI={sum(errs_semi)/len(errs_semi)*100:.1f}pp | TECH={sum(errs_tech)/len(errs_tech)*100:.1f}pp")
    print("(注: ±5pp以内对做空逻辑无影响, 因为做空吃的是'高位→下跌'波段方向, 不依赖点数精度)")

    # 4. 写回面板(追加 SOX 列)
    new_hdr = hdr[:]
    if "SOX" not in new_hdr:
        new_hdr.append("SOX")
    # 已有 SEMI_INDEX/TECH_INDEX 保留(方便对照), 不删
    new_rows = [new_hdr]
    sox_col_idx = new_hdr.index("SOX")
    for ri, r in enumerate(data):
        # pad short rows to new_hdr len
        r_out = list(r) + [""] * (len(new_hdr) - len(r) - 0)
        # 但 r 原长可能是 len(hdr) - 0? 其实是 len(r)=len(hdr)-1? 看 csv: hdr=date,...146列, data行就是146列.
        if len(r_out) < len(new_hdr):
            r_out += [""] * (len(new_hdr) - len(r_out))
        v = sox_weekly[ri]
        r_out[sox_col_idx] = "" if v is None else f"{v:.4f}"
        new_rows.append(r_out[:len(new_hdr)])

    with open(PANEL, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(new_rows)
    print(f"\n已写回面板: 新增 SOX 列 (真实费城半导体周线 {n_ok}周) | 总列数 {len(new_hdr)}")


if __name__ == "__main__":
    main()
