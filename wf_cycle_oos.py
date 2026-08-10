# -*- coding: utf-8 -*-
"""
wf_cycle_oos.py - 周期叠加层 样本外 walk-forward 验证 (v6.21)
============================================================
项目方法论要求: 叠加层改进须经 滚动窗口 + 双维度配对 t 检验(|t|>=2 才算真改进)。
本脚本对三引擎做 expanding-origin walk-forward:
  每个 origin t: train=[数据起点, t], test=[t, t+1y]
  1) 在 TRAIN 上逐周期测 ON/OFF 倍数比 -> 选 ratio>1.0 的周期(按 ratio 归一化权重)
     (权重仅用 train 数据选出, 测试期完全不可见 -> 真样本外)
  2) 用该权重在 TEST 上跑 ON vs OFF -> 记录 (mult_on, mult_off, mdd_on, mdd_off)
聚合多 origin -> 配对 t 检验:
  - 倍数维度: d = mult_on/mult_off - 1
  - MDD 维度 : d = mdd_off - mdd_on  (正=回撤改善)
输出 cycle_wf_oos.json + 打印结论。
"""
import os, sys, json, math, time, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "us_stocks"))
sys.path.insert(0, os.path.join(ROOT, "crypto_stocks"))
from cycles import specs as SP

DET_TILT = 0.3          # 选周期用的中性探测 tilt(只探方向, 不探力度)
TEST_YEARS = 1          # 每个 test 窗口 1 年
TRAIN_MIN_YEARS = 3     # 训练期最短 3 年

END = {"A股": "2026-08-06", "美股": "2026-07-20", "加密": "2026-07-24"}
START = {"A股": "2010-01-04", "美股": "2016-02-01", "加密": "2017-08-14"}


def add_years(d, n):
    dt = datetime.date.fromisoformat(d)
    y = dt.year + n
    m, day = dt.month, dt.day
    if m == 2 and day == 29:
        day = 28
    return f"{y:04d}-{m:02d}-{day:02d}"


def run_ashare(start, overlay, tilt=0.0, weights=None):
    from ashare_backtest.backtest_engine import run
    s, _, _, _ = run(offense_mode="momentum", momentum_lookback=26, use_tech=False,
                     core_satellite=True, core_frac=0.5, death_cross=True,
                     use_core_sub=True, costs=True, start_date=start,
                     cycle_overlay=overlay, cycle_tilt=tilt, cycle_weights=weights)
    return s["final_multiple"], s["mdd"]


def run_us(start, overlay, tilt=0.0, weights=None):
    import us_backtest_ai as usmod
    from us_backtest_ai import load_panel, load_us_cfg, run_optimized
    dates, series = load_panel(os.path.join(ROOT, "us_stocks", "data", "weekly_adjclose_full_ext.csv"))
    a = next(i for i, d in enumerate(dates) if d >= start)
    sw = {k: v[a:] for k, v in series.items()}; dw = dates[a:]
    usmod.series_proxy.clear(); usmod.series_proxy.update(sw)
    us_cfg = load_us_cfg()
    opt = us_cfg.get("options_sim") if us_cfg.get("options_sim", {}).get("enabled", False) else None
    _, st = run_optimized(sw, dw, use_ai=False, cfg=None, refresh_weeks=4, theme_div=True,
                          max_per_theme=2, us_cfg=us_cfg, options_sim=opt,
                          cycle_overlay=overlay, cycle_tilt=tilt, cycle_weights=weights)
    return st["multiple"], st["mdd"] * 100


def run_crypto(start, overlay, tilt=0.5, weights=None):
    import crypto_options_bt as cm
    px = cm._load_default()
    r = cm.run_bt(px, cfg_dict=None, label="V6_wf", start=start,
                  cycle_overlay=overlay, cycle_tilt=tilt, cycle_weights=weights)
    return r["multiple"], r["mdd"] * 100


RUNNERS = {"A股": run_ashare, "美股": run_us, "加密": run_crypto}


def select_weights(eng, train_start, train_end):
    """在 train 窗口逐周期测 ON/OFF 倍数比, 选 ratio>1.0 的周期(按 ratio 归一化)。"""
    try:
        base, _ = RUNNERS[eng](train_start, False)
    except Exception:
        return {}
    if not base or base <= 0:
        return {}
    ratios = {}
    for cid in [c["id"] for c in SP.CYCLES]:
        try:
            m_on, _ = RUNNERS[eng](train_start, True, tilt=DET_TILT, weights={cid: 1.0})
        except Exception:
            continue
        if m_on and m_on > 0:
            r = m_on / base
            if r > 1.0:
                ratios[cid] = r
    if not ratios:
        return {}
    s = sum(ratios.values())
    return {k: round(v / s, 4) for k, v in ratios.items()}


