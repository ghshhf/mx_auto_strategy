# 美股期权套保回测 · 设计文档

**日期**: 2026-08-07
**作者**: 用户（原作者）+ AI 协作
**状态**: 待实施

## 1. 背景与动机

### 1.1 项目现状

`mx_auto_strategy` 已有完整美股回测体系（[us_stocks/us_backtest_ai.py](file:///workspace/mx_auto_strategy/us_stocks/us_backtest_ai.py)）：
- 160 只 ticker 真实面板（2016-02 至今周线，westock-data 抓取）
- 13 主题选股（AI算力/半导体/CloudSaaS/EV/光伏/GLP1/网络安全 等）
- 市况三档（weak/balance/bull）+ crash 档
- 结构性降敞口手段：`struct_def`（永久现金袖）+ `vol_target`（波动率目标化）+ `crash_off`（崩盘档进攻占比）
- 倍数 ≈22.9x / MDD ≈-48%（无杠杆）

### 1.2 原作者的判断（us_backtest_ai.py:344 注释）

> "事后信号(MA/护栏/止损/广度)均无法压MDD(要么太迟要么鞭梢); 结构性降敞口是唯一路径"

**此判断在纯现货框架下成立**。鞭梢效应导致止损在快速反转中错过反弹，MA 信号滞后，广度信号噪音大。原作者用现金袖 + 波动率目标化压 MDD，方向正确但代价是收益（23x/-48% → 8.5x/-32%）。

### 1.3 缺失的拼图：期权

原作者当时忽略了期权工具。期权提供**非对称 payoff**，是现货无法替代的对冲手段：

- **远期 OTM put**（保护性看跌）：崩盘前开 SPY/QQQ 远期 OTM put，权利金极低（虚值特别便宜），崩盘时 put 暴涨提供组合对冲。这是真正的"用小钱保大头"。
- **Covered call at 止盈价**：涨到止盈线卖 call，不到就收权利金增厚收益。行权价 = 止盈价，到期被行权即按止盈价交割。

**核心洞察**：期权是缺失的那块拼图。原"止损无法压MDD"判断在加入期权后不再适用——期权的非对称 payoff 能在崩盘段提供现货无法提供的保护。

### 1.4 用户原话

> "原主的也是我。过去为什么我压不了？因为我当时忘了有期权这个东西。打个比方，美股那个极端崩盘的时候，你提前开一个大盘空单，是吧？远期这不就是那保的一部分了吗？因为你要知道，远期的话，虚值特别虚，特别便宜。"
>
> "100 美元的时候，你卖出 150 美元，你不可能短时间内给我蹦到 150 美元吧？如果刚好 150 美元是咱们的止盈线呢？"
>
> "做完简单回测一下。3 年、5 年、10 年。"

## 2. 设计目标

### 2.1 阶段划分

**阶段1（本次实施）**：美股现货回测增强 + 期权接口预留
- 改造 [us_backtest_ai.py](file:///workspace/mx_auto_strategy/us_stocks/us_backtest_ai.py) `run_optimized()` 加持仓跟踪 + 单点止盈 + -8% 硬止损 + 成本模型补全
- 新建 `us_stocks/us_options.py` 期权覆盖层接口（阶段1 空壳，阶段2 实现）
- 跑 3/5/10 年回测对照（现货基线 vs 含止盈止损）

**阶段2（后续）**：期权覆盖层实现
- yfinance 拉 SPY/QQQ option_chain（LEAPS 远月，已确认数据可用，QQQ 有 2028-12 到期合约）
- 大盘 protective put 套保（崩盘前开远期 OTM put）
- 个股 covered call at 止盈价（行权价 = 止盈价）
- Black-Scholes / Greeks 计算
- 期权权利金 + payoff 计入 NAV
- 跑 3/5/10 年回测对照（现货 vs 现货+期权）

### 2.2 成功标准

- 阶段1 完成后：3/5/10 年回测能跑通，输出含止盈止损+成本扣减的倍数/MDD/CAGR
- 阶段1 不破坏现有 `run_optimized` 的 `struct_def`/`vol_target`/`crash_off` 逻辑
- 阶段1 为阶段2 预留清晰接口（`us_options.covered_call_at_take_profit` / `us_options.protective_put_for_hedge`）
- A 股代码零改动（175 个单测保持绿）

### 2.3 范围边界

**阶段1 做**：
- 改造 `run_optimized` 加持仓跟踪 + 止盈止损 + 成本模型
- 新建 `us_options.py` 空壳接口
- 新增 `strategy_config.json` 的 `us_backtest` 配置段
- 新增 `tests/test_us_backtest.py` 测试
- 跑 3/5/10 年回测，落盘结果

**阶段1 不做**：
- 不接 yfinance（回测用现有面板，160 只 ticker 已够）
- 不实现期权定价（阶段2）
- 不动 A 股代码
- 不用 CMC key（已保存到本地 .env，阶段2/未来加密货币才用）

**阶段2 才做**：
- yfinance option_chain 数据拉取
- Black-Scholes / Greeks
- 大盘 protective put 套保
- 个股 covered call
- 期权 NAV 计入

## 3. 架构设计

### 3.1 文件改动

```
mx_auto_strategy/
├── us_stocks/
│   ├── us_backtest_ai.py    [改] run_optimized 加持仓跟踪+止盈止损+成本模型
│   ├── us_options.py        [新] 阶段2 期权覆盖层接口(阶段1 空壳)
│   └── data/
│       └── weekly_adjclose_full_ext.csv  [复用] 160 只 ticker 面板, 不新抓数据
├── strategy_config.json     [改] +us_backtest 配置段
├── tests/
│   └── test_us_backtest.py  [新] 止盈/止损/成本/无前视
└── ashare_backtest/         [不动] A 股零改动
```

### 3.2 核心原则

1. **不新建引擎**：改造现有 `run_optimized()`，保留原作者的 `struct_def`/`vol_target`/`crash_off` 哲学
2. **止盈止损是叠加层**：在再平衡后检查，不干预权重分配逻辑
3. **阶段2 接口预留**：`us_options.py` 空壳函数返回 None，阶段1 走纯现货逻辑，阶段2 切换为期权逻辑
4. **A 股零改动**：所有改动局限于 `us_stocks/` 目录

### 3.3 数据流

```
weekly_adjclose_full_ext.csv (现有面板, 不新抓数据)
        ↓
load_panel() (现有函数, 不改)
        ↓
run_optimized() [改造] ── 每周:
│   1. 算 weights (现有逻辑: 动量+趋势门+集中加权+vol_target+struct_def)
│   2. 算 turnover × slippage 扣成本 [新]
│   3. 检查每只票止盈止损 [新]
│       ├─ 止盈触发 → us_options.covered_call_at_take_profit() [阶段1 返回None=清仓]
│       └─ 止损触发 → 清仓转现金
│   4. nav 累加
↓
finalize() [现有函数, 微调加 cost 字段]
        ↓
stats {multiple, mdd, cagr, cost_total, tp_count, sl_count} [扩展]
```

## 4. 详细设计

### 4.1 持仓状态跟踪（新增）

当前 `run_optimized` 只跟踪 `weights`（权重 dict），不跟踪建仓价。新增 `holdings_state`：

```python
# 每只票的持仓状态(新建)
holdings_state = {
    "NVDA": {
        "entry_price": 150.0,    # 建仓价(首次建仓或再平衡时更新)
        "entry_week": 100,        # 建仓周索引
        "weight": 0.15,           # 当前权重
    },
    ...
}
```

**更新时机**：
- 首次建仓（权重从 0 变正）：记录 entry_price = 当周收盘价
- 再平衡调整权重：更新 entry_price 为加权平均（旧仓 × 旧价 + 新增 × 当周价）/ 新总仓
- 清仓（止盈/止损触发）：从 holdings_state 移除

### 4.2 单点止盈（新增）

```python
def check_take_profit(code, state, price, cfg):
    """到止盈价触发, 阶段1 清仓, 阶段2 卖 covered call。
    
    止盈价 = entry_price × (1 + take_profit_pct)
    默认 take_profit_pct = 0.50 (+50%)
    
    返回:
        None - 未触发
        "clear" - 阶段1 清仓(阶段2 改为 "sell_call")
    """
    tp_pct = cfg["us_backtest"]["take_profit_pct"]
    strike = state["entry_price"] * (1 + tp_pct)
    if price >= strike:
        return "clear"
    return None
```

**设计要点**：
- 止盈价 = entry_price × (1 + 50%)，这是阶段2 covered call 的行权价预留位
- 阶段1 触发即清仓转现金，下周再平衡会重新分配
- 阶段2 触发时调用 `us_options.covered_call_at_take_profit(code, strike, cfg)`，返回 CoveredCall 对象则卖 call 留仓收权利金

### 4.3 -8% 硬止损（新增）

```python
def check_stop_loss(code, state, price, cfg):
    """硬止损: 单票亏损超阈值全清。
    
    定位 = 风险护栏(防单票爆雷), 非压MDD手段。
    原作者注释"止损无法压MDD"在纯现货框架下成立,
    但本止损定位为风险护栏, 与 struct_def/vol_target 压MDD手段正交。
    
    默认 stop_loss_pct = -0.08 (-8%)
    """
    sl_pct = cfg["us_backtest"]["stop_loss_pct"]
    if price / state["entry_price"] - 1 <= sl_pct:
        return "clear"
    return None
```

**与原作者哲学的兼容**：
- `struct_def` / `vol_target` / `crash_off` 全部保留不动（这些压 MDD）
- 止损是**叠加层**，定位为风险护栏（防单票黑天鹅如退市/财务造假），不指望压组合 MDD
- 阶段2 加入大盘 protective put 后，单票止损 + 大盘 put 双重保护

### 4.4 成本模型补全（新增）

当前 `run_optimized` 完全无成本扣减（[us_backtest_ai.py:369](file:///workspace/mx_auto_strategy/us_stocks/us_backtest_ai.py) `nav *= (1 + growth)` 无 turnover × cost）。

```python
# 在再平衡时计算换手并扣成本
old_w = weights  # 上周权重
new_w = target_weights  # 本周目标权重
# turnover = 单边换手(买+卖各算一半, 总和 = sum|Δw|)
turnover = sum(abs(new_w.get(c, 0) - old_w.get(c, 0)) 
               for c in set(new_w) | set(old_w)) / 2.0
slippage_bps = cfg["us_backtest"]["slippage_bps"]  # 默认 10 = 0.1%
cost = turnover * slippage_bps / 10000.0
nav *= (1 - cost)
cost_total += cost
```

**设计要点**：
- 单边换手 = `sum|Δw| / 2`（买+卖对称，总换手是单边两倍，扣成本按单边一次）
- 滑点 0.1% 是美股零售零售合理假设（IB 真实成本约 0.05%，含 SEC fee + TAF）
- 止盈止损触发的清仓也计入 turnover

### 4.5 期权接口预留（us_options.py 空壳）

```python
# us_stocks/us_options.py
"""美股期权覆盖层(阶段2 实现, 阶段1 空壳)。

阶段1: 所有函数返回 None, run_optimized 走纯现货逻辑。
阶段2: 拉 yfinance option_chain, 实现 covered call / protective put。

设计哲学:
  - 远期 OTM put (LEAPS) 套保: 虚值特别虚, 权利金极低, 崩盘时暴涨对冲组合回撤
  - Covered call at 止盈价: 行权价 = 止盈价, 到期被行权即按止盈价交割, 不到则收权利金
  - 期权是缺失的非对称 payoff 工具, 现货止损无法替代
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

### 4.6 run_optimized 改造点

在现有 `run_optimized` 循环中（[us_backtest_ai.py:359-439](file:///workspace/mx_auto_strategy/us_stocks/us_backtest_ai.py)）插入 3 个新逻辑块。**关键：再平衡前必须先快照权重**（否则成本扣减无对照）：

```python
# 现有: for t in range(n): ... (行 359)
for t in range(n):
    # === 新增块0: 再平衡前快照权重(供成本扣减对照) ===
    prev_weights = dict(weights) if weights else {}
    
    # === 现有再平衡逻辑(行 374-436): 算 selected / weights ===
    # ... (不改, 但需确保 weights 更新后 prev_weights 仍保留再平衡前值)
    
    # === 新增块1: 成本扣减(再平衡后, 用 prev_weights 对照) ===
    if t > 0 and t == last_rebal:
        new_w = weights  # 本周权重(再平衡后)
        turnover = sum(abs(new_w.get(c, 0) - prev_weights.get(c, 0))
                       for c in set(new_w) | set(prev_weights)) / 2.0
        cost = turnover * cfg["us_backtest"]["slippage_bps"] / 10000.0
        nav *= (1 - cost)
        cost_total += cost
    
    # === 新增块2: 持仓状态更新(再平衡后) ===
    if t >= WARMUP and selected and t == last_rebal:
        for c, w in weights.items():
            if c == "__cash__":
                continue
            price = series.get(c, [None]*n)[t]
            if price is None or price <= 0:
                continue
            if c not in holdings_state and w > 0:
                # 首次建仓
                holdings_state[c] = {
                    "entry_price": price,
                    "entry_week": t,
                    "weight": w,
                }
            elif c in holdings_state:
                # 再平衡调整: 加权平均成本(简化: 用新价覆盖, 阶段2 可精确算)
                old = holdings_state[c]
                old_w_val = old["weight"]
                new_w_val = w
                if new_w_val > old_w_val:
                    # 加仓: 加权平均
                    total_w = old_w_val + new_w_val
                    old["entry_price"] = (
                        old["entry_price"] * old_w_val + price * (new_w_val - old_w_val)
                    ) / total_w
                old["weight"] = new_w_val
    
    # === 新增块3: 止盈止损检查(每周, 再平衡前) ===
    if t > 0 and holdings_state:
        to_clear = []
        for code, state in list(holdings_state.items()):
            price = series.get(code, [None]*n)[t]
            if price is None or price <= 0:
                continue
            # 止盈
            if check_take_profit(code, state, price, cfg) == "clear":
                option = us_options.covered_call_at_take_profit(
                    code, state["entry_price"] * (1 + cfg["us_backtest"]["take_profit_pct"]), cfg
                )
                if option is None:
                    # 阶段1: 纯现货清仓
                    to_clear.append((code, "take_profit"))
                    tp_count += 1
                # 阶段2: option 非 None 时卖 call 留仓(阶段1 不走这分支)
            # 止损
            elif check_stop_loss(code, state, price, cfg) == "clear":
                to_clear.append((code, "stop_loss"))
                sl_count += 1
        
        # 执行清仓: 权重转现金, 移除 holdings_state
        for code, reason in to_clear:
            if code in weights:
                weights["__cash__"] = weights.get("__cash__", 0) + weights[code]
                del weights[code]
            del holdings_state[code]
    
    # 现有: nav 累加逻辑(行 360-371) 不变
    ...
```

### 4.7 配置新增

`strategy_config.json` 新增 `us_backtest` 段：

```json
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

### 4.8 finalize() 扩展

`finalize()` 返回的 stats dict 新增字段：

```python
return nav_hist, {
    "multiple": nav, "cagr": cagr, "mdd": mdd,
    "weak_pct": ..., "crash_pct": ..., "guard_pct": ...,
    "spy_mult": spy_mult, "yrs": yrs, "yearly": yearly,
    # 新增
    "cost_total": cost_total,        # 累计成本(滑点)
    "take_profit_count": tp_count,   # 止盈触发次数
    "stop_loss_count": sl_count,     # 止损触发次数
}
```

## 5. 测试设计

`tests/test_us_backtest.py` 覆盖：

### 5.1 止盈触发
- 合成面板：某票从 100 涨到 150（+50%），验证 holdings_state 移除、权重转现金
- 边界：涨到 149.99 不触发，150.00 触发

### 5.2 止损触发
- 合成面板：某票从 100 跌到 92（-8%），验证清仓
- 边界：跌到 92.01 不触发，92.00 触发

### 5.3 成本扣减
- 合成面板：再平衡时权重从 {A:0.5, B:0.5} 变为 {A:0.6, B:0.4}
- 验证 turnover = 0.1, cost = 0.1 × 10/10000 = 0.0001, nav 扣减正确

### 5.4 持仓状态更新
- 首次建仓：entry_price = 当周收盘价
- 加仓：加权平均成本正确
- 清仓：holdings_state 移除

### 5.5 无前视
- 止盈止损只用 t 时刻已知信息（当周收盘价）
- 不用 t+1 数据

### 5.6 原有逻辑不回归
- struct_def/vol_target/crash_off 行为不变
- 不加止盈止损时（take_profit_pct=inf, stop_loss_pct=-inf），结果与原版一致

### 5.7 期权接口空壳
- `us_options.covered_call_at_take_profit` 阶段1 返回 None
- `us_options.protective_put_for_hedge` 阶段1 返回 None

## 6. 回测输出

跑 3/5/10 年回测，输出对照表：

```
=== 美股回测对照 (止盈止损+成本模型) ===
窗口    倍数(原版)  倍数(新版)  Δ倍数     MDD(原版)  MDD(新版)  ΔMDD    CAGR(原版)  CAGR(新版)
3y      XX.XXx     XX.XXx     +X.XXx    -XX.X%    -XX.X%    +X.X    XX.X%      XX.X%
5y      XX.XXx     XX.XXx     +X.XXx    -XX.X%    -XX.X%    +X.X    XX.X%      XX.X%
10y     XX.XXx     XX.XXx     +X.XXx    -XX.X%    -XX.X%    +X.X    XX.X%      XX.X%

止盈触发次数: 3y=X / 5y=X / 10y=X
止损触发次数: 3y=X / 5y=X / 10y=X
累计成本:     3y=X.X% / 5y=X.X% / 10y=X.X%
```

## 7. 风险与权衡

### 7.1 止盈的代价
- +50% 止盈会错过继续上涨的票（如 NVDA 从 100 涨到 500）
- 但阶段2 加入 covered call 后，止盈是卖 call 而非清仓，能继续收权利金 + 保留上行到行权价

### 7.2 止损的鞭梢风险
- 原作者注释明确指出止损鞭梢问题
- 本设计定位止损为"风险护栏"（防单票黑天鹅），不指望压组合 MDD
- 阶段2 加入大盘 protective put 后，组合层面有非对称保护，单票止损鞭梢风险可接受

### 7.3 成本模型简化
- 阶段1 用固定 0.1% 滑点，未按股数计 IB 真实费率
- 阶段2 可升级为 IB 真实成本（$0.005/股 + SEC fee + TAF）

### 7.4 持仓状态简化
- 阶段1 再平衡时 entry_price 用简化加权（加仓时加权，减仓时不改）
- 阶段2 可精确算（按 FIFO 或平均成本法）

## 8. 后续阶段2 预告

阶段2 实施时只需：
1. 实现 `us_options.py` 三个函数（拉 yfinance option_chain + Black-Scholes）
2. `run_optimized` 中 `us_options.covered_call_at_take_profit` 返回非 None 时走期权分支
3. NAV 计入期权权利金 + payoff
4. 配置 `us_backtest.options.enabled = true`

阶段1 的接口设计保证阶段2 无需改动 `run_optimized` 主循环结构。
