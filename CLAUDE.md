# CLAUDE.md — mx_auto_strategy 智能体使用指南

> 本文件供 Claude Code / Cursor / Codex / 其他 AI 编程智能体自动读取。
> 任何 Agent clone 本仓库后，读此文件即可直接上手，无需用户额外解释。

---

## 这是什么

龙虾炒股大赛（模拟盘）自动交易系统 v6.18，核心模式叫**「剧本书写者」**：

- **防御端**：系统自治。从低 beta 蓝筹白名单自动选 Top3，按三档市况（弱势/平衡/强势）自动调仓位。
- **进攻端**：用户给方向就锁定用户方向，不给就走自适应主线（行业动量扫描）。
- **大方向**：用户直接写人话剧本（`user_script.md`），系统解析执行。

> 设计哲学：**防御端自律 + 进攻端剧本锁定 + 大方向甩剧本 = 不可能输。**

## 市场分类导航（智能体自动归类）

本仓库按**市场**分**三大类**，请按此归类与隔离：

- **A 股（主系统，默认根目录）**：龙虾炒股大赛模拟盘自动交易。依赖 `mx-moni` API、T+1、限价；含 `auto_trader.py` / `grid_trader.py` / `selector.py` / `weekly_theme.py` / `death_cross.py` / `tech_adoption.py`（⚠️ v6.18 验证含前视偏差, 默认关闭）等。回测在 `ashare_backtest/`（引擎 `backtest_engine.py`，面板由 `tencent_hfq_rebuild.py` 联网重建生成，**面板 CSV 未入库**）。回测框架含交易成本建模(v6.16)、walk-forward 双维度配对检验(v6.18)、ablation 单变量消融(v6.18)、幸存者偏差声明；v6.18 经样本外检验确认所有叠加层均不显著, 基线锁定 动量26+核心卫星+死叉。
- **美股（对标迁移，目录 `us_stocks/`）**：同一套方法论迁移到美股。US50 篮子（48 进攻 + KO/ABBV 防御）+ 动量轮动 + Walk-forward 样本外验证 + 崩盘保护 + 网格叠加。真实面板回测（含 AI 选股层 `us_backtest_ai.py`）结果见 `us_stocks/README.md`（⚠️ 早期 ~50x 为合成数据未计成本，仅供参照；真实值 22.48x）。权威分类标记为 `us_stocks/README.md` 首行 HTML 注释 `CATEGORY: us_stocks`。
- **加密（第三策略，目录 `crypto_stocks/`）**：同一套方法论迁移到加密货币，已由「仅额度汇总」升级为**独立第三策略**。Crypto50 池（BTC/ETH/OKB 防御核 + 进攻 TopN 动量）+ 12 赛道木头姐相位 + 四档市况 + CrashGuard + VolTarget + **期权三件套引擎**（`crypto_options_bt.py`）。真实数据经 `127.0.0.1:3067` 代理从 Binance/OKX 拉取（`crypto_hist_data.py`）。**权威真值（v6.18 期权审计）：期权增强头条 = 448.6x（CAGR 97.4% / MDD −57.6%），无期权基线进攻 Top3 = 100.6x（MDD −63.5%）／防御档 = 40.7x（MDD −45.2%）**；减半周期（opt-in，协议级确定性日期零后视）为**合法 regime 信号**，其 in-sample 拟合峰值 ~17000x（10 年面板真实数据可复现）是样本内上限非承诺值，真实样本外 Walk-forward = 274.8x（69% 保留）/ 切割 B = 3.4x。旧「42,484x」系**合成数据已废弃推翻**，与真实数据的 17000x **不可混淆**。权威分类标记为 `crypto_stocks/README.md` 首行 `CATEGORY: crypto`。

> 归类规则：涉及美股的代码、数据、报告一律放在 `us_stocks/` 内；涉及加密的一律放在 `crypto_stocks/` 内；涉及 A 股的放在根目录。三者逻辑互不混入。新增文件请同步更新对应目录的 `README.md`。

