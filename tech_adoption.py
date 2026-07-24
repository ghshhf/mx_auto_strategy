"""
tech_adoption.py - 科技渗透率 / 采用率相位 (木头姐 Cathie Wood / ARK 框架)

设计动机:
  木头姐(ARK)分析科技不是"猜涨跌", 而是用:
    1) 莱特定律(Wright's Law): 累计产量每翻倍, 成本按固定比例下降 -> 成本降到临界点, 采用非线性爆发
    2) 渗透率 S 曲线: 当渗透率跨过临界(成本平价), 进入加速段(甜区 ~10%-30%); 过 ~50%-60% 进入成熟/饱和, 增速放缓
  本模块把这套"产品普及率"思想落成一个**轻量、离线、可解释**的进攻侧权重倾斜层。

职责:
  - 给进攻题材(行业)标注"采用相位"(early / accelerating / saturating / mature / policy / unknown)
  - 把相位映射成动量权重乘子(加速期加成, 饱和期降权), 喂给 weekly_theme 做主线排序倾斜
  - 仅影响进攻侧; 防御蓝筹底仓完全不动 (符合 16 倍框架铁律)

数据源: 内置精选渗透率表 (curated, 离线, 无外部依赖)。
  渗透率数字为**近似估值**(截至 as_of), 用于相位判断而非精确预测; 定期人工复核更新即可。
  任何未在表中收录的行业 -> 中性(乘子 1.0), 不干预原逻辑。

安全: 全部 try/except 降级; 模块导入失败 / 配置缺失 -> 返回中性, 绝不中断主流程。

自测: `python3 tech_adoption.py` 或 `MOCK=1 python3 tech_adoption.py`
"""
import os
import sys

# ---------------------------------------------------------------------------
# 内置精选渗透率表 (curated penetration table)
#   penetration: 当前渗透率近似 % (None 表示非消费扩散技术, 用 policy 处理)
#   phase: early / accelerating / saturating / mature / policy
#   as_of: 数据截至
#   note: 相位判断依据
# ---------------------------------------------------------------------------
THEMES = {
    # —— 加速渗透 (S 曲线陡峭段, 木头姐甜区) ——
    "半导体":     {"penetration": 22, "phase": "accelerating", "as_of": "2025Q4",
                   "note": "国产化率~20-25%, 处加速替代段"},
    "半导体设备": {"penetration": 18, "phase": "accelerating", "as_of": "2025Q4",
                   "note": "设备国产化率~15-20%, 加速替代"},
    "AI":         {"penetration": 35, "phase": "accelerating", "as_of": "2025Q4",
                   "note": "企业AI/生成式渗透快速提升, 仍处甜区"},
    "计算机":     {"penetration": 30, "phase": "accelerating", "as_of": "2025Q4",
                   "note": "AI Agent 驱动软件渗透再加速"},
    "电网":       {"penetration": 28, "phase": "accelerating", "as_of": "2025Q4",
                   "note": "特高压/配网/储能投资渗透提升"},
    "港股科技":   {"penetration": 32, "phase": "accelerating", "as_of": "2025Q4",
                   "note": "镜像 AI/半导体渗透"},
    "科技宽基":   {"penetration": 32, "phase": "accelerating", "as_of": "2025Q4",
                   "note": "科技整体渗透"},
    # —— 早期 (渗透极低, 爆发前夜, 木头姐最佳布局区) ——
    "机器人":     {"penetration": 5,  "phase": "early", "as_of": "2025Q4",
                   "note": "人形机器人渗透极低, 爆发前夜(甜区)"},
    "医药":       {"penetration": 15, "phase": "early", "as_of": "2025Q4",
                   "note": "创新药/AI制药渗透低, 长期空间大"},
    # —— 饱和 (过甜区, 增速放缓) ——
    "新能源":     {"penetration": 50, "phase": "saturating", "as_of": "2025Q4",
                   "note": "NEV渗透率~50%, 过加速段进入成熟"},
    "汽车":       {"penetration": 48, "phase": "saturating", "as_of": "2025Q4",
                   "note": "新能源占比高, 行业增速放缓"},
    # —— 成熟 (国内装机/渗透已高, 周期属性) ——
    "锂矿":       {"penetration": 48, "phase": "mature", "as_of": "2025Q4",
                   "note": "随新能源成熟"},
    "光伏":       {"penetration": 55, "phase": "mature", "as_of": "2025Q4",
                   "note": "国内装机饱和, 产能过剩"},
    "消费电子":   {"penetration": 75, "phase": "mature", "as_of": "2025Q4",
                   "note": "手机饱和, AI手机尚早期"},
    "通信":       {"penetration": 62, "phase": "mature", "as_of": "2025Q4",
                   "note": "5G渗透~60%+, 成熟"},
    "面板":       {"penetration": 70, "phase": "mature", "as_of": "2025Q4",
                   "note": "成熟周期"},
    # —— 政策/战略驱动 (非消费扩散技术, 中性不倾斜) ——
    "军工":       {"penetration": None, "phase": "policy", "as_of": "2025Q4",
                   "note": "政策预算驱动, 非渗透逻辑"},
    "军工电子":   {"penetration": None, "phase": "policy", "as_of": "2025Q4",
                   "note": "政策驱动, 中性"},
    "稀土":       {"penetration": None, "phase": "policy", "as_of": "2025Q4",
                   "note": "战略资源, 中性"},
}

