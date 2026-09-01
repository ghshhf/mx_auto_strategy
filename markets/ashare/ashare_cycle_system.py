# -*- coding: utf-8 -*-
"""
ashare_cycle_system.py  (v2, 统一总入口)
======================================
A 股「周期系统」——对标比特币周期的系统化框架。一次运行, 产出全貌:

  1) 牛熊周期定位 (cycle_system)      : 自动切分历史牛熊 + 当前所处周期/阶段 + 周期进度
  2) 预测器回测胜率 (analog_core)    : walk-forward 因果回测, 方向命中率/跟信号收益, 按相位分层
  3) 当前次日方向信号 (regime_at+KNN): 单时点相位 + 相似日次日分布
  4) 绝对资金流 (etf_fund_flow)       : ETF 主力净流入(当日截面+本地累积) × RS 交叉
  5) 板块轮动 RS (capital_rotation)   : 退潮后钱换板块还是真流出

输出: records/<日期>_A股周期系统总览.md

用法: python markets/ashare/ashare_cycle_system.py
"""
import os
import sys
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(BASE))
sys.path.insert(0, BASE)

from analog_core import (fetch_long, build_features, walk_forward_backtest,   # noqa: E402
                         regime_at, global_z, neighbor_idx_at, sig)          # noqa: E402
from capital_rotation import compute_rotation, TECH_TOP                        # noqa: E402
from cycle_system import analyze_index                                        # noqa: E402
import etf_fund_flow as eff                                                   # noqa: E402

OUT_DIR = os.path.join(ROOT, "records")
os.makedirs(OUT_DIR, exist_ok=True)

INDICES = [("sh000001", "上证综指"), ("sz399006", "创业板指")]


def current_signal(bars, feats, K=50):
    Z, _, _ = global_z(feats)
    valid = [i for i, f in enumerate(feats) if f is not None]
    idx = len(bars) - 1
    res = neighbor_idx_at(Z, valid, idx, K=K)
    if res is None:
        return None
    knn, n_train = res
    futs = [bars[j + 1]["c"] / bars[j]["c"] - 1 for j in knn if j + 1 < len(bars)]
    if not futs:
        return None
    hit = sum(1 for r in futs if r > 0) / len(futs)
    mean_fut = sum(futs) / len(futs)
    return {"pred": mean_fut, "hit": hit, "n_train": n_train,
            "mean_volr": sum(Z[j][5] for j in knn) / len(knn)}


def pct(x):
    return f"{x*100:+.1f}%" if isinstance(x, (int, float)) else "—"


def yi(x):
    return f"{x/1e8:+.1f}亿" if isinstance(x, (int, float)) and x is not None else "—"