## 选股决策总则（智能体必须先读，这是系统灵魂）

用户给的是**板块方向**（如"打电力""打医药"），系统/智能体按以下四层顺序自动决策，**不要擅自加复杂规则**：

1. **剧本（主轴）**：用户提前写死的方向坐标，决定"打哪里"。锁定，不漂移。
2. **政策/新闻（置信度）**：依托相关政策、新闻面做共振确认——由**智能体运行时��己实时搜索**完成（智能体自带该功能，无需硬编码新闻源）。
3. **K线强弱（节奏）**：纯粹看技术面涨跌，判定**强势 / 中等 / 弱势**三档，决定仓位动作（弱势收敛防守、强势加攻、中等标准框架）。
4. **载体（买什么）**：方向定了之后买个股还是指数，**规则极简——个股太贵就买指数，否则买个股**。无需写复杂载体路由模块，智能体看单价自行判定。

> 前三层是叠加关系（方向→置信度→节奏），第四层是价格门槛问题不是算法问题。
> 新闻/政策面的获取交给智能体自身能力，系统不内置新闻爬取依赖（已有 `news_feed.py` 仅作离线兜底，非必需）。
> 加密资产：用户额度与股票并列，但属独立认知维度（不对外解释）。根目录 `crypto_data.py` 仍**仅做总资金汇总**（拉公开行情并入账本，不分析不选币）。
> 但**策略研究已独立成第三大类** `crypto_stocks/`（Crypto50 + 动量选币 + 四档市况，真实数据回测 100.6x / 防御档 40.7x）——注意区分：`crypto_data.py`=记账汇总，`crypto_stocks/`=策略回测，两者互不混入。
> 对普通人而言框架只需股票即可（年化~13%已足够）；crypto 波动极大（真实 MDD −63.5%），非必需。

---

## 智能体三步上手

### 1. 准备环境

```bash
git clone https://github.com/ghshhf/mx_auto_strategy.git
cd mx_auto_strategy
pip install pandas numpy matplotlib     # 仅回测/画图需要；实盘主流程只用标准库
export MX_APIKEY="你的mx-moni API key"   # 从环境变量读，绝不硬编码
```

> 📦 **依赖说明（已核实）**：本仓库**代码零引用 `requests`**（旧文档写的 `pip install requests` 是错的，已更正）。
> 所有 HTTP 请求走标准库 `urllib`，无需安装。第三方依赖只有三个，且**仅回测与绘图链路**用到：
> `pandas` / `numpy`（回测引擎）、`matplotlib`（净值图）。
> 只跑实盘主流程（`auto_trader.py`）时，**标准库即可，无需任何 pip 安装**。

### 2. 给用户「给方向」

> 🔒 **剧本已封印（2026-07-30 / W31）**：`user_script.md` 方向主轴已移交 AI（`script_advisor` + `ai_score`）。默认不再手写作业；智能体改方向请走 AI 路径。重新启用手写需 `playbook.sealed=false` 并清除封印横幅。

直接编辑 `user_script.md` 写人话即可（仅限封印解除后），例如：

```
下周主攻电力和医疗，防御端你定，弱势市多留现金。
```

系统关键词映射（写口语就行）：

| 你写的 | 系统理解 |
|---|---|
| `电力` / `电网` | 进攻端叠加电力方向 |
| `医疗` / `医药` / `药` | 进攻端叠加医药方向 |
| 不写进攻方向 | 系统走自适应主线 |
| `防御端你定` / 不写 | 系统从防御白名单自治 |

`user_script.md` 会在运行时被解析并同步进 `weekly_theme.json`（machine-readable）。

### 3. 运行

```bash
python3 auto_trader.py --mode select   # 仅选股评分，不交易（干跑）
python3 auto_trader.py                 # 实际下单（需 MX_APIKEY + 模拟盘账户）
```

交易节奏：**每天手动触发 3 次**（10:00 / 12:00 / 14:00），无自动 cron、无后台脚本（用户铁律）。

### 4. 推送到 GitHub（需要 token）

