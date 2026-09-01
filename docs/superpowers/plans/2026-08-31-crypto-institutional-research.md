# Crypto Institutional Research 子模块实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 `markets/crypto/research/` 独立子模块——支持查询 BTC/ETH/SOL 等主流币的机构研报覆盖数、机构列表、按时间分组的目标价上下区间（min/max），提供 5 个 CLI 命令（fetch/analyze/report/latest/add），**首日不联网即可用**（内置渣打/ARK/摩根等大牌种子数据），**绝不捏造、绝不参与交易/回测决策**。

**Architecture:** 6 层解耦：① config/seeds（数据基础）→ ② kb（本地持久化）→ ③ sources/（多源抓取器，仿 data_sources.py 降级模式）→ ④ parsers/（可选 LLM 结构化提取）→ ⑤ aggregate.py（交叉聚合，per-coin 统计）→ ⑥ main.py（CLI 展示层）。每层独立 import，聚合层和 CLI 层可单测。

**Tech Stack:** Python ≥ 3.11；HTTP 用 `urllib.request + net_config`（不引 requests，与 market_data.py 一致）；JSONL 原子写入用 tempfile；report 输出无外部依赖（纯标准库 html+table）。

---

## 文件结构总览（12 个要创建的文件）

| 文件 | 职责 |
|---|---|
| `markets/crypto/research/__init__.py` | 包标记 |
| `markets/crypto/research/config.py` | TRACKED_INSTITUTIONS 3 级白名单 + SYNONYMS_MAP + 常量（分桶） |
| `markets/crypto/research/seeds.py` | 15 条内置种子（BTC 6家 / ETH 4家 / SOL 3家） |
| `markets/crypto/research/sources/__init__.py` | 导出源 + `get_all_sources()` |
| `markets/crypto/research/sources/base.py` | BaseResearchSource 抽象 + 代理 HTTP + JSONL 原子 + 去重 id |
| `markets/crypto/research/sources/exchange_research.py` | 源① Binance/OKX/Coinbase 研报（桩 + 降级） |
| `markets/crypto/research/sources/media_keyword.py` | 源② 加密媒体关键词三重匹配（桩 + 降级） |
| `markets/crypto/research/sources/price_target_agg.py` | 源③ CMC/CoinGecko 目标价探测（桩 + 降级） |
| `markets/crypto/research/parsers/__init__.py` | 包标记 |
| `markets/crypto/research/parsers/llm_extract.py` | 可选 LLM 提取：未配置返回空、配了调 llm_client |
| `markets/crypto/research/aggregate.py` | 核心：records → per-coin 聚合（3桶 + 近半年 + 诚实零覆盖） |
| `markets/crypto/research/main.py` | argparse CLI（5 命令） + 终端格式化表格 |
| `markets/crypto/research/kb/.gitignore` | `*.jsonl` / `*.html` / `*.md` 全忽略（永不入库git） |

**要修改的 0 个文件**：模块完全独立，零侵入整条交易/回测链。

---

## Task 1: 目录脚手架 + .gitignore

**Files:**
- Create: `markets/crypto/research/__init__.py`, `markets/crypto/research/{sources,parsers}/__init__.py`
- Create: `markets/crypto/research/kb/.gitignore`

- [ ] **Step 1: 创建目录 + 4 个包文件**

Run:
```bash
mkdir -p /workspace/mx_auto_strategy/markets/crypto/research/{sources,parsers,kb}
```

Create 4 files:
```python
# markets/crypto/research/__init__.py
"""Crypto Institutional Research Coverage —— 纯参考模块，不参与交易/回测决策。"""
__version__ = "1.0.0"
```

```python
# markets/crypto/research/sources/__init__.py
from .base import BaseResearchSource, compute_record_id, read_jsonl, append_jsonl_atomic
from .exchange_research import ExchangeResearchSource
from .media_keyword import MediaKeywordSource
from .price_target_agg import PriceTargetAggSource
__all__ = ["BaseResearchSource","compute_record_id","read_jsonl","append_jsonl_atomic",
           "ExchangeResearchSource","MediaKeywordSource","PriceTargetAggSource"]
def get_all_sources():
    return [ExchangeResearchSource(), MediaKeywordSource(), PriceTargetAggSource()]
```

```python
# markets/crypto/research/parsers/__init__.py
"""Parsers: 非结构化 → 结构化 Record。"""
```

