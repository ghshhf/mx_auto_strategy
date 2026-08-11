# PITFALLS.md — 项目历史踩坑日志

> **目的**：记录本项目（mx_auto_strategy，三市场量化回测研究引擎）历史上反复踩过的坑。
> 给"未来的 AI / 未来的自己"看的——改代码、加数据、跑回测前先读这一份，能少走很多弯路。
> 维护方式：每踩一个新坑就追加一节，旧坑若已修复就标注 `【已修复】`。

---

## §1 数据层坑（最致命，删错/用错会静默污染回测）

- **`*_em` 文件名 ≠ eastmoney 数据源【重大误解点】**
  记忆里写"eastmoney 已死，现用腾讯 `web.ifzq.gtimg.cn` 后复权周线"。但**活跃代码 `ashare_backtest/tencent_hfq_rebuild.py` 产出的是 `ashare_weekly_em/`、`ashare_panel_close_em.csv`、`ashare_panel_volume_em.csv`**——文件名沿用了旧 `_em` 后缀，实际已是腾讯数据。
  → **切勿按文件名判断数据源**。`ashare_weekly_em/`、`ashare_panel_close_em.csv`、`ashare_panel_volume_em.csv` 都是**活跃、被 `backtest_engine.py` 读写**的，删了回测直接崩。
  → 真正的废弃 eastmoney 残留是显式带 `OLD_eastmoney_bak` / `.bak9` 后缀的，已于 2026-08-11 清理。

- **活跃 A 股面板清单（勿动）**：
  `ashare_panel_close.csv`（默认）、`ashare_panel_close_em.csv`、`ashare_panel_volume_em.csv`（均腾讯后复权）、`ashare_weekly_em/<code>.csv`（逐标的原始周线）、`macro_monthly.csv`、`valuation_daily.csv`。
  `ashare_daily/`、`ashare_weekly/`（无后缀）、`ashare_weekly_hfq/`、`ashare_panel_close_hfq.csv`、`ashare_panel_ohlc*.csv`、`_mx_raw/`、`*_OLD_eastmoney_bak`、`*.bak9` 均已确认**无任何代码引用、且未被 git 跟踪**，属孤儿，已删。

- **美股 SOX 原始数据**：`us_stocks/data/raw_sox_historyofmarket.json`（502K）被 `us_stocks/extend_panel_real_indices.py` 读取，**勿删**（非重新生成则美股面板缺 SOX 真实指数）。

- **加密面板**：`crypto_stocks/data/weekly_adjclose_crypto50.csv`（主，61→62 币）与 `weekly_adjclose_crypto50_10y.csv`（10y，621 周）是回测唯一数据源。增币须同时回填两面板对齐日期（见 `_add_trb_backfill.py` 模板），且早期空缺列引擎按周自动排除，不会报错。

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
- `ashare_backtest/data/ashare_weekly_em_OLD_eastmoney_bak/`（4.3M）
- `ashare_backtest/data/ashare_panel_close_em.csv.OLD_eastmoney_bak`
- `ashare_backtest/data/ashare_panel_close.csv.bak9`
- `ashare_backtest/data/ashare_panel_close_hfq.csv`、`ashare_panel_ohlc.csv`、`ashare_panel_ohlc_hfq.csv`（共 ~6.4M）
- `ashare_backtest/data/_mx_raw/`（564K 原始 dump）
- `ashare_backtest/data/ashare_daily/`（58 文件 6.2M，无引用，研究用周线）
- `ashare_backtest/data/ashare_weekly/`（106 文件 4.1M）、`ashare_weekly_hfq/`（106 文件 4.4M，eastmoney 时代孤儿周线）
- 根目录 `_opt_weights.log`、`_verify_weights.log`（未跟踪 scratch 日志）

保留待确认（未删）：`crypto_stocks/_scratch_*.py` 等草稿脚本（19 个，无外部 import）、`E:\xmanbian` 根目录 mx 相关残留（`mx_backtest_*.html`、`_mx_src/`、`mx_auto_strategy_*.md`、`_qa_verify/`、`mx_hk_design/`、`mx_backtest_run/` 等）——见对话确认。

**回收空间**：`ashare_backtest/data` 由 ~25M+ 降至 5.5M。
