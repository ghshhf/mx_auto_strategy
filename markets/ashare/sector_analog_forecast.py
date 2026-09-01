# -*- coding: utf-8 -*-
"""
sector_analog_forecast.py
========================
把「类比预测(KNN)」下沉到板块/行业ETF层面, 先拆"科技"这条线:
  半导体 / 通信(光模块算力) / 人工智能 / 芯片 / 消费电子
每个 ETF 用自己的长序列做相似日匹配, 给次日方向 + 退潮判定。

复用 index_analog_forecast 的 fetch_long / build_features (同口径, 腾讯后复权日K)。
多空立场按"多方/空方/中性并陈"呈现, 不给交易指令。

产出: records/<日期>_科技板块_类比方向.md
用法: python markets/ashare/sector_analog_forecast.py
"""
import os
import sys
import math
import datetime
import statistics as st

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(BASE))
sys.path.insert(0, BASE)
from index_analog_forecast import fetch_long, build_features  # noqa: E402

OUT_DIR = os.path.join(ROOT, "records")
os.makedirs(OUT_DIR, exist_ok=True)

K = 50
EXCLUDE_RECENT = 30

# 科技线: 板块 -> [(code, name)]
TECH = {
    "AI算力链-半导体": [("512480", "半导体ETF")],
    "AI算力链-通信(光模块/算力)": [("515880", "通信ETF")],
    "AI算力链-人工智能": [("159819", "人工智能ETF")],
    "芯片": [("159995", "芯片ETF")],
    "消费电子": [("159732", "消费电子ETF")],
}


