# -*- coding: utf-8 -*-
"""
自动搜索「能吃再平衡超额」的资产池

核心方法 (2026-09-09):
  1) 解析筛选 —— Fernholz 超额增长率 (excess growth rate)
     γ* = (1/2)[ Σ_i w_i σ_ii  -  w'Σw ]
     等权下 = (1/2)(加权平均方差 - 组合方差)
     这是**连续再平衡**相对买入持有的漂移优势, 只依赖协方差矩阵 → 可完全向量化,
     百万级组合秒级评估。它解释了为什么"低相关 + 高波动"能产超额。

  2) 精确验证 —— 对解析 Top 候选做真实月度/季度再平衡回测
     注意: γ* 不含"超级赢家惩罚" (漂移权重偏离导致的 log 收益损失),
     所以解析 Top 必须经精确回测二次筛, 两者差异本身就是"赢家集中度"的度量。

用法:
  python pool_search.py --verify          # 验证 γ* 与实际超额的吻合度(用已知池)
  python pool_search.py --search --k 4 --top 25 --window 2010
"""
import argparse
import itertools
import os
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

PANELS = [
    "us_universe_weekly_adjclose.csv",   # Twelve Data 美股/ADR/ETF 宇宙
    "hk_leaders_weekly_adjclose.csv",    # 腾讯港股龙头
    "a_leaders_weekly_adjclose.csv",     # 腾讯 A股龙头 (hfq 后复权)
    "yahoo_global_weekly_adjclose.csv",  # Yahoo 日/韩/台/欧 全球龙头 (adjclose)
    "equities_weekly_adjclose.csv",      # 早期 4 标的
    "us_etf_weekly_adjclose.csv",        # 美股 ETF 宇宙
    "commodity_worldbank_monthly.csv",   # World Bank 商品 (1960起)
    "fred_extended_monthly.csv",         # FRED 扩展(商品/汇率/股指/宏观)
    "global_assets_monthly.csv",         # FRED 全球资产
]
# 注: eia_gas_monthly.csv 含 500+ 高度相关的州级气价+库存, 留作能源基本面参考,
#     不进自动搜池(能源现货已由 fred_extended 的 Brent/HenryHub/煤 覆盖)。

# 非可直接持有(仅作信号/对照, 不进自动搜池): 宏观/利率水平/VIX 指数本身
NON_TRADABLE_HINTS = ("UNRATE", "CPI", "PCE", "PPI", "GDP", "INDPRO", "RSAFS",
                      "UMCSENT", "M1SL", "M2SL", "WALCL", "H41", "RRP", "WTREGEN",
                      "CSUSHPISA", "MSPUS", "HOUST", "TEDRATE", "STLFSI", "BAML",
                      "VIX", "VXN", "VXD", "RVX", "OVX", "GVZ", "EVZ", "VXV",
                      "DGS", "DFII", "T5YIE", "T10YIE", "T5YIFR", "MORTGAGE",
                      "SOFR", "FEDFUNDS", "DTB3", "DEX", "DTWE", "MORT")


def is_tradable(col):
    u = col.upper()
    return not any(h in u for h in NON_TRADABLE_HINTS)


DATA_DIR = DATA


def load_all():
    frames = []
    for f in PANELS:
        p = os.path.join(DATA_DIR, f)
        if not os.path.exists(p):
            continue
        d = pd.read_csv(p, index_col=0, parse_dates=True)
        d.columns = [str(c) for c in d.columns]
        frames.append(d)
    if not frames:
        raise SystemExit("无数据面板")
    out = pd.concat(frames, axis=1)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    # 跨面板可能有同名列(如同名股指), 保留首次出现, 避免 px[c] 变 DataFrame
    dups = out.columns[out.columns.duplicated()].tolist()
    if dups:
        print(f"[去重] 跨面板同名列 {len(dups)} 个: {', '.join(sorted(set(dups))[:12])}"
              f"{' ...' if len(set(dups)) > 12 else ''}")
    out = out.loc[:, ~out.columns.duplicated(keep="first")]
    return clean(out)


def clean(px):
    """剔除复权异常序列: 非正价格 / 单周跳涨 >400%(除权错误) / 有效点 <36"""
    drop = []
    for c in px.columns:
        s = px[c].dropna()
        if len(s) < 36:
            drop.append(c)
            continue
        if s.min() <= 0:                       # 后复权出现负价 = 复权链断裂
            drop.append(c)
            continue
        if s.pct_change().max() > 4.0:         # 单周 +400% 以上 = 除权/复权错误
            drop.append(c)
    if drop:
        print(f"[清洗] 剔除 {len(drop)} 个异常序列: {', '.join(drop[:12])}"
              f"{' ...' if len(drop) > 12 else ''}")
    return px.drop(columns=drop)