```bash
git remote set-url origin https://<你的GH_TOKEN>@github.com/ghshhf/mx_auto_strategy.git
git push origin main
git remote set-url origin https://github.com/ghshhf/mx_auto_strategy.git   # 推完还原, token不落盘
```

> 也可用 `gh auth login` 后直接 `git push`。token 绝不写进任何文件（除一次性命令），推完即还原。

---

## 账号体系 + 自己的实盘资金曲线（手动记账，本地永久留存）

> 核心是**多账号**：每个账号独立资金曲线、互不串账、各自从零起算。
> **本地无自动清零机制** —— 所有账号都永久留存，攒未来回测依据。

| 账号来源 | account_id | 本地行为 |
|---|---|---|
| 自己实盘（默认） | `real`（可加 `real2`…） | 你手动买卖，永久记录 |
| 模拟大赛 | `sim_261984600000041416` | 远程比赛平台自己清零，本地只看远程每笔如实记，远程清零不影响本地 |

> ⚠️ **关键认知**：龙虾大赛的清零是【远程比赛平台】干的，与本地无关。
> 咱们本地只负责忠实记录 —— 远程怎么归零是它的事，本地账本永远留着，未来回测才有完整依据。

```bash
python3 manual_log.py accounts                                  # 列出所有账号+余额
python3 manual_log.py deposit --amount 50000                     # 实盘real入金(默认账号)
python3 manual_log.py buy --code 600900 --name 长江电力 --price 28.5 --qty 100
python3 manual_log.py buy --account real2 --code 601398 --name 工商银行 --price 6.8 --qty 10000
python3 manual_log.py summary --account sim_261984600000041416  # 读龙虾大赛账号(本地留存)
python3 manual_log.py export                                     # 导出CSV
# 仅当用户亲口要求删账号时才用 (二次确认; real 禁止删):
python3 manual_log.py delete --account real2 --confirm
```

- 数据落在 `records/<账号ID>/trades.jsonl` + `equity.jsonl`（**已加入 `.gitignore` 排除 `*.jsonl`，不推 GitHub**）。
- **本地无清零**：系统不会自动清空任何账号。只有用户明确说"删账号"才用 `delete`（带 `--confirm`，且 `real` 受保护禁止删）。
- 与模拟盘 `auto_trader.py` 的状态完全隔离，是追加写的独立账本。
- `--account` 参数挂在每个子命令上，写 `buy --account xxx` 即可。

---

## 关键文件（智能体改动指南）

| 文件 | 改不改 | 说明 |
|---|---|---|
| `strategy_config.json` | 偶尔 | 候选池 + 风控参数，所有可调项集中在此 |
| `user_script.md` | **常改** | 用户给方向的人话入口，智能体应优先读这个 |
| `weekly_theme.py` | 少改 | 叠加解析逻辑（`user_direction_overlay` 模式） |
| `auto_trader.py` | 少改 | 主引擎（市况判定→选股→买入→止盈止损） |
| `selector.py` | 少改 | 三维评分选股引擎 |
| `market_data.py` | 不改 | 腾讯财经行情获取 |
| `manual_log.py` | 不改 | **账号体系**手动记账（本地无清零，永久留存，仅手动 delete） |

---

## 市况三档（系统自动判定，除非用户用剧本覆盖）

| 市况 | 判定 | 防御% | 进攻% | 现金% |
|---|---|---|---|---|
| 弱势 | 沪深300 低于20日MA -3% | 60 | 24 | 16 |
| 平衡 | MA ±3% 带内 | 45 | 45 | 10 |
| 强势 | 高于 MA +3% | 35 | 60 | 5 |

---

## 当前剧本状态（2026-W32 当周）

- **进攻方向**：待定（AI 层 shadow 评估中，用户可手写 `user_script.md` 或等 AI 积累足够样本后晋升）
- **防御端（系统自治）**：银行 + 电力 + 红利低波
- **目标**：正收益即可，赚红包，拿大赛前十
- **市况背景**：以运行时 `user_script.md` 和 `weekly_theme.json` 为准

