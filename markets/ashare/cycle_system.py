# -*- coding: utf-8 -*-
"""
cycle_system.py
===============
A 股「牛熊周期定位系统」——对标比特币周期的系统性周期分析。

核心思路(与比特币周期同构):
  - 用"从滚动高点回撤 ≥ bull_dd 确认牛市终结/顶部"、 "从滚动低点反弹 ≥ bear_up 确认熊市终结/底部"
    把价格历史切成交替的 牛市段 / 熊市段(算法, 不硬编码)。
  - 定位当前处于哪一轮周期的哪个阶段, 并对比"历史每轮涨到多少见顶 / 跌到多少见底"
    给出"周期进度"(类似比特币 '我们在这轮周期的哪个位置')。

接口: AkShare 指数日线全历史(analog_core.fetch_index_long, 1990 至今)。
输出: records/<日期>_A股牛熊周期定位.md
"""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(__file__))
import analog_core as ac


# --------------------------------------------------------------------------
# 周期切分(基于回撤, 类比比特币周期牛熊线)
# --------------------------------------------------------------------------
def detect_cycles(bars, bull_dd=0.25, bear_up=0.20):
    """返回 (cycles, state)。cycles: 已闭合段列表 + 最后一段(未闭合)。
    每段: {type, start_idx, end_idx, peak_idx/trough_idx, start_p, peak_p/trough_p,
           peak_d/trough_d, ret(段内涨跌幅), from_low/from_peak(最后段才有)}。
    """
    n = len(bars)
    cycles = []
    state = "bull"                      # 假设从历史最低点起为牛市
    run_peak = bars[0]["c"]; run_peak_i = 0
    run_trough = bars[0]["c"]; run_trough_i = 0
    seg_start_i = 0; seg_start_p = bars[0]["c"]

    for i in range(1, n):
        p = bars[i]["c"]
        if state == "bull":
            if p > run_peak:
                run_peak = p; run_peak_i = i
            if run_peak > 0 and p / run_peak - 1 <= -bull_dd:
                cycles.append({"type": "bull", "start_idx": seg_start_i,
                               "end_idx": run_peak_i, "peak_idx": run_peak_i,
                               "start_p": seg_start_p, "peak_p": run_peak,
                               "peak_d": bars[run_peak_i]["d"],
                               "ret": run_peak / seg_start_p - 1})
                state = "bear"; run_trough = p; run_trough_i = i
                seg_start_i = run_peak_i; seg_start_p = run_peak
        else:  # bear
            if p < run_trough:
                run_trough = p; run_trough_i = i
            if run_trough > 0 and p / run_trough - 1 >= bear_up:
                cycles.append({"type": "bear", "start_idx": seg_start_i,
                               "end_idx": run_trough_i, "trough_idx": run_trough_i,
                               "start_p": seg_start_p, "trough_p": run_trough,
                               "trough_d": bars[run_trough_i]["d"],
                               "ret": run_trough / seg_start_p - 1})
                state = "bull"; run_peak = p; run_peak_i = i
                seg_start_i = run_trough_i; seg_start_p = run_trough

    # 最后一段(未闭合)
    last = {"type": state, "start_idx": seg_start_i, "end_idx": n - 1,
            "start_p": seg_start_p, "last_p": bars[-1]["c"], "last_d": bars[-1]["d"]}
    if state == "bull":
        last["peak_p"] = run_peak; last["peak_d"] = bars[run_peak_i]["d"]
        last["from_low"] = bars[-1]["c"] / seg_start_p - 1
        last["from_peak"] = (bars[-1]["c"] / run_peak - 1) if run_peak > 0 else 0.0
    else:
        last["peak_p"] = run_peak; last["peak_d"] = bars[run_peak_i]["d"]
        last["trough_p"] = run_trough; last["trough_d"] = bars[run_trough_i]["d"]
        last["from_peak"] = (bars[-1]["c"] / run_peak - 1) if run_peak > 0 else 0.0
        last["from_trough"] = bars[-1]["c"] / run_trough - 1
    cycles.append(last)
    return cycles, state


