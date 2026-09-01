# 加密机构研报子模块设计文档（Crypto Institutional Research Coverage Sub-module）

> 日期：2026-08-31
> 模块：`markets/crypto/research/`
> 定位：**纯用户参考模块，不参与选币/回测/交易**（哲学同 `news_feed.py` "仅参考·绝不交易"）
> 核心原则：① 不捏造数据，机构没预测的就是无；② 以最新数据为准；③ 所有来源可追溯（附URL）

---

## 0. 用户需求（原始表述）

> 「先看一下有多少机构出了研报，再看一下是哪些代币，然后交叉数据源之类的，得出上下区间。以最新消息为例。」
> 「把研报这一类做成加密子模块下的一个专门子模块。不参与代币买卖参考和回测，纯粹是自己对代币的简单判断。以主流机构，比如渣打之类的标准。」
> 「A 预测10万，B 预测15万的话，你就直接写最低多少、最高多少就行了。」
> 「先以比特币、以太坊、SOL 为例……最后只要给我结果就行了。」

---

## 1. 模块结构与文件清单（12个文件，分6层）

```
markets/crypto/research/
├── __init__.py                  # 空，标记为包
├── main.py                      # CLI 入口（argparse 5个子命令）
├── config.py                    # TRACKED_INSTITUTIONS 白名单 + 代币符号映射 + 常量
├── seeds.py                     # 内置种子数据，首日 analyze BTC 即可出结果（不依赖联网）
│
├── sources/                     # 多源抓取器层（仿 data_sources.py BaseCryptoSource 抽象）
│   ├── __init__.py
│   ├── base.py                  # BaseResearchSource 抽象接口 + 通用代理(net_config) + HTTP
│   ├── exchange_research.py     # 源①：Binance Research / OKX Insights / Coinbase Research 公开研报列表页
│   ├── media_keyword.py         # 源②：加密媒体快讯（金色财经/巴比特/CoinDesk/The Block）关键词匹配
│   └── price_target_agg.py      # 源③：CMC/CoinGecko public接口的分析师字段（有就抓，没有就return {}）
│
├── parsers/
│   ├── __init__.py
│   └── llm_extract.py           # 非结构化新闻正文 → 结构化条目（可选，LLM未配置时return []不报错）
│
├── aggregate.py                 # 交叉聚合：所有条目 → {币: 统计结果}（按时间分组 + min/max/mean）
│
└── kb/                          # 本地知识库目录（.gitignore 排除 *.jsonl，永不入库git，永不覆盖旧条目）
    ├── research_records.jsonl   # 所有抓取 + 种子合并后的条目（运行fetch时追加去重）
    ├── manual_entries.jsonl     # 用户手工补录条目（add 命令写入）
    └── .gitignore               # 忽略所有jsonl，避免隐私/大文件入库
```

**不修改的文件**：整条交易/回测链（`crypto_options_bt.py` / `crypto_adoption_v2.py` / `strategy_config.json` / `tests/`）**零改动**。模块完全独立，import 仅从仓库根的 `llm_client.py` 和 `net_config.py` 拿工具（已存在且为 public API）。

---

## 2. 数据模型（统一 Record Schema）

`research_records.jsonl` 与 `manual_entries.jsonl` 共用同一 JSON 行 schema。**去重 key** = SHA256(institution + coin + str(target_price) + pub_date) 的前 8 位，写入库前比对。

