# -*- coding: utf-8 -*-
"""issuance_vs_return.py —— 币池「净增发率」与「涨跌」关系的检验

用户假设: 净增发 <5%/y 的代币更容易上涨; >10%/y 的基本很难上涨。

数据口径
--------
价格: **纯本地** data/weekly_adjclose_crypto50_10y.csv (周K, 27币, 2014-09-19~2026-09-04)
      —— 不调用任何外部接口。
增发: 由各币**协议规则**(减半/尾排/销毁/固定上限)推导的净供给年增速, 不是抓来的行情。
      每条都标注 basis(依据) 与 conf(置信度), 见 ISSUANCE 表。

两个口径必须分开
----------------
  net_avg  : 该币**持有期平均**净增发率(%, 年化) —— 持有者实际承受的稀释
  net_now  : 当前净增发率(%, 年化)
涨跌用美元价格 CAGR(本地面板已是后复权/调整价)。

"稀释门槛"含义
--------------
  市值持平所需的年涨幅 = 净增发率。故 实际CAGR - 净增发率 = 需求增长(真实价值增长)。
  净增发 10%/y 的币, 价格必须每年涨 >10% 才能不掉市值。

用法: python markets/crypto/issuance_vs_return.py
"""
from __future__ import annotations

import json
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
OUT_JSON = os.path.join(HERE, "out", "issuance_vs_return.json")

# ---------------------------------------------------------------------------
# 净增发率表 (%/年)。basis: 依据; conf: 置信度 高/中/低
# net_avg = 该币在面板可得窗口内的平均净增发; net_now = 当前
# ---------------------------------------------------------------------------
ISSUANCE = {
    # coin : (net_avg, net_now, 硬顶, 机制与依据, conf)
    "BTC":   (3.6,  0.83, "21M",   "减半: 2016-07(12.5)→2020-05(6.25)→2024-04(3.125), 450枚/日", "高"),
    "ETH":   (2.8,  0.40, "无",    "2022-09 转 PoS 前 PoW 净~4.3%/y, 之后 PoS 发行~0.5%/y 减 EIP-1559+blob 销毁(2024后销毁转弱→转正)", "中"),
    "OKB":   (0.0, -0.5,  "21M",   "2025-08 一次性销毁 6526万枚(93%), 硬顶锁 21M, 此后仅季度回购销毁", "中"),
    "AAVE":  (1.5,  1.0,  "16M",   "上限 16M; Safety Module 奖励发行, 部分由回购抵消", "中低"),
    "ADA":   (4.0,  1.9,  "45B",   "reserve 递减释放(monetary expansion): 2021~5.5%→2025~2.2%→2026~1.9%; 无销毁", "高"),
    "APT":   (25.0, 12.0, "无",    "高通胀 + 归属解锁: 流通量 2022-10 起自 ~1.3亿 增至 7亿+, 年增速远超总供给增速", "中"),
    "AVAX":  (2.0,  1.6,  "720M",  "上限 720M; 质押奖励释放 ~2%/y, C-Chain 费用销毁抵消少量", "中"),
    "DOT":   (9.0,  7.5,  "无",    "原 10%/y 通胀(全额给质押者), 2024-25 提案降档; 国库有部分销毁", "高"),
    "FIL":   (6.0,  3.2,  "1.96B", "基线铸币随算力衰减, pledge 抵押有销毁; 通胀自 2021 的 ~8% 降至 ~3%", "中"),
    "LINK":  (6.0,  5.0,  "1B",    "总量 1B; 节点/团队奖励逐步释放, 流通自 2021 ~4.7亿 增至 ~7亿", "中低"),
    "POL":   (3.0,  1.8,  "10B",   "MATIC→POL 1:1 迁移; POL 引入 2%/y 验证者发行(部分销毁)", "中"),
    "RENDER":(2.0,  0.5,  "644M",  "渲染奖励排放已于 2023 结束; 1% 费用销毁 → 近似固定供给", "中低"),
    "SOL":   (5.5,  4.0,  "无",    "通胀 8% 起每年递减 15% 至终值 1.5%(2026 ~4.0%); 50% 手续费销毁", "高"),
    "GRAM":  (1.5,  0.6,  "无",    "TON 改名; 年通胀 ~0.6%; ⚠️ 1.08B 冻结盘 2027-02 解锁为硬供给日历", "中"),
    "TRX":   (0.3, -0.3,  "无",    "SR 出块奖励发行 ~0.2%/y, 网络费销毁超过发行 → 净轻微通缩", "中"),
    "UNI":   (2.0,  0.0,  "1B",    "4%/y 治理通胀 2024-09 四周年到期终止; 2025-26 UNIfication 激活协议费+销毁", "中低"),
    "ZEC":   (3.0,  1.0,  "21M",   "减半: 2020-11(6.25)→2024-11(3.125), 现 164,250枚/年", "高"),
    "BNB":   (-3.9, -2.0, "减至100M","季度 Auto-Burn(依 BNB 链用量), 总供给自 200M 降至 ~139M → 净通缩", "中高"),
    "XLM":   (0.0,  0.0,  "50B",   "2019-11 销毁 550亿 + 取消 1% 通胀 → 供给固定", "高"),
    "LTC":   (0.9,  0.43, "84M",   "减半 2023-08(12.5→6.25), 现 328,500枚/年", "高"),
    "XRP":   (0.0,  0.0,  "100B",  "预挖 100B, 托管每月释放但回流; 无新增发行, 仅有微量销毁", "高"),
    "GLM":   (0.0,  0.0,  "1B",    "公平发行 100% 流通, 无通胀(同时无销毁/无质押 → 无价值捕获)", "高"),
    "BCH":   (2.0,  0.83, "21M",   "减半 2024-04(6.25→3.125), 与 BTC 同规则", "高"),
    "RAY":   (10.0, 3.0,  "555M",  "早期农场排放极高(2021-22 ~30%/y), 之后递减; 2024 起有回购。⚠️ 估计误差大", "低"),
    "PENDLE":(8.0,  3.0,  "258M",  "vePENDLE 排放逐年递减; 早期高排放", "低"),
    "ETHFI": (15.0, 10.0, "1B",    "质押/激励排放 + 大额归属解锁, 流通增速高", "低"),
    "HYPE":  (-1.5, -2.5, "1B",    "99% 协议费用用于回购销毁 → 净通缩; 援助基金持续吸筹", "中"),
}

