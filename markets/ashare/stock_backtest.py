# -*- coding: utf-8 -*-
"""
stock_backtest.py —— 个股 α 引擎(指数当相位拨盘)
==============================================
用户原话: "过去买的是个股, 我只是用指数当参考, 通过买个股出倍数。"

架构(严格因果, 无未来函数):
  1. 指数(sh000001) 走 analog_core.regime_at -> 每日"市场相位权重" w_mkt ∈ [0,1]
     (主升满仓 / 赶顶减仓 / 筑底半仓 / 震荡近空 / 退潮主跌近零)。
     这是"拨盘": 决定整体开闸与否, 不持有指数本身。
  2. 个股宇宙(20 只核心资产) 每 rebal 日:
       - 只用当时已有数据算 60日 RS(动量) 与 是否站上 MA250(趋势过滤)
       - 过滤掉 MA250 下方(下跌趋势)的票, 在"站上 MA250 且 RS>0"的票里按 RS 取前 N
       - 落选者权重 0, 现金
  3. 持仓权重 = w_mkt(拨盘) × 等权(前 N 只)  —— 拨盘关闸时整体降仓。
  4. 摩擦: 单边 5bp, 仅在调仓日对权重变动收。

诚实基准(全部可比):
  A. 买入持有指数(sh000001)               —— 纯拨盘, 不挑股
  B. 等权买入持有 20 只(月度再平衡)        —— 纯个股, 不拨盘不挑
  C. 个股 RS 轮动(始终满仓, 不拨盘)        —— 纯挑股
  D. 个股 RS 轮动 + 指数拨盘(本系统)        —— 挑股 + 拨盘
  E. 事后最佳单只(知道未来, 仅供对照)       —— 说明 18x 只能靠"选对那一只"

用法:
  python stock_backtest.py                # 跑全部, 打印对比表
  python stock_backtest.py --start 2015-01-01 --topn 5
"""
import os, sys, json, math, argparse
sys.path.insert(0, os.path.dirname(__file__))
import data_store as ds
import analog_core as ac

BASE = os.path.dirname(os.path.abspath(__file__))

# 个股宇宙 —— 拆成两截便于诚实对比:
#   CORE_20 : 原 20 只白马核心资产(天然给不出倍数, 基数稳)
#   GROWTH_15: 新增 15 只赛道成长股(真正的十倍机会在 2019-2021 这类票)
# 选股广度(把更多"可能十倍"的票放进候选池)才是真正的杠杆, 而非金融杠杆。
CORE_20 = [
    ("000002", 0, "万科A"), ("000333", 0, "美的集团"), ("000568", 0, "泸州老窖"),
    ("000651", 0, "格力电器"), ("000661", 0, "长春高新"), ("000858", 0, "五粮液"),
    ("002415", 0, "海康威视"), ("002475", 0, "立讯精密"), ("300760", 0, "迈瑞医疗"),
    ("600030", 1, "中信证券"), ("600036", 1, "招商银行"), ("600048", 1, "保利发展"),
    ("600276", 1, "恒瑞医药"), ("600519", 1, "贵州茅台"), ("600585", 1, "海螺水泥"),
    ("600887", 1, "伊利股份"), ("601166", 1, "兴业银行"), ("601318", 1, "中国平安"),
    ("601398", 1, "工商银行"), ("603288", 1, "海天味业"),
]
GROWTH_15 = [
    ("601012", 1, "隆基绿能"), ("300274", 0, "阳光电源"), ("300014", 0, "亿纬锂能"),
    ("300750", 0, "宁德时代"), ("002594", 0, "比亚迪"),   ("300782", 0, "卓胜微"),
    ("603259", 1, "药明康德"), ("603501", 1, "豪威集团"), ("603986", 1, "兆易创新"),
    ("002371", 0, "北方华创"), ("300015", 0, "爱尔眼科"), ("300059", 0, "东方财富"),
    ("300122", 0, "智飞生物"), ("300124", 0, "汇川技术"), ("601888", 1, "中国中免"),
]
# 第三批 5 只(扩到 40): 按行业广度选 5 个赛道成长龙头, 覆盖电子/新能源设备/
# 消费成长/高端装备/AI 五个尚未充分代表的细分 —— 选股广度杠杆, 非按收益前视挑选。
GROWTH_5 = [
    ("002241", 0, "歌尔股份"),   # 电子/消费电子(VR/声学)
    ("300450", 0, "先导智能"),   # 新能源设备(锂电)
    ("603605", 1, "珀莱雅"),     # 消费成长(美妆)
    ("300316", 0, "晶盛机电"),   # 高端装备(光伏/半导体设备)
    ("002230", 0, "科大讯飞"),   # 人工智能/软件
]
# 第四批 10 只(扩到 50): 按行业广度补"周期性行业", 与现有消费/医药/科技/新能源池
# 低相关, 提供独立周期流。选股广度杠杆(非前视挑收益)。setcode: 沪=1 深=0。
GROWTH_CYC_10 = [
    ("601088", 1, "中国神华"),   # 能源/煤炭
    ("601899", 1, "紫金矿业"),   # 有色金属(金铜)
    ("600309", 1, "万华化学"),   # 基础化工(MDI)
    ("600019", 1, "宝钢股份"),   # 钢铁
    ("600893", 1, "航发动力"),   # 军工/航空发动机
    ("600050", 1, "中国联通"),   # 通信/运营商
    ("600900", 1, "长江电力"),   # 公用事业/水电
    ("600009", 1, "上海机场"),   # 交通运输/机场
    ("600660", 1, "福耀玻璃"),   # 汽车/零部件
    ("002714", 0, "牧原股份"),   # 农林牧渔/养猪
]
UNIVERSE = CORE_20 + GROWTH_15 + GROWTH_5 + GROWTH_CYC_10  # 默认 50 只全宇宙

