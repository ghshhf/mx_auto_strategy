# mx_auto_strategy · 文档中心手册

本目录是 `ghshhf/mx_auto_strategy` 的 **GitHub Pages 静态站点**（`https://ghshhf.github.io/mx_auto_strategy/`），承载三市场量化回测的可视化与报告。

> 研究性质声明：本站所有数字均为**历史回测**结果，非未来收益承诺，不构成投资建议。

## 站点结构

- `index.html` — 三市场量化回测中枢（总览 / A股 / 美股 / 加密 / 组合 / 报告中心 六个 Tab）。
- `report.html?r=<报告名>.md` — 统一报告查看器，把 `.md` 报告渲染为带样式的网页（避免裸文本"白屏"）。
- `portfolio_blend.html` — 跨市场组合层曲线（A股 + 美股 + 加密，四种组合方案）。
- `portfolio_curves.html` / `curves.html` / `backtest_curves.html` — 各市场回测曲线与明细。
- `data/*.json` — 渲染层数据（与页面分离，引擎重算后刷新即可，无需重建页面）。

## 三市场引擎

| 市场 | 引擎目录 | 权威真值 | 说明 |
|------|----------|----------|------|
| A股 | `ashare_backtest/` | 头条 18.185x · CAGR 22.31% · MDD −33.31% | 腾讯后复权周线 + momentum26 + 核心卫星 0.5 + 死叉 |
| 美股 | `us_stocks/` | 期权增强 99.85x · 无期权 22.48x | 真实面板 + 公允 BS 期权定价；期权层非杠杆收租/保险 |
| 加密 | `crypto_stocks/` | 期权增强 448.6x · 减半相位叠加 | 含幸存者偏差；减半周期相位减仓为合法 alpha |

## 数据文件

- `data/nav.json` — A股净值（多窗口 + 配置）。
- `data/nav_us.json` — 美股净值（optimized / options_sim）。
- `data/nav_crypto.json` — 加密净值（cycle 多窗口）。
- `data/portfolio_blend.json` — 跨市场组合层真值与季再平衡日志。

## 报告索引

- `TRUTH.md` — 单一真值源（审计后验证真值汇总）。
- `CYCLE_DERISK.md` / `cycle_framework.md` — 周期去风险与框架。
- `crypto_overlay_report.md` / `cycle_opt_report.md` / `cycle_weights_report.md` / `cycle_windows_report.md` — 周期叠加层系列报告。
- `portfolio_blend_report.md` / `backtest_report.md` / `us-options-hedge-design.md` / `THEME_SELECTION.md` — 组合、回测、期权、主题报告。

点击首页「报告中心」Tab 即可阅读全部报告（自动经 `report.html` 渲染）。
