# mx_auto_strategy — 三市场量化回测研究引擎

> 给「下一个 AI（或接手的人）」的操作手册。本项目是 **A股 / 美股 / 加密** 三市场的**周线动量 + 周期减仓**回测研究引擎，**非实盘交易系统**。A股 live 自动交易（剧本 / 模拟盘 / 龙虾大赛）已于 2026-08-07 **永久搁置**，项目重心是三市场量化回测研究。

---

## 0. 30 秒上手（最重要）

1. **Python 必须用量化 venv**，默认 `python` 没有 pandas，会立刻报 `ModuleNotFoundError`**。⚠️ 解释器文件名必须带 `.exe` 扩展名（Git Bash 下省略会报 "No such file or directory"，脚本会静默失败）**：
   ```
   C:/Users/admin/.workbuddy/binaries/python/envs/default/Scripts/python.exe
   ```
2. **下载行情走本地代理** `http://127.0.0.1:1080`（socks5；Binance/OKX/CMC/腾讯可达；Git 操作 GitHub 也走此代理 `git -c http.proxy=socks5://127.0.0.1:1080`）。端口随本机代理软件变化，以实际监听为准。
3. **Git Bash 下 Python 不认 `/e/` 挂载点**，一律用 Windows 绝对路径（如 `C:/Users/...` 或 `E:/xmanbian/...`）。
4. 改完任何东西，先读 `PITFALLS.md`（本仓根目录）——里面是历年踩过的坑，能省你几小时。

---

## 1. 仓内结构

| 路径 | 作用 |
|---|---|
| `markets/crypto/` | 加密回测主引擎（周线动量 + 减半周期减仓） |
| `markets/ashare/` | A股回测（腾讯后复权金标准面板） |
| `markets/us/` | 美股回测（真实面板 + AI 选股层） |
| `cycles/` | 减半周期相位表与叠加层（`phases.py` / `overlay.py` / `specs.py`） |
| `docs/` | 报告产物（如 `curves.html`） |
| `PITFALLS.md` | **必读**：历史踩坑清单 |
| `README.md` | 本文件 |

---

## 1.1 网页端与自动发布（GitHub Pages）

本项目已启用 **GitHub Pages**：从 `main` 分支的 `/docs` 目录静态发布，站点地址：

> **https://ghshhf.github.io/mx_auto_strategy/**

门户页 `docs/index.html` 为单页仪表盘：总览真值对照 + 三市场（A股/美股/加密）净值曲线下钻（窗口/配置切换、倍数对数曲线 + 回撤面积、指标卡、逐年表）+ 跨市场组合层 + 完整报告中心。数据层 `docs/data/*.json` 与渲染分离，引擎重算后刷新即可，无需重建页面。

**「完整系统跑在网页端」是怎么实现的（重要边界）：**
- GitHub Pages 只托管**静态文件**，浏览器里跑不了 Python 回测引擎；
- 但 `.github/workflows/publish.yml` 会在 **CI 中用仓库内已提交的数据快照运行引擎**，重算 `docs/data/*.json` 与各报告、自动写回 `main`，Pages 随即重发——**内容由自动化流水线动态生成，从用户视角是「活的、会自动更新的站点」**；
- CI 运行器无本地代理、连不上腾讯/Binance/OKX/CMC，**无法在云端拉实时行情**。因此：
  - 加密面板与组合层可 CI 离线重算；
  - A股/美股面板未提交（需本地代理生成），其导出在面板缺失时自动跳过、保留已提交结果；
  - **「实时数据刷新」需在本机走代理后运行 `scripts/refresh_and_publish.sh`**，推送后 CI 自动接手重算与发布。

**本地刷新并发布（实时数据）：**
```bash
bash scripts/refresh_and_publish.sh
```
脚本会重算各市场 NAV、组合层、各报告，并将 `docs/` 提交推送到 `main`（Git 需已配置代理/SSH）。推送后 Pages 约 1–2 分钟重发。

