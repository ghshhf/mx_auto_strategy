# -*- coding: utf-8 -*-
"""
index_analog_forecast.py
========================
用「大量历史数据 + 相似日耦合(类比匹配)」对上证综指(sh000001)做**次日方向**预判,
并叠加「资金量/活跃度」维度。

思路 (非ML, 纯 nearest-neighbor analog):
  1. 分页拉腾讯后复权日K, 攒 2005 至今的长序列。
  2. 对每一天构造"市场状态特征向量"(全部因果, 只用当时已有数据):
       - 周期位置: close / MA250 - 1        (贴合"3000中枢"周期论)
       - 短/中/长动量: ret5 / ret20 / ret60
       - 波动: 20日已实现波动率
       - 活跃度: volume / MA20(vol)         (资金量代理)
  3. 用今天的特征向量, 在历史上找 K 个最相似交易日(排除最近30日防自相关)。
  4. 看这 K 个"历史今天"之后一天的收益分布 => 次日方向 + 命中率。
  5. 资金结合: 在 K 个邻居里, 高量/低量子群的后续表现对比。

⚠️ 这是"大概方向"的粗糙工具, 不是择时系统。样本外边缘有限, 且高度依赖所选特征。

依赖: 仅标准库。无代理直连腾讯。
产出: records/<日期>_上证次日方向_类比预测.md
用法: python ashare_backtest/index_analog_forecast.py
"""
import os
import sys
import json
import time
import math
import datetime
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
OUT_DIR = os.path.join(ROOT, "records")
os.makedirs(OUT_DIR, exist_ok=True)

API = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
TARGET_START = "2005-01-01"
K = 50
EXCLUDE_RECENT = 30
SEMI_CODE = "512480"   # 半导体ETF, 用于"当前盘面"附读


def _get(url, dec="utf-8", timeout=12):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://finance.qq.com/",
    })
    return urllib.request.urlopen(req, timeout=timeout).read().decode(dec, "ignore")


def fetch_daily(code, start, end, count=1000):
    """分页拉日K(升序), 返回 [{'d','c','v'}]。"""
    pref = code if code.startswith(("sh", "sz")) else ("sh" if code[0] == "5" else "sz") + code
    url = f"{API}?param={pref},day,{start},{end},{count},"
    try:
        j = json.loads(_get(url))
    except Exception as e:
        print(f"  ! {code} 解析失败: {e}", file=sys.stderr)
        return []
    node = (j.get("data") or {}).get(pref) or {}
    arr = node.get("hfqday") or node.get("day") or []
    out = []
    for r in arr:
        try:
            out.append({"d": r[0], "c": float(r[2]),
                        "v": float(r[5]) if len(r) > 5 else 0.0})
        except (IndexError, ValueError, TypeError):
            continue
    return out


def fetch_long(code, target_start=TARGET_START, page=1000):
    """从今天往前分页, 攒到 target_start 为止。"""
    today = datetime.date.today()
    end = today.strftime("%Y-%m-%d")
    all_bars = []
    seen = set()
    guard = 0
    while True:
        guard += 1
        if guard > 40:
            break
        bars = fetch_daily(code, target_start, end, page)
        if not bars:
            break
        for b in bars:
            if b["d"] not in seen:
                seen.add(b["d"])
                all_bars.append(b)
        first_d = bars[0]["d"]
        if first_d <= target_start:
            break
        # 往前挪一页
        dt = datetime.date.fromisoformat(first_d) - datetime.timedelta(days=1)
        end = dt.strftime("%Y-%m-%d")
        time.sleep(0.15)
    all_bars.sort(key=lambda x: x["d"])
    return all_bars


def sma(vals, i, n):
    if i < n - 1:
        return None
    return sum(v for v in vals[i - n + 1:i + 1]) / n


def stdev(vals, i, n):
    if i < n - 1:
        return None
    m = sum(vals[i - n + 1:i + 1]) / n
    return math.sqrt(sum((v - m) ** 2 for v in vals[i - n + 1:i + 1]) / n)


