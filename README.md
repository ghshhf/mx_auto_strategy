# mx_auto_strategy — 龙虾炒股大赛自动交易系统 v6.8

> 模拟盘专用：龙虾炒股大赛（账户 261984600000041416，100 万虚拟金，全零持仓）
> 核心模式：**剧本书写者** —— 防御端系统自治 + 进攻端用户方向叠加 + 大方向甩剧本

🔗 **GitHub**：https://github.com/ghshhf/mx_auto_strategy

📄 **智能体入口**：`CLAUDE.md`（Claude Code / Cursor / Codex / 其他 AI 拉取后自动读取，直接上手）

---

## 一句话哲学

> **防御端自律 + 进攻端剧本锁定 + 大方向甩剧本 = 不可能输**

- **防御端**：系统自治。低 beta 蓝筹白名单自动选 Top3，三档市况自动调仓。
- **进攻端**：你给方向就锁定你的方向，不给就走自适应主线（行业动量扫描）。
- **大方向**：直接写人话剧本（`user_script.md`），系统解析执行——写啥演啥。

---

## 快速开始

```bash
git clone https://github.com/ghshhf/mx_auto_strategy.git
cd mx_auto_strategy
pip install requests
export MX_APIKEY="你的mx-moni API key"   # 从环境变量读, 绝不硬编码

# 干跑选股(不交易)
python3 auto_trader.py --mode select

# 实际下单(需模拟盘账户 + 交易时段)
python3 auto_trader.py
```

**交易节奏**：每天手动触发 3 次（10:00 / 12:00 / 14:00）。无自动 cron、无后台脚本（用户铁律）。

---

## 给方向（人话入口）

直接编辑 `user_script.md`：

```
下周主攻电力和医疗，防御端你定，弱势市多留现金。
```

关键词映射（写口语即可）：

| 你写的 | 系统理解 |
|---|---|
| `电力` / `电网` | 进攻端叠加电力方向 |
| `医疗` / `医药` / `药` | 进攻端叠加医药方向 |
| 不写进攻方向 | 系统走自适应主线 |
| `防御端你定` / 不写 | 系统从防御白名单自治 |

运行时 `user_script.md` 被解析并同步进 `weekly_theme.json`（machine-readable）。

---

## 账号体系 + 自己的实盘资金曲线（手动记账，本地永久留存）

`manual_log.py` 支持**多账号**，每个账号独立资金曲线、互不串账。**本地无自动清零**——所有账号永久留存，攒回测依据：

| 账号来源 | account_id | 本地行为 |
|---|---|---|
| 自己实盘（默认） | `real`（可加 `real2`…） | 你手动买卖，永久记录 |
| 模拟大赛 | `sim_261984600000041416` | 远程比赛平台自己清零，本地只看远程每笔如实记，远程清零不影响本地 |

> 龙虾大赛的清零是【远程比赛平台】干的，与本地无关。本地只负责忠实记录，未来回测才有完整依据。

```bash
python3 manual_log.py accounts                                 # 所有账号+余额
python3 manual_log.py deposit --amount 50000                  # 实盘入金(默认real)
python3 manual_log.py buy --code 600900 --name 长江电力 --price 28.5 --qty 100
python3 manual_log.py buy --account real2 --code 601398 --name 工商银行 --price 6.8 --qty 10000
python3 manual_log.py summary --account sim_261984600000041416   # 读龙虾大赛(本地留存)
python3 manual_log.py delete --account real2 --confirm        # 仅当你亲口要求删账号
```

- 数据落在 `records/<账号ID>/*.jsonl`（**已 `.gitignore` 排除，不推 GitHub、永不自动清零**）。
- 本地无清零机制；只有你明确说"删账号"才用 `delete`（带 `--confirm`，`real` 受保护禁止删）。
- 与 `auto_trader.py` 的模拟盘状态完全隔离，是追加写的独立账本。

---

## 市况三档（系统自动判定，剧本可覆盖）