# --------------------------------------------------------------------------
# 阶段判定
# --------------------------------------------------------------------------
def stage_label(seg, state):
    if state == "bull":
        fl = seg.get("from_low", 0)
        fp = seg.get("from_peak", 0)
        if fl < 0.30:
            return "牛市早期/启动"
        if fl < 0.80:
            return "主升浪"
        if fp > -0.10:
            return "赶顶/泡沫期"
        return "见顶回落(牛市末端)"
    else:
        fh = seg.get("from_peak", 0)
        ft = seg.get("from_trough", 0)
        if fh > -0.30:
            return "主跌初期"
        if ft > -0.05:
            return "深度熊市/筑底"
        return "熊市中段(反弹中)"


# --------------------------------------------------------------------------
# 历史统计(用于"周期进度"对比)
# --------------------------------------------------------------------------
def history_stats(cycles):
    bulls = [c for c in cycles if c["type"] == "bull" and "ret" in c]
    bears = [c for c in cycles if c["type"] == "bear" and "ret" in c]
    def agg(lst, key):
        if not lst:
            return (0, 0, 0)
        vals = [c[key] for c in lst]
        return (sum(vals) / len(vals), min(vals), max(vals))
    return {"bull_avg": agg(bulls, "ret")[0], "bull_min": agg(bulls, "ret")[1],
            "bull_max": agg(bulls, "ret")[2],
            "bear_avg": agg(bears, "ret")[0], "bear_min": agg(bears, "ret")[1],
            "bear_max": agg(bears, "ret")[2],
            "n_bull": len(bulls), "n_bear": len(bears)}


# --------------------------------------------------------------------------
# 报告
# --------------------------------------------------------------------------
def pct(x):
    return f"{x*100:+.1f}%" if isinstance(x, (int, float)) else "—"


def analyze_index(name, code):
    bars = ac.fetch_index_long(code)
    cycles, state = detect_cycles(bars)
    stats = history_stats(cycles)
    last = cycles[-1]
    stage = stage_label(last, state)
    return bars, cycles, state, stats, last, stage


