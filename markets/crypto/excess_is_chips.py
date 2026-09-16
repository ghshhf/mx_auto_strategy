# -*- coding: utf-8 -*-
"""excess_is_chips.py — 「超额收益 = 筹码变多」恒等式 + AAVE 场景推演

用户命题 (2026-09-14):
    "你下跌的时候不转筹码, 那你那个收益怎么超额呢? 超额收益本质上就是筹码变多了。"
    "AAVE 未来涨到 500 美元…如果中间不转筹码, 到后期不就还是接盘高位买入吗?"

本脚本把这条命题做成三件事:
  【段1】恒等式: 证明"超额收益"不存在第二个来源 —— 它就是筹码增幅的加权平均。
          NAV_rebal(T) - NAV_hold(T) = Σ_i (1/n)·m_i·(β_i - 1)
          超额比例 = Σ_i [m_i/Σ_j m_j]·(β_i - 1),  m_i=价格倍数, β_i=筹码倍数
          权重 = 该币最终涨幅的贡献占比 → "筹码变多"必须变在最终跑赢的一侧。
  【段2】全样本检验: 2,561 对里"筹码>1"与"超额>0"的重合度 (筹码是机器产出, 超额是结果)。
  【段3】AAVE 价格史核对 (Binance 日线, 缓存 out/aave_daily.csv)。
  【段4】场景: AAVE 终点价 $100~1000 下, 再平衡 vs 死拿 的净值/超额; 盈亏平衡价。
  【段5】"转筹码"的等效入场成本: 再平衡替你换来的 AAVE 平均成本 vs 现价 vs 目标价。
  【段6】三路径对照: 死拿不加 / 再平衡转筹码 / 到 $500 才买入。

铁律: 再平衡目的 = 筹码不掉队, 非收益最大化。本脚本中"筹码"= 币量倍数(死拿=1.000)。
"""
import os
import sys
import math
import json
import time
import datetime as dt
import importlib.util
import urllib.request

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

_spec = importlib.util.spec_from_file_location("bap", os.path.join(HERE, "crypto_btc_ada_pair.py"))
bap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bap)

# 🔒 调仓数学收敛到跨市场唯一引擎 markets/core/rebalance.py (2026-09-15)
_spec_rb = importlib.util.spec_from_file_location(
    "rb_kernel", os.path.join(os.path.dirname(HERE), "core", "rebalance.py"))
_rb = importlib.util.module_from_spec(_spec_rb)
_spec_rb.loader.exec_module(_rb)

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50_10y.csv")
OUTDIR = os.path.join(HERE, "out")
CACHE_DAILY = os.path.join(OUTDIR, "aave_daily.csv")
COST_BP = 10.0
REBAL_WEEKS = 4
MAIN_START = "2020-10-09"     # 主口径起点: AAVE 上市周 (面板首行也就此开始)

SEP = "=" * 108
sep = "-" * 108