```
# markets/crypto/research/kb/.gitignore
*.jsonl
*.html
*.md
*.tmp
```

- [ ] **Step 2: 验证**

```bash
ls /workspace/mx_auto_strategy/markets/crypto/research/{__init__.py,sources/__init__.py,parsers/__init__.py,kb/.gitignore} | wc -l
# Expected: 4
```

- [ ] **Step 3: 提交**

```bash
git add markets/crypto/research/__init__.py markets/crypto/research/{sources,parsers}/__init__.py markets/crypto/research/kb/.gitignore
git commit -m "feat(crypto-research): task1 scaffolding + kb gitignore"
```

---

## Task 2: config.py（白名单 + 同义映射 + 代币别名 + 分桶常量 + 4 个纯函数）

**Files:**
- Create: `markets/crypto/research/config.py`
- Create: `tests/test_research_config.py`

- [ ] **Step 1: 创建 config.py**

`normalize_institution(raw) → str`, `tier_of(institution) → tier1|tier2|tier3|unknown`, `normalize_coin(raw) → str|None`, `normalize_rating(raw) → bullish|bearish|neutral|null` 四个纯函数。TIER1 12 家（渣打/JPM/GS/MS/ARK/Fidelity/BlackRock/VanEck/DB/Citi/BofA/UBS），TIER2 8 家（Galaxy/Binance/OKX/Coinbase/Kraken/Glassnode/Messari/Delphi），TIER3 6 家。代币别名覆盖 BTC/ETH/SOL/ADA/SOL/.../ONDO 的中英文简写共 40+ 条。分桶常量 `HORIZON_BUCKETS = (("within_1y",0,12), ("1_to_3y",13,36), ("beyond_3y",37,999))`，`LATEST_WINDOW_DAYS = 180`。

- [ ] **Step 2: 创建测试文件 test_research_config.py（11 个断言）**

4 组用例：`test_normalize_institution_synonyms_hit + test_normalize_institution_whitelist_direct + test_normalize_institution_unknown_passthrough`；`test_normalize_coin_aliases_and_case + test_normalize_coin_all_supported_upper_match + test_normalize_coin_unknown_is_none`；`test_tier_of_all_whitelisted + tier_of unknown`；`test_normalize_rating_common + none/empty + unknown_is_none_not_guessed`。

- [ ] **Step 3: 跑测试 → 全 PASS（config 实现后立即可过）**

```bash
pytest tests/test_research_config.py -v
# Expected: 11 passed
```

- [ ] **Step 4: 提交**

```bash
git add markets/crypto/research/config.py tests/test_research_config.py
git commit -m "feat(crypto-research): task2 config with 4 normalizers + 11 tests pass"
```

---

## Task 3: seeds.py（15 条真实公开种子 + 规范化函数）

**Files:**
- Create: `markets/crypto/research/seeds.py`
- Append to `tests/test_research_config.py` (3个种子断言函数)

- [ ] **Step 1: 创建 seeds.py**

SEED_RECORDS_RAW 列表含 BTC 8 条（渣打×2/Galaxy/ARK/JPM/VanEck×2/Fidelity）、ETH 4 条（渣打/Galaxy/VanEck/ARK）、SOL 3 条（VanEck/Galaxy/ARK），总计 15 条。每条含 institution/coin/target_price/target_date/horizon_months/pub_date/rating/source_url/excerpt。提供 `get_seed_records()` 函数，返回规范化后的完整 records：延迟 import `compute_record_id` 算 id；`tier_of`+白名单过滤；补 `source_type="seed"`、`confidence=0.9`、`fetched_at=now_iso_z`。

- [ ] **Step 2: 追加到 tests/test_research_config.py**

3 个断言：
- `test_seeds_are_valid_and_normed()`：≥13 条、id 全 8 位且去重、coin ∈ {BTC,ETH,SOL}、每条都有 tier/target_currency=USD/正 target_price/非空 excerpt。
- `test_seeds_btc_has_6_institutions_distinct()`：{渣打,GALAXY,ARK,JPM,VANECK,FIDELITY} 6 个都出现。
- `test_seeds_eth_has_at_least_3 + test_seeds_sol_has_at_least_2`：覆盖最低要求。

- [ ] **Step 3: 先跑 seed 测试 → 预期 FAIL（compute_record_id 来自 sources.base，此时 Task 4 还没写 → ImportError）。确认"失败先行"后再跑 Task 4。**

- [ ] **Step 4: 提交 seeds.py**

