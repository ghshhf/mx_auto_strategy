# -*- coding: utf-8 -*-
"""
export_nav_crypto.py — 加密 NAV 导出 docs/data/nav_crypto.json (数据层)

产出单条序列: 10y cycle(减半相位叠加开启, tilt=0.3), 起点 2016-08-11。

真值口径沿革（2026-09-04 统一，详见 TRUTH_AUTHORITY.md）:
  - 当前权威(本脚本实跑): **7,637.77x** / MDD -69.6% / Sharpe 1.64 / CAGR 142.8%
    （cycle_overlay 口径, 34 币池 + 期权三件套已关闭 + 三面板已修复为真值）
  - reconcile 10y FULL(inv_vol+1.2+周期) 为 8,488x, 与本脚本 cycle_overlay 口径不同, 勿混用
  - 28,092x 为 2026-08 前的旧口径（43 币 + 期权开启），**已废弃，勿再引用**
  - 59,361,202x 同为期权时代数字（见 crypto_options_bt.py 配置注释），已废弃

复用 A股 export_nav.py 窗口逻辑(按日期切 10y/5y/3y/full, 归一化倍数+MDD+CAGR)。

数据为渲染分离: docs/index.html 通过 fetch 读取本文件。
"""
import os, sys, json, datetime as dt
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from crypto_options_bt import run_bt

DATA = os.path.join(HERE, "data")
TENY = os.path.join(DATA, "weekly_adjclose_crypto50_10y.csv")
if not os.path.exists(TENY):
    print(f"[错误] 找不到面板 {TENY}"); sys.exit(1)


def load(path):
    return pd.read_csv(path, index_col=0, parse_dates=True).sort_index()


px = load(TENY)
r = run_bt(px, None, label="10y/cycle", start="2016-08-11", cycle_overlay=True)
nav = r["nav"]  # pd.Series, index=date, name=label
dates = [d.strftime("%Y-%m-%d") for d in nav.index]
nav_vals = [float(x) for x in nav.values]


def compute_window(lo, hi):
    w_dates = dates[lo:hi + 1]
    w_nav = nav_vals[lo:hi + 1]
    n0 = w_nav[0]
    mult = [x / n0 for x in w_nav]
    peak = w_nav[0]
    dd = []
    for x in w_nav:
        peak = max(peak, x)
        dd.append(x / peak - 1.0)
    mdd = min(dd) * 100
    d0 = dt.date.fromisoformat(w_dates[0])
    d1 = dt.date.fromisoformat(w_dates[-1])
    yrs = (d1 - d0).days / 365.25
    cagr = ((w_nav[-1] / n0) ** (1 / yrs) - 1.0) * 100 if yrs > 0 else 0.0
    return dict(dates=w_dates,
                mult=[round(x, 4) for x in mult],
                dd=[round(x, 4) for x in dd],
                stats=dict(final_mult=round(w_nav[-1] / n0, 3), mdd=round(mdd, 1),
                           cagr=round(cagr, 1), n_weeks=len(w_dates),
                           start_d=w_dates[0], end_d=w_dates[-1]))


def lo_for(ny):
    last = len(dates) - 1
    ld = dt.date.fromisoformat(dates[last])
    target = ld.replace(year=ld.year - ny)
    tstr = target.isoformat()
    for i in range(len(dates)):
        if dates[i] >= tstr:
            return i
    return 0


windows = {"full": compute_window(0, len(dates) - 1)}
for ny, tag in [(10, "10y"), (5, "5y"), (3, "3y")]:
    windows[tag] = compute_window(lo_for(ny), len(dates) - 1)

out = dict(
    generated_at=dt.date.today().isoformat(),
    source="加密本地面板(34币, 10y, Binance/OKX/Gate; 三面板已修复对齐, 期权层已关闭)",
    last_date=dates[-1],
    windows={"cycle": windows},
    truth=dict(
        cycle=dict(final_mult=round(r["multiple"], 3),
                   mdd=round(r["mdd"] * 100, 1),
                   cagr=round(r["cagr"] * 100, 1),
                   sharpe=round(r.get("sharpe", 0), 2)),
        note="10y cycle = 减半相位叠加开启(tilt=0.3) 口径, 加密权威真值。base(叠加关)=21,419x。",
    ),
)

OUT_DIR = os.path.join(ROOT, "docs", "data")
os.makedirs(OUT_DIR, exist_ok=True)
OUT = os.path.join(OUT_DIR, "nav_crypto.json")
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

print(f"crypto 10y cycle: {r['multiple']:.2f}x | MDD {r['mdd']*100:.1f}% | CAGR {r['cagr']*100:.1f}% | Sharpe {r.get('sharpe',0):.2f}")
print(f"输出: {OUT} ({os.path.getsize(OUT)} bytes)")
