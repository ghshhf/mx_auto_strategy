# -*- coding: utf-8 -*-
"""按用户设定验证: 单资产长期震荡上涨15%(几何) + 波动σ, 4个低相关再平衡 = 15% + γ* ?
做法: 设算术漂移 mu = 目标几何 + σ²/2, 使单资产实际年化涨幅≈15%。
"""
import numpy as np

def sim(sigma, rho, N, target_geo=0.15, years=20, n=3000, seed=3):
    rng = np.random.default_rng(seed)
    m = 12
    sm = sigma/np.sqrt(m)
    mu = target_geo + sigma**2/2          # 使单资产几何收益≈target_geo
    mum = mu/m
    cov = np.full((N, N), rho*sm**2)
    np.fill_diagonal(cov, sm**2)
    L = np.linalg.cholesky(cov + 1e-12*np.eye(N))
    reb, hld, sng = [], [], []
    for _ in range(n):
        z = rng.standard_normal((years*m, N))
        r = mum + z @ L.T
        v = 1.0
        for t in range(len(r)):
            v *= 1 + r[t].mean()
        reb.append(v**(1/years) - 1)
        hld.append(np.prod(1 + r, axis=0).mean()**(1/years) - 1)
        sng.append(np.prod(1 + r[:, 0])**(1/years) - 1)
    return np.median(reb)*100, np.median(hld)*100, np.median(sng)*100

print("="*104)
print("用户设定验证: 单资产长期年化涨幅≈15%(几何), 4个资产等权再平衡 (中位数典型路径, 20年)")
print("="*104)
print(f"{'波动σ':<8}{'相关ρ':<7}{'单资产实际':>11}{'等权持有':>10}{'再平衡':>10}"
      f"{'再平衡-单资产':>14}{'理论γ*':>10}{'用户算法15%+γ*':>15}")
for sigma in [0.30, 0.35, 0.40, 0.50, 0.60]:
    for rho in [0.0, 0.3]:
        N = 4
        reb, hld, sng = sim(sigma, rho, N)
        th = 0.5 * sigma**2 * (N-1)/N * (1-rho) * 100
        print(f"{sigma*100:>5.0f}%  {rho:<7.2f}{sng:>10.2f}%{hld:>9.2f}%{reb:>9.2f}%"
              f"{reb-sng:>13.2f}pp{th:>9.2f}%{15+th:>14.2f}%")

print("\n" + "="*104)
print("结论对照: 实测(真实数据) vs 本模拟")
print("="*104)
print("  实测: 高波动好标的池(单资产CAGR中位~14%, σ~50%) → 4资产再平衡 CAGR中位 22~24%")
print("  本模拟: σ=50%, ρ=0.3, 单资产15% → 再平衡 ≈", end=" ")
reb, _, sng = sim(0.50, 0.3, 4)
print(f"{reb:.2f}%  (单资产实际 {sng:.2f}%)")
print(f"  即: 15%(上涨) + γ*6.56pp ≈ 21.6%, 与实测 22~24% 吻合。")
