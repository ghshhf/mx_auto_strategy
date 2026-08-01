<!-- CATEGORY: crypto | 加密分类 | AUTO-CLASSIFY: yes -->
<!-- CLASSIFY_KEYWORDS: crypto, 加密, BTC, ETH, OKB, bitcoin, ethereum, crypto backtest, 加密回测, 加密策略 -->
# 加密分类 (Crypto) — mx_auto_strategy 加密回测

> ## ⚠️ 2026-07-31 真相化（必读）
> 本目录原 README 把 **V5.1「10 年 ≈ 42,484x」当作 FINAL 结论**，经核查**该数字不可信、不可复现**，原因：
> 1. **回测引擎丢失**：`backtest_v1.py` / `backtest_v2.py` 从未进 git、已彻底删除（全仓无任何 `run_backtest` 定义），`realistic_validation.py` 一 import 即崩 —— 整套系统此前**无法复现**。
> 2. **数据是合成的**：50 币面板由 `generate_synthetic_*` 生成（进攻币纯虚构，仅 BTC 锚真实价），**不是真实成交价**。
> 3. **过拟合铁证**：遗留的 `realistic_validation_results.json` 显示 walk-forward **训练期 1028x → 测试期 22x**（即便在合成数据上已是崩塌式衰减）。
>
> **已做的修复**（2026-07-31）：① 重建 `backtest_v2.py` 引擎（可复现，严查前视）；② 重写 `crypto_hist_data.py` 覆盖全部 57 币真实周K线（Binance 主 / OKX 备，上市前留空）；③ 本文档真相化。
> **真实数据已落地**（2026-07-31 当晚）：经 `127.0.0.1:3067` 代理，Binance/OKX **真实周K线已拉到**（`weekly_adjclose_crypto50.csv`，468 周 × 57 币，2017-08 ~ 2026-07，52 币有数据，5 币源缺失留空）。重建引擎跑出**真实倍数**（见 §1 真实表）。
> **诚实口径**：真实倍数仍含**幸存者偏差**（标的池为"现存主流币"清单，已死/下架币未纳入→偏高），且真实数据仅 2017 起（Binance 上币），非合成数据的"10 年"。倍数仅供方法论证，**非未来承诺**。
>
> ### 📌 真值速查（唯一可引用口径）
>
> | 状态 | 数字 | 口径 |
> |---|---|---|
> | ✅ **权威真值** | **100.6x**（MDD −63.5% / Sharpe 1.06） | 进攻 Top3，Binance/OKX **真实**周K线 |
> | ✅ **权威真值（防御档）** | **40.7x**（MDD −45.2% / Sharpe 1.11） | Top3 + Crash(−15%) + VolT(0.60)，**真实**数据 |
> | ❌ **已废弃** | ~~42,484x / 46,238x / 56,878x / 137x~~ | **合成数据 · 非实盘口径 · 已推翻**，不得引用 |
>
> **合成数据脚本已于 2026-08 从仓库移除**（`generate_synthetic_data.py` / `_v2` / `_v3`，经核查无任何模块 import 或调用）。
> **唯一实盘数据路径**：`crypto_hist_data.py` —— 经 `127.0.0.1:3067` 代理从 **Binance（主）/ OKX（备）** 拉取真实周K线，产出 `data/weekly_adjclose_crypto50.csv`，再由 `backtest_v2.py` 消费。

