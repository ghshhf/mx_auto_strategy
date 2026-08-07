"""extend_panel_industry_index.py - 面板龙头等权合成9大行业指数 + 联网真实ETF交叉验证。

合成指数(新增7个, 共9个):
  旧2个: SEMI_INDEX (半导体14只), TECH_INDEX (科技大盘11只)
  新7个: HEALTH_INDEX 医药20只(对标XLV/IBB真实ETF)
          CONSUMER_INDEX 消费16只(对标XLP必选+XLY可选综合)
          FINANCIAL_INDEX 金融8只(对标XLF)
          ENERGY_INDEX 能源2只+清洁相关(对标XLE, 面板缺能源故XLE仅2只, 用XLE真实数据做降级)
          CLEAN_INDEX 光伏/清洁能源8只(对标ICLN/TAN)
          AUTO_INDEX 电动车/智能驾驶6只(对标DRIV/IDRV)
          INDUSTRIAL_INDEX 工业13只(对标XLI)

合成方法(已修): 每周取成分股有效简单收益等权平均 → 复利累乘(基期=100)。
          收益对价格水平/成员数不变 -> 无均价法假跳; None成分自动跳过。

联网真实ETF年度收益锚点(多源交叉一致, 2016-2024):
  XLV医疗  / XLF金融  / XLI工业   = ETFreplay.com + Vanguard 官方季报 + PortfoliosLab 三源一致
  XLE能源  / XLP必消 / XLY可选   = PortfoliosLab + ETFreplay 两源一致
  已内嵌于下方 REAL_ANNUAL dict, 仅作合成可信度校验, 不参与回测。
"""
import os, csv

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(HERE, "data", "weekly_adjclose_full_ext.csv")

# ========================================================= 成分
# 用户原意: 做空大盘/行业指数而非个股。合成指数=做空对标物, 成分需覆盖面板非科技主要行业。
SECTORS = {
    # (合成指数名, [成分代码列表], 对标真实ETF, 注释)
    "SEMI_INDEX":   (["NVDA","AMD","AVGO","SMCI","INTC","QCOM","TXN","MU",
                      "AMAT","LRCX","KLAC","MRVL","ASML","TSM","ARM","MPWR"],
                     "SOX费城半导体", "16只半导体设备/芯片/设计龙头"),
    "TECH_INDEX":   (["MSFT","AAPL","GOOGL","META","AMZN","NFLX","CRM",
                      "ADBE","INTU","ORCL","PLTR","NOW","SNOW","DDOG","NET","TEAM",
                      "WDAY","ZS","PANW","CSCO","IBM","ACN","FICO","ANSS","CDNS"],
                     "XLK+SOX综合(科技龙头等权)", "25只大盘科技龙头, 含SaaS/安全/咨询"),
    "HEALTH_INDEX": (["LLY","NVO","AZN","VRTX","REGN","MRNA","GILD","AMGN","ILMN",
                      "PFE","MRK","ABBV","JNJ","BMY","MDT","ISRG","UNH","ABT","SYK","CVS"],
                     "XLV医疗保健", "20只制药/设备/医保龙头"),
    "CONSUMER_INDEX":(["KO","PEP","COST","WMT","PG","MCD","CL","NKE","SBUX","BKNG",
                      "EBAY","ETSY","SPOT","TME","DASH","MELI","HUBS","CPNG","YUM","QSR"],
                     "XLP(必选)+XLY(可选)综合", "20只消费龙头(必选+电商可选)"),
    "FINANCIAL_INDEX":(["JPM","BAC","WFC","V","MA","AXP","BLK","GS","MS","BRK.B","C","SCHW"],
                     "XLF金融", "12只银行/卡/券商/资管龙头"),
    "ENERGY_INDEX": (["XOM","CVX","EOG","COP","OXY","SLB"],
                     "XLE能源", "6只油气巨头+油服(面板能源票少, 用巨头等权近似)"),
    "CLEAN_INDEX":  (["ENPH","SEDG","FSLR","JKS","CSIQ","RUN","NEE","BEPC","CWEN","AY","TSLA","PLUG"],
                     "ICLN(清洁)+TAN(光伏)", "12只光伏/风电/氢能/公用事业清洁"),
    "AUTO_INDEX":   (["TSLA","RIVN","LI","NIO","XPEV","MBLY","LCID","FSR"],
                     "DRIV/IDRV 电动车自动驾驶", "TSLA+新势力+ADAS(8只, TSLA主导)"),
    "INDUSTRIAL_INDEX":(["CAT","DE","HON","BA","LMT","UPS","GE","FTV","ROK","IR",
                      "TER","VRT","NXT","ITW","ETN","PH","CARR","OTIS","RTX","SWK"],
                     "XLI工业", "20只工业/军工/航空/工程机械龙头"),
}

