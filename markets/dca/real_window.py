# -*- coding: utf-8 -*-
"""真实历史窗口定投 —— 不用 bootstrap，直接用实际发生过的那一个 40 年。

场景：
  A  三腿（标普500全收益 / 纳指100 / 恒生）共同窗口 1988-01-04 起 38.7 年，各 10 元/日
  B  A + 上证红利ETF（510880 后复权，2007-01-18 起 19.7 年）错峰叠加
  C  A + 上证综指（1990-12-19 起 35.8 年）错峰叠加
  D  纳指100 单腿 38.7 年
  E  标普500全收益 单腿 38.7 年

股息口径：标普500 用官方全收益指数（dy=0）；纳指100 价格指数 +0.7%/年；
        恒生价格指数 +3.5%/年（长期股息率均值）；510880 用后复权（分红已再投）。
"""
import csv, os, json, datetime as dt
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(ROOT, "data", "history")
MACRO = os.path.join(ROOT, "data", "macro")
OUT = os.path.join(ROOT, "out")
os.makedirs(OUT, exist_ok=True)

TODAY = dt.date(2026, 9, 16)
AMT = 10.0


# ----------------------------------------------------------------- 数据
def load_hist(sym):
    with open(os.path.join(HIST, sym + ".csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    d = np.array([dt.date.fromisoformat(r["date"]) for r in rows])
    p = np.array([float(r["adjclose"] or r["close"]) for r in rows])
    return d, p


def make_tr(sym, dy=0.0):
    """价格指数 + 固定年化股息率 → 全收益（按交易日复投）"""
    d, p = load_hist(sym)
    if dy:
        p = p * np.power(1.0 + dy, np.arange(len(p)) / 252.0)
    return d, p


def extend_back(sym, target_start, dy=0.0, tdays=243):
    """把序列按实测几何年化向前延展到 target_start（假设该年化全期成立）。"""
    d, p = make_tr(sym, dy)
    yr = (d[-1] - d[0]).days / 365.25
    g = (p[-1] / p[0]) ** (1.0 / yr) - 1.0
    n = int(round(((d[0] - target_start).days / 365.25) * tdays))
    if n <= 0:
        return d, p
    k = np.arange(n, 0, -1)
    pf = p[0] / np.power(1.0 + g, k / tdays)
    dd, pp, seen = [], [], set()
    for i in range(n):
        x = target_start + dt.timedelta(days=int(round(i * 365.25 / tdays)))
        if x < d[0] and x not in seen:
            seen.add(x)
            dd.append(x)
            pp.append(pf[i])
    return np.array(dd + list(d)), np.concatenate([np.array(pp), p])


def synth_extended(sym, target_start, dy=0.0):
    """延展后落成 CSV，供 build() 当普通腿使用。"""
    d, p = extend_back(sym, target_start, dy)
    name = "EXT_" + sym.replace(".", "_")
    with open(os.path.join(HIST, name + ".csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "close", "adjclose"])
        for a, b in zip(d, p):
            w.writerow([a.isoformat(), f"{b:.6f}", f"{b:.6f}"])
    return name


def load_cpi():
    with open(os.path.join(MACRO, "CPIAUCNS.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    d = np.array([dt.date.fromisoformat(r["date"]) for r in rows])
    v = np.array([float(r["value"]) for r in rows])
    return d, v


def cpi_at(cd, cv, d):
    j = int(np.searchsorted(cd, d)) - 1
    return float(cv[max(j, 0)])


# ----------------------------------------------------------------- 定投
def dca(px, amt=AMT):
    sh = 0.0
    inv = 0.0
    eq = np.empty(len(px))
    ci = np.empty(len(px))
    for i, p in enumerate(px):
        sh += amt / p
        inv += amt
        eq[i] = sh * p
        ci[i] = inv
    return eq, ci


def xirr(cfs):
    """cfs: list[(date, amount)]；负=投入，正=收回。二分法。"""
    x0 = dt.date(1900, 1, 1)
    t = np.array([(d - x0).days / 365.25 for d, _ in cfs])
    a = np.array([v for _, v in cfs], dtype=float)
    lo, hi = -0.95, 3.0
    for _ in range(120):
        mid = (lo + hi) / 2.0
        if np.sum(a / (1.0 + mid) ** t) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _leg(t):
    """legs 元素 = (sym, dy, sd) 或 (sym, dy, sd, amt) 或 (sym, dy, sd, amt, ed)
    sd=起投日（None=从头）；amt=每日金额；ed=停止新增投入日（None=投到窗口末）。
    停止投入后仓位继续持有到窗口末 —— 这正是「接力」需要的语义。"""
    return (t[0], t[1], t[2],
            t[3] if len(t) > 3 else AMT,
            t[4] if len(t) > 4 else None)


def build(legs):
    """legs: [(sym, dy, sd[, amt[, ed]])] → 组合日期/市值/累计投入/各腿终值"""
    ser = []
    for leg in legs:
        sym, dy, sd, amt, ed = _leg(leg)
        d, p = make_tr(sym, dy)
        if sd is not None:
            i0 = int(np.searchsorted(d, sd))
            d, p = d[i0:], p[i0:]
        if ed is not None:
            i1 = int(np.searchsorted(d, ed))
            d, p = d[:i1], p[:i1]
        eq, ci = dca(p, amt)
        key = sym
        while key in [s[3] for s in ser]:
            key = key + "*"          # 同一标的出现多条腿时避免覆盖
        ser.append((d.tolist(), eq, ci, key))
    alld = sorted(set().union(*[set(s[0]) for s in ser]))
    tot_eq = np.zeros(len(alld))
    tot_ci = np.zeros(len(alld))
    ends = {}
    for dl, eq, ci, sym in ser:
        m = dict(zip(dl, zip(eq.tolist(), ci.tolist())))
        ve, vc = [], []
        last = None
        for x in alld:
            if x in m:
                last = m[x]
            ve.append(last[0] if last else 0.0)
            vc.append(last[1] if last else 0.0)
        tot_eq += np.array(ve)
        tot_ci += np.array(vc)
        ends[sym] = float(eq[-1])
    return alld, tot_eq, tot_ci, ends


def metrics(alld, eq, ci, cd, cv):
    n = len(alld)
    ratio = np.where(ci > 0, eq / np.where(ci > 0, ci, 1.0), 1.0)
    j = int(np.argmin(ratio))
    # 现金流：每日新增投入（负）+ 期末终值（正）
    dci = np.diff(np.concatenate([[0.0], ci]))
    cfs = [(d, -float(x)) for d, x in zip(alld, dci) if x > 1e-9]
    cfs.append((alld[-1], float(eq[-1])))
    yrs = (alld[-1] - alld[0]).days / 365.25
    inv = float(ci[-1])
    fin = float(eq[-1])
    # 名义投入 ≠ 实际投入：1988 年的 10 元比 2026 年的 10 元值钱得多。
    # 把每一笔投入按 CPI 折成「2026 年购买力」，才是真正掏出去的钱。
    c_now = cpi_at(cd, cv, TODAY)
    real_inv = 0.0
    for d, x in zip(alld, dci):
        if x > 1e-9:
            real_inv += float(x) * c_now / cpi_at(cd, cv, d)
    under = ratio < 1.0
    cur = lng = 0
    for u in under:
        cur = cur + 1 if u else 0
        lng = max(lng, cur)
    return dict(
        start=alld[0].isoformat(), end=alld[-1].isoformat(),
        years=round(yrs, 2), days=n,
        invested=inv, final=fin, multiple=fin / inv,
        xirr=xirr(cfs),
        real_invested=real_inv, real_multiple=fin / real_inv,
        max_dd=float(ratio[j] - 1.0), worst_date=alld[j].isoformat(),
        under_pct=float(under.mean()), longest_under_days=int(lng),
        cpi_factor=real_inv / inv,
    )


def report(tag, legs, cd, cv, note=""):
    alld, eq, ci, ends = build(legs)
    m = metrics(alld, eq, ci, cd, cv)
    print("\n" + "=" * 82)
    print(f"{tag}   {note}")
    print("=" * 82)
    print(f"  窗口 {m['start']} → {m['end']}  ({m['years']} 年, {m['days']} 个交易日)")
    avg_daily = m["invested"] / m["days"]
    print(f"  计息腿 {len(legs)} 条  实际日均投入 {avg_daily:5.2f} 元/交易日  "
          f"≈ 每月 {avg_daily*21:,.0f} 元")
    for leg in legs:
        sym, dy, sd, amt, ed = _leg(leg)
        span = f"{sd or '起始'} → {ed or '今'}"
        print(f"    · {sym:14s} 股息 {dy:6.2%}  {amt:6.2f} 元/日  {span}")
    print(f"  累计投入（名义） {m['invested']:>12,.0f} 元")
    print(f"  折 2026 购买力    {m['real_invested']:>12,.0f} 元   （{m['cpi_factor']:.2f}× —— 早期的钱更值钱）")
    print(f"  期末市值 {m['final']:>14,.0f} 元   = {m['final']/1e4:>8,.1f} 万")
    print(f"  名义倍数 {m['multiple']:>14.2f} ×（账户里看到的）")
    print(f"  实际倍数 {m['real_multiple']:>14.2f} ×（按购买力口径）")
    print(f"  XIRR     {m['xirr']:>14.2%}")
    print(f"  最深浮亏 {m['max_dd']:>14.1%}   （{m['worst_date']}）")
    print(f"  水下占比 {m['under_pct']:>14.1%}   最长连续水下 {m['longest_under_days']/252:.2f} 年")
    print(f"  各腿终值: " + "  ".join(f"{k}={v/1e4:,.1f}万" for k, v in ends.items()))
    m["legs"] = [dict(sym=s, dy=d,
                      start=(x.isoformat() if x else None),
                      end=(e.isoformat() if e else None), amt=a)
                 for s, d, x, a, e in (_leg(l) for l in legs)]
    m["leg_ends"] = {k: v / 1e4 for k, v in ends.items()}
    m["tag"] = tag
    m["note"] = note
    # 年末快照（用于画图）
    ys = {}
    for d, e, c in zip(alld, eq, ci):
        if d.month == 12 and d.day >= 28:
            ys[f"{d.year}"] = dict(e=float(e), c=float(c), ratio=float(e / c) if c else 1.0)
    m["year_snap"] = ys
    key = ["1988", "1990", "1995", "2000", "2002", "2003", "2007", "2008", "2009",
           "2013", "2018", "2020", "2021", "2022", "2024", "2025", "2026"]
    print("  年末快照（市值 / 累计投入 / 倍数）:")
    for y in key:
        if y in ys:
            s = ys[y]
            print(f"    {y}   市值 {s['e']/1e4:9,.1f}万    投入 {s['c']/1e4:8,.1f}万    {s['ratio']:.2f}×")
    hit = {}
    for y in sorted(ys):
        s = ys[y]
        for thr in (1e6, 5e6, 1e7):
            if thr not in hit and s["e"] >= thr:
                hit[thr] = y
    print("  首次突破: " + "  ".join(
        f"{v/1e4:,.0f}万→{hit[v]}年" for v in sorted(hit)) if hit else "  （未突破 100 万）")
    m["first_hit"] = {f"{k/1e4:.0f}万": v for k, v in hit.items()}
    return m


def main():
    cd, cv = load_cpi()
    res = {}

    res["A_three"] = report(
        "场景A · 三腿共同窗口（近 38.7 年）",
        [("IDX_SP500TR", 0.0, dt.date(1988, 1, 4)),
         ("IDX_NDX", 0.007, dt.date(1988, 1, 4)),
         ("IDX_HSI", 0.035, dt.date(1988, 1, 4))],
        cd, cv, "标普500全收益 + 纳指100 + 恒生，各 10 元/日 = 30 元/日")

    res["B_four_510880"] = report(
        "场景B · 四腿错峰（A + 上证红利ETF 从 2007）",
        [("IDX_SP500TR", 0.0, dt.date(1988, 1, 4)),
         ("IDX_NDX", 0.007, dt.date(1988, 1, 4)),
         ("IDX_HSI", 0.035, dt.date(1988, 1, 4)),
         ("510880.SS", 0.0, dt.date(2007, 1, 18))],
        cd, cv, "前 19 年 30 元/日，2007 起 40 元/日")

    res["C_four_sse"] = report(
        "场景C · 四腿错峰（A + 上证综指 从 1990）",
        [("IDX_SP500TR", 0.0, dt.date(1988, 1, 4)),
         ("IDX_NDX", 0.007, dt.date(1988, 1, 4)),
         ("IDX_HSI", 0.035, dt.date(1988, 1, 4)),
         ("000001.SS", 0.02, dt.date(1990, 12, 19))],
        cd, cv, "前 3 年 30 元/日，1990-12 起 40 元/日")

    ext = synth_extended("510880.SS", dt.date(1988, 1, 4))
    res["F_four_40y"] = report(
        "场景F · 四腿各投满 38.7 年（A股红利腿向前延展 18.7 年）",
        [("IDX_SP500TR", 0.0, dt.date(1988, 1, 4)),
         ("IDX_NDX", 0.007, dt.date(1988, 1, 4)),
         ("IDX_HSI", 0.035, dt.date(1988, 1, 4)),
         (ext, 0.0, None)],
        cd, cv, "A股红利腿按实测年化 4.72% 几何延展到 1988 ⇒ 四腿同起点、各 10 元/日")

    # ---- 同样 40 元/日，红利那 10 元「怎么安排」的全部选项
    A_SSE = dt.date(2007, 1, 18)      # 上证红利ETF 起投日 = 接力切换点

    res["G_relay"] = report(
        "场景G · 【用户口径】红利腿接力：A股没数据时跑港股，有了跑A股",
        [("IDX_SP500TR", 0.0, dt.date(1988, 1, 4), 10.0),
         ("IDX_NDX", 0.007, dt.date(1988, 1, 4), 10.0),
         ("IDX_HSI", 0.035, dt.date(1988, 1, 4), 10.0),
         ("IDX_HSI", 0.035, dt.date(1988, 1, 4), 10.0, A_SSE),   # 前 19 年顶替 A股
         ("510880.SS", 0.0, A_SSE, 10.0)],                        # 2007 起接手
        cd, cv, "全程 40 元/日：前 19 年港股红利 20 元/日（A股缺位），2007 起港股红利 10 + A股红利 10")

    res["H_hsi_double"] = report(
        "场景H · 对照：那 10 元全程都给港股（不切回 A股）",
        [("IDX_SP500TR", 0.0, dt.date(1988, 1, 4), 10.0),
         ("IDX_NDX", 0.007, dt.date(1988, 1, 4), 10.0),
         ("IDX_HSI", 0.035, dt.date(1988, 1, 4), 20.0)],
        cd, cv, "全程 40 元/日，恒生含息 20 元/日")

    res["I_even_three"] = report(
        "场景I · 对照：三腿等额（那 10 元平分给三条腿）",
        [("IDX_SP500TR", 0.0, dt.date(1988, 1, 4), 40.0 / 3),
         ("IDX_NDX", 0.007, dt.date(1988, 1, 4), 40.0 / 3),
         ("IDX_HSI", 0.035, dt.date(1988, 1, 4), 40.0 / 3)],
        cd, cv, "全程 40 元/日，三等分每腿 13.33 元/日")

    res["J_us_only"] = report(
        "场景J · 对照：那 10 元全给美股（标普/纳指各 20 元/日）",
        [("IDX_SP500TR", 0.0, dt.date(1988, 1, 4), 20.0),
         ("IDX_NDX", 0.007, dt.date(1988, 1, 4), 20.0)],
        cd, cv, "全程 40 元/日，两条美股腿各 20 元/日")

    # ---- 用户 09-17 02:00 口径：凑齐 5 腿，50 元/日
    A_SSE = dt.date(2007, 1, 18)      # 上证红利ETF 起投日
    A_DVY = dt.date(2003, 11, 7)      # iShares 道指精选红利 起投日

    res["K_five_50"] = report(
        "场景K · 【用户口径】凑齐 5 腿，各 10 元/日 = 50 元/日",
        [("IDX_SP500TR", 0.0, dt.date(1988, 1, 4), 10.0),
         ("IDX_SP500TR", 0.0, dt.date(1988, 1, 4), 10.0, A_DVY),  # 美股红利缺位期顶替
         ("IDX_NDX", 0.007, dt.date(1988, 1, 4), 10.0),
         ("IDX_HSI", 0.035, dt.date(1988, 1, 4), 10.0),
         ("IDX_HSI", 0.035, dt.date(1988, 1, 4), 10.0, A_SSE),    # A股红利缺位期顶替
         ("510880.SS", 0.0, A_SSE, 10.0),
         ("DVY", 0.0, A_DVY, 10.0)],
        cd, cv, "标普500 + 纳指100 + 港股红利 全程；A股红利 2007 起、美股红利(DVY) 2003 起，"
                "缺位期分别由港股红利/标普500 顶替 ⇒ 全程恒定 50 元/日")

    res["L_five_no_us_div"] = report(
        "场景L · 对照：同样 50 元/日，但不要美股红利（钱给标普/纳指/港股红利）",
        [("IDX_SP500TR", 0.0, dt.date(1988, 1, 4), 50.0 / 3),
         ("IDX_NDX", 0.007, dt.date(1988, 1, 4), 50.0 / 3),
         ("IDX_HSI", 0.035, dt.date(1988, 1, 4), 50.0 / 3)],
        cd, cv, "三腿等额，每腿 16.67 元/日")

    res["M_five_no_div"] = report(
        "场景M · 对照：同样 50 元/日，全部砍掉红利，只要美股",
        [("IDX_SP500TR", 0.0, dt.date(1988, 1, 4), 25.0),
         ("IDX_NDX", 0.007, dt.date(1988, 1, 4), 25.0)],
        cd, cv, "标普500 全收益 25 元/日 + 纳指100 25 元/日")

    res["D_ndx_only"] = report(
        "场景D · 纳指100 单腿（近 38.7 年）",
        [("IDX_NDX", 0.007, dt.date(1988, 1, 4))],
        cd, cv, "10 元/日")

    res["E_sp500_only"] = report(
        "场景E · 标普500 全收益 单腿（近 38.7 年）",
        [("IDX_SP500TR", 0.0, dt.date(1988, 1, 4))],
        cd, cv, "10 元/日")

    # ---- 达到名义千万需要什么
    print("\n" + "=" * 82)
    print("要达到「名义千万」需要什么（全部按 40 元/日 基数）")
    print("=" * 82)
    for k in ["A_three", "B_four_510880", "F_four_40y",
              "G_relay", "H_hsi_double", "I_even_three", "J_us_only",
              "K_five_50", "L_five_no_us_div", "M_five_no_div"]:
        if k not in res:
            continue
        m = res[k]
        base = m["invested"] / m["days"]      # 实际日均投入（分段腿已折算）
        scale = 1e7 / m["final"]
        print(f"  {m['tag'][:36]:38s} 终值 {m['final']/1e4:7,.0f}万 "
              f"倍数 {m['multiple']:5.2f}×  ⇒ 投入放大 {scale:4.2f}× "
              f"= 每日 {base*scale:5.1f} 元")

    # ---- 年化对照
    print("\n各腿窗口内年化（几何，含股息）:")
    for sym, dy, sd in [("IDX_SP500TR", 0.0, dt.date(1988, 1, 4)),
                        ("IDX_NDX", 0.007, dt.date(1988, 1, 4)),
                        ("IDX_HSI", 0.035, dt.date(1988, 1, 4)),
                        ("510880.SS", 0.0, dt.date(2007, 1, 18)),
                        ("000001.SS", 0.02, dt.date(1990, 12, 19))]:
        d, p = make_tr(sym, dy)
        i0 = int(np.searchsorted(d, sd))
        d2, p2 = d[i0:], p[i0:]
        yr = (d2[-1] - d2[0]).days / 365.25
        print(f"  {sym:14s} {d2[0]}→{d2[-1]} ({yr:5.1f}y)  "
              f"{p2[-1]/p2[0]:8.2f}×  年化 {(p2[-1]/p2[0])**(1/yr)-1:6.2%}")

    with open(os.path.join(OUT, "real_window_result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=float)
    print(f"\n结果: {os.path.join(OUT, 'real_window_result.json')}")


if __name__ == "__main__":
    main()
