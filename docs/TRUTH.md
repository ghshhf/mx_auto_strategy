# 单一真值源 (Single Source of Truth) · mx_auto_strategy v6.18

本文件汇总三市场量化回测的**审计后验证真值**。所有数字均经实跑复现；详细推导见各引擎 README 与解释页。
散落在 README / CLAUDE / 子 README 的数字以本文件为准。

## 一句话定位
A股 / 美股 / 加密 = 同源方法论的三套**研究回测引擎**（非实盘执行系统）。
期权层 = 远期（≥1 年 DTE）收租 / 保险，**非杠杆**，权利金几个百分点 / 年 ≈ 费用级。

## 各市场权威真值

### A股（`markets/ashare/`）
- **头条 18.185x** · CAGR 22.31% · MDD −33.31%（v6.18 权威）
- 口径：腾讯后复权周线面板 + momentum26 + 核心卫星 0.5 + 死叉 + `use_tech=False` + `trend_filter=False` + 含成本
- 窗口 2014-10-17 ~ 2026-08-06（749 周）；同期 HS300 1.905x → 超额 9.55x
- 含幸存者偏差；趋势过滤经 v6.18 实证为损害已移除
- 引擎 `markets/ashare/backtest_engine.py`；导出 `markets/ashare/export_nav.py` → `docs/data/nav.json`（已与头条对齐）

### 美股（`markets/us/`）
- **头条 99.85x** · CAGR 46.8% · MDD −47.2%（期权增强，真实面板 + 公允 BS 期权定价）
- 无期权基线 22.48x（无杠杆袖 14.46x）；保守下限 31.7x
- 期权层：covered call 收租（~4.5%/年）+ protective put 保险（~6%/年），远期（52 周 DTE）
- 引擎 `markets/us/us_backtest_ai.py`；数据 `markets/us/data/us_nav_ai.csv`（`optimized_nav`）

### 加密（`markets/crypto/`）
- **头条 448.6x** · CAGR ~97% · MDD −57.6%（期权三件套 + 封顶 4.5x + 减半周期关）
- 无期权基线：进攻 Top3 100.6x / 防御档 40.7x
- **减半周期合法**：协议级确定性日期（零后视）；in-sample 拟合上限 ~17000x（真实 10 年面板可复现 18360x，**非合成假数**）
- **⚠️ 2026-08-11 默认翻转为开**：此前"默认关"基于一个测试错误（只翻开关而 `risk_scale` 仍为 1.0 → 减仓未生效，仅激进做空项生效并退化 10y）。查证：17000x 的 alpha **100% 来自时间刻减仓**（关掉 crash 做空项，10y 结果一字不差）。新默认 `enabled=True / cr=bb=0.3 / ph=31` → 10y **24,494x / −43.5%**（旧默认 6,266x / −61.3%）。OOS：20 窗 walk-forward 倍数 t=+3.45、MDD t=+2.91（双维度显著），周期切割 3 轮保留率 100%。详见 `docs/CYCLE_DERISK.md`
- **⚠️ 2026-08-11 二次修订（山寨维度）**：此前所有相位实证只用 BTC 一列。全 56 币重算后发现三点：①本轮山寨中位自周期顶 **−89.4%** vs BTC **−48.2%**（分化史上最极端）；②本轮山寨见顶 post-halving **7.3 月**，比 BTC（17.2 月）**提前 9.9 个月**，前两轮则同步 → 时间刻在 `accumulation` 段仍让策略满仓持已见顶的山寨；③全局 MDD −43.5% **不在下行相位**，100% 落在 `pre_halving`，`accumulation 2024` 段 MDD −40.3% 却只赚 26.0%。对策：下行相位 `cr=bb` 由 0.3 → **0.0**（完全离场）+ 新增 **`alt_rs_gate`**（ALT/BTC 等权相对强度破 20 周 MA → 进攻仓转防御核 BTC，市场信号非时间刻）。结果 10y **37,815x / −32.4% / Sharpe 2.00**（MDD 天花板首次被打破）；5y 5.81x/−41.4% → **7.32x/−33.9%**。OOS：156 周窗 walk-forward 倍数 t=**+2.31**、MDD t=**+6.17**（胜 17/18）；周期切割两轮均倍数更高 + 回撤更浅。**证伪记录**：「差别减仓（保 BTC 砍山寨）」无独立 alpha，等敞口对照后其收益 100% 来自总敞口更低
- 反直觉铁律：**见顶期（euphoria）必须满仓**（减仓则 10y 18,378x→4,580x）；「高位」不是减仓信号，「减半后 18 个月」才是
- 诚实样本外：切割 B 3.4x / Walk-forward 274.8x（≈69% 后视镜保留）
- 引擎 `markets/crypto/crypto_options_bt.py`；学习页 `markets/crypto/reports/crypto_17000_explainer.html`；机制文档 `docs/CYCLE_DERISK.md`
- **85% 档过拟合判定**：strong 档进攻 cap 65%→85% 在头条面板为平滑杠杆（不解锁额外 alpha），且 walk-forward 下 IS 选参（0.85）打不过头条 0.65 → 头条 0.65 为诚实选择（证据 `markets/crypto/crypto_strong_offense_wf_out.txt`）

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
- 时间刻减仓虽 OOS 双维度显著，但**重度依赖四年周期规律成立**——若 ETF/机构化把周期拉平，crash+bear_bottom 的 13 个月低仓（30%）会变成长期踏空，这是该策略的**单点故障**

## 文档索引
- 主 `README.md` — 项目定位与分类（A股 live 智能体指南见 `_archive/CLAUDE.md`）
- A股：`markets/ashare/` + `docs/curves.html`
- 美股：`markets/us/README.md` + `markets/us/data/us_nav_ai.csv`
- 加密：`markets/crypto/README.md` + `markets/crypto/reports/crypto_17000_explainer.html`
- 组合：`docs/portfolio_blend.html` + `docs/data/portfolio_blend.json`
- OOS 证据：`markets/crypto/crypto_oos_out*.txt`、`markets/crypto/crypto_strong_offense_wf_out.txt`、`_archive/reports/us_oos_out.txt`
