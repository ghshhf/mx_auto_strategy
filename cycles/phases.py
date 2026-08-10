# -*- coding: utf-8 -*-
"""
phases.py - 周期相位计算 + 合成 regime (v6.19)
================================================
核心正确性属性(与 macro_overlay 同等级):
  1. 前视偏差防护: cycle_phase_at(state, query) 只读取 available_date <= query 的行,
     未来行完全不可见。一旦破坏, 回测结果作废。
  2. 相位有界: 每个周期相位 ∈ [-1, 1], 合成 regime ∈ [-1, 1]。
  3. 优雅降级: 数据缺失 → 该周期相位归 0(中性), 不影响其他周期与基线。
  4. 额度守恒: tilt_multiplier 输出 ∈ [TILT_MIN, TILT_MAX], 不产生隐性杠杆。

量化周期相位: 取"截至 query 已可用的最新月度值", 对其过去窗口(默认 60 月, VIX 36 月)
做 z 分数, 乘方向(direction)后裁剪到 [-1,1]。
定性周期相位: 取"截至 query 已评估的最新分析师判定"。
"""
from __future__ import annotations
import os
import math
import csv

from . import specs

# 各列 z 分数窗口(月)
Z_WINDOW = {"vix": 36}
DEFAULT_WINDOW = 60


def _clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def load_cycles(raw_path, qual_path=None):
    """读取 cycles_raw.csv + 定性周期 CSV, 返回内部 state。"""
    quant_rows = []
    cols = []
    if raw_path and os.path.exists(raw_path):
        with open(raw_path, encoding="utf-8-sig", newline="") as f:
            r = csv.DictReader(f)
            cols = [c for c in (r.fieldnames or []) if c not in ("month", "available_date")]
            for row in r:
                rec = {"month": row.get("month", ""), "avail": row.get("available_date", "")}
                for c in cols:
                    v = row.get(c, "")
                    rec[c] = float(v) if v not in ("", None) else None
                quant_rows.append(rec)

    col_series = {c: [] for c in cols}
    for idx, rec in enumerate(quant_rows):
        for c in cols:
            if rec.get(c) is not None:
                col_series[c].append((idx, rec["avail"], rec[c]))

    qual_rows = []
    if qual_path and os.path.exists(qual_path):
        with open(qual_path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    ph = float(row.get("phase", ""))
                except (TypeError, ValueError):
                    continue
                qual_rows.append({
                    "cycle": row.get("cycle_id", ""),
                    "avail": row.get("assessment_date", ""),
                    "phase": _clip(ph),
                    "note": row.get("note", ""),
                })

    return {"quant_rows": quant_rows, "col_series": col_series,
            "cols": cols, "qual": qual_rows}


def _latest_idx_before(series, query):
    """series: [(idx, avail, val)] 按 avail 升序; 返回 avail<=query 的最大下标。"""
    lo, hi, ans = 0, len(series) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if series[mid][1] <= query:
            ans = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return ans


def _zscore_at(series, i, window):
    vals = [v for (_, _, v) in series[max(0, i - window + 1):i + 1]]
    if len(vals) < 3:
        return 0.0
    m = sum(vals) / len(vals)
    var = sum((x - m) ** 2 for x in vals) / len(vals)
    sd = math.sqrt(var)
    if sd < 1e-9:
        return 0.0
    return (series[i][2] - m) / sd


def cycle_phase_at(state, query):
    """返回 {cycle_id: phase∈[-1,1]}。query 为 'YYYY-MM-DD'。"""
    out = {}
    for c in specs.CYCLES:
        if c["kind"] == "quant":
            parts = []
            for _sid, col, _t, sign in c["fred"]:
                ser = state["col_series"].get(col)
                if not ser:
                    continue
                i = _latest_idx_before(ser, query)
                if i < 0:
                    continue
                w = Z_WINDOW.get(col, DEFAULT_WINDOW)
                # 各分量自带 sign: +1=越高越顺风(risk-on), -1=越高越逆风(risk-off)
                parts.append(sign * _zscore_at(ser, i, w))
            if not parts:
                out[c["id"]] = 0.0
                continue
            # 已是 risk-on 得分(各分量 sign 已归位), 直接平均裁剪
            out[c["id"]] = round(_clip(sum(parts) / len(parts)), 4)
        else:
            best = None
            for q in state["qual"]:
                if q["cycle"] == c["id"] and q["avail"] <= query:
                    if best is None or q["avail"] > best["avail"]:
                        best = q
            out[c["id"]] = round(best["phase"], 4) if best else 0.0
    return out


def composite_regime(state, query, weights=None):
    """12 周期加权合成 ∈ [-1,1]。weights: {id: w}; 缺省用 specs 权重。"""
    phases = cycle_phase_at(state, query)
    if weights is None:
        weights = {c["id"]: c["weight"] for c in specs.CYCLES}
    num = sum(phases[k] * weights[k] for k in phases if k in weights)
    den = sum(weights[k] for k in phases if k in weights)
    return _clip(num / den) if den > 0 else 0.0


def tilt_multiplier(regime, tilt=specs.DEFAULT_TILT):
    """regime∈[-1,1] -> 进攻仓位乘数 ∈ [TILT_MIN, TILT_MAX]。"""
    return _clip(1.0 + tilt * regime, specs.TILT_MIN, specs.TILT_MAX)


def write_monthly(state, out_path):
    """按月导出周期相位 + 合成 regime 到 CSV。"""
    months = sorted({rec["month"] for rec in state["quant_rows"]})
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    header = ["month", "available_date"] + [c["id"] for c in specs.CYCLES] + ["composite"]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for ym in months:
            # 以该月可用日作为查询点
            avail = ""
            for rec in state["quant_rows"]:
                if rec["month"] == ym:
                    avail = rec["avail"]
                    break
            q = avail or (ym + "-01")
            ph = cycle_phase_at(state, q)
            comp = composite_regime(state, q)
            row = [ym, avail] + [f"{ph[c['id']]:.4f}" for c in specs.CYCLES] + [f"{comp:.4f}"]
            w.writerow(row)
    return out_path
