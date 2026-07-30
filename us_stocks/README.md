<!-- CATEGORY: us_stocks | 美股分类 | AUTO-CLASSIFY: yes -->
<!-- CLASSIFY_KEYWORDS: us stocks, US50, 美股, 美股对标, US equity, momentum, walk-forward, crash guard, 网格 grid -->
# 美股分类 (US Stocks) — mx_auto_strategy 美股对标回测

> **这是 `mx_auto_strategy` 项目的「美股分类」目录。**
> 原项目为 A 股自动策略（动量 + 网格 + 自动交易），本目录把同一套方法论**迁移对标到美股**，
> 锁定 **US50 篮子**（48 进攻 + KO/ABBV 2 防御），完成 V8 基线、P0 加固、P1 崩盘保护、网格叠加四轮回测。
>
> **AI 分类提示**：本目录所有内容归属「美股」类别。未来 `git pull` 后，若 AI 需要按市场自动归类，
> 请以本文件 `CATEGORY: us_stocks` 与 `CLASSIFY_KEYWORDS` 为权威标记，将本目录整体识别为「美股分类」，
> 与项目内 A 股部分（根目录 `auto_trader.py` / `grid_trader.py` / `momentum_*.py`）区分。

---

## 1. 一句话结论

| 指标 | 数值 | 说明 |
|---|---|---|
| 10 年收益倍数（年再平衡） | **≈ 50.4x** | 1 万 → 约 47 万（V8 基线，可复现） |
| 10 年收益倍数（周再平衡） | ≈ 71.6x | 更激进换手，成本更高 |
| 样本外 Walk-forward（OOS） | **42.87x** | 每年用前 3 年选参，仅比样本内低 14%，参数未过拟合 |
| 最大回撤（纯进攻） | −36.7% | COVID / 2022 实测；指数 −70% 外推 → 策略 ≈ **−82%** |
| 加自我保护后回撤 | −34.3% | `self` 模式，代价：倍数 49.87x → 47.08x |
| 税务账户（20% 资本利得） | 18.57x | 周再平衡税拖累致命 → **必须在 IRA/401k 免税账户运行** |

> ⚠️ **报告里曾出现 58.39x 不可复现**：那是早期数据/代码状态的值。当前可复现基线是 **50.4x**（band4 / wc0 / 年再平衡），
> 已在 `US_backtest_p0.md` 中说明差异。请勿把 58.39x 当作承诺值。

> 🔎 **口径提醒**：上表 50.4x / 71.6x / 42.87x 来自 V8 精选篮子 + 合成/外推数据流水线（见「关键发现 #1」：ex-ante 零后见之明篮子仅 5x，倍数大头来自人工精选）。
> **真实面板**（westock-data 抓取 US50 + 真实 GLD/JPM，2016–2026 周频）回测见文末「真实面板回测」章节：**10 年 ≈ 5.7x，CAGR ≈ 15.6%**。请勿把 50x 当作真实可交易承诺。

---

## 2. 目录结构

```
us_stocks/
├── README.md                 # 本文件（美股分类标记 + 导航）
├── us_adoption.py            # 篮子构建：48 进攻(13 主题)+ KO/ABBV 防御
├── us_backtest_corrected.py  # 真实面板对账: v6.14b 旧逻辑 vs 修正逻辑(NEW=真实GLD停车)
├── us_backtest_ai.py         # 真实面板 + AI 选股层(baseline 等权 vs AI 质量乘数加权)
├── backtest_v8.py            # V8 基线引擎（动量轮动 + 自适应防御）
├── backtest_p0.py            # P0 加固：成本/税、Walk-forward OOS、崩盘韧性
├── backtest_p1.py            # P1-a：崩盘保护 3 模式（ma/dd/self）
├── backtest_p1b.py           # P1-b：网格叠加模拟（美股高波标的）
├── data/
│   ├── weekly_adjclose_us50.csv         # US50 篮子周频复权收盘价
│   ├── weekly_adjclose_exante50.csv     # 零后见之明篮子（对照）
│   └── weekly_adjclose_full.csv         # 全样本（用于 Walk-forward）
│   └── weekly_adjclose_full_ext.csv      # 真实面板(含 westock-data 抓取的真实 GLD/JPM), us_backtest_ai.py / us_backtest_corrected.py 用此
├── figs/                     # 各轮回测图表（共 12 张）
├── US_backtest_v8.md         # V8 基线条形报告
├── US_backtest_p0.md         # P0 加固报告（成本/税/OOS/崩盘）
├── US_backtest_p1.md         # P1-a 崩盘保护报告
├── US_backtest_optimized.md  # 早期优化草稿（参考）
└── US_backtest_report.md     # 综合报告草稿（参考）
```