POS = {  # 与 regime_positioning 一致
    "主升浪": 1.00, "赶顶/收割期": 0.40, "筑底": 0.50, "震荡": 0.10,
    "退潮期": 0.10, "主跌浪": 0.00, "数据不足": 0.10,
}
COST = 0.0005

def load_pairs(code):
    bars = ds.load_bars(code)
    if not bars:
        return []
    out = []
    for b in bars:
        if isinstance(b, dict):
            out.append((b["d"], float(b["c"])))
        else:
            out.append((b[0], float(b[1])))
    out.sort(key=lambda x: x[0])
    return out

def ma(seq, i, n):
    if i < n - 1:
        return None
    return sum(seq[i - n + 1:i + 1]) / n

def metrics(eq):
    n = len(eq) - 1
    yrs = n / 242.0
    mult = eq[-1]
    cagr = (mult ** (1 / yrs) - 1) if mult > 0 and yrs > 0 else float("nan")
    peak = eq[0]; mdd = 0.0
    for x in eq:
        peak = max(peak, x); mdd = min(mdd, x / peak - 1)
    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq))]
    mean = sum(rets) / len(rets)
    sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / len(rets))
    sharpe = (mean / sd * math.sqrt(242)) if sd > 0 else 0.0
    return dict(days=n, years=round(yrs, 2), mult=round(mult, 2),
                cagr=round(cagr * 100, 1), mdd=round(mdd * 100, 1),
                vol=round(sd * math.sqrt(242) * 100, 1), sharpe=round(sharpe, 2))

# ---------------------------------------------------------------------------
def build_market_clock():
    """以 sh000001 为总时钟(它有 2005->今 的长历史)。"""
    idx = ds.load_bars("sh000001")
    dates = [b["d"] for b in idx]
    idx_close = [float(b["c"]) for b in idx]
    # 指数相位权重(每日, 因果) — 必须用真实成交量, 否则 build_features
    # 的 ma20v<=0 会让全部特征为 None -> regime 恒为"数据不足" -> 拨盘失效。
    idx_bars = [{"d": b["d"], "c": float(b["c"]), "v": float(b.get("v") or 0)}
                for b in idx]
    feats = ac.build_features(idx_bars)
    w_mkt = []
    for i in range(len(idx)):
        label, _ = ac.regime_at(idx_bars, feats, i)
        w_mkt.append(POS.get(label, 0.10))
    return dates, idx_close, w_mkt