WINDOWS = [
    ("全历史(各币自身)", None),
    ("近5.7年(2021-01-01起)", "2021-01-01"),
    ("本轮(2024-01-01起)", "2024-01-01"),
]


def _spearman(x: np.ndarray, y: np.ndarray):
    """不依赖 scipy: 秩变换后取 Pearson, 并用 t 近似给 p 值。"""
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    rho = float(np.corrcoef(rx, ry)[0, 1])
    n = len(x)
    if n < 4 or abs(rho) >= 1:
        return rho, np.nan
    t = rho * np.sqrt((n - 2) / (1 - rho ** 2))
    # 双尾 p: 用正态近似(t 分布粗替代, n>=20 时误差可忽略)
    from math import erfc, sqrt
    p = erfc(abs(t) / sqrt(2))
    return rho, float(p)


def load_panel() -> pd.DataFrame:
    px = pd.read_csv(PANEL, index_col=0, parse_dates=True).sort_index()
    return px


def stats_for(s: pd.Series) -> dict:
    """单币价格统计。s 已 dropna。"""
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    if yrs <= 0.2 or len(s) < 8:
        return {}
    mult = float(s.iloc[-1] / s.iloc[0])
    cagr = mult ** (1 / yrs) - 1
    dd = (s / s.cummax() - 1).min()
    # 日历年收益(几何年化更能反映"能不能涨")
    yr = s.resample("YE").last()
    yr = pd.concat([pd.Series([s.iloc[0]], index=[s.index[0]]), yr]).sort_index()
    yr = (yr / yr.shift(1) - 1).dropna()
    return dict(
        yrs=round(yrs, 2), mult=round(mult, 3), cagr=round(cagr * 100, 1),
        mdd=round(float(dd) * 100, 1),
        pos_yrs=int((yr > 0).sum()), tot_yrs=int(len(yr)),
        pos_rate=round(float((yr > 0).mean()) * 100, 0),
        med_yr=round(float(np.median(yr)) * 100, 1) if len(yr) else np.nan,
    )