| 市况 | 判定 | 防御% | 进攻% | 现金% |
|---|---|---|---|---|
| 弱势 | 沪深300 低于20日MA -3% | 60 | 24 | 16 |
| 平衡 | MA ±3% 带内 | 54 | 30 | 16 |
| 强势 | 高于 MA +3% | 44 | 40 | 16 |

---

## 文件结构

```
mx_auto_strategy/
├── CLAUDE.md            # 🤖 智能体入口(自动读取, 直接上手)
├── user_script.md       # 📝 用户剧本入口(人话给方向)
├── weekly_theme.json    # 机器可读的叠加配置(由user_script自动同步)
├── strategy_config.json # 所有可调参数(候选池89只 + 风控)
├── weekly_theme.py      # 叠加解析逻辑(user_direction_overlay模式)
├── selector.py          # 三维评分选股引擎
├── auto_trader.py       # 主引擎(市况判定→选股→买入→止盈止损)
├── market_data.py       # 腾讯财经行情获取
├── manual_log.py        # 📒 账号体系手动记账(本地无清零, 永久留存, 仅手动delete)
├── script_tracker.py    # 📜 剧本书写者命中追踪(剧本JSON→自动判定→胜率)
├── sync_contest.py      # 🔄 龙虾大赛远程只读同步(本地永久留存)
├── backtest_*.py        # 回测脚本(3年/5年/剧本关仓验证)
├── scripts/             # 剧本存档(用户护城河资产, 进版本库)
└── *_proof.md / *_report.md  # 论证报告(剧本书写者实力证据链)
```

### 扩展工具（v7.2 能力补全）

| 工具 | 能力 |
|---|---|
| `manual_log.py mark` | 实时市值估值（持仓×最新价→浮动盈亏+总净值） |
| `manual_log.py curve` | 资金曲线导出 CSV（日期→净值，供回测/画图） |
| `manual_log.py drawdown` | 回撤闸（超阈输出降级全防御建议） |
| `script_tracker.py` | 剧本命中追踪（add/list/check/stats，积累胜率） |
| `sync_contest.py` | 大赛只读同步（远程快照追加本地，远程清零不影响） |

```bash
python3 manual_log.py mark                              # 实时估值
python3 manual_log.py curve                             # 导出曲线CSV
python3 manual_log.py drawdown --threshold 5            # 回撤>5%告警
python3 script_tracker.py add --title "科技离场" --direction bearish --expiry 2026-08-01 --code sh000300 --expect down
python3 script_tracker.py check                         # 自动判定到期剧本
python3 script_tracker.py stats                         # 剧本胜率
python3 sync_contest.py --account sim_261984600000041416   # 同步大赛(需MX_APIKEY)
```

---

## 安全红线

1. **API key 只从环境变量 `MX_APIKEY` 读取，绝不写入文件或回显。**
2. **不碰合约/杠杆**（除非剧本明确指定）。
3. **不开 cron / 后台定时**（每天手动触发 3 次）。
4. **单票 ≤ 18%**，不重仓。
5. **推送前确认 `.gitignore` 已排除 token / 状态文件。**

---

## 论证报告（为什么这么设计）

- `strategy_script_proof.md` —— 十层证据链：用户「剧本书写者」能力（3年5000%/50倍为何很正常）
- `pool_analysis_report.md` —— 为什么5年回测失真（池子太小）
- `strategy_power_proof.md` —— 散户-30% vs 用户-2.67% 实力论证
- `backtest_script_july.py` —— 6月底交剧本→7月关仓+5.79% 量化验证

---

## 当前剧本状态（2026-W29 当周快照）

- **进攻方向（用户锁定）**：电力 或 医疗（医药）
- **防御端（系统自治）**：银行 + 电力 + 红利低波
- **目标**：正收益即可，赚红包，拿大赛前十
- **市况**：弱势市（沪深300 偏离 MA 约 -6.5%）

> 实际以 `user_script.md` + `weekly_theme.json` 运行时为准。