# ---------------------------------------------------------------------------
# 时变渗透率相位表 (PHASE_HISTORY) — 木头姐框架的"每个时代当红成长赛道"本质
# ---------------------------------------------------------------------------
# 用户洞察(2026-07-25): 渗透率框架本职 = 识别"当期热门成长赛道"
#   (白酒时代 / 新能源时代 / AI 时代), 不该拿一张 2025 静态快照把早年加速期错配成饱和.
#   例如宁德 2019-2021 是 10 倍主升浪(加速期), 但 2025 视角看"新能源饱和×0.65"会压低其权重.
#   故每个行业给出 [起始年, 结束年, 相位] 区间列表; 回测/历史场景按年份查当年真实相位.
# 非回测(live)场景不传 year -> 用上方 THEMES 当前评估(2025 视角), 行为不变.
# 年份落在所有区间外 -> 回落到 THEMES 当前相位(兜底).
PHASE_HISTORY = {
    # 白酒/消费: 2016-2020 高端白酒量价齐升加速; 2021+ 见顶成熟
    "白酒":   [(2016, 2020, "accelerating"), (2021, 2026, "mature")],
    "消费":   [(2016, 2020, "accelerating"), (2021, 2026, "mature")],
    # 新能源/电池: 2016-2018 早期; 2019-2021 主升浪加速; 2022+ 饱和
    "新能源": [(2016, 2018, "early"), (2019, 2021, "accelerating"), (2022, 2026, "saturating")],
    "汽车":   [(2019, 2021, "accelerating"), (2022, 2026, "saturating")],
    "锂矿":   [(2019, 2021, "accelerating"), (2022, 2026, "mature")],
    # 半导体设备: 2019-2021 加速; 2022 周期下行mature; 2023-2026 自主可控加速
    "半导体设备": [(2019, 2021, "accelerating"), (2022, 2022, "mature"), (2023, 2026, "accelerating")],
    "半导体":     [(2019, 2021, "accelerating"), (2023, 2026, "accelerating")],
    # AI/光模块: 2018-2022 早期; 2023-2026 算力爆发加速
    "AI":       [(2018, 2022, "early"), (2023, 2026, "accelerating")],
    "计算机":   [(2018, 2022, "early"), (2023, 2026, "accelerating")],
    "通信":     [(2023, 2026, "accelerating")],  # 光模块/算力链
    # 医药/CXO: 2017-2021 创新药+CXO高景气加速; 2022+ 成熟(寒冬/制裁)
    "医药":     [(2017, 2021, "accelerating"), (2022, 2026, "mature")],
    # 光伏: 2020-2022 加速; 2023+ 成熟(产能过剩)
    "光伏":     [(2020, 2022, "accelerating"), (2023, 2026, "mature")],
    # 机器人: 2023+ 早期/加速(人形机器人爆发前夜)
    "机器人":   [(2023, 2026, "early")],
    # 电网: 2021+ 加速(特高压/配网/储能)
    "电网":     [(2021, 2026, "accelerating")],
    "港股科技": [(2023, 2026, "accelerating")],
    "科技宽基": [(2023, 2026, "accelerating")],
}