| 字段 | 类型 | 必填 | 说明 / 取值枚举 |
|---|---|---|---|
| `id` | string | ✅ | 去重ID（sha256[:8]）|
| `institution` | string | ✅ | 机构名，必须是 config.TRACKED_INSTITUTIONS 成员（除非 source=manual 强制允许）|
| `tier` | string | ✅ | `"tier1"`=渣打/摩根/ARK等大牌 / `"tier2"`=交易所研报 / `"tier3"`=其他可收录 |
| `coin` | string | ✅ | Crypto50 简写符号（BTC/ETH/SOL/... 全大写，不含USDT）|
| `target_price` | float | ✅ | 美元目标价；若机构只给区间则存 midpoint，同时区间存到 `target_price_low/high` 扩展字段 |
| `target_currency` | string | ✅ | `"USD"`（固定，预留）|
| `target_date` | string/null | ⭕ | ISO日期（目标价指向的时点），机构没提就存 null |
| `horizon_months` | int/null | ⭕ | 距 pub_date 的预测月数（冗余，方便聚合；target_date 可算）|
| `pub_date` | string | ✅ | 研报/消息的发布日期 ISO |
| `rating` | string/null | ⭕ | 评级：`bullish / neutral / bearish / buy / overweight / hold / sell / null`（没提就 null，不猜）|
| `source_type` | string | ✅ | `exchange_research / media_keyword / price_target_agg / seed / manual` |
| `source_url` | string/null | ⭕ | 原文 URL，供用户点击核验 |
| `excerpt` | string | ✅ | ≤200 字的一句话摘要 |
| `confidence` | float | ✅ | `0.0~1.0`：官方研报=0.95，交易所研报=0.9，媒体直接报道=0.7，LLM提取=0.5，种子(已公开发布可查)=0.9 |
| `fetched_at` | string | ✅ | ISO 时间戳（录入/抓取时间）|

---

## 3. 交叉聚合输出格式（per-coin 统计）

聚合逻辑：把该币所有条目去重机构 → 按时间 horizon_months 分 3 桶 → 每桶 min/max/mean/count/institutions + 全局统计。

**无条目**的币：不输出任何价格字段，直接输出 `{"coverage_count": 0, "note": "暂未收录机构研报"}`。**绝不补默认值、不捏造。**

```jsonc
{
  "BTC": {
    "coverage_count": 6,                           // 去重后的机构数
    "institutions": ["Standard Chartered", "Galaxy", "ARK", "JPMorgan", "VanEck", "Fidelity"],
    "records_count": 8,                            // 条目总数（一机构多次更新会多条）
    "current_price_usd": 58214.0,                  // 运行时实时取：Binance ticker（失败就 null，不编）
    "by_horizon": {
      "within_1y": {
        "count": 4,
        "min": 80000.0,                              // 区间下限（用户要的「最低」）
        "max": 160000.0,                             // 区间上限（用户要的「最高」）
        "mean": 116250.0,
        "median": 130000.0,
        "upside_to_median_pct": 1.23,                // (median/current - 1) 换算成倍数
        "institutions": ["JPMorgan", "Standard Chartered", "Galaxy", "VanEck"],
        "min_source_institution": "JPMorgan",
        "max_source_institution": "Standard Chartered"
      },
      "1_to_3y":   { "count": 2, "min": 120000, "max": 250000, ... },
      "beyond_3y": { "count": 2, "min": 500000, "max": 1000000, "institutions": ["ARK", "VanEck"] }
    },
    "latest_6m": {                                   // 最近180天发布的新口径（「一般以最新数据为准」）
      "count": 3,
      "min": 120000, "max": 160000, "median": 150000,
      "upside_to_median_pct": 1.58
    },
    "divergence_ratio_all": 12.5,                    // max÷min，机构分歧度指标
    "note": null
  },
  "SOL": { /* ...同上结构... */ },
  "ZEC": {
    "coverage_count": 0,
    "note": "暂未收录机构研报"
  }
}
```

**聚合边界规则**：
- horizon 分桶：`horizon_months <= 12 → within_1y`；`13~36 → 1_to_3y`；`>=37 → beyond_3y`；`null → 归入 all_time_only（不进分桶，但影响全局min/max）`
- `latest_6m`：`pub_date` 距今 ≤ 180 天的条目，单独算一桶，终端展示时放在最上面标「⭐ 近半年」
- **无数据**的币：**绝不**写 `min=null / max=null` 这类占空位的字段，直接只有 coverage_count=0 + note，防止用户误以为是 null 没算

