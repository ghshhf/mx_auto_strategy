# 代币池低市值精检清单（2026-08-13）

> 数据来源：CoinGecko / CoinPaprika / WebSearch 实时市值（部分限流后补）；持有周数 = 最终回测 fixed 模式逐周统计。
> 总周数 469。57 币中 **23 个 held>0（真被选中），34 个 held=0（纯占位）**。

## 一、核心结论
1. **34/57 币从未被回测选中**（held=0）。它们是「指数敏感/占位币」：参与 alt-RS 赛道相位判定，但自身对收益零贡献。删这类币 = 零回测成本，只动选股相位。
2. **低市值 + 纯占位**的那批，是「项目还活不活」的研究重点——值不值得占个坑。
3. **低市值但真被选中**（held>0）的币，删了会动回测 needle，研究价值更高。

## 二、低市值研究候选（按市值升序，标注 held 周）

### A 档：低市值 + 纯占位（held=0，删了零回测成本）
| 代币 | 市值(亿$) | 赛道 | 备注/红flags |
|---|---|---|---|
| PHB | ~0.0025 (25万$) | AI+加密 | **僵尸级**：30天 -94%、排名 #4000+，基本已死 → 强烈建议直接删 |
| BEAM | 0.016 | GameFi | Illuvium 游戏币，游戏基本失败 |
| RIO | 0.034 | RWA | Realio 微市值 RWA，极边缘 |
| SECRET | 0.106 | 隐私 | 隐私币，监管叙事已死 |
| METIS | 0.189 | L2扩容 | L2 赛道极度拥挤 |
| ILV | 0.241 | GameFi | Illuvium 游戏失败 |
| API3 | 0.273 | 基础设施 | 预言机，中规中矩 |
| MANTA | 0.273 | L2扩容 | 曾有过争议 |
| POLYX | 0.394 | RWA | Polymesh 证券型链，极niche |
| GMX | 0.685 | 链上永续 | 被 Hyperliquid 碾压 |
| GALA | 0.838 | GameFi | 游戏，长期弱势 |
| IMX | 0.990 | GameFi | 游戏 L2 |
| DYDX | ~1.0 (1亿$) | 链上永续 | 收入 QoQ -70%、代币迁移混乱(ethDYDX 死)、解禁抛压 |
| 1INCH | 1.17 | DeFi | DEX 聚合，叙事平淡 |
| SNX | 1.17 | DeFi | 合成资产，边缘化 |
| GRT | 1.49 | 基础设施 | The Graph 索引，币价长期弱势 |
| AKT | 1.55 | AI+加密 | Akash 去中心化算力，小众 |
| STRK | 1.58 | L2扩容 | Starknet ZK L2，TVL 低 |
| COMP | 1.63 | DeFi | Compound，借贷老牌但弱势 |
| ENS | 1.74 | 基础设施 | 域名，稳健但小 |
| LDO | 2.42 | DeFi | Lido 质押，受监管压 |
| SEI | 2.70 | L1公链 | 新 L1，竞争激烈 |
| TIA | 2.94 | 模块化 | Celestia，模块化叙事退潮 |
| APT | 4.79 | L1公链 | Aptos，MOVE 系弱势 |
| JUP | 6.2 | DEX | Solana DEX 聚合，中市值 |
| MKR | 12.0 (12亿$) | DeFi | MakerDAO/Sky，蓝筹但 held=0（选股逻辑从未捞它） |
| DOT | 13.3 | L1公链 | Polkadot，生态沉寂 |
| ONDO | 16.3 | RWA | RWA 龙头之一（用户 RWA 袖），但 held=0 |
| TAO | 19.2 | AI+加密 | Bittensor，AI 算力叙事 |
| NEAR | 21.5 | L1公链 | 老牌 L1 |
| UNI | 22.0 | DeFi | Uniswap，蓝筹 DEX 但 held=0 |
| PAS | N/A | 模块化 | CoinGecko 无数据 |
| PEAQ | N/A | DePIN | CoinGecko 无数据 |
| TON | N/A | L1公链 | CoinGecko 无数据 |

### B 档：低市值 + 真被选中（held>0，删了会动回测）
| 代币 | 市值(亿$) | held周 | 赛道 | 备注 |
|---|---|---|---|---|
| HNT | 0.329 | 12 | DePIN | Helium，已迁 Solana，DePIN 代表 |
| CFG | 0.800 | 12 | RWA | Centrifuge，**近期极活跃**（Ethena/JANUS 合作、$200M RWA）→ 建议保留 |
| AR | 1.17 | 9 | 存储 | Arweave 永久存储 |
| DASH | 3.9 | 9 | 隐私 | 隐私币，叙事已死但被选中 |
| ARB | 5.2 | 9 | L2扩容 | Arbitrum，L2 龙头 |
| CRV | 4.2 | 11 | DeFi | Curve，稳定币 DEX |
| FIL | 5.7 | 11 | 存储 | Filecoin |
| POL | 8.0 | 24 | L2扩容 | Polygon（原 MATIC） |
| OP | 2.0 | 14 | L2扩容 | Optimism |
| ZEC | 83.9 | 11 | 隐私 | Zcash |
| AVAX | 27.4 | 13 | L1公链 | Avalanche |
| SUI | 27.9 | 12 | L1公链 | Sui |
| FET | 3.0 | 1 | AI+加密 | Fetch.ai/ASI |
| RENDER | 6.5 | 1 | AI+加密 | 去中心化渲染 |

## 三、建议优先研究的「红flags」候选
1. **PHB** — 僵尸级（$25万、30天-94%），删了零成本且项目已死，最该删。
2. **ILV / BEAM / RIO** — 游戏 + 微市值，项目基本失败/边缘。
3. **SECRET** — 隐私币监管叙事已死。
4. **DASH / ZEC** — 隐私币整体叙事退潮（DASH 还被持有 9 周，若研究确认该删会动回测）。
5. **GMX / DYDX** — 链上永续，被 Hyperliquid 碾压、收入坍塌。

## 四、下一步
挑 1 个（或一批）手动确认后，由我执行「删币 + 改代码 + 同步 3 个 CSV + 重跑回测」，对照 held/倍数变化。
