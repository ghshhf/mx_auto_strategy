# -*- coding: utf-8 -*-
"""
capital_rotation.py
===================
板块资金轮动分析: 回答「科技退潮后, 钱去哪了? 真流出, 还是换板块?」

方法(稳健, 不依赖脆弱的份额历史接口):
  以科技脉冲顶 **2026-06-30** 为锚点, 计算各板块代表ETF的「相对强弱(RS)」:
    RS = 板块收益 - 宽基基准收益(上证/创业板)
  - RS 显著 >0  => 退潮期里逆势走强 = 资金轮动承接(换板块流入)
  - RS ≈ 0 / 轻微负(且属防御) => 避险承接
  - RS 显著 <0 (如科技) => 退潮/真流出重灾区

同时给出近 20/60 日动量, 区分「已经轮入并涨完」vs「正在轮入」。

⚠️ 真·ETF份额(绝对流入)需日频累积快照; 本模块用 RS(相对)作主信号, 东财规模快照作体量参考。
产出: records/<日期>_板块资金轮动.md
"""
import os
import sys
import time
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, BASE)
from analog_core import fetch_long              # noqa: E402
from sector_universe import UNIVERSE, iter_etfs  # noqa: E402

OUT_DIR = os.path.join(ROOT, "records")
os.makedirs(OUT_DIR, exist_ok=True)

TECH_TOP = "2026-06-30"   # 科技脉冲顶锚点
BASELINES = [("sh000001", "上证综指"), ("sz399006", "创业板指")]


def ret_since(bars, date_str):
    """bars 升序; 返回自 date_str(含)以来收益, 以及该锚点收盘价。"""
    anchor = None
    for b in bars:
        if b["d"] >= date_str:
            anchor = b["c"]
            break
    if anchor is None or bars[-1]["c"] <= 0:
        return None, None
    return bars[-1]["c"] / anchor - 1, anchor


def ret_back(bars, n):
    if len(bars) <= n:
        return None
    return bars[-1]["c"] / bars[-1 - n]["c"] - 1


def compute_rotation():
    """返回 dict: baselines, sec_rank, tech_avg, nontech_avg, all_etf。
    供系统报告复用, 避免重复拉数。"""
    # 基准
    base_ret = {}
    for code, name in BASELINES:
        bars = fetch_long(code)
        r, _ = ret_since(bars, TECH_TOP)
        base_ret[name] = (r if r is not None else 0.0)
        print(f"{name} 自 {TECH_TOP} 收益: {(r*100 if r else 0):+.1f}%", file=sys.stderr)

    # 各 ETF 收益
    data = []   # (s1, s2, code, name, ret_since_top, r20, r60, anchor)
    for s1, s2, code, name in iter_etfs():
        bars = fetch_long(code)
        if not bars:
            data.append((s1, s2, code, name, None, None, None, None))
            continue
        rs, anchor = ret_since(bars, TECH_TOP)
        r20 = ret_back(bars, 20)
        r60 = ret_back(bars, 60)
        data.append((s1, s2, code, name, rs, r20, r60, anchor))
        time.sleep(0.10)

    # 聚合到一级板块
    sec = {}
    for s1, s2, code, name, rs, r20, r60, anchor in data:
        if rs is None:
            continue
        sec.setdefault(s1, []).append((s2, code, name, rs, r20, r60))

    sh_b = base_ret.get("上证综指", 0.0)
    cyb_b = base_ret.get("创业板指", 0.0)

    sec_rank = []
    for s1, rows in sec.items():
        avg = sum(r[3] for r in rows) / len(rows)
        rs_sh = avg - sh_b
        rs_cyb = avg - cyb_b
        r20 = sum((r[4] or 0) for r in rows) / len(rows)
        r60 = sum((r[5] or 0) for r in rows) / len(rows)
        sec_rank.append((s1, avg, rs_sh, rs_cyb, r20, r60))
    sec_rank.sort(key=lambda x: x[2], reverse=True)

    tech_rows = [(s2, code, name, rs, r20, r60) for (s1, s2, code, name, rs, r20, r60, a) in data
                 if s1 == "科技TMT" and rs is not None]
    nontech = [(s1, s2, code, name, rs, r20, r60) for (s1, s2, code, name, rs, r20, r60, a) in data
               if s1 != "科技TMT" and rs is not None]
    tech_avg = sum(r[3] for r in tech_rows) / len(tech_rows) if tech_rows else 0
    nontech_avg = sum(r[4] for r in nontech) / len(nontech) if nontech else 0

    all_etf = [(s1, s2, code, name, rs, r20, r60) for (s1, s2, code, name, rs, r20, r60, a) in data
               if rs is not None]
    all_etf.sort(key=lambda x: (x[4] - sh_b), reverse=True)
    return {"base_ret": base_ret, "sec_rank": sec_rank, "tech_avg": tech_avg,
            "nontech_avg": nontech_avg, "all_etf": all_etf, "sh_b": sh_b, "cyb_b": cyb_b}


