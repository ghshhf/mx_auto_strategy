# -*- coding: utf-8 -*-
"""
etf_fund_flow.py
================
A 股「绝对资金流」数据层 + 板块资金流向报告（AkShare 升级版）。

数据源(已实测 2026-08-14):
  - akshare.fund_etf_spot_em  (主源): 一次性返回全部 ~1576 只 ETF 的
        ['最新份额'(份), '主力净流入-净额'(元), '成交额'(元), '涨跌幅', '最新价', '总市值']
        -> 真·绝对资金流(当日全市场截面)，一次调用覆盖全市场，比分页 push2delay 强得多。
  - push2delay.eastmoney.com  (兜底): 当 akshare 不可用时，分页拉 ETF 快照(f38份额/f62主力/f20规模)。
  - 腾讯 web.ifzq.gtimg.cn   : ETF 后复权日K -> 相对资金流 RS(自顶以来涨跌, 完整历史)。
  - 东财 push2his(历史资金流日K) 本沙箱被限，已验证不可用 -> 改用「每日累积最新份额」攒历史。

设计:
  - compute_flow() 返回计算结果(供 ashare_cycle_system 总入口复用)。
  - 每次运行把当日 最新份额 / 主力净流入 写入本地累积缓存，日积月累自动生成历史序列；
    未来可直接算「自顶以来 ETF 份额净申购(=绝对资金净流入代理)」。
  - 与 capital_rotation 的 RS(价格口径)交叉，回答「退潮后钱去哪了：真流出 vs 换板块」。

输出: records/<日期>_绝对资金流与轮动.md
"""
import os
import sys
import json
import time
import datetime
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
import sector_universe as su
import analog_core as ac   # 复用 fetch_long 及其本地缓存
import data_store         # 本地 + GitHub 双缓存数据层

TECH_TOP = "2026-06-30"    # 科技脉冲顶锚点(半导体/通信/芯片 06-30 见顶)

try:
    import akshare as ak
    AK_OK = True
except Exception:
    AK_OK = False


# --------------------------------------------------------------------------
# 网络(兜底源)
# --------------------------------------------------------------------------
def http_get(url, tries=4, timeout=15):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer": "https://quote.eastmoney.com/", "Accept": "*/*"})
            return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(0.8 * (i + 1))


# --------------------------------------------------------------------------
# 数据源 A：AkShare 全量 ETF 实时(主源)
# --------------------------------------------------------------------------
def get_spot_akshare():
    """fund_etf_spot_em -> {code: dict(name,price,chg,amount,shares,main_net,scale)} , data_date"""
    df = ak.fund_etf_spot_em()
    out = {}
    for _, r in df.iterrows():
        try:
            c = str(r.get("代码"))
            if not c:
                continue
            def fnum(col):
                v = r.get(col)
                try:
                    if v is None or (isinstance(v, float) and v != v):
                        return None
                    return float(v)
                except Exception:
                    return None
            out[c] = {
                "name": r.get("名称"),
                "price": fnum("最新价"),
                "chg": fnum("涨跌幅"),
                "amount": fnum("成交额"),
                "shares": fnum("最新份额"),
                "main_net": fnum("主力净流入-净额"),
                "scale": fnum("总市值"),
            }
        except Exception:
            continue
    dd = None
    if "数据日期" in df.columns and len(df):
        try:
            dd = str(df["数据日期"].iloc[0])[:10]
        except Exception:
            dd = None
    return out, dd


# --------------------------------------------------------------------------
# 数据源 B：push2delay 分页(兜底)
# --------------------------------------------------------------------------
def get_spot_push2delay():
    out = {}
    pn = 1
    while True:
        url = ("https://push2delay.eastmoney.com/api/qt/clist/get?pn=%d&pz=100&po=1&np=1"
               "&fltt=2&invt=2&fid=f20&fs=b:MK0021&fields=f12,f14,f20,f38,f62" % pn)
        j = json.loads(http_get(url))
        diff = (j.get("data") or {}).get("diff") or []
        if not diff:
            break
        for d in diff:
            c = d.get("f12")
            if not c:
                continue
            out[c] = {"name": d.get("f14"), "shares": d.get("f38"),
                      "main_net": d.get("f62"), "scale": d.get("f20")}
        if len(diff) < 100:
            break
        pn += 1
        if pn > 25:
            break
        time.sleep(0.08)
    return out, None