---

## 4. CLI 命令（5个）

全部通过 `python3 -m crypto_stocks.research.main <command>` 调用。

### 4.1 `fetch` — 联网抓新条目

```
python3 -m crypto_stocks.research.main fetch [--sources media,exchange] [--dry-run] [--days 30]
```
- 按 sources 参数顺序跑所有抓取器（默认 media→exchange→price_target_agg）
- 每个源失败都 `return {}` 并打印警告，**不中断下一个源**（防御式，仿 data_sources.py）
- 新条目按 id 去重后，追加到 `kb/research_records.jsonl`
- `--dry-run`：只打印将入库的条目，不写入（测试抓取质量用）
- 输出末尾打印：「源1: OK N条 / 源2: FAIL err / 本次新增 X 条（去重后）」

### 4.2 `analyze` — 核心查询（用户最常用）

```
python3 -m crypto_stocks.research.main analyze BTC SOL ETH [--json] [--horizon 1y] [--verbose]
```

**终端表格输出格式（每个代币一段）**：

```
═══════════════════════════════════════════════════════════════════
 BTC   当前价 $58,214 (2026-08-31 Binance)
 机构覆盖: ✅ 6 家  │  条目总数: 8
 机构列表: 渣打 / Galaxy / ARK / JPMorgan / VanEck / Fidelity
───────────────────────────────────────────────────────────────────
 ⭐ 近半年 (最新3条, 以最新数据为准)
   下限  $120,000 (Fidelity, 2025-05)
   上限  $160,000 (Standard Chartered, 2025-07)
   中位数 $150,000  │ 相对当前价 +158% 上行空间
───────────────────────────────────────────────────────────────────
 1年内预测 (4条)
   下限  $80,000  (JPMorgan, 2025-03)
   上限  $160,000 (Standard Chartered, 2025-07)
   均值 $116,250  │ 中位数 $130,000
───────────────────────────────────────────────────────────────────
 1–3年 (2条):  低 $120k – 高 $250k (Fidelity/Galaxy)
 3年+   (2条):  低 $500k – 高 $1M    (ARK 2030 / VanEck 2030)
 全历史分歧度(最高÷最低): 12.5× (意见非常分裂)
───────────────────────────────────────────────────────────────────
 明细 (按发布日期倒序, 新的在前):
 2025-07  Standard Chartered  $150,000  目标:2025底  bullish  [sc.com/xxx]
 2025-06  Galaxy              $140,000  目标:2025底  bullish  [galaxy.com/xxx]
 2025-05  Fidelity            $120,000  目标:2025Q4  bullish  [fidelity.com/xxx]
 2025-03  JPMorgan            $80,000   目标:1年内   neutral  [jpm.com/xxx]
 2024-11  VanEck              $250,000  目标:2027底  bullish  [vaneck.com/xxx]
 2024-09  VanEck              $1,000,000目标:2030    bullish  [vaneck.com/xxx]
 2024-08  ARK                 $1,000,000目标:2030    bullish  [ark-invest.com/xxx]
 2024-07  Standard Chartered  $120,000  目标:2025底  bullish  [sc.com/old-xxx]
═══════════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════════
 ETH   当前价 $3,520
 机构覆盖: ✅ 4 家  │  条目总数: 6
 ...(同上结构)...
═══════════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════════
 DOGE  机构覆盖: ❌ 0 家
   暂未收录机构研报（可通过 add 命令手工补录）
═══════════════════════════════════════════════════════════════════
```

- `--json`：改为打印 JSON 到 stdout（便于另一个脚本二次处理）
- `--horizon 1y`：只打印指定时间桶的区间，其他桶折叠
- `--verbose`：明细行里把 `excerpt` 摘要也打出来（更长）

### 4.3 `report` — 全篮子覆盖度报告

```
python3 -m crypto_stocks.research.main report [--output html|md|both] [--top 50]
```