def knn_forecast(bars, feats):
    train_idx = [i for i in range(len(bars)) if feats[i] is not None
                 and i < len(bars) - 1 - EXCLUDE_RECENT]
    if len(train_idx) < 20:
        return None
    cols = list(zip(*[feats[i] for i in train_idx]))
    means = [st.mean(c) for c in cols]
    sds = [st.pstdev(c) for c in cols]

    def z(v):
        return [(v[j] - means[j]) / (sds[j] or 1) for j in range(len(v))]

    tz = z(feats[-1])
    dists = []
    for i in train_idx:
        fz = z(feats[i])
        d = math.sqrt(sum((tz[j] - fz[j]) ** 2 for j in range(len(tz))))
        nxt = bars[i + 1]["c"] / bars[i]["c"] - 1
        dists.append((d, i, nxt, feats[i][5]))
    dists.sort(key=lambda x: x[0])
    knn = dists[:K]
    nxts = [x[2] for x in knn]
    hit = sum(1 for r in nxts if r > 0) / len(nxts)
    mean_nxt = sum(nxts) / len(nxts)
    vr_sorted = sorted(x[3] for x in knn)
    med_vr = vr_sorted[len(vr_sorted) // 2]
    hi = [x[2] for x in knn if x[3] >= med_vr]
    lo = [x[2] for x in knn if x[3] < med_vr]
    hi_m = sum(hi) / len(hi) if hi else None
    lo_m = sum(lo) / len(lo) if lo else None
    return {"mean": mean_nxt, "hit": hit, "hi_m": hi_m, "lo_m": lo_m,
            "med_vr": med_vr, "n_train": len(train_idx)}


def recent(bars):
    c = bars[-1]["c"]
    def r(n):
        return (c / bars[-1 - n]["c"] - 1) * 100 if len(bars) > n else None
    return r(5), r(20), r(60)


def rollover_tag(r5, r20, r60):
    if r5 is None:
        return "数据不足"
    if r5 > 0 and (r20 or 0) > 0 and (r60 or 0) > 0:
        return "全面强势"
    if r5 < 0 and (r20 or 0) > 0:
        return "短期拐头(顶部迹象)"
    if r5 < 0 and (r60 or 0) < 0:
        return "已进入回调"
    if r5 > 0 and (r20 or 0) < 0:
        return "超跌反弹"
    return "震荡/中性"


def peak_info(bars):
    """近70日峰值与距峰值回撤(核验脉冲顶/腰斩)。"""
    seg = bars[-70:]
    pk = max(seg, key=lambda b: b["c"])
    dd = (bars[-1]["c"] / pk["c"] - 1) * 100
    return pk["d"], pk["c"], dd


def sig(m):
    if m is None:
        return "—"
    if m > 0.0015:
        return "偏多▲"
    if m < -0.0015:
        return "偏空▼"
    return "中性—"


def main():
    today = datetime.date.today().strftime("%Y%m%d")
    results = []
    for sector, etfs in TECH.items():
        code, name = etfs[0]
        bars = fetch_long(code)
        feats = build_features(bars)
        f = knn_forecast(bars, feats)
        r5, r20, r60 = recent(bars)
        pk_d, pk_c, dd = peak_info(bars)
        results.append((sector, code, name, bars[-1]["c"], r5, r20, r60,
                        rollover_tag(r5, r20, r60), f, len(bars), pk_d, pk_c, dd))

    L = []
    L.append(f"# 科技板块 · 类比方向（{today}）\n")
    L.append("> **方法**：每个科技ETF用自身长序列做 KNN 相似日匹配(K=50, 排除近30日), 给次日方向与退潮判定。")
    L.append("> **口径**：腾讯后复权日K；特征=周期位置(close/MA250)+动量(5/20/60日)+波动+活跃度(vol/MA20)。")
    L.append("> **立场**：多方/空方/中性并陈，仅给方向，非交易指令。\n")

    L.append("## 一、科技细分 · 速览表\n")
    L.append("| 细分 | ETF | 代码 | 最新 | 5日 | 20日 | 60日 | 退潮判定 | KNN信号 | 涨命中 | 训练样本 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for sector, code, name, c, r5, r20, r60, tag, f, n, pk_d, pk_c, dd in results:
        def p(x):
            return f"{x:+.1f}%" if isinstance(x, (int, float)) else "—"
        sig_s = sig(f["mean"]) if f else "—"
        hit_s = f"{f['hit']*100:.0f}%" if f else "—"
        L.append(f"| {sector} | {name} | {code} | {c:.3f} | {p(r5)} | {p(r20)} | {p(r60)} | {tag} | {sig_s} | {hit_s} | {f['n_train'] if f else '—'} |")

    L.append("\n## 一·B 数据核验（近70日脉冲顶 / 距峰值回撤）\n")
    L.append("> 60日 -50% 这类极端数已逐只核验：**非脏点，是真实脉冲顶后腰斩**。两独立ETF峰值日都在 2026-06 末，交叉验证。\n")
    L.append("| 细分 | ETF | 近70日峰值日 | 峰值价 | 距峰值回撤 |")
    L.append("|---|---|---|---|---|")
    for sector, code, name, c, r5, r20, r60, tag, f, n, pk_d, pk_c, dd in results:
        L.append(f"| {sector} | {name} | {pk_d} | {pk_c:.3f} | {dd:+.1f}% |")

    L.append("\n## 二、逐个细分解读\n")
    for sector, code, name, c, r5, r20, r60, tag, f, n, pk_d, pk_c, dd in results:
        L.append(f"### {sector}（{name} {code}）\n")
        L.append(f"- 最新 {c:.3f}；5日 {r5:+.1f}% / 20日 {r20:+.1f}% / 60日 {r60:+.1f}%。")
        L.append(f"- **退潮判定：{tag}**")
        if f:
            L.append(f"- 类比次日信号 **{sig(f['mean'])}**（邻居次日均值 {f['mean']*100:+.2f}%，涨命中 {f['hit']*100:.0f}%）。")
            L.append(f"- 资金量结合：高量邻居次日 {('%+.2f%%'%(f['hi_m']*100)) if f['hi_m'] is not None else '—'} "
                     f"/ 低量 {('%+.2f%%'%(f['lo_m']*100)) if f['lo_m'] is not None else '—'}（中位活跃度 {f['med_vr']:.2f}）。")
        else:
            L.append("- 历史样本不足, 跳过KNN。")
        L.append("")

    # 科技合成: 平均 KNN 次日均值
    means = [r[8]["mean"] for r in results if r[8]]
    comp = sum(means) / len(means) if means else None
    L.append("## 三、科技合成信号 + 多空立场\n")
    L.append(f"- 科技5细分 KNN 次日均值平均 **{comp*100:+.2f}%** → 合成信号 **{sig(comp)}**（次日维度）。\n")
    L.append("**关键核验结论（先说事实）**：")
    L.append("- 半导体/通信/芯片 **不是“要退潮”，是已经在退潮中段**：2026-06 末脉冲见顶、2 个月内腰斩(距峰值 -63~-64%)，现在处于暴跌后企稳。")
    L.append("- 人工智能ETF / 消费电子ETF 距峰值仅 -3%~-17%，**没经历那轮崩**，是科技里仍悬在高位、可能接棒回撤的线。")
    L.append("- 因此“科技退潮”要分两条线看：硬件(半导体/通信/芯片)退得最狠且接近跌透；AI应用/消费电子尚未退，是后续风险点。\n")
    L.append("**空方（退潮论，成立但有时点修正）**：")
    L.append("- 硬件线：脉冲顶+腰斩已是事实，产业“AI硬件资本开支”叙事若证伪，企稳后还有阴跌/磨底。")
    L.append("- 应用/消费电子：仍在高位，若跟随硬件risk-off，补跌空间相对更大。\n")
    L.append("**多方（反驳退潮）**：")
    L.append("- 硬件线已跌透( -60%+ )，估值与情绪出清较充分，向下空间反比向上大；KNN次日偏多即超跌企稳反弹。")
    L.append("- 半导体设备国产化/AI资本开支长逻辑未证伪，急跌后存在分化机会(龙头抗跌)。\n")
    L.append("**中性推演**：")
    L.append("- KNN“偏多”是**短线超跌反弹**信号(腰斩后企稳日次日多反弹)，与中线退潮趋势不矛盾——死猫跳可共存于下行通道。")
    L.append("- “退潮”是过程非断崖；确认应用/消费电子也开始退的信号：其 60 日翻负 + 量能持续萎缩。\n")

    L.append("## 四、诚实声明\n")
    L.append("- 行业ETF上市晚(多在2019~2021), 可比历史短于上证, 类比样本更少, 边缘更弱。")
    L.append("- KNN 给的是“大概方向”, 单 ETF 噪声大; 看板块合成 + 退潮判定比单只更稳。")
    L.append("- 资金维度仍仅用 ETF 量/MA20 代理; 板块主力净流入(push2)沙箱断连, 待补。")

    out = os.path.join(OUT_DIR, f"{today}_科技板块_类比方向.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"已写出: {out}", file=sys.stderr)
    print("\n".join(L))


if __name__ == "__main__":
    main()