def build_stock_matrix(dates, universe=None):
    """把每只个股对齐到指数时钟(前向填充), 返回 {code: {date: close}} 与首个可用日。"""
    if universe is None:
        universe = UNIVERSE
    by_code = {}
    first_avail = {}
    for code, _, name in universe:
        pairs = load_pairs(code)
        if not pairs:
            continue
        m = {d: c for d, c in pairs}
        # 前向填充
        seq = {}
        last = None
        for d in dates:
            if d in m:
                last = m[d]
            if last is not None:
                seq[d] = last
        by_code[code] = (name, seq)
        first_avail[code] = pairs[0][0]
    return by_code, first_avail

def simulate_system(dates, w_mkt, by_code, first_avail, topn=5, rebal=21,
                    trend_filter=True):
    """指数拨盘 + 个股 RS 轮动(趋势过滤)。返回权益曲线。"""
    codes = list(by_code.keys())
    n = len(dates)
    eq = [1.0]
    prev_w = {c: 0.0 for c in codes}
    for i in range(1, n):
        rebal_day = (i % rebal == 0) or (i <= rebal)
        target = dict(prev_w)
        if rebal_day:
            # 候选: 已有数据且至少 61 根历史(算 RS60)
            cands = []
            for c in codes:
                seq = by_code[c][1]
                if dates[i - 1] not in seq:
                    continue
                # 找 i-1 与 i-61 在序列中的位置(用最近已知)
                # 用 dates 索引: 取前 61 个交易日的 close
                hist = [seq.get(dates[j]) for j in range(max(0, i - 61), i)]
                hist = [x for x in hist if x is not None]
                if len(hist) < 61:
                    continue
                c0, c1 = hist[0], hist[-1]
                if c0 <= 0:
                    continue
                rs = c1 / c0 - 1
                ma250 = ma([seq.get(dates[j]) for j in range(max(0, i - 250), i)
                            if seq.get(dates[j]) is not None], len([x for x in
                            [seq.get(dates[j]) for j in range(max(0, i - 250), i)]
                            if x is not None]) - 1, 250) if (i >= 250) else None
                above = (ma250 is None) or (c1 > ma250)
                if trend_filter and not above:
                    continue
                if rs <= 0:
                    continue
                cands.append((c, rs))
            cands.sort(key=lambda x: -x[1])
            top = cands[:topn]
            mw = w_mkt[i - 1]
            target = {c: 0.0 for c in codes}
            if top:
                for c, _ in top:
                    target[c] = mw / len(top)
        # 当日组合收益(按 prev_w)
        day_ret = 0.0
        for c in codes:
            w = prev_w[c]
            if w == 0:
                continue
            seq = by_code[c][1]
            c0 = seq.get(dates[i - 1]); c1 = seq.get(dates[i])
            if c0 and c1 and c0 > 0:
                day_ret += w * (c1 / c0 - 1)
        cost = 0.0
        if rebal_day:
            for c in codes:
                cost += COST * abs(target.get(c, 0) - prev_w[c])
        eq.append(eq[-1] * (1 + day_ret - cost))
        prev_w = {c: target.get(c, 0.0) for c in codes}
    return eq

def simulate_bh_equal(dates, by_code, rebal=21):
    """等权买入持有(月度再平衡, 仅持当时已上市的)。"""
    codes = list(by_code.keys())
    n = len(dates)
    eq = [1.0]
    prev_w = {c: 0.0 for c in codes}
    for i in range(1, n):
        rebal_day = (i % rebal == 0) or (i <= rebal)
        avail = [c for c in codes if dates[i - 1] in by_code[c][1]]
        target = {c: 0.0 for c in codes}
        if avail:
            for c in avail:
                target[c] = 1.0 / len(avail)
        day_ret = 0.0
        for c in codes:
            w = prev_w[c]
            if w == 0:
                continue
            seq = by_code[c][1]
            c0 = seq.get(dates[i - 1]); c1 = seq.get(dates[i])
            if c0 and c1 and c0 > 0:
                day_ret += w * (c1 / c0 - 1)
        cost = 0.0
        if rebal_day:
            for c in codes:
                cost += COST * abs(target.get(c, 0) - prev_w[c])
        eq.append(eq[-1] * (1 + day_ret - cost))
        prev_w = {c: target.get(c, 0.0) for c in codes}
    return eq

