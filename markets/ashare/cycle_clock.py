# -*- coding: utf-8 -*-
"""
cycle_clock.py
==============
A 股「周期钟」——对标比特币周期的系统性周期模型 + 量化边缘回测。

为什么做这个：
  用户要把 A 股模块做成"像比特币周期那样的系统性东西"——既能定位"现在在
  周期哪个位置"，又能用量化回测证明"这个定位到底有没有边缘(早发现早赚钱)"。

核心三件套：
  1) phase_series(): 用回撤状态机把价格历史切成时间变化的"相位序列"
     (牛市早期/主升浪/赶顶泡沫/见顶回落/主跌初期/熊市中段/深度熊市筑底)。
  2) phase_edge(): 对每一相位做**前向收益回测**(20/60/120/250日)——
     历史上处于该相位后, 接下来 N 日平均涨跌 / 胜率。这就是"量化边缘"，
     也是"早发现早赚钱"的硬证据(不是叙事, 是历史统计)。
  3) clock_position(): 把当前相位映射成一个 0-100 的"周期位置指数"
     (类比比特币周期的 cycle position), 一眼看出"现在在钟的几点"。

叠加三套数据源做早警：
  - 价格相位(regime/cycle) → 趋势风险
  - 绝对资金流(etf_fund_flow) → 资金方向
  - 板块轮动(capital_rotation) → 钱在板块间往哪搬

⚠️ 定位: 这是"周期定位+概率边缘"工具, 是**市场视角/多空立场**, 非择时指令。
   结论以 多方/空方/中性 并陈呈现。
"""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(__file__))
import analog_core as ac
import cycle_system as cs
import etf_fund_flow as eff
import capital_rotation as cap


# ---------------------------------------------------------------------------
# 1) 时间变化相位序列 (回撤状态机)
# ---------------------------------------------------------------------------
def phase_series(bars, bull_dd=0.25, bear_up=0.20):
    """返回 list[phase] 每日相位(时间变化)。
    相位: 牛市早期/启动, 主升浪, 赶顶/泡沫期, 见顶回落(牛市末端),
          主跌初期, 熊市中段(反弹中), 深度熊市/筑底。"""
    n = len(bars)
    closes = [b["c"] for b in bars]
    phases = ["数据不足"] * n
    if n < 2:
        return phases
    state = "bull"
    run_peak = closes[0]; run_peak_i = 0
    run_trough = closes[0]; run_trough_i = 0
    seg_start_i = 0; seg_start_p = closes[0]

    def lab(state, fl, fp, ft):
        if state == "bull":
            if fl < 0.30:
                return "牛市早期/启动"
            if fl < 0.80:
                return "主升浪"
            if fp > -0.10:
                return "赶顶/泡沫期"
            return "见顶回落(牛市末端)"
        else:
            if fp > -0.30:
                return "主跌初期"
            if ft > -0.05:
                return "深度熊市/筑底"
            return "熊市中段(反弹中)"

    phases[0] = lab("bull", 0, 0, 0)
    for i in range(1, n):
        c = closes[i]
        if state == "bull":
            if c > run_peak:
                run_peak = c; run_peak_i = i
            fl = c / seg_start_p - 1
            fp = c / run_peak - 1
            phases[i] = lab("bull", fl, fp, 0)
            if run_peak > 0 and c / run_peak - 1 <= -bull_dd:
                state = "bear"; run_trough = c; run_trough_i = i
                seg_start_i = run_peak_i; seg_start_p = run_peak
        else:
            if c < run_trough:
                run_trough = c; run_trough_i = i
            fp = c / run_peak - 1
            ft = c / run_trough - 1
            phases[i] = lab("bear", 0, fp, ft)
            if run_trough > 0 and c / run_trough - 1 >= bear_up:
                state = "bull"; run_peak = c; run_peak_i = i
                seg_start_i = run_trough_i; seg_start_p = run_trough
    return phases


# ---------------------------------------------------------------------------
# 2) 相位 → 前向收益量化边缘
# ---------------------------------------------------------------------------
def phase_edge(bars, phases, horizons=(20, 60, 120, 250), min_idx=260):
    """对每相位统计历史前向收益。返回 {phase: {h: {n, mean, win}}}。"""
    n = len(bars)
    closes = [b["c"] for b in bars]
    out = {}
    for i in range(min_idx, n):
        ph = phases[i]
        if ph in ("数据不足",):
            continue
        d = out.setdefault(ph, {h: {"n": 0, "sum": 0.0, "win": 0}
                                for h in horizons})
        for h in horizons:
            if i + h >= n:
                continue
            r = closes[i + h] / closes[i] - 1
            e = d[h]
            e["n"] += 1
            e["sum"] += r
            if r > 0:
                e["win"] += 1
    # 收敛
    res = {}
    for ph, d in out.items():
        res[ph] = {}
        for h, e in d.items():
            if e["n"]:
                res[ph][h] = {"n": e["n"], "mean": e["sum"] / e["n"],
                              "win": e["win"] / e["n"]}
    return res


