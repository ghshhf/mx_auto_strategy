# markets/dca —— 多市场长历史仓 & 长期定投推演

> 建立 2026-09-17。**一次把数据与渠道固化到本地**，此后任何定投/长期推演直接读盘。

## 一句话用法

```bash
P=E:/xmanbian/_venv/mx_quant/Scripts/python.exe
$P markets/dca/fetch_history.py          # 增量抓数（已有跳过），落 data/history/*.csv
$P markets/dca/fetch_history.py --force  # 全量重抓
$P markets/dca/fetch_macro.py            # FRED 宏观序列
$P markets/dca/dca_long.py               # 40 年定投推演 → out/long_dca_result.json
```

## 目录

```
markets/dca/
├── SOURCES.md         渠道清单 + 参数 + 踩坑（新增数据源先看这里）
├── fetch_history.py   唯一抓取入口（多源回退 + 体检 + 毛刺清洗 + FETCH_LOG）
├── fetch_macro.py     FRED 宏观（免 key）
├── dca_backtest.py    定投引擎（dca / xirr / metrics / 滚动窗口）
├── dca_long.py        40 年推演（全收益构造 / bootstrap / 敏感性）
├── _verify.py         数据体检脚本
└── data/
    ├── FETCH_LOG.json 逐标的记录：条数/起止/命中渠道/清洗点/异常（**不静默**）
    ├── history/*.csv  date,close,adjclose（日频）
    └── macro/*.csv
```

## 已落盘数据（27 只，2026-09-17）

| 类别 | 标的 | 起点 | 年数 | 口径 |
|---|---|---|---|---|
| 美股指数 | ^GSPC / ^SP500TR / ^NDX / ^IXIC / ^DJI | 1927 / 1988 / 1985 / 1971 / 1992 | 99 / 39 / 41 / 56 / 35 | 价格为价格、TR 为全收益 |
| 美股 ETF | SPY / VOO / QQQ / SCHD / VYM / DVY / NOBL | 1993~2013 | 13~34 | adjclose 含分红 |
| 港股 | ^HSI / ^HSCE / 2800.HK / 3110.HK | 1986 / 1993 / 2008 / 2013 | 40 / 33 / 19 / 13 | 指数为价格，ETF 含分红 |
| A股 | 515100 / 510880 / 510300 / 159915 / 512880 / 000300 / 000001 | 1990~2020 | 6~36 | **腾讯 hfq 后复权** |
| 其他 | CNY=X / GC=F / ^TNX | 2001 / 2000 / 1962 | 25 / 26 / 64 | — |
| 宏观 | CPI(美/中) / 美元人民币 / 港元 / FFR / 10Y / 30Y / M2 | 1913~ | — | FRED |

## 三条命门（错一条，结果就废）

1. **`range=max` 会把周线降频成季线** —— 必须 `period1/period2` 显式指定。
2. **A股必须后复权（hfq / 东财 fqt=2）** —— 前复权对长期高分红品种（510880）会把
   历史价压成**负数**（实测 2008 段 −0.279），回测出 −99% 假浮亏。
3. **价格指数 ≠ 全收益** —— ^GSPC/^NDX/^HSI 的 adjclose == close。实测 38.7 年股息再投
   贡献 **2.24 倍**（年化 +2.11%）。不修正，长期定投低估一倍以上。

## 已知残留问题

- `^HSTECH` 在 Yahoo 返回 404（代码失效），恒生科技指数暂无源。
- 东财 push2his **强限流**，连续请求必断连（`RemoteDisconnected`）；当前 A股腿默认回退到腾讯。
- 腾讯 hfq 偶发**单日复权台阶错误**（510880 @ 2008-01-03），`clean_spikes()` 自动删除并记日志。
