# 单一真值源 (Single Source of Truth) · mx_auto_strategy v6.18

本文件汇总三市场量化回测的**审计后验证真值**。所有数字均经实跑复现；详细推导见各引擎 README 与解释页。
散落在 README / CLAUDE / 子 README 的数字以本文件为准。

## 一句话定位
A股 / 美股 / 加密 = 同源方法论的三套**研究回测引擎**（非实盘执行系统）。
期权层 = 远期（≥1 年 DTE）收租 / 保险，**非杠杆**，权利金几个百分点 / 年 ≈ 费用级。

## 各市场权威真值

### A股（`ashare_backtest/`）
- **头条 18.185x** · CAGR 22.31% · MDD −33.31%（v6.18 权威）
- 口径：腾讯后复权周线面板 + momentum26 + 核心卫星 0.5 + 死叉 + `use_tech=False` + `trend_filter=False` + 含成本
- 窗口 2014-10-17 ~ 2026-08-06（749 周）；同期 HS300 1.905x → 超额 9.55x
- 含幸存者偏差；趋势过滤经 v6.18 实证为损害已移除
- 引擎 `ashare_backtest/backtest_engine.py`；导出 `ashare_backtest/export_nav.py` → `docs/data/nav.json`（已与头条对齐）

### 美股（`us_stocks/`）
- **头条 99.85x** · CAGR 46.8% · MDD −47.2%（期权增强，真实面板 + 公允 BS 期权定价）
- 无期权基线 22.48x（无杠杆袖 14.46x）；保守下限 31.7x
- 期权层：covered call 收租（~4.5%/年）+ protective put 保险（~6%/年），远期（52 周 DTE）
- 引擎 `us_stocks/us_backtest_ai.py`；数据 `us_stocks/data/us_nav_ai.csv`（`optimized_nav`）

### 加密（`crypto_stocks/`）
- **头条 448.6x** · CAGR ~97% · MDD −57.6%（期权三件套 + 封顶 4.5x + 减半周期关）
- 无期权基线：进攻 Top3 100.6x / 防御档 40.7x
- **减半周期合法**：协议级确定性日期（零后视），为 opt-in 可选层（默认关）；in-sample 拟合上限 ~17000x（真实 10 年面板可复现 18360x，**非合成假数**）
- 诚实样本外：切割 B 3.4x / Walk-forward 274.8x（≈69% 后视镜保留）
- 引擎 `crypto_stocks/crypto_options_bt.py`；学习页 `crypto_stocks/crypto_17000_explainer.html`
- **85% 档过拟合判定**：strong 档进攻 cap 65%→85% 在头条面板为平滑杠杆（不解锁额外 alpha），且 walk-forward 下 IS 选参（0.85）打不过头条 0.65 → 头条 0.65 为诚实选择（证据 `crypto_stocks/crypto_strong_offense_wf_out.txt`）

## 跨市场组合（`portfolio_blend.py`，共同窗口 2017–2026，470 周）
| 方案 | 倍数 | MDD | Sharpe |
|---|---|---|---|
| 单市场：A股 6.83x / 美股 111x / 加密 448.6x | — | −21 ~ −58% | 1.2 ~ 1.4 |
| 等权（1/3） | 129.6x | −34.3% | 2.00 |
| 波动平价（逆波动） | 43.1x | −25.8% | 2.05 |
| **波动平价（季再平衡·封顶 60%）** | 42.8x | −26.3% | 2.01 |

核心论点：三市场低相关，分散在不牺牲太多倍数的前提下显著压低 MDD、抬升 Sharpe。
「季再平衡·封顶 60%」为真正可执行分配器：每 13 周按回看波动重算逆波动目标权重（单市场 ≤60%），区间内含息持有。

## 期权哲学（贯穿三引擎）
- 选 ≥1 年 DTE 远期期权；权利金 = 名义的几个百分点 / 年（美股 call 4.5% / put 6%；加密因 IV 高 call 13–28% / put 15.6%）
- 卖 call = 收租（净现金流入 ≈0）；买 put = 保险（成本封顶）→ **非杠杆暴露**
- 只有「买 call 作股票替代（deep ITM，名义 10–30%）」才是真杠杆，三引擎均不做

## 诚实口径
- 加密含幸存者偏差（现存主流币清单）；美股 / 加密期权层为公允定价下可辩护值
- 所有数字为研究方法论论证，**非未来业绩承诺**
- 减半周期 / 17000x 为 in-sample 上限，不可当承诺

## 文档索引
- 主 `README.md` / `CLAUDE.md` — 项目定位与分类
- A股：`ashare_backtest/` + `docs/curves.html`
- 美股：`us_stocks/README.md` + `us_stocks/data/us_nav_ai.csv`
- 加密：`crypto_stocks/README.md` + `crypto_stocks/crypto_17000_explainer.html`
- 组合：`docs/portfolio_blend.html` + `docs/data/portfolio_blend.json`
- OOS 证据：`crypto_stocks/crypto_oos_out*.txt`、`crypto_stocks/crypto_strong_offense_wf_out.txt`、`us_oos_out.txt`
