# -*- coding: utf-8 -*-
"""wf_crypto_tilt_sweep.py - 用已 OOS 选出的加密权重, 扫 test tilt, 量化 收益/MDD 权衡。"""
import os, sys, json, math
ROOT = os.path.dirname(os.path.abspath(__file__))   # crypto_stocks/
REPO = os.path.dirname(ROOT)                         # 仓库根
sys.path.insert(0, REPO)
sys.path.insert(0, ROOT)

def run_crypto(start, tilt, weights):
    import crypto_options_bt as cm
    px = cm._load_default()
    r = cm.run_bt(px, cfg_dict=None, label="V6_wf", start=start,
                  cycle_overlay=True, cycle_tilt=tilt, cycle_weights=weights)
    return r["multiple"], r["mdd"] * 100

data = json.load(open(os.path.join(ROOT, "data", "cycle_wf_oos.json"), encoding="utf-8"))
pairs = data["加密"]["pairs"]
print(f"加密 OOS 窗口数={len(pairs)} (均为 ACTIVE, 权重来自各自 train 选出)")
for tilt in (0.2, 0.3, 0.4, 0.5):
    ratios, mdds = [], []
    for p in pairs:
        off = p["mult_off"]; m_off = p["mdd_off"]
        m_on, md_on = run_crypto(p["test_start"], tilt, p["weights"])
        ratios.append(m_on / off); mdds.append(m_off - md_on)
    geo = math.exp(sum(math.log(r) for r in ratios) / len(ratios))
    mean_mdd = sum(mdds) / len(mdds)
    print(f"  tilt={tilt}: 几何倍数比={geo:.4f} (+{(geo-1)*100:.1f}%)  均值MDDimp={mean_mdd:+.2f}pp")