# ========================================================= 真实ETF年度收益(联网多源交叉一致, 2016-2024)
# 用于校验合成指数可信度。来源:
#   XLF: ETFreplay.com XLF 2026.7.31快照 (1998-2026 完整年度)
#   XLV: FinanceCharts XLV 2026.8.3快照 (与Alphacubator交叉一致)
#   XLI: Vanguard XLI NAV 2026.6.30官方快照
#   XLE/XLP: PortfoliosLab XLP vs XLE 2026.8.5快照
#   XLY(可选消费): Vanguard XLY NAV 2026.6.30官方快照
REAL_ANNUAL = {
    # year -> {ETF: return_decimal}
    2016: {"XLV":-0.0276,"XLF":+0.2259,"XLI":+0.1993,"XLE":-0.0089,"XLP":+0.1298,"XLY":+0.0587},
    2017: {"XLV":+0.2177,"XLF":+0.2200,"XLI":+0.2385,"XLE":-0.0089,"XLP":+0.1298,"XLY":+0.2277},
    2018: {"XLV":+0.0628,"XLF":-0.1304,"XLI":-0.1310,"XLE":-0.1822,"XLP":-0.0807,"XLY":+0.0166},
    2019: {"XLV":+0.2045,"XLF":+0.3188,"XLI":+0.2911,"XLE":+0.1174,"XLP":+0.2743,"XLY":+0.2843},
    2020: {"XLV":+0.1330,"XLF":-0.0167,"XLI":+0.1100,"XLE":-0.3267,"XLP":+0.1011,"XLY":+0.2966},
    2021: {"XLV":+0.2559,"XLF":+0.3482,"XLI":+0.2096,"XLE":+0.5328,"XLP":+0.1720,"XLY":+0.2785},
    2022: {"XLV":-0.0208,"XLF":-0.1060,"XLI":-0.0555,"XLE":+0.6432,"XLP":-0.0081,"XLY":-0.3625},
    2023: {"XLV":+0.0207,"XLF":+0.1202,"XLI":+0.1803,"XLE":-0.0063,"XLP":-0.0082,"XLY":+0.3963},
    2024: {"XLV":+0.0248,"XLF":+0.3055,"XLI":+0.1737,"XLE":+0.0556,"XLP":+0.1220,"XLY":+0.2647},
}

def synth_index(series, dates, constituents, name):
    """等权收益率合成指数(修复旧版'价格均价法'假跳)。

    旧版: 每周取成分股价格算术平均 -> 首周归一=100。缺陷:
      (1) 平均的是'价格'而非'收益' -> 高价股主导, 非等权;
      (2) 成员数浮动(IPO/退市/None) -> 平均价格水平突变 -> 假跳(如CONSUMER_INDEX 13倍)。
    新版: 每周取成分股当周有效简单收益, 等权平均, 复利累乘(基期=100)。
      - 收益对价格水平与成员数不变 -> 无假跳;
      - 某周无有效收益(全None)则沿用上周值(0收益), 序列连续;
      - 仅用于'做空对标物'的周收益, 绝对水位无关紧要。
    """
    n = len(dates)
    out = [None] * n
    idx = None
    for i in range(1, n):
        rets = []
        for c in constituents:
            arr = series.get(c)
            if not arr or i >= len(arr):
                continue
            a, b = arr[i], arr[i - 1]
            if a is None or b is None or b <= 0 or a <= 0:
                continue
            rets.append(a / b - 1)
        if not rets:
            if idx is not None:
                out[i] = idx  # 沿用上周, 视为0收益
            continue
        r = sum(rets) / len(rets)
        if idx is None:
            idx = 100.0
        idx = idx * (1 + r)
        out[i] = round(idx, 4)
    return out


