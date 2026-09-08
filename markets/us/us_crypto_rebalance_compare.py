"""加密 27币 vs 美股多池 — 再平衡超额对照 (回应用户: 美股是否也有肉)。

汇总 crypto_account_nav / us_rebalance_quant 的结论为一张对照表。
加密数据: 直接调 crypto 侧已算结果或重算公平窗满配。
"""
import os
import sys
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))

# --- 读美股 v2 结果 ---
import pandas as pd
us_df = pd.read_csv(os.path.join(HERE, "data", "us_rebalance_quant.csv"))

print("=" * 88)
print(f"{'池子':<32}{'窗口':>7}{'波动':>7}{'相关':>6}{'死拿CAGR':>10}{'再平衡CAGR':>12}{'超额pp/y':>10}")
print("=" * 88)
for _, r in us_df.iterrows():
    print(f"{r['tag']:<32}{r['yrs']:>6.1f}y{r['vol']:>7.1f}%{r['corr']:>6.2f}"
          f"{r['hold_cagr']:>+9.1f}%{r['rebal_cagr']:>+11.1f}%{r['excess_pp_y']:>+10.2f}")

# --- 加密 公平窗 满配 (从 crypto_account_nav 导出的 CSV 汇总) ---
cr = pd.read_csv(os.path.join(HERE, "..", "crypto", "data", "account_nav_13coin.csv"))
HOLD13 = 10.1  # 13币等权死拿 (crypto_account_nav 输出)
print(f"{'加密·13老币 等权死拿':<32}{6.06:>6.1f}y{'15.6':>7}%{'':>6}"
      f"{((HOLD13**(1/6.06)-1)*100):>+9.1f}%{'':>12}")
for mode, lbl in [("quad4", "加密·13老币 4币×3满配"), ("pair2", "加密·13老币 2币×6满配")]:
    s = cr.loc[cr["mode"] == mode, "nav"].sort_values()
    med = float(s.iloc[len(s) // 2])
    yrs = 6.06
    cagr = (med ** (1 / yrs) - 1) * 100
    print(f"{lbl:<32}{yrs:>6.1f}y{'15.6':>7}%{'':>6}"
          f"{((HOLD13**(1/yrs)-1)*100):>+9.1f}%{cagr:>+11.1f}%{cagr-(HOLD13**(1/yrs)-1)*100:>+10.2f}")