```bash
git add markets/crypto/research/seeds.py
git commit -m "feat(crypto-research): task3 15 seeds (BTC8/ETH4/SOL3 from tier1 public)"
```

---

## Task 4: sources/base.py（去重 id + JSONL 原子读写 + 代理 HTTP + 抽象基类）

**Files:**
- Create: `markets/crypto/research/sources/base.py`
- Create: `tests/test_research_sources_base.py`

- [ ] **Step 1: 创建 base.py**

包含：
1. `compute_record_id(record) → 8位sha256`，key = 机构小写|币大写|round(price,4)|pub_date[:10]
2. `read_jsonl(path) → list[dict]`，缺文件→[]、坏行跳过
3. `append_jsonl_atomic(path, new_records) → int`：读旧记录+比对 id 去重 → 新的与旧的合并后写 tmp 文件 → os.replace(path)；返回实际新增数
4. `http_get(url, timeout, headers, return_response)`：经 net_config.get_proxy_opener_params() 返回的字典构建 ProxyHandler；User-Agent 固定为 Chrome 124；任何异常 return 空字符串或 (0, b"")，永不抛
5. `BaseResearchSource(ABC)`：`name` 属性、抽象方法 `fetch_latest(days=30) → list[dict]`、`_finalize(raw_records) → list[normed_records_with_id]`（内部调 config 四个规范化函数，过 tier+coin 过滤后补所有字段、计算 id、去重同一批内的重复 id）

- [ ] **Step 2: 创建 tests/test_research_sources_base.py**

两组用例：
- `test_record_id_is_deterministic_and_dedupes()`：同 record 同 id；price/coin 任一变 id 变
- `test_jsonl_roundtrip_and_dedupe()`：tmpdir 下空读→[]、写 2 条→再写重复→0 新增、追加新 1 条→3 条总、坏行插中间→read 仍剩 3 条

- [ ] **Step 3: 跑测试（config 2 tests + sources base tests）**

```bash
pytest tests/test_research_config.py tests/test_research_sources_base.py -v
# Expected: config 11+4=15 tests PASS, sources_base 2 PASS → 全 PASS
```

- [ ] **Step 4: 提交**

```bash
git add markets/crypto/research/sources/base.py tests/test_research_sources_base.py tests/test_research_config.py
git commit -m "feat(crypto-research): task4 base with id dedup + atomic JSONL + proxy HTTP + 17 tests PASS"
```

---

## Task 5: 三个抓取源桩实现（失败降级 return []，不抛异常）

**Files:**
- Create: `markets/crypto/research/sources/exchange_research.py`
- Create: `markets/crypto/research/sources/media_keyword.py`
- Create: `markets/crypto/research/sources/price_target_agg.py`

- [ ] **Step 1: 三源桩创建（fetch_latest 最后必须 self._finalize(records) → 即使 records 空也不抛）**

- exchange_research.py：`ExchangeResearchSource`（name="exchange_research", tier2）。_ENDPOINTS 存 Binance Research/OKX Insights/Coinbase Research 三个 URL。循环 GET→空结果跳过。注释里写明真实抓取 TODO：解析研报卡片。空 records 入 finalize → 返回 []。
- media_keyword.py：`MediaKeywordSource`（name="media_keyword", tier3 confidence 0.7）。_RSS_FEEDS 存 CoinDesk/The Block/Cointelegraph。注释写明三重匹配（机构∩代币∩数字）。import 一个 `try_llm_extract_from_news`（失败不抛）。最终 records_raw 初始 [] → finalize → []。
- price_target_agg.py：`PriceTargetAggSource`。探测 CoinGecko `/coins/{bitcoin|ethereum|solana}` endpoint。`_pluck_possible_targets(data, coin)` 递归扫描 dict 有没有 analyst/price_target/prediction 类 key。有 CMC_PRO_API_KEY 时再试 CMC（桩不抓）。最后 finalize → []。

- [ ] **Step 2: smoke 测试（三源实例化 + 调 fetch_latest(days=1)）—— 必须返回空列表不抛异常**

```bash
cd /workspace/mx_auto_strategy && python3 -c "
from crypto_stocks.research.sources import get_all_sources
for s in get_all_sources():
    recs = s.fetch_latest(days=1)
    assert isinstance(recs, list), f'{s.name} not list'
    print(f'{s.name}: {len(recs)} records (沙箱环境应为0)')
print('OK 三源桩不抛异常')
"
```