# --------------------------------------------------------------------------
# 价格指标(相对资金流)
# --------------------------------------------------------------------------
def ret_back(bars, n):
    if len(bars) <= n:
        return None
    return bars[-1]["c"] / bars[-1 - n]["c"] - 1


def rs_since(bars, top_date):
    idx = 0
    for i, b in enumerate(bars):
        if b["d"] <= top_date:
            idx = i
        else:
            break
    base = bars[idx]["c"]
    return bars[-1]["c"] / base - 1, bars[idx]["d"]


# --------------------------------------------------------------------------
# 累积缓存
# --------------------------------------------------------------------------
def load_accum():
    return data_store.load_flow()


def save_accum(accum):
    data_store.save_flow(accum)


# --------------------------------------------------------------------------
# 判定
# --------------------------------------------------------------------------
def verdict(rs, mt):
    if rs is None or mt is None:
        return "数据不足"
    if rs > 0.03 and mt > 0:
        return "真承接▲(涨且净流入)"
    if rs > 0.03 and mt <= 0:
        return "拉高出货?(涨但净流出)"
    if rs <= -0.03 and mt > 0:
        return "低位吸筹(跌但净流入)"
    if rs <= -0.03 and mt <= 0:
        return "真撤退▼(跌且净流出)"
    return "观望/中性"


# --------------------------------------------------------------------------
# 计算核心
# --------------------------------------------------------------------------
def compute_flow(verbose=False):
    """返回 (sec_stat, rows, snap, src_label, today, accum_dates)。"""
    today = datetime.date.today().strftime("%Y%m%d")

    snap, data_date = (get_spot_akshare() if AK_OK else (None, None))
    src = "akshare.fund_etf_spot_em"
    if not snap:
        snap, data_date = get_spot_push2delay()
        src = "push2delay(兜底)"
    if verbose:
        print(f"主源: {src} | 快照 ETF 数: {len(snap)} | 数据日期: {data_date}", file=sys.stderr)
        want = [code for _, _, code, _ in su.iter_etfs()]
        missing = [c for c in want if c not in snap]
        print(f"覆盖 {len(want)-len(missing)}/{len(want)} 行业ETF; 缺失: {missing}", file=sys.stderr)

    # 全市场 ETF 主力净流入合计(流动性总闸)
    mkt_main = sum((s.get("main_net") or 0) for s in snap.values() if s.get("main_net") is not None)

    accum = load_accum()
    dayflow = {}
    for c, s in snap.items():
        dayflow[c] = {"s": s.get("shares"), "m": s.get("main_net")}
    accum[today] = dayflow
    save_accum(accum)
    dates = sorted(accum.keys())
    if verbose and len(dates) > 1:
        print(f"累积历史天数: {len(dates)} ({dates[0]} ~ {dates[-1]})", file=sys.stderr)

    rows = []
    for s1, s2, code, name in su.iter_etfs():
        s = snap.get(code)
        main_today = s.get("main_net") if s else None
        shares = s.get("shares") if s else None
        scale = s.get("scale") if s else None
        price = s.get("price") if s else None
        chg = s.get("chg") if s else None
        try:
            bars = ac.fetch_long(code)
        except Exception:
            bars = None
        if not bars:
            rows.append((s1, s2, code, name, None, None, None, main_today, shares, scale, price, chg, None, None))
            continue
        rs, anchor = rs_since(bars, TECH_TOP)
        r20 = ret_back(bars, 20)
        r60 = ret_back(bars, 60)
        # 份额净申购(历史累积代理): 当前份额 - 累积起始日份额
        sub_rate = None
        if len(dates) >= 2 and shares is not None:
            first = None
            for d in dates:
                v = accum[d].get(code, {}).get("s")
                if v is not None:
                    first = v
                    break
            if first:
                sub_rate = shares / first - 1
        rows.append((s1, s2, code, name, rs, r20, r60, main_today, shares, scale, price, chg, sub_rate, anchor))
        time.sleep(0.03)

    # 聚合到一级板块
    sec = {}
    for s1, s2, code, name, rs, r20, r60, mt, share, scale, price, chg, sub_rate, anchor in rows:
        if rs is None:
            continue
        d = sec.setdefault(s1, {"rs": [], "r20": [], "r60": [], "mt": [], "scale": [], "sub": []})
        d["rs"].append(rs)
        if r20 is not None: d["r20"].append(r20)
        if r60 is not None: d["r60"].append(r60)
        if mt is not None: d["mt"].append(mt)
        if scale is not None: d["scale"].append(scale)
        if sub_rate is not None: d["sub"].append(sub_rate)

    def avg(lst):
        return sum(lst) / len(lst) if lst else 0.0

    sec_stat = []
    for s1, d in sec.items():
        sec_stat.append({
            "s1": s1, "rs": avg(d["rs"]), "r20": avg(d["r20"]), "r60": avg(d["r60"]),
            "mt": avg(d["mt"]), "mt_sum": sum(d["mt"]), "scale": sum(d["scale"]),
            "sub": avg(d["sub"]) if d["sub"] else None,
        })
    return sec_stat, rows, snap, src, today, dates, mkt_main


