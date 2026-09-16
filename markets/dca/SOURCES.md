# markets/dca —— 多市场长历史数据仓 & 定投推演

> 建立于 2026-09-17。目的：**一次性把数据与渠道固化到本地**，此后做任何定投/长期推演
> 直接读盘，不再重复摸索接口。

## 目录

```
markets/dca/
├── SOURCES.md            # 本文件：渠道清单、参数、坑
├── fetch_history.py      # 唯一抓取入口（多源回退 + 落盘 + FETCH_LOG）
├── fetch_macro.py        # 宏观序列（CPI / 汇率 / 利率）
├── dca_backtest.py       # 定投推演引擎
└── data/
    ├── FETCH_LOG.json    # 每次抓取的逐标的记录（含失败原因，不静默）
    ├── history/*.csv     # date,close,adjclose —— 日频，adjclose 含分红再投资
    └── macro/*.csv
```

## 渠道清单（按优先级）

| # | 渠道 | 适用 | 关键参数 | 说明 |
|---|---|---|---|---|
| 1 | **Yahoo chart v8** | 美股/港股/指数/ETF/汇率/商品 | `period1=1900-01-01&period2=now&interval=1d&events=div,split` | 主力。`adjclose` **天然含分红再投**，这是长周期推演的命门 |
| 2 | Yahoo query1 | 同上（备用域名） | 同 v8 | query2 限流时切 |
| 3 | 东财 push2his | A股/港股/ETF | `klt=101/102`、`fqt=1`(前复权) | A股腿首选，但**单 IP 强限流**，需延时 |
| 4 | 腾讯 fqkline | A股/港股 | `qfq`、**单次 ≤640 条** | 必须按 `end` 分段回退拼接 |
| 5 | FRED fredgraph | 宏观（CPI/利率） | `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>` | **免 key**，直接 CSV |

**代理**：统一 `from net_config import proxy_opener`（仓库唯一真源，默认 `http://127.0.0.1:3067`）。
环境变量里的 57113 等是坏的，`net_config` 已处理"默认优先于环境变量"。

## 踩过的坑（不要再踩）

1. **`range=max` 会把周线降频成季线** —— Yahoo 对 `range=max` 会按数据量自动降采样。
   做长历史必须用 `period1/period2` 显式指定起止，否则拿到 169 条覆盖 42 年（=每季度一条）还看不出错。
2. **Windows 上 1970 前的时间戳** —— `datetime.fromtimestamp(负数)` 直接 `OSError: [Errno 22]`。
   `^GSPC` 从 1927 年起，必然踩到。解法：`EPOCH + timedelta(seconds=ts)` 手算。
3. **指数 ≠ 全收益** —— `^GSPC` 的 `adjclose` 就等于 `close`（指数不做分红调整），
   标普500 含分红要用 **`^SP500TR`**（1988 起）。红利类策略用价格指数会严重低估，别犯。
4. **A股复权三闸门**（沿用 ashare 口径）：本地 K 线未复权 / Yahoo 系统性缺交易日 /
   腾讯 `hfq` 后复权才是可用源。本仓 A 股 ETF 腿走东财 `fqt=1`。
5. **东财限流是常态**，不是故障。单腿连抓必断，必须延时 + 缓存。
6. 跨市场**日频相关会被交易时段错开压低**（实测 0.045 → 周频 0.109），报分散度必须用周频。

## 已落盘标的

见 `data/FETCH_LOG.json`（每次运行自动刷新，含条数、起止日、命中渠道、失败原因）。