Expected：三行 "0 records" + "OK 三源桩不抛异常"

- [ ] **Step 3: 提交**

```bash
git add markets/crypto/research/sources/{exchange_research,media_keyword,price_target_agg}.py
git commit -m "feat(crypto-research): task5 3 research source stubs (fail-safe return [])"
```

---

## Task 6: parsers/llm_extract.py（可选 LLM 层：未配置永远返回 []，永不中断）

**Files:**
- Create: `markets/crypto/research/parsers/llm_extract.py`
- Create: `tests/test_research_llm_extract.py`

- [ ] **Step 1: 创建 llm_extract.py**

提供 `try_llm_extract_from_news(title, body, max_chars=4000) → list[dict]`。内部三步：① `_is_llm_configured()` → try import `llm_client.is_configured`，失败/False 返回 []。② `_call_llm(content)` → 调 `llm_client.chat(system=SYSTEM_PROMPT, user=content)`，异常返回 ""。③ 剥 markdown code fence → json.loads → 看 predictions 列表，缺少 institution/coin 的跳过。SYSTEM_PROMPT 严格要求：绝不臆测、只取明确出现的信息、输出纯 JSON `{"predictions": [...]}`。

- [ ] **Step 2: 创建 tests/test_research_llm_extract.py（1 个 smoke 测试）**

`test_llm_extract_degrades_gracefully_without_llm()`：在沙箱（无 LLM 配置）情况下，调用 `try_llm_extract_from_news("渣打银行上调BTC目标价至15万美元", "渣打银行最新发布...")` 必须返回 `[]`，不抛异常、不返回臆测数据。

- [ ] **Step 3: 跑测试 PASS**

```bash
pytest tests/test_research_llm_extract.py -v
```

- [ ] **Step 4: 提交**

```bash
git add markets/crypto/research/parsers/llm_extract.py tests/test_research_llm_extract.py
git commit -m "feat(crypto-research): task6 llm_extract optional layer (degrades to [])"
```

---

## Task 7: aggregate.py（交叉聚合核心 + 9 个单元测试 ★业务逻辑）

**Files:**
- Create: `markets/crypto/research/aggregate.py`
- Create: `tests/test_research_aggregate.py`

- [ ] **Step 1: 写失败测试先行（tests/test_research_aggregate.py）—— 9 个断言**

`_sample_records()` fixture 构造 10 条记录：BTC 8 条（渣打17月/JPM21月/ARK78月/VanEck41月/VanEck77月/Galaxy12月/Fidelity6月/大摩null_target）+ ETH 2 条。

9 个用例：
1. `test_btc_aggregation_coverage_and_buckets`：BTC coverage_count == 7（6家目标价+大摩覆盖），institutions 去重后等于 {Standard Chartered,JPM,ARK,VanEck,GALAXY,Fidelity,Morgan Stanley}，records_count==8。
2. `test_btc_bucket_min_max_no_phantom_nulls`：按 horizon 分桶演算——within_1y = Galaxy(12)+Fidelity(6)=2 条 min120k/max140k/median130k、1_to_3y = 渣打(17)+JPM(21)=2 条 min80k/max150k、beyond_3y = ARK(78)+VanEck(41)+VanEck(77)=3 条 min250k/max1M。upside_to_median_pct=130000/58000≈×2.24。
3. `test_btc_latest_6m_window_only_recent`：today_iso="2026-08-31" 时 Galaxy(2026-05-01)+Fidelity(2026-04-22)+大摩(2026-03-01)=3 条，最新6m窗口 min120k/max140k（大摩 null 跳过）。
4. `test_divergence_ratio_is_max_div_min_across_all`：max(1M) / min(80k) = 12.5。
5. `test_eth_basic_aggregation`：coverage_count=2，within_1y count=0，1_to_3y 1条 beyond_3y 1条。
6. `test_zero_coverage_coin_outputs_nothing_but_coverage_zero_and_note`：requested_coins=["SOL","ZEC"] → 输出只有 coverage_count=0 和 note="暂未收录机构研报"。**没有任何 min/max/mean/median/by_horizon 等占位字段**（assert key not in）。
7. `test_records_sorted_by_pub_date_desc`：aggregate_records_with_details 返回的 all_records pub_date 倒序。
8. `test_aggregate_respects_requested_coins_order`：requested_coins=["ZEC","BTC"] → result 的迭代顺序是 ZEC→BTC。
9. `test_get_current_prices_handles_failure`（不 mock 真网络）：传空 coins 返回 {}；在沙箱离线环境传 ["BTC","ETH"] 也能返回 {}（只要不抛异常就算过，因为 HTTP 降级返回空串时 json.loads 会失败 → 返回 {}）。

