# -*- coding: utf-8 -*-
"""
specs.py - 12 周期框架定义 (v6.19)
====================================
定义多周期研究框架的 12 个周期: 每个周期有
  - id / name        周期标识与人类可读名
  - kind             'quant' = 由 FRED 真实序列计算; 'qual' = 分析师点截判定
  - direction        +1 = 指标越高越利于风险资产(risk-on); -1 = 越高越逆风(risk-off)
  - weight           合成 regime 时的权重(同组归一)
  - lag_months       发布滞后(月), 用于 available_date 前视防护
  - fred             quant 周期的 FRED 序列 [(series_id, col, transform)]  transform: 'last'|'mean'|'yoy'
  - proxy            该周期的真实代理指标(文档用)
  - note             方向/口径说明

方向约定(risk-on 得分 +1 = 对风险资产最大顺风, -1 = 最大逆风):
  联邦利率   -1  加息/高利率 = 收紧 = 逆风
  美元       -1  美元走强 = 新兴市场/加密逆风
  信贷       -1  高收益利差走阔 = 信用压力 = 逆风
  流动性     +1  央行扩表 = 流动性充裕 = 顺风
  情绪       -1  VIX 升高 = 恐慌 = 逆风
  盈利       +1  企业利润同比走高 = 顺风
  通胀/商品  -1  CPI 同比过高 = 政策收紧逆风(本框架定义为逆风代理)
  房地产     +1  房价同比走强 = 资产端顺风
  半导体库存 -1  库存累积 = 逆风(去库存末端 = 顺风), 分析师判定
  科技AI创新 +1  创新/资本开支上行 = 顺风, 分析师判定
  监管政策   -1  监管收紧 = 逆风, 分析师判定(重点看加密/AI)
  加密自身   +1  减半后上行期/链上健康 = 顺风, 半确定性(减半日 + BTC 趋势)

本文件是纯声明, 不触网、不产生副作用, 可被测试直接 import。
"""
from __future__ import annotations

