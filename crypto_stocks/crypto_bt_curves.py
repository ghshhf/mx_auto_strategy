"""
crypto_bt_curves.py - 10y 回测 NAV 曲线 (PNG, 避免 HTML 白屏)
三种模式:
  base      : 含期权层 (enabled_call + enabled_short 默认开)
  no_option : 纯现货层 (enabled_call=False + enabled_short=False, 仅现货多头 + 减半减仓)
  BTC       : 买入持有基准
输出: crypto_bt_curves.png (对数 NAV + 回撤子图)
"""
import sys, json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

sys.path.insert(0, ".")
from crypto_options_bt import run_bt

TENY = "data/weekly_adjclose_crypto50_10y.csv"
START = "2016-08-11"

# ---- 读面板 + BTC 基准 ----
px = pd.read_csv(TENY, index_col=0, parse_dates=True).sort_index()
px = px[px.index >= pd.Timestamp(START)]
btc = px["BTC"].copy()

def safe_nav(r):
    nav = r["nav"].copy()
    nav = nav[nav > 0]
    return nav

# base 含期权
r_base = run_bt(px, None, label="base", start=START, cycle_overlay=False)
# 关闭期权: 纯现货
r_no = run_bt(px, {"enabled_call": False, "enabled_short": False},
              label="no_option", start=START, cycle_overlay=False)

nav_base = safe_nav(r_base)
nav_no = safe_nav(r_no)
# BTC 基准 = BTC 归一化到起点=1
btc_nav = (btc / btc.iloc[0]).iloc[btc.index >= nav_base.index[0]]

def metrics(nav):
    mult = float(nav.iloc[-1]) / float(nav.iloc[0])
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = (mult ** (1 / yrs) - 1) * 100 if yrs > 0 else 0
    peak = nav.cummax()
    dd = nav / peak - 1
    mdd = dd.min() * 100
    ret = nav.pct_change().dropna()
    sharpe = (ret.mean() / ret.std() * np.sqrt(52)) if ret.std() > 0 else 0
    return mult, cagr, mdd, sharpe

mb, cb, db, sb = metrics(nav_base)
mn, cn, dn, sn = metrics(nav_no)
mbtc = float(btc_nav.iloc[-1]) / float(btc_nav.iloc[0])

# ---- 绘图 ----
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                                gridspec_kw={"height_ratios": [3, 1]})

ax1.plot(nav_base.index, nav_base.values, label=f"With Options {mb:.0f}x", color="#d62728", lw=1.6)
ax1.plot(nav_no.index, nav_no.values, label=f"Spot Only (Options Off) {mn:.0f}x", color="#1f77b4", lw=1.6)
ax1.plot(btc_nav.index, btc_nav.values, label=f"BTC Hold {mbtc:.0f}x", color="#7f7f7f", lw=1.2, ls="--")
ax1.set_yscale("log")
ax1.set_ylabel("NAV (log scale)")
ax1.set_title("Crypto 10y Backtest NAV (2016-08 ~ 2026-08, 40-coin panel)")
ax1.grid(True, which="both", alpha=0.3)
ax1.legend(loc="upper left")
ax1.yaxis.set_major_formatter(mticker.ScalarFormatter())

# 回撤子图
def dd_series(nav):
    return nav / nav.cummax() - 1
dd_base = dd_series(nav_base)
dd_no = dd_series(nav_no)
ax2.fill_between(dd_base.index, dd_base.values * 100, 0, color="#d62728", alpha=0.3)
ax2.fill_between(dd_no.index, dd_no.values * 100, 0, color="#1f77b4", alpha=0.3)
ax2.set_ylabel("Drawdown %")
ax2.set_ylim(-50, 5)
ax2.grid(True, alpha=0.3)
ax2.axhline(-31.3, color="#999", ls=":", lw=0.8)

plt.tight_layout()
out = "reports/crypto_bt_curves.png"
plt.savefig(out, dpi=130)
print("saved", out)

# 指标输出
result = {
    "base": {"multiple": round(mb, 1), "cagr": round(cb, 1), "mdd": round(db, 1), "sharpe": round(sb, 2)},
    "no_option": {"multiple": round(mn, 1), "cagr": round(cn, 1), "mdd": round(dn, 1), "sharpe": round(sn, 2)},
    "btc": {"multiple": round(mbtc, 1)},
}
print(json.dumps(result, ensure_ascii=False, indent=2))
with open("reports/crypto_bt_curves.json", "w") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