# --------------------------------------------------------------------------
# 报告
# --------------------------------------------------------------------------
def pct(x):
    return f"{x*100:+.1f}%" if isinstance(x, (int, float)) else "—"

def yi(x):
    if x is None:
        return "—"
    return f"{x/1e8:+.1f}亿"

def wan(x):
    if x is None:
        return "—"
    return f"{x/1e4:+.0f}万"


def main():
    sec_stat, rows, snap, src, today, dates, mkt_main = compute_flow(verbose=True)

    L = []
    L.append(f"# A股绝对资金流与板块轮动（{today}）\n")
    L.append("> 数据口径：绝对资金流 = ETF **主力净流入额(元)**，来自 AkShare `fund_etf_spot_em` 当日全市场截面"
             "（一次调用覆盖全部 ~1576 只 ETF；并写入本地累积缓存，日积月累生成历史序列）。"
             "相对资金流(RS) = 自科技脉冲顶 **%s** 以来的价格涨跌（腾讯后复权，完整历史）。\n" % TECH_TOP)
    L.append(f"> **主数据源：{src} | 全市场 ETF 今日主力净流入合计：{yi(mkt_main)}**"
             f"（正=整体净买入，负=整体净卖出；这是比 43 只样本更完整的市场流动性总闸）\n")

    L.append("## 一、绝对资金流 · 当日截面（板块主力净流入合计）\n")
    L.append("> 真·今天有多少钱净买入/净卖出该板块 ETF（元，汇总到一级板块）。\n")
    L.append("| 一级板块 | 今日主力净流入 | 当前规模 | 自顶RS | 交叉判定 |")
    L.append("|---|---|---|---|---|")
    for st in sorted(sec_stat, key=lambda x: (x["mt_sum"] or 0), reverse=True):
        L.append(f"| {st['s1']} | {yi(st['mt_sum'])} | {yi(st['scale'])} | {pct(st['rs'])} | {verdict(st['rs'], st['mt_sum'])} |")
    L.append(f"\n**全市场行业ETF 今日主力净流入合计：{yi(mkt_main)}**（正=整体净买入，负=整体净卖出）\n")

    L.append("## 二、相对资金流 · 自顶以来价格涨跌（RS，完整历史）\n")
    L.append("> 钱“换板块”的镜像：哪个板块自科技顶以来涨了（承接）、哪个跌了（被弃）。\n")
    L.append("| 一级板块 | 自顶RS | 近20日 | 近60日 |")
    L.append("|---|---|---|---|")
    for st in sorted(sec_stat, key=lambda x: x["rs"], reverse=True):
        L.append(f"| {st['s1']} | {pct(st['rs'])} | {pct(st['r20'])} | {pct(st['r60'])} |")

    L.append("\n## 三、交叉结论：退潮后钱去哪了？\n")
    inflow = [s for s in sec_stat if (s["mt_sum"] or 0) > 0 and s["rs"] > 0]
    outflow = [s for s in sec_stat if (s["mt_sum"] or 0) < 0 and s["rs"] < 0]
    hedge = [s for s in sec_stat if s["rs"] > 0.03 and (s["mt_sum"] or 0) <= 0]
    L.append(f"- **真承接（涨+今日净流入）板块**：{', '.join(x['s1'] for x in inflow) or '无'}")
    L.append(f"- **真撤退（跌+今日净流出）板块**：{', '.join(x['s1'] for x in outflow) or '无'}")
    L.append(f"- **拉高出货嫌疑（涨但今日净流出）板块**：{', '.join(x['s1'] for x in hedge) or '无'}")
    L.append("")
    L.append("**多空立场（仅呈现市场视角，非交易指令）：**")
    fin_names = "、".join(x["s1"] for x in inflow) or "无"
    out_names = "、".join(x["s1"] for x in outflow) or "无"
    hed_names = "、".join(x["s1"] for x in hedge) or "无"
    L.append(f"- **空方（退潮/收割延续）**：真撤退板块（跌且净流出）为 {out_names}；"
             "若这些板块持续净流出，说明高位/弱势品种的钱在真撤离，退潮未止。")
    L.append(f"- **多方（换板块承接）**：真承接板块（涨且净流入）为 {fin_names}；"
             "资金从科技切向低位价值/困境反转，是“换板块”而非“真流出”，市场结构性仍活跃。")
    L.append(f"- **中性推演（警惕假突破）**：拉高出货嫌疑板块（涨但净流出）为 {hed_names}；"
             "绝对资金流截面需结合多日累积才能定趋势；当前单日读数更像“退潮期轮动”，"
             "即总量未明显离场，但在板块间剧烈再分配。")

    if len(dates) >= 2:
        L.append("\n## 四、ETF 份额净申购（累积历史，绝对资金净流入代理）\n")
        L.append(f"> 本地累积 {len(dates)} 天（{dates[0]} ~ {dates[-1]}）的「最新份额」变化 = 净申购率。"
                 "份额持续增长即真·资金净流入（配置型），比日内主力净额更稳健。\n")
        L.append("| 一级板块 | 份额净申购(自积累起始) |")
        L.append("|---|---|")
        for st in sorted(sec_stat, key=lambda x: (x["sub"] or -9), reverse=True):
            L.append(f"| {st['s1']} | {(pct(st['sub']) if st['sub'] is not None else '积累中')} |")

    L.append("\n## 诚实声明\n")
    L.append("- 绝对资金流今日为**当日全市场截面**（主源 AkShare `fund_etf_spot_em`；东财历史资金流 push2his 在本环境被限）。"
             "本脚本每次运行会把当日「最新份额 / 主力净流入」写入 `markets/ashare/data/ashare/flow/etf_flow_accum.json`(随仓库提交到 GitHub)，"
             "**日积月累后自动生成历史累计序列**，届时可直接算“自顶以来净申购/净流”。")
    L.append("- RS（价格涨跌）为完整历史口径，已验证稳。两者结合是「相对+绝对」双重验证。")
    L.append("- 主力净流入为二级市场日内资金方向，含交易型资金；长期配置资金应以 ETF 份额净申购为准（同接口「最新份额」，已采集待累积）。")
    L.append("- 单日资金流是噪音（见 wb-finance-skill fund-flow 框架）：趋势性/连续性才有配置意义，需多日累积后复盘。")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "records")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{today}_绝对资金流与轮动.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print("\n=== 板块今日主力净流入(合计) ===", file=sys.stderr)
    for st in sorted(sec_stat, key=lambda x: (x["mt_sum"] or 0), reverse=True):
        print(f"  {st['s1']:10s} {yi(st['mt_sum'])}  RS={pct(st['rs'])}", file=sys.stderr)
    print(f"\n全市场ETF今日主力净流入合计: {yi(mkt_main)}", file=sys.stderr)
    print(f"报告已生成: {out_path}", file=sys.stderr)
    return out_path


if __name__ == "__main__":
    main()
