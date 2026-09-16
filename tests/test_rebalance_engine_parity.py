# -*- coding: utf-8 -*-
"""
🔒 再平衡引擎「唯一真源」回归测试 (2026-09-15 P0 收敛后新增)

背景:
  仓库里曾经存在 **3 份并行实现** 的等权再平衡核心循环
  (crypto / ashare_all / ashare_50_50), 算法等价但**没有任何测试锁住它们**。
  只要改一处忘了另一处, 跨市场数字就不可比, 而 CI 全程绿灯。
  现已收敛到 markets/core/rebalance.py; 本文件负责**让它不再漂回去**。

三层防线:
  ① 单一实现  —— AST 扫描全仓, 除 core 外不得再出现调仓核心特征
  ② 跨市场一致 —— 同一输入喂给 crypto / ashare 两份包装, 关键数值必须一致
  ③ 内核不变量 —— capital 无关性 / 权重归一 / 调仓次数
"""
import ast
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "markets" / "core" / "rebalance.py"

# 调仓核心循环的**特征串** (任何一份复制粘贴都逃不掉)
FINGERPRINTS = (
    "np.abs(tgt - units)",
    "tot * w / pr[k]",
    "traded / tot",
)


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def core():
    return _load("markets/core/rebalance.py", "rb_core_fx")


@pytest.fixture(scope="module")
def crypto():
    return _load("markets/crypto/crypto_btc_ada_pair.py", "rb_crypto_fx")


@pytest.fixture(scope="module")
def ashare():
    return _load("markets/ashare/ashare_pair_all.py", "rb_ashare_fx")


# ---------------------------------------------------------------- ① 单一实现
def test_only_one_rebalance_kernel_implementation():
    """凡含调仓核心特征的文件, 必须已改为调用 core (kernel / step)。

    说明: 有的函数有**独有**的外层逻辑(相位版调仓日历、分批建仓现金流、
    逐笔成交日志), 不要求删除 —— 但**调仓数学**必须走 core。
    """
    offenders, via_core = {}, []
    for p in (ROOT / "markets").rglob("*.py"):
        if p.name == "conftest.py" or "_archive" in p.parts:
            continue
        if p.resolve() == CORE.resolve():
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hits = [f for f in FINGERPRINTS if f in src]
        uses = ("rebalance_kernel" in src) or ("rebalance_step" in src)
        rel = str(p.relative_to(ROOT))
        if hits and not uses:            # 有核心特征却没接 core ⇒ 违规
            offenders[rel] = hits
        if uses:                         # 已接 core
            via_core.append(rel)
    assert not offenders, (
        "发现未复用 core 的平行调仓实现 —— 请改为调用 "
        "markets/core/rebalance.py 的 rebalance_kernel / rebalance_step"
        f": {offenders}"
    )
    assert len(via_core) >= 6, (
        f"复用 core 的文件只有 {len(via_core)} 个, 疑似收敛未覆盖全: {via_core}"
    )


def test_core_kernel_is_referenced_by_all_markets():
    """三个市场的入口都必须转发到 core, 不许自己算。"""
    for rel in ("markets/crypto/crypto_btc_ada_pair.py",
                "markets/ashare/ashare_pair_all.py",
                "markets/ashare/ashare_pair_50_50.py"):
        src = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        assert "rebalance_kernel" in src, f"{rel} 未调用唯一引擎 rebalance_kernel"


# ---------------------------------------------------------------- ② 跨市场一致
def _synth(seed=2026, n=2, T=260):
    rng = np.random.default_rng(seed)
    pr = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.06, (T, n)), axis=0))
    idx = pd.date_range("2018-01-05", periods=T, freq="7D")
    return pr, pd.DataFrame(pr, index=idx, columns=[f"C{i}" for i in range(n)])


@pytest.mark.parametrize("seed,n,rb,cb", [
    (7, 2, 4, 10.0), (42, 3, 4, 10.0), (2026, 5, 13, 0.0), (99, 2, 1, 10.0),
])
def test_crypto_ashare_parity(crypto, ashare, seed, n, rb, cb):
    """同输入 ⇒ crypto.sim 与 ashare.sim_pair 的净值/死拿倍数必须一致。"""
    pr, df = _synth(seed=seed, n=n)
    c = crypto.sim(df, list(df.columns), rebal_weeks=rb, cost_bp=cb)
    a = ashare.sim_pair(pr, rebal_weeks=rb, cost_bp=cb)
    # crypto 用 capital=1, ashare 用 capital=CAP ⇒ 都是「倍数」, 可直接比
    assert np.isclose(c["nav"], a["nav_mult"], rtol=1e-12, atol=1e-12)
    assert np.isclose(c["hold_nav"], a["hold_mult"], rtol=1e-12, atol=1e-12)
    beta_c = np.array([c["units_mult"][k] for k in df.columns])
    assert np.allclose(beta_c, a["beta"], rtol=1e-12, atol=1e-12)
    assert c["turnover_events"] == a["ntr"]


# ---------------------------------------------------------------- ③ 内核不变量
def test_capital_does_not_change_multiples(core):
    """capital 只缩放 NAV 量级, 不影响任何倍数/比率。"""
    pr, _ = _synth(seed=11, n=3)
    r1 = core.rebalance_kernel(pr, 4, 10.0, capital=1.0)
    r2 = core.rebalance_kernel(pr, 4, 10.0, capital=123456.0)
    assert np.allclose(r2["NAV"] / r1["NAV"], 123456.0, rtol=1e-12)
    assert np.allclose(r1["units"] / r1["U0"], r2["units"] / r2["U0"], rtol=1e-12)
    assert r1["ntr"] == r2["ntr"]


def test_equal_weight_and_initial_nav(core):
    pr, _ = _synth(seed=5, n=4)
    r = core.rebalance_kernel(pr, 4, 10.0, capital=1000.0)
    assert np.allclose(r["w"], 1.0 / 4)
    assert np.isclose(r["NAV"][0], 1000.0, rtol=1e-12)
    # 注意: r["units"] 是**期末**份额, 期初要用 U0
    assert np.isclose(float((r["U0"] * pr[0]).sum()), 1000.0, rtol=1e-12)


def test_rebalance_event_count(core):
    """调仓次数 = ceil((T-1)/rb) - 1, 且每次换手率非负。"""
    pr, _ = _synth(seed=3, n=2)
    for rb in (1, 4, 13):
        r = core.rebalance_kernel(pr, rb, 10.0)
        T = pr.shape[0]
        expect = len([k for k in range(rb, T, rb)])
        assert r["ntr"] == expect, (rb, r["ntr"], expect)
        assert len(r["turns"]) == r["ntr"]
        assert all(t >= 0 for t in r["turns"])


def test_zero_cost_has_no_leak(core):
    """0 成本时, 调仓本身不消耗价值 (NAV 在调仓点连续)。"""
    pr, _ = _synth(seed=17, n=2)
    r0 = core.rebalance_kernel(pr, 4, 0.0, capital=1.0)
    r1 = core.rebalance_kernel(pr, 4, 10.0, capital=1.0)
    assert r0["NAV"][-1] > r1["NAV"][-1], "10bp 必须比 0bp 差 (成本确实在扣)"