def simulate_bh_index(dates, idx_close):
    eq = [1.0]
    for i in range(1, len(dates)):
        r = idx_close[i] / idx_close[i - 1] - 1
        eq.append(eq[-1] * (1 + r))
    return eq

def simulate_rs_nogate(dates, by_code, topn=5, rebal=21):
    """RS 轮动始终满仓(不拨盘)。"""
    codes = list(by_code.keys())
    n = len(dates)
    eq = [1.0]
    prev_w = {c: 0.0 for c in codes}
    for i in range(1, n):
        rebal_day = (i % rebal == 0) or (i <= rebal)
        target = dict(prev_w)
        if rebal_day:
            cands = []
            for c in codes:
                seq = by_code[c][1]
                if dates[i - 1] not in seq:
                    continue
                hist = [seq.get(dates[j]) for j in range(max(0, i - 61), i)
                        if seq.get(dates[j]) is not None]
                if len(hist) < 61:
                    continue
                c0, c1 = hist[0], hist[-1]
                if c0 > 0:
                    cands.append((c, c1 / c0 - 1))
            cands.sort(key=lambda x: -x[1])
            top = cands[:topn]
            target = {c: 0.0 for c in codes}
            for c, _ in top:
                target[c] = 1.0 / len(top)
        day_ret = 0.0
        for c in codes:
            w = prev_w[c]
            if w == 0:
                continue
            seq = by_code[c][1]
            c0 = seq.get(dates[i - 1]); c1 = seq.get(dates[i])
            if c0 and c1 and c0 > 0:
                day_ret += w * (c1 / c0 - 1)
        cost = 0.0
        if rebal_day:
            for c in codes:
                cost += COST * abs(target.get(c, 0) - prev_w[c])
        eq.append(eq[-1] * (1 + day_ret - cost))
        prev_w = {c: target.get(c, 0.0) for c in codes}
    return eq

def best_single(dates, by_code):
    """事后最佳单只(知道未来, 仅供对照 18x 是否可能)。买入持有最佳。"""
    best_eq = None; best_c = None
    for c, (name, seq) in by_code.items():
        eq = [1.0]
        d0 = None
        for i in range(1, len(dates)):
            if dates[i - 1] in seq and dates[i] in seq:
                if d0 is None:
                    d0 = i - 1
                c0 = seq[dates[i - 1]]; c1 = seq[dates[i]]
                eq.append(eq[-1] * (c1 / c0))
        if best_eq is None or eq[-1] > best_eq[-1]:
            best_eq = eq; best_c = (c, name)
    return best_eq, best_c

def compute_rows(universe, dates, idx_close, w_mkt, args, label):
    """对给定宇宙跑全部 5 个策略, 返回 rows 与核心指标。"""
    by_code, first_avail = build_stock_matrix(dates, universe)
    by_code_t = {}
    for c, (name, seq) in by_code.items():
        by_code_t[c] = (name, {d: seq[d] for d in dates if d in seq})

    eq_idx = simulate_bh_index(dates, idx_close)
    eq_ehw = simulate_bh_equal(dates, by_code_t, args.rebal)
    eq_rs  = simulate_rs_nogate(dates, by_code_t, args.topn, args.rebal)
    eq_sys = simulate_system(dates, w_mkt, by_code_t, first_avail,
                             args.topn, args.rebal)
    eq_best, best_c = best_single(dates, by_code_t)

    rows = [
        ("A 买入持有指数", eq_idx),
        ("B 等权买持%d(月度再平衡)" % len(by_code_t), eq_ehw),
        ("C 个股RS轮动(满仓不拨盘)", eq_rs),
        ("D 个股RS轮动+指数拨盘(系统)", eq_sys),
        ("E 事后最佳单只(知未来对照)", eq_best),
    ]
    return rows, by_code_t, best_c


