"""实测「净增发率 vs 涨跌」——用 CMC 全历史 市值/价格 反推流通量。

核心
----
    流通量_t = market_cap_t / price_t
这条序列由供应商直接从链上/协议汇总，天然含「发行 + 解锁 − 销毁」，
所以得到的是**实测净增发**，不含任何排放计划推测。

关键恒等式
----------
    价格 = 市值 / 流通量   →   价格涨幅 = 市值涨幅 − 净增发
因此把「净增发」与「价格涨幅」放在一起看，可以直接分离两件事：
    · 净增发高 → 即使市值不变，价格也必然被稀释掉（机械效应）
    · 若高增发组连「市值涨幅」都是负的 → 不只是稀释，需求端也在跑

口径纪律
--------
· 同一窗口、同一数据源算净增发与涨幅，避免跨源口径混用。
· 供应商会「重分类」流通量（把已解锁的国库/空投一次性计入流通），
  造成虚假的暴增/暴减。用「最大单周跳变」识别并单独标注。
· 本池按「买旧不买新 + 熊市幸存」筛选，存在幸存者偏差，结论不外推全市场。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HIST = ROOT / "markets" / "crypto" / "data" / "cmc_history"
CG_SNAP = ROOT / "markets" / "crypto" / "out" / "cg_supply_2026-09-12.json"

WINDOWS = [("近1年", 365), ("近2年", 730), ("近3年", 1095)]
# 上市年份分界：<=2020 视为「老币」，>2020 为「新币」
VINTAGE_CUT = 2020
ARTIFACT_JUMP = 0.15      # 单周流通量跳变 >15% 记为疑似重分类


def load(sym: str) -> pd.DataFrame | None:
    f = HIST / f"{sym}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    rows = [(int(k), v[0], v[2]) for k, v in d["points"].items()]
    s = pd.DataFrame(rows, columns=["t", "px", "mc"]).sort_values("t")
    s["date"] = pd.to_datetime(s["t"], unit="s", utc=True).dt.tz_localize(None)
    s = s[s["px"] > 0].copy()
    s["supply"] = s["mc"] / s["px"]
    return s.set_index("date")[["px", "mc", "supply"]]


def window_metrics(s: pd.DataFrame, days: int) -> dict | None:
    end = s.index[-1]
    tgt = end - pd.Timedelta(days=days)
    if s.index[0] > tgt:
        return None
    i0 = int(s.index.searchsorted(tgt))
    i0 = max(0, min(i0, len(s) - 2))
    a, b = s.iloc[i0], s.iloc[-1]
    span = (s.index[-1] - s.index[i0]).days
    if span < days * 0.75:
        return None
    yrs = span / 365.25
    g_sup = (b["supply"] / a["supply"]) ** (1 / yrs) - 1
    g_px = (b["px"] / a["px"]) ** (1 / yrs) - 1
    g_mc = (b["mc"] / a["mc"]) ** (1 / yrs) - 1
    sub = s.iloc[i0:]
    chg = sub["supply"].pct_change().dropna()
    jump = float(chg.abs().max()) if len(chg) else np.nan
    # 阶跃事件识别：协议发行/解锁是平滑的（周变化通常 <1%）；
    # 供应商「重分类」或一次性销毁/换币会表现为少数几个大台阶。
    n_big = int((chg.abs() > 0.04).sum())
    step = bool(np.isfinite(jump) and jump > 0.05 and n_big >= 2)
    return dict(yrs=yrs, span=span, g_sup=g_sup, g_px=g_px, g_mc=g_mc,
                sup0=a["supply"], sup1=b["supply"], px0=a["px"], px1=b["px"],
                max_jump=jump, n_big_jumps=n_big, step_event=step)


def spearman(x, y) -> float:
    """自实现 Spearman（venv 无 scipy）。"""
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) < 4:
        return np.nan
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    return float(np.corrcoef(rx, ry)[0, 1])


def main() -> None:
    syms = sorted(p.stem for p in HIST.glob("*.json"))
    recs = []
    for sym in syms:
        s = load(sym)
        if s is None:
            continue
        vintage = s.index[0].year
        for tag, days in WINDOWS:
            m = window_metrics(s, days)
            if m:
                recs.append(dict(coin=sym, window=tag, days=days, vintage=vintage, **m))
    df = pd.DataFrame(recs)

    print("=" * 104)
    print("A. 逐币逐窗口：实测年化净增发 vs 年化价格涨幅 vs 年化市值涨幅")
    print("=" * 104)
    for tag, _ in WINDOWS:
        g = df[df["window"] == tag].sort_values("g_sup", ascending=False)
        if g.empty:
            continue
        print(f"\n-- {tag}  (n={len(g)})")
        print(f"  {'币':7s}{'年化净增发':>11s}{'年化价格':>10s}{'年化市值':>10s}"
              f"{'最大单周跳变':>13s}{'大台阶数':>9s}   上市年  标注")
        for r in g.itertuples():
            flag = " ⚠️阶跃事件(重分类/一次性销毁)" if r.step_event else ""
            print(f"  {r.coin:7s}{r.g_sup * 100:10.2f}%{r.g_px * 100:9.1f}%{r.g_mc * 100:9.1f}%"
                  f"{r.max_jump * 100:12.1f}%{r.n_big_jumps:9d}   {r.vintage:>6d}{flag}")

    print()
    print("=" * 104)
    print("B. 横截面相关（净增发 与 涨幅）")
    print("=" * 104)
    print(f"  {'窗口':8s}{'n':>4s}{'Spearman(增发,价格)':>22s}{'Pearson':>10s}"
          f"{'Spearman(增发,市值)':>22s}")
    for tag, _ in WINDOWS:
        g = df[df["window"] == tag]
        sp_p = spearman(g["g_sup"], g["g_px"])
        pe_p = float(np.corrcoef(g["g_sup"], g["g_px"])[0, 1])
        sp_m = spearman(g["g_sup"], g["g_mc"])
        print(f"  {tag:8s}{len(g):4d}{sp_p:22.3f}{pe_p:10.3f}{sp_m:22.3f}")

    print()
    print("=" * 104)
    print("C. 按净增发率分组（检验 5% / 10% 两条线）")
    print("=" * 104)
    for tag, _ in WINDOWS:
        g = df[df["window"] == tag]
        print(f"\n-- {tag}")
        bins = [(-np.inf, 0.05, "<5%"), (0.05, 0.10, "5-10%"), (0.10, np.inf, ">10%")]
        print(f"  {'档':8s}{'币数':>5s}{'价格中位':>10s}{'市值中位':>10s}{'增发中位':>10s}   成员")
        for lo, hi, lab in bins:
            m = g[(g["g_sup"] >= lo) & (g["g_sup"] < hi)]
            if m.empty:
                print(f"  {lab:8s}{0:5d}{'—':>10s}")
                continue
            mem = " ".join(f"{r.coin}({r.g_px * 100:+.0f}%)"
                           for r in m.sort_values("g_px", ascending=False).itertuples())
            print(f"  {lab:8s}{len(m):5d}{m['g_px'].median() * 100:9.1f}%"
                  f"{m['g_mc'].median() * 100:9.1f}%{m['g_sup'].median() * 100:9.1f}%   {mem}")

    print()
    print("=" * 104)
    print("D. 阈值敏感性：分界线放 3/5/7/10/15%，低增发组 vs 高增发组的价格涨幅中位差")
    print("=" * 104)
    print(f"  {'窗口':8s}" + "".join(f"{f'{c}%':>13s}" for c in (3, 5, 7, 10, 15)))
    for tag, _ in WINDOWS:
        g = df[df["window"] == tag]
        line = f"  {tag:8s}"
        for c in (0.03, 0.05, 0.07, 0.10, 0.15):
            lo = g[g["g_sup"] < c]["g_px"]
            hi = g[g["g_sup"] >= c]["g_px"]
            line += (f"{((lo.median() - hi.median()) * 100):8.1f}pp"
                     f"({len(lo)}/{len(hi)})") if len(lo) and len(hi) else f"{'—':>13s}"
        print(line)
    print("  读法：数值 =（低增发组价格中位 − 高增发组价格中位），括号内为 (低增发组币数/高增发组币数)。")
    print("  数值越大说明该分界线越能区分；若随分界线上移而单调变大，说明真正的线比 3~5% 更高。")

    print()
    print("=" * 104)
    print("E. 分层：老币(<=2020 上市) vs 新币(>2020 上市)")
    print("=" * 104)
    for tag, _ in WINDOWS:
        g = df[df["window"] == tag]
        print(f"\n-- {tag}")
        for lab, m in (("老币 <=2020", g[g["vintage"] <= VINTAGE_CUT]),
                       ("新币 >2020", g[g["vintage"] > VINTAGE_CUT])):
            print(f"  {lab:12s} n={len(m):2d}  价格中位 {m['g_px'].median() * 100:+7.1f}%  "
                  f"增发中位 {m['g_sup'].median() * 100:+7.2f}%  "
                  f"Spearman(增发,价格) = {spearman(m['g_sup'], m['g_px']):+.3f}")

    print()
    print("=" * 104)
    print("F. 稳健性：剔除「阶跃事件」标的后重算（阶跃=重分类或一次性销毁，非持续增发）")
    print("=" * 104)
    for tag, _ in WINDOWS:
        g = df[df["window"] == tag]
        g2 = g[~g["step_event"]]
        drop = sorted(g[g["step_event"]]["coin"].tolist())
        print(f"  {tag:8s} 全部 n={len(g):2d} Spearman={spearman(g['g_sup'], g['g_px']):+.3f}"
              f"  |  剔除后 n={len(g2):2d} Spearman={spearman(g2['g_sup'], g2['g_px']):+.3f}"
              f"   剔除: {drop if drop else '—'}")

    print()
    print("=" * 104)
    print("G. 增发趋势：3年 → 2年 → 1年 的年化净增发（看是「收敛」还是「顽固」）")
    print("=" * 104)
    piv = df.pivot_table(index="coin", columns="window", values="g_sup", aggfunc="first")
    piv = piv.reindex(columns=["近3年", "近2年", "近1年"])      # 时间正序：老→新
    order = piv["近1年"].sort_values(ascending=False).index
    print(f"  {'币':7s}{'3年年化':>10s}{'2年年化':>10s}{'1年年化':>10s}   走势")
    for c in order:
        r = piv.loc[c]
        vals = [r.get(w) for w in ("近3年", "近2年", "近1年")]
        seq = [v for v in vals if pd.notna(v)]
        trend = "—"
        if len(seq) >= 2:
            if seq[-1] < seq[0] - 0.02:
                trend = "↓ 收敛"
            elif seq[-1] > seq[0] + 0.02:
                trend = "↑ 加速"
            else:
                trend = "→ 顽固"
        cells = "".join(f"{v * 100:9.2f}%" if pd.notna(v) else f"{'—':>10s}" for v in vals)
        print(f"  {c:7s}{cells}   {trend}")
    print("  近1年缺失者为上市不足 1 年；「收敛」= 增发率逐年下降，「顽固」= 一直维持同档。")

    print()
    print("=" * 104)
    print("H. 回归：价格涨幅 = a + b·净增发（b 是「每多 1pp 增发，价格少涨多少 pp」）")
    print("=" * 104)
    for tag, _ in WINDOWS:
        g = df[df["window"] == tag]
        x = g["g_sup"].to_numpy(float)
        y = g["g_px"].to_numpy(float)
        m = np.isfinite(x) & np.isfinite(y)
        b, a = np.polyfit(x[m], y[m], 1)
        resid = y[m] - (a + b * x[m])
        r2 = 1 - resid.var() / y[m].var()
        print(f"  {tag:8s} b = {b:+.3f}   a = {a * 100:+.1f}%   R² = {r2:.3f}   "
              f"(b≈-1 表示纯稀释/市值不变；b<-1 表示高增发还额外杀市值)")
    print("  注：b 的量级受极端值影响大（如 ZEC 近1年 +2400%），仅作方向参考。")

    print()
    print("=" * 104)
    print("I. 与 CoinGecko(近1年, 日频) 的口径对照 —— 验证实测值稳健")
    print("=" * 104)
    g1 = df[df["window"] == "近1年"]
    SUP = ROOT / "markets" / "crypto" / "data" / "supply_history"
    ref = json.loads(CG_SNAP.read_text(encoding="utf-8")) if CG_SNAP.exists() else {}
    print(f"  {'币':7s}{'CMC增发(1y)':>13s}{'CG增发(1y)':>13s}{'差':>9s}   若两源都大 → 真实; 若背离 → 供应商重分类")
    for r in g1.sort_values("g_sup", ascending=False).itertuples():
        f = SUP / f"{r.coin}.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        mc0, px0 = d["market_caps"][0][1], d["prices"][0][1]
        mc1, px1 = d["market_caps"][-1][1], d["prices"][-1][1]
        cg = (mc1 / px1) / (mc0 / px0) - 1
        print(f"  {r.coin:7s}{r.g_sup * 100:12.2f}%{cg * 100:12.2f}%"
              f"{(r.g_sup - cg) * 100:8.1f}pp")

    out = ROOT / "markets" / "crypto" / "out" / "issuance_measured.json"
    out.parent.mkdir(exist_ok=True)
    df.to_json(out, orient="records", indent=1, force_ascii=False)
    print(f"\n明细已存 {out.relative_to(ROOT)}  ({len(df)} 行)")


if __name__ == "__main__":
    main()