**仅改引擎/报告逻辑（无需新数据）：** 直接 `git push` 到 `main`，`publish.yml` 监听到推送即自动重算并发布。

---

## 2. 当前权威真值（改完必须回归到这里，勿飘）

| 市场 | 真值 | 口径 |
|---|---|---|
| **A股** v6.18 | **18.185x** / CAGR 22.31% / MDD −33.31% | 2014-10-17~2026-08-06，749 周，含成本；基线 = momentum26 + 核心卫星 0.5 + 死叉，`use_tech=False + trend_filter=False` |
| **美股** | 无杠杆 **22.48x / −48.4%**；20% 现金袖 **14.46x / −40.8%** | 155 列真实面板（2021-08 起） |
| **加密 10y** | 优化参数 **59,361,202x（≈59.36Mx）** / MDD −23.8% / Sharpe 2.91（12y 全面板为 427Mx） | 621 周（2016-08 起），**43 币**；同期 BTC 买入持有 108.8x。完整真值表见 `TRUTH_AUTHORITY.md` |

> ⚠️ **旧口径 `24,493x / −43.5%` 已废弃**（2026-08-11 MDD 修复后 `DEFAULT_CFG` 演进）。不要把它和现在的 28,092x 直接并列对比。
> 📌 加密倍率完整真值表（含窗口/引擎版本口径、为何历史数字对不上）见根目录 `TRUTH_AUTHORITY.md`。
> ⚠️ A股真值 18.185x 含**幸存者偏差**（指数成分股幸存筛选）。

---

## 3. 各市场怎么跑（精确命令）

### 加密（43 币）
```bash
cd markets/crypto
C:/Users/admin/.workbuddy/binaries/python/envs/default/Scripts/python.exe run_windows_bt.py
# 产出: crypto_windows_report.md + crypto_windows_results.json（10/5/3 年 × base/cycle 两档）
```
引擎：`crypto_options_bt.py`；面板：`data/weekly_adjclose_crypto50.csv`（全样本）+ `data/weekly_adjclose_crypto50_10y.csv`（621 周）。引擎按周过滤"当周有非 NaN 非零价"的币，早期空缺列（如 TRB 2020-08 前）自动不可选，不会报错。

### A股
```bash
cd markets/ashare
C:/Users/admin/.workbuddy/binaries/python/envs/default/Scripts/python.exe run_windows.py
# 产出: nav_windows.html + nav_windows.csv（3/5/10y trailing 窗口对比）
```
⚠️ **陷阱**：`run_windows.py` 硬编码 `use_tech=True`，而 v6.18 权威真值 18.185x 是 `use_tech=False + trend_filter=False`。直接跑 `run_windows.py` 得到的不是 18.185x。要复现真值，改 `run_windows.py` 里的 `cfg`（`use_tech=False, trend_filter=False`），或直接调 `backtest_engine.run(...)`。面板来源 `ashare_panel_close_em.csv`（活跃腾讯后复权数据）。

### 美股
```bash
cd markets/us
C:/Users/admin/.workbuddy/binaries/python/envs/default/Scripts/python.exe us_backtest_ai.py --no-ai
# --no-ai: 关闭 AI 选股层，只跑 baseline + optimized（复现 22.48x 真值无需 LLM）
# 默认还会跑 optimized；如需真接 LLM 加权加 --with-llm（需配置，否则 pass-through=1.0）
```
面板：`weekly_adjclose_full_ext.csv`（155 列）。基线真值 22.48x 来自 `run_baseline`（无杠杆）。

### 周期叠加（加密）
```bash
python run_cycle_windows.py        # 根目录
```
把 `cycles/` 的减半相位减仓叠加到加密引擎上。相位表见 `cycles/phases.py` 的 `HALVING_PHASE_ADJUST`（默认 `crash=bear_bottom=0.3`、预热起点 `ph=31` 月）。

---

## 4. 怎么加一个新代币到加密篮子（以 TRB 为例，2026-08-11 实操可复现）