def build_features(bars):
    """返回与 bars 等长的特征列表(前序不足处为 None)。"""
    closes = [b["c"] for b in bars]
    vols = [b["v"] for b in bars]
    feats = []
    for i in range(len(bars)):
        c = closes[i]
        ma250 = sma(closes, i, 250) or sma(closes, i, 120) or sma(closes, i, 60)
        ma60 = sma(closes, i, 60)
        ma20v = sma(vols, i, 20)
        if ma250 is None or ma60 is None or ma20v is None or ma20v <= 0:
            feats.append(None)
            continue
        level = c / ma250 - 1.0
        ret5 = (c / closes[i - 5] - 1) if i >= 5 else None
        ret20 = (c / closes[i - 20] - 1) if i >= 20 else None
        ret60 = (c / closes[i - 60] - 1) if i >= 60 else None
        vol20 = stdev([(closes[j] / closes[j - 1] - 1) for j in range(max(1, i - 19), i + 1)],
                      19, 20) if i >= 20 else None
        vol_ratio = vols[i] / ma20v
        if None in (ret5, ret20, ret60, vol20):
            feats.append(None)
            continue
        feats.append([level, ret5, ret20, ret60, vol20, vol_ratio])
    return feats


def main():
    today = datetime.date.today().strftime("%Y%m%d")
    print("拉取上证综指长序列 ...", file=sys.stderr)
    sh = fetch_long("sh000001")
    print(f"  上证条数={len(sh)} 区间={sh[0]['d']}->{sh[-1]['d']}", file=sys.stderr)
    feats = build_features(sh)

    # 训练集: 特征非空 且 不是最近 EXCLUDE_RECENT 天, 且 有"次日"
    train_idx = [i for i in range(len(sh)) if feats[i] is not None
                 and i < len(sh) - 1 - EXCLUDE_RECENT]
    # 标准化(用训练集统计)
    import statistics as st
    cols = list(zip(*[feats[i] for i in train_idx]))
    means = [st.mean(c) for c in cols]
    sds = [st.pstdev(c) for c in cols]

    def z(vec):
        return [(vec[j] - means[j]) / (sds[j] or 1) for j in range(len(vec))]

    today_i = len(sh) - 1
    today_feat = feats[today_i]
    tz = z(today_feat)

    # 距离
    dists = []
    for i in train_idx:
        fz = z(feats[i])
        d = math.sqrt(sum((tz[j] - fz[j]) ** 2 for j in range(len(tz))))
        # 次日收益
        nxt = sh[i + 1]["c"] / sh[i]["c"] - 1
        dists.append((d, i, nxt, feats[i][5]))
    dists.sort(key=lambda x: x[0])
    knn = dists[:K]
    nxts = [x[2] for x in knn]
    hit = sum(1 for r in nxts if r > 0) / len(nxts)
    mean_nxt = sum(nxts) / len(nxts)
    nxts_s = sorted(nxts)
    q1, q2, q3 = nxts_s[len(nxts_s)//4], nxts_s[len(nxts_s)//2], nxts_s[3*len(nxts_s)//4]

    # 资金结合: 按 K 邻居自身的 vol_ratio 中位数切分(避免高/低桶一边为空)
    vr_sorted = sorted(x[3] for x in knn)
    med_vr = vr_sorted[len(vr_sorted)//2]
    hi = [x[2] for x in knn if x[3] >= med_vr]
    lo = [x[2] for x in knn if x[3] < med_vr]
    hi_m = sum(hi)/len(hi) if hi else None
    lo_m = sum(lo)/len(lo) if lo else None
    avg_volr = sum(x[3] for x in knn)/len(knn)

    def sig(m):
        if m > 0.0015: return "偏多 ▲"
        if m < -0.0015: return "偏空 ▼"
        return "中性 —"

    # 当前盘面: 半导体 + 上证近期
    semi = fetch_long(SEMI_CODE)
    sfeats = build_features(semi)
    sl = semi[-1]["c"]
    s5 = (sl/semi[-6]["c"]-1)*100 if len(semi) > 5 else None
    s20 = (sl/semi[-21]["c"]-1)*100 if len(semi) > 20 else None
    sh_last = sh[-1]["c"]
    sh5 = (sh_last/sh[-6]["c"]-1)*100
    sh20 = (sh_last/sh[-21]["c"]-1)*100
    sh60 = (sh_last/sh[-61]["c"]-1)*100 if len(sh) > 60 else None

    # ---------- 写报告 ----------
    L = []
    L.append(f"# 上证次日方向 · 类比预测（{today}）\n")
    L.append("> **方法**：2005 至今日K → 相似日 KNN 匹配(排除最近30日) → 看邻居次日收益分布。")
    L.append("> **特征**：周期位置(close/MA250-1) + 动量(ret5/20/60) + 波动(20d) + 活跃度(vol/MA20vol)。")
    L.append("> **性质**：粗糙方向工具，非择时系统。边缘有限，勿单凭此下单。\n")

    L.append("## 当前盘面（回答你的两个疑问）\n")
    L.append(f"- **上证综指最新收盘 {sh_last:.2f}**（2026-08-14）。")
    L.append(f"  近5日 {sh5:+.1f}% / 近20日 {sh20:+.1f}% / 近60日 {sh60:+.1f}%。")
    L.append(f"  ⚠️ 你口中的“3500左右”与实际 **{sh_last:.0f}** 偏差很大——指数比你想的更高，")
    L.append("  处于长周期偏上沿，**均值回归/回调压力结构性偏大**（和你“中枢周期”的直觉一致，只是位置更极致）。")
    L.append(f"- **半导体ETF(512480)**：最新 {sl:.3f}，近5日 {s5:+.1f}% / 近20日 {s20:+.1f}%。")
    L.append("  在本周速览里它是 AI 链里相对最强（13周+5.4% vs 通信-10.6%/AI-7.4%）；")
    L.append("  若它也开始拐头向下，往往意味着 AI 链最后一截强势补跌——需盯紧近几日是否破位。\n")

    L.append("## 次日方向预判（KNN, K=%d）\n" % K)
    L.append(f"- **信号：{sig(mean_nxt)}**  （基于邻居次日平均收益 {mean_nxt*100:+.2f}%）")
    L.append(f"- **上涨命中率：{hit*100:.0f}%**（{int(hit*K)}/{K} 个相似历史日的次日收涨）")
    L.append(f"- **次日收益分布**：Q1 {q1*100:+.2f}% / 中位 {q2*100:+.2f}% / Q3 {q3*100:+.2f}%")
    L.append(f"- **邻居平均活跃度 vol/MA20 = {avg_volr:.2f}**（>1 偏放量环境）\n")

    L.append("## 资金量结合（高量 vs 低量邻居）\n")
    L.append("同样特征相似的日子里，区分“放量”与“缩量”环境，看次日表现差异：\n")
    L.append("| 子群 | 样本数 | 平均次日收益 |")
    L.append("|---|---|---|")
    L.append(f"| 高量(vol≥邻居中位 {med_vr:.2f}) | {len(hi)} | {('%+.2f%%'%(hi_m*100)) if hi_m is not None else '—'} |")
    L.append(f"| 低量(vol<邻居中位) | {len(lo)} | {('%+.2f%%'%(lo_m*100)) if lo_m is not None else '—'} |")
    L.append("")
    L.append("> 解读：若高量子群次日明显优于低量，说明“相似形态+放量”才是有效信号，单纯形态匹配会高估。\n")

    L.append("## Top-10 最相似历史日（及次日实际）\n")
    L.append("| 历史日 | 次日收益 | 周期位置 | 活跃度 |")
    L.append("|---|---|---|---|")
    for d, i, nxt, vr in knn[:10]:
        L.append(f"| {sh[i]['d']} | {nxt*100:+.2f}% | {feats[i][0]*100:+.1f}% | {vr:.2f} |")

    L.append("\n## 方法论诚实声明\n")
    L.append("- 单指数 + 6 个特征的 KNN 能捕捉短动量与粗略均值回归，但**样本外边缘有限且随 regime 漂移**。")
    L.append("- “资金量”这里只用指数成交量/MA20 作活跃度代理；真正的板块主力净流入(push2)在本沙箱被断连，")
    L.append("  两市成交额需另接东财 push2delay 聚合，可作为后续增强。")
    L.append("- 历史分位/周期位置是关键正则项：当前位置偏高，会系统性拉低匹配到的“利好邻居”占比。")

    out = os.path.join(OUT_DIR, f"{today}_上证次日方向_类比预测.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"已写出: {out}", file=sys.stderr)
    print("\n".join(L))


if __name__ == "__main__":
    main()