def build(px: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in px.columns:
        if c not in ISSUANCE:
            print(f"  ⚠️ {c} 无增发表条目, 跳过")
            continue
        na, nn, cap, mech, conf = ISSUANCE[c]
        r = dict(coin=c, net_avg=na, net_now=nn, cap=cap, mech=mech, conf=conf)
        for tag, start in WINDOWS:
            s = px[c].dropna()
            if start:
                s = s.loc[start:]
            st = stats_for(s)
            if not st:
                continue
            for k, v in st.items():
                r[f"{tag}|{k}"] = v
        rows.append(r)
    return pd.DataFrame(rows)


def bucket(x: float) -> str:
    if x < 5:
        return "A. <5%"
    if x <= 10:
        return "B. 5-10%"
    return "C. >10%"


def report(df: pd.DataFrame) -> None:
    W = WINDOWS[0][0]
    df = df.copy()
    df["bin_avg"] = df["net_avg"].map(bucket)
    df["bin_now"] = df["net_now"].map(bucket)

    print("=" * 118)
    print("币池 27 枚: 净增发率 vs 涨跌   (价格=本地面板; 增发=协议规则推导)")
    print("=" * 118)
    cols = ["coin", "net_avg", "net_now", "cap", "conf",
            f"{W}|cagr", f"{W}|mult", f"{W}|mdd", f"{W}|pos_rate"]
    cols = [c for c in cols if c in df.columns]
    d = df.sort_values("net_avg")
    print(d[cols].to_string(index=False,
                            header=["币", "持有期均增发%", "当前增发%", "硬顶", "置信",
                                    "CAGR%", "倍数", "MDD%", "上涨年占比%"]))

    # ---- 分组统计(用持有期平均增发) ----
    print()
    for win_tag, _ in WINDOWS:
        cagr_c = f"{win_tag}|cagr"
        pos_c = f"{win_tag}|pos_rate"
        if cagr_c not in df.columns:
            continue
        sub = df.dropna(subset=[cagr_c])
        if len(sub) < 5:
            continue
        print("-" * 118)
        print(f"【{win_tag}】样本 {len(sub)} 币   按**持有期平均净增发**分组")
        print(f"  {'分组':10s}{'币数':>4s}{'CAGR中位数':>12s}{'CAGR均值':>10s}"
              f"{'正收益占比':>11s}{'上涨年占比中位':>14s}   成员")
        for b in ["A. <5%", "B. 5-10%", "C. >10%"]:
            g = sub[sub["bin_avg"] == b]
            if not len(g):
                print(f"  {b:10s}{0:>4d}      ——")
                continue
            pr = (g[cagr_c] > 0).mean() * 100
            prs = g[pos_c].median() if pos_c in g.columns else np.nan
            mem = " ".join(f"{cn}({v:+.0f}%)"
                           for cn, v in zip(g["coin"], g[cagr_c]))
            print(f"  {b:10s}{len(g):>4d}{g[cagr_c].median():>11.1f}%{g[cagr_c].mean():>9.1f}%"
                  f"{pr:>10.0f}%{prs:>13.0f}%   {mem}")
        # 相关系数
        x = sub["net_avg"].to_numpy(dtype=float)
        y = sub[cagr_c].to_numpy(dtype=float)
        pear = np.corrcoef(x, y)[0, 1]
        rho, pval = _spearman(x, y)
        print(f"  → Pearson(增发, CAGR) = {pear:+.3f}   "
              f"Spearman = {rho:+.3f} (p≈{pval:.3f})")
        # 稀释门槛: CAGR - 增发 = 需求增长
        sub2 = sub.assign(demand=sub[cagr_c] - sub["net_avg"])
        print(f"  → 剔除稀释后「需求增长」中位数: "
              f"{sub2.groupby('bin_avg')['demand'].median().round(1).to_dict()}")
        print()

    # ---- 用当前增发分组(对照) ----
    W2 = WINDOWS[1][0]
    c2 = f"{W2}|cagr"
    print("=" * 118)
    print(f"【对照】改用**当前**净增发分组, 收益窗口 = {W2}")
    print("=" * 118)
    sub = df.dropna(subset=[c2])
    for b in ["A. <5%", "B. 5-10%", "C. >10%"]:
        g = sub[sub["bin_now"] == b]
        if not len(g):
            print(f"  {b:10s} 0 币")
            continue
        mem = " ".join(f"{cn}({v:+.0f}%)" for cn, v in zip(g["coin"], g[c2]))
        print(f"  {b:10s}{len(g):>3d}币  中位 {g[c2].median():+7.1f}%   "
              f"正收益 {(g[c2] > 0).mean() * 100:3.0f}%   {mem}")
    x = sub["net_now"].to_numpy(dtype=float)
    y = sub[c2].to_numpy(dtype=float)
    rho, pval = _spearman(x, y)
    print(f"  → Pearson(当前增发, CAGR) = {np.corrcoef(x, y)[0, 1]:+.3f}   "
          f"Spearman = {rho:+.3f} (p≈{pval:.3f})")

    # ---- 共线性检验: 上市年份是否才是真因 ----
    print()
    print("=" * 118)
    print("共线性检验: 增发率是否只是「上市新老」的代理变量?")
    print("=" * 118)
    px = load_panel()
    first_yr = {c: px[c].dropna().index[0].year for c in px.columns}
    s2 = df.assign(vintage=[first_yr.get(c) for c in df["coin"]]).dropna(subset=[c2])
    r_v = np.corrcoef(s2["vintage"].astype(float), s2[c2].astype(float))[0, 1]
    r_iv = np.corrcoef(s2["net_avg"], s2["vintage"].astype(float))[0, 1]
    print(f"  Corr(上市年份, CAGR)          = {r_v:+.3f}")
    print(f"  Corr(净增发, 上市年份)         = {r_iv:+.3f}   "
          f"(共线性{'强, 需控制' if abs(r_iv) > 0.6 else '不强'})")
    # 控制上市年份: 在 2020 年及以前上市的"老币"子样本里再看增发-CAGR
    old = s2[s2["vintage"] <= 2020]
    new = s2[s2["vintage"] > 2020]
    for tag, g in (("老币(≤2020上市)", old), ("新币(>2020上市)", new)):
        if len(g) >= 5:
            rho, p = _spearman(g["net_avg"].to_numpy(float), g[c2].to_numpy(float))
            print(f"  {tag:16s} n={len(g):2d}  Spearman(增发,CAGR) = {rho:+.3f} (p≈{p:.3f})  "
                  f"中位增发 {g['net_avg'].median():.1f}%  中位CAGR {g[c2].median():+.1f}%")
    print()
    print("=" * 118)
    print("阈值敏感性: 若把分界线移到 3/5/7/10/15%, 「高增发组」中位 CAGR 如何变")
    print("=" * 118)
    print(f"  {'阈值':>6s}{'≥阈值币数':>10s}{'该组CAGR中位':>14s}{'<阈值CAGR中位':>15s}{'差值':>9s}")
    for th in (3, 5, 7, 10, 15):
        hi = sub[sub["net_avg"] >= th]
        lo = sub[sub["net_avg"] < th]
        if not len(hi):
            print(f"  {th:>5d}%{0:>10d}          ——")
            continue
        print(f"  {th:>5d}%{len(hi):>10d}{hi[c2].median():>13.1f}%"
              f"{lo[c2].median():>14.1f}%{hi[c2].median() - lo[c2].median():>8.1f}pp")


def main():
    px = load_panel()
    print(f"本地面板: {px.shape[0]} 周 x {px.shape[1]} 币   "
          f"{px.index[0].date()} ~ {px.index[-1].date()}\n")
    df = build(px)
    report(df)
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(df.to_dict(orient="records"), f, ensure_ascii=False, indent=1)
    print(f"\n表已存: {OUT_JSON}")


if __name__ == "__main__":
    main()