def backtest(sub, rule="ME"):
    """精确回测: 返回 (再平衡CAGR, 死拿CAGR, 超额pp, 再平衡MDD)"""
    m = sub.resample(rule).last() if rule != "ME" else sub.resample("ME").last()
    m = m.dropna()
    if len(m) < 24:
        return None
    g = (m / m.shift(1)).dropna()          # 增长因子(不是收益率!)
    years = len(g) / (4 if rule == "QE" else 12)
    w0 = np.full(g.shape[1], 1.0 / g.shape[1])
    bh = np.cumprod(g.values @ w0)          # 死拿: 初始权重不变
    wb = w0.copy()
    rb = [1.0]
    for i in range(len(g)):
        rr = g.values[i]
        rb.append(rb[-1] * float(np.dot(wb, rr)))
        wb = wb * rr
        wb = wb / wb.sum()
    rb = np.array(rb[1:])
    if rb[-1] <= 0 or bh[-1] <= 0:
        return None
    ex = (rb[-1] ** (1 / years) - bh[-1] ** (1 / years)) * 100
    dd = (rb / np.maximum.accumulate(rb) - 1).min()
    return rb[-1], bh[-1], ex, dd, years


def gamma_star(cov, w=None):
    """Fernholz 超额增长率 (年化, %)"""
    n = cov.shape[0]
    w = np.full(n, 1.0 / n) if w is None else w
    avg_var = np.sum(w * np.diag(cov))
    port_var = float(w @ cov @ w)
    return 0.5 * (avg_var - port_var)