def main():
    today = datetime.date.today().strftime("%Y%m%d")
    rot = compute_rotation()
    base_ret = rot["base_ret"]
    sec_rank = rot["sec_rank"]
    tech_avg = rot["tech_avg"]
    nontech_avg = rot["nontech_avg"]
    all_etf = rot["all_etf"]
    sh_b = rot["sh_b"]
    cyb_b = rot["cyb_b"]

    def pct(x):
        return f"{x*100:+.1f}%" if isinstance(x, (int, float)) else "—"

    L = []
    L.append(f"# 板块资金轮动 · 自科技顶({TECH_TOP})至今（{today}）\n")
    L.append("> **核心问题**：科技退潮后，资金是真流出市场，还是换板块承接？")
    L.append("> **方法**：以科技脉冲顶 2026-06-30 为锚，算各板块相对强弱 RS = 板块收益 − 宽基基准。")
    L.append("> **基准**：上证综指自锚点 " + pct(sh_b) + " ／ 创业板指 " + pct(cyb_b) +
             "（创业板更代表科技，其跌幅即科技退潮的镜像）。\n")

    L.append("## 一、一级板块轮动全景（按 RS 排序）\n")
    L.append("RS = 板块代表ETF均值收益 − 上证基准。正值=跑赢大盘=轮动承接；负值=跑输=退潮/流出。\n")
    L.append("| 一级板块 | 自顶收益 | RS(对上证) | RS(对创业板) | 近20日 | 近60日 | 轮动判定 |")
    L.append("|---|---|---|---|---|---|---|")
    for s1, avg, rs_sh, rs_cyb, r20, r60 in sec_rank:
        if rs_sh > 0.05:
            tag = "轮动承接▲"
        elif rs_sh > -0.03:
            tag = "抗跌/避险"
        else:
            tag = "退潮/流出▼"
        L.append(f"| {s1} | {pct(avg)} | {pct(rs_sh)} | {pct(rs_cyb)} | {pct(r20)} | {pct(r60)} | {tag} |")

    L.append("\n## 二、科技线 vs 其余：钱去哪了？\n")
    L.append(f"- **科技TMT 自顶均值：{pct(tech_avg)}**（硬件已腰斩，应用/消费电子滞后回撤）")
    L.append(f"- **非科技 自顶均值：{pct(nontech_avg)}**  vs 上证基准 {pct(sh_b)}")
    L.append(f"- **结论性读数**：非科技板块自科技顶以来 **{'跑赢' if nontech_avg > sh_b else '跑输'}** 上证基准 "
             f"**{pct(nontech_avg - sh_b)}** → ")
    if nontech_avg - sh_b > 0.02:
        L.append("  **资金明显换板块承接**（不是简单流出市场），承接方向见下方 Top 承接板块。")
    elif nontech_avg - sh_b > -0.02:
        L.append("  资金大体随大盘横盘，未明显换板块，也未大规模流出，处于观望/再平衡。")
    else:
        L.append("  非科技也同步走弱，提示存在整体性风险偏好下降（真流出倾向）。")

    L.append("\n## 三、Top 承接板块（RS 最强，轮入方向）\n")
    L.append("| 板块 | ETF | 自顶收益 | RS(对上证) | 近20日 | 近60日 |")
    L.append("|---|---|---|---|---|---|")
    for s1, s2, code, name, rs, r20, r60 in all_etf[:12]:
        L.append(f"| {s1}/{s2} | {name}({code}) | {pct(rs)} | {pct(rs - sh_b)} | {pct(r20)} | {pct(r60)} |")

    L.append("\n## 四、重灾区（RS 最弱，退潮/流出）\n")
    L.append("| 板块 | ETF | 自顶收益 | RS(对上证) |")
    L.append("|---|---|---|---|")
    for s1, s2, code, name, rs, r20, r60 in all_etf[-10:]:
        L.append(f"| {s1}/{s2} | {name}({code}) | {pct(rs)} | {pct(rs - sh_b)} |")

    L.append("\n## 五、诚实声明\n")
    L.append("- RS(相对强弱) 是「换板块」的稳健代理；**绝对流入(ETF份额净申购)** 仍需日频累积东财规模快照，")
    L.append("  本模块未做(需要历史序列)。结论「换板块 vs 真流出」基于相对表现，逻辑成立但非资金流水级确认。")
    L.append("- 创业板指(sz399006)自锚点若大跌，即科技退潮的镜像；其与上证背离越大，越说明是「结构性轮动」而非「全面流出」。")
    L.append("- 近20日 vs 自顶收益可区分「已轮入涨完」与「正在轮入」：若自顶强但近20日转弱，提示承接已进入后半段。")

    out = os.path.join(OUT_DIR, f"{today}_板块资金轮动.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n已写出: {out}", file=sys.stderr)
    print("\n".join(L))


if __name__ == "__main__":
    main()
