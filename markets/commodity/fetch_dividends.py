# -*- coding: utf-8 -*-
"""抓取分红历史 → 量化"未复权 close" 对 CAGR 的低估幅度。
用户指出: 1)股票未复权→CAGR低估(分红); 2)ETF也除息+扣管理费→同样低估。
本脚本: 对候选池抓 dividendhistory.org 分红, 算股息率, 估算真实CAGR修正量。
"""
import requests, pandas as pd, io, time, re, numpy as np

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
PROX = {"http": "http://127.0.0.1:3067", "https": "http://127.0.0.1:3067"}

# 用户口径池中的美股(Twelve Data 抓的未复权); 港股已hfq复权故跳过
SYMS = ["AMD","MU","STX","WDC","ON","ENTG","RCL","BIDU","TCOM","FSLR","WLDN"]

panel = pd.read_csv("data/us_universe_weekly_adjclose.csv", index_col=0, parse_dates=True)
panel = panel.apply(pd.to_numeric, errors='coerce')

def parse_div(sym):
    """返回 [(date, amount)] 或 None"""
    try:
        r = requests.get(f"https://dividendhistory.org/payout/{sym}/", headers=UA, proxies=PROX, timeout=30)
        tabs = pd.read_html(io.StringIO(r.text))
        for t in tabs:
            cols = [str(c) for c in t.columns]
            if any("Ex-Dividend" in c for c in cols) and any("Cash Amount" in c for c in cols):
                dcol = [c for c in t.columns if "Ex-Dividend" in str(c)][0]
                acol = [c for c in t.columns if "Cash Amount" in str(c)][0]
                out = []
                for _, row in t.iterrows():
                    try:
                        d = pd.to_datetime(row[dcol])
                    except Exception:
                        continue
                    m = re.search(r"[\d.]+", str(row[acol]))
                    if not m: continue
                    amt = float(m.group())
                    # 排除预估(未来)
                    if d > pd.Timestamp.today(): continue
                    out.append((d, amt))
                return out
        return None
    except Exception as e:
        return None

print(f"{'标的':<7}{'分红记录':>8}{'近年每股年分红':>14}{'现价':>10}{'股息率':>9}{'CAGR低估':>10}")
print("-"*62)
rows = []
for s in SYMS:
    if s not in panel.columns:
        print(f"{s:<7} 不在面板"); continue
    px = panel[s].dropna()
    if len(px) < 60:
        print(f"{s:<7} 数据不足"); continue
    last_px = float(px.iloc[-1])
    dv = parse_div(s)
    if not dv:
        print(f"{s:<7}{'无/未抓到':>8}{'-':>14}{last_px:>10.1f}{'0.0%':>9}{'~0.0pp':>10}   (大概率不分红)")
        rows.append(dict(sym=s, n_div=0, ann_div=0.0, yield_pct=0.0))
        time.sleep(1.5)
        continue
    df = pd.DataFrame(dv, columns=["date","amt"]).sort_values("date")
    # 近3年每股年分红
    recent = df[df.date >= pd.Timestamp.today() - pd.Timedelta(days=365*3)]
    yrs = max(1.0, (recent.date.max()-recent.date.min()).days/365.25) if len(recent)>1 else 1.0
    ann = float(recent.amt.sum()/yrs) if len(recent) else float(df.tail(4).amt.sum())
    yld = ann/last_px*100
    print(f"{s:<7}{len(df):>8}{ann:>14.2f}{last_px:>10.1f}{yld:>8.2f}%{yld:>9.2f}pp")
    rows.append(dict(sym=s, n_div=len(df), ann_div=ann, yield_pct=yld))
    time.sleep(1.5)

r = pd.DataFrame(rows)
r.to_csv("data/dividend_yields.csv", index=False, encoding="utf-8-sig")
print(f"\n平均股息率 {r.yield_pct.mean():.2f}%  → 未复权 close 对 CAGR 的平均低估 ≈ {r.yield_pct.mean():.2f}pp/年")
print(f"有分红标的 {int((r.n_div>0).sum())}/{len(r)}, 不分红(低估≈0) {int((r.n_div==0).sum())} 个")
print("已存 data/dividend_yields.csv")