1. **`crypto_adoption_v2.py`**
   - `THEME_COINS[<赛道>]` 加入符号（如 `'基础设施': ['LINK','ENS','API3','GRT','TRB']`）
   - `COIN_META` 加元信息：`'TRB': {'name':'Tellor','role':'offense','theme':'基础设施','launch':2019}`
2. **`sync_crypto_panel.py`** 的 `_CMC_ID_MAP` 加 CMC id
   - ⚠️ **先查再写**：用 `pro-api.coinmarketcap.com/v1/cryptocurrency/map?symbol=XXX` 核实 id，**别猜**（Tellor 实测是 4944，不是直觉的 10108）
3. **回填历史周线**：写脚本用 `crypto_hist_data.fetch_binance_full('<SYM>USDT', '<起始日>')` 主源（OKX/CMC 兜底），对齐日期写回 `data/weekly_adjclose_crypto50.csv` 和 `..._10y.csv` 的新列。上市前留空。参考本仓 `_add_trb_backfill.py`。
4. **重跑** `run_windows_bt.py` 验证新币进入且历史非空。

> ⚠️ **统计坑（踩过）**：算新币与 BTC 的**相关性 / beta 必须按【日期对齐】**，不能按行索引对齐（两币上市日不同会错位），更不能把"同周价格比值"当收益率（会得到假的 corr=1.0000）。见 `crypto_options_bt.py` 周边分析代码。

---

## 5. 数据怎么重抓

| 市场 | 脚本 | 源 |
|---|---|---|
| A股 | `markets/ashare/tencent_hfq_rebuild.py` | 腾讯 `web.ifzq.gtimg.cn` 后复权周线（**活跃**；eastmoney 源已死，勿用 `eastmoney_hfq_rebuild.py`） |
| 加密 | `markets/crypto/sync_crypto_panel.py` | Binance → OKX → CMC 三级降级同步 |

> ⚠️ 文件名带 `_em` ≠ eastmoney 源。`ashare_weekly_em/`、`ashare_panel_close_em.csv`、`ashare_panel_volume_em.csv` 是**活跃腾讯数据**，被引擎读写——**删了回测直接崩**。真废弃是带 `OLD_eastmoney_bak` / `.bak9` 后缀的。

---

## 6. 关键坑速查（详见 `PITFALLS.md`）

- **前视偏差**：手写 `PHASE_HISTORY` 是 2026 回看标注，回测 2019 年即"知道"哪个行业加速 → 虚增 +18%~+37%。只用 `[0,i]` 现算的 `tech_mode="data"`。
- **减半周期减仓是加密主干**：alpha 100% 来自 `halving_*_risk_scale` 按相位减仓，与做空零关系。翻开关前先确认子参数不是空操作默认值。
- **加密反直觉铁律**：① 见顶期 euphoria 必须满仓（"高位"不是减仓信号，"减半后 18 个月"才是）；② 筑底期 bear_bottom 不能恢复仓位；③ 预热起点 ph=31 月 ≫ 36 月。
- **估值层 MDD 改善是单点事件**（压平 2015 泡沫），非持续风控能力；默认关闭。
- **框架纪律**：加密"买旧不买新"——新代币有解锁放量→归零序列风险；老牌=已证幸存者（非高回报保证）。集中度量赛道（如预言机 TVS） favor 老大 LINK，嫌弃利基 also-ran 是证据支持、非偏见。

---

## 7. 项目状态 / 不做什么

- ✅ 三市场回测研究（活跃）
- ❌ A股 live 自动交易（剧本 / 模拟盘 / 龙虾大赛）—— 2026-08-07 起永久搁置
- 📌 `_scratch_*.py` 草稿脚本（约 25 个，零外部 import）保留不动，作方法论备查；根目录 `E:\xmanbian` 的 `mx_backtest_*.html` / `_mx_src` / `_qa_verify` 等 mx 残留不在本仓，勿误删
- 📌 所有成果已 `git commit` 入库（含 TRB 入池、回测、本报告、`PITFALLS.md`）