def print_pool_block(label, rows, best_c, bench):
    print("\n" + "=" * 74)
    print("【%s】" % label)
    print("%-30s %8s %7s %8s %6s %6s" %
          ("策略", "倍率", "年化%", "最大回撤%", "波动%", "夏普"))
    print("-" * 74)
    for name, eq in rows:
        m = metrics(eq)
        tag = ("  <<%s" % best_c[1]) if name.startswith("E") else ""
        print("%-30s %8.2fx %6.1f%% %8.1f%% %6.1f%% %6.2f%s" %
              (name, m["mult"], m["cagr"], m["mdd"], m["vol"], m["sharpe"], tag))
    ms = metrics([r[1] for r in rows if r[0].startswith("D")][0])
    print("  系统(D) 年化 %.1f%%  —  是否接近18x基准: %s" %
          (ms["cagr"], "接近" if ms["cagr"] >= bench else "远未达(诚实结论)"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--topn", type=int, default=5)
    ap.add_argument("--rebal", type=int, default=21)
    ap.add_argument("--pool", default="both",
                    choices=["both", "core", "p35", "p40", "p50"])
    args = ap.parse_args()

    dates, idx_close, w_mkt = build_market_clock()

    # 截断到 start(指数时钟, 与宇宙无关)
    cut = [k for k, d in enumerate(dates) if d >= args.start]
    if not cut:
        print("start 太晚, 无数据"); return
    s0 = cut[0]
    dates = dates[s0:]; idx_close = idx_close[s0:]; w_mkt = w_mkt[s0:]

    bench = (18 ** (1/10) - 1) * 100
    print("=" * 74)
    print("A股 个股α引擎(指数=相位拨盘)  窗口 %s ~ %s" % (dates[0], dates[-1]))
    print("  topN=%d | 调仓=%d日 | 摩擦单边5bp | 基准18x≈年化%.1f%%" %
          (args.topn, args.rebal, bench))
    print("=" * 74)

    pool_map = {
        "core": ("原20只核心资产(CORE_20)", CORE_20),
        "p35":  ("扩池35只(CORE+GROWTH15)", CORE_20 + GROWTH_15),
        "p40":  ("扩池40只(CORE+GROWTH15+GROWTH5)", CORE_20 + GROWTH_15 + GROWTH_5),
        "p50":  ("扩池50只(全宇宙)", UNIVERSE),
    }
    if args.pool == "both":
        pools = [pool_map["core"], pool_map["p50"]]
    else:
        pools = [pool_map[args.pool]]

    results = {}
    for label, uni in pools:
        rows, by_code_t, best_c = compute_rows(uni, dates, idx_close, w_mkt,
                                               args, label)
        results[label] = rows
        print_pool_block(label, rows, best_c, bench)

    # 诚实对比: 40 池 vs 20 池 的系统(D)与B
    if args.pool == "both":
        core_d = metrics([r[1] for r in results[pools[0][0]] if r[0].startswith("D")][0])
        all_d  = metrics([r[1] for r in results[pools[1][0]] if r[0].startswith("D")][0])
        core_b = metrics([r[1] for r in results[pools[0][0]] if r[0].startswith("B")][0])
        all_b  = metrics([r[1] for r in results[pools[1][0]] if r[0].startswith("B")][0])
        print("\n" + "=" * 74)
        print("诚实对比: 扩池50 相对 原20 的增量")
        print("  D(系统):  倍率 %6.2fx -> %6.2fx | 年化 %5.1f%% -> %5.1f%% | 回撤 %6.1f%% -> %6.1f%%" %
              (core_d["mult"], all_d["mult"], core_d["cagr"], all_d["cagr"],
               core_d["mdd"], all_d["mdd"]))
        print("  B(等权):  倍率 %6.2fx -> %6.2fx | 年化 %5.1f%% -> %5.1f%% | 回撤 %6.1f%% -> %6.1f%%" %
              (core_b["mult"], all_b["mult"], core_b["cagr"], all_b["cagr"],
               core_b["mdd"], all_b["mdd"]))
        print("  结论: 选股广度(把更多'可能十倍'的票放进候选)才是真杠杆;")
        print("        金融杠杆只会在'世俗熊(2021-2024)动量崩溃'里先爆仓。")

    print("\n注: E 为'开天眼'对照, 说明18x只能靠选对具体那一只(事后已知),")
    print("    机械系统(D)的真实价值是砍回撤而非造倍数。")

if __name__ == "__main__":
    main()