# phase -> 配置键 (乘子从 strategy_config.tech_adoption 读取, 缺省用硬兜底)
_PHASE_KEY = {
    "accelerating": "boost_accelerating",
    "early": "early_boost",
    "saturating": "cut_saturating",
    "mature": "mature_mult",
}
_PHASE_DEFAULT = {
    "accelerating": 1.35,
    "early": 1.15,
    "saturating": 0.65,
    "mature": 0.8,
}
_NEUTRAL = 1.0  # unknown / policy


def _cfg_block(cfg):
    return (cfg or {}).get("tech_adoption", {}) if isinstance(cfg, dict) else {}


def is_active(cfg):
    """模块是否生效(启用且非影子观察)。"""
    try:
        b = _cfg_block(cfg)
        return bool(b.get("enabled", True)) and not bool(b.get("shadow_mode", False))
    except Exception:
        return False


def phase_multiplier(phase, cfg):
    """phase -> 权重乘子。unknown/policy -> 中性 1.0。"""
    b = _cfg_block(cfg)
    if phase in _PHASE_KEY:
        return float(b.get(_PHASE_KEY[phase], _PHASE_DEFAULT[phase]))
    return float(b.get("unknown_neutral", _NEUTRAL))


def _phase_for(industry, year):
    """时变相位查询: 给定年份返回该行业当年相位; 无匹配区间/无历史 -> 回落 THEMES 当前相位。"""
    hist = PHASE_HISTORY.get(industry)
    if hist:
        for (s, e, ph) in hist:
            if s <= year <= e:
                return ph
    return THEMES.get(industry, {}).get("phase", "unknown")


def get_adoption(industry, cfg=None, year=None):
    """查某行业的采用相位与权重乘子。安全: 任何异常 -> 中性。

    year: 指定年份则查时变相位表(PHASE_HISTORY), 用于回测/历史场景;
          不传(None)则使用 THEMES 当前评估(2025 视角), 实时/近况场景行为不变。
    返回 dict: {industry, penetration, phase, multiplier, note, as_of}
    """
    try:
        ph = _phase_for(industry, year) if year is not None else THEMES.get(industry, {}).get("phase", "unknown")
        info = THEMES.get(industry)
        pen = info.get("penetration") if info else None
        note = (info.get("note", "") if info else "")
        if year is not None:
            note = (note + f" [历史{year}年相位:{ph}]").strip()
        if not info:
            return {
                "industry": industry, "penetration": None, "phase": ph,
                "multiplier": phase_multiplier(ph, cfg),
                "note": (note or "未收录, 中性不干预"), "as_of": None,
            }
        return {
            "industry": industry,
            "penetration": pen,
            "phase": ph,
            "multiplier": phase_multiplier(ph, cfg),
            "note": note,
            "as_of": info.get("as_of"),
        }
    except Exception:
        return {"industry": industry, "penetration": None, "phase": "unknown",
                "multiplier": _NEUTRAL, "note": "异常降级中性", "as_of": None}


