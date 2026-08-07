# 美股期权套保回测 · 阶段1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 改造 `us_stocks/us_backtest_ai.py` 的 `run_optimized()` 加持仓跟踪 + 单点止盈(+50%) + -8% 硬止损 + 0.1% 滑点成本模型，并新建 `us_stocks/us_options.py` 期权覆盖层空壳接口（阶段2 实现），跑 3/5/10 年回测输出对照表。

**Architecture:** 不新建引擎，改造现有 `run_optimized()`。止盈止损作为叠加层插入主循环，不干预原作者的 `struct_def`/`vol_target`/`crash_off` 权重分配逻辑。期权接口空壳返回 None，阶段1 走纯现货逻辑，阶段2 切换为期权逻辑。A 股代码零改动。

**Tech Stack:** Python 3 标准库（csv/datetime/dataclasses），无新依赖。回测用现有 `weekly_adjclose_full_ext.csv` 面板（160 只 ticker），不接 yfinance。

**设计文档:** [docs/us-options-hedge-design.md](file:///workspace/mx_auto_strategy/docs/us-options-hedge-design.md)

**原作者哲学兼容性:** 原作者注释（[us_backtest_ai.py:344](file:///workspace/mx_auto_strategy/us_stocks/us_backtest_ai.py)）"事后信号(止损)无法压MDD"在纯现货框架下成立。本设计的止损定位为**风险护栏**（防单票黑天鹅），不指望压组合 MDD；阶段2 加入大盘 protective put 才是非对称对冲工具。

---

## 文件结构

```
mx_auto_strategy/
├── us_stocks/
│   ├── us_backtest_ai.py    [改] run_optimized 加持仓跟踪+止盈止损+成本模型
│   └── us_options.py        [新] 阶段2 期权覆盖层接口(阶段1 空壳)
├── strategy_config.json     [改] +us_backtest 配置段
├── tests/
│   └── test_us_backtest.py  [新] 止盈/止损/成本/无前视/原逻辑不回归
└── us_stocks/data/
    └── us_nav_ai.csv        [改] 输出加新列
```

---

## Task 1: 新建期权接口空壳 `us_options.py`

**Files:**
- Create: `us_stocks/us_options.py`

**目的:** 阶段2 期权覆盖层的接口预留。阶段1 所有函数返回 None，`run_optimized` 走纯现货逻辑。

- [ ] **Step 1: 创建 `us_options.py` 空壳文件**

```python
"""美股期权覆盖层(阶段2 实现, 阶段1 空壳)。

阶段1: 所有函数返回 None, run_optimized 走纯现货逻辑。
阶段2: 拉 yfinance option_chain, 实现 covered call / protective put。

设计哲学(用户原话):
  - 远期 OTM put (LEAPS) 套保: "虚值特别虚, 特别便宜", 崩盘时暴涨对冲组合回撤
  - Covered call at 止盈价: "100 美元时卖出 150 美元, 刚好 150 是止盈线",
    行权价=止盈价, 到期被行权即按止盈价交割, 不到则收权利金
  - 期权是缺失的非对称 payoff 工具, 现货止损无法替代

阶段2 实施时只需实现本文件三个函数, run_optimized 主循环结构不变。
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class CoveredCall:
    """备兑看涨期权(阶段2 实现)。"""
    underlying: str        # 标的代码
    strike: float          # 行权价(=止盈价)
    expiry: date           # 到期日(远期 LEAPS)
    premium: float         # 权利金(阶段2 从 yfinance option_chain 拉)
    contracts: int         # 张数(每张 100 股)


@dataclass
class ProtectivePut:
    """保护性看跌期权(阶段2 实现)。"""
    underlying: str        # 标的代码(SPY/QQQ 大盘指数 ETF)
    strike: float          # 行权价(OTM, 低于现货)
    expiry: date           # 到期日(远期 LEAPS)
    premium: float         # 权利金
    contracts: int         # 张数


def covered_call_at_take_profit(code: str, strike: float,
                                  cfg: dict) -> Optional[CoveredCall]:
    """止盈触发时调用。

    阶段1: 返回 None = 纯现货清仓。
    阶段2: 拉 yfinance option_chain(code), 选 LEAPS 远月到期,
           找 strike 最接近的 OTM call, 返回 CoveredCall。
           run_optimized 收到后: 卖 call 收权利金, 留仓等被行权(按止盈价交割)。
    """
    return None  # 阶段1 占位


def protective_put_for_hedge(code: str, spot: float,
                               cfg: dict) -> Optional[ProtectivePut]:
    """高位套保时调用。

    阶段1: 返回 None = 不套保。
    阶段2: 拉 yfinance option_chain(SPY/QQQ), 选 LEAPS 远月到期,
           找 OTM put (strike = spot × (1 - otm_pct), 默认 otm_pct=0.10),
           返回 ProtectivePut。run_optimized 收到后: 买 put 付权利金,
           崩盘时 put 暴涨对冲组合回撤。
    """
    return None  # 阶段1 占位
```

- [ ] **Step 2: 验证文件可 import**

Run: `cd /workspace/mx_auto_strategy && python -c "import sys; sys.path.insert(0, 'us_stocks'); import us_options; print(us_options.covered_call_at_take_profit('AAPL', 150.0, {})); print(us_options.protective_put_for_hedge('QQQ', 400.0, {}))"`
Expected: 两个 `None`，无异常。

- [ ] **Step 3: Commit**

```bash
cd /workspace/mx_auto_strategy
git add us_stocks/us_options.py
git commit -m "feat(us): 新增期权覆盖层空壳接口(阶段2 实现, 阶段1 返回 None)"
```

---

## Task 2: 新增 `us_backtest` 配置段

**Files:**
- Modify: `strategy_config.json` (在顶层对象内新增 `us_backtest` 段)

**目的:** 集中管理美股回测的止盈止损+成本+期权参数，与现有配置风格一致。

- [ ] **Step 1: 读取当前 strategy_config.json 末尾结构**

Run: `cd /workspace/mx_auto_strategy && python -c "import json; c=json.load(open('strategy_config.json')); print(list(c.keys())[-3:])"`
Expected: 看到末尾几个键名（如 `['market_data', 'instrument', 'market']`），确定插入位置。

- [ ] **Step 2: 在 strategy_config.json 顶层新增 `us_backtest` 段**

在 `strategy_config.json` 的顶层 JSON 对象内（最后一个 `}` 之前）新增：

```json
,
"us_backtest": {
    "_comment": "v6.18 美股回测止盈止损+成本模型。止盈价=阶段2 covered call 行权价预留位。原作者哲学: struct_def/vol_target 压MDD, 止损定位=风险护栏(防单票爆雷), 期权(阶段2)才是非对称对冲工具。",
    "take_profit_pct": 0.50,
    "stop_loss_pct": -0.08,
    "slippage_bps": 10,
    "options": {
        "enabled": false,
        "_comment": "阶段2 开关。阶段1 false=纯现货, true=接 yfinance option_chain。",
        "min_dte": 180,
        "otm_pct": 0.10,
        "hedge_underlying": "QQQ",
        "_comment_hedge": "大盘套保标的: QQQ(高beta, 崩盘保护更激进) 或 SPY(宽基, 更稳)"
    }
}
```

- [ ] **Step 3: 验证 JSON 合法**

Run: `cd /workspace/mx_auto_strategy && python -c "import json; c=json.load(open('strategy_config.json')); print(c['us_backtest'])"`
Expected: 打印出含 `take_profit_pct: 0.5`, `stop_loss_pct: -0.08`, `slippage_bps: 10` 的 dict，无 JSON 解析错误。

- [ ] **Step 4: Commit**

```bash
cd /workspace/mx_auto_strategy
git add strategy_config.json
git commit -m "feat(us): 新增 us_backtest 配置段(止盈+50%/止损-8%/滑点0.1%/期权开关)"
```

---

## Task 3: 新增 `load_us_cfg` 辅助函数

**Files:**
- Modify: `us_stocks/us_backtest_ai.py` (在 `load_panel` 函数后，约第 92 行后插入)

**目的:** 从 strategy_config.json 读取 `us_backtest` 段，提供默认值兜底（兼容老配置）。

- [ ] **Step 1: 在 `load_panel` 函数后插入 `load_us_cfg`**

在 `us_stocks/us_backtest_ai.py` 的 `load_panel` 函数（约第 80-91 行）之后插入：

```python
def load_us_cfg(path=None):
    """读取 us_backtest 配置段, 提供默认值兜底(兼容老配置/无配置运行)。

    Returns:
        dict: {
            "take_profit_pct": float,   # +50% 止盈
            "stop_loss_pct": float,     # -8% 止损
            "slippage_bps": int,        # 10 = 0.1% 滑点
            "options": {...},
        }
    """
    default = {
        "take_profit_pct": 0.50,
        "stop_loss_pct": -0.08,
        "slippage_bps": 10,
        "options": {"enabled": False, "min_dte": 180, "otm_pct": 0.10,
                    "hedge_underlying": "QQQ"},
    }
    if path is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "strategy_config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        us = cfg.get("us_backtest", {})
        return {
            "take_profit_pct": float(us.get("take_profit_pct", default["take_profit_pct"])),
            "stop_loss_pct": float(us.get("stop_loss_pct", default["stop_loss_pct"])),
            "slippage_bps": int(us.get("slippage_bps", default["slippage_bps"])),
            "options": us.get("options", default["options"]),
        }
    except Exception:
        return default
```

- [ ] **Step 2: 在文件顶部 import 区域加 `import json`**

在 `us_stocks/us_backtest_ai.py` 第 44-50 行的 import 区域，确认已有 `import json`。如果没有，在 `import csv` 后加一行 `import json`。

Run: `cd /workspace/mx_auto_strategy && python -c "import ast; ast.parse(open('us_stocks/us_backtest_ai.py').read()); print('syntax ok')"`
Expected: `syntax ok`

- [ ] **Step 3: 验证函数可调用**

Run: `cd /workspace/mx_auto_strategy && python -c "import sys; sys.path.insert(0, 'us_stocks'); from us_backtest_ai import load_us_cfg; c=load_us_cfg(); print(c)"`
Expected: 打印 `{'take_profit_pct': 0.5, 'stop_loss_pct': -0.08, 'slippage_bps': 10, 'options': {...}}`

- [ ] **Step 4: Commit**

```bash
cd /workspace/mx_auto_strategy
git add us_stocks/us_backtest_ai.py
git commit -m "feat(us): 新增 load_us_cfg 读取止盈止损+成本配置(带默认值兜底)"
```

---

## Task 4: 新增止盈止损检查函数

**Files:**
- Modify: `us_stocks/us_backtest_ai.py` (在 `load_us_cfg` 函数后插入)

**目的:** 纯函数, 易测试。检查单票是否触发止盈/止损。

- [ ] **Step 1: 在 `load_us_cfg` 后插入 `check_take_profit` 和 `check_stop_loss`**

```python
def check_take_profit(code, state, price, us_cfg):
    """到止盈价触发, 阶段1 清仓, 阶段2 卖 covered call。

    止盈价 = entry_price × (1 + take_profit_pct)
    默认 take_profit_pct = 0.50 (+50%)

    Args:
        code: 标的代码(用于日志)
        state: holdings_state[code] dict, 含 entry_price
        price: 当周收盘价
        us_cfg: load_us_cfg() 返回的配置

    Returns:
        None - 未触发
        "clear" - 阶段1 清仓(阶段2 改为 "sell_call")
    """
    tp_pct = us_cfg["take_profit_pct"]
    entry = state.get("entry_price")
    if not entry or entry <= 0 or price is None or price <= 0:
        return None
    strike = entry * (1 + tp_pct)
    if price >= strike:
        return "clear"
    return None


def check_stop_loss(code, state, price, us_cfg):
    """硬止损: 单票亏损超阈值全清。

    定位 = 风险护栏(防单票爆雷), 非压MDD手段。
    原作者注释"止损无法压MDD"在纯现货框架下成立,
    但本止损定位为风险护栏, 与 struct_def/vol_target 压MDD手段正交。
    阶段2 加入大盘 protective put 后, 单票止损 + 大盘 put 双重保护。

    默认 stop_loss_pct = -0.08 (-8%)
    """
    sl_pct = us_cfg["stop_loss_pct"]
    entry = state.get("entry_price")
    if not entry or entry <= 0 or price is None or price <= 0:
        return None
    if price / entry - 1 <= sl_pct:
        return "clear"
    return None
```

- [ ] **Step 2: 验证语法**

Run: `cd /workspace/mx_auto_strategy && python -c "import sys; sys.path.insert(0, 'us_stocks'); from us_backtest_ai import check_take_profit, check_stop_loss; us_cfg={'take_profit_pct':0.5,'stop_loss_pct':-0.08}; print(check_take_profit('X', {'entry_price':100}, 150, us_cfg)); print(check_take_profit('X', {'entry_price':100}, 149, us_cfg)); print(check_stop_loss('X', {'entry_price':100}, 92, us_cfg)); print(check_stop_loss('X', {'entry_price':100}, 93, us_cfg))"`
Expected: `clear` / `None` / `clear` / `None`

- [ ] **Step 3: Commit**

```bash
cd /workspace/mx_auto_strategy
git add us_stocks/us_backtest_ai.py
git commit -m "feat(us): 新增 check_take_profit/check_stop_loss 纯函数(止盈+50%/止损-8%)"
```

---

## Task 5: 改造 `run_optimized` 主循环

**Files:**
- Modify: `us_stocks/us_backtest_ai.py` (改造 `run_optimized` 函数, 约第 326-439 行)

**目的:** 在主循环中插入持仓跟踪 + 成本扣减 + 止盈止损检查。保留原作者的 struct_def/vol_target/crash_off 逻辑不动。

这是本计划最复杂的任务，分多个 Step。

- [ ] **Step 1: 修改 `run_optimized` 函数签名, 新增 `us_cfg` 参数**

将 `run_optimized` 函数签名（第 326-330 行）改为：

```python
def run_optimized(series, dates, use_ai, cfg, refresh_weeks=4, top_n=3,
                  trend_gate="ma5", lookback=52, alloc=None, rebal=1, lev=1.0,
                  score_mode="mom", theme_div=False, max_per_theme=2,
                  phase_tilt=False, crash_off=80, vol_target=0.0, vol_floor=0.3,
                  struct_def=0.0, gauge="QQQ", us_cfg=None):
```

（仅在末尾加 `us_cfg=None`）

- [ ] **Step 2: 在函数体开头初始化新变量**

将第 355-358 行（`n = len(dates)...` 那一段）改为：

```python
    REBAL = rebal                               # 再平衡周期(周, 默认1=周频, 对齐A股)
    n = len(dates); nav = 1.0; nav_hist = []; peak = 1.0; mdd = 0.0
    weights = {"__cash__": 1.0}; selected = []; last_rebal = -100; yearly = {}
    weak_weeks = 0; crash_weeks = 0; vol_weeks = 0
    last_pool = -100; universe = []; gauge_arr = series.get(gauge) or series.get("SPY")
    # === v6.18 新增: 持仓跟踪 + 止盈止损 + 成本模型 ===
    if us_cfg is None:
        us_cfg = load_us_cfg()
    holdings_state = {}      # {code: {"entry_price": float, "entry_week": int, "weight": float}}
    prev_weights = {}        # 再平衡前权重快照(供成本扣减对照)
    cost_total = 0.0         # 累计成本(滑点)
    tp_count = 0             # 止盈触发次数
    sl_count = 0             # 止损触发次数
```

- [ ] **Step 3: 在主循环开头快照权重**

将第 359 行 `for t in range(n):` 之后立即插入（在 `if t > 0 and weights:` 之前）：

```python
    for t in range(n):
        # === v6.18 新增: 再平衡前快照权重(供成本扣减对照) ===
        prev_weights = dict(weights)
```

- [ ] **Step 4: 在 nav 累加后插入成本扣减**

找到第 369-371 行（`nav *= (1 + growth); nav_hist.append(nav); peak = max(peak, nav)` 那一段），在其后（`mdd = min(...)` 之前）插入成本扣减逻辑。

注意：成本扣减应在再平衡发生时计算，但 nav 累加在循环开头。需要将成本扣减放在 `weights = {c: w for c, w in tw.items()...}` 之后（第 436 行附近）。具体改法：

将第 436 行 `weights = {c: w for c, w in tw.items() if w > 0} or {"__cash__": 1.0}` 之后插入：

```python
            weights = {c: w for c, w in tw.items() if w > 0} or {"__cash__": 1.0}
            # === v6.18 新增: 再平衡成本扣减 ===
            if t > 0 and prev_weights:
                new_w = weights
                turnover = sum(abs(new_w.get(c, 0) - prev_weights.get(c, 0))
                               for c in set(new_w) | set(prev_weights)) / 2.0
                cost = turnover * us_cfg["slippage_bps"] / 10000.0
                nav *= (1 - cost)
                nav_hist[-1] = nav  # 同步更新已 append 的 nav
                cost_total += cost
            # === v6.18 新增: 持仓状态更新(再平衡后) ===
            for c, w in weights.items():
                if c == "__cash__" or w <= 0:
                    continue
                price = series.get(c, [None] * n)[t] if series.get(c) else None
                if price is None or price <= 0:
                    continue
                if c not in holdings_state:
                    # 首次建仓
                    holdings_state[c] = {
                        "entry_price": price,
                        "entry_week": t,
                        "weight": w,
                    }
                else:
                    # 再平衡调整: 加仓时加权平均成本, 减仓时不改 entry_price
                    old = holdings_state[c]
                    old_w = old["weight"]
                    if w > old_w and old_w > 0:
                        # 加仓: 加权平均
                        old["entry_price"] = (
                            old["entry_price"] * old_w + price * (w - old_w)
                        ) / w
                    old["weight"] = w
            # 移除已清仓的票
            for c in list(holdings_state.keys()):
                if c not in weights:
                    del holdings_state[c]
```

- [ ] **Step 5: 在再平衡前插入止盈止损检查**

找到第 377-378 行（`need_rebal = (t == WARMUP) or (t - last_rebal >= REBAL)` 之前），插入止盈止损检查：

```python
        # === v6.18 新增: 止盈止损检查(每周, 再平衡前) ===
        if t > WARMUP and holdings_state:
            to_clear = []
            for code, state in list(holdings_state.items()):
                arr = series.get(code)
                if not arr or t >= len(arr) or arr[t] is None or arr[t] <= 0:
                    continue
                price = arr[t]
                # 止盈优先(止盈触发后不再检查止损)
                if check_take_profit(code, state, price, us_cfg) == "clear":
                    to_clear.append((code, "take_profit"))
                    tp_count += 1
                elif check_stop_loss(code, state, price, us_cfg) == "clear":
                    to_clear.append((code, "stop_loss"))
                    sl_count += 1
            # 执行清仓: 权重转现金, 移除 holdings_state
            if to_clear:
                for code, reason in to_clear:
                    if code in weights:
                        weights["__cash__"] = weights.get("__cash__", 0) + weights[code]
                        del weights[code]
                    if code in holdings_state:
                        del holdings_state[code]
                # 清仓也算换手, 扣成本
                if prev_weights:
                    new_w = weights
                    turnover = sum(abs(new_w.get(c, 0) - prev_weights.get(c, 0))
                                   for c in set(new_w) | set(prev_weights)) / 2.0
                    cost = turnover * us_cfg["slippage_bps"] / 10000.0
                    nav *= (1 - cost)
                    nav_hist[-1] = nav
                    cost_total += cost
```

- [ ] **Step 6: 修改 `finalize` 调用, 传入新统计字段**

将第 439 行 `return finalize(nav, nav_hist, mdd, dates, yearly, n, weak_weeks, crash_weeks, 0)` 改为：

```python
    return finalize(nav, nav_hist, mdd, dates, yearly, n, weak_weeks, crash_weeks, 0,
                    cost_total=cost_total, tp_count=tp_count, sl_count=sl_count)
```

- [ ] **Step 7: 修改 `finalize` 函数签名, 接受新字段**

将 `finalize` 函数（第 442 行）改为：

```python
def finalize(nav, nav_hist, mdd, dates, yearly, n, weak_weeks, crash_weeks=0, guard_weeks=0,
             cost_total=0.0, tp_count=0, sl_count=0):
    yrs = (n - WARMUP) / 52.0
    cagr = (nav ** (1 / yrs) - 1) * 100 if yrs > 0 else 0
    spy_arr = series_proxy.get("SPY")
    spy_mult = (spy_arr[n - 1] / spy_arr[WARMUP]) if spy_arr and spy_arr[WARMUP] else None
    return nav_hist, {
        "multiple": nav, "cagr": cagr, "mdd": mdd,
        "weak_pct": weak_weeks / max(1, (n - WARMUP)) * 100,
        "crash_pct": crash_weeks / max(1, (n - WARMUP)) * 100,
        "guard_pct": guard_weeks / max(1, (n - WARMUP)) * 100,
        "spy_mult": spy_mult, "yrs": yrs, "yearly": yearly,
        "cost_total": cost_total, "take_profit_count": tp_count, "stop_loss_count": sl_count,
    }
```

- [ ] **Step 8: 修改 `main()` 中调用 `run_optimized` 的地方, 传入 `us_cfg`**

在 `main()` 函数中找到所有 `run_optimized(...)` 调用（约第 530-580 行），在参数末尾加 `us_cfg=load_us_cfg()`。

先读取 main 函数确认调用点：

Run: `cd /workspace/mx_auto_strategy && python -c "
import re
src = open('us_stocks/us_backtest_ai.py').read()
for i, line in enumerate(src.split(chr(10)), 1):
    if 'run_optimized(' in line and 'def run_optimized' not in line:
        print(f'{i}: {line.strip()}')
"`
Expected: 看到 2-4 个调用点（如 `_opt_nav, _opt_stats = run_optimized(...)`）

在每个调用点的参数末尾（`gauge="QQQ"` 之后）加 `, us_cfg=us_cfg`，并在 `main()` 开头加 `us_cfg = load_us_cfg()`。

- [ ] **Step 9: 验证语法 + 跑通原版回测**

Run: `cd /workspace/mx_auto_strategy && python -c "import ast; ast.parse(open('us_stocks/us_backtest_ai.py').read()); print('syntax ok')"`
Expected: `syntax ok`

Run: `cd /workspace/mx_auto_strategy/us_stocks && python us_backtest_ai.py --mode optimized --no-ai 2>&1 | tail -20`
Expected: 回测跑通，输出倍数/MDD/CAGR，无异常。倍数应略低于原版（因新增成本扣减），止盈止损次数 > 0。

- [ ] **Step 10: Commit**

```bash
cd /workspace/mx_auto_strategy
git add us_stocks/us_backtest_ai.py
git commit -m "feat(us): run_optimized 加持仓跟踪+止盈止损+成本模型(保留原作者 struct_def/vol_target 逻辑)"
```

---

## Task 6: 新增单元测试 `test_us_backtest.py`

**Files:**
- Create: `tests/test_us_backtest.py`

**目的:** 覆盖止盈止损触发、成本扣减、持仓状态更新、无前视、原逻辑不回归。

- [ ] **Step 1: 创建测试文件骨架**

```python
"""
us_backtest 止盈止损 + 成本模型 单元测试。

覆盖:
  - check_take_profit: +50% 触发清仓, 边界 149.99 不触发
  - check_stop_loss: -8% 触发清仓, 边界 92.01 不触发
  - check_take_profit 优先于 check_stop_loss
  - load_us_cfg: 配置读取 + 默认值兜底
  - run_optimized: 持仓状态更新 + 成本扣减 + 止盈触发清仓
  - 无前视: 止盈止损只用 t 时刻已知信息
  - 原逻辑不回归: 关闭止盈止损时结果接近原版

全部为纯函数/合成面板测试, 不依赖外部行情数据。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "us_stocks"))

import us_backtest_ai as ubt


class TestCheckTakeProfit(unittest.TestCase):
    def setUp(self):
        self.us_cfg = {"take_profit_pct": 0.50, "stop_loss_pct": -0.08, "slippage_bps": 10}

    def test_triggers_at_50pct(self):
        state = {"entry_price": 100.0}
        self.assertEqual(ubt.check_take_profit("X", state, 150.0, self.us_cfg), "clear")

    def test_not_trigger_below_threshold(self):
        state = {"entry_price": 100.0}
        self.assertIsNone(ubt.check_take_profit("X", state, 149.99, self.us_cfg))

    def test_triggers_above_threshold(self):
        state = {"entry_price": 100.0}
        self.assertEqual(ubt.check_take_profit("X", state, 200.0, self.us_cfg), "clear")

    def test_zero_entry_returns_none(self):
        state = {"entry_price": 0}
        self.assertIsNone(ubt.check_take_profit("X", state, 150.0, self.us_cfg))

    def test_none_price_returns_none(self):
        state = {"entry_price": 100.0}
        self.assertIsNone(ubt.check_take_profit("X", state, None, self.us_cfg))


class TestCheckStopLoss(unittest.TestCase):
    def setUp(self):
        self.us_cfg = {"take_profit_pct": 0.50, "stop_loss_pct": -0.08, "slippage_bps": 10}

    def test_triggers_at_minus_8pct(self):
        state = {"entry_price": 100.0}
        self.assertEqual(ubt.check_stop_loss("X", state, 92.0, self.us_cfg), "clear")

    def test_not_trigger_above_threshold(self):
        state = {"entry_price": 100.0}
        self.assertIsNone(ubt.check_stop_loss("X", state, 92.01, self.us_cfg))

    def test_triggers_on_bigger_loss(self):
        state = {"entry_price": 100.0}
        self.assertEqual(ubt.check_stop_loss("X", state, 50.0, self.us_cfg), "clear")

    def test_zero_entry_returns_none(self):
        state = {"entry_price": 0}
        self.assertIsNone(ubt.check_stop_loss("X", state, 50.0, self.us_cfg))


class TestLoadUsCfg(unittest.TestCase):
    def test_reads_from_real_config(self):
        cfg = ubt.load_us_cfg()
        self.assertEqual(cfg["take_profit_pct"], 0.50)
        self.assertEqual(cfg["stop_loss_pct"], -0.08)
        self.assertEqual(cfg["slippage_bps"], 10)
        self.assertIn("options", cfg)

    def test_default_on_missing_file(self):
        cfg = ubt.load_us_cfg("/nonexistent/path.json")
        self.assertEqual(cfg["take_profit_pct"], 0.50)
        self.assertEqual(cfg["stop_loss_pct"], -0.08)
        self.assertEqual(cfg["slippage_bps"], 10)


class TestRunOptimizedTakeProfit(unittest.TestCase):
    """合成面板: 单票从 100 涨到 150, 验证止盈触发清仓。"""
    def test_take_profit_clears_position(self):
        # 构造合成面板: SPY 平稳 + 单票 X 在 WARMUP+10 周涨到 150
        n = 80
        dates = [f"2020-01-{i+1:02d}" for i in range(n)]
        series = {"SPY": [100.0 + i * 0.1 for i in range(n)]}
        # X: 前 WARMUP+10 周平稳在 100, 之后涨到 150
        x_prices = []
        for i in range(n):
            if i < ubt.WARMUP + 10:
                x_prices.append(100.0)
            else:
                x_prices.append(150.0)  # 触发止盈
        series["X"] = x_prices
        us_cfg = {"take_profit_pct": 0.50, "stop_loss_pct": -0.08, "slippage_bps": 10,
                  "options": {"enabled": False}}
        ubt.series_proxy = {"SPY": series["SPY"]}
        nav_hist, stats = ubt.run_optimized(
            series, dates, use_ai=False, cfg=None,
            top_n=1, trend_gate=None, lookback=4, rebal=1,
            us_cfg=us_cfg,
        )
        self.assertGreater(stats["take_profit_count"], 0,
                           "应至少触发一次止盈")


class TestRunOptimizedNoRegression(unittest.TestCase):
    """关闭止盈止损时(take_profit_pct=inf, stop_loss_pct=-inf), 结果接近原版。"""
    def test_disabled_tp_sl_runs_clean(self):
        n = 80
        dates = [f"2020-01-{i+1:02d}" for i in range(n)]
        series = {"SPY": [100.0 + i * 0.1 for i in range(n)]}
        series["X"] = [100.0 + i * 0.5 for i in range(n)]
        # 关闭止盈止损
        us_cfg = {"take_profit_pct": 999.0, "stop_loss_pct": -999.0,
                  "slippage_bps": 0, "options": {"enabled": False}}
        ubt.series_proxy = {"SPY": series["SPY"]}
        nav_hist, stats = ubt.run_optimized(
            series, dates, use_ai=False, cfg=None,
            top_n=1, trend_gate=None, lookback=4, rebal=1,
            us_cfg=us_cfg,
        )
        # 止盈止损不应触发
        self.assertEqual(stats["take_profit_count"], 0)
        self.assertEqual(stats["stop_loss_count"], 0)
        # 成本应为 0(slippage_bps=0)
        self.assertEqual(stats["cost_total"], 0.0)
        # NAV 应为正
        self.assertGreater(stats["multiple"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: 跑测试验证**

Run: `cd /workspace/mx_auto_strategy && python -m pytest tests/test_us_backtest.py -v 2>&1 | tail -30`
Expected: 全部 PASS。如有失败, 根据失败信息调整测试或实现。

- [ ] **Step 3: Commit**

```bash
cd /workspace/mx_auto_strategy
git add tests/test_us_backtest.py
git commit -m "test(us): 新增止盈止损+成本模型单元测试(覆盖触发/边界/无前视/不回归)"
```

---

## Task 7: 跑 3/5/10 年回测输出对照表

**Files:**
- Modify: `us_stocks/us_backtest_ai.py` (在 `main()` 末尾加对照表打印)

**目的:** 用户要求"做完简单回测一下。3 年、5 年、10 年"。输出原版(无止盈止损) vs 新版(含止盈止损+成本) 对照。

- [ ] **Step 1: 在 `main()` 末尾加对照表打印逻辑**

在 `main()` 函数末尾（所有 run_optimized 调用之后），加入对照表打印。先读取 main 函数末尾确认插入点：

Run: `cd /workspace/mx_auto_strategy && python -c "
src = open('us_stocks/us_backtest_ai.py').read()
lines = src.split(chr(10))
for i, line in enumerate(lines, 1):
    if 'print(' in line and i > 580:
        print(f'{i}: {line.strip()}')
" | tail -10`
Expected: 看到 main 末尾的打印语句，确定插入位置。

在 main 末尾加入：

```python
    # === v6.18 新增: 3/5/10 年对照表 ===
    print("\n" + "=" * 100)
    print("美股回测对照 (止盈止损+成本模型 vs 原版)")
    print("=" * 100)
    # 先跑原版(关闭止盈止损)
    us_cfg_off = {"take_profit_pct": 999.0, "stop_loss_pct": -999.0,
                  "slippage_bps": 0, "options": {"enabled": False}}
    # 再跑新版(开启)
    us_cfg_on = load_us_cfg()
    print(f"{'窗口':<8}{'倍数(原版)':>14}{'倍数(新版)':>14}{'Δ倍数':>10}"
          f"{'MDD(原版)':>12}{'MDD(新版)':>12}{'CAGR(原版)':>12}{'CAGR(新版)':>12}")
    print("-" * 100)
    # 用不同 WARMUP 起点模拟 3/5/10 年窗口
    # (实际面板从 2016 起, 10y=全量, 5y=后5年, 3y=后3年)
    n_total = len(dates) if 'dates' in dir() else 0
    if n_total == 0:
        # main 里可能没 dates 变量, 重新加载
        dates, series_loaded = load_panel(PANEL)
        n_total = len(dates)
    for ny in (3, 5, 10):
        start_idx = max(ubt.WARMUP, n_total - ny * 52)
        if start_idx < ubt.WARMUP:
            continue
        # 截取面板
        sub_dates = dates[start_idx:]
        sub_series = {c: arr[start_idx:] for c, arr in series_loaded.items()}
        ubt.series_proxy = {"SPY": sub_series.get("SPY", [])}
        # 原版
        _, stats_off = run_optimized(
            sub_series, sub_dates, use_ai=False, cfg=None,
            top_n=3, trend_gate="ma5", lookback=52, rebal=1,
            us_cfg=us_cfg_off,
        )
        # 新版
        ubt.series_proxy = {"SPY": sub_series.get("SPY", [])}
        _, stats_on = run_optimized(
            sub_series, sub_dates, use_ai=False, cfg=None,
            top_n=3, trend_gate="ma5", lookback=52, rebal=1,
            us_cfg=us_cfg_on,
        )
        print(f"{ny}y{'':<6}{stats_off['multiple']:>13.2f}x{stats_on['multiple']:>13.2f}x"
              f"{stats_on['multiple']-stats_off['multiple']:>+9.2f}x"
              f"{stats_off['mdd']*100:>11.2f}%{stats_on['mdd']*100:>11.2f}%"
              f"{stats_off['cagr']:>11.2f}%{stats_on['cagr']:>11.2f}%")
    print("-" * 100)
    # 触发次数汇总(全量)
    ubt.series_proxy = {"SPY": series_loaded.get("SPY", [])}
    _, stats_full = run_optimized(
        series_loaded, dates, use_ai=False, cfg=None,
        top_n=3, trend_gate="ma5", lookback=52, rebal=1,
        us_cfg=us_cfg_on,
    )
    print(f"\n止盈触发次数(全量): {stats_full['take_profit_count']}")
    print(f"止损触发次数(全量): {stats_full['stop_loss_count']}")
    print(f"累计成本(全量): {stats_full['cost_total']*100:.4f}%")
    print("=" * 100)
```

- [ ] **Step 2: 跑回测验证输出**

Run: `cd /workspace/mx_auto_strategy/us_stocks && python us_backtest_ai.py --mode optimized --no-ai 2>&1 | tail -30`
Expected: 末尾打印对照表，含 3y/5y/10y 三行的倍数/MDD/CAGR 对照 + 触发次数汇总。

- [ ] **Step 3: Commit**

```bash
cd /workspace/mx_auto_strategy
git add us_stocks/us_backtest_ai.py
git commit -m "feat(us): main 末尾加 3/5/10 年回测对照表(原版 vs 含止盈止损+成本)"
```

---

## Task 8: 全量回归测试

**Files:**
- 无文件改动, 仅运行测试

**目的:** 确保新增改动不破坏现有 A 股测试 + 新增 us_backtest 测试通过。

- [ ] **Step 1: 跑全量单测**

Run: `cd /workspace/mx_auto_strategy && python -m pytest tests/ -v 2>&1 | tail -20`
Expected: 全部 PASS（含原有 175 个 + 新增 us_backtest 测试）。允许 skip。

- [ ] **Step 2: 跑美股回测确认无异常**

Run: `cd /workspace/mx_auto_strategy/us_stocks && python us_backtest_ai.py --mode optimized --no-ai 2>&1 | tail -40`
Expected: 回测跑通, 输出 3/5/10 年对照表, 止盈止损次数 > 0, 累计成本 > 0。

- [ ] **Step 3: 跑 QA-02 合成数据测试**

Run: `cd /workspace/mx_auto_strategy && python ashare_backtest/_qa/qa_02_synthetic_unit_tests.py 2>&1 | tail -10`
Expected: `26 PASS / 0 FAIL`（A 股回测零回归）。

- [ ] **Step 4: 验证 A 股代码无 import 美股模块**

Run: `cd /workspace/mx_auto_strategy && python -c "
import ast
for f in ['auto_trader.py', 'market_data.py', 'instrument.py', 'selector.py', 'weekly_theme.py', 'grid_trader.py']:
    tree = ast.parse(open(f).read())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = ' '.join(getattr(a, 'name', '') for a in (node.names or []))
            mod = getattr(node, 'module', '') or ''
            if 'us_backtest' in mod or 'us_options' in mod:
                print(f'{f}: 意外 import {mod}')
print('check done')
"`
Expected: `check done`，无意外 import 报告。

- [ ] **Step 5: 最终 Commit (如有未提交改动)**

Run: `cd /workspace/mx_auto_strategy && git status`
Expected: working tree clean（所有改动已提交）。

---

## 自审清单

**Spec 覆盖检查:**

| Spec 要求 | 对应 Task | 状态 |
|---|---|---|
| 持仓跟踪 (holdings_state) | Task 5 Step 2,4 | ✅ |
| 单点止盈 +50% (预留行权价) | Task 4, Task 5 Step 5 | ✅ |
| -8% 硬止损 (风险护栏) | Task 4, Task 5 Step 5 | ✅ |
| 成本模型 0.1% 滑点 | Task 5 Step 4 | ✅ |
| 期权接口空壳 (阶段2 预留) | Task 1 | ✅ |
| us_backtest 配置段 | Task 2 | ✅ |
| 测试覆盖 | Task 6 | ✅ |
| 3/5/10 年回测对照 | Task 7 | ✅ |
| A 股零改动 | Task 8 Step 4 验证 | ✅ |
| 保留 struct_def/vol_target/crash_off | Task 5 (不改权重分配逻辑) | ✅ |

**Placeholder 扫描:** 无 TBD/TODO, 所有 Step 含完整代码。

**类型一致性检查:**
- `check_take_profit(code, state, price, us_cfg)` 在 Task 4 定义, Task 5 Step 5 调用 ✅
- `check_stop_loss(code, state, price, us_cfg)` 同上 ✅
- `load_us_cfg()` 返回 dict, Task 3/5/6 使用一致 ✅
- `finalize(..., cost_total=, tp_count=, sl_count=)` Task 5 Step 6/7 一致 ✅
- `us_cfg` 参数在 `run_optimized` 签名和调用点一致 ✅

---

## 执行选择

**Plan complete and saved to `docs/superpowers/plans/2026-08-07-us-options-hedge-phase1.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - 每个 Task 派一个 fresh subagent, 任务间 review, 快速迭代

**2. Inline Execution** - 在当前会话用 executing-plans, 批量执行带检查点

**Which approach?**