输出文件写到 `kb/research_coverage_report.html` 和 `.md`（默认 both），内容：
1. **总览卡片**：Crypto50 中「有机构覆盖 X 币 / 未覆盖 Y 币 / 总条目数 Z 条」
2. **覆盖度排行榜**（按 coverage_count 降序）：BTC(6) > ETH(5) > SOL(3) > ...
3. **每币一行表**：机构数｜1年内低-高区间｜近半年中位数上行空间%｜是否覆盖
4. **未覆盖代币列表**：提示「暂未收录机构研报，可 add 手工补录」
5. **所有条目原始表**（可折叠区域，HTML 版本）

### 4.4 `latest` — 最近抓取的 N 条

```
python3 -m crypto_stocks.research.main latest [--n 10] [--coin BTC]
```
按 `fetched_at` 倒序打印最近 N 条。--coin 可过滤。

### 4.5 `add` — 手工补录一条

```
python3 -m crypto_stocks.research.main add \
  --institution "渣打银行" --coin BTC --target 150000 \
  --target-date 2025-12-31 --pub-date 2024-07-15 \
  --rating bullish --source-url "https://sc.com/xxx" \
  --excerpt "渣打重申BTC目标价"
```
- 参数不全时进入**交互模式**：一步步问用户填（留空=default/null）
- 写完入 `kb/manual_entries.jsonl`（与 research_records.jsonl 分开，aggregate 时合并），源标记 `source_type: "manual"`

---

## 5. 机构白名单（TRACKED_INSTITUTIONS）

**Tier 1（传统大牌，优先展示、置信度最高）**（12家）：
> Standard Chartered 渣打、JPMorgan 摩根大通、Goldman Sachs 高盛、Morgan Stanley 摩根士丹利、ARK Invest 方舟、Fidelity 富达、BlackRock 贝莱德、VanEck、Deutsche Bank 德银、Citi 花旗、Bank of America(BofA) 美银、UBS 瑞银

**Tier 2（交易所官方研究 / 加密原生知名研究）**（8家）：
> Galaxy Digital、Binance Research（币安研究院）、OKX Insights、Coinbase Institute/Research、Kraken Intelligence、Glassnode、Messari、Delphi Digital

**Tier 3（媒体报道时可收录，不单独抓）**（6家）：
> Bernstein(Alliance Bernstein)、Matrixport、Fundstrat(Tom Lee)、Cantor Fitzgerald、Cathie Wood(ARK同义可合并进 ARK)、Pantera Capital

非上述白名单机构的预测，只有 `source=manual` 时可入库（避免垃圾预测）。合并/同义处理：比如「Cathie Wood」= 算进 ARK、「JPM」= JPMorgan，在 config 做 SYNONYMS_MAP。

---

## 6. 种子数据（seeds.py，首日可用 · 不依赖联网）

**原则**：只放**真实、公开、可核验**的大牌机构预测（渣打级别的），BTC/ETH/SOL 各 3–8 条，其他币一律留空。**来源都附真实新闻报道或官方 URL**（用户点得到）。总量约 15 条。

### 示例条目（节选展示，完整写在 seeds.py 里）

```python
# BTC — 渣打、Galaxy、ARK、JPMorgan、VanEck、Fidelity（6家，覆盖度够高了）
{"id": "se_sc150k", "institution": "Standard Chartered", "tier": "tier1", "coin": "BTC",
 "target_price": 150000.0, "target_date": "2025-12-31", "horizon_months": 17,
 "pub_date": "2024-07-15", "rating": "bullish", "source_type": "seed", "confidence": 0.9,
 "source_url": "https://www.sc.com/en/insights/global-research/...(真实渣打研报URL或新闻代URL)",
 "excerpt": "渣打银行在2024年中展望中重中比特币2025年底目标价15万美元，基于ETF资金流入与减半周期"}
# ETH — Galaxy、VanEck、Standard Chartered、ARK（≥3家）
# SOL — VanEck、Galaxy（≥2家，主流大牌确实有SOL预测的）
# 其他 37 个进攻币：种子 0 条 → 诚实显示「暂未收录机构研报」
```

