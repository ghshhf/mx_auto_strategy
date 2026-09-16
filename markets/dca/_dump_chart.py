# -*- coding: utf-8 -*-
"""把 out/long_dca_result.json 压成前端可用的紧凑数据"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
j = json.load(open(os.path.join(HERE, "out", "long_dca_result.json"), encoding="utf-8"))

# 1) 40 年分位带（每 5 交易日一点 → 40 年 × 252 / 5 ≈ 2016 点，再降到 ~200 点）
band = j["C_bootstrap"].get("band_pct")
if band:
    qs = ["5", "25", "50", "75", "95"]
    n = len(band["50"])
    step = max(1, n // 48)
    idx = list(range(0, n, step))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    out = {q: [round(band[q][i], 2) for i in idx] for q in qs}
    out["years"] = [round(i * 5 / 252, 1) for i in idx]
    print("分位带点数:", len(idx), "末点年:", out["years"][-1])
    print("JSON:", json.dumps(out, ensure_ascii=False))
else:
    out = None
    print("没有 band_pct")

# 2) 百年 60 个 40 年窗口
W = j["A_century_40y_tr"]["windows"]
w = [dict(y=r["start_year"], m=round(r["multiple"], 2),
          x=round(r["xirr"] * 100, 2), dd=round(r["max_dd"] * 100, 1))
     for r in W]
print("窗口数:", len(w))

# 3) 敏感性
S = [dict(lab=v["label"], adj=v["adj"],
          med=round(v["multiples"]["median"], 2),
          p5=round(v["multiples"]["p5"], 2),
          p95=round(v["multiples"]["p95"], 2),
          fin=round(v["finals"]["median"]),
          real=round(v["real_finals"]["median"]))
     for v in j["D_sensitivity"].values()]

# 4) 汇总
C = j["C_bootstrap"]
summ = dict(
    invested=round(C["invested_total"]),
    infl=round(C["inflation_factor"], 2),
    med_final=round(C["finals"]["median"]),
    p5_final=round(C["finals"]["p5"]), p95_final=round(C["finals"]["p95"]),
    med_mult=round(C["multiples"]["median"], 2),
    p5_mult=round(C["multiples"]["p5"], 2), p95_mult=round(C["multiples"]["p95"], 2),
    med_real=round(C["real_finals"]["median"]),
    p5_real=round(C["real_finals"]["p5"]), p95_real=round(C["real_finals"]["p95"]),
    med_dd=round(C["max_dd"]["median"] * 100, 1),
    p5_dd=round(C["max_dd"]["p5"] * 100, 1),
    med_under=round(C["under_pct"]["median"] * 100, 2),
    med_longest=round(C["longest_under_years"]["median"], 2),
    med_dd_year=round(C["worst_dd_at_year"]["median"], 1),
    drifts={l["name"]: round(l["drift"] * 100, 2) for l in C["legs"]},
    corr=C["corr"],
)
p = os.path.join(HERE, "out", "chart_data.json")
json.dump(dict(band=out, windows=w, sens=S, summary=summ), open(p, "w", encoding="utf-8"),
          ensure_ascii=False)
print("写入", p)
print(json.dumps(summ, ensure_ascii=False, indent=1))
print("\n敏感性:", json.dumps(S, ensure_ascii=False))
