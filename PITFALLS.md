# PITFALLS.md — 项目历史踩坑日志

> **目的**：记录本项目（mx_auto_strategy，三市场量化回测研究引擎）历史上反复踩过的坑。
> 给"未来的 AI / 未来的自己"看的——改代码、加数据、跑回测前先读这一份，能少走很多弯路。
> 维护方式：每踩一个新坑就追加一节，旧坑若已修复就标注 `【已修复】`。

---

## §1 数据层坑（最致命，删错/用错会静默污染回测）

- **`*_em` 文件名 ≠ eastmoney 数据源【重大误解点】**
  记忆里写"eastmoney 已死，现用腾讯 `web.ifzq.gtimg.cn` 后复权周线"。但**活跃代码 `markets/ashare/tencent_hfq_rebuild.py` 产出的是 `ashare_weekly_em/`、`ashare_panel_close_em.csv`、`ashare_panel_volume_em.csv`**——文件名沿用了旧 `_em` 后缀，实际已是腾讯数据。
  → **切勿按文件名判断数据源**。`ashare_weekly_em/`、`ashare_panel_close_em.csv`、`ashare_panel_volume_em.csv` 都是**活跃、被 `backtest_engine.py` 读写**的，删了回测直接崩。
  → 真正的废弃 eastmoney 残留是显式带 `OLD_eastmoney_bak` / `.bak9` 后缀的，已于 2026-08-11 清理。

- **活跃 A 股面板清单（勿动）**：
  `ashare_panel_close.csv`（默认）、`ashare_panel_close_em.csv`、`ashare_panel_volume_em.csv`（均腾讯后复权）、`ashare_weekly_em/<code>.csv`（逐标的原始周线）、`macro_monthly.csv`、`valuation_daily.csv`。
  `ashare_daily/`、`ashare_weekly/`（无后缀）、`ashare_weekly_hfq/`、`ashare_panel_close_hfq.csv`、`ashare_panel_ohlc*.csv`、`_mx_raw/`、`*_OLD_eastmoney_bak`、`*.bak9` 均已确认**无任何代码引用、且未被 git 跟踪**，属孤儿，已删。

- **美股 SOX 原始数据**：`markets/us/data/raw_sox_historyofmarket.json`（502K）被 `markets/us/extend_panel_real_indices.py` 读取，**勿删**（非重新生成则美股面板缺 SOX 真实指数）。

- **加密面板**：`markets/crypto/data/weekly_adjclose_crypto50.csv`（主，61→62 币）与 `weekly_adjclose_crypto50_10y.csv`（10y，621 周）是回测唯一数据源。增币须同时回填两面板对齐日期（见 `_add_trb_backfill.py` 模板），且早期空缺列引擎按周自动排除，不会报错。

---

## §2 回测 / 前视偏差坑【已修复，但仍须警惕】

- **手写 `PHASE_HISTORY` / static 行业加速标注 = 前视偏差**。回测 2019 年即"知道"哪个行业会加速 → 倍数虚增 +18.2%~+37.2%（static 21.5x vs data 无前视 15.67x）。
  → 必须用 `tech_mode="data"`（只用 `[0,i]` 现算），`use_tech` / `trend_filter` **默认关闭**。任何"按历史标注给行业加权"的方案都先怀疑前视。

- **倍数增长来自参数，不来自数据变多**。固定旧参跑不同数据末日：589 周 23,218x → 619 周 18,360x（−20.9%）→ 621 周 18,378x。补的 7 个月恰是 crash+bear_bottom 段。**用户若问"数据多了是不是倍数更高"，答案是反的。**

- **样本外裁决**：12 变体无一 `|t|≥2`。全样本数字与逐年/样本外冲突时，**以逐年 + 样本外为准**。特性改进须做消融（单变量对照）+ walk-forward 双维度配对 t 检验（倍数 + MDD，`|t|≥2` 才算真改进）。

- **幸存者偏差严重**：去 Top5 −34.8%、去 Top10 −51.8%。所有 A 股倍数数字都含幸存者偏差，报头条须注明。

---

## §3 加密引擎（减半周期减仓）坑【主干，非做空】

- **减半周期按相位减仓是加密引擎主干（2026-08-11 确立）**，alpha 100% 来自 `halving_*_risk_scale`，与做空零关系。证据：强制关掉 `HALVING_PHASE_ADJUST['crash']` 的做空×2/MA 收紧，10y 结果一字不差。

- **翻开关前必确认子参数非空操作默认值【曾犯错】**：早先测 `enabled=True` 判"退化 10y 故默认关"是**测试错误**——三个 `risk_scale` 仍为 1.0，减仓分支根本没进去，只有激进做空项生效。**翻开关必须先确认 risk_scale 不是 1.0。**

