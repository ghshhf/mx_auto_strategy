# -*- coding: utf-8 -*-
"""
ashare_pair_diag.py — A股配对的三个诊断口径（2026-09-14 新增）

段A  单位换算: 「筹码年化」 vs 「超额(累计)」不是同一单位
     —— 分层表同时给 年数 / 筹码年化 / 超额累计 / 超额折年化 / 兑现率。
段B  超额由谁决定: 强腿(价格倍数大的一侧)的筹码倍数
     —— 权重分布 + corr + 按 β_强腿 分桶（单调）。
段C  半导体 × 存储 受控对照（含相关矩阵 / 子行业互配 vs 跨行业 / 换对手单调性）

用法: python ashare_pair_diag.py
口径: 与 ashare_pair_all.py 完全一致（两股 50:50 · 4 周 · 10bp · 筹码死拿=1.000）
"""
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ashare_pair_all as A          # noqa: E402

SEP = "=" * 108
MIN_HIST = A.MIN_HIST
SEMI = {"兆易创新": "存储", "北方华创": "半导体设备",
        "中芯国际": "半导体制造", "韦尔股份": "半导体设计"}
PEERS = {"贵州茅台": "白酒", "招商银行": "银行", "阳光电源": "光伏",
         "比亚迪": "汽车", "恒瑞医药": "医药", "中兴通讯": "通信",
         "工业富联": "电子", "浪潮信息": "服务器"}
LAYERS = ["2005-01-07", "2010-01-08", "2015-01-09", "2018-01-05",
          "2020-01-03", "2020-10-09", "2022-07-08"]


def p(x, d=2):
    return f"{x * 100:.{d}f}%"


def col0(px, nm):
    for c in px.columns:
        if str(c).split("|")[0] == nm:
            return c
    return None