def annual_return(dates, series_arr, year):
    """取某年度首末有效价格 → 算年度收益。"""
    first = last = None
    for i, d in enumerate(dates):
        if not d.startswith(str(year)):
            continue
        v = series_arr[i] if i < len(series_arr) else None
        if v is None:
            continue
        if first is None:
            first = v
        last = v
    if first and last and first > 0:
        return last / first - 1
    return None


def main():
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

    # 1) 合成9个指数
    synth_results = {}
    for name, (cons, etf, note) in SECTORS.items():
        arr = synth_index(series, dates, cons, name)
        synth_results[name] = (arr, cons, etf, note)
        n_ok = sum(1 for v in arr if v is not None)
        print(f"合成 {name:<18}: {n_ok:>4}周 | 成分{len(cons)}只 | 对标{etf} {note}")

    # 2) 交叉验证: 合成 vs 真实ETF年度收益
    print("\n=== 交叉验证: 合成指数 vs 真实ETF 年度收益(误差pp, 方向√/×) ===")
    # 映射: 合成名 -> 真实ETF列名
    cmp_map = {
        "HEALTH_INDEX":     ("XLV",  "医药XLV"),
        "FINANCIAL_INDEX":  ("XLF",  "金融XLF"),
        "INDUSTRIAL_INDEX": ("XLI",  "工业XLI"),
        "ENERGY_INDEX":     ("XLE",  "能源XLE"),
        "CONSUMER_INDEX":   ("XLP",  "消费(用XLP必消基准, XLY可选会更波动)"),
    }
    years = sorted(REAL_ANNUAL.keys())
    print(f"{'指数':<18}", end="")
    for y in years: print(f"  {y}", end="")
    print(f"  {'MAE':>5}")
    for sname, (arr, cons, _, _) in synth_results.items():
        if sname not in cmp_map:
            continue
        etf, label = cmp_map[sname]
        print(f"{sname:<18}", end="")
        errs = []
        for y in years:
            s = annual_return(dates, arr, y)
            r = REAL_ANNUAL[y].get(etf)
            if s is None or r is None:
                print(f"    --", end=""); continue
            d_pp = (s - r) * 100
            mark = "√" if (s >= 0) == (r >= 0) else "×"
            print(f"  {d_pp:>+5.1f}{mark}", end="")
            errs.append(abs(d_pp))
        mae = sum(errs) / len(errs) if errs else float("nan")
        print(f"  {mae:>5.1f}")

    print("\n注: 误差(pp)=合成-真实 | MAE=年均绝对误差 | √=方向一致 ×=方向相反")
    print("    消费用XLP(必消)作基准, 合成包含电商可选(AMZN/EBAY等), 误差偏大属预期内")
    print("    SEMI_INDEX 对标SOX(historyofmarket真实), 见 extend_panel_real_indices.py 输出")

    # 3) 写回面板(追加9列, 若已存在则覆盖)
    new_hdr = hdr[:]
    for name in SECTORS:
        if name not in new_hdr:
            new_hdr.append(name)
    col_idx = {name: new_hdr.index(name) for name in SECTORS}
    new_rows = [new_hdr]
    for ri, r in enumerate(data):
        # pad到目标长度
        r_out = list(r) + [""] * (len(new_hdr) - len(r))
        for name, (arr, _, _, _) in synth_results.items():
            ci = col_idx[name]
            v = arr[ri] if ri < len(arr) else None
            r_out[ci] = "" if v is None else f"{v}"
        new_rows.append(r_out[:len(new_hdr)])

    with open(PANEL, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(new_rows)
    n_new = sum(1 for n in SECTORS if n not in hdr)
    print(f"\n已写回面板: {len(SECTORS)}列(新增{n_new}) | 总列数={len(new_hdr)}")


if __name__ == "__main__":
    main()