> **这是 `mx_auto_strategy` 项目的「加密分类」目录。**
> 原项目为 A 股自动策略（动量 + 网格 + 自动交易），美股分类 `us_stocks/` 做了美股对标回测。
> 本目录把同一套方法论**迁移到加密货币**（用户已决定 crypto 作为继 A 股、美股后的**第三策略**，不再仅是额度汇总）：
> - **V1**: Crypto3 篮子（BTC 防御 + ETH/OKB 进攻），三档市况，7 年回测（设计）
> - **V2**: Crypto50 池子（3 防御 + 进攻），四档市况，木头姐选币，10 年回测（设计）
> - **引擎重建 (2026-07-31)**: `backtest_v2.py` 恢复可复现；真实数据通道 `crypto_hist_data.py` 覆盖全 57 币
>
> **AI 分类提示**：本目录所有内容归属「加密」类别。未来 `git pull` 后，若 AI 需要按市场自动归类，
> 请以本文件 `CATEGORY: crypto` 与 `CLASSIFY_KEYWORDS` 为权威标记，将本目录整体识别为「加密分类」，
> 与 A 股部分（根目录）和 `us_stocks/` 美股部分并列。

---

## 1. 一句话结论

### ✅ 真实数据回测（Binance/OKX 周K线，2017-08 ~ 2026-07，468 周 × 52 有数据币，重建引擎 `backtest_v2.py`）

> 防御核 BTC/ETH/OKB（周频再平衡回目标权重）+ 进攻 TopN 动量（木头姐选币，仅用 ≤t 数据，严查前视）+ 四档市况 + 可选 Crash Guard + Vol Target。成本 10bps/单边。
> ⚠️ **含幸存者偏差**：标的池="现存主流币"清单，已死/下架小币未纳入 → 倍数偏高。真实数据仅 2017 起（Binance 上币），窗口约 9 年。

| 配置 | 倍数 | CAGR | MDD | Sharpe | 避险周 |
|---|---|---|---|---|---|
| 进攻 Top3（无防御层） | **100.6x** | 67.1% | −63.5% | 1.06 | 0 |
| 进攻 Top5 | 56.9x | 56.8% | −62.2% | 1.01 | 0 |
| **Top3 + Crash(−15%) + VolT(0.60)** | **40.7x** | 51.1% | **−45.2%** | 1.11 | 330 |
| Top5 + Crash + VolT | 30.0x | 46.0% | −45.2% | 1.07 | 349 |

- **真实倍数 ≈ 100x（进攻 Top3）/ ≈ 41x（加防御层）**，远超同期 BTC 买入持有（2017 $4,086 → 2026 $64,788 ≈ **15.9x**）。加密动量小币超额显著，与美股/ A 股同方法论结论一致（选币+动量+纪律跑赢基准）。
- **MDD 是crypto 结构性难题**：即便加 Crash Guard + Vol Target，MDD 仍 −45%（加密单周 −20~−40% 是常态，反应式避险砍不掉趋势内波动）。要再压 MDD 只能降进攻仓位权重，代价是倍数。
- 对比 A 股（16x/−22%）、美股（23x/−48%）：crypto 倍数更高但回撤也更暴烈，**风险收益比（Sharpe ≈1.1）反而更低**——高收益靠的是高波动，不算"免费午餐"。

### ❌ V5.1（**合成数据 · 非实盘口径 · 已废弃**）

> ⚠️ **下表所有数字均为 `generate_synthetic_*` 合成数据的产物 —— 合成数据 · 非实盘口径 · 已废弃。**
> 进攻币价格为**纯虚构随机序列**（仅 BTC 锚定真实价），不是真实成交价，因此 **42,484x / 46,238x / 56,878x / 137x 等一切倍数均不成立、已被推翻**。
> 权威真值请看上方 §1「✅ 真实数据回测」表：**进攻 Top3 = 100.6x**、**Top3+Crash+VolT = 40.7x（防御档）**。
> 下表仅保留为**历史教训**（记录"合成数据能编出多离谱的收益"），**任何场合不得引用为已实现业绩**。

