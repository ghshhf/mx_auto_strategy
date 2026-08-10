# -*- coding: utf-8 -*-
"""
specs.py - 12 层金融周期叠加框架定义 (v6.20)
============================================
从"简单市场状态"(单一 composite) 扩展为 12 层周期叠加。
每一层是一个独立周期, 各有:
  - id / name        周期标识与人类可读名
  - role             该层在框架中的作用(用户给定 作用 列)
  - kind             'quant' = 由 FRED 真实序列计算; 'qual' = 分析师点截判定
  - weight           合成 regime 时的权重(同组归一)
  - lag_months       发布滞后(月), 用于 available_date 前视防护
  - fred             quant 周期的 FRED 序列 [(series_id, col, transform, sign)]
                      transform: 'last'|'mean'|'yoy'
                      sign: +1 = 该分量越高越利于风险资产(risk-on); -1 = 越高越逆风(risk-off)
  - proxy            该周期的真实代理指标(文档用)
  - note             方向/口径说明

12 层(顺序即叠加层次):
  1 联邦利率周期   加息/降息趋势
  2 半导体库存周期 芯片产业节奏
  3 科技AI创新周期 技术浪潮定位
  4 市场情绪周期   VIX/恐慌指数
  5 盈利周期       EPS增长节奏
  6 估值周期       PE/PB水位
  7 信贷周期       信用扩张/收缩
  8 美元周期       汇率方向
  9 流动性周期     M2/资金面
 10 地缘政治周期   风险事件
 11 大宗商品周期   油价/原材料
 12 房地产周期     Case-Shiller房价

方向约定(risk-on 得分 +1 = 对风险资产最大顺风, -1 = 最大逆风):
  联邦利率   -1  加息/高利率 = 收紧 = 逆风 (2s10s 倒挂=逆风, 自带 sign)
  美元       -1  美元走强 = 新兴市场/加密逆风
  信贷       -1  高收益利差走阔 = 信用压力 = 逆风
  流动性     +1  央行扩表/资金面宽裕 = 顺风
  情绪       -1  VIX 升高 = 恐慌 = 逆风
  盈利       +1  企业利润同比走高 = 顺风
  估值       -1  市值/GDP(Buffett 指标)偏高 = 估值贵 = 逆风(均值回归)
  大宗商品   -1  油价/原材料走高 = 成本推动通胀/逆风
  房地产     +1  房价同比走强 = 资产端顺风

本文件是纯声明, 不触网、不产生副作用, 可被测试直接 import。
"""
from __future__ import annotations

