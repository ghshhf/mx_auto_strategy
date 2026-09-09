# -*- coding: utf-8 -*-
"""验证用户洞察: 波动率差挣的钱 = 补上的波动损耗。
恒等式: gamma* = (sigma^2 - sigma_p^2)/2 = 单资产波动损耗 - 组合波动损耗
修正: 典型路径用中位数(而非算术均值, 后者被少数暴涨路径拉高)。
"""
import numpy as np

def sim(sigma, rho, N, years=20, n=3000, seed=2, mu=0.0):
    rng = np.random.default_rng(seed)
    m = 12
    sm = sigma/np.sqrt(m)
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
        reb.append(v**(1/years) - 1)                       # 等权再平衡
        hld.append(np.prod(1 + r, axis=0).mean()**(1/years) - 1)  # 等权持有
        sng.append(np.prod(1 + r[:, 0])**(1/years) - 1)    # 单资产持有
    return np.median(reb)*100, np.median(hld)*100, np.median(sng)*100

print("="*100)
print("验证: 波动率差收益 γ* 是否 = 补上的波动损耗 (漂移=0, 即资产算术期望收益为0)")
print("="*100)
print(f"{'设定':<22}{'单资产中位':>11}{'等权持有中位':>13}{'再平衡中位':>12}{'再平衡-持有':>12}{'理论γ*':>10}{'单资产-持有':>12}")
for sigma in [0.30, 0.40, 0.50, 0.60]:
    for rho in [0.0, 0.3]:
        N = 4
        reb, hld, sng = sim(sigma, rho, N)
        th = 0.5 * sigma**2 * (N-1)/N * (1-rho) * 100
        # 单资产波动损耗 = sigma^2/2 ; 组合损耗 = sigma_p^2/2
        print(f"σ={sigma:.0%} ρ={rho} N={N}      {sng:>10.2f}%{hld:>12.2f}%{reb:>11.2f}%"
              f"{reb-hld:>11.2f}pp{th:>9.2f}%{sng-hld:>11.2f}pp")

print("\n" + "="*100)
print("损耗拆解 (σ=50%, N=4, ρ=0)")
print("="*100)
sig, rho, N = 0.50, 0.0, 4
sig_p = sig*np.sqrt((1+(N-1)*rho)/N)
print(f"  单资产波动 σ        = {sig*100:.1f}%   → 几何损耗 σ²/2   = {sig**2/2*100:.2f}%/年")
print(f"  组合波动 σ_p        = {sig_p*100:.1f}%   → 几何损耗 σ_p²/2 = {sig_p**2/2*100:.2f}%/年")
print(f"  波动率差收益 γ*     = (σ²-σ_p²)/2    = {(sig**2-sig_p**2)/2*100:.2f}%/年")
print(f"  即: 再平衡把损耗从 {sig**2/2*100:.2f}% 压到 {sig_p**2/2*100:.2f}%, 差额 {(sig**2-sig_p**2)/2*100:.2f}% 就是挣到的钱")

reb, hld, sng = sim(sig, rho, N)
print(f"\n  模拟(中位数): 单资产 {sng:.2f}%  等权持有 {hld:.2f}%  再平衡 {reb:.2f}%")
print(f"  实际挣到(再平衡-持有) = {reb-hld:.2f}pp   理论 γ* = {(sig**2-sig_p**2)/2*100:.2f}pp")