| 指标 | 理想数据 | 真实摩擦+滑点 | 说明 |
|---|---|---|---|
| 10 年收益倍数 | **46,238x** *(合成·已废弃)* | **42,484x** *(合成·已废弃)* | 1 万 → 4.25 亿 —— **纯合成数据虚构，不可信** |
| BTC 买入持有 | 631x *(合成)* | 631x *(合成)* | 同期基准（合成锚定，非真实 BTC 走势） |
| 策略 vs BTC 超额 | +7,234% *(合成)* | +6,638% *(合成)* | 建立在虚构价格上，无意义 |
| 最大回撤 | −32.9% *(合成)* | −30.8% *(合成)* | 合成数据回撤失真偏小（真实为 −63.5%） |
| Sharpe 比率 | 3.68 *(合成)* | 3.03 *(合成)* | 真实值仅 ≈1.06，合成高估约 3 倍 |
| 真实/理想收益比 | — | **92%** *(合成)* | 该结论同样基于合成数据，不成立 |

### V5.1 核心逻辑（三条铁律）

1. **防御端不动**: BTC 50% + ETH 30% + OKB 20%，长期持有永不卖出
2. **跌多了不碰**: 进攻代币近 2 周单周跌超 20% 直接排除（出事/插针不赌）
3. **整体大跌就避险**: 组合回撤超 15% 触发 Crash Guard，砍仓转稳定币

### Walk-Forward 验证 (5+5 年, 带滑点)

| 期间 | 收益 | MDD | Sharpe |
|---|---|---|---|
| Train 2016-2020 | 1,222x | −30.8% | 3.39 |
| Test 2021-2025 | 20x | −27.5% | 2.68 |

两期 Sharpe 均 > 2.5，但 **Train 1,222x → Test 20x 的崩塌式衰减本身就是过拟合铁证**（且这还只是合成数据上的表现，真实数据只会更严峻）。原「无过拟合」结论**不成立**。

### 赛道分类 (12 个赛道, 54 个进攻代币)

| 赛道 | 渗透率 | 相位 | 权重乘子 | 代表代币 |
|---|---|---|---|---|
| L1 公链 | 25% | 加速 | 1.35x | SOL, ADA, AVAX, NEAR |
| L2 扩容 | 18% | 加速 | 1.35x | ARB, OP, MATIC |
| DeFi | 12% | 加速 | 1.35x | UNI, LINK, AAVE, MKR |
| AI+加密 | 3% | 加速 | 1.35x | FET, RENDER, TAO |
| 模块化 | 8% | 加速 | 1.35x | TIA, DYM |
| RWA | 1% | 加速 | 1.35x | ONDO, POLYX |
| DePIN | 2% | 早期 | 1.15x | HNT, PEAQ |
| 存储 | 5% | 早期 | 1.15x | FIL, AR |
| 隐私 | 3% | 早期 | 1.15x | ZEC, DASH |
| DeFi 借贷 | 20% | 饱和 | 0.65x | AAVE, COMP |
| DEX | 15% | 饱和 | 0.65x | UNI, CRV |
| GameFi | 8% | 饱和 | 0.65x | AXS, GALA |

> **已排除**: Meme 赛道（回测验证亏钱）、LSD 赛道（导致权重重复计算）

### V2 (旧版, 10 年, Crypto50) — **合成数据 · 非实盘口径 · 已废弃**

> ⚠️ 同为 `generate_synthetic_*` 合成数据产物，**全表已废弃**，仅存档。权威真值见 §1 真实表（100.6x / 40.7x）。

| 指标 | 数值 | 说明 |
|---|---|---|
| 10 年收益倍数 | 56,878x *(合成·已废弃)* | V5.1 前身 |
| BTC 买入持有 | 631x | 同期基准 |
| 纯防御 3 币 | 539x | 仅 BTC+ETH+OKB |
| 策略 vs BTC 超额 | +8,915% | 选币 + 动量 + 自适应防御 |
| BTC 最大回撤 | −84.8% | 2022 加密冬天 |
| 策略最大回撤 | −52.5% | 改善 32pp |
| SelfGuard 保护版 | −34.1% MDD, 39,278x | 回撤再降 18pp |
| Sharpe 比率 | 3.94 | 周频, 无风险利率=0 |

### V1 (7.3 年, Crypto3, 三档市况) — **合成数据 · 非实盘口径 · 已废弃**