# 每个周期 dict 字段见模块 docstring
CYCLES = [
    # ---------- 第 1 层: 联邦利率周期 (量化) ----------
    dict(id="fed_rate", name="联邦利率周期", role="加息/降息趋势", kind="quant", weight=1.2,
         lag_months=1,
         fred=[("FEDFUNDS", "fed_funds", "last", -1), ("T10Y2Y", "t10y2y", "last", +1)],
         proxy="联邦基金目标利率 + 2s10s 收益率曲线",
         note="加息/高利率收紧金融条件(higher=risk-off, sign=-1); 曲线倒挂(T10Y2Y<0)亦为信用压力(higher=less inverted=risk-on, sign=+1)。两分量各自带 sign, 不再额外计罚。"),

    # ---------- 第 2 层: 半导体库存周期 (定性) ----------
    dict(id="semiconductor", name="半导体库存周期", role="芯片产业节奏", kind="qual", weight=0.8,
         lag_months=0,
         fred=[],
         proxy="DRAM/NAND 价格趋势 + SOX 动量 + 半导体库存销售比(无干净 FRED 序列)",
         note="库存累积期=逆风, 去库存末端=顺风。FRED 无干净序列, 由分析师按公开数据判定。direction=-1。"),

    # ---------- 第 3 层: 科技AI创新周期 (定性) ----------
    dict(id="ai_innovation", name="科技AI创新周期", role="技术浪潮定位", kind="qual", weight=0.8,
         lag_months=0,
         fred=[],
         proxy="AI 资本开支趋势 + NVDA 数据中心收入 + 推理成本曲线",
         note="创新/开支上行=顺风。无干净宏观序列, 分析师判定。direction=+1。"),

    # ---------- 第 4 层: 市场情绪周期 (量化) ----------
    dict(id="sentiment", name="市场情绪周期", role="VIX/恐慌指数", kind="quant", weight=0.9,
         lag_months=0,
         fred=[("VIXCLS", "vix", "mean", -1)],
         proxy="VIX 隐含波动率(日度→月度均值)",
         note="VIX 升高 = 恐慌/去风险 = 逆风; 均值回归强, 用 36 月 z 分数。higher=risk-off, sign=-1。"),

    # ---------- 第 5 层: 盈利周期 (量化) ----------
    dict(id="earnings", name="盈利周期", role="EPS增长节奏", kind="quant", weight=0.9,
         lag_months=2,
         fred=[("CP", "cp", "yoy", +1)],
         proxy="美国企业利润 (CP, 季度→月度 ffill) 同比",
         note="盈利同比扩张 = 基本面顺风。higher=risk-on, sign=+1。"),

    # ---------- 第 6 层: 估值周期 (定性; FRED 无干净 PE/PB/CAPE 月度序列) ----------
    dict(id="valuation", name="估值周期", role="PE/PB水位", kind="qual", weight=0.9,
         lag_months=0,
         fred=[],
         proxy="市值/GDP (Buffett 指标) + CAPE/Shiller PE + 标普 500 市净率水位(由分析师判定)",
         note="FRED 无干净的月度 PE/PB 或 CAPE 序列(CAPE 在 FRED 404; 市值/GDP DDDM01USA156NWDB 仅年度且止于2020)。与半导体/AI/地缘同为定性层: 由分析师按当期估值水位判定。higher(贵)=risk-off, 分析师判定时取负相位。direction=-1。"),

    # ---------- 第 7 层: 信贷周期 (量化) ----------
    dict(id="credit", name="信贷周期", role="信用扩张/收缩", kind="quant", weight=1.0,
         lag_months=1,
         fred=[("BAMLH0A0HYM2", "hy_oas", "last", -1)],
         proxy="ICE BofA 美国高收益债期权调整利差 (OAS, bp)",
         note="利差走阔 = 信用收缩/违约担忧 = 风险逆风。higher=risk-off, sign=-1。"),

    # ---------- 第 8 层: 美元周期 (量化) ----------
    dict(id="dollar", name="美元周期", role="汇率方向", kind="quant", weight=1.0,
         lag_months=1,
         fred=[("DTWEXBGS", "dtwexbgs", "last", -1)],
         proxy="广义贸易加权美元指数 (DTWEXBGS)",
         note="美元走强压制新兴市场资产与加密(美元计价负债端)。higher=risk-off, sign=-1。"),

    # ---------- 第 9 层: 流动性周期 (量化) ----------
    dict(id="liquidity", name="流动性周期", role="M2/资金面", kind="quant", weight=1.2,
         lag_months=2,
         fred=[("WALCL", "walcl", "last", +1)],
         proxy="美联储总资产 (WALCL, 十亿美元) 作为全球流动性代理",
         note="扩表 = 基础流动性注入 = 风险资产顺风。higher=risk-on, sign=+1。仅美储_proxy, 非全球全口径(M2 见 note)。"),

    # ---------- 第 10 层: 地缘政治周期 (定性, 新增) ----------
    dict(id="geopolitics", name="地缘政治周期", role="风险事件", kind="qual", weight=0.6,
         lag_months=0,
         fred=[],
         proxy="地缘热点指数(中东/俄乌/台海/贸易摩擦)+ 主权风险溢价",
         note="冲突升级/制裁扩散=逆风。分析师按当期事件判定。direction=-1。无干净宏观序列。"),

    # ---------- 第 11 层: 大宗商品周期 (量化, 由通胀重构) ----------
    dict(id="commodity", name="大宗商品周期", role="油价/原材料", kind="quant", weight=0.8,
         lag_months=1,
         fred=[("DCOILWTICO", "wti", "last", -1)],
         proxy="WTI 原油现货价 (DCOILWTICO, 美元/桶) 作为大宗商品/原材料代理",
         note="油价/原材料走高 = 成本推动通胀/逆风。higher=risk-off, sign=-1。FRED 无综合商品指数干净序列, 以原油作主代理。"),

    # ---------- 第 12 层: 房地产周期 (量化) ----------
    dict(id="housing", name="房地产周期", role="Case-Shiller房价", kind="quant", weight=0.6,
         lag_months=2,
         fred=[("CSUSHPISA", "cs", "yoy", +1)],
         proxy="标普/凯斯-席勒 20 城房价指数同比 (CSUSHPISA)",
         note="房价同比走强 = 资产端顺风, 但亦触发政策收紧; 本框架取资产端顺风。higher=risk-on, sign=+1。"),
]