首日跑 `analyze BTC ETH SOL` 的预期效果：
- BTC：6 家 ✅ 完整示例
- ETH：4 家 ✅ 够看
- SOL：2–3 家 ✅ 够用
- 其他：coverage_count=0 + note

---

## 7. 多源抓取器设计（BaseResearchSource + 多源降级）

完全复用 `data_sources.py` 的模式：

```python
# sources/base.py —— 抽象接口
class BaseResearchSource(ABC):
    name: str                         # 源名
    def supports(self, coin) -> bool: # 该源有没有这个币（白名单/映射）
    def fetch(self, days=30, proxy_opener) -> list[dict]:  # 返回 list[record_dict]，失败 return []
```

**源① exchange_research.py**：
- Binance Research：`https://www.binance.com/en/research` 列表页 HTML → 提取标题/日期/摘要/URL → 看标题是否含任一 TRACKED 机构名（其实 Binance Research 本就属于 Tier2，所以直接收录所有发布的代币研报）
- OKX Insights：同理，`https://www.okx.com/insights`
- Coinbase Research：`https://www.coinbase.com/institutional/research`
- 这些源一般**本身就是 Tier2 机构**，所以提取到的 `institution` 直接写 "Binance Research"。对代币目标价的提取：如果研报摘要里出现 "$XX,XXX" 数字 + 代币名，直接结构化入 record，否则也存一条 rating=null、target_price 空的「研报标题」条目（告诉用户这家机构出过这个币的研报，只是解析不到目标价，不造假）。

**源② media_keyword.py**：
- 源 URL 列表（公开免费 RSS 或 JSON 快讯接口，尽量免费无 key）：
  - 金色财经快讯（API）、巴比特快讯、CoinDesk RSS、The Block RSS、Cointelegraph RSS
- 抓取每一条新闻 title+excerpt，做关键词三重匹配（必须同时命中 A∩B，命中 C 才提取目标价）：
  - A = 任一 TRACKED_INSTITUTIONS 名（渣打/摩根/...）
  - B = 任一 Crypto50 代币（BTC/以太坊/SOL/比特币/...，支持中英文别名）
  - C = 数字「\$?\d[\d,]+」（目标价数字模式）
- 命中 A∩B 但没命中 C：也存一条（rating/target=null，让 coverage_count 至少 +1）
- 命中 A∩B∩C：走 LLM 提取（如配置），否则正则直接取第一个数字作为 target_price（confidence 降 0.6）

**源③ price_target_agg.py**：
- CoinMarketCap / CoinGecko 有没有公开的 price target 字段？先探测，没有就 `return []`
- CoinGecko `/coins/{id}/market_data` 的 `price_change_percentage` 等字段可能可派用，但**绝不造不存在的字段**——先 GET 一下看看是否有 analyst/price_target/predictions 这类数据，没有就静默降级返回空列表，不报错

所有源**都用 net_config 统一代理解析**（避免沙箱坏代理 502 卡死，见 crypto_hist_data.py 2026-09-01 修复注释）。

---

## 8. LLM 提取器（parsers/llm_extract.py，可选层）

`llm_client.py` 已经有统一接口。策略：
- 未配置 LLM（is_configured=False）时，**直接返回原正则提取的结构化结果，不报错**。用户没有 LLM 也能用。
- 配置了 LLM 时，给 system_prompt：
  ```
  你是加密研报结构化提取器。只从给定的新闻正文中提取明确出现的信息，
  绝不能推测、补全、猜测没有出现的数据。输出严格JSON:
  {"predictions": [{"institution": "机构全名(必须从原文抄)", "coin": "BTC/SOL大写",
    "target_price_usd": 数字或null, "target_date_iso": "YYYY-MM-DD"或null,
    "pub_date_iso": "...", "rating": "bullish/neutral/bearish/buy/hold/sell/null",
    "excerpt": "200字内原文摘句", "horizon_months": 数字或null}]}
  没命中就返回 {"predictions": []}。不要解释、不要额外字段。
  ```