| 指标 | 数值 |
|---|---|
| 策略倍数 | 137x *(合成·已废弃)* |
| BTC 基准 | 15.6x *(合成)* |
| 策略回撤 | −59.7% *(合成)* |

> ⚠️ **合成数据 · 非实盘口径 · 已废弃**（沙箱限制时期的虚构序列）。权威真值见 §1 真实表。
> 真实数据已由 `crypto_hist_data.py` 经代理从 Binance/OKX 拉取落地，无需再生成合成数据。

---

## 2. 目录结构

```
crypto_stocks/
├── README.md                          # 本文件（加密分类标记 + 导航）
├── crypto_adoption.py                 # V1 篮子：BTC 防御 + ETH/OKB 进攻
├── crypto_adoption_v2.py              # V2 篮子：Crypto50 + 12 赛道 + 木头姐相位
├── crypto_hist_data.py                # ✅ **唯一实盘数据路径** (2026-07-31 重写): 经 3067 代理拉 Binance主/OKX备
│                                      #    真实周K线, 覆盖全 57 币, 上市前留空
├── backtest_v2.py                     # V2 引擎 (2026-07-31 重建, 50池/四档/木头姐选币/CrashGuard/VolTarget, 严查前视)
├── backtest_v1_results.json           # 遗留*合成数据*结果 (已废弃, 仅存档)
├── backtest_v2_results.json           # 遗留*合成数据*结果 (已废弃, 仅存档)
├── realistic_validation.py            # 遗留验证脚本 (import 已重建的 backtest_v2 即可跑)
├── realistic_validation_results.json  # 遗留*合成数据*walk-forward 结果 (已废弃, 过拟合证据)
├── data/
│   ├── weekly_adjclose_crypto3.csv     # 3防御币 (crypto_hist_data 旧版产物)
│   ├── weekly_adjclose_crypto50.csv    # ✅ 真实周K线 (468周 × 57币, 2017-08~2026-07, 52币有数据)
│   └── weekly_adjclose_crypto50_v3.csv # ⚠ 合成 V3 遗留面板 (已废弃, 勿用于回测)
└── figs/
    ├── v1_*.png                       # V1 图表 (基于合成数据, 已废弃)
    └── v2_*.png                       # V2 图表 (净值/回撤/市况时间轴)
```

> **合成数据脚本已移除（2026-08）**：`generate_synthetic_data.py` / `generate_synthetic_v2.py` / `generate_synthetic_v3.py` 三个文件已从仓库删除。
> 删除前已全仓核查：**无任何模块 `import` 或调用它们**（`realistic_validation.py` 顶部注释明确写着"不依赖 generate_synthetic_v3"），删除不影响任何可运行路径。
> 此后 **crypto 子系统只有一条数据路径**：`crypto_hist_data.py`（真实 Binance/OKX，经 `127.0.0.1:3067` 代理）→ `data/weekly_adjclose_crypto50.csv` → `backtest_v2.py`。**不再存在生成合成数据的能力，从源头杜绝假倍数回流。**
>
> 🔧 **已知残留（不影响运行，待后续代码任务清理）**：`realistic_validation.py:103` 有一行 `print` 提示文案仍写着"先运行 `generate_synthetic_v3.py`"，该脚本已删除，此提示**已失效**。
> 这只是一个字符串提示、**不是 import 也不是调用**，不会导致任何 ImportError。本次为纯文档任务、不改 `.py`，故保留原样。
> 若触发该分支（V3 合成面板不存在），正确做法是**跑 `crypto_hist_data.py` 拉真实数据**，而不是再生成合成数据。
>
> **注意**：原 `backtest_v1.py` 已丢失（从未进 git）；`crypto_adoption.py`(V1篮子) 仍在。所有遗留 `*_results.json` 均为合成数据产物，**已废弃**。

---

## 3. 方法论（与 A 股 / 美股同源，迁移到加密）