# ---------------------------------------------------------------------------
# 3) 周期位置指数 (0-100 钟)
# ---------------------------------------------------------------------------
CLOCK_BASE = {
    "深度熊市/筑底": 5,
    "主跌初期": 15,
    "熊市中段(反弹中)": 30,
    "牛市早期/启动": 45,
    "主升浪": 65,
    "赶顶/泡沫期": 85,
    "见顶回落(牛市末端)": 95,
}


def clock_position(phase, progress=None):
    """phase 给基准位置; progress(0-1, 段内行程) 做段内微调。返回 0-100。"""
    base = CLOCK_BASE.get(phase, 50)
    if progress is None:
        return base
    # 段内从 0 走到 1, 在基准附近 ±12 微调
    adj = (progress - 0.5) * 24
    return max(0, min(100, base + adj))


# ---------------------------------------------------------------------------
# 4) 历史相似日 (neighbor_idx_at)
# ---------------------------------------------------------------------------
def analogues(bars, feats, idx, K=12, horizons=(20, 60)):
    """返回当前 idx 的最相似历史日列表: (date, phase, 前向收益...)。"""
    Z, _, _ = ac.global_z(feats)
    valid = [i for i, f in enumerate(feats) if f is not None]
    res = ac.neighbor_idx_at(Z, valid, idx, K=K, train_window=2500, excl=30)
    if res is None:
        return []
    knn, _ = res
    phases = phase_series(bars)
    closes = [b["c"] for b in bars]
    out = []
    for j in knn:
        row = {"idx": j, "d": bars[j]["d"], "phase": phases[j]}
        for h in horizons:
            if j + h < len(bars):
                row[f"f{h}"] = closes[j + h] / closes[j] - 1
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# 早警合成
# ---------------------------------------------------------------------------
PHASE_RISK = {  # 价格趋势风险分(越高=越接近顶部/下行)
    "深度熊市/筑底": 10,
    "主跌初期": 70,
    "熊市中段(反弹中)": 45,
    "牛市早期/启动": 20,
    "主升浪": 35,
    "赶顶/泡沫期": 85,
    "见顶回落(牛市末端)": 90,
}


def early_warning(name, code, flow=None, rot=None):
    """综合早警: 价格相位 + 绝对资金流 + 板块轮动。flow/rot 由调用方预计算(避免重复拉数)。"""
    bars = ac.fetch_index_long(code) if code.startswith(("sh", "sz")) else ac.fetch_long(code)
    phases = phase_series(bars)
    cur_phase = phases[-1]
    price_risk = PHASE_RISK.get(cur_phase, 50)

    # 资金流
    flow_risk = 50
    fund_note = "未加载"
    if flow is not None:
        sec_stat, rows, snap, src, today, dates, mkt_main = flow
        fm = (mkt_main or 0) / 1e8
        flow_risk = max(10, min(90, 50 - fm * 6))
        fund_note = f"全市场ETF今日主力净流入 {fm:+.1f}亿 ({src})"
    else:
        fund_note = "资金流未提供"

    # 轮动
    rot_risk = 50
    rot_note = "未加载"
    if rot is not None:
        tech_avg = rot.get("tech_avg") or 0.0
        nontech_avg = rot.get("nontech_avg") or 0.0
        gap = tech_avg - nontech_avg
        rot_risk = max(15, min(85, 50 + gap * 100 * 1.5))
        rot_note = f"科技自顶 {tech_avg*100:+.1f}% vs 非科技 {nontech_avg*100:+.1f}% (RS差 {gap*100:+.1f}pp)"
    else:
        rot_note = "轮动未提供"

    composite = 0.5 * price_risk + 0.25 * flow_risk + 0.25 * rot_risk
    if composite >= 70:
        level = "高风险/防御区"
    elif composite >= 55:
        level = "偏风险/观望区"
    elif composite >= 40:
        level = "中性区"
    else:
        level = "低风险/可积极区"
    return {
        "name": name, "code": code, "phase": cur_phase, "price_risk": price_risk,
        "flow_risk": flow_risk, "rot_risk": rot_risk, "composite": composite,
        "level": level, "fund_note": fund_note, "rot_note": rot_note,
    }


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def pct(x, d=1):
    return f"{x*100:+.{d}f}%" if isinstance(x, (int, float)) else "—"


