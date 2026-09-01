# BTC / ETH 50:50 配对再平衡回测（10 年 · 真实数据 · USD 记账）

独立自包含脚本，不依赖也不修改 `crypto_stocks/` 现有引擎（`backtest_v2.py` 等）。

> ### 另见：五币扩展 → [`MULTI_COIN_PLAN.md`](MULTI_COIN_PLAN.md)
>
> 引擎已泛化为 N 资产，`N=2` 即本文的 BTC/ETH 退化情形（数值逐位一致）。
> 五币版（BTC/ETH/XRP/BNB/TRX，500 USD）入口为 `multi_coin_rebalance.py`。
>
> ⚠️ **上真钱前必读 `MULTI_COIN_PLAN.md` 第 5 节。** 压力测试表明：只要组合里有
> 任意一个币真的归零（而非暴跌后恢复），滚动再平衡线会亏到只剩基准的 **2.7%**，
> 而买入持有只掉到 68%——因为再平衡每周都在卖掉活着的币给尸体输血。该风险
> **当前没有代码保护**，且实测证明无法用价格阈值规避（TRX 曾 -95.4%、XRP 曾
> -94.9%，之后都完整恢复并成为收益最高的两个币之一）。

```bash
# 运行环境（managed venv，已装 pandas/numpy/yfinance/plotly）
C:\Users\21393\.workbuddy\binaries\python\envs\default\Scripts\python.exe btc_eth_rebalance.py
```

## 一、两条净值线

| | 线1 「滚动互平衡」 | 线2 「买入持有」 |
|---|---|---|
| t0 建仓 | 200 USD，扣 0.1% 建仓费后 199.80 USD，ETH/BTC 各 99.90 USD | 同左 |
| 之后 | 每周末按收盘价市值化；若 \|w_eth − 50%\| ≥ 1pp，交易回精确 50/50，按**实际成交额**收 0.1% | 全程不动 |

再平衡撮合口径（真实交易所行为）：设超配腿市值 `v_over`、总市值 `T`，
成交额 `X = v_over − T/2`；卖出超配腿 `X` USD（该腿落在 `T/2`），
扣费后 `X·(1−fee)` 买入低配腿（该腿落在 `T/2 − X·fee`）。
故再平衡后超配腿权重略高于 50%，偏差量级 `fee/2 = 5e-4`，远小于 1pp 阈值。

## 二、数据（全部为交易所真实成交价，无任何合成/插值）

| 标的 | 主源 | 补缺 |
|---|---|---|
| BTC | Yahoo Finance `BTC-USD` 日线 2016-08-01 ~ 至今（3654 天，无缺口） | — |
| ETH | Yahoo Finance `ETH-USD` 日线（**仅从 2017-11-09 起**） | Coinbase Exchange `ETH-USD` 真实 USD 现货日线补 2016-08-01 ~ 2017-11-08（465 天，零缺口） |

- 周线口径：日线按 `W-FRI`（周六~周五）重采样取**周内最后一根**日线收盘 →
  即周五收盘。最后一根为进行中的当周，标注为实际最新交易日。
- 拼接连续性：ETH 2017-11-08 (307.91, Coinbase) → 2017-11-09 (320.88, Yahoo)
  单日 +4.21%，无跳空断层。
- 为什么不用 Binance：本沙箱经代理访问 `api.binance.com` 返回 **HTTP 451**（地域封禁）。
- 为什么 ETH 补缺优先 Coinbase 而非 Bitfinex：Bitfinex 因 2016-08-02 被黑事件
  停机至 08-09，该段缺 7 天，会把 t0 挤到非周五；Coinbase 是受监管 USD 现货且逐日连续。
- 出网：脚本自动探测 `127.0.0.1:3067` → `3066` → 直连，并清理冲突的 `*_PROXY` 环境变量。

## 三、产物

| 文件 | 内容 |
|---|---|
| `btc_eth_weekly.csv` | `date, btc_close, eth_close`（523 周） |
| `nav_btc_eth.csv` | `date, nav_line1, nav_line2` |
| `metrics_btc_eth.json` | 全部指标 + 数据溯源 + 自检结论 |
| `nav_btc_eth.html` | plotly 交互图（plotly.js 内联，离线可开）：净值双线（对数/线性可切）+ 回撤副图 + ETH 权重副图 + 最大回撤区间阴影 |
| `btc_eth_daily_raw.csv(.meta.json)` | 日线缓存与溯源记录（`--no-cache` 可强制重拉） |

## 四、结果（2016-08-05 ~ 2026-08-02，523 周）

| 指标 | 线1 滚动互平衡 | 线2 买入持有 |
|---|---|---|
| 终值 | **48,999.07 USD** | **27,533.44 USD** |
| 总收益 | +24,399.54% | +13,666.72% |
| 年化 CAGR | +73.44% | +63.71% |
| 最大回撤 | **−87.19%** | **−90.46%** |
| 再平衡次数 | **256** | 0 |
| 累计手续费 | 150.54 USD | 0.20 USD |
| 最好自然年 | 2017 +4,916.73% | 2017 +3,760.96% |
| 最差自然年 | 2018 −76.33% | 2018 −79.40% |

参照：100% BTC 终值 21,898.65 USD；100% ETH 终值 33,168.23 USD。
最大回撤区间均为 2018-01-12 → 2018-12-14。

结论：10 年区间内滚动互平衡相对买入持有多赚 21,465 USD（1.78×），
CAGR +9.72pp，同时最大回撤浅 3.28pp —— 即**收益更高且回撤更小**，
代价是 256 次交易、150 USD 手续费（占本金 75%，但仅占终值 0.3%）。

## 五、自检（`IS_PASS`）

脚本每次运行都会打印四项不变量校验，全通过才返回退出码 0：

- (a) 线2 终值 == `q_eth·末价 + q_btc·末价`（除建仓费外零费用漂移）—— 实测 abs diff `0.000e+00`
- (b) 每次再平衡后 \|w_eth − 50%\| 最大 `1.012e-04`，远小于 1pp 阈值
- (c) 手续费只在交易周计提；266 个无交易周 NAV 仅随价格变动，误差 `0.000e+00`
- (d) 周线数据完整性：523 根、无 NaN/重复/非正价、间隔中位数 7 天

此外已用**独立复算**（另写一套纯循环实现，不引用本项目任何模块）逐项比对
终值 / 最大回撤 / 再平衡次数 / 累计手续费 / CAGR，全部完全一致。

## 六、模块结构

```
btc_eth_rebalance.py   CLI 入口：拉数 → 回测 → 指标 → 落盘 → 自检
config.py              路径、网络、标的、BacktestConfig（不可变参数）
data_sources.py        代理探测、Yahoo/Coinbase/Bitfinex/Kraken、周线重采样、缓存
backtest.py            两条线的撮合引擎（WeekRecord / LineResult）
metrics.py             CAGR、最大回撤、自然年收益、波动率、单币参照
selfcheck.py           四项不变量校验，产出 IS_PASS
report.py              终端表格、CSV/JSON 落盘、plotly HTML
```

## 七、可调参数

```bash
python btc_eth_rebalance.py --band 0.05        # 5pp 阈值（交易更少）
python btc_eth_rebalance.py --fee 0.0004       # 万四费率
python btc_eth_rebalance.py --capital 1000     # 改初始投入
python btc_eth_rebalance.py --start 2018-01-01 # 改区间
python btc_eth_rebalance.py --no-cache         # 强制重新联网拉数
python btc_eth_rebalance.py --no-chart         # 跳过 HTML
```