- **三条反直觉铁律**：①见顶期 euphoria 必须满仓（改 0.5→10y 18,378x 崩到 4,580x）；②筑底期 bear_bottom 不能恢复仓位（设 1.0→MDD −43.5% 恶化到 −64.2%）；③预热起点 `ph=31` 月 ≫ 36 月（24,494x vs 9,315x）。

- **做空层去留**：10y 纯减仓（无做空）28,674x/−43.0% 优于含做空 24,494x/−43.5%；但 9y/5y/3y **含做空全胜**。walk-forward 倍数 t=+0.23（无显著差异）、MDD t=+2.60（纯减仓回撤显著更浅）。**默认保持含做空**（近期>全样本铁律），但须诚实标注做空在 MDD 上是显著代价。

- **回撤诊断【已修复】**：期权层（covered call / put / 做空）是"收益覆盖层"不是"崩盘保险"——崩盘段组合仍 63%~75% 满仓现货，做空只在 call 被行权后开（崩盘是跌，call 不被行权→贡献恒 0）。已修：默认开主动做空对冲（`short_proactive_ma=20, size=0.40`）。修复后 5y MDD −57.7%→−51.5%、3y −57.9%→−51.8%；10y MDD 现为 **−33% 档**（旧"权威真值 24,493x/−43.5%" 口径偏旧，勿直接对比）。

---

## §4 统计 / 计算坑

- **两资产收益相关性必须按日期对齐**：取 `set(date)∩`，对相邻公共日期算 `p[d1]/p[d0]-1`，再对两等长收益向量算 Pearson。
  → 错误做法 1：用"同周 A/B 比值对数"当收益率 → corr 假象 = 1.0000。
  → 错误做法 2：按**索引**对齐（A 起 2017、B 起 2020 错位）→ corr ≈ 0 也错。
  → 正确结果示例：`corr(TRB,BTC)=+0.51, beta≈1.19; corr(BTC,ETH)=+0.74`（健全性校验通过）。

---

## §5 框架 / 方法论坑（加密代币分析）

- **"买旧不买新"框架**：加密里买旧（活过周期=幸存者）≠ 回报高。TRB 是标准反面教材（2019 上线、活过 2022 熊、未归零，但 6y USD −81%、对 BTC −98.8%、MDD −94%、高 beta 1.19 零 alpha）。**幸存者筛查通过 ≠ 回报筛查通过。**

- **集中度量赛道 favor 老大非偏见【修正】**：一般"多赢共存非赢家通吃"，但**强网络效应/集中度量（如预言机 TVS）上不成立**。Tellor TVS 未进 DeFiLlama 预言机榜（门槛 ~$4M），Chainlink $34B——差 4 数量级。此类赛道应 favor incumbent，嫌弃利基 also-ran，证据支持，非偏见。

- **风险三过滤 + 三条纪律**：①内部 overhang（VC 解锁/创始人杠杆）有限且收敛→不列永久结构性风险；②价格/基本面背离=错杀论题非风险；③市场多赢共存非赢家通吃（见上修正）。免责声明须顶部/价格节/底部三处。

- **对标关系即核心强度（双刃）**：BCH 对标 BTC 占"数字现金"卡槽；但顶层基准对（BTC vs 黄金）亦会背离。

- **CMC id 须实测，勿猜**：Tellor CMC id = 4944（曾误猜 10108，浪费一轮）。加币前用 `pro-api.coinmarketcap.com/v1/cryptocurrency/map?symbol=X` 实测。

---

## §6 工程 / 环境坑

- **Python 环境**：默认 `python` 无 pandas。须用 quant venv：`G:/venv/quant/Scripts/python.exe`（pandas 3.0.5, plotly 6.9.0）。crypto 回测统一走它（约 49s/10y 档）。

- **Git Bash 下 Python 不认 `/e/` 挂载点** → 解析成 `e:\` → FileNotFoundError。Python 读写文件用 Windows 绝对路径（`C:/Users/21393/...`、`E:/xmanbian/...`）；`head`/`cp` 等 Git Bash 工具认 `/e/` 但 Python 不认。

- **代理 3067**：finance 数据（Yahoo/Coinbase/Bitfinex/Kraken）经 `http://127.0.0.1:3067` 可达；Binance api 经代理返回 HTTP 451 地理封锁（用 OKX/CMC 兜底）。`gh api` 经代理偶发断连（"wsarecv: connection forcibly closed"）→ 写重试循环（≤6 次，失败 sleep 1-2s）。git push 经代理：`git -c http.proxy=... -c https.proxy=... push origin <branch>`。