### 3.1 篮子 (crypto_adoption.py)
- **Crypto3**: BTC（防御，数字黄金）+ ETH（进攻，智能合约平台）+ OKB（进攻，交易所生态）
- 类比 A 股「蓝筹防御 + 成长进攻」和美股「KO/ABBV 防御 + 48 进攻」
- 加密特色：无行业分类，按「价值存储(L1) / 智能合约(L1) / 交易所代币(L2)」分层

### 3.2 信号 (backtest_v1.py)
- **市况判定**: BTC 价格偏离 MA10 → weak/flat/strong 三档（加密波动大，带宽 8%）
- **动量轮动**: ETH/OKB 按过去 12 周动量排名，动态分配进攻权重
- **仓位配置**: 弱市 60%BTC+20%进攻+20%现金，强市 30%BTC+55%进攻+15%现金
- **成本建模**: 单边 0.1%（Binance 标准 maker/taker 费率）

### 3.3 保护
- **CrashGuard(MA30)**: BTC 跌破 30 周均线 → 缩仓 70%，跌破 20% → 清仓
- **VolTarget(60%)**: 组合年化波动 > 60% → 超额部分转稳定币

### 3.4 加密 vs 股票的关键差异

| 维度 | A 股 | 美股 | 加密 |
|---|---|---|---|
| 交易时间 | 工作日 9:30-15:00 | 工作日 9:30-16:00 | 7x24 全天候 |
| T+N | T+1 | T+1 (部分 T+0) | T+0 |
| 涨跌停 | ±10%/20% | 无 | 无 |
| 复权 | 需要 | 需要 | 不需要 |
| 估值 | PE/PB/换手率 | PE/PB | 市值/NTVL/活跃地址 |
| 防御资产 | 蓝筹/CWB | KO/ABBV/CWB | 稳定币(USDT) |
| 市况基准 | 沪深300 | SPY | BTC |

---

## 4. 运行方式（诚实流程）

```bash
cd crypto_stocks

# 0. 先看符号映射是否正确 (沙箱安全, 不联网)
python3 crypto_hist_data.py --check

# 1. 下载真实数据 (经 127.0.0.1:3067 代理 Binance/OKX 可达; 脚本自动读 HTTPS_PROXY 环境变量)
python3 crypto_hist_data.py            # -> data/weekly_adjclose_crypto50.csv (真实版, 已生成)

# 2. 跑重建引擎 (消费上述 CSV; 真实数据即真实倍数)
python3 backtest_v2.py                  # 默认 V5: cost=10bps, offense_n=3
python3 backtest_v2.py --offense-n 5 --crash-thr -0.15 --vol-target 0.60   # 加 CrashGuard+VolTarget

# 3. 查看篮子定义
python3 crypto_adoption_v2.py
```

依赖：`pandas`, `numpy`（用 `G:\venv\quant\Scripts\python.exe`，含 pandas 3.0.5）。真实数据下载仅用标准库 `urllib`（自动走 `HTTPS_PROXY` 代理 / 留空则直连），无需 key。

> ✅ **真实数据已生成**：`data/weekly_adjclose_crypto50.csv`（468 周 × 57 币，2017-08 ~ 2026-07，52 币有数据）。若需刷新，重跑 `crypto_hist_data.py` 即可（代理可达 Binance/OKX，无需 key）。

---

## 5. 关键发现

> ⚠️ 本节数字来自**丢失的 V1 引擎 + 合成数据**（43.5x / 137x 等），属设计期探索性结论，**不可当作真实业绩**。仅保留作方法论直觉参考。

1. **简单分散即大幅跑赢 BTC**: 等权三币种 43.5x vs BTC 15.6x，说明加密市场「小币超额」显著
2. **动量轮动是主 alpha 来源**: 策略 137x vs 等权 43.5x，动量贡献约 3x 提升
3. **防御配置有效**: BTC 回撤 -77.6% → 策略 -59.7%，改善 18pp
4. **CrashGuard 在加密市场效果有限**: MA30 止损在快速反弹中错失机会（63x vs 137x），与美股结论一致
5. **手续费影响极小**: 0.1% 周频手续费仅侵蚀 ~3% 收益（141x → 137x），加密高收益对成本容忍度高

