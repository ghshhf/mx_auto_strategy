# -*- coding: utf-8 -*-
"""
CRV / TRX 轮动回测 (基于真实 Binance/OKX 周线面板 crypto50.csv)
用法: python crypto_rotation_backtest.py

假设(可改下方参数):
- 窗口: 起点 date >= START_DATE, 到数据末行(=今天代理)
- 本金 INIT_CAP, 起始 50/50 (各 INIT_CAP/2)
- 买入持有: 从不交易, 无费用
- 轮动(50/50 再平衡): 任一侧权重偏离目标 > BAND(默认1%)即调回50/50,
  每次调仓对成交金额收 FEE(默认1%)手续费
"""
import csv
import os

CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "weekly_adjclose_crypto50.csv")
START_DATE = "2021-08-05"   # 5年前窗口起点
INIT_CAP = 200.0           # 本金(美元)
FEE = 0.01                 # 每笔调仓手续费率 1%
BAND = 0.01                # 再平衡触发阈值(偏离目标权重 >1%)

def load(sym_a, sym_b):
    with open(CSV_PATH, newline='', encoding='utf-8-sig') as fh:
        r = csv.reader(fh); header = next(r); rows = list(r)
    ia, ib = header.index(sym_a), header.index(sym_b)
    series = []
    for row in rows:
        if row[0] < START_DATE:
            continue
        va, vb = row[ia], row[ib]
        if va in ("", None) or vb in ("", None):
            continue
        series.append((row[0], float(va), float(vb)))
    return series

def main():
    S = load("CRV", "TRX")
    dates = [x[0] for x in S]
    pC = [x[1] for x in S]
    pT = [x[2] for x in S]
    n = len(S)
    print(f"面板: {CSV_PATH}")
    print(f"窗口: {dates[0]} ~ {dates[-1]}  ({n} 周, 约 {n/52:.1f} 年)")
    print(f"起点价 CRV=${pC[0]:.4f}  TRX=${pT[0]:.4f}   终点价 CRV=${pC[-1]:.4f}  TRX=${pT[-1]:.4f}")
    print(f"本金 ${INIT_CAP:.0f} = CRV ${INIT_CAP/2:.0f} + TRX ${INIT_CAP/2:.0f}\n")

    half = INIT_CAP / 2.0
    ratioC = pC[-1] / pC[0]
    ratioT = pT[-1] / pT[0]
    bh_crv = half * ratioC
    bh_trx = half * ratioT
    bh_total = bh_crv + bh_trx
    print("【场景A】买入持有 50/50 (无费用, 从不交易)")
    print(f"  CRV: ${half:.0f} -> ${bh_crv:.2f}  ({ratioC:+.1%})")
    print(f"  TRX: ${half:.0f} -> ${bh_trx:.2f}  ({ratioT:+.1%})")
    print(f"  合计: ${INIT_CAP:.0f} -> ${bh_total:.2f}  (倍数 {bh_total/INIT_CAP:.2f}x)\n")

    # 轮动: 50/50 再平衡, 漂移>BAND 调回, 每笔 FEE
    vC, vT = half, half
    rebal = 0
    fees = 0.0
    for t in range(1, n):
        vC *= pC[t] / pC[t-1]
        vT *= pT[t] / pT[t-1]
        total = vC + vT
        wC = vC / total
        if abs(wC - 0.5) > BAND:
            traded = abs(vC - total / 2.0)
            fee = traded * FEE
            total -= fee
            vC = vT = total / 2.0
            rebal += 1
            fees += fee
    rot_total = vC + vT
    print(f"【场景B】轮动 50/50 再平衡 (阈值>BAND={BAND:.0%}, 费率{FEE:.0%})")
    print(f"  再平衡次数: {rebal}  累计手续费: ${fees:.2f}")
    print(f"  合计: ${INIT_CAP:.0f} -> ${rot_total:.2f}  (倍数 {rot_total/INIT_CAP:.2f}x)\n")

    # 单币持有参考
    print("【参考】单币买入持有")
    print(f"  全仓 CRV: ${INIT_CAP:.0f} -> ${INIT_CAP*ratioC:.2f}  ({ratioC:+.1%})")
    print(f"  全仓 TRX: ${INIT_CAP:.0f} -> ${INIT_CAP*ratioT:.2f}  ({ratioT:+.1%})")

    print(f"\n结论: 5年窗口内 TRX 是持续赢家(约{ratioT:.1f}x), CRV 缩水约{abs(ratioC):.0%}。"
          f" 50/50再平衡轮动因持续卖出TRX买CRV且叠加1%费率, "
          f"({rot_total/INIT_CAP:.2f}x) 低于买入持有({bh_total/INIT_CAP:.2f}x)。"
          f" 若要碾压, 需改用动量轮动(追强币)而非50/50再平衡。")

if __name__ == "__main__":
    main()