# 每个周期 dict 字段见模块 docstring
CYCLES = [
    # ---------- 量化周期 (FRED 真实序列) ----------
    dict(id="fed_rate", name="联邦利率周期", kind="quant", direction=-1, weight=1.2,
         lag_months=1,
         fred=[("FEDFUNDS", "fed_funds", "last", -1), ("T10Y2Y", "t10y2y", "last", +1)],
         proxy="联邦基金目标利率 + 2s10s 收益率曲线",
         note="加息/高利率收紧金融条件(higher=risk-off, sign=-1); 曲线倒挂(T10Y2Y<0)亦为信用压力(higher=less inverted=risk-on, sign=+1)。两分量各自带 sign, 不再额外计罚。"),
    dict(id="dollar", name="美元周期", kind="quant", direction=-1, weight=1.0,
         lag_months=1,
         fred=[("DTWEXBGS", "dtwexbgs", "last", -1)],
         proxy="广义贸易加权美元指数 (DTWEXBGS)",
         note="美元走强压制新兴市场资产与加密(美元计价负债端)。higher=risk-off, sign=-1。"),
    dict(id="credit", name="信贷周期", kind="quant", direction=-1, weight=1.0,
         lag_months=1,
         fred=[("BAMLH0A0HYM2", "hy_oas", "last", -1)],
         proxy="ICE BofA 美国高收益债期权调整利差 (OAS, bp)",
         note="利差走阔 = 信用收缩/违约担忧 = 风险逆风。higher=risk-off, sign=-1。"),
    dict(id="liquidity", name="流动性周期", kind="quant", direction=+1, weight=1.2,
         lag_months=2,
         fred=[("WALCL", "walcl", "last", +1)],
         proxy="美联储总资产 (WALCL, 十亿美元) 作为全球流动性代理",
         note="扩表 = 基础流动性注入 = 风险资产顺风。higher=risk-on, sign=+1。仅美储_proxy, 非全球全口径。"),
    dict(id="sentiment", name="市场情绪周期", kind="quant", direction=-1, weight=0.9,
         lag_months=0,
         fred=[("VIXCLS", "vix", "mean", -1)],
         proxy="VIX 隐含波动率(日度→月度均值)",
         note="VIX 升高 = 恐慌/去风险 = 逆风; 均值回归强, 用 36 月 z 分数。higher=risk-off, sign=-1。"),
    dict(id="earnings", name="企业盈利周期", kind="quant", direction=+1, weight=0.9,
         lag_months=2,
         fred=[("CP", "cp", "yoy", +1)],
         proxy="美国企业利润 (CP, 季度→月度 ffill) 同比",
         note="盈利同比扩张 = 基本面顺风。higher=risk-on, sign=+1。"),
    dict(id="inflation", name="大宗商品/通胀周期", kind="quant", direction=-1, weight=0.8,
         lag_months=1,
         fred=[("CPIAUCSL", "cpi", "yoy", -1)],
         proxy="美国 CPI 同比 (CPIAUCSL)",
         note="本框架将高通胀定义为政策收紧逆风代理(非商品多头代理)。higher=risk-off, sign=-1。"),
    dict(id="housing", name="房地产周期", kind="quant", direction=+1, weight=0.6,
         lag_months=2,
         fred=[("CSUSHPISA", "cs", "yoy", +1)],
         proxy="标普/凯斯-席勒 20 城房价指数同比 (CSUSHPISA)",
         note="房价同比走强 = 资产端顺风, 但亦触发政策收紧; 本框架取资产端顺风。higher=risk-on, sign=+1。"),

    # ---------- 定性周期 (分析师点截判定, 不带前视) ----------
    dict(id="semiconductor", name="半导体库存周期", kind="qual", direction=-1, weight=0.8,
         lag_months=0,
         fred=[],
         proxy="DRAM/NAND 价格趋势 + SOX 动量 + 半导体库存销售比(无干净 FRED 序列)",
         note="库存累积期=逆风, 去库存末端=顺风。FRED 无干净序列, 由分析师按公开数据判定。direction=-1。"),
    dict(id="ai_innovation", name="科技AI创新周期", kind="qual", direction=+1, weight=0.8,
         lag_months=0,
         fred=[],
         proxy="AI 资本开支趋势 + NVDA 数据中心收入 + 推理成本曲线",
         note="创新/开支上行=顺风。无干净宏观序列, 分析师判定。direction=+1。"),
    dict(id="regulation", name="监管政策周期", kind="qual", direction=-1, weight=0.7,
         lag_months=0,
         fred=[],
         proxy="加密/AI 监管立场(牌照、SEC/CFTC、稳定币法案)",
         note="监管收紧=逆风。分析师按当期政策事件判定。direction=-1。"),
    dict(id="crypto_native", name="加密自身周期", kind="qual", direction=+1, weight=0.9,
         lag_months=0,
         fred=[],
         proxy="BTC 减半日程(协议级确定性) + BTC 趋势 + 链上 MVRV/NUPL",
         note="减半后上行期=顺风; 叠加 BTC 趋势修正。半确定性(减半日无前视)。direction=+1。"),
]

# 便捷索引
BY_ID = {c["id"]: c for c in CYCLES}
QUANT_CYCLES = [c for c in CYCLES if c["kind"] == "quant"]
QUAL_CYCLES = [c for c in CYCLES if c["kind"] == "qual"]

# 合成权重归一(便于 composite_regime 直接加权)
TOTAL_WEIGHT = sum(c["weight"] for c in CYCLES)

# 默认 tilt: regime 得分映射到进攻仓位的乘数幅度(沿用 macro_overlay 语义)
DEFAULT_TILT = 0.5
# 乘数边界(避免隐性杠杆/空仓过度)
TILT_MIN, TILT_MAX = 0.5, 1.5

# 减半日(协议级确定性, 零后视) — 用于 crypto_native 半确定性相位
HALVING_DATES = ["2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20", "2028-04-??"]
# 减半后典型顺风窗口(月): 减半后 0~18 个月偏顺风
HALVING_TAILWIND_MONTHS = 18
