# -*- coding: utf-8 -*-
"""cycles — 多周期研究框架 (v6.19)
跨市场(美股/加密/A股)宏观周期叠加层。详见 docs/cycle_framework.md。
"""
from .specs import (
    CYCLES, BY_ID, QUANT_CYCLES, QUAL_CYCLES, TOTAL_WEIGHT,
    DEFAULT_TILT, TILT_MIN, TILT_MAX, HALVING_DATES,
)
from .phases import (
    load_cycles, cycle_phase_at, composite_regime, tilt_multiplier, write_monthly,
)
from .fetch import fetch_all, build_raw_csv

__all__ = [
    "CYCLES", "BY_ID", "QUANT_CYCLES", "QUAL_CYCLES", "TOTAL_WEIGHT",
    "DEFAULT_TILT", "TILT_MIN", "TILT_MAX", "HALVING_DATES",
    "load_cycles", "cycle_phase_at", "composite_regime", "tilt_multiplier",
    "write_monthly", "fetch_all", "build_raw_csv",
]
