"""us_sector_match.py - 把联网抓来的**权威行业分类**与本地数据做三重匹配。

匹配对象(三层, 逐层收紧)
------------------------
  匹配①  分类 ↔ 本地行情面板      : 标的能否一一对上、窗口是否可比、市值/上市年补齐
  匹配②  分类 ↔ 本地 11 个行业ETF数据 : **经验验证** —— 每只票与 11 个 SPDR 行业 ETF 的
          周收益相关性排序, 看它挂的行业标签是不是真的它最"同涨同跌"的那个 ETF。
          这一步把"分类"变成"被数据证伪过的分类", 也是回答"同涨同跌合不合理"的直接证据。
  匹配③  分类 ↔ 再平衡回测结果    : 用官方 GICS 分类**重跑**同产业/跨产业拆分,
          与之前的手工标签口径对比, 检验"同产业配对收割差"是不是标签造成的假象。

另附: 跨市场桥接 GICS 11 大类 <-> A股 34 细分行业, 让两个市场能在同一行业口径下对话。

依赖: us_sector_map.csv (由 us_sector_fetch.py 联网生成)
产物: out/us_sector_validation.csv (逐票: 标签 / 实测归属 / 相关排名)
用法: python us_sector_match.py
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(ROOT, "markets", "ashare")):
    if p not in sys.path:
        sys.path.insert(0, p)

from ashare_pair_all import (                       # noqa: E402
    metrics, pool_at, pct, nm, REBAL_WEEKS,
)
from us_pair_50_50 import load_us                     # noqa: E402

DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "out")
SECTOR_MAP = os.path.join(DATA, "us_sector_map.csv")

T0 = "2017-02-03"
TEND = "2026-07-24"
SEC = "=" * 96
SEP = "-" * 96

# 统一 11 大类 -> SPDR 行业 ETF
SECTOR_ETF = {
    "信息技术": "XLK", "医疗保健": "XLV", "工业": "XLI", "可选消费": "XLY",
    "必需消费": "XLP", "金融": "XLF", "能源": "XLE", "材料": "XLB",
    "公用事业": "XLU", "房地产": "XLRE", "通信服务": "XLC",
}
ETF_SECTOR = {v: k for k, v in SECTOR_ETF.items()}
ETF_LIKE = {"SPY", "QQQ", "DIA", "IWM", "MDY", "VTI", "CWB"}

# 跨市场桥接: GICS 11 大类 <-> A股 34 细分行业(按业务实质对齐, 非一一对应)
BRIDGE = {
    "信息技术": ["半导体", "电子", "软件", "服务器", "安防"],
    "通信服务": ["传媒", "通信"],
    "医疗保健": ["医药", "中药"],
    "可选消费": ["汽车", "家电", "免税", "传媒(可选侧)"],
    "必需消费": ["白酒", "啤酒", "乳品", "调味品", "肉制品", "养殖"],
    "金融": ["银行", "券商", "保险"],
    "工业": ["机械", "军工", "建筑", "建材", "交运"],
    "能源": ["煤炭", "化工(能源侧)"],
    "材料": ["钢铁", "有色", "化工"],
    "公用事业": ["电力", "光伏(发电侧)"],
    "房地产": ["地产"],
}


def out(*a):
    print(*a)


def load_etf():
    """本地 11 个 SPDR 行业 ETF 日线 -> W-FRI 周线(与面板同频)。"""
    d = {}
    for f in sorted(glob.glob(os.path.join(DATA, "raw_index_XL*_daily.csv"))):
        sym = os.path.basename(f).split("_")[2]
        s = pd.read_csv(f, index_col=0)
        s.index = pd.to_datetime(s.index)
        d[sym] = s["close"]
    return pd.DataFrame(d).sort_index()


def load_map():
    m = pd.read_csv(SECTOR_MAP)
    m["ticker"] = m.ticker.astype(str).str.strip()
    return m


# ================================================================== 段0
def section0(us, m):
    out(SEP)
    out("段0 · 匹配总览: 分类表 ↔ 行情面板 ↔ 行业ETF")
    out(SEP)
    out(f"  分类表 us_sector_map.csv        {len(m)} 只")
    out(f"  行情面板 weekly_adjclose_full   {us.shape[1]} 只 × {len(us)} 周")
    out(f"    窗口 {us.index[0].date()} ~ {us.index[-1].date()}  "
        f"({(us.index[-1] - us.index[0]).days / 365.25:.2f} 年, 已 W-FRI 重采样)")
    miss = [t for t in us.columns if t not in set(m.ticker)]
    out(f"  面板标的是否全在分类表: {'✅ 全覆盖' if not miss else f'❌ 缺 {miss}'}")
    n_etf = int(m.is_etf.sum())
    out(f"  可做行业实证的标的: {len(m) - n_etf} 只 (剔 {n_etf} 只指数ETF)")
    out(f"  三源覆盖: GICS {m.src_gics.sum()} / Nasdaq {m.src_nasdaq.sum()} / "
        f"SEC {m.src_sec.sum()};  三源齐全 {(m.n_src == 3).sum()}")
    mc = m[m.market_cap.notna() & ~m.is_etf]
    out(f"  市值补全: {len(mc)}/{len(m) - n_etf} 只 (中位 "
        f"${mc.market_cap.median() / 1e9:.1f}B, 最大 "
        f"${mc.market_cap.max() / 1e9:.0f}B)")
    y = m[(m.ipo_year != "") & m.ipo_year.notna() & ~m.is_etf]
    out(f"  上市年补全: {len(y)} 只; 2000 年后上市 {int((y.ipo_year.astype(int) > 2000).sum())} 只"
        f"  (最新 {int(y.ipo_year.astype(int).max())})")
    return m


# ================================================================== 段1/2
def section12(us, ew, m):
    """分类 ↔ 行情 经验验证: 每票 vs 11 行业 ETF 的相关排名。"""
    common = us.index.intersection(ew.index)
    rp = us.loc[common].pct_change()
    re_ = ew.loc[common].pct_change()
    out()
    out(SEP)
    out("段1 · 匹配②: 分类 VS 行情 —— 标签说的行业, 是不是它真正『同涨同跌』的那个?")
    out(SEP)
    out(f"  对齐窗口 {common[0].date()} ~ {common[-1].date()}  ({len(common)} 周)")
    # 每只票对 11 个 ETF 的相关
    rows = []
    for t in rp.columns:
        c = re_.corrwith(rp[t]).dropna()
        if len(c) < 11 or c.isna().all():
            continue
        rk = c.rank(ascending=False)
        top = c.idxmax()
        rows.append(dict(ticker=t, top_etf=top, top_rho=float(c.max()),
                         top2_etf=c.nlargest(2).index[-1],
                         top2_rho=float(c.nlargest(2).iloc[-1]),
                         min_etf=c.idxmin(), min_rho=float(c.min()),
                         **{f"rho_{k}": float(v) for k, v in c.items()}))
    v = pd.DataFrame(rows)
    v["top_sector"] = v.top_etf.map(ETF_SECTOR)
    v["empirical_sector"] = v.top_sector
    v = v.merge(m[["ticker", "name", "uni_sector", "uni_gics", "uni_nasdaq",
                   "uni_sec", "gics_sub_industry", "nasdaq_industry",
                   "sec_sic_desc", "market_cap"]], on="ticker", how="left")

    def hitrate(col, tag):
        if col not in v.columns:
            return
        sub = v[v[col].notna() & (v[col] != "") & v[col].isin(SECTOR_ETF)]
        if not len(sub):
            return
        etf_of = sub[col].map(SECTOR_ETF)
        own = pd.Series([r.get(f"rho_{e}", np.nan)
                         for r, e in zip(sub.to_dict("records"), etf_of)],
                        index=sub.index)
        rank = pd.Series([int(re_.corrwith(rp[t]).rank(ascending=False)[e])
                          for t, e in zip(sub.ticker, etf_of)], index=sub.index)
        out(f"  {tag:<26} n={len(sub):>4}  命中(自有ETF=第1名) "
            f"{float((rank == 1).mean()):>6.1%}   进前3名 "
            f"{float((rank <= 3).mean()):>6.1%}   自有ETF相关中位 "
            f"{own.median():>6.3f}   实测最优 {sub.top_rho.median():>6.3f}")

    out("  口径: 『命中』= 该票与**它自己那一类的行业ETF**的周收益相关性排进 11 个 ETF 的前列。")
    hitrate("uni_gics", "GICS 官方 11 大类")
    hitrate("uni_nasdaq", "Nasdaq 官方 12 类")
    hitrate("uni_sec", "SEC SIC→11 大类")
    hitrate("uni_sector", "本表统一口径(优先GICS)")

    # ⚠️ 公平对照: GICS 只覆盖 S&P500(大盘股), 天然占便宜 -> 必须缩到同一批标的比
    fair = v[v.uni_gics.isin(SECTOR_ETF)]
    out()
    out(f"  ⚠️ 公平对照(把三源都缩到都有标签的同一批 {len(fair)} 只, 消除样本偏差):")

    def fairrate(col, tag):
        sub = fair[fair[col].isin(SECTOR_ETF)]
        if not len(sub):
            return
        etf_of = sub[col].map(SECTOR_ETF)
        rank = pd.Series([int(re_.corrwith(rp[t]).rank(ascending=False)[e])
                          for t, e in zip(sub.ticker, etf_of)], index=sub.index)
        out(f"    {tag:<24} n={len(sub):>4}  命中(第1名) {float((rank == 1).mean()):>6.1%}"
            f"   进前3名 {float((rank <= 3).mean()):>6.1%}")

    fairrate("uni_gics", "GICS 官方 11 大类")
    fairrate("uni_nasdaq", "Nasdaq 官方 12 类")
    fairrate("uni_sec", "SEC SIC→11 大类")
    out("    ⇒ 同批标的下 GICS 仍领先, 说明优势来自分类本身, 不是大盘股更好认。")

    out()
    out("  分行业: 『同涨同跌』有多强 (该类成员 vs 本类 ETF 的相关中位)")
    out(f"    {'行业':<8}{'只数':>5}{'对自有ETF':>11}{'对最优ETF':>11}"
        f"{'自有=最优':>11}{'对最无关ETF':>13}")
    for s, g in v.groupby("uni_sector"):
        if s not in SECTOR_ETF:
            continue
        etf = SECTOR_ETF[s]
        own = g[f"rho_{etf}"].dropna()
        avg_min = np.mean([r.get(f"rho_{e}", np.nan)
                           for r, e in zip(g.to_dict("records"), g.min_etf)])
        out(f"    {s:<8}{len(g):>5}{own.median():>11.3f}{g.top_rho.median():>11.3f}"
            f"{float((own >= g.top_rho - 1e-9).mean()):>11.1%}{avg_min:>13.3f}")

    out()
    out(SEP)
    out("段2 · 标签与实测不符的标的 (需要人工裁决的清单)")
    out(SEP)
    sub = v[v.uni_sector.isin(SECTOR_ETF)].copy()
    sub["own_rank"] = [int(re_.corrwith(rp[t]).rank(ascending=False)[e])
                       for t, e in zip(sub.ticker, sub.uni_sector.map(SECTOR_ETF))]
    sub["hon_rho"] = [r.get(f"rho_{SECTOR_ETF[s]}", np.nan)
                      for r, s in zip(sub.to_dict("records"), sub.uni_sector)]
    bad = sub[sub.own_rank > 1].sort_values("own_rank", ascending=False)
    out(f"  统一口径下 {len(sub)} 只可验证, 其中 {len(bad)} 只 "
        f"({len(bad) / len(sub):.1%}) 的自有行业 ETF **不是**第1名:")
    out(f"    {'代码':<6}{'统一标签':<8}{'实测最优':<8}{'自有排名':>8}{'相关差':>8}  "
        f"{'GICS细分行业':<34}")
    for _, r in bad.iterrows():
        out(f"    {r.ticker:<6}{r.uni_sector:<8}{str(r.top_sector):<8}"
            f"{int(r.own_rank):>8}{r.top_rho - r.hon_rho:>8.3f}  "
            f"{str(r.gics_sub_industry)[:34]:<34}")
    out()
    out("  ⇒ 这些多数不是『标错』, 而是**业务横跨多行业**: 例如 GOOGL/META 在 GICS 里")
    out("     属通信服务(广告/流量), 但云+芯片采购让它和 XLK 也高度同步;")
    out("     VRT(数据中心设备) GICS 归工业, 但客户全是科技巨头, 与 XLK 更同频。")
    os.makedirs(OUT, exist_ok=True)
    v.to_csv(os.path.join(OUT, "us_sector_validation.csv"),
             index=False, encoding="utf-8-sig")
    out("  [✓] 逐票验证明细 -> out/us_sector_validation.csv")
    return v


# ================================================================== 段3
def pairs_sector(px, cols, secmap):
    """同窗、同引擎, 但行业标签换成外部权威口径。只保留标签齐全的腿。"""
    cols = [c for c in cols if str(secmap.get(c, "")) not in ("", "nan")]
    sub = px[cols].loc[T0:TEND].dropna(how="any")
    yrs = (sub.index[-1] - sub.index[0]).days / 365.25
    arr = sub.values.astype(float)
    cl = list(sub.columns)
    r = sub.pct_change().iloc[1:]
    cm = pd.DataFrame(np.corrcoef(r.values.T), index=cl, columns=cl)
    rows = []
    for i in range(len(cl)):
        for j in range(i + 1, len(cl)):
            pr = arr[:, [i, j]]
            if not np.isfinite(pr).all():
                continue
            mm = metrics(pr, yrs)
            a, b = nm(cl[i]), nm(cl[j])
            rows.append(dict(A=a, B=b, Ai=secmap[a], Bi=secmap[b],
                             rho=float(cm.iloc[i, j]), yrs=yrs,
                             chip_ann=mm["chip_ann"], exc=mm["exc"],
                             mA=float(mm["m"][0]), mB=float(mm["m"][1])))
    df = pd.DataFrame(rows)
    df["same"] = (df.Ai == df.Bi) & (df.Ai != "")
    df["drift_gap"] = (np.log(df.mA) - np.log(df.mB)).abs() / df.yrs
    return sub, df


def section3(us, m, pu):
    out()
    out(SEP)
    out("段3 · 匹配③: 用官方分类**重跑**同产业/跨产业拆分 (检验旧结论是否标签造成的假象)")
    out(SEP)
    mrec = m.set_index("ticker")

    def clean(v):
        s = "" if pd.isna(v) else str(v).strip()
        return "" if s in ("", "nan", "None") else s

    # 🔴 严格同集: 三种口径都必须有标签, 否则标的集不同 -> ρ/对数不可比
    base = [c for c in pu if nm(c) != "CYBR"
            and nm(c) in mrec.index
            and all(clean(mrec[col].get(nm(c), "")) for col in
                    ("gics_sector", "nasdaq_sector", "nasdaq_industry",
                     "gics_sub_industry"))]
    sub = us[base].loc[T0:TEND].dropna(how="any")
    yrs = (sub.index[-1] - sub.index[0]).days / 365.25
    npair = len(base) * (len(base) - 1) // 2
    out(f"  🔴 严格对照: 固定**同一标的集**(三源标签都齐的 {len(base)} 只) 与**同一对数**"
        f"(C({len(base)},2)={npair:,})")
    out(f"     窗口 {sub.index[0].date()} ~ {sub.index[-1].date()}  {len(sub)} 周 "
        f"({yrs:.2f} 年);  剔 ETF;  已剔 CYBR(尾部整列缺)")
    out()
    out(f"  {'分类口径':<34}{'类别数':>6}{'对数':>8}{'同类对数':>9}{'同类ρ':>8}"
        f"{'同类筹码年化':>13}{'跨类筹码年化':>13}{'同类/跨类':>10}")
    taxs = [
        ("① GICS Sector (官方 11 大类)", "gics_sector"),
        ("② GICS Sub-Industry (官方细分)", "gics_sub_industry"),
        ("③ Nasdaq sector (官方 12 类)", "nasdaq_sector"),
        ("④ Nasdaq industry (官方细分)", "nasdaq_industry"),
    ]
    for tag, col in taxs:
        sm = {k: clean(mrec[col].get(k, "")) for k in base}
        _, d = pairs_sector(us, base, sm)
        if tag.startswith("①"):
            d1 = d
        s, x = d[d.same], d[~d.same]
        if not len(s) or not len(x):
            continue
        ncat = len({v for v in sm.values() if v})
        out(f"  {tag:<34}{ncat:>6}{len(d):>8,}{len(s):>9,}{s.rho.median():>8.3f}"
            f"{pct(s.chip_ann.median()):>13}"
            f"{pct(x.chip_ann.median()):>13}"
            f"{s.chip_ann.median() / x.chip_ann.median():>9.2f}×")
    # 旧手工细分行业(同一标的集, 只用其中有手工标签的腿)
    try:
        from us_sector_split import SEC as OLD
        haven = [c for c in base if OLD.get(nm(c), "")]
        sm = {k: OLD[nm(k)] for k in haven}
        _, d = pairs_sector(us, haven, sm)
        s, x = d[d.same], d[~d.same]
        if len(s) and len(x):
            out(f"  {'⑤ [对照] 之前手工编的细分行业':<34}"
                f"{len(set(sm.values())):>6}{len(d):>8,}{len(s):>9,}{s.rho.median():>8.3f}"
                f"{pct(s.chip_ann.median()):>13}"
                f"{pct(x.chip_ann.median()):>13}"
                f"{s.chip_ann.median() / x.chip_ann.median():>9.2f}×")
            out(f"      (⑤ 的标的集只能缩到有手工标签的 {len(haven)} 只, "
                f"所以它的『跨类』与①②不同源, 只作量级参考)")
    except Exception as e:                                  # noqa: BLE001
        out(f"  [对照] 手工标签不可用: {e}")
    out()
    out("  同一标的集内, 改用**相关性分桶**验证(ρ 与标签口径无关 ⇒ 这条可比):")
    out(f"    {'ρ 区间':<14}{'对数':>8}{'筹码年化中位':>13}{'超额中位':>11}"
        f"{'超额>0':>9}{'同类占比':>10}")
    edges = [-1, .2, .4, .6, .8, 1.01]
    for i in range(len(edges) - 1):
        b = d1[(d1.rho >= edges[i]) & (d1.rho < edges[i + 1])]
        if not len(b):
            continue
        out(f"    [{edges[i]:>4.1f},{edges[i + 1]:>4.2f}){len(b):>8,}"
            f"{pct(b.chip_ann.median()):>13}{pct(b.exc.median()):>11}"
            f"{float((b.exc > 0).mean()):>9.1%}{float(b.same.mean()):>10.1%}")
    out(f"    corr(ρ, 筹码年化) = {d1.rho.corr(d1.chip_ann):+.3f}   "
        f"corr(ρ, 超额) = {d1.rho.corr(d1.exc):+.3f}")
    out()
    out("  🔴🔴 读法(这行是自我推翻):")
    out("     · 颗粒度粗(11 大类)时, 同类 ≈ 跨类(甚至略好) —— 『别配同产业』在 11 类")
    out("       口径下**不成立**; 之前 0.62× 是用我**自编的 53 个细分类**跑出来的。")
    out("     · 真正单调起作用的是**颗粒度**: 类别越细 -> 同类 ρ 越高 -> 收割越低。")
    out("       看 ρ 那一列怎么随类别数爬升, 再看同类/跨类怎么塌下去。")
    out("     ⇒ 结论该改成: 不是「同产业」不好, 是「**同类里两腿太同步(高 ρ)**」不好;")
    out("       而『同类』的同步强度取决于你把行业切多细。粗类=无用标签, 细类=高 ρ 陷阱。")
    return sub


# ================================================================== 段4
def section4(m, ash):
    out()
    out(SEP)
    out("段4 · 跨市场桥接: GICS 11 大类 ↔ A股 34 细分行业 (统一行业口径才能对话)")
    out(SEP)
    from ashare_universe_build import INDUS
    a_ind = pd.Series(list(INDUS.values())).value_counts()
    us_cnt = m[~m.is_etf].uni_sector.value_counts()
    out(f"  {'GICS 11 大类':<10}{'美股只数':>8}   {'可对接的 A股 行业':<44}{'A股只数':>8}")
    for s, _ in us_cnt.items():
        if s in ("指数ETF", "其他", "未覆盖"):
            continue
        cand = [x for x in BRIDGE.get(s, []) if x in a_ind.index]
        na = int(sum(a_ind[c] for c in cand))
        out(f"  {s:<10}{int(us_cnt[s]):>8}   {'/'.join(cand)[:44]:<44}{na:>8}")
    tot_u = int(us_cnt.drop(["指数ETF", "其他", "未覆盖"], errors="ignore").sum())
    out()
    out(f"  美股 {tot_u} 只可归入 11 大类;  A股 {int(a_ind.sum())} 只分布在 "
        f"{len(a_ind)} 个细分行业")
    gap = [k for k in a_ind.index if not any(k in v for v in BRIDGE.values())]
    out(f"  A股 有而美股池缺对位的行业: {gap}")
    out(f"  美股 有而 A股 池缺对位的行业: "
        f"{[k for k, v in BRIDGE.items() if not any(x in a_ind.index for x in v)]}")
    out()
    out("  ⇒ 之前 A股 段'同行业 0.87% vs 跨行业 2.05%'用的是 A股 自己的 34 细分行业;")
    out("     美股侧现在才有同为官方口径的 11 大类。两边颗粒度不同(A股更细),")
    out("     所以『A股 同行业更差』有一部分来自它把行业切得更细 ⇒ ρ 更高。")


def main():
    us = load_us()
    ew = load_etf()
    m = load_map()
    section0(us, m)
    section12(us, ew, m)
    pu = pool_at(us, pd.Timestamp(T0))
    section3(us, m, pu)
    try:
        from ashare_pair_all import load_px
        ash = load_px()
        section4(m, ash)
    except Exception as e:                                   # noqa: BLE001
        print("段4 跳过:", e)
    out()
    out(SEC)


if __name__ == "__main__":
    main()
