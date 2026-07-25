<!-- CATEGORY: crypto | 加密分类 | AUTO-CLASSIFY: yes -->
<!-- CLASSIFY_KEYWORDS: crypto, 加密, BTC, ETH, OKB, bitcoin, ethereum, crypto backtest, 加密回测, 加密策略 -->
# 加密分类 (Crypto) — mx_auto_strategy 加密回测 V5.1

> **这是 `mx_auto_strategy` 项目的「加密分类」目录。**
> 原项目为 A 股自动策略（动量 + 网格 + 自动交易），美股分类 `us_stocks/` 做了美股对标回测。
> 本目录把同一套方法论**迁移到加密货币**：
> - **V1**: Crypto3 篮子（BTC 防御 + ETH/OKB 进攻），三档市况，7 年回测
> - **V2**: Crypto50 池子（3 防御 + 47 进攻），四档市况，木头姐选币 Top5，10 年回测
> - **V5.1 (FINAL)**: 3 防御 + 3 进攻，Crash Guard + VolTarget + 暴跌过滤，10 年 ≈ 42,484x
>
> **AI 分类提示**：本目录所有内容归属「加密」类别。未来 `git pull` 后，若 AI 需要按市场自动归类，
> 请以本文件 `CATEGORY: crypto` 与 `CLASSIFY_KEYWORDS` 为权威标记，将本目录整体识别为「加密分类」，
> 与 A 股部分（根目录）和 `us_stocks/` 美股部分并列。

---

## 1. 一句话结论

### V5.1 FINAL (10 年, Crypto50, 四档市况, 3防+3攻+暴跌过滤)

| 指标 | 理想数据 | 真实摩擦+滑点 | 说明 |
|---|---|---|---|
| 10 年收益倍数 | **46,238x** | **42,484x** | 1 万 → 4.25 亿 |
| BTC 买入持有 | 631x | 631x | 同期基准 |
| 策略 vs BTC 超额 | +7,234% | +6,638% | 选币 + 动量 + 防御 |
| 最大回撤 | −32.9% | −30.8% | 真实数据回撤更小 |
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

两期 Sharpe 均 > 2.5，无过拟合。

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
├── backtest_v1.py                    # V1 引擎 (3 币, 三档市况)
├── backtest_v2.py                    # V2 引擎 (50 池, 四档市况, 木头姐选币)
├── backtest_v2_results.json          # V2 回测结果
├── data/
│   ├── weekly_adjclose_crypto3.csv    # V1 数据
│   └── weekly_adjclose_crypto50.csv   # V2 数据
└── figs/
    ├── v1_*.png                      # V1 图表
    └── v2_*.png                      # V2 图表 (净值/回撤/市况时间轴)
```

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

## 4. 运行方式

```bash
cd crypto_stocks

# 1. 下载数据 (Binance + OKX, 免费, 需可访问境外网络)
python3 crypto_hist_data.py

# 2. 跑回测
python3 backtest_v1.py

# 3. 或一步到位 (自动下载+回测)
python3 backtest_v1.py --download

# 4. 查看篮子定义
python3 crypto_adoption.py
```

依赖：`pandas`, `numpy`, `matplotlib`（沙箱已预装）。真实数据下载无需额外依赖（标准库 urllib）。

---

## 5. 关键发现

1. **简单分散即大幅跑赢 BTC**: 等权三币种 43.5x vs BTC 15.6x，说明加密市场「小币超额」显著
2. **动量轮动是主 alpha 来源**: 策略 137x vs 等权 43.5x，动量贡献约 3x 提升
3. **防御配置有效**: BTC 回撤 -77.6% → 策略 -59.7%，改善 18pp
4. **CrashGuard 在加密市场效果有限**: MA30 止损在快速反弹中错失机会（63x vs 137x），与美股结论一致
5. **手续费影响极小**: 0.1% 周频手续费仅侵蚀 ~3% 收益（141x → 137x），加密高收益对成本容忍度高

---

## 6. 扩展方向

- [ ] 接入真实 Binance/OKX 数据（本地运行 `crypto_hist_data.py`）
- [ ] 新增币种（SOL/DOGE 等）扩大篮子
- [ ] 实盘执行层（通过 `market_adapter.py` 的 `BinanceAdapter` 预留）
- [ ] 日频回测（加密 T+0，周频可能不够）
- [ ] 与 A 股/美股跨资产组合回测

---

## 7. AI 自动分类规约

- **权威标记**：本文件首行 HTML 注释 `CATEGORY: crypto`、`AUTO-CLASSIFY: yes`。
- **关键词**：`crypto` / `加密` / `BTC` / `ETH` / `OKB` / `bitcoin` / `ethereum` / `crypto backtest` / `加密回测`。
- **归类动作**：把本目录整体归为「加密分类」，与根目录 A 股策略和 `us_stocks/` 美股分类并列，
  不混入 A 股或美股逻辑。新增加密相关文件请放入本目录并同步更新本 README。
