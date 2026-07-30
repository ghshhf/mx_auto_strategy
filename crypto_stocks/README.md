<!-- CATEGORY: crypto | 加密分类 | AUTO-CLASSIFY: yes -->
<!-- CLASSIFY_KEYWORDS: crypto, 加密, BTC, ETH, OKB, bitcoin, ethereum, crypto backtest, 加密回测, 加密策略 -->
# 加密分类 (Crypto) — mx_auto_strategy 加密回测

> ## ⚠️ 2026-07-31 真相化（必读）
> 本目录原 README 把 **V5.1「10 年 ≈ 42,484x」当作 FINAL 结论**，经核查**该数字不可信、不可复现**，原因：
> 1. **回测引擎丢失**：`backtest_v1.py` / `backtest_v2.py` 从未进 git、已彻底删除（全仓无任何 `run_backtest` 定义），`realistic_validation.py` 一 import 即崩 —— 整套系统此前**无法复现**。
> 2. **数据是合成的**：50 币面板由 `generate_synthetic_*` 生成（进攻币纯虚构，仅 BTC 锚真实价），**不是真实成交价**。
> 3. **真实 API 被墙**：Binance / OKX / CoinGecko 在本机沙箱**全部不可达**（直连 + 代理 3067 均失败），真数据拉不到（同 A 股东财被墙）。
> 4. **过拟合铁证**：遗留的 `realistic_validation_results.json` 显示 walk-forward **训练期 1028x → 测试期 22x**（即便在合成数据上已是崩塌式衰减）。
>
> **已做的修复**（2026-07-31）：① 重建 `backtest_v2.py` 引擎（可复现，严查前视）；② 重写 `crypto_hist_data.py` 覆盖全部 57 币真实周K线（Binance 主 / OKX 备，上市前留空）；③ 本文档真相化。
> **诚实结论**：crypto 第三策略的**真实倍数尚未产生**——必须在可联网环境跑 `crypto_hist_data.py` 拉真实数据，再喂 `backtest_v2.py` 才有资格谈倍数。详见文末「真相化与重建路线」。

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

### V5.1（设计稿，**数字均为合成数据，不可信**，见表下注）

> ⚠️ **这些是 `generate_synthetic_*` 合成数据的产物，不是真实成交价回测**。引擎 `backtest_v2.py` 此前丢失、现已重建；真实倍数须用 `crypto_hist_data.py` 拉真实数据后重测。下表仅保留为**设计目标参考**，不得当作已实现业绩。

| 指标 | 理想数据 | 真实摩擦+滑点 | 说明 |
|---|---|---|---|
| 10 年收益倍数 | **46,238x** | **42,484x** *(合成)* | 1 万 → 4.25 亿（合成数据，不可信） |
| BTC 买入持有 | 631x | 631x | 同期基准（合成锚定） |
| 策略 vs BTC 超额 | +7,234% | +6,638% | 选币 + 动量 + 防御 |
| 最大回撤 | −32.9% | −30.8% | 合成数据回撤更小 |
| Sharpe 比率 | 3.68 | 3.03 | 周频, 无风险利率=0 |
| 真实/理想收益比 | — | **92%** | 真实摩擦仅损失 8% |

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

### V2 (旧版, 10 年, Crypto50)

| 指标 | 数值 | 说明 |
|---|---|---|
| 10 年收益倍数 | 56,878x | V5.1 前身 |
| BTC 买入持有 | 631x | 同期基准 |
| 纯防御 3 币 | 539x | 仅 BTC+ETH+OKB |
| 策略 vs BTC 超额 | +8,915% | 选币 + 动量 + 自适应防御 |
| BTC 最大回撤 | −84.8% | 2022 加密冬天 |
| 策略最大回撤 | −52.5% | 改善 32pp |
| SelfGuard 保护版 | −34.1% MDD, 39,278x | 回撤再降 18pp |
| Sharpe 比率 | 3.94 | 周频, 无风险利率=0 |

### V1 (7.3 年, Crypto3, 三档市况)

| 指标 | 数值 |
|---|---|
| 策略倍数 | 137x |
| BTC 基准 | 15.6x |
| 策略回撤 | −59.7% |

> **注意**：数据为合成数据（沙箱限制）。本地运行 `crypto_hist_data.py` 拉取真实数据。

---

## 2. 目录结构

```
crypto_stocks/
├── README.md                          # 本文件（加密分类标记 + 导航）
├── crypto_adoption.py                 # V1 篮子：BTC 防御 + ETH/OKB 进攻
├── crypto_adoption_v2.py             # V2 篮子：Crypto50 + 12 赛道 + 木头姐相位
├── crypto_hist_data.py               # 历史数据下载 (Binance 主 + OKX 备, 免费)
├── generate_synthetic_data.py        # V1 合成数据 (3 币, 7 年)
├── generate_synthetic_v2.py          # V2 合成数据 (50 币, 10 年)
├── backtest_v2.py                    # V2 引擎 (**2026-07-31 重建**, 50池/四档/木头姐选币/CrashGuard/VolTarget, 严查前视)
├── backtest_v2_results.json          # 遗留的*合成数据*结果 (不可信, 仅供参考)
├── crypto_hist_data.py               # **2026-07-31 重写**: 真实周K线下载, 覆盖全57币(Binance主/OKX备, 上市前留空)
├── generate_synthetic_data.py        # ⚠ 合成数据生成 (V1/V2/V3) — 仅用于管线测试, **非真实业绩**
├── generate_synthetic_v2.py
├── generate_synthetic_v3.py
├── realistic_validation.py           # 遗留验证脚本 (import 已重建的 backtest_v2 即可跑)
├── data/
│   ├── weekly_adjclose_crypto3.csv    # 3防御币 (crypto_hist_data 旧版产物)
│   ├── weekly_adjclose_crypto50.csv   # ⚠ 当前为合成数据; 真实版须重跑 crypto_hist_data.py
│   └── weekly_adjclose_crypto50_v3.csv # 合成 V3 (含插针/rug)
└── figs/
    ├── v1_*.png                      # V1 图表
    └── v2_*.png                      # V2 图表 (净值/回撤/市况时间轴)
```