> ⚠️ 以上为快照，实际以 `user_script.md` 和 `weekly_theme.json` 运行时为准。智能体启动时应先读这两个文件。

---

## 安全红线（智能体必须遵守）

1. **API key 只从环境变量 `MX_APIKEY` 读取，绝不写入任何文件或回显。**
2. **不碰合约/杠杆/可转债高波动标的**（除非用户剧本明确指定）。
3. **不自动开 cron / 后台定时任务**（用户要求每天手动触发 3 次）。
4. **单票仓位 ≤ 18%**，不重仓押注。
5. **推送到 GitHub 前，确认 `.gitignore` 已排除 token/状态文件。**

---

## 扩展工具（能力补全）

| 工具 | 能力 | 命令示例 |
|---|---|---|
| `manual_log.py mark` | **实时市值估值**：读持仓→拉最新价→算浮动盈亏+总净值（闭市降级成本口径） | `python3 manual_log.py mark` |
| `manual_log.py curve` | **资金曲线导出**：读 equity 快照→导出"日期→净值"CSV，供回测/画图 | `python3 manual_log.py curve` |
| `manual_log.py drawdown` | **回撤闸**：算最大/周回撤，超阈（默认-5%）输出降级全防御建议 | `python3 manual_log.py drawdown --threshold 5` |
| `script_tracker.py` | **剧本命中追踪 v1.1**：剧本落 JSON（含预期+到期日）→ check 自动比对行情判定命中→积累胜率；支持 source=human/ai 区分来源，compare 对比胜率 | `python3 script_tracker.py add/list/check/stats/compare` |
| `shadow_eval.py` | **AI shadow A/B 评估**：ai_score shadow 模式运行时记录"规则排序 vs AI排序"快照，后续计算前向收益量化 AI 是否真加分 | `python3 shadow_eval.py evaluate --horizon 20` / `report` / `status` |
| `ai_promotion_gate.py` | **shadow→active 晋升门槛**：5 项量化门槛（样本量/AI胜率/超额收益/剧本样本/剧本胜率），全满足才建议晋升 | `python3 ai_promotion_gate.py check` / `status` |
| `sync_contest.py` | **大赛只读同步**：调 mx-moni 查远程龙虾账户→追加快照进 `records/sim_*/`，远程清零不影响本地 | `python3 sync_contest.py --account sim_261984600000041416` |
| `news_feed.py` | **实时新闻参考源**：拉公开快讯→与剧本方向匹配打「共振」标签→落本地。**仅参考·绝不交易** | `python3 news_feed.py fetch` / `news_feed.py latest --resonance` |
| `crypto_data.py` | **加密数据源**：CoinGecko主·Binance/OKX备，免费全币种+交易所相关数据，仅公开行情不碰私钥 | `python3 crypto_data.py price btc eth sol` / `crypto_data.py exchange binance` |

> 设计闭环：行情(`market_data`) → 选股(`selector`+`weekly_theme`) → 下单/记录(`auto_trader`+`local_records`) →
> 多账号账本(`manual_log`, 本地永久) → 实时估值/曲线/回撤(`mark`/`curve`/`drawdown`) →
> 剧本护城河(`script_tracker` v1.1, human/ai 分源) → AI shadow A/B 评估(`shadow_eval`) →
> 晋升门槛(`ai_promotion_gate`) → 远程比对(`sync_contest`) → 新闻共振参考(`news_feed`)。

---

## AI 成熟度框架 (v6.15)

AI overlay 当前 `enabled=false`（用户决策：与外部 AI 冗余，shadow 空转边际贡献为零）。
但代码保留，并已补齐 shadow→active 的量化晋升机制：