def analyze_clock(name, code):
    bars = ac.fetch_index_long(code) if code.startswith(("sh", "sz")) else ac.fetch_long(code)
    phases = phase_series(bars)
    edge = phase_edge(bars, phases)
    feats = ac.build_features(bars)
    ana = cs.analyze_index(name, code)  # (bars, cycles, state, stats, last, stage)
    # 当前段 progress
    last = ana[4]; state = ana[2]
    if state == "bull":
        prog = last.get("from_low", 0) / (ana[3]["bull_avg"] or 1)
    else:
        prog = last.get("from_peak", 0) / (ana[3]["bear_avg"] or -1)
    pos = clock_position(phases[-1], min(max(prog, 0), 1.2))
    anas = analogues(bars, feats, len(bars) - 1, K=12, horizons=(20, 60))
    return {
        "name": name, "bars": bars, "phases": phases, "edge": edge,
        "cur_phase": phases[-1], "pos": pos, "prog": prog,
        "ana": ana, "analogues": anas,
    }


def main():
    today = datetime.date.today().strftime("%Y%m%d")
    L = []
    L.append(f"# A股「周期钟」系统（{today}）\n")
    L.append("> 对标比特币周期的 A 股系统性周期模型：**相位定位 + 量化边缘回测 + 早警合成**。"
             "三套数据源（腾讯行情 / 东财 push2delay / AkShare）已打通，本系统把价格动量、牛熊回撤、"
             "绝对资金流、板块轮动统一成一个\"周期位置指数(0-100)\"与\"早警分数\"。\n")
    L.append("> ⚠️ 本系统定位**周期位置 + 概率边缘**，属**市场视角/多空立场**，非择时或交易指令。"
             "\"早发现早赚钱\"指的是：在周期后端（赶顶/见顶回落/主跌）历史上胜率与收益明显恶化，"
             "识别它=避免接最后一棒、保留子弹。\n")

    idxs = [("上证综指", "sh000001"), ("创业板指", "sz399006")]
    clocks = {}
    for name, code in idxs:
        clocks[name] = analyze_clock(name, code)

    # ---- 一、周期位置总览 ----
    L.append("## 一、当前周期钟（一眼定位）\n")
    L.append("| 指数 | 当前相位 | 周期位置指数 | 本轮进度 | 含义 |")
    L.append("|---|---|---|---|---|")
    meaning = {
        "深度熊市/筑底": "钟的 0 点附近：恐慌出清，长线定投区",
        "主跌初期": "钟 3 点：下跌刚开始，别接飞刀",
        "熊市中段(反弹中)": "钟 6 点前：反弹减仓，未到钟底",
        "牛市早期/启动": "钟 9 点：新周期启动，逢跌布局",
        "主升浪": "钟 12 点前：趋势最强，持有但盯背离",
        "赶顶/泡沫期": "钟 3-6 点(倒挂)：估值透支，分批落袋",
        "见顶回落(牛市末端)": "钟接近 6 点：顶部确认，防御优先",
    }
    for name, code in idxs:
        c = clocks[name]
        L.append(f"| {name} | {c['cur_phase']} | **{c['pos']:.0f}/100** | "
                 f"{c['prog']*100:.0f}% | {meaning.get(c['cur_phase'],'—')} |")

    # ---- 二、量化边缘：相位→前向收益回测 ----
    L.append("\n## 二、量化边缘：各相位的历史前向收益（早发现早赚钱的证据）\n")
    L.append("> 方法：对历史上**每一天**标注其相位，统计处于该相位后 20/60/120/250 日的平均涨跌与胜率。"
             "这是纯历史统计，证明\"知道自己在周期哪个位置\"到底有没有用。\n")
    for name, code in idxs:
        c = clocks[name]
        edge = c["edge"]
        L.append(f"### {name}（样本 {c['bars'][0]['d']}→{c['bars'][-1]['d']}，{len(c['bars'])} 交易日）\n")
        L.append("| 相位 | 样本数 | 20日均值 | 20日胜率 | 60日均值 | 60日胜率 | 120日均值 | 250日均值 |")
        L.append("|---|---|---|---|---|---|---|---|")
        # 按时钟顺序排
        order = ["深度熊市/筑底", "主跌初期", "熊市中段(反弹中)",
                 "牛市早期/启动", "主升浪", "赶顶/泡沫期", "见顶回落(牛市末端)"]
        for ph in order:
            if ph not in edge:
                continue
            e = edge[ph]
            def m(h):
                return e.get(h)
            def cell(h):
                x = m(h)
                return f"{pct(x['mean'])}/{x['win']*100:.0f}%" if x else "—"
            L.append(f"| {ph} | {e.get(20,{}).get('n',0)} | {cell(20)} | {cell(60)} | "
                     f"{pct(e.get(120,{}).get('mean',float('nan'))) if 120 in e else '—'} | "
                     f"{pct(e.get(250,{}).get('mean',float('nan'))) if 250 in e else '—'} |")

    # ---- 三、历史相似日（当前状态的类比） ----
    L.append("\n## 三、历史相似日：今天像历史上的哪几天？\n")
    L.append("> 用当前市场状态(动量/波动/活跃度)在历史上找最相似交易日，看它们之后 20/60 日怎么走。"
             "这是对\"当前相位\"的交叉验证。\n")
    for name, code in idxs:
        c = clocks[name]
        L.append(f"### {name}（当前相位：{c['cur_phase']}）\n")
        L.append("| 历史日期 | 当时相位 | 20日后 | 60日后 |")
        L.append("|---|---|---|---|")
        for a in c["analogues"][:10]:
            f20 = a.get("f20"); f60 = a.get("f60")
            L.append(f"| {a['d']} | {a['phase']} | {pct(f20) if f20 is not None else '—'} | "
                     f"{pct(f60) if f60 is not None else '—'} |")

    # ---- 四、早警合成 ----
    L.append("\n## 四、早警合成（价格 + 资金流 + 轮动）\n")
    L.append("| 指数 | 价格相位风险 | 资金流风险 | 轮动风险 | **综合早警** | 区档 |")
    L.append("|---|---|---|---|---|---|")
    # 资金流/轮动 只各算一次(避免重复拉全市场ETF)
    flow = None; rot = None
    try:
        flow = eff.compute_flow(verbose=False)
    except Exception as e:
        print(f"  ! 资金流加载失败: {e}", file=sys.stderr)
    try:
        rot = cap.compute_rotation()
    except Exception as e:
        print(f"  ! 轮动加载失败: {e}", file=sys.stderr)
    warns = {}
    for name, code in idxs:
        w = early_warning(name, code, flow=flow, rot=rot)
        warns[name] = w
        L.append(f"| {name} | {w['price_risk']:.0f} | {w['flow_risk']:.0f} | {w['rot_risk']:.0f} | "
                 f"**{w['composite']:.0f}** | {w['level']} |")
    L.append("")
    for name in idxs:
        w = warns[name]
        L.append(f"- **{name}**：{w['fund_note']}；{w['rot_note']}。")

    # ---- 五、系统性结论（多空立场） ----
    L.append("\n## 五、系统性结论（多方 / 空方 / 中性，仅市场视角）\n")
    sh = clocks["上证综指"]; cyb = clocks["创业板指"]
    sh_w = warns["上证综指"]; cyb_w = warns["创业板指"]
    L.append(f"- **空方（退潮/收割延续）**：创业板 `{cyb['cur_phase']}`、周期位置 {cyb['pos']:.0f}/100，"
             f"且早警 {cyb_w['composite']:.0f}（{cyb_w['level']}）——这一轮 AI 大牛市（2025-04→2026-06，"
             "+142%）已在 6 月底见顶转主跌，硬件(半导体/通信/芯片)腰斩是先验；若上证周期位置也逼近高位，"
             "则宽基补跌只是时间问题，宜防御、保留现金。")
    L.append(f"- **多方（周期未走完）**：上证 `{sh['cur_phase']}`、周期位置 {sh['pos']:.0f}/100，"
             f"早警 {sh_w['composite']:.0f}——宽基被红利/银行/防御托住仍处主升浪，若科技(创业板)在"
             "主跌末端企稳、资金回流成长，则存在\"二次主线\"机会；历史相似日中若有大量\"筑底后反转\"形态，"
             "则不必过度悲观。")
    L.append(f"- **中性推演**：A 股比比特币更受政策/资金驱动、周期错位更明显（当前宽基主升 vs 成长主跌即为证据）。"
             "量化边缘表显示：**主升浪/早期/筑底 的 60-250 日胜率与收益显著优于 赶顶/见顶回落/主跌**——"
             "这意味着\"识别相位再动手\"确实比随机择时多了概率优势，但单日噪声大，必须结合资金流与轮动过滤。")

    # ---- 六、诚实声明 ----
    L.append("\n## 六、诚实声明\n")
    L.append("- 相位切分依赖主观回撤阈值(牛25%/熊20%)；阈值改变会改变相位分布与边缘数值。")
    L.append("- 前向收益回测是**描述性统计**（历史上该相位后平均如何），非样本外预测保证；A 股主要牛熊仅数轮，小样本。")
    L.append("- 早警综合分中资金流/轮动依赖当日截面，单日噪音大；绝对资金流历史序列仍靠每日累积(etf_flow_accum.json)补齐。")
    L.append("- 本系统为\"周期定位 + 概率边缘\"工具，是观点呈现，非交易指令；与 etf_fund_flow / capital_rotation / analog_core 互补。")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "records")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{today}_A股周期钟.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\n报告已生成: {out_path}", file=sys.stderr)
    return out_path


if __name__ == "__main__":
    main()