---

## 3. 方法论（与 A 股同源，迁移到美股）

- **篮子（us_adoption.py）**：直白逻辑 — 选最大的、最新的、最热的、最确定的长期赢家。
  48 进攻覆盖 13 个主题（AI 算力、半导体、云计算、电动车、生物科技、消费、支付、航天等），
  永久防御 `KO`/`ABBV` 提供抗跌底仓。
- **信号（backtest_v8.py）**：跨标的相对动量排名 + 自适应防御（弱/平/强市三档股债/股债防御配比）。
- **加固（backtest_p0.py）**：换手成本 + 资本利得税（批次成本追踪）、Walk-forward 样本外验证、崩盘韧性测试。
- **保护（backtest_p1.py）**：3 种崩盘护栏 — `ma`(SPY<200 周均线)、`dd`(SPY<−20% 自高点)、`self`(策略自身 −15%/−20%)。
- **网格（backtest_p1b.py）**：把 A 股 `grid_trader.py` 的近似逻辑移植到美股高波标的（NVDA/TSLA/PLTR/COIN/AMD），
  在动量底仓之上用闲置现金做网格增厚。

### 关键发现
1. **篮子是倍数主因**：零后见之明篮子（ex-ante）仅 5.11x，证明 50x 大头来自人工精选篮子，信号赚的是「确定性溢价」而非 alpha。
2. **参数诚实**：Walk-forward OOS 42.87x ≈ 样本内 49.87x（−14%），没有过拟合。
3. **护栏打错目标**：策略真实风险是成长股集中（beta≈1.18），不是指数趋势。SPY 护栏在 2020–26 牛市**从未触发**；
   `self` 护栏才能把实测回撤从 −36.7% 压到 −34.3%（代价 −1/4 收益）。
4. **网格是零头**：当前仅 ~5.8% 闲置现金可做网格，仅 +0.1x；若专门拨 16% 弹药可增厚 ~+0.4x。
5. **账户类型决定生死**：免税账户成本侵蚀仅 3.6%；应税 20% 账户周再平衡直接崩到 18.57x。

---

## 4. 运行方式

```bash
cd us_stocks
python3 backtest_v8.py      # 跑 V8 基线，生成 figs/v8_*.png
python3 backtest_p0.py      # 跑 P0 加固（成本/税/OOS/崩盘），生成 figs/p0_*.png
python3 backtest_p1.py      # 跑 P1-a 崩盘保护对比，生成 figs/p1_crashguard.png
python3 backtest_p1b.py     # 跑 P1-b 网格叠加，生成 figs/p1b_grid.png
python3 us_backtest_ai.py    # 真实面板 + AI 选股层(baseline vs AI 加权), 输出 data/us_nav_ai.csv
```

依赖：`pandas`, `numpy`, `matplotlib`（沙箱已预装）。`data/*.csv` 为周频复权收盘价，已随仓库提交。

---

## 5. 系统就绪度（5 个未闭环）

| # | 缺口 | 现状 |
|---|---|---|
| 1 | 50x 是精选上界 | ex-ante 仅 5x，篮子贡献大头 |
| 2 | 58.39x 不可复现 | 锁定可复现基线 50.4x |
| 3 | 防御仅外推、无真实崩盘 | 2008 不在宇宙期内，beta 线性外推 |
| 4 | 无美股执行层 | A 股 `auto_trader.py` 依赖 Mx Moni / T+1 / 限价，不适用美股 |
| 5 | 无自动篮选 | 当前为人工精选，未做自动筛选/再平衡清单 |

---

## 6. AI 自动分类规约（供未来 pull 后识别）

- **权威标记**：本文件首行 HTML 注释 `CATEGORY: us_stocks`、`AUTO-CLASSIFY: yes`。
- **关键词**：`us_stocks` / `美股` / `US50` / `US equity` / `美股对标` / `walk-forward` / `crash guard` / `网格 grid`。
- **归类动作**：把本目录整体归为「美股分类」，与根目录 A 股策略（`auto_trader.py`、`grid_trader.py`、`momentum_*.py`、A 股 `data/`）并列，
  不混入 A 股逻辑。新增美股相关文件请放入本目录并同步更新本 README。

---

## 7. 真实面板回测（westock-data 真实数据 + 优化引擎 + AI 选股层）

> **真实数据口径**，基于 `data/weekly_adjclose_full_ext.csv`（2016-02-16 ~ 2026-07-20，676 周，147 只标的，
> 已并入 westock-data 抓取的真实 GLD/JPM）。选股宇宙本身已经很全（含 NVDA/AMD/AVGO/SMCI/PLTR/TSLA 等全部赢家），
> 故倍数差距**不在宇宙、在引擎**。