def main():
    today = datetime.date.today().strftime("%Y%m%d")
    L = []
    L.append(f"# A股牛熊周期定位系统（{today}）\n")
    L.append("> 方法论：对标比特币周期的分析框架——用\"从滚动高点回撤≥25%确认牛终结/见顶、从滚动低点反弹≥20%确认熊终结/见底\"，"
             "把价格历史切成交替的**牛市段/熊市段**（算法识别，非硬编码）。再对比\"历史每轮涨到多少见顶、跌到多少见底\"，"
             "定位当前处于**本轮周期的哪个阶段/进度**。\n")
    L.append("> 数据：AkShare 指数日线全历史（上证 sh000001、创业板 399006，1990 至今，单调用全量）。回撤阈值为主观参数，结论为**周期定位视角**，非交易指令。\n")

    idxs = [("上证综指", "sh000001"), ("创业板指", "399006")]
    summary = {}
    for name, code in idxs:
        bars, cycles, state, stats, last, stage = analyze_index(name, code)
        summary[name] = (state, stage, last, stats)
        L.append(f"## 一、{name} · 历史牛熊周期表\n")
        L.append(f"样本 {bars[0]['d']} → {bars[-1]['d']}，共 {len(bars)} 个交易日。\n")
        L.append("| # | 类型 | 起点(日期/收盘) | 顶/底(日期/价位) | 段内涨跌幅 | 时长(交易日) |")
        L.append("|---|---|---|---|---|---|")
        closed = [c for c in cycles if "ret" in c]
        for i, c in enumerate(closed, 1):
            if c["type"] == "bull":
                ext = f"顶 {c['peak_d']} / {c['peak_p']:.0f}"
            else:
                ext = f"底 {c['trough_d']} / {c['trough_p']:.0f}"
            dur = c["end_idx"] - c["start_idx"]
            L.append(f"| {i} | {'牛市' if c['type']=='bull' else '熊市'} | "
                     f"{bars[c['start_idx']]['d']} / {c['start_p']:.0f} | {ext} | {pct(c['ret'])} | {dur} |")

        # 当前
        L.append(f"\n**当前状态：{'牛市段' if state=='bull' else '熊市段'} · 阶段判定：{stage}**\n")
        if state == "bull":
            L.append(f"- 本轮自低点({bars[last['start_idx']]['d']} / {last['start_p']:.0f}) 已上涨 **{pct(last['from_low'])}**")
            L.append(f"- 距本轮高点({last['peak_d']} / {last['peak_p']:.0f}) 回撤 **{pct(last['from_peak'])}**")
        else:
            L.append(f"- 本轮自高点({last['peak_d']} / {last['peak_p']:.0f}) 已回撤 **{pct(last['from_peak'])}**")
            L.append(f"- 距本轮低点({last['trough_d']} / {last['trough_p']:.0f}) 反弹 **{pct(last['from_trough'])}**")
        L.append(f"\n**历史参照（{stats['n_bull']}轮牛市 / {stats['n_bear']}轮熊市）：**")
        L.append(f"- 牛市从低点平均涨幅 **{pct(stats['bull_avg'])}**（区间 {pct(stats['bull_min'])} ~ {pct(stats['bull_max'])}）")
        L.append(f"- 熊市从高点平均回撤 **{pct(stats['bear_avg'])}**（区间 {pct(stats['bear_min'])} ~ {pct(stats['bear_max'])}）")
        if state == "bull":
            prog = last["from_low"] / stats["bull_avg"] if stats["bull_avg"] else 0
            L.append(f"- **周期进度（本轮涨幅 / 历史牛市平均涨幅）：≈ {prog*100:.0f}%** —— "
                     f"{'已接近或超出历史均值，警惕赶顶' if prog>=0.9 else '仍有空间' if prog<0.7 else '进入中后段'}")
        else:
            prog = last["from_peak"] / stats["bear_avg"] if stats["bear_avg"] else 0
            L.append(f"- **底部进度（本轮回撤 / 历史熊市平均回撤）：≈ {prog*100:.0f}%** —— "
                     f"{'回撤已充分，接近历史底部区' if prog>=0.9 else '回撤尚未到位' if prog<0.7 else '进入下半场'}")
        L.append("")

    L.append("## 二、系统性结论（多空立场，仅市场视角）\n")
    sh_state, sh_stage, sh_last, sh_stats = summary["上证综指"]
    cyb_state, cyb_stage, cyb_last, cyb_stats = summary["创业板指"]
    L.append(f"- **宽基（上证）= {sh_stage}**：{('从低点'+pct(sh_last.get('from_low',0))+'、未破前高') if sh_state=='bull' else ('从高点'+pct(sh_last.get('from_peak',0)))}。"
             "上证被权重(银行/红利/防御)托住，结构性强弱被掩盖。")
    L.append(f"- **成长（创业板）= {cyb_stage}**：创业板是这一轮\"AI/科技大牛市\"的主战场，"
             f"{('从低点'+pct(cyb_last.get('from_low',0))) if cyb_state=='bull' else ('从高点'+pct(cyb_last.get('from_peak',0)))}。"
             "用户感知的\"退潮/收割\"主要在创业板与科技硬件(半导体/通信/芯片 6月底脉冲顶后腰斩)，与宽基周期错位。")
    L.append("- **空方**：若创业板已进入\"见顶回落/主跌\"且上证周期进度偏高，则本轮 AI 大牛市处中后段，"
             "高位成长退潮是周期规律的体现，后续轮动至低位价值/困境反转。")
    L.append("- **多方**：若上证/创业板均处\"主升浪早期\"且周期进度<70%，则 AI 主线未尽，回调即布局窗口。")
    L.append("- **中性推演**：A 股牛熊比比特币更受政策/资金驱动、更混乱；周期定位给\"大概位置\"，"
             "需与板块轮动(资金流)和类比预测(analog_core)交叉验证，不可单凭周期下注。")

    L.append("\n## 三、诚实声明\n")
    L.append("- 牛熊切分依赖主观回撤阈值(牛25%/熊20%)，阈值改变会改变分段数量与结论。")
    L.append("- \"周期进度\"是相对历史均值的粗略类比，A 股样本少(主要牛熊仅数轮)，统计意义有限。")
    L.append("- 本系统定位\"当前在哪一轮、哪个阶段\"，是方向性框架，非择时信号；与 etf_fund_flow(资金)、analog_core(预测回测) 互补。")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "records")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{today}_A股牛熊周期定位.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    # 终端摘要
    for name, code in idxs:
        _, stage, last, stats = summary[name]
        print(f"{name}: {stage} | 进度数据见报告", file=sys.stderr)
    print(f"\n报告已生成: {out_path}", file=sys.stderr)
    return out_path


if __name__ == "__main__":
    main()