def apply_tilt(industry_momentum, cfg):
    """给 scan_industry_momentum 的结果就地叠加采用相位。

    industry_momentum: {ind: {"avg_chg":..., "count":..., "tickers":[...]}}
    生效时新增字段: adoption_phase / adoption_mult / adj_chg (=avg_chg*mult)
    未生效(shadow/disabled/异常)时: adj_chg=avg_chg, 相位=unknown, 乘子=1.0
    """
    try:
        b = _cfg_block(cfg)
        active = bool(b.get("enabled", True)) and not bool(b.get("shadow_mode", False))
        for ind, d in industry_momentum.items():
            if active:
                ad = get_adoption(ind, cfg)
                d["adoption_phase"] = ad["phase"]
                d["adoption_mult"] = ad["multiplier"]
                d["adj_chg"] = round((d.get("avg_chg", 0.0) or 0.0) * ad["multiplier"], 2)
            else:
                d["adoption_phase"] = "unknown"
                d["adoption_mult"] = _NEUTRAL
                d["adj_chg"] = d.get("avg_chg", 0.0)
        return industry_momentum
    except Exception:
        for d in industry_momentum.values():
            d.setdefault("adoption_phase", "unknown")
            d.setdefault("adoption_mult", _NEUTRAL)
            d.setdefault("adj_chg", d.get("avg_chg", 0.0))
        return industry_momentum


def _selftest():
    print("=" * 60)
    print("tech_adoption.py 离线自检 (木头姐渗透率相位)")
    print("=" * 60)
    cfg = {"tech_adoption": {
        "enabled": True, "boost_accelerating": 1.35, "early_boost": 1.15,
        "mature_mult": 0.8, "cut_saturating": 0.65, "unknown_neutral": 1.0,
    }}
    cases = ["半导体", "AI", "机器人", "新能源", "光伏", "军工", "核电", "医药"]
    print(f"{'行业':<10}{'渗透%':<8}{'相位':<14}{'乘子':<8}说明")
    for c in cases:
        ad = get_adoption(c, cfg)
        pen = "-" if ad["penetration"] is None else str(ad["penetration"])
        print(f"{c:<10}{pen:<8}{ad['phase']:<14}{ad['multiplier']:<8}{ad['note']}")
    # 倾斜演示
    print("\n倾斜演示 (avg_chg=5% 行业):")
    sim = {"半导体": {"avg_chg": 5.0}, "新能源": {"avg_chg": 5.0},
           "光伏": {"avg_chg": 5.0}, "军工": {"avg_chg": 5.0}, "核电": {"avg_chg": 5.0}}
    apply_tilt(sim, cfg)
    for ind, d in sim.items():
        print(f"  {ind:<8} avg={d['avg_chg']:>4}  phase={d['adoption_phase']:<12} "
              f"mult={d['adoption_mult']}  adj_chg={d['adj_chg']}")
    # 校验: 加速期 > 中性 > 饱和
    semi = get_adoption("半导体", cfg)["multiplier"]
    sat = get_adoption("新能源", cfg)["multiplier"]
    neu = get_adoption("核电", cfg)["multiplier"]
    assert semi > neu > sat, "相位排序错误"
    # 影子模式不生效
    cfg_shadow = {"tech_adoption": dict(cfg["tech_adoption"], shadow_mode=True)}
    sim2 = {"半导体": {"avg_chg": 5.0}}
    apply_tilt(sim2, cfg_shadow)
    assert sim2["半导体"]["adj_chg"] == 5.0, "影子模式应不改变 adj_chg"
    # 时变相位: 同行业不同年份相位不同(新能源 2019加速 vs 2025饱和; 宁德早年权重应被抬高)
    n_ev = get_adoption("新能源", cfg, year=2019)["multiplier"]
    n_25 = get_adoption("新能源", cfg, year=2025)["multiplier"]
    ai_ev = get_adoption("AI", cfg, year=2019)["multiplier"]
    ai_25 = get_adoption("AI", cfg, year=2025)["multiplier"]
    assert n_ev > n_25, "新能源应早年(加速)权重高于近年(饱和)"
    assert ai_25 > ai_ev, "AI应近年(加速)权重高于早年(早期)"
    print(f"\n时变相位校验: 新能源 2019×{n_ev} vs 2025×{n_25}; AI 2019×{ai_ev} vs 2025×{ai_25}")
    print("✅ 自检通过: 加速期加成 > 中性 > 饱和; 影子模式不干预; 时变相位年代正确。")


if __name__ == "__main__":
    _selftest()