# ---------------------------------------------------------------- 数据
def load_panel():
    px = pd.read_csv(PANEL, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


def aave_daily(refresh=False):
    """Binance AAVEUSDT 日线; 缓存到 out/aave_daily.csv, 网络失败自动降级到缓存。

    返回的 index 统一为 DatetimeIndex (无论走缓存还是现拉)。
    """
    if os.path.exists(CACHE_DAILY) and not refresh:
        d = pd.read_csv(CACHE_DAILY, index_col=0, parse_dates=True)
        d.index = pd.to_datetime(d.index)
        return d
    try:
        import net_config
        opener = net_config.proxy_opener()
    except Exception:
        opener = urllib.request.build_opener()

    def gj(url):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return json.loads(opener.open(req, timeout=40).read().decode())

    rows, t0 = [], int(dt.datetime(2020, 9, 25, tzinfo=dt.timezone.utc).timestamp() * 1000)
    while True:
        k = gj(f"https://api.binance.com/api/v3/klines?symbol=AAVEUSDT&interval=1d&startTime={t0}&limit=1000")
        if not k:
            break
        rows += k
        if len(k) < 1000:
            break
        t0 = k[-1][0] + 86400000
        time.sleep(0.25)
    if not rows:
        if os.path.exists(CACHE_DAILY):
            return pd.read_csv(CACHE_DAILY, index_col=0, parse_dates=True)
        raise RuntimeError("AAVE 日线获取失败且无缓存")
    rec = [(dt.datetime.fromtimestamp(x[0] / 1000, dt.timezone.utc).strftime("%Y-%m-%d"),
            float(x[1]), float(x[2]), float(x[3]), float(x[4])) for x in rows]
    # 丢弃未收盘的当日 bar —— Binance 会把"进行中"的当日 K 线一并返回, 其 close
    # 是滚动值。实测 2026-09-14 01:03(北京) 抓到 09-13 报 126.68, 而该日真实收盘
    # 是 124.35(差 1.9%)。留着会污染所有"最新价/现价"类统计, 故一律剔除。
    _today_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    rec = [r for r in rec if r[0] < _today_utc]

    d = (pd.DataFrame(rec, columns=["date", "open", "high", "low", "close"])
           .drop_duplicates("date").set_index("date").sort_index())
    d.index = pd.to_datetime(d.index)
    os.makedirs(OUTDIR, exist_ok=True)
    d.to_csv(CACHE_DAILY, float_format="%.6f")
    return d


# ------------------------------------------------- 与引擎完全一致的再平衡 (带成交日志)
def sim_trades(px, coins, focus, capital=10000.0, rebal_weeks=REBAL_WEEKS,
               cost_bp=COST_BP, start=None, end=None):
    """等权月度再平衡, 记录 focus 币每次成交的币量与现金。口径与引擎 sim 一致。"""
    sub = px[list(coins)].dropna(how="any")
    if start is not None:
        sub = sub[sub.index >= start]
    if end is not None:
        sub = sub[sub.index <= end]
    if len(sub) < rebal_weeks * 2:
        return None
    pr = sub.values.astype(float)
    T, n = pr.shape
    w = np.ones(n) / n
    i = list(coins).index(focus)
    # 🔒 核心循环 → 唯一引擎 (track_trades 提供逐次调仓的份额快照)
    kr = _rb.rebalance_kernel(pr, rebal_weeks=rebal_weeks, cost_bp=cost_bp,
                              capital=capital, track=True, track_trades=True)
    NAV, R_hist = kr["NAV"], kr["R_hist"]
    units, U0 = kr["units"], kr["U0"]
    trades = []
    for s in kr["steps"]:
        dq = float(s["units_after"][i] - s["units_before"][i])
        trades.append(dict(date=sub.index[s["k"]], dq=dq,
                           px=float(s["price"][i]),
                           cash=float(dq * s["price"][i])))
    yrs = (sub.index[-1] - sub.index[0]).days / 365.25
    hold_ser = pd.Series((w * (pr / pr[0])).sum(axis=1), index=sub.index) * capital
    nav_ser = pd.Series(NAV, index=sub.index)
    R = units / U0
    ret = nav_ser.pct_change().dropna()
    if len(coins) == 2:
        a, b = pr[:, 0], pr[:, 1]
        ra, rb = np.diff(np.log(a)), np.diff(np.log(b))
        rho = float(np.corrcoef(ra, rb)[0, 1])
    else:
        rho = float("nan")
    return dict(
        coins=list(coins), yrs=yrs, start=sub.index[0], end=sub.index[-1],
        nav=float(nav_ser.iloc[-1]), hold=float(hold_ser.iloc[-1]),
        excess=float(nav_ser.iloc[-1] / hold_ser.iloc[-1] - 1),
        units=units, U0=U0, R=R, i=i,
        px_first=pr[0].copy(), px_last=pr[-1].copy(),
        px_ser=sub, R_hist=pd.DataFrame(R_hist, index=sub.index, columns=list(coins)),
        nav_ser=nav_ser, hold_ser=hold_ser, rho=rho,
        vol_ann=float(ret.std() * np.sqrt(52)),
        turnover_ann=float(len(trades) / yrs) * (2 if n == 2 else n / 2.0),
        trades=trades,
    )


# ---------------------------------------------------------------- 段1 恒等式
def section_identity(px):
    print(SEP)
    print("【段1】恒等式检验: 超额收益是否存在『筹码变多』之外的第二个来源?")
    print(SEP)
    print("  设 n 币等权, 起点各投 1/n, m_i = P_i(T)/P_i(0) 价格倍数, β_i = 筹码倍数。")
    print("  死拿:   NAV_hold(T)  = (1/n)·Σ m_i            ← 只有价格")
    print("  再平衡: NAV_rebal(T) = (1/n)·Σ m_i·β_i        ← 价格 × 筹码")
    print("  相减:   NAV_rebal(T) - NAV_hold(T) = (1/n)·Σ m_i·(β_i - 1)")
    print()
    print("  ⇒ 超额(绝对额)  = Σ_i [w_i·m_i]·(β_i - 1)      w_i = 1/n 初始权重")
    print("  ⇒ 超额(比例)    = Σ_i [m_i / Σ_j m_j]·(β_i - 1)")
    print()
    print("  结论: 超额的唯一来源是 (β_i - 1)。权重 = 该币最终涨幅的贡献占比。")
    print("        若 β_i ≡ 1 (完全不转筹码), 超额恒等于 0 —— 无条件成立, 无例外。")
    print()

    coins19 = [c for c in px.columns if pd.notna(px[c].loc[MAIN_START:]).all() and len(px[c].loc[MAIN_START:].dropna()) > 300]
    rx = px[coins19].loc[MAIN_START:].dropna(how="any")
    # 用面板数据直接验证 (对象: 全部 C(19,2) 配对)
    from itertools import combinations
    errs, rows = [], []
    for a, b in combinations(coins19, 2):
        r = sim_trades(rx, [a, b], a, capital=1.0)
        if r is None:
            continue
        m = r["px_last"] / r["px_first"]
        beta = r["R"]
        resid = float(np.sum(m * (beta - 1)) / np.sum(m))     # 恒等式右端
        errs.append(abs(resid - r["excess"]))
        rows.append((a, b, r["excess"], resid, r["R"][0], r["R"][1], m[0], m[1]))
    print(f"  数值验证 (主口径 {len(coins19)} 币窗口 {rx.index[0].date()}~{rx.index[-1].date()}, "
          f"{len(rows)} 对):")
    print(f"     max |恒等式右端 - 引擎超额| = {max(errs):.3e}   (浮点级误差 → 恒等式成立)")
    print()
    print("  抽样展示 (超额 = 筹码项按价格倍数加权):")
    print(f"    {'配对':<14}{'价格倍数A':>10}{'价格倍数B':>10}{'筹码βA':>9}{'筹码βB':>9}"
          f"{'超额(引擎)':>11}{'Σm(β-1)/Σm':>12}")
    for r in sorted(rows, key=lambda x: -abs(x[2]))[:6]:
        print(f"    {r[0]+'+'+r[1]:<14}{r[6]:>10.3f}{r[7]:>10.3f}{r[4]:>9.4f}{r[5]:>9.4f}"
              f"{r[2]:>11.2%}{r[3]:>12.2%}")
    print()
    print("  ⚠️ 权重是 m_i: 筹码必须变在『最终跑赢』的一侧, 超额才为正。")
    print("     这是从恒等式直接读出的必要条件, 不是经验规律。")
    return coins19, rx, rows


# ---------------------------------------------------------------- 段2 全样本
def section_allpairs():
    print()
    print(SEP)
    print("【段2】全样本 2,561 对: 『筹码>1』与『超额>0』是不是同一件事?")
    print(SEP)
    p = os.path.join(OUTDIR, "all_pairs_exhaustive.csv")
    if not os.path.exists(p):
        print("  (缺 out/all_pairs_exhaustive.csv, 跳过)")
        return
    ex = pd.read_csv(p)
    n = len(ex)
    chip_up = int((ex["ucb"] > 1.0).sum())
    beat = int((ex["nav"] > ex["hold"]).sum())
    both = int(((ex["ucb"] > 1.0) & (ex["nav"] > ex["hold"])).sum())
    chip_up_lose = int(((ex["ucb"] > 1.0) & (ex["nav"] <= ex["hold"])).sum())
    print(f"  样本: {n} 对 (13 层窗口, 含主口径 19 币 171 对)")
    print(f"    筹码倍数 > 1.000 (筹码变多) : {chip_up:>4} 对  ({chip_up/n:>6.1%})")
    print(f"    净值 > 死拿       (超额>0)  : {beat:>4} 对  ({beat/n:>6.1%})")
    print(f"    两者同时成立                : {both:>4} 对  ({both/n:>6.1%})")
    print(f"    筹码变多 但 超额≤0          : {chip_up_lose:>4} 对  ({chip_up_lose/n:>6.1%})")
    print()
    print("  ⇒ 筹码变多是『几乎必然』的 (收割项 ¼(1-ρ)σ²T 是确定项);")
    print("     但超额为正需要在 m_i 大的那一侧筹码变多。二者不完全重合,")
    print("     差额就是『筹码搬到了最终跑输的一侧』。")
    print()
    print()
    print("  ⚠️ 但『筹码变多』≠『超额为正』—— 权重是 m_i, 必须变在最终跑赢的一侧。")
    print("     按窗口长度拆开看:")
    for lab, nm in [("2020-10-09/19币", "主口径 5.90 年 (19 币)")]:
        s = ex[ex["layer"] == lab]
        if not len(s):
            continue
        print(f"       {nm}: 筹码>1 {int((s['ucb']>1).sum())}/{len(s)}, "
              f"超额>0 {int((s['nav']>s['hold']).sum())}/{len(s)} "
              f"({(s['nav']>s['hold']).mean():.1%}), "
              f"超额中位 {(s['nav']/s['hold']-1).median():+.2%}")
    short = ex[ex["yrs"] < 3]
    if len(short):
        print(f"       短窗口 (<3年, {len(short)} 对): 超额>0 仅 "
              f"{(short['nav']>short['hold']).mean():.1%}, "
              f"中位 {(short['nav']/short['hold']-1).median():+.2%}")
        print("       → 收割项 ¼(1-ρ)σ²T 与 T 成正比: 窗口太短, 筹码优势来不及堆出来。")
    else:
        print("       (无 <3 年层)")
    print(f"       相关系数 corr(组合筹码倍数, 超额) = "
          f"{np.corrcoef(ex['ucb'], ex['nav']/ex['hold']-1)[0,1]:.3f}  "
          f"→ 同向但不是 1:1, 差的正是『筹码落在哪一侧』。")
    return


# ---------------------------------------------------------------- 段3 AAVE 史
def section_history(d):
    print()
    print(SEP)
    print("【段3】AAVE 价格史核对 (Binance AAVEUSDT 日线)")
    print(SEP)
    close, low, high = d["close"], d["low"], d["high"]
    atl_d = low.idxmin(); ath_d = high.idxmax()
    cur = float(close.iloc[-1])
    print(f"  数据区间 {d.index[0].date()} ~ {d.index[-1].date()}  n={len(d)}")
    print(f"  上市首日 {d.index[0].date()}  O {d['open'].iloc[0]:.2f} / C {d['close'].iloc[0]:.2f}")
    print(f"  历史最低(盘中) {low.min():.2f} @ {atl_d.date()}")
    print(f"  历史最高(盘中) {high.max():.2f} @ {ath_d.date()}")
    print(f"  最新收盘 {cur:.2f} @ {d.index[-1].date()}")
    print()
    print(f"  {'年份':<6}{'年内最低':>12}{'低点日':>14}{'年内最高':>12}{'高点日':>14}")
    for y, g in d.groupby(d.index.year):
        print(f"  {y:<6}{g['low'].min():>12.2f}{str(g['low'].idxmin().date()):>14}"
              f"{g['high'].max():>12.2f}{str(g['high'].idxmax().date()):>14}")
    print()
    # 底部抬升阶梯
    steps = []
    for y, g in d.groupby(d.index.year):
        steps.append((y, float(g["low"].min()), float(g["high"].max())))
    first_low = steps[0][1]
    print(f"  底部阶梯 (以 2020 年 {first_low:.2f} 为 1.00×):")
    for y, lo, hi in steps:
        print(f"    {y}  低点 {lo:>8.2f}  = {lo/first_low:>5.2f}× 起始低点   "
              f"高点 {hi:>8.2f}  = {hi/first_low:>5.2f}×")
    print()
    atl_z = (d.index >= atl_d) if False else None
    yrs_from_low = (d.index[-1] - atl_d).days / 365.25
    yrs_from_ath = (d.index[-1] - ath_d).days / 365.25
    print(f"  从历史最低到今天 {yrs_from_low:.2f} 年: {cur/float(low.min()):.2f}×  "
          f"年化 {(cur/float(low.min()))**(1/yrs_from_low)-1:+.1%}")
    print(f"  从历史最高到今天 {yrs_from_ath:.2f} 年: {cur/float(high.max()):.2f}×  "
          f"(距高点 {cur/float(high.max())-1:+.1%}, 至今未创新高)")
    print()
    print("  ⇒ 起点 $28 一档 → 今天 $126, 年化 ~+28%。这在股票市场是很好的成绩;")
    print("     在加密里显得平, 只是因为拿它跟百倍币比。")
    return dict(cur=float(cur), atl=float(low.min()), atl_d=str(atl_d),
                ath=float(high.max()), ath_d=str(ath_d))


# ---------------------------------------------------------------- 段4/5/6 场景
def section_scenario(px, hist, pairs=None):
    cur_px = hist["cur"]
    pairs = pairs or [("AAVE", "BTC"), ("AAVE", "UNI"), ("AAVE", "ETH"), ("AAVE", "SOL")]
    px_ok = [p for p in pairs if all(c in px.columns for c in p)]

    print()
    print(SEP)
    print("【段4】AAVE 场景: 『下跌时转筹码』到底换来了什么")
    print(SEP)
    print("  统一设定: 起点 $10,000 (两侧各 $5,000), 月度再平衡, 单边 10bp, 窗口 = 主口径窗口")
    print()

    results = []
    for a, b in px_ok:
        r = sim_trades(px, [a, b], a, capital=10000.0, start=MAIN_START)
        if r is None:
            continue
        trades = r["trades"]
        bought = [t for t in trades if t["dq"] > 0]
        sold = [t for t in trades if t["dq"] < 0]
        gross_buy_u = sum(t["dq"] for t in bought)
        cash_out = sum(t["cash"] for t in bought)
        gross_sell_u = sum(-t["dq"] for t in sold)
        cash_in = sum(-t["cash"] for t in sold)
        net_u = float(r["units"][r["i"]] - r["U0"][r["i"]])
        net_cash = sum(t["cash"] for t in trades)
        results.append(dict(a=a, b=b, r=r, net_u=net_u, net_cash=net_cash,
                            gross_buy_u=gross_buy_u, cash_out=cash_out,
                            gross_sell_u=gross_sell_u, cash_in=cash_in,
                            avg_buy_px=cash_out / gross_buy_u if gross_buy_u > 0 else float("nan"),
                            avg_sell_px=cash_in / gross_sell_u if gross_sell_u > 0 else float("nan"),
                            n_buy=len(bought), n_sell=len(sold),
                            beta_a=float(r["R"][r["i"]]),
                            beta_b=float(r["R"][1 - r["i"]]),
                            m_a=float(r["px_last"][r["i"]] / r["px_first"][r["i"]]),
                            m_b=float(r["px_last"][1 - r["i"]] / r["px_first"][1 - r["i"]])))

    print(f"  {'配对':<12}{'年数':>6}{'β(AAVE)':>9}{'β(对手)':>9}{'筹码年化':>9}"
          f"{'再平衡净值':>11}{'死拿净值':>10}{'超额':>9}{'ρ':>7}")
    for x in results:
        r = x["r"]
        chip_ann = x["beta_a"] ** (1 / r["yrs"]) - 1
        print(f"  {x['a']+'+'+x['b']:<12}{r['yrs']:>6.2f}{x['beta_a']:>9.4f}{x['beta_b']:>9.4f}"
              f"{chip_ann:>9.2%}{r['nav']:>11,.0f}{r['hold']:>10,.0f}"
              f"{r['excess']:>9.2%}{r['rho']:>7.3f}")

    base = next((x for x in results if x["b"] == "BTC"), results[0] if results else None)
    if base is None:
        return
    a, b = base["a"], base["b"]
    r = base["r"]
    uA0, uB0 = r["U0"][r["i"]], r["U0"][1 - r["i"]]
    uA, uB = r["units"][r["i"]], r["units"][1 - r["i"]]
    pB_now = r["px_last"][1 - r["i"]]
    dA, dB = uA - uA0, uB0 - uB
    print()
    print(f"  ── 以 {a}+{b} 为详细样本 ──")
    print(f"  窗口 {r['start'].date()} ~ {r['end'].date()}  ({r['yrs']:.2f} 年)")
    print(f"  AAVE 起点 {r['px_first'][r['i']]:.2f} → 终点 {r['px_last'][r['i']]:.2f} "
          f"({base['m_a']:.3f}×)   {b} 起点 {r['px_first'][1-r['i']]:.2f} → "
          f"终点 {r['px_last'][1-r['i']]:.2f} ({base['m_b']:.3f}×)")
    print(f"  AAVE 筹码 {base['beta_a']:.4f}×    {b} 筹码 {base['beta_b']:.4f}×")
    print(f"  再平衡净值 {r['nav']:,.0f}  vs  死拿 {r['hold']:,.0f}   超额 {r['excess']:+.2%}")

    # 共 77 次月度调仓
    print()
    print(f"  月度调仓 {len(r['trades'])} 次, 其中买入 AAVE {base['n_buy']} 次 / 卖出 {base['n_sell']} 次")
    print(f"  累计买入 AAVE {base['gross_buy_u']:,.4f} 枚 @ 均价 ${base['avg_buy_px']:,.2f}")
    print(f"  累计卖出 AAVE {base['gross_sell_u']:,.4f} 枚 @ 均价 ${base['avg_sell_px']:,.2f}")
    print(f"  净增持 AAVE {base['net_u']:,.4f} 枚  (起点 {uA0:,.4f} → 终点 {uA:,.4f}, "
          f"{base['net_u']/uA:+.1%} 的持仓是转来的)")
    print(f"  AAVE 腿净现金流 {base['net_cash']:+,.0f} 美元"
          f"  ({'净收钱' if base['net_cash'] > 0 else '净付钱'})")
    print(f"  卖出均价 比 买入均价 高 ${base['avg_sell_px']-base['avg_buy_px']:,.2f}/枚 "
          f"→ 高抛低吸的价差本身就产生现金")
    print()

    # 盈亏平衡 / 恒正条件
    print("  ── 超额 > 0 的条件 (NAV_rebal > NAV_hold ⟺ P_A·dA > P_B·dB) ──")
    print(f"    dA = AAVE 再平衡净增持 = {dA:+,.4f} 枚    (死拿 {uA0:,.4f} → 再平衡 {uA:,.4f})")
    print(f"    dB = {b} 的死拿筹码 − 再平衡筹码 = {dB:+,.4f} 枚    "
          f"(死拿 {uB0:,.4f} → 再平衡 {uB:,.4f})")
    if dA > 0 and dB <= 0:
        print(f"    ⇒ dA>0 且 dB≤0: 两个币的筹码【同时增加】(β_AAVE={base['beta_a']:.3f}, "
              f"β_{b}={base['beta_b']:.3f})")
        print("       → 超额对 AAVE 终点价【无条件为正】。这是纯收割:")
        print("         与 AAVE 涨不涨、涨多少都无关, 不需要 AAVE 跑赢任何东西。")
    elif abs(dA) > 1e-12:
        be = pB_now * dB / dA
        print(f"    ⇒ AAVE 盈亏平衡价 = ${be:,.2f}  (现价 ${cur_px:.2f}, 需 {be/cur_px-1:+.1%})")
        print(f"      等价判据: m_AAVE/m_{b} 必须 > {dB/dA:.4f}")
        print(f"      (β_{b}={base['beta_b']:.3f} < 1: {b} 侧筹码被搬走 → 超额依赖 AAVE 兑现)")
    print()

    # 终点价扫描
    print()
    print("  ── AAVE 终点价扫描 (把 AAVE 换到不同价位, 其余币停在面板末日价) ──")
    print(f"  {'AAVE终点价':>12}{'相对现价':>10}{'再平衡净值':>13}{'死拿净值':>12}"
          f"{'再平衡对死拿':>14}{'超额':>10}")
    fixed_b = uB * pB_now
    fixed_b_h = uB0 * pB_now
    scan = []
    for p in [cur_px, 100, 150, 200, 300, 400, 500, 700, 1000]:
        nv = uA * p + fixed_b
        hv = uA0 * p + fixed_b_h
        scan.append((p, nv, hv, nv / hv - 1))
        print(f"  {p:>12,.0f}{p/cur_px:>9.2f}×{nv:>13,.0f}{hv:>12,.0f}{nv/hv:>13.1%}{nv/hv-1:>10.2%}")

    # 段5/6
    print()
    print(SEP)
    print("【段5】『转筹码』到底是怎么发生的 —— 熊市里的每一次搬运")
    print(SEP)
    tr = r["trades"]
    yr_buy = {}
    for t in tr:
        y = str(t["date"])[:4]
        rec = yr_buy.setdefault(y, dict(bu=0.0, bq=0.0, su=0.0, sq=0.0))
        if t["dq"] > 0:
            rec["bu"] += t["dq"]; rec["bq"] += t["cash"]
        else:
            rec["su"] += -t["dq"]; rec["sq"] += -t["cash"]
    print(f"  {'年份':<8}{'买入AAVE':>12}{'均价':>11}{'卖出AAVE':>12}{'均价':>11}{'AAVE年末价':>12}")
    for y in sorted(yr_buy):
        rec = yr_buy[y]
        pa = rec["bq"] / rec["bu"] if rec["bu"] > 1e-12 else float("nan")
        ps = rec["sq"] / rec["su"] if rec["su"] > 1e-12 else float("nan")
        g = px.loc[f"{y}-01-01":f"{y}-12-31", a].dropna()
        ref = float(g.iloc[-1]) if len(g) else float("nan")
        print(f"  {y:<8}{rec['bu']:>12,.4f}{pa:>11,.1f}{rec['su']:>12,.4f}{ps:>11,.1f}{ref:>12,.1f}")

    print()
    print(SEP)
    print("【段6】『中间不转筹码, 后期不就是接盘高位买入吗?』—— 两条路径的现金代价")
    print(SEP)
    tgt = 500.0
    X = base["net_u"]                      # 再平衡净增持的 AAVE 枚数
    cost_rebal = -base["net_cash"]         # 再平衡为这 X 枚付出的净现金
    cost_high = X * tgt                    # 在 $500 买同样 X 枚的花费
    btc_sleeve = fixed_b_h                 # 死拿口径下对手侧在末日的价值
    afford = btc_sleeve / tgt              # 光靠对手侧, 在 $500 能买几枚
    print(f"  设定: 起点 $10,000 (两侧各 $5,000); AAVE 终点价 ${tgt:.0f}; "
          f"{b} 停在末日价 ${pB_now:,.0f}")
    print(f"  目标: 在 AAVE = ${tgt:.0f} 时手里有 {uA:,.4f} 枚 AAVE (再平衡路径的实际筹码量)")
    print()
    print(f"  {'路径':<34}{'AAVE枚数':>12}{'AAVE市值':>12}{'对手侧':>11}{'账户总值':>12}")
    print(f"  {'① 死拿不动':<34}{uA0:>12,.4f}{uA0*tgt:>12,.0f}{btc_sleeve:>11,.0f}"
          f"{uA0*tgt+btc_sleeve:>12,.0f}")
    print(f"  {'② 再平衡(熊市转筹码)':<34}{uA:>12,.4f}{uA*tgt:>12,.0f}{fixed_b:>11,.0f}"
          f"{uA*tgt+fixed_b:>12,.0f}")
    print(f"  {'③ 不转筹码, $500 时全买 AAVE':<34}{afford:>12,.4f}{afford*tgt:>12,.0f}"
          f"{btc_sleeve-afford*tgt:>11,.0f}{btc_sleeve:>12,.0f}")
    print()
    print(f"  ② 比 ① 多 {X:,.4f} 枚 AAVE; 在 $500 时多出 ${X*tgt:,.0f} 的市值。")
    print()
    print(f"  ⚠️ 路径③ 光靠『不转筹码攒下的对手侧』(${btc_sleeve:,.0f}) 在 $500 只能买 "
          f"{afford:,.4f} 枚,")
    print(f"     比 ② 的 {uA:,.4f} 枚少 {uA-afford:,.4f} 枚; 要凑够同样筹码需掏出新钱 "
          f"${cost_high-btc_sleeve:,.0f}。")
    print()
    print(f"  ⚠️ 更根本的一点: 在终点价买入【不改变账户总值】——")
    print(f"     同样的钱在 $500 买, 和在 $500 前任何时点买, 只要终点都是 $500, 总值一样。")
    print(f"     高位买入唯一的代价是: 同样的筹码, 路径②净现金流 {base['net_cash']:+,.0f},")
    print(f"     路径③要付 ${cost_high:,.0f} → 差 ${cost_high-cost_rebal:,.0f}。")
    print()
    print("  ⚠️ 边界 (不能顺着说的地方): 这套只在『AAVE 最终兑现』时成立。")
    print("     若 AAVE 永远停在现价之下, β>1 只是把筹码堆在一个不涨的币上,")
    print(f"     净值会输给死拿 —— 这正是 {b} 侧 β<1 的含义。")


def export_scenario(px, pair=("AAVE", "BTC"), out_csv=None):
    """导出 AAVE+对手 的逐周序列, 供作图取数。"""
    a, b = pair
    r = sim_trades(px, [a, b], a, capital=10000.0, start=MAIN_START)
    if r is None:
        return None
    i = r["i"]
    df = pd.DataFrame({
        "date": r["px_ser"].index.strftime("%Y-%m-%d"),
        f"px_{a}": r["px_ser"][a].values,
        f"px_{b}": r["px_ser"][b].values,
        f"chip_{a}": r["R_hist"][a].values,          # 再平衡下的筹码倍数
        f"chip_{b}": r["R_hist"][b].values,
        "chip_hold_a": 1.0,                           # 死拿筹码恒为 1
        "nav_rebal": r["nav_ser"].values,
        "nav_hold": r["hold_ser"].values,
    })
    out_csv = out_csv or os.path.join(OUTDIR, "aave_excess_scenario.csv")
    df.to_csv(out_csv, index=False, float_format="%.6f")
    return out_csv


def main():
    px = load_panel()
    coins19, rx, rows = section_identity(px)
    section_allpairs()
    d = aave_daily()
    hist = section_history(d)
    section_scenario(px, hist)
    p = export_scenario(px)
    if p:
        print()
        print(f"  [导出] 逐周序列 -> {os.path.relpath(p, REPO)}")


if __name__ == "__main__":
    main()
