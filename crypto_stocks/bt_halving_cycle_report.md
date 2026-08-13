# BTC 减半周期回测（比特币周期为例）— 当前 50 币池

> 生成: 2026-08-13 | 引擎 `crypto_options_bt.py`（`halving_cycle_enabled` 时间刻减仓层）
> 数据: 本地面板 `weekly_adjclose_crypto50.csv`（主，2017-08-11~2026-08-07）+ `weekly_adjclose_crypto50_10y.csv`（10y，2016-08-11 起）
> 口径: `halving_OFF` = 关掉 BTC 减半日历减仓（基线）；`halving_ON` = 开启（比特币周期时间刻减仓）。其余用 `DEFAULT_CFG`（pre_halving_start_month=36）。

## 结果：比特币周期时间刻减仓 vs 关闭

| 窗口 | 模式 | 倍数 | CAGR | MDD | Sharpe | BTC 买入持有 |
|---|---|---|---|---|---|---|
| 10y | OFF（基线） | 7930.1x | 145.0% | −44.4% | 1.74 | 108.8x |
| 10y | **ON（BTC 周期）** | **21663.6x** | **170.9%** | **−36.9%** | **2.01** | 108.8x |
| 5y | OFF（基线） | 3.27x | 26.7% | −42.8% | 0.80 | 1.30x |
| 5y | **ON（BTC 周期）** | **8.19x** | **52.3%** | **−36.9%** | **1.28** | 1.30x |
| 3y | OFF（基线） | 1.53x | 15.3% | −42.3% | 0.57 | 2.44x |
| 3y | **ON（BTC 周期）** | **2.55x** | **36.7%** | **−36.3%** | **1.10** | 2.44x |

### 比特币周期层的贡献（ON − OFF）
- **10y**：倍数 ×2.73（7930→21664）、MDD −44.4%→−36.9%、Sharpe 1.74→2.01
- **5y**：倍数 ×2.50、MDD −42.8%→−36.9%、Sharpe 0.80→1.28
- **3y**：倍数 ×1.67、MDD −42.3%→−36.3%、Sharpe 0.57→1.10

**结论**：BTC 减半日历减仓在所有窗口同时抬升收益、压低回撤、改善 Sharpe——是典型的"时间刻减仓" alpha，与 README §1.2 的判定一致（alpha 100% 来自 `crash/bear_bottom` 相位把现货敞口缩到 30~50%、其余转 STABLE 现金）。

## 减半相位周数分布（主面板 2017-08-11 起，pre_halving_start_month=36）

| 相位 | 周数 | 占比 |
|---|---|---|
| accumulation（积累/满仓） | 53 | 33.8% |
| euphoria（见顶/满仓） | 26 | 16.6% |
| crash（暴跌/缩仓） | 26 | 16.6% |
| bear_bottom（筑底/缩仓） | 16 | 10.2% |
| pre_halving（预热/缩仓） | 36 | 22.9% |
| 合计 | 157 周 | 100% |

## 诚实口径（必读）
- **10y 21664x 是样本内（in-sample）上限**，非承诺值。当前用的是 `DEFAULT_CFG`（pre_halving_start_month=36、相位缩放取默认），并非 README §1.2 的调优最优档（pre_halving_start_month=31、cr=bb=0.0 → 10y 37815x）。调参方向一致、量级可比。
- **含幸存者偏差**：标的池为"现存主流币"清单（已删 STRK/BEAM/PAS/SEI 等），已死/下架币未纳入 → 倍数偏高。
- **样本外大幅衰减**：README 记录的 walk-forward（2020–2025）累积约 274.8x、保留率约 69%；切割 B（训 2 轮→测第 3 轮）仅 3.4x。周期层通过 OOS 复检，但绝对倍数不可外推为未来业绩。
- 同窗口 BTC 买入持有（10y 108.8x / 5y 1.3x / 3y 2.44x）作基准：BTC 周期层在 10y 把策略从 7930x 拉到 21664x，显著跑赢 BTC 持有；但 5y/3y 窗口因 2021-2026 慢牛后的震荡，策略与 BTC 持有差距收窄。

## 复现
```bash
cd crypto_stocks
python bt_halving_cycle.py   # -> bt_halving_cycle_results.json
```
同目录相关脚本：`run_windows_bt.py`（base vs cycles.overlay 叠加，依赖 cycles 包）、`crypto_oos_validate.py`（减半参数过拟合 walk-forward 检验）、`_scratch_cycle_universal.py`（跨轮验证"BTC 周期=全篮通用底层"论题）、`diag_cycle_gate.py`（MA 触发 vs 周期门控对比）、`crypto_17000_learn.py`（17000x 逐层拆解）。