- **GitHub 操作**：master 分支已于 2026-08-07 删除，仅 `origin/main`（GitHub 默认分支=main，删除不被拦截）。**勿用 `git merge-base main master`**（master 非本地引用会报错假阴性）。gh git/refs API 须传完整 40 位 SHA。

---

## §7 项目状态 / 范围坑

- **A 股 live 自动交易（"剧本书写者"/live sim）已于 2026-08-08 永久搁置**，不再作为项目目标。项目重心 = **三市场量化回测研究引擎**（A 股 / 美股 / 加密）。`auto_trader.py`、`script_advisor.py`、`script_tracker.py`、`shadow_eval.py`、`grid_trader.py`、`ai_score.py`、`market_data.py`、`instrument.py` 等 live 基础设施虽仍被 `tests/` 引用，**未删除但非活跃方向**，改这些模块前先确认是否还在维护。

- **绝密/敏感**：用户曾贴 GitHub PAT 于对话（已提醒吊销）。`.env` 含 CMC key，被 `.gitignore` 排除，勿提交。

---

## §8 本次清理记录（2026-08-11）

删除（均 0 git 跟踪、0 代码引用，属孤儿/显式备份）：
- `markets/ashare/data/ashare_weekly_em_OLD_eastmoney_bak/`（4.3M）
- `markets/ashare/data/ashare_panel_close_em.csv.OLD_eastmoney_bak`
- `markets/ashare/data/ashare_panel_close.csv.bak9`
- `markets/ashare/data/ashare_panel_close_hfq.csv`、`ashare_panel_ohlc.csv`、`ashare_panel_ohlc_hfq.csv`（共 ~6.4M）
- `markets/ashare/data/_mx_raw/`（564K 原始 dump）
- `markets/ashare/data/ashare_daily/`（58 文件 6.2M，无引用，研究用周线）
- `markets/ashare/data/ashare_weekly/`（106 文件 4.1M）、`ashare_weekly_hfq/`（106 文件 4.4M，eastmoney 时代孤儿周线）
- 根目录 `_opt_weights.log`、`_verify_weights.log`（未跟踪 scratch 日志）

保留待确认（未删）：`markets/crypto/_scratch_*.py` 等草稿脚本（19 个，无外部 import）、`E:\xmanbian` 根目录 mx 相关残留（`mx_backtest_*.html`、`_mx_src/`、`mx_auto_strategy_*.md`、`_qa_verify/`、`mx_hk_design/`、`mx_backtest_run/` 等）——见对话确认。

**回收空间**：`markets/ashare/data` 由 ~25M+ 降至 5.5M。

---

## §9 MANTRA → CFG 替换记录（2026-08-11）

### 背景
RWA 赛道代币池中 MANTRA (OM) 被替换为 CFG (Centrifuge)。用户经链上数据深度研究后确认 MANTRA "特别差"，非单纯价格涨跌判断，而是项目基本面全面崩坏。

### MANTRA (OM) 的核心问题（七宗罪）