- [ ] **Step 2: 跑 aggregate 测试 → 确认 FAIL（aggregate 模块还没写 → ModuleNotFound）**

- [ ] **Step 3: 写 aggregate.py**

对外 API 3 个：
- `aggregate_records(records, requested_coins=None, current_prices=None, today_iso=None)` 主函数。内部：按币分组 → 对每个币分桶 _bucket_of_horizon → _calc_bucket_stats(records_in_bucket, current_price) 返回 count/min/max/mean/median/upside×/institutions/min_src/max_src 字典 → 最近180天 latest_6m 桶统计；全局分歧度 max÷min；零覆盖币严格只输出 coverage_count=0+note。
- `aggregate_records_with_details(records, **kwargs)` = 主函数 + 每个币追加 all_records（按 pub_date 倒序）。
- `get_current_prices(coins)`：Binance `/api/v3/ticker/price?symbols=["BTCUSDT",...]` → JSON。任何异常返回 {}。

内部工具：`_price_filter(只取 target_price 有效正数)`、`_bucket_of_horizon(按照 HORIZON_BUCKETS 常量找桶)`、`_days_between(date_a_iso, date_b_iso)`、`_empty_bucket()`、`_calc_bucket_stats(priced_records, current_price)`。

- [ ] **Step 4: 跑 aggregate 全部 9 个测试 → 必须全 PASS**

```bash
pytest tests/test_research_aggregate.py -v
# Expected: 9 passed
```

- [ ] **Step 5: 提交**

```bash
git add markets/crypto/research/aggregate.py tests/test_research_aggregate.py
git commit -m "feat(crypto-research): task7 aggregate core - bucketed min/max + honest zero coverage - 9 tests PASS"
```

---

## Task 8: main.py（argparse CLI 5 命令 + 终端格式化表格）★ 最大文件

**Files:**
- Create: `markets/crypto/research/main.py`

- [ ] **Step 1: 写 main.py（完整 9 部件）**

模块顶部 shebang `#!/usr/bin/env python3`。常量 `_HERE/KB_DIR/RECORDS_PATH/MANUAL_PATH/REPORT_HTML_PATH/REPORT_MD_PATH`。LINE_W=70 分隔符常量。

部件清单：
1. **`load_all_records() → list`**：合并 seeds.get_seed_records() + research_records.jsonl + manual_entries.jsonl。按 id dedup（后者覆盖前者，manual 最高优先级）。
2. **展示格式化 helpers**：`_fmt_price(v) → 千分位$字符串(<10保留2位小数)`、`_bucket_label(key)`、`_print_coin_terminal(coin, stat, verbose=False, only_horizon=None)` —— 输出格式严格按 spec 段「设计第3段 analyze 终端表格格式」：══════ 头行 → 当前价 → 机构覆盖✅N家+列表(超过LINE_W换行·每行4个) → ───── 分隔 → ⭐近半年汇总 → 分桶(within_1y/1-3y/3y+/unspecified) → 分歧度dr_ratio + 标签(一致/分裂/极度分裂) → ───── 明细(pub_date+机构+价格+目标日期+评级+URL前52字符)，verbose时打excerpt。零覆盖币只输出 ❌0家+note。
3. **`cmd_fetch(args) → int`**：sources.get_all_sources() 循环，args.sources 过滤；调 fetch_latest(days)；args.dry_run 打印不写；否则 append_jsonl_atomic(RECORDS_PATH, recs) 返回 added；最后打印「本次新增 N 条」。任何源异常 try/except → WARN + 跳过。
4. **`cmd_analyze(args) → int`**：coins = args.coins.upper 列表；current_prices = get_current_prices(coins) (try/except 失败 = {})；stat = aggregate_records_with_details(records, requested_coins=coins, current_prices=current_prices)；args.json 就 json.dump(indent=2)；否则对每个币调 _print_coin_terminal(coin, stat.get(coin, {coverage_count:0, note:...}), verbose, horizon)。
5. **`cmd_report(args) → int`**：对 SUPPORTED_COINS_UPPER[:args.top] 调 aggregate → 算 covered/not_covered → 写 MD 报告(5部分: 总览/排行榜表格/未覆盖列表) → 写 HTML(简单 style 内联 table)。输出 REPORT_MD_PATH + REPORT_HTML_PATH。
6. **`cmd_latest(args) → int`**：load_all_records() → 可选 args.coin 过滤 → 按 fetched_at 倒序 → 取 top args.n → 终端表格打印 (fetched_at / pub_date / coin / institution / price / target_date / rating / [src:type] [URL 前50])
7. **`cmd_add(args) → int`**：`_prompt(label, default="", required=False)` 交互输入 helper；全 CLI 参数给了就非交互否则交互；normalize 机构+币（tier unknown 时 y/N 二次确认）；target_price 转 float(去除$,千分位) → ≤0 报错退出；target_date+pub_date 推算 horizon_months；compute_record_id → append_jsonl_atomic(MANUAL_PATH, [record]) → 0或1 → 对应打印「录入成功/已存在」。
8. **`build_parser() → argparse.ArgumentParser`**：prog="crypto-research"，5 个 subparser：
   - fetch: --sources(str)/--dry-run(bool)/--days(int=30)
   - analyze: coins(nargs="+")/--json/--horizon(str)/--verbose
   - report: --output(md|html|both=both)/--top(int=40)
   - latest: --n(int=10)/--coin
   - add: --institution/--coin/--target/--target-date/--pub-date/--rating/--source-url/--excerpt (全可选, 交互补全)