def paired_t(vals):
    n = len(vals)
    if n < 2:
        return None
    mean = sum(vals) / n
    var = sum((x - mean) ** 2 for x in vals) / (n - 1)
    if var == 0:
        return 0.0
    return mean / (math.sqrt(var) / math.sqrt(n))


def main():
    results = {}
    print("=" * 100)
    print("周期叠加层 样本外 walk-forward 验证 (expanding-origin, train 选权重 / test 评估)")
    print("=" * 100)
    for eng in ("A股", "美股", "加密"):
        key = {"A股": "ashare", "美股": "us", "加密": "crypto"}[eng]
        test_tilt = SP.ENGINE_TILT[key]
        y0 = int(START[eng][:4]); oy = int(END[eng][:4])
        pairs = []
        for yr in range(y0 + TRAIN_MIN_YEARS, oy):
            origin = f"{yr+1:04d}-01-01"          # test 起点
            ts = add_years(origin, -TEST_YEARS)   # = train 终点 = test 起点
            test_end = add_years(origin, TEST_YEARS)
            if test_end > END[eng]:
                continue
            w = select_weights(eng, ts, origin)
            try:
                m_off, md_off = RUNNERS[eng](ts, False)
                if not w:
                    # 训练期无有效周期 -> 记录中性(模型正确 abstain)
                    pairs.append(dict(test_start=ts, test_end=test_end, weights={},
                                      mult_off=m_off, mult_on=m_off, ratio=1.0,
                                      mdd_off=md_off, mdd_on=md_off, mdd_imp=0.0,
                                      abstain=True))
                    continue
                m_on, md_on = RUNNERS[eng](ts, True, tilt=test_tilt, weights=w)
            except Exception as e:
                print(f"  [warn] {eng} {ts}->{test_end} 失败: {e}")
                continue
            if m_off and m_on:
                ratio = m_on / m_off
                mdd_imp = md_off - md_on  # 正=改善
                pairs.append(dict(test_start=ts, test_end=test_end, weights=w,
                                  mult_off=round(m_off, 3), mult_on=round(m_on, 3),
                                  ratio=round(ratio, 4), mdd_off=round(md_off, 2),
                                  mdd_on=round(md_on, 2), mdd_imp=round(mdd_imp, 2),
                                  abstain=False))
        ratios = [p["ratio"] for p in pairs]
        mdd_imps = [p["mdd_imp"] for p in pairs]
        t_r = paired_t([r - 1 for r in ratios])
        t_m = paired_t(mdd_imps)
        nonzero = [p for p in pairs if not p.get("abstain")]
        results[eng] = dict(
            n_windows=len(pairs), n_active=len(nonzero),
            mean_ratio=round(sum(ratios) / len(ratios), 4) if ratios else None,
            geo_ratio=round(math.exp(sum(math.log(r) for r in ratios) / len(ratios)), 4) if ratios else None,
            t_ratio=t_r, t_mdd=t_m,
            pass_ratio=bool(t_r is not None and abs(t_r) >= 2),
            pass_mdd=bool(t_m is not None and abs(t_m) >= 2),
            pairs=pairs,
        )
        print(f"\n###### {eng} (key={key}, test_tilt={test_tilt}) ######")
        print(f"  窗口数={len(pairs)} 有效(选出周期)={len(nonzero)} "
              f"几何倍数比={results[eng]['geo_ratio']} 均值比={results[eng]['mean_ratio']}")
        print(f"  t(倍数)={t_r}  t(MDD)={t_m}  |t|>=2 ? 倍数:{results[eng]['pass_ratio']} MDD:{results[eng]['pass_mdd']}")
        for p in pairs:
            tag = "ABSTAIN" if p.get("abstain") else "ACTIVE "
            print(f"    {tag} {p['test_start']}->{p['test_end']} w={p['weights']} "
                  f"ON={p['mult_on']} OFF={p['mult_off']} ratio={p['ratio']} MDDimp={p['mdd_imp']}")
    with open(os.path.join(ROOT, "cycle_wf_oos.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n已写入 cycle_wf_oos.json")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\n总耗时 {time.time()-t0:.1f}s")
