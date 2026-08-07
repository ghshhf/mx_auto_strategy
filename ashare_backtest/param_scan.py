"""A股主引擎 参数稳健性扫描 (v6.18 诚实基线)。

目的: 验证头条 18.185x 不是 momentum_lookback=26 的 cherry-pick。
方法: 在 v6.18 诚实基线(use_tech=False + trend_filter=False + 核心卫星 + 死叉 + 交易成本)下,
      扫 momentum_lookback ∈ {13,18,21,26,34,43,52}, 看倍数/MDD/CAGR 是否稳定。
数据: 腾讯后复权面板 (data/ashare_panel_close_em.csv), 与权威真值同源。

输出: 打印表格 + 写 data/param_scan.csv (gitignore, 仅本地产物)。
结论判据: 若 18.185x(lookback=26) 落在各参数结果的紧凑区间中央 → 非 cherry-pick, 策略可信;
          若 lookback=26 异常突出 → 疑似过拟合单点, 需回调预期。
"""
import os, sys, csv
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from backtest_engine import run

PANEL = os.path.join(HERE, 'data', 'ashare_panel_close_em.csv')
GRID = [13, 18, 21, 26, 34, 43, 52]


def main():
    rows = []
    print(f"{'lookback':>9} {'倍数':>10} {'CAGR':>8} {'MDD':>9} {'HS300':>8} {'超额':>9} {'周数':>6}")
    print('-' * 62)
    for lb in GRID:
        s, _, _, _ = run(
            offense_mode='momentum', momentum_lookback=lb,
            use_tech=False, trend_filter=False,
            core_satellite=True, core_frac=0.5, death_cross=True,
            costs=True, use_core_sub=True, panel_path=PANEL,
        )
        fm = s['final_multiple']; cagr = s['cagr']; mdd = s['mdd']
        hs = s['hs300_multiple']; exc = s['excess_vs_hs300']; wk = s['weeks']
        print(f"{lb:>9} {fm:>9.3f}x {cagr:>7.1f}% {mdd:>8.1f}% {hs:>7.2f}x {exc:>8.2f}x {wk:>6}")
        rows.append(dict(lookback=lb, mult=round(fm, 3), cagr=round(cagr, 2),
                         mdd=round(mdd, 2), hs300=round(hs, 3),
                         excess=round(exc, 3), weeks=wk))
    # 稳定性摘要
    mults = [r['mult'] for r in rows]
    mdds = [r['mdd'] for r in rows]
    print('-' * 62)
    print(f"倍数区间: {min(mults):.3f}x ~ {max(mults):.3f}x  (跨度 {max(mults)-min(mults):.3f}x)")
    print(f"MDD区间:  {min(mdds):.1f}% ~ {max(mdds):.1f}%")
    base = next(r for r in rows if r['lookback'] == 26)
    print(f"基线 lookback=26: {base['mult']:.3f}x / MDD {base['mdd']:.1f}%")
    if min(mults) <= base['mult'] <= max(mults):
        print("结论: lookback=26 落在扫描区间内 → 非 cherry-pick, 策略对参数选择不敏感。")
    else:
        print("结论: lookback=26 偏离扫描区间 → 疑似过拟合, 需回调预期。")

    out = os.path.join(HERE, 'data', 'param_scan.csv')
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['lookback', 'mult', 'cagr', 'mdd', 'hs300', 'excess', 'weeks'])
        w.writeheader(); w.writerows(rows)
    print(f"\n已写 {out}")


if __name__ == '__main__':
    main()