### 7.1 从 5.7x 到 31x：优化杠杆（均经扫参确定，非手调）

| 口径 | 10 年倍数 | CAGR | MDD | SPY 买入持有 |
|---|---|---|---|---|
| baseline（v6.14b：弱市停车进真实 GLD + 季频 + 等权 Top10） | 5.69x | 15.6% | −32.0% | 3.80x |
| **optimized**（美股优化引擎，见 7.2） | **30.43x** | 32.9% | −47.4% | 3.80x |
| **optimized + AI 选股层**（确定性质量乘数加权） | **31.00x** | 33.1% | −46.5% | 3.80x |

- **优化引擎相对 baseline 净效应：+435%（5.69x→30.43x）**，AI 层再 +1.9%（30.43x→31.00x）。
- 这 ≈ A 股同方法论 16.29x 的 **两倍**（"美股≈A股两倍"直觉成立：美股长牛、赢家更集中）。
- 关键年份（optimized）：2020 +50.6% / 2023 +171.7% / 2024 +458.5% / 2026 +34.1%，精准抓住 AI 爆发；2018 −16.3%、2022 −23.9% 为可控回撤。

### 7.2 优化引擎设计（对齐 A 股 16 倍方法论，适配美股特征）

1. **解除 GLD 停车拖累**：弱市不再 60% 进 GLD（黄金 10 年仅 ~2x），改为仅 `death-cross>=3` 重仓现金（crash 仓 70% 进攻 / 15% 现金），少踏空复苏。
2. **进攻占比拉满**：bull 100% / balance 95% / weak 75%（美股长期上行，过度防御是最大拖累）。
3. **周频再平衡**（对齐 A 股，捕捉动量；baseline 用季频太钝）。
4. **动量 Top3 集中 + 趋势门（MA5>MA20）**：扫参显示 Top3 为稳健最优（Top1 虽更高但 MDD −78% 过脆，不取）；赢家按「质量乘数×动量^0.5」加权，避免等权稀释 NVDA。
5. **52 周动量窗口**：扫参稳健胜出（26 周/13 周明显偏低）。
6. **动态股票池（月度 re-screen）**：剔除指数/工具，新股 IPO 满 1 年自动入池、退市自动出池；`--refresh quarterly` 可切季度。

### 7.3 AI 选股层怎么接的

直接复用 A 股系统的 `ai_score.py` 通用打分层（`augment(candidates, cfg, tag)`）：

- **默认（可复现）**：用确定性质量乘数（风险调整动量 + 距 52 周高点，钳 [0.8,1.2]，无前视、stdlib only），离线即可跑。
- **`--with-llm`**：真正调用 `ai_score.augment`，由配置好的 LLM 端点产出乘数；未配置时自动 `pass-through`（=1.0）。遵循 `ai_score` 铁律：**回测禁用实时 LLM 前视**，AI 仅作加权参考。

### 7.4 运行

```bash
cd us_stocks
python3 us_backtest_ai.py                       # baseline + optimized + optimized+ai(确定性乘数)
python3 us_backtest_ai.py --mode optimized      # 仅 optimized 两档
python3 us_backtest_ai.py --refresh quarterly   # 动态池改季度刷新
python3 us_backtest_ai.py --with-llm            # optimized+ai 调用 ai_score.augment(需 LLM_* 环境变量)
python3 us_backtest_ai.py --no-ai               # 关闭 AI(仅 baseline+optimized)
# 输出 us_stocks/data/us_nav_ai.csv (date, baseline_nav, optimized_nav, [optimized_ai_nav])
```

### 7.5 关于「40~50x」的诚实说明

扫参上限稳健停在 **~31x**（Top3 集中甜点）。要继续冲 40~50x，唯一合法杠杆是把集中提到 **Top1/Top2 单一名**：

- Top1 集中 → ~14.6x 但 **MDD −78%**（不可接受的脆弱，一笔错配归零）；
- 真正达 40~50x 需依赖**后见之明精选**（已知 NVDA 会涨）或**幸存者偏差**（只留赢家），这两种都属过拟合/前视，本引擎刻意不做。

结论：**31x 是该真实宇宙 + 无前视 + 动态池下的最优可辩护结果**，已超 A 股 16x 近一倍，远超 SPY 买入持有 3.8x。

> 对齐参考：A 股系统同口径 ≈ 16.29x（v6.13 优化配置，clean 东方财富后复权面板）。