# ------------------------------------------------------------------ 段A
def section_a(px):
    print()
    print(SEP)
    print("段A · 单位换算: 『筹码年化』与『超额(累计)』不是同一单位")
    print(SEP)
    hdr = (f"  {'层':<12}{'年数':>7}{'池':>5}{'对数':>7}{'筹码年化':>10}"
           f"{'累计筹码':>10}{'超额累计':>10}{'超额折年':>10}{'兑现率':>8}"
           f"{'净值CAGR':>10}{'死拿CAGR':>10}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    store = {}
    for t0s in LAYERS:
        st, df = A.run_layer(px, t0s, pd.Timestamp(t0s))
        if st is None:
            continue
        yrs = float(df.yrs.iloc[0])
        df["exc_ann"] = (1 + df.exc) ** (1 / yrs) - 1
        df["conv"] = df.exc / (df.chip_geo - 1).replace(0, np.nan)
        store[t0s] = (st, df, yrs)
        print(f"  {t0s:<12}{yrs:>7.2f}{st['n']:>5}{st['npair']:>7}"
              f"{p(df.chip_ann.median()):>10}{df.chip_geo.median():>10.4f}"
              f"{p(df.exc.median()):>10}{p(df.exc_ann.median()):>10}"
              f"{df.conv.median():>8.2f}{p(df.nav_cagr.median()):>10}"
              f"{p(df.hold_cagr.median()):>10}")
    print("  " + "-" * (len(hdr) - 2))
    print("  ⇒ 超额是【整个窗口的累计值】, 筹码是【年化值】—— 同一行两个数不同单位。")
    print("  ⇒ 关系: 超额(累计) ≈ 兑现率 × 累计筹码增幅 (主口径 12.50% ≈ 0.62 × 26.48%)。")
    print()
    print("  同行业 vs 跨行业 (两层对照):")
    for t0s in ("2005-01-07", "2015-01-09", "2020-10-09"):
        if t0s not in store:
            continue
        st, df, yrs = store[t0s]
        s, c = df[df.Aind == df.Bind], df[df.Aind != df.Bind]
        print(f"    {t0s} 同行业 {len(s):>5} 对 筹码年化 {p(s.chip_ann.median()):>8} "
              f"超额折年 {p((1 + s.exc.median()) ** (1 / yrs) - 1):>8}   |   "
              f"跨行业 {len(c):>5} 对 筹码年化 {p(c.chip_ann.median()):>8} "
              f"超额折年 {p((1 + c.exc.median()) ** (1 / yrs) - 1):>8}")
    return store


# ------------------------------------------------------------------ 段B
def section_b(px, store, t0s="2015-01-09"):
    st, df, yrs = store[t0s]
    print()
    print(SEP)
    print(f"段B · 超额由谁决定: 强腿(价格倍数更大的一侧)的筹码倍数   [{t0s} 层, {len(df)} 对, {yrs:.2f}y]")
    print(SEP)
    df = df.copy()
    df["beta_strong"] = np.where(df.mA >= df.mB, df.betaA, df.betaB)
    df["beta_weak"] = np.where(df.mA >= df.mB, df.betaB, df.betaA)
    df["w_strong"] = df[["mA", "mB"]].max(axis=1) / (df.mA + df.mB)
    print(f"  强腿权重 w 中位 {df.w_strong.median():.3f}  "
          f"P10 {df.w_strong.quantile(.10):.3f}  P90 {df.w_strong.quantile(.90):.3f}")
    print(f"  强腿筹码 β 中位 {df.beta_strong.median():.4f} (<1 占 {p((df.beta_strong < 1).mean(), 1)})")
    print(f"  弱腿筹码 β 中位 {df.beta_weak.median():.4f} (>1 占 {p((df.beta_weak > 1).mean(), 1)})")
    print(f"  corr(超额, β_强腿) = {df.exc.corr(df.beta_strong):+.3f}   "
          f"corr(超额, β_弱腿) = {df.exc.corr(df.beta_weak):+.3f}")
    print()
    bins = [0, .2, .35, .5, .7, .9, 1.0, 1.3, 99]
    lab = ["<0.2", "0.2-0.35", "0.35-0.5", "0.5-0.7", "0.7-0.9", "0.9-1.0",
           "1.0-1.3", ">1.3"]
    df["bkt"] = pd.cut(df.beta_strong, bins=bins, labels=lab, right=False)
    print(f"  {'强腿β':<11}{'对数':>6}{'超额累计中位':>13}{'折年化':>10}"
          f"{'净值CAGR':>11}{'死拿CAGR':>11}")
    for k, g in df.groupby("bkt", observed=True):
        print(f"  {str(k):<11}{len(g):>6}{p(g.exc.median()):>13}"
              f"{p((1 + g.exc.median()) ** (1 / yrs) - 1):>10}"
              f"{p(g.nav_cagr.median()):>11}{p(g.hold_cagr.median()):>11}")
    print("  ⇒ 权重压在强腿 ⇒ 超额 ≈ 『强腿筹码掉没掉』; 弱腿那堆筹码只占不到 1/3 权重。")


# ------------------------------------------------------------------ 段C
def section_c(px):
    print()
    print(SEP)
    print("段C · 半导体 × 存储 受控对照 (同窗口, 每腿 $5,000)")
    print(SEP)
    print("  上市时间: " + " / ".join(
        f"{n} {px[col0(px, n)].dropna().index[0].date()}" for n in SEMI
        if col0(px, n) is not None))
    print(f"  ⇒ 需上市满 {MIN_HIST} 周才可作配对腿; 2015 主口径内只有北方华创一只是半导体。")
    print()
    names = list(SEMI) + list(PEERS)
    cols = {n: col0(px, n) for n in names}
    t0 = pd.Timestamp("2017-02-17")
    sub = px[[c for c in cols.values() if c is not None]].loc[t0:].dropna(how="any")
    yrs = (sub.index[-1] - sub.index[0]).days / 365.25
    inv = {v: k for k, v in cols.items() if v is not None}
    print(f"  受控窗口 {sub.index[0].date()} ~ {sub.index[-1].date()}  {yrs:.2f} 年 "
          f"({len(sub)} 周, {sub.shape[1]} 只; 被最晚上市的中芯国际压窄)")
    print()
    r = sub.pct_change()
    cm = r.corr()
    lab = [f"{inv[c]}" for c in cm.columns]
    print("  相关矩阵: " + "  ".join(f"{x}" for x in lab))
    for i, c in enumerate(cm.columns):
        print(f"    {lab[i]:<6}" + "".join(f"{cm.iloc[i, j]:>8.3f}" for j in range(len(cm))))
    print()
    rows = []

    def line(lab_, a, b):
        r_ = A.sim_pair(sub[[cols[a], cols[b]]].values.astype(float))
        rho = float(cm.loc[cols[a], cols[b]])
        ann = r_["chip_geo"] ** (1 / yrs) - 1
        rows.append(dict(pair=lab_, a=a, b=b, rho=rho, chip_ann=ann, exc=r_["exc"],
                         nav=r_["nav_mult"], hold=r_["hold_mult"]))
        print(f"  {lab_:<20}{rho:>7.3f}{r_['beta'][0]:>8.3f}{r_['beta'][1]:>8.3f}"
              f"{p(ann):>10}{p(r_['exc']):>10}"
              f"{p((1 + r_['exc']) ** (1 / yrs) - 1):>10}"
              f"{r_['nav_mult']:>9.3f}{r_['hold_mult']:>9.3f}")

    hdr = (f"  {'组合':<20}{'相关':>7}{'筹码A':>8}{'筹码B':>8}{'筹码年化':>10}"
           f"{'超额累计':>10}{'超额折年':>10}{'净值×':>9}{'死拿×':>9}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    line("设备×存储", "北方华创", "兆易创新")
    line("制造×存储", "中芯国际", "兆易创新")
    line("设计×存储", "韦尔股份", "兆易创新")
    print("  " + "-" * (len(hdr) - 2))
    for a in ("北方华创", "兆易创新"):
        for b in PEERS:
            line(f"{a}×{b}", a, b)
        print("  " + "-" * (len(hdr) - 2))
    D = pd.DataFrame(rows)
    semi = D[(D.a.isin(SEMI)) & (D.b.isin(SEMI))]
    cross = D[(D.a.isin(SEMI)) ^ (D.b.isin(SEMI))]
    for tag, g in (("半导体×半导体(子行业互配)", semi), ("半导体×跨行业", cross)):
        print(f"  {tag:<26}{len(g):>3} 对  筹码年化中位 {p(g.chip_ann.median()):>8}  "
              f"超额折年中位 {p((1 + g.exc.median()) ** (1 / yrs) - 1):>8}  "
              f"平均相关 {g.rho.mean():.3f}")
    print()
    print(f"  【换对手的单调性】固定 北方华创, 换对手 (对手独家死拿倍数 ↓):")
    hold1 = {n: float(sub[cols[n]].iloc[-1] / sub[cols[n]].iloc[0])
             for n in names if cols[n]}
    for _, rr in D[D.a == "北方华创"].sort_values("hold", ascending=True).iterrows():
        opp = rr.b if rr.a == "北方华创" else rr.a
        print(f"    {opp:<8}({PEERS.get(opp, '半导体'):<5}) 独家死拿 {hold1[opp]:>6.2f}×  "
              f"超额 {p(rr.exc):>8}  折年 {p((1 + rr.exc) ** (1 / yrs) - 1):>8}")
    print("  ⇒ 对手越强(与北方华创漂移差越小) → 超额越好; 漂移差拉大 → 超额转负。")


def main():
    px = A.load_px()
    print(f"面板 {px.shape[0]} 周 × {px.shape[1]} 只  "
          f"{px.index[0].date()} ~ {px.index[-1].date()}")
    print(f"口径: 两股 50:50 · {A.REBAL_WEEKS} 周调仓 · {A.COST_BP:.0f}bp · "
          f"筹码死拿=1.000 · 新标的需上市满 {MIN_HIST} 周")
    store = section_a(px)
    section_b(px, store)
    section_c(px)
    print()
    print(SEP)
    print("完成。")
    print(SEP)


if __name__ == "__main__":
    main()