> **注意**：原 `backtest_v1.py` 已丢失（从未进 git）；`crypto_adoption.py`(V1篮子) 仍在。所有"结果"Json 均为合成数据产物。

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

# 1. 下载真实数据 (需在【可联网环境】跑; 本机沙箱 Binance/OKX 被墙)
python3 crypto_hist_data.py            # -> data/weekly_adjclose_crypto50.csv (真实版)

# 2. 跑重建引擎 (消费上述 CSV; 合成数据仅自检, 数字不可信)
python3 backtest_v2.py                  # 默认 V5: cost=10bps, offense_n=3
python3 backtest_v2.py --offense-n 5 --crash-thr -0.15 --vol-target 0.60   # 加 CrashGuard+VolTarget

# 3. 查看篮子定义
python3 crypto_adoption_v2.py
```

依赖：`pandas`, `numpy`（用 `G:\venv\quant\Scripts\python.exe`，含 pandas 3.0.5）。真实数据下载仅用标准库 `urllib`，无需 key。

> ⚠️ **本机沙箱网络限制**：Binance / OKX / CoinGecko 全部不可达（直连 + 代理 3067 均失败），故真实数据**只能在有出境网络的环境拉取**。拉到后覆盖 `data/weekly_adjclose_crypto50.csv`，再跑 `backtest_v2.py` 即得真实倍数。

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
| 回测引擎丢失 | `backtest_v1.py`/`backtest_v2.py` 从未进 git、已彻底删除；`realistic_validation.py` import 即崩 → 不可复现 |
| 数据是合成的 | 50 币面板由 `generate_synthetic_*` 生成（进攻币纯虚构，仅 BTC 锚真实价） |
| 真实 API 被墙 | Binance/OKX/CoinGecko 本机沙箱全不可达（直连+代理3067均失败）；下载器原仅覆盖 3 币 |
| 过拟合铁证 | 遗留 `realistic_validation_results.json`：walk-forward 训练 1028x → 测试 **22x** |

### 6.2 已完成的修复
1. ✅ **重建 `backtest_v2.py`**：防御核(BTC/ETH/OKB)+进攻TopN动量+四档市况+CrashGuard+VolTarget+相位倾斜；严格前视防护（选币/市况只用 ≤t 数据）；消费 weekly_adjclose CSV，真数据可无缝替换。合成数据自检通过（不崩、指标可算）。
2. ✅ **重写 `crypto_hist_data.py`**：由 `crypto_adoption_v2.COIN_META` 自动推导全 57 币 Binance/OKX 符号，上市前自然留空；`--check` 沙箱安全自检通过。
3. ✅ **README 真相化**：顶部警示 + §1/§5/§6 标注合成/过拟合，删除"FINAL 42,484x 已达成"误导。

### 6.3 待办（出真实倍数必经）
- [x] 重建回测引擎（可复现）
- [x] 扩展真实数据下载器到全 57 币（待联网环境执行）
- [ ] **在可联网环境跑 `crypto_hist_data.py` 拉真实周K线** → 覆盖 `data/weekly_adjclose_crypto50.csv`
- [ ] 跑 `backtest_v2.py` 出**真实倍数**（届时单独汇报，不沿用任何合成数字）
- [ ] 引擎前视/过拟合复审（真实数据到位后做 walk-forward + 参数敏感性）
- [ ] 实盘执行层（`market_adapter.py` 的 `BinanceAdapter` 预留）
- [ ] 日频回测（加密 T+0，周频可能不够）
- [ ] 与 A 股/美股跨资产组合回测

> **诚实口径**：crypto 第三策略的真实业绩**尚未产生**。任何倍数都必须来自 Binance/OKX 真实成交数据 + 重建引擎，且经 walk-forward 验证无过拟合后才可引用。

---

## 7. AI 自动分类规约

- **权威标记**：本文件首行 HTML 注释 `CATEGORY: crypto`、`AUTO-CLASSIFY: yes`。
- **关键词**：`crypto` / `加密` / `BTC` / `ETH` / `OKB` / `bitcoin` / `ethereum` / `crypto backtest` / `加密回测`。
- **归类动作**：把本目录整体归为「加密分类」，与根目录 A 股策略和 `us_stocks/` 美股分类并列，
  不混入 A 股或美股逻辑。新增加密相关文件请放入本目录并同步更新本 README。