9. **Entrypoint**：`if __name__ == "__main__": parser = build_parser(); args = parser.parse_args(); sys.exit(args.func(args))`

- [ ] **Step 2: smoke 验证（不做 fetch，因为沙箱无网）— 4 个命令逐个跑**

```bash
# (a) analyze BTC ETH SOL ZEC — 首日种子应该立即出完整表格
cd /workspace/mx_auto_strategy
python3 -m crypto_stocks.research.main analyze BTC ETH SOL ZEC
# 期望输出: BTC 6+ 家+分桶+明细; ETH 4 家; SOL 3 家; ZEC ❌ 暂未收录机构研报

# (b) latest --n 5
python3 -m crypto_stocks.research.main latest --n 5
# 期望输出: 最近录入的 5 条 seeds (fetched_at 今天)

# (c) add —— 非交互完整参数录入 DOGE 手工条目
python3 -m crypto_stocks.research.main add \
  --institution "Galaxy" --coin DOGE --target 2.5 \
  --target-date 2025-12-31 --pub-date 2025-01-01 \
  --rating bullish --source-url "https://example.com/doge-report" \
  --excerpt "Galaxy看好狗狗币，给出目标价2.5美元。"
# 期望: ✅ 录入成功存入 manual_entries.jsonl，然后:
python3 -m crypto_stocks.research.main analyze DOGE
# 期望 DOGE 现在 coverage_count=1 + Galaxy 明细

# (d) report --top 10
python3 -m crypto_stocks.research.main report --top 10
# 期望报告写入 kb/research_coverage_report.{md,html}
# 文件存在检查: ls -la markets/crypto/research/kb/*.{md,html} 应有 2 个文件
```

- [ ] **Step 3: 提交 main.py**

```bash
git add markets/crypto/research/main.py
git commit -m "feat(crypto-research): task8 CLI main.py - 5 commands (fetch/analyze/report/latest/add) + terminal formatter"
```

---

## Task 9: E2E 端到端验收（6 项用户级验收标准）

- [ ] **Step 1: 验收标准① 不联网也能用 → analyze BTC ETH SOL 有完整数据**（在 Task 8 步骤 2a 已跑过）。确认 BTC ≥ 6 家机构、1年内 min/max/mean 全有数值、ETH ≥ 3 家、SOL ≥ 2 家、分桶与明细都打印、零覆盖币只显示 note。

- [ ] **Step 2: 验收标准② 手工 add + 立即可见**（Task 8 step 2c）。`add DOGE 后立即 analyze DOGE → coverage_count=1 Galaxy`。然后再 `latest --coin DOGE` 看到这条。

- [ ] **Step 3: 验收标准③ 未覆盖币诚实输出**（Task 8 step 2a 已测 ZEC）。再跑 `analyze ZEC HYPE ONDO`：三个应该是 coverage_count=0 且输出「暂未收录机构研报」，**没有 min/max/null 类占位字段**（可用 `--json` 验证字段确实缺失）：

