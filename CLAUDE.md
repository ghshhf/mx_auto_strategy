# CLAUDE.md — mx_auto_strategy 智能体使用指南

> 本文件供 Claude Code / Cursor / Codex / 其他 AI 编程智能体自动读取。
> 任何 Agent clone 本仓库后，读此文件即可直接上手，无需用户额外解释。

---

## 这是什么

龙虾炒股大赛（模拟盘）自动交易系统 v6.8，核心模式叫**「剧本书写者」**：

- **防御端**：系统自治。从低 beta 蓝筹白名单自动选 Top3，按三档市况（弱势/平衡/强势）自动调仓位。
- **进攻端**：用户给方向就锁定用户方向，不给就走自适应主线（行业动量扫描）。
- **大方向**：用户直接写人话剧本（`user_script.md`），系统解析执行。

> 设计哲学：**防御端自律 + 进攻端剧本锁定 + 大方向甩剧本 = 不可能输。**

---

## 智能体三步上手

### 1. 准备环境

```bash
git clone https://github.com/ghshhf/mx_auto_strategy.git
cd mx_auto_strategy
pip install requests
export MX_APIKEY="你的mx-moni API key"   # 从环境变量读，绝不硬编码
```

### 2. 给用户「给方向」

直接编辑 `user_script.md` 写人话即可，例如：

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
| 平衡 | MA ±3% 带内 | 54 | 30 | 16 |
| 强势 | 高于 MA +3% | 44 | 40 | 16 |

---

## 当前剧本状态（2026-W29 当周）

- **进攻方向（用户锁定）**：电力 或 医疗（医药）
- **防御端（系统自治）**：银行 + 电力 + 红利低波
- **目标**：正收益即可，赚红包，拿大赛前十
- **市况背景**：弱势市（沪深300 偏离 MA 约 -6.5%），科技崩后防御为王

> ⚠️ 以上为快照，实际以 `user_script.md` 和 `weekly_theme.json` 运行时为准。智能体启动时应先读这两个文件。

---

## 安全红线（智能体必须遵守）

1. **API key 只从环境变量 `MX_APIKEY` 读取，绝不写入任何文件或回显。**
2. **不碰合约/杠杆/可转债高波动标的**（除非用户剧本明确指定）。
3. **不自动开 cron / 后台定时任务**（用户要求每天手动触发 3 次）。
4. **单票仓位 ≤ 18%**，不重仓押注。
5. **推送到 GitHub 前，确认 `.gitignore` 已排除 token/状态文件。**

---

## 扩展工具（能力补全，已在 v7.2 加入）

| 工具 | 能力 | 命令示例 |
|---|---|---|
| `manual_log.py mark` | **实时市值估值**：读持仓→拉最新价→算浮动盈亏+总净值（闭市降级成本口径） | `python3 manual_log.py mark` |
| `manual_log.py curve` | **资金曲线导出**：读 equity 快照→导出"日期→净值"CSV，供回测/画图 | `python3 manual_log.py curve` |
| `manual_log.py drawdown` | **回撤闸**：算最大/周回撤，超阈（默认-5%）输出降级全防御建议 | `python3 manual_log.py drawdown --threshold 5` |
| `script_tracker.py` | **剧本命中追踪**：剧本落 JSON（含预期+到期日）→ check 自动比对行情判定命中→积累胜率 | `python3 script_tracker.py add/list/check/stats` |
| `sync_contest.py` | **大赛只读同步**：调 mx-moni 查远程龙虾账户→追加快照进 `records/sim_*/`，远程清零不影响本地 | `python3 sync_contest.py --account sim_261984600000041416` |
| `news_feed.py` | **实时新闻参考源**：拉公开快讯→与剧本方向匹配打「共振」标签→落本地。**仅参考·绝不交易** | `python3 news_feed.py fetch` / `news_feed.py latest --resonance` |

> 设计闭环：行情(`market_data`) → 选股(`selector`+`weekly_theme`) → 下单/记录(`auto_trader`+`local_records`) →
> 多账号账本(`manual_log`, 本地永久) → 实时估值/曲线/回撤(`mark`/`curve`/`drawdown`) →
> 剧本护城河(`script_tracker`) → 远程比对(`sync_contest`) → 新闻共振参考(`news_feed`)。读一切金融数据、记录、宏观剧本、自动筛选、资讯参考全打通。

---

## 论证报告（供智能体理解「为什么这么设计」）

- `strategy_script_proof.md` —— 十层证据链：用户「剧本书写者」能力论证（3年5000%/50倍为何很正常）
- `pool_analysis_report.md` —— 为什么5年回测失真（池子太小）
- `strategy_power_proof.md` —— 散户-30% vs 用户-2.67% 的实力论证
- `backtest_script_july.py` —— 6月底交剧本→7月关仓+5.79% 的量化验证
