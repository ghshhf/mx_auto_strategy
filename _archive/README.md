# _archive — 已停用的历史模块

本目录存放**不再维护、不参与 CI、不参与 Pages 发布**的历史代码与产物。
保留仅为可追溯；新代码一律不要引用本目录下的任何模块。

## ashare_live/ — A股 live 交易系统（2026-08-07 起永久搁置）

曾是一套完整的 A股自动化交易/选题/记账系统（v6.x ~ v7.2），2026-09-01 从仓库根目录
整体归档至此。归档理由：策略已停止实盘使用，长期无人维护，却占据根目录 33 个脚本、
约 6000 行，是"根目录混杂"的主要来源。

**A股研究主线不受影响**：`ashare_backtest/`（回测引擎、v6.18 真值 18.185x）与
`cycles/`（减半周期框架，被加密模块共用）仍在原位，是本仓库 A股部分的唯一权威。

### 目录内容

| 路径 | 说明 |
|---|---|
| `ashare_live/*.py` | 33 个已停用的 A股脚本（选股、网格、自动交易、记账、主题、预测等） |
| `ashare_live/tests/` | 与上述脚本配套的 10 个单元测试，随脚本一并归档 |
| `ashare_live/records/` | 历史模拟账户、交易流水 jsonl、A股周期研究笔记 |

### 两个例外（保留在仓库根目录）

以下两个模块虽属 A股系统出身，但被现役模块依赖，已**保留在根目录**，不属于归档范围：

- `ai_score.py` — 被 `us_stocks/us_backtest_ai.py`（`--with-llm`）依赖
- `llm_client.py` — 被 `crypto_stocks/research/parsers/llm_extract.py` 依赖

### 如何运行归档测试（一般不必要）

```bash
python -m pytest _archive/ashare_live/tests/ -v
```

`_archive/ashare_live/conftest.py` 会把归档目录加入 `sys.path`，使
`import auto_trader` 等仍可解析。CI 不执行此目录。

## crypto_btc_eth/ — BTC/ETH 配对再平衡一次性实验（2026-09-01 归档）

单次提交 `2792124` 引入的自包含实验交付物，README 自述"独立自包含脚本，不依赖也不修改
`crypto_stocks/` 现有引擎"。2026-09-01 归档，理由：

1. **全仓零外部引用** —— 无任何脚本/文档/CI 引用它，与 `crypto_stocks/`（现役加密主干，
   含 `manage_token.py` 运维工具链、470 周×57 币面板）在职能上重复；
2. 自带一套完整 backtest / rebalance / report / NAV 生成链，与现役加密引擎形成**双套 NAV
   口径**，易造成"哪个是真值"的混淆。

### 保留理由（暂不硬删）

其 `README.md` 与 `MULTI_COIN_PLAN.md` 记录了两条有独立价值的结论：

- 再平衡撮合口径（按实际成交额收 0.1% 手续费）的实现细节；
- **压力测试发现**：组合中任一币真的归零（而非暴跌后恢复）时，滚动再平衡会亏到只剩
  基准的 **2.7%**，而买入持有只掉到 68% —— 因为再平衡每周都在卖掉活着的币给尸体输血。
  该风险当前无代码保护，且实测无法用价格阈值规避。

### 彻底删除

若确认不再需要，整目录删除即可（git 历史中仍可追溯）：

```bash
git rm -r --cached _archive && rm -rf _archive
```