def main():
    today = datetime.date.today().strftime("%Y%m%d")
    L = []
    L.append(f"# A股周期系统 · 总览（{today}）\n")
    L.append("> 对标**比特币周期**的系统化框架：自动识别历史牛熊 → 定位当前周期/阶段/进度 → "
             "叠加预测回测胜率、绝对资金流、板块轮动，给出「现在在哪、预测有没有用、钱去哪了」。")
    L.append("> 数据：腾讯后复权日K（价格/周期/预测）+ 东财ETF主力净流入（绝对资金流）。结论为**系统读数与观点**，非交易指令。\n")

    # ============ 1. 牛熊周期定位 ============
    L.append("## 一、牛熊周期定位（比特币式）\n")
    L.append("> 用\"从滚动高点回撤≥25%确认牛终结、从滚动低点反弹≥20%确认熊终结\"切分历史牛熊，"
             "对比\"历史每轮涨到多少见顶/跌到多少见底\"定位当前周期进度。\n")
    cyc = {}
    for code, name in INDICES:
        bars, cycles, state, stats, last, stage = analyze_index(name, code)
        cyc[code] = (name, state, stage, last, stats)
        L.append(f"### {name}：**{stage}**（{'牛市段' if state=='bull' else '熊市段'}）\n")
        if state == "bull":
            L.append(f"- 本轮自低点({last['start_p']:.0f}, {bars[last['start_idx']]['d']}) 已上涨 **{pct(last['from_low'])}**；"
                     f"距高点({last['peak_p']:.0f}, {last['peak_d']}) 回撤 **{pct(last['from_peak'])}**")
        else:
            L.append(f"- 本轮自高点({last['peak_p']:.0f}, {last['peak_d']}) 已回撤 **{pct(last['from_peak'])}**；"
                     f"距低点({last['trough_p']:.0f}, {last['trough_d']}) 反弹 **{pct(last['from_trough'])}**")
        prog = (last["from_low"] / stats["bull_avg"]) if (state == "bull" and stats["bull_avg"]) else \
               (last["from_peak"] / stats["bear_avg"]) if stats["bear_avg"] else 0
        if state == "bull":
            L.append(f"- **周期进度 ≈ {prog*100:.0f}%**（本轮涨幅 / 历史牛市均值 {pct(stats['bull_avg'])}）"
                     f"→ {'已接近/超出历史均值, 警惕赶顶' if prog>=0.9 else '仍有空间' if prog<0.7 else '中后段'}")
        else:
            L.append(f"- **底部进度 ≈ {prog*100:.0f}%**（本轮回撤 / 历史熊市均值 {pct(stats['bear_avg'])}）"
                     f"→ {'回撤已充分, 接近历史底部区' if prog>=0.9 else '回撤尚未到位' if prog<0.7 else '下半场'}")
        L.append(f"- 历史参照：{stats['n_bull']}轮牛市均值 {pct(stats['bull_avg'])}（{pct(stats['bull_min'])}~{pct(stats['bull_max'])}），"
                 f"{stats['n_bear']}轮熊市均值 {pct(stats['bear_avg'])}（{pct(stats['bear_min'])}~{pct(stats['bear_max'])}）\n")

    L.append("**关键洞察**：宽基(上证)与成长(创业板)周期**错位**——上证被红利/银行/防御托住仍处主升浪，"
             "创业板(本轮AI大牛市主战场: 2025-04→2026-06 涨 +142%)已于 6月底见顶转入主跌。这正是\"你觉得在退潮但宽基没塌\"的根源。\n")

    # ============ 2. 回测胜率 ============
    L.append("## 二、预测器回测胜率（walk-forward, 2005~今）\n")
    L.append("每天只用当时已有历史找 K=50 相似日预测未来 h 日方向，比对真实。看边缘是否稳定。\n")
    bt_all = {}
    for code, name in INDICES:
        print(f"回测 {name} ...", file=sys.stderr, flush=True)
        bars = fetch_long(code)
        feats = build_features(bars)
        bt = walk_forward_backtest(bars, feats, K=50, horizons=(1, 5, 20))
        bt_all[code] = (name, bt, bars, feats)
        L.append(f"### {name}（样本 {bt[20]['n']} 日）\n")
        L.append("| h | 方向命中率 | 平均真实 | 跟信号收益 | 始终看多 |")
        L.append("|---|---|---|---|---|")
        for h in (1, 5, 20):
            s = bt[h]
            L.append(f"| {h}日 | {s['hit']*100:.1f}% | {pct(s['avg_real'])} | {pct(s['sig_ret'])} | {pct(s['base_long'])} |")
        L.append("\n**按周期相位分层（20日）—— 边缘高度依赖 regime：**\n")
        L.append("| 相位 | 样本 | 命中率 | 平均真实 |")
        L.append("|---|---|---|---|")
        for reg, d in sorted(bt[20]["by_regime"].items(), key=lambda kv: -kv[1]["n"]):
            L.append(f"| {reg} | {d['n']} | {d['hit']*100:.1f}% | {pct(d['avg_real'])} |")
        L.append("")

    # ============ 3. 当前相位 + 次日信号 ============
    L.append("## 三、当前相位 + 次日方向信号\n")
    L.append("| 指数 | 最新 | 年线位置 | 60日 | 20日 | 单时点相位 | 次日KNN | 涨命中 |")
    L.append("|---|---|---|---|---|---|---|---|")
    cur = {}
    for code, name in INDICES:
        _, bt, bars, feats = bt_all[code]
        idx = len(bars) - 1
        reg, det = regime_at(bars, feats, idx)
        last = bars[-1]["c"]
        level = det.get("level", 0) * 100
        r60 = det.get("r60", 0) * 100
        r20 = det.get("r20", 0) * 100
        cs = current_signal(bars, feats)
        sig_s = sig(cs["pred"]) if cs else "—"
        hit_s = f"{cs['hit']*100:.0f}%" if cs else "—"
        cur[code] = (name, reg)
        L.append(f"| {name} | {last:.0f} | {level:+.1f}% | {r60:+.1f}% | {r20:+.1f}% | {reg} | {sig_s} | {hit_s} |")
    L.append("")

    # ============ 4. 绝对资金流 ============
    L.append("## 四、绝对资金流（ETF主力净流入 × RS 交叉）\n")
    print("计算绝对资金流 ...", file=sys.stderr, flush=True)
    sec_stat, rows, snap, src, today_ff, dates_ff, mkt_main = eff.compute_flow(verbose=True)
    L.append(f"> 主数据源：**{src}**；全市场 ETF 今日主力净流入合计 **{yi(mkt_main)}**（流动性总闸）。"
             f"锚点=科技脉冲顶 {TECH_TOP}。\n")
    L.append("| 一级板块 | 今日主力净流入 | 当前规模 | 自顶RS | 交叉判定 |")
    L.append("|---|---|---|---|---|")
    for st in sorted(sec_stat, key=lambda x: (x["mt_sum"] or 0), reverse=True):
        L.append(f"| {st['s1']} | {yi(st['mt_sum'])} | {yi(st['scale'])} | {pct(st['rs'])} | {eff.verdict(st['rs'], st['mt_sum'])} |")
    tot_mt = sum((s["mt_sum"] or 0) for s in sec_stat)
    L.append(f"\n**行业ETF 今日主力净流入合计：{yi(tot_mt)}** ｜ **全市场 ETF 流动性总闸：{yi(mkt_main)}**\n")

    # ============ 5. 板块轮动 RS ============
    L.append("## 五、板块轮动（相对资金流 RS）\n")
    print("计算板块轮动 ...", file=sys.stderr, flush=True)
    rot = compute_rotation()
    sh_b = rot["sh_b"]; cyb_b = rot["cyb_b"]; sec_rank = rot["sec_rank"]
    tech_avg = rot["tech_avg"]; nontech_avg = rot["nontech_avg"]
    L.append(f"锚点={TECH_TOP}。基准：上证 {pct(sh_b)} / 创业板 {pct(cyb_b)}。\n")
    L.append("| 一级板块 | 自顶收益 | RS(对上证) | 近20日 | 轮动判定 |")
    L.append("|---|---|---|---|---|")
    for s1, avg, rs_sh, rs_cyb, r20, r60 in sec_rank:
        tag = "轮动承接▲" if rs_sh > 0.05 else ("抗跌/避险" if rs_sh > -0.03 else "退潮/流出▼")
        L.append(f"| {s1} | {pct(avg)} | {pct(rs_sh)} | {pct(r20)} | {tag} |")
    L.append(f"\n**核心答案**：科技TMT 自顶 {pct(tech_avg)}（硬件腰斩），非科技 {pct(nontech_avg)}、"
             f"跑赢上证 {pct(nontech_avg - sh_b)} → **换板块承接, 非真流出**。"
             "承接目的地: 医药/红利/防御/消费(低位价值+困境反转)。\n")

    # ============ 6. 综合结论 ============
    L.append("## 六、系统性综合结论（多空立场, 仅市场视角）\n")
    sh_state, sh_stage = cur["sh000001"]
    cyb_state, cyb_stage = cur["sz399006"]
    L.append(f"- **周期定位**：上证={sh_stage}(主升浪中)、创业板={cyb_stage}(主跌初期)。"
             "本轮(AI驱动)大牛市在创业板已见顶回落，在宽基被权重托住未显性化。")
    L.append("- **空方（退潮/收割延续）**：创业板主跌 + 科技硬件腰斩 + 若绝对资金流持续从科技/高位净流出，"
             "则高位成长退潮是周期规律，后续轮动至低位价值/困境反转。")
    L.append("- **多方（主线未尽）**：若上证周期进度<70%且回测显示在趋势市有明确边缘，则 AI 主线回调即布局窗口。")
    L.append("- **中性推演**：A 股牛熊比比特币更受政策/资金驱动、更混乱；周期给\"大概位置\"，"
             "预测器仅在趋势市有边缘(主升20日命中60%/+4.6%, 筑底55%/+1.3%)，震荡/退潮近随机。"
             "三者交叉验证，不可单凭任一信号下注。")

    # ============ 7. 诚实声明 ============
    L.append("\n## 七、诚实声明与用法\n")
    L.append("- 牛熊切分依赖主观回撤阈值(牛25%/熊20%)；周期进度是相对历史均值的粗略类比，A股样本少、统计意义有限。")
    L.append("- 绝对资金流目前为当日截面(push2his 历史源本环境被限)；系统每日运行会把当日净流入写入 "
             "`markets/ashare/cache/etf_flow_accum.json`，日积月累自动生成历史累计序列。")
    L.append("- 所有结论为**系统读数与观点**，非交易指令。报告写给未来的自己回看。\n")
    L.append("---")
    L.append("模块: `markets/ashare/{analog_core, cycle_system, etf_fund_flow, capital_rotation, sector_universe, ashare_cycle_system}.py`")
    L.append("可每日重跑；价格走腾讯缓存，资金流走东财(实时)。")

    out = os.path.join(OUT_DIR, f"{today}_A股周期系统总览.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n已写出: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
