# 数据源注册清单（2026-09-09 验证）

> 原则：**历史/延迟数据基本全免费，付费的只是实时流**。注册只需邮箱，无需信用卡。
> 注册后把 **API key 字符串** 发我即可，我会存到 `markets/commodity/keys.local.json`（已加入 .gitignore，不进仓库）。

---

## 一、必注册（3 个，覆盖当前所有缺口）

### 1. EIA — 美国能源信息署 ⭐ 最高优先
- **注册链接**：https://www.eia.gov/opendata/register.php
- **文档**：https://www.eia.gov/opendata/documentation.php
- **免费额度**：约 5,000 次/天，无信用卡
- **补什么缺口**：本轮最大缺口——**气体与能源全链**
  - 天然气：Henry Hub 现货/期货、各州门站价、居民/工业/电力终端价
  - LPG 家族：丙烷（Propane）、丁烷、乙烷、丙烯
  - 工业气体：氦气（Helium，EIA 有专门序列）
  - 煤炭、电力（含区域电价）、各国 LNG 进出口价
- **为什么必须**：World Bank Pink Sheet 有天然气但年更粗；FRED 只有 Henry Hub 日频和日本 LNG，**丙烷/丁烷/氦气 FRED 根本没有此序列**

### 2. Twelve Data — 全球个股（含日股）⭐ 次优先
- **注册链接**：https://twelvedata.com/register
- **免费额度**：800 credits/天（8/分钟），**20+ 年历史**，70+ 交易所
- **补什么缺口**：**日股丰田 7203.T**（腾讯行情接口无日股），以及全球个股冗余校验
- **代码格式**：`7203.T`（东证）、`0700.HK`（港股）、`AMD`（美股）
- **注意**：免费档官方标注"3 markets"，若日股被挡，我会改用其他通道

### 3. FRED — 圣路易斯联储 API key
- **注册（先建账号）**：https://fredaccount.stlouisfed.org/login/secure/
- **拿 key**：https://fred.stlouisfed.org/docs/api/api_key.html
- **免费额度**：120 次/分钟
- **补什么**：我们已用 CSV 通道抓到 88 个序列，但**有 key 才能按关键词搜索全部 80 万+ 序列**，不必猜 ID（本轮贵金属 ID 失效就是猜 ID 的代价）

---

## 二、可选（冗余与扩面）

| 源 | 注册链接 | 免费额度 | 用途 |
|---|---|---|---|
| Alpha Vantage | https://www.alphavantage.co/support/#api-key | 25 次/天，20+ 年 | 美股兜底冗余 |
| Finnhub | https://finnhub.io/register | 60 次/分钟 | 美股基本面、新闻情绪 |
| Nasdaq Data Link (Quandl) | https://data.nasdaq.com/account/register | 50 次/天 | 连续期货、另类数据 |

---

## 三、不推荐（免费档无用）

- **EODHD**：https://eodhd.com/register — 免费档**只有过去 1 年**数据，30 年历史需 $19.99/月。覆盖虽好（60+ 交易所）但免费档对回测无意义。
- **Tiingo**：注册页已 404，且免费档国际股票覆盖弱。

---

## 四、已打通、无需注册（本轮实测）

| 通道 | 状态 | 覆盖 |
|---|---|---|
| **腾讯行情** `web.ifzq.gtimg.cn` | ✅ 全历史 | 港股（hfq 后复权，2004 起）、美股（qfq，2007 起）；**单段上限 640 条，按日期分段可取全史**；❌ 无日股 |
| FRED CSV `fredgraph.csv` | ✅ | 商品 41 + 全球资产 47 序列，1992 起 |
| World Bank Pink Sheet | ✅ | 71 品种月度，1960–2025（含金银铂） |
| Yahoo Finance | ❌ | "Edge: Too Many Requests" 限流 |
| stooq | ❌ | JS PoW 验证，破解后仍 Access denied |
| 东财 push2his | ❌ | 分片域名（33./63.push2his）被代理阻断 |

### 已实测可得标的（无需等注册）
| 标的 | 代码 | 数据 | 区间 |
|---|---|---|---|
| 腾讯控股 | hk00700 | 550+640 周 hfq | 2004-06 起 |
| 中国海洋石油 | hk00883 | 同上 | 2004-06 起 |
| 紫金矿业 | hk02899 | 同上 | 2004-06 起 |
| 超威半导体 | usAMD.OQ | 640 周 qfq | 2007-09 起 |
| 丰田汽车 | 7203.T | ⏳ 待 Twelve Data | — |

**复权口径提醒**：港股长期 qfq（前复权）会把早期价格压成负数（腾讯 2004 年 qfq 收盘 −54.98），
收益率计算必须用 **hfq 后复权**。已确认 hfq 正常（2004 年 4.025 → 2014 年 568.18）。