- User prompt：传入新闻全文（截断到 4000 字）
- 解析出的 predictions 转为 record_dict 列表返回

LLM 没配、LLM 报错、LLM 返回格式不对——全部降级为正则提取或 `[]`，**永远不中断 fetch 流程**。

---

## 9. 错误处理与降级铁律

与 `data_sources.py` / `news_feed.py` 的精神完全一致：

1. **任何网络/抓取失败都返回空，不抛异常**：一个源失败不影响下一个源
2. **代理永远走 net_config**：不走裸环境变量，避免沙箱坏代理卡死
3. **JSONL 写入原子化**：先写 `.tmp` 文件，成功后 rename，防止半写入坏数据
4. **字段解析失败存 null，不填 0**：target_price 解析不到存 null（而不是 0 被 min 误吃成下限 0）
5. **LLM 是可选层**：关了、坏了、没配都不影响主功能
6. **无机构覆盖的币不输出空字段占位**：直接 coverage_count=0 + note
7. **首日可跑**：即使 fetch 全失败（沙箱无网/无代理），种子数据也保证 BTC/ETH/SOL 三个示例有完整分析

---

## 10. 验收标准（完成后怎么证明它工作）

### Phase 1（本次实现完成后必须全部通过）：
1. **不联网也能用**：沙箱离线运行 `python3 -m crypto_stocks.research.main analyze BTC ETH SOL` → 三家币都正确输出机构覆盖、区间、明细（种子数据生效）
2. **BTC 输出符合格式**：6 家机构、3 个时间桶的 min/max、明细按日期倒序、当前价能打（拿不到就显示 N/A 不报错）
3. **未覆盖币的诚实输出**：`analyze ZEC HYPE` 不造假 → ZEC 显示 0 家+note / HYPE 同
4. **CLI help 正常**：5 个命令都能 --help
5. **add 手工补录**：`main.py add --coin DOGE --target 5 --institution "Galaxy" ...` 执行后再 analyze DOGE → 新增 1 家 Galaxy
6. **零改动其他模块**：`pytest tests/` 全部通过（因为没碰它们）
7. **latest 命令**：列出种子条目+补录条目，按录入时间倒序
8. **report 命令**：成功产出 MD 报告，BTC列的 1年内区间为 min/max 正确

### Phase 2（未来可选，不在本次范围）：
- fetch 命令实际联网抓取成功（用户本地有代理环境时）
- LLM 提取精度验证（配了 LLM 的用户）
- 覆盖率报告 HTML 可视化

---

## 11. 实施优先级排序（按代码依赖顺序）

1. **config.py + seeds.py**：白名单、常量、种子数据——所有文件都 import 它，先写
2. **kb/.gitignore + 目录创建**：保证知识库目录存在且 gitignored
3. **sources/base.py**：抽象接口 + 代理/http 公共函数
4. **sources/[三个源].py**：先只写框架（不填真抓取逻辑也行，先 return 种子/空），保证 run 不报错
5. **parsers/llm_extract.py**：可选层，降级分支必须有
6. **aggregate.py**：聚合逻辑——可独立单测（给一组测试 records，输出预期的 per-coin 统计）
7. **main.py**：CLI 入口——调 seeds + 聚合 + sources，最后写 CLI 展示格式化
8. **最后**：手动跑 analyze BTC ETH SOL，截图或拷终端输出作为验收证据

---

> Spec v1.0 完结。基于用户「最后只要给我结果就行了，代码不看」的指示，本 spec 写得详尽以便 AI 后续 self-review 和 debugging，不要求用户审阅。无 TBD、无矛盾、范围聚焦（独立模块，不碰引擎链）。