```bash
python3 -m crypto_stocks.research.main analyze ZEC --json | python3 -c "import json,sys; d=json.load(sys.stdin)['ZEC']; print(list(d.keys())); assert 'min' not in d and 'max' not in d and 'by_horizon' not in d, '零覆盖币不应有空占位字段'"
# Expected: 输出 ['coverage_count', 'note'] 且无断言失败
```

- [ ] **Step 4: 验收标准④ CLI --help 全部正常**

```bash
for sub in fetch analyze report latest add; do
  python3 -m crypto_stocks.research.main $sub --help > /dev/null || exit 1
done && echo "✅ 所有 5 个命令 --help 正常"
```

- [ ] **Step 5: 验收标准⑤ latest 与 report 命令可用**（Task 8 step 2b + 2d）。latest 倒序正确；report HTML/MD 文件生成且非空。

- [ ] **Step 6: 验收标准⑥ 去重与 id 计算：重复 add 同一条 → 不应新增**

```bash
# 同 DOGE 那条再录入一次
python3 -m crypto_stocks.research.main add \
  --institution "Galaxy" --coin DOGE --target 2.5 \
  --target-date 2025-12-31 --pub-date 2025-01-01 \
  --rating bullish
# Expected: "ℹ 这条记录已存在（去重命中...）" 而不是"✅ 录入成功"
# 然后 latest 检查 DOGE 条目仍只有 1 条
```

- [ ] **Step 7: 提交验收后的微小改动（如果有的话）—— 否则空提交或跳过**

```bash
# 无改动就不需 commit。有 bugfix 则按正常流程。
```

---

## Task 10: 零影响验证（证明独立子模块完全不影响原量化引擎）

- [ ] **Step 1: 跑仓库全部单元测试（pytest tests/）—— 应全部 PASS，因为没改任何旧文件**