1. **团队控制 90% 流通量**：9.8 亿枚流通中 7.92 亿枚在团队单一钱包，真实流通仅 ~1.88 亿枚。高度控盘 = 价格操纵温床 [$TRAE_REF](https://blog.csdn.net/vv_lcmg88/article/details/147298510)。

2. **TVL 与估值完全脱节**：FDV 曾达 $153.9 亿（2025年3月），但 TVL 自 2023 年起仅维持在"几十万美元"级别。高估值零采用 = 纯叙事泡沫 [$TRAE_REF](https://www.aicoin.com/en/article/453950)。

3. **2025年4月崩盘 90%**：24 小时暴跌 89.2%。崩盘前 3 天，19 个疑似同一实体的钱包向 OKX 转入 1427 万 OM（约 $9100 万），构成内幕抛售嫌疑 [$TRAE_REF](https://www.aicoin.com/en/article/453950)。

4. **骗局起源 + 法律纠纷**：MANTRA DAO（2020）早期被指骗局，创始人 Calvin Ng 涉线上赌博 21Pink。2022 年 RioDeFi 起诉 MANTRA DAO 资产侵占，2024 年香港高等法院介入 [$TRAE_REF](https://www.aicoin.com/en/article/453950)。

5. **中东资本接管**：2023 年 FDV 跌至 $2000 万时被中东资本通过中间人收购，仅保留 CEO 职位。此后包装为 RWA 项目，2024 年在 Binance 实现 200 倍涨幅（高控盘+OTC 倒手）[$TRAE_REF](https://www.aicoin.com/en/article/453950)。

6. **代币经济操纵**：供应量从 8.88 亿翻倍至 17.77 亿，引入 3% 年通胀。废弃原 ERC-20 OM，重建为 MANTRA Chain 原生代币 [$TRAE_REF](https://www.aicoin.com/en/article/453950)。

7. **当前状态（2026）**：市值仅 ~$6270 万，价格 ~$0.0085，GitHub stars 91 / 3 个月 46 commits，DAO 国库缩至 14.1K，持币者仅 35.6K。联合创始人/CTO 全部离职 [$TRAE_REF](https://www.cryptopolitan.com/mantra-chain-tries-to-make-a-comeback-with-om-token-buybacks-stablecoin-and-rwa-tokenization-plans/)[$TRAE_REF](https://www.aicoin.com/en/article/453950)。

### CFG (Centrifuge) 的核心优势

1. **真实 TVL 爆发**：从 2025 年初 ~$5000 万增长至 2026 Q2 的 $16.8 亿（30 倍），由真实机构资产驱动 [$TRAE_REF](https://www.gate51.cloud/zh/blog/centrifuge-cfg-onchain-credit-tokenization-structure-and-full-risk-analysis)。

2. **顶级机构合作**：
   - **Coinbase** 指定 CFG 为首选代币化基础设施 + 战略入股 [$TRAE_REF](https://centrifuge.io/blog/centrifuge-q2-2026-recap)
   - **纽约人寿**（$8070 亿 AUM）首个代币化基金上线 Centrifuge [$TRAE_REF](https://centrifuge.io/blog/centrifuge-q2-2026-recap)
   - **Ethena** 竞标选定 Centrifuge，配置 $2.5 亿至 JAAA [$TRAE_REF](https://centrifuge.io/blog/centrifuge-q2-2026-recap)
   - **Kraken Institutional** 将 JAAA 列为首批合格托管 RWA [$TRAE_REF](https://centrifuge.io/blog/centrifuge-q2-2026-recap)
   - S&P 全球评级将 JTRSY 升至 'AAAf'（最高基金信用评级）[$TRAE_REF](https://centrifuge.io/blog/centrifuge-q1-2026-recap)

3. **真实产品采用**：JTRSY TVL 突破 $10 亿，JAAA 为旗舰信贷产品，deSPXA 提供 S&P 500 DeFi 敞口，已部署以太坊/Base/Arbitrum/Celo/Solana/Monad/Stellar/X Layer [$TRAE_REF](https://centrifuge.io/blog/centrifuge-q2-2026-recap)。

4. **技术标准输出**：ERC-7540（异步金库标准）由 Centrifuge 联合撰写，已合并入 OpenZeppelin 公共合约库 [$TRAE_REF](https://centrifuge.io/blog/centrifuge-q2-2026-recap)。

5. **合规创始人 + 长期愿景**：2017 年由 Lucas Vogelsang 等创立，2021 年与 MakerDAO 完成首笔 RWA 抵押贷款里程碑 [$TRAE_REF](https://www.gate51.cloud/zh/blog/centrifuge-cfg-onchain-credit-tokenization-structure-and-full-risk-analysis)。

6. **代币经济改善**：CFG 持币者 10,988（+16% QoQ），Q4 2025 启动费率开关从规模扩张转向盈利变现 [$TRAE_REF](https://centrifuge.io/blog/centrifuge-q4-2025-recap)。

7. **$10 亿赎回设施**：Grove Basin 承诺 $10 亿为 JTRSY 提供 7×24 USDC 即时赎回 [$TRAE_REF](https://centrifuge.io/blog/centrifuge-q2-2026-recap)。

### 回测影响
替换后 5y MDD 从 -51.5% → -30.1%（改善 21.4pp），5y 倍数从 ~1x → 7.69x。MANTRA 在面板中仅 24 周数据且持续下跌（-68.9%），严重拖累整体回撤。

### 教训（给未来 AI）
- **代币替换不能只看价格**：MANTRA 价格曾涨 200 倍，但 TVL/团队/链上活动全面崩坏。必须查链上数据（TVL、持币者分布、团队持仓、GitHub 活跃度、合作伙伴质量）。
- **RWA 赛道真伪鉴别**：真 RWA = 有机构级资产上链（CFG: BlackRock/Janus Henderson/纽约人寿）；伪 RWA = 纯叙事包装（MANTRA: 中东资本收购后贴 RWA 标签，TVL 几十万美元）。
- **高度控盘 = 红线**：团队持 90% 流通量 → 随时可砸盘，不是"有信心"而是"待出货"。