def verify():
    """用已知池验证 γ* 与实际超额的相关性"""
    px = load_all()
    m = px.resample("ME").last()
    POOLS = [
        ("能源油气", ["USO", "UNG", "XLE"]),
        ("金油气农金属", ["GLD", "USO", "UNG", "DBA", "DBB"]),
        ("股债60/40", ["SPY", "TLT"]),
        ("金银铂钯", ["GLD", "SLV", "PPLT", "PALL"]),
        ("9大行业", ["XLF", "XLE", "XLK", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB"]),
        ("日港德英", ["EWJ", "EWH", "EWG", "EWU"]),
        ("国家4+2", ["EWJ", "EWH", "EWG", "EWU", "EWZ", "INDA"]),
        ("发达+新兴", ["EFA", "EEM", "EWJ", "EWG"]),
        ("全类别12", ["SPY", "QQQ", "IWM", "EFA", "EEM", "EWJ", "TLT",
                    "LQD", "GLD", "DBC", "VNQ", "HYG"]),
        ("商品金铜油", ["GLD", "CPER", "USO"]),
        ("债券梯度", ["TLT", "IEF", "LQD", "HYG", "TIP"]),
        ("农产品", ["DBA", "CORN", "WEAT", "SOYB"]),
    ]
    rows = []
    for tag, cols in POOLS:
        cols = [c for c in cols if c in m.columns]
        if len(cols) < 2:
            continue
        sub = m[cols].dropna()
        if len(sub) < 36:
            continue
        ret = (sub / sub.shift(1) - 1).dropna()
        cov = ret.cov().values * 12                     # 年化
        gs = gamma_star(cov) * 100
        bt = backtest(sub.resample("ME").last())
        if bt is None:
            continue
        avg_corr = ret.corr().values[np.triu_indices(len(cols), 1)].mean()
        avg_vol = ret.std().mean() * np.sqrt(12) * 100
        rows.append((tag, len(cols), avg_corr, avg_vol, gs, bt[2]))

    d = pd.DataFrame(rows, columns=["池", "N", "平均相关性", "平均波动%", "γ*预测%", "实际超额pp"])
    pd.set_option("display.width", 200)
    print(d.round(2).to_string(index=False))
    print()
    print("相关性矩阵:")
    print(d[["平均相关性", "平均波动%", "γ*预测%", "实际超额pp"]].corr().round(3).to_string())
    c1 = d["γ*预测%"].corr(d["实际超额pp"])
    print(f"\nγ* 预测 vs 实际超额 相关系数: {c1:.3f}")
    return d


def search(k=4, top=25, window=2010, n_sample=400000, universe=None, rule="ME", max_conc=12):
    """搜索最优池"""
    px = load_all()
    m = px.resample("ME").last()
    m = m[m.index >= f"{window}-01-01"]

    # 数据完整性过滤: 仅保留可直接持有的标的, 覆盖窗口起点附近 + 完整性阈值
    keep = []
    for c in m.columns:
        if not is_tradable(c):
            continue
        s = m[c].dropna()
        if len(s) < 36:
            continue
        # 允许在窗口前 15% 内上市(新龙头也能参与), 但需覆盖后半段
        if s.index[0] > m.index[int(len(m) * 0.15)]:
            continue
        if s.index[-1] < m.index[int(len(m) * 0.85)]:
            continue
        keep.append(c)
    m = m[keep]
    print(f"候选宇宙: {m.shape[1]} 个标的, 窗口 {m.index[0].date()} ~ {m.index[-1].date()}")

    # 完整性过滤: 保留窗口内覆盖 >=60% 的标的(新龙头可参与); γ* 仅作预筛,
    # 最终精确回测对每池取完整重叠区间(sub[cs].dropna), 不受此阈值影响排名
    sub = m.dropna(axis=1, thresh=int(len(m) * 0.6))
    print(f"完整性过滤后: {sub.shape[1]} 个")

    ret_all = (sub / sub.shift(1) - 1).dropna(how="all")
    # 用整体协方差(允许个别 NaN 用 0)
    cov = ret_all.cov().values * 12
    cols = list(sub.columns)
    n = len(cols)

    # 解析 γ* 向量化枚举: 随机采样 n_sample 个 k 元组
    rng = np.random.default_rng(42)
    best = []
    tried = set()
    diag = np.diag(cov)
    iters = min(n_sample, 2000000)
    print(f"采样 {iters} 个 {k} 元组合...")
    idxs = rng.integers(0, n, size=(iters, k))
    # 去重行
    idxs = np.unique(idxs, axis=0)
    print(f"去重后 {len(idxs)} 个")

    # 分块计算 γ* (一次性构造 (iters,k,n) 会 OOM → 每块 20000)
    CH = 20000
    gs_parts = []
    for s0 in range(0, len(idxs), CH):
        blk = idxs[s0:s0 + CH]
        avg_var = diag[blk].mean(axis=1)
        Cb = np.take_along_axis(cov[blk], blk[:, :, None], axis=2)   # (blk,k,k)
        port_var = Cb.sum(axis=(1, 2)) / (k * k)
        gs_parts.append(0.5 * (avg_var - port_var) * 100)
        del Cb
    gs = np.concatenate(gs_parts)

    order = np.argsort(-gs)[:max(top * 12, 300)]
    print("精确回测候选池...")
    rows = []
    for j in order:
        combo = tuple(sorted(idxs[j].tolist()))
        if combo in tried:
            continue
        tried.add(combo)
        if len(set(combo)) < k:          # 跳过含重复标的的池
            continue
        cs = [cols[i] for i in combo]
        d = sub[cs].dropna()
        if len(d) < 36:
            continue
        bt = backtest(d, rule)
        if bt is None:
            continue
        r = (d / d.shift(1) - 1).dropna()
        avg_corr = r.corr().values[np.triu_indices(k, 1)].mean()
        avg_vol = r.std().mean() * np.sqrt(12) * 100
        # 赢家集中度: 最大倍数 / 中位倍数
        mult = d.iloc[-1] / d.iloc[0]
        conc = float(mult.max() / mult.median()) if mult.median() > 0 else np.nan
        rows.append((cs, gs[j], bt[2], bt[0], bt[1], avg_corr, avg_vol, conc, bt[3], bt[4]))
        if len(rows) >= top * 6:
            break

    out = pd.DataFrame(rows, columns=["组合", "γ*预测%", "实际超额pp", "再平衡x", "死拿x",
                                      "平均相关性", "平均波动%", "赢家集中度", "MDD", "年数"])
    out = out.sort_values("实际超额pp", ascending=False)
    pd.set_option("display.width", 250)
    print("\n=== 全部候选 Top", top, "(按实际超额) ===")
    print(out.head(top).round(2).to_string(index=False))
    # 稳健池: 赢家集中度 <= max_conc (剔除单一名字主导的数据挖掘结果)
    rob = out[out["赢家集中度"] <= max_conc].head(top)
    print(f"\n=== 稳健池 (赢家集中度 <= {max_conc}) Top {len(rob)} ===")
    print(rob.round(2).to_string(index=False))
    out.to_csv(os.path.join(DATA, "pool_search_result.csv"), index=False)
    rob.to_csv(os.path.join(DATA, "pool_search_robust.csv"), index=False)
    return out, rob


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--search", action="store_true")
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--window", type=int, default=2010)
    ap.add_argument("--rule", default="ME")
    ap.add_argument("--max-conc", type=float, default=12,
                   help="稳健池赢家集中度上限(最大倍数/中位倍数), 默认12剔除单一名字主导")
    ap.add_argument("--data-dir", default=DATA, help="面板目录(抓取进行中可用快照避免读到半写文件)")
    a = ap.parse_args()
    globals()["DATA_DIR"] = a.data_dir
    if a.verify:
        verify()
    elif a.search:
        search(k=a.k, top=a.top, window=a.window, rule=a.rule, max_conc=a.max_conc)
    else:
        ap.print_help()