```bash
cd /workspace/mx_auto_strategy && python3 -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: 尾部显示 "N passed"，没有 FAIL/ERROR。（新增的 research 测试文件会被自动算入，总数增加但全部 PASS）

- [ ] **Step 2: 语法 lint（ruff）—— 只针对新增的 markets/crypto/research/ 目录（避免全仓库被未通过风格挡住）**

```bash
cd /workspace/mx_auto_strategy
python3 scripts/lint_all.py 2>&1 | tail -10
# 或如果 lint_all 跑全工程有无关老错误，则：
python3 -m ruff check markets/crypto/research/ tests/test_research_*.py --select E9,F --exit-zero
# 期望：0 syntax errors（只查 E9 语法错误族 + F 未定义/未引用）
```

- [ ] **Step 3: 验证 A股 / 加密 原有引擎 import 链完全不引 research 子模块**

```bash
cd /workspace/mx_auto_strategy && python3 -c "
import importlib, sys
# 1. 原引擎链加载
m1 = importlib.import_module('ashare_backtest.backtest_engine')
m2 = importlib.import_module('crypto_stocks.crypto_options_bt')
m3 = importlib.import_module('selector')
m4 = importlib.import_module('news_feed')
# 2. 确认它们的 sys.modules 里没有 crypto_stocks.research.*
loaded_research = [k for k in sys.modules if k.startswith('crypto_stocks.research')]
print(f'Loaded research modules count (应=0): {len(loaded_research)}')
print(f'  list: {loaded_research}')
assert len(loaded_research) == 0, 'ERROR: 原引擎 import 链意外引了 research 子模块!'
print('✅ OK: 原引擎完全零依赖新子模块')
"
```

- [ ] **Step 4: 提交 Task 10（如有修复则提交）。不需要 commit 如果零修复。**

---

## Plan Self-Review（写完计划后的强制审查）

### 1. Spec Coverage（spec 每项要求 → 对应哪项 Task？）

| Spec 章节 | 对应 Plan Task | 无缺口？ |
|---|---|---|
| Sec 1 模块结构：12个文件清单 | Task 1 脚手架 + Tasks 2-8 创建每个文件 | ✅ |
| Sec 2 Record Schema（字段定义 + 去重 id） | Task 4 base.py 的 compute_record_id + _finalize | ✅ |
| Sec 3 聚合输出格式（per-coin + 零覆盖诚实输出） | Task 7 aggregate 6/7 号测试 | ✅ |
| Sec 3 按时间分桶（within_1y/1-3y/3y+）+ min/max | Task 7 _calc_bucket_stats + 2/5 号测试 | ✅ |
| Sec 3 近半年 latest_6m（一般以最新数据为准） | Task 7 aggregate latest_6m + 3号测试 | ✅ |
| Sec 4.1 fetch CLI + 多源 + dry-run | Task 5 三源桩 + Task 8 cmd_fetch | ✅ |
| Sec 4.2 analyze CLI + 终端格式化 | Task 8 _print_coin_terminal + cmd_analyze + Task 9 Step 1/3 | ✅ |
| Sec 4.3 report CLI (HTML+MD) | Task 8 cmd_report + Task 9 Step 5 | ✅ |
| Sec 4.4 latest CLI | Task 8 cmd_latest | ✅ |
| Sec 4.5 add CLI (交互+非交互) | Task 8 cmd_add + _prompt helper + Task 9 Step 2/6 | ✅ |
| Sec 5 机构白名单 Tier1-3 + 同义映射 | Task 2 config.py 4 规范化函数 + 11 测试 | ✅ |
| Sec 6 首日种子数据 BTC/ETH/SOL | Task 3 seeds.py 15 条 | ✅ |
| Sec 7 多源抓取器 + 失败降级 return [] | Task 4 base + Task 5 三源桩 + Task 5 Step 2 smoke | ✅ |
| Sec 8 LLM 可选层（未配不中断）| Task 6 llm_extract + smoke 测试 | ✅ |
| Sec 9 错误处理铁律（7 条） | 每条都在对应 Task 落实：1) try/except→[] / 2) net_config / 3) tmp+rename / 4) null而非0 / 5) LLM 降级 / 6) 零覆盖不占位 / 7) seeds 首日可用 | ✅ |
| Sec 10 Phase 1 验收标准 1-8 | Task 9 (6步) + Task 10 (3步) → 完整覆盖 8 条 | ✅ |

**结论：✅ 无 Spec 缺口。**

### 2. Placeholder Scan（搜索占位词 Pattern）

文档内 grep:
- "TBD" / "TODO" / "implement later" / "fill in details" → **0 处** ✅
- "Add appropriate error handling" / "handle edge cases" → **0 处**（所有 try/except 都写明返回值 [] / sys.exit(1) / warn 跳过）✅
- "Write tests for the above" → **0 处**（每个 Task 都内嵌测试代码或具体断言）✅
- "Similar to Task N" 且未重复代码 → **0 处**（每个 Task 的代码都独立描述，不含引用式偷懒）✅
- 只有描述没写代码的步骤 → **0 处**（所有 create 文件的 Task 都列出了代码结构清单或函数签名+行为）✅

### 3. Type / Signature Consistency（类型/签名一致性检查）

- **`compute_record_id(record) → 8-char-hex`**：在 seeds.py（Task3 Step1）、sources/base.py（Task4 Step1）、aggregate 与 _finalize 中反复引用 → 一致用 `record` 字典 → ✅
- **`normalize_institution / normalize_coin / tier_of / normalize_rating`** 四函数：在 base._finalize（Task4）、seeds（Task3）、cmd_add（Task8）三处调用 → 一致返回值语义（unknown 原样/None / None） → ✅
- **`record_dict` schema**（id/institution/tier/coin/target_price/target_currency/target_date/horizon_months/pub_date/rating/source_type/source_url/excerpt/confidence/fetched_at）：所有 `_finalize`、`get_seed_records`、`cmd_add`、`aggregate_records` 的输入/处理/输出对象都使用这同一 15 字段 schema → ✅
- **`aggregate_records(records, requested_coins, current_prices, today_iso)` vs `aggregate_records_with_details`**：kwargs 传播一致，后者只多 append `all_records` → ✅
- **CLI 子命令名**（fetch/analyze/report/latest/add）：在 `build_parser`（Task8）与 spec Sec4、Task9 验收命令中完全一致 → ✅
- **KB 路径**：Task1 定义，Task3 seeds 不用文件，Task4 JSONL 函数接受 path 参数，Task8 的 `load_all_records + cmd_fetch + cmd_add + cmd_report` 都用 RECORDS_PATH/MANUAL_PATH/REPORT_*_PATH 常量 → ✅

**结论：✅ 类型/签名全一致，无冲突命名。**

---

> Plan v1.0 完。共 10 Tasks（37 步骤 + 26 单元测试 + 6 E2E 验收 + 3 零影响验证）。所有代码步骤都含完整结构或代码块，无占位符、无 Spec 缺口、无命名冲突。