---

## 6. 真相化与重建路线（2026-07-31）

### 6.1 诊断结论（为什么旧 42,484x 不可信）
| 问题 | 证据 |
|---|---|
| 回测引擎丢失 | `backtest_v1.py`/`backtest_v2.py` 从未进 git、已彻底删除；`realistic_validation.py` import 即崩 → 不可复现（已重建） |
| 数据是合成的 | 50 币面板由 `generate_synthetic_*` 生成（进攻币纯虚构，仅 BTC 锚真实价） |
| 真实 API（已解决） | Binance/OKX/CoinGecko 经 `127.0.0.1:3067` 代理**现已可达**；`crypto_hist_data.py` 重写为覆盖全 57 币 → 真实面板已落地 |
| 过拟合铁证 | 遗留 `realistic_validation_results.json`：walk-forward 训练 1028x → 测试 **22x** |

### 6.2 已完成的修复
1. ✅ **重建 `backtest_v2.py`**：防御核(BTC/ETH/OKB)+进攻TopN动量+四档市况+CrashGuard+VolTarget+相位倾斜；严格前视防护（选币/市况只用 ≤t 数据）；消费 weekly_adjclose CSV，真数据可无缝替换。合成数据自检通过（不崩、指标可算）。
2. ✅ **重写 `crypto_hist_data.py`**：由 `crypto_adoption_v2.COIN_META` 自动推导全 57 币 Binance/OKX 符号，上市前自然留空；`--check` 沙箱安全自检通过。
3. ✅ **README 真相化**：顶部警示 + §1/§5/§6 标注合成/过拟合，删除"FINAL 42,484x 已达成"误导。

### 6.3 待办（出真实倍数必经）
- [x] 重建回测引擎（可复现）
- [x] 扩展真实数据下载器到全 57 币
- [x] **在可联网环境跑 `crypto_hist_data.py` 拉真实周K线** → 已覆盖 `data/weekly_adjclose_crypto50.csv`（468 周 × 57 币）
- [x] 跑 `backtest_v2.py` 出**真实倍数** → **100.6x（Top3）/ 40.7x（Top3+Crash+VolT）**，见 §1
- [x] **移除合成数据脚本**（`generate_synthetic_*` ×3，确认无引用后删除，杜绝假数据回流）
- [ ] 引擎前视/过拟合复审（真实数据上做 walk-forward + 参数敏感性）
- [ ] 实盘执行层（`market_adapter.py` 的 `BinanceAdapter` 预留）
- [ ] 日频回测（加密 T+0，周频可能不够）
- [ ] 与 A 股/美股跨资产组合回测

> **诚实口径**：crypto 第三策略的**回测**真实倍数已产生（100.6x / 40.7x，真实 Binance/OKX 数据 + 重建引擎），但**实盘业绩仍为零**——从未真实下过一单。
> 该倍数含**幸存者偏差**（标的池为现存主流币，已死/下架币未纳入 → 偏高），窗口仅 2017 起约 9 年，且**尚未通过真实数据上的 walk-forward 过拟合复审**。
> 因此：可作为**方法论有效性的证据**引用，**不可作为未来收益承诺**，更不等于实盘可复制。

---

## 7. AI 自动分类规约

- **权威标记**：本文件首行 HTML 注释 `CATEGORY: crypto`、`AUTO-CLASSIFY: yes`。
- **关键词**：`crypto` / `加密` / `BTC` / `ETH` / `OKB` / `bitcoin` / `ethereum` / `crypto backtest` / `加密回测`。
- **归类动作**：把本目录整体归为「加密分类」，与根目录 A 股策略和 `us_stocks/` 美股分类并列，
  不混入 A 股或美股逻辑。新增加密相关文件请放入本目录并同步更新本 README。