# 便捷索引
BY_ID = {c["id"]: c for c in CYCLES}
QUANT_CYCLES = [c for c in CYCLES if c["kind"] == "quant"]
QUAL_CYCLES = [c for c in CYCLES if c["kind"] == "qual"]

# 合成权重归一(便于 composite_regime 直接加权)
TOTAL_WEIGHT = sum(c["weight"] for c in CYCLES)

# 默认 tilt: regime 得分映射到进攻仓位的乘数幅度(沿用 macro_overlay 语义)
# v6.21 优化: 由 0.5 下调至 0.2。
DEFAULT_TILT = 0.2

# 逐引擎精选周期 + 权重 (v6.22, 依据 optimize_cycle_weights.py 的逐周期有效性实验):
#   对每个引擎, 把 12 周期**单独**接入(tilt=0.3)测 ON/OFF 倍数比, 取三窗口几何均值 >1.0 的周期入选;
#   入选周期按有效性强弱赋相对权重(权重越高 -> 在合成 regime 中越主导, 即用户所言"权重越高越该起作用")。
#   结论:
#     - A股: credit(信贷)+ commodity(大宗商品) 入选。fed_rate 对 A股无效(ratio<1, 中国股受美联储利率
#           传导弱), 但信贷利差/油价这类确实影响 -> 印证"宏观类周期有用, 只是走的不是美联储利率通道"。
#     - 美股: 12 周期几何均值**全部 <1.0**(其死亡交叉/波动率目标已吃掉周期能加的东西) -> 精选集为空。
#            cycle_overlay=True 时本 dict 为空 -> composite_regime 返回 0 -> 乘数 1.0(中性), 安全无副作用;
#            **实证建议 美股保持 cycle_overlay=False**。
#     - 加密: liquidity(流动性, 10y 单周期 ratio 1.99, 2022 寒冬前转逆风减仓)+ housing + commodity + fed_rate。
#   权重已归一化到 sum=1, 仅表示引擎内相对主导度。
ENGINE_CYCLE_WEIGHTS = {
    "ashare": {"credit": 0.529, "commodity": 0.471},
    "us": {},                       # 空 -> 叠加层中性(乘数1.0); 建议关闭
    "crypto": {"fed_rate": 0.224, "liquidity": 0.307, "commodity": 0.227, "housing": 0.242},
}

# 逐引擎推荐 tilt(在各自精选子集上扫描 ON/OFF 几何倍数比 + 样本外 walk-forward 验证得出):
#   - A股: 精选子集下 tilt 单调递增收益, 但 MDD 随 tilt 加深; 取 0.3 为"起作用但不至于把回撤拖太狠"的平衡点。
#            OOS(wf_cycle_oos.py): 几何倍数比 +9.65%(t=12.0, |t|>=2 显著), MDD 中性(t=1.63 不显著)。
#   - 美股: 无有用周期 -> 0.0(配合空精选集=纯中性); OOS 6 窗口全 1.0, 建议保持 cycle_overlay=False。
#   - 加密: OOS 验证推翻"崩盘保险"叙事 -> 叠加层是**收益放大器**(显著 +22% 倍数, t=5.4)但
#            **显著恶化 MDD(-6pp, t=-5.98)**; in-sample 的 MDD 改善是 2022 单事件幻觉(同估值层性质)。
#            tilt 扫描(0.2/0.3/0.4/0.5)为单调权衡: 0.3 = 平衡档(仍显著 +16% 倍数 / -4pp MDD),
#            0.5 收益最高但回撤代价大。默认取 0.3。
ENGINE_TILT = {"ashare": 0.3, "us": 0.0, "crypto": 0.3}
# 乘数边界(避免隐性杠杆/空仓过度)
TILT_MIN, TILT_MAX = 0.5, 1.5
