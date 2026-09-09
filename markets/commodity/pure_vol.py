# -*- coding: utf-8 -*-
"""纯波动率收益理论计算 (用户设定: 波动率30%, 低相关, 无风险利率0, 算术口径).
公式: 等权N资产, 各自波动σ, 两两相关ρ
    gamma* = 0.5 * sigma^2 * (N-1)/N * (1-rho)
并用蒙特卡洛验证。
"""
import numpy as np

def gamma_theory(sigma, rho, N):
    return 0.5 * sigma**2 * (N-1)/N * (1-rho)

print("="*88)
print("一、纯波动率收益 γ* 理论值 (%)  [公式: ½σ²·(N-1)/N·(1-ρ)]")
print("="*88)
print(f"{'波动率σ':<9}" + "".join(f"{f'N={n}':>12}" for n in [2,4,8,20,100]))
for sig in [0.20, 0.30, 0.40, 0.50, 0.60, 0.73]:
    row = f"{sig*100:>6.0f}%  "
    for n in [2,4,8,20,100]:
        row += f"{gamma_theory(sig, 0.0, n)*100:>11.2f}%"
    print(row)
print("\n(上表为相关性 ρ=0 的理想上限;  ρ 越高收益越低, 乘 (1-ρ) )")

print("\n" + "="*88)
print("二、相关性影响 (σ=30%)")
print("="*88)
print(f"{'相关性ρ':<9}" + "".join(f"{f'N={n}':>12}" for n in [2,4,8,20]))
for rho in [0.0, 0.2, 0.4, 0.6, 0.8]:
    row = f"{rho:>7.2f}  "
    for n in [2,4,8,20]:
        row += f"{gamma_theory(0.30, rho, n)*100:>11.2f}%"
    print(row)

print("\n" + "="*88)
print("三、反推: 想靠纯波动率差挣到 X%, 需要多大波动率? (N=4, ρ=0)")
print("="*88)
for target in [0.05, 0.10, 0.15, 0.20, 0.30]:
    # target = 0.5*s^2*0.75  ->  s^2 = target/0.375
    s = np.sqrt(target / (0.5*0.75))
    print(f"  目标 {target*100:>4.0f}%/年  →  需要资产波动率 σ = {s*100:>5.1f}%")

# ---------- 蒙特卡洛验证 ----------
def mc(sigma, rho, N, mu_arith=0.0, years=20, n_sim=2000, seed=1):
    """蒙特卡洛: 月频, 等权再平衡 vs 持有"""
    rng = np.random.default_rng(seed)
    m = 12
    sm = sigma/np.sqrt(m)
    mum = mu_arith/m
    # 协方差: 对角 sm^2, 非对角 rho*sm^2
    cov = np.full((N,N), rho*sm**2); np.fill_diagonal(cov, sm**2)
    L = np.linalg.cholesky(cov + 1e-12*np.eye(N))
    reb_all, hld_all = [], []
    for _ in range(n_sim):
        z = rng.standard_normal((years*m, N))
        r = mum + z @ L.T                      # 月算术收益
        # 再平衡: 每月等权
        val = 1.0
        for t in range(len(r)):
            val *= 1.0 + r[t].mean()
        reb_all.append(val**(1/years)-1)
        # 持有: 等权买入不再平衡
        g = np.prod(1.0+r, axis=0).mean()
        hld_all.append(g**(1/years)-1)
    return np.mean(reb_all)*100, np.mean(hld_all)*100

print("\n" + "="*88)
print("四、蒙特卡洛验证 (20年, 2000次模拟, 月频再平衡)")
print("="*88)
print(f"{'设定':<34}{'再平衡年化':>12}{'持有年化':>12}{'超额':>10}{'理论γ*':>10}")
cases = [
    ("σ=30%, N=4, ρ=0, 漂移0%",   0.30, 0.0, 4, 0.0),
    ("σ=30%, N=4, ρ=0.3, 漂移0%", 0.30, 0.3, 4, 0.0),
    ("σ=30%, N=8, ρ=0, 漂移0%",   0.30, 0.0, 8, 0.0),
    ("σ=50%, N=4, ρ=0, 漂移0%",   0.50, 0.0, 4, 0.0),
    ("σ=50%, N=4, ρ=0.3, 漂移0%", 0.50, 0.3, 4, 0.0),
    ("σ=30%, N=4, ρ=0, 漂移15%",  0.30, 0.0, 4, 0.15),
    ("σ=50%, N=4, ρ=0.3, 漂移15%",0.50, 0.3, 4, 0.15),
]
for name, sg, rh, nn, mu in cases:
    reb, hld = mc(sg, rh, nn, mu)
    th = gamma_theory(sg, rh, nn)*100
    print(f"{name:<34}{reb:>11.2f}%{hld:>11.2f}%{reb-hld:>9.2f}pp{th:>9.2f}%")

print("\n注: 漂移0%时两者都为负(波动拖累), 但再平衡亏损更少, 差额=γ*(波动率差收益)。")
print("    真实投资中资产有正漂移(盈利增长), 总年化 = 漂移 + γ* - 波动拖累。")
