# -*- coding: utf-8 -*-
"""
overlay.py - 12 层周期 composite_regime 的统一叠加层接口 (v6.20)
==============================================================

把 cycles 模块的 composite_regime 作为"统一风险 regime 信号"接入三大回测引擎
(A股 / 美股 / 加密)。设计原则与 macro_overlay 完全一致:

  1. 前视防护: cycle_scale_at 内部走 composite_regime -> cycle_phase_at,
     只读取 available_date <= query 的行, 未来行完全不可见。
  2. 相位有界 / 额度守恒: 所有 helper 保证不产生隐性杠杆
     (进攻仓最多只能从防御仓/稳定币匀额度, 绝不借入)。
  3. 优雅降级: 数据缺失 / 模块加载失败 -> 乘数归 1.0, 不改变基线回测。
  4. 默认关闭: 引擎仅在 cycle_overlay=True 时调用本模块; 关闭时路径与原基线逐字节一致。

引擎接入示意:
  A股      : apply_to_alloc(o_pct, d_pct, c_pct, scale)   # 进攻/防御/现金三栏守恒
  美股     : cap_offense(base_off, a_cash, a_off, struct_def)  # 现金自动吸收差额
  加密     : apply_to_crypto_target(off_w, stable_room, scale)  # 进攻↔稳定币守恒
"""
from __future__ import annotations

import os

from . import specs
from .phases import load_cycles, composite_regime, tilt_multiplier

DEFAULT_TILT = specs.DEFAULT_TILT  # = 0.5; 乘数 ∈ [TILT_MIN, TILT_MAX] = [0.5, 1.5]

_HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(_HERE, "data", "cycles_raw.csv")
QUAL = os.path.join(_HERE, "data", "cycles_qualitative_seed.csv")

_STATE = None  # 进程内缓存, 避免每周重读 CSV


def _as_date(s):
    """归一化日期为 'YYYY-MM-DD'。接受字符串或 pandas Timestamp。"""
    if hasattr(s, "strftime"):
        return s.strftime("%Y-%m-%d")
    s = str(s)
    return s[:10]


def get_cycle_state():
    """加载并缓存 cycles 内部 state; 文件缺失返回 None(优雅降级)。"""
    global _STATE
    if _STATE is not None:
        return _STATE
    try:
        if os.path.exists(RAW):
            _STATE = load_cycles(RAW, QUAL)
        else:
            _STATE = None
    except Exception:
        _STATE = None
    return _STATE


def cycle_scale_at(date_str, tilt=DEFAULT_TILT):
    """返回进攻仓乘数 ∈ [TILT_MIN, TILT_MAX]; 无数据 -> 1.0(中性, 不改变基线)。

    date_str: 'YYYY-MM-DD' 字符串或 pandas Timestamp。
    内部 composite_regime 自带前视防护(仅看 available_date <= date_str 的行)。
    """
    state = get_cycle_state()
    if not state or not state.get("quant_rows"):
        return 1.0
    regime = composite_regime(state, _as_date(date_str))
    return tilt_multiplier(regime, tilt)


# ---------------- 额度守恒 helper (被三引擎复用, 便于单元测试) ----------------

def apply_to_alloc(o_pct, d_pct, c_pct, scale, o_cap=80.0):
    """A股式守恒: 用 scale 缩放进攻仓, 加仓从防御仓匀、减仓释放现金。

    返回 (new_o, new_d, new_c)。保证 new_c >= 0 且 new_o <= o_cap(无隐性杠杆)。
    scale=1.0 -> 原样返回(基线不变)。
    """
    new_o = max(0.0, min(float(o_cap), float(o_pct) * float(scale)))
    if new_o > float(o_pct):
        take = min(new_o - float(o_pct), float(d_pct))  # 只能从防御仓匀, 匀不出就不加
        new_o = float(o_pct) + take
        d_pct = float(d_pct) - take
    else:
        c_pct = float(c_pct) + (float(o_pct) - new_o)
    return new_o, float(d_pct), float(c_pct)


def apply_to_crypto_target(off_w, stable_room, scale):
    """加密式守恒: 缩放进攻权重 off_w, 差额从稳定币(STABLE)匀取。

    off_w: {coin: weight} 进攻权重(dict)。stable_room: 当前稳定币权重(float)。
    scale: 周期乘数。返回 (new_off_w, new_stable)。
    保证 new_stable >= 0(无隐性杠杆), 且 sum(new_off_w)+new_stable == sum(off_w)+stable_room。
    """
    off_sum = sum(off_w.values())
    if off_sum <= 0:
        return dict(off_w), float(stable_room)
    cap = (off_sum + float(stable_room)) / off_sum  # 顺风加仓最多把稳定币吃光, 不借入
    s = min(float(scale), cap)
    new_off = {c: v * s for c, v in off_w.items()}
    new_stable = max(0.0, float(stable_room) - (off_sum * s - off_sum))
    return new_off, new_stable


def cap_offense(base_off, a_cash, a_off, struct_def=0.0):
    """美股式守恒: 返回经周期缩放且不产生隐性杠杆的进攻百分比。

    base_off = a['off'] * vol_scale * lev(引擎原有基线进攻百分比)。
    cap 由 (现金 + 进攻) 额度决定: 周期顺风最多把现金吃光, 绝不借入。
    struct_def>0 时防御袖(stable/分红袖)也计入可腾挪额度。
    当 base_off 已 <= cap(默认 lev=1 时成立) -> 与基线一致; 仅顺风超额时被裁。
    """
    cap = (float(a_cash) + float(a_off)) / max(1e-9, 1.0 - float(struct_def))
    return max(0.0, min(float(base_off), cap))