1. **shadow_eval.py**：ai_score 每次 shadow 运行自动记录"规则 top3 vs AI top3"快照到 `records/shadow_eval_snapshots.jsonl`。快照满 `horizon` 个交易日后，`evaluate` 计算两组等权前向收益并对比。
2. **ai_promotion_gate.py**：5 项门槛同时满足才建议晋升 — min_samples(20) / min_ai_win_rate(55%) / min_avg_outperformance(1%) / min_script_samples(5) / min_script_win_rate(50%)。门槛可在 `strategy_config.json` 的 `ai_overlay.promotion_gate` 配置。
3. **script_tracker v1.1**：新增 `source` 字段区分 human/ai 剧本；`compare` 命令对比两者胜率；`_indicator_hit` 修复区间收益计算 bug（原取"最近60根K线"→现取"写入日→到期日"）。
4. **script_advisor 自动追踪**：API 模式生成草稿后自动创建 `source=ai` 的 tracker 记录，AI 建议也纳入胜率统计。

晋升路径：`enabled=true` + `shadow_mode=true` → 积累样本 → `shadow_eval evaluate` → `ai_promotion_gate check` → 全 PASS → `shadow_mode=false`（paper trading 验证）→ 稳定后可考虑 live。

---

## 论证报告（供智能体理解「为什么这么设计」）

- `strategy_script_proof.md` —— 十层证据链：用户「剧本书写者」能力论证（3年5000%/50倍为何很正常）
- `pool_analysis_report.md` —— 为什么5年回测失真（池子太小）
- `strategy_power_proof.md` —— 散户-30% vs 用户-2.67% 的实力论证
- `ashare_backtest/REPORT_10Y_LIMIT.md` —— ⚠️ **已废弃**：westock 面板伪迹踩坑记录（其中 19.5x 为虚增假数，勿引用）

> ⚠️ **收益真值口径（v6.18 重大更正）**：旧「16.29x / 22.18x / 24.16x」系 **eastmoney 字段映射错位**或**前视偏差虚增**, **已废弃**。v6.18 改用腾讯 `web.ifzq.gtimg.cn` 后复权周线（字段正确: open/close/high/low）+ 交易成本建模, **全样本真值: 18.185x / CAGR 22.31% / MDD -33.31% / 相对沪深300 超额 +9.55x**（窗口 2014-10-17~2026-08-06, 749 周, 含幸存者偏差, 非未来承诺）。
> 旧的「18 倍 / 19.5 倍」出自 westock（腾讯）面板伪迹虚增（单周跳变 ±50%~±35000%），**已于 2026-07-30 全面废弃**，任何文档不得再引用。
> v6.16 新增: 交易成本建模(佣金万2.5+印花税0.05%+滑点0.1%, 默认开启) / walk-forward 滚动窗口验证 / 幸存者偏差声明+敏感性检查(`survivorship_check.py`)。v6.18 新增: walk-forward 升级为**双维度配对检验**(倍数+MDD, |t|≥2 才算显著) + ablation 单变量消融; 经检验趋势过滤/科技相位/量能/宏观/估值分位等叠加层**样本外均不显著**, 基线锁定 动量26+核心卫星+死叉。

### ★ 显著性闸门 (v6.18 诚实纪律, CI 强制)
- **基线完整性测试** `tests/test_baseline_integrity.py`: 数据存在才拦截、缺失则跳过。断言 `run()` 默认(use_tech=False+trend_filter=False+核心卫星+死叉+成本)精确复现 18.185x/-33.31%(容差内), 且默认签名值锁定为 False。**任何人把默认翻回前视相位或破坏基线数字, CI 红。**
- **增强层准入规则 (PR 评审手动执行)**: 任何声称"提升"的叠加层, 须经 `walk_forward.py` 双维度配对检验, **样本外 |t|≥2 才算显著、才准入基线**; |t|<2 一律判噪声, 默认关闭。v6.18 已裁决: 趋势过滤/科技相位/量能/宏观/估值 12 变体**无一达标**。
- **幸存者偏差上界**: 头条 18.185x 为被系统性高估的上界(去 Top5 赢家即 -36.3% 至 11.591x, 见 `survivorship_check.py --compare`); 精确修正需含退市 point-in-time 池(akshare 经代理不可得), 故标"上界"不标精确值。
