""" concentration_probe_test.py - 离线单测(不依赖网络)
=================================================================
运行: python concentration_probe_test.py
设计: 通过 get_fund_concentration(cfg, _board=<构造板块>) 注入假数据,
      验证打分/阈值/降权/全失败安全退回, 以及 auto_trader 中的总敞口收紧数学。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import concentration_probe as cp


def make_board(hhi_target, hot_share_target, ret_share_target, nf_hhi_target):
    """委托模块内部的假板块构造器(与 _self_test 同源)。"""
    return cp._make_board(hhi_target, hot_share_target, ret_share_target, nf_hhi_target)


CFG = {"concentration_probe": {}}
CFG_ON = {"concentration_probe": {"shadow_mode": False}}  # 关影子, 验证真实收紧


def test_ordering():
    """拥挤度上升 -> 分数上升、防御收紧更强。"""
    normal = cp.get_fund_concentration(CFG, _board=make_board(0.03, 0.22, 0.40, 0.03))
    mild = cp.get_fund_concentration(CFG, _board=make_board(0.08, 0.38, 0.60, 0.06))
    high = cp.get_fund_concentration(CFG, _board=make_board(0.11, 0.50, 0.80, 0.10))
    extreme = cp.get_fund_concentration(CFG, _board=make_board(0.14, 0.63, 0.88, 0.13))
    scores = [normal["score"], mild["score"], high["score"], extreme["score"]]
    assert scores == sorted(scores), f"分数应随拥挤递增: {scores}"
    tightens = [normal["defensive_tighten"], mild["defensive_tighten"],
                high["defensive_tighten"], extreme["defensive_tighten"]]
    assert tightens == sorted(tightens, reverse=True), f"收紧应随拥挤增强: {tightens}"
    assert normal["label"] == "normal" and extreme["label"] == "extreme"
    assert normal["defensive_tighten"] == 1.0, "正常分散市不干预"
    assert extreme["defensive_tighten"] <= 0.60, "极端抱团应强力收紧"
    print(f"  [OK] ordering: 分数={scores} 收紧={tightens}")


def test_hot_cluster_share_reported():
    """hot_cluster_share_pct 接近构造目标。"""
    r = cp.get_fund_concentration(CFG, _board=make_board(0.11, 0.50, 0.80, 0.10))
    assert abs(r["hot_cluster_share_pct"] - 50.0) < 5.0, r["hot_cluster_share_pct"]
    assert len(r["top_hot_sectors"]) > 0
    print(f"  [OK] hot_cluster_share_pct={r['hot_cluster_share_pct']}% top={r['top_hot_sectors'][:3]}")


def test_graceful_all_fail():
    """板块数据全失败 -> 安全退回(tighten=1.0, 不干预)。"""
    r = cp.get_fund_concentration(CFG, _board=None)
    assert r["defensive_tighten"] == 1.0
    assert r["label"] in ("unknown",)
    print(f"  [OK] all-fail fallback: tighten={r['defensive_tighten']} label={r['label']}")


def test_graceful_partial_fail():
    """涨幅集中度缺失(全市场普跌, ret_share=None) -> 仍能用其余维度打分(降权)。"""
    b = make_board(0.11, 0.50, 0.80, 0.10)
    b = [(n, -1.0, a, nf) for (n, _, a, nf) in b]  # 全员下跌 -> total_gain=0 -> ret_share=None
    r = cp.get_fund_concentration(CFG, _board=b)
    assert r["score"] > 0, "缺失涨幅维度仍应有分数(降权)"
    assert "return_dispersion" not in r["_parts"], "缺失维度不应计入 _parts"
    print(f"  [OK] partial-fail: score={r['score']} parts={list(r['_parts'].keys())}")


def test_integration_math():
    """auto_trader 中的总敞口收紧数学: 防御+进攻按比例减, 现金补回, 总和=100。"""
    def apply_conc(base_pct, off_pct, cash_pct, res):
        if res.get("apply") and res["defensive_tighten"] < 1.0:
            tighten = res["defensive_tighten"]
            gross = base_pct + off_pct
            freed = round(gross * (1.0 - tighten), 1)
            base_pct = round(base_pct * tighten, 1)
            off_pct = round(off_pct * tighten, 1)
            cash_pct = round(cash_pct + freed, 1)
        return base_pct, off_pct, cash_pct

    # 弱市模板 60/24/16, 极端拥挤 tighten=0.6 (CFG_ON 关影子, 真实收紧)
    extreme = cp.get_fund_concentration(CFG_ON, _board=make_board(0.14, 0.63, 0.88, 0.13))
    b, o, c = apply_conc(60, 24, 16, extreme)
    assert abs((b + o + c) - 100.0) < 0.5, (b, o, c)
    assert b < 60 and o < 24 and c > 16, (b, o, c)
    # 正常市 tighten=1.0 -> 不变
    normal = cp.get_fund_concentration(CFG_ON, _board=make_board(0.03, 0.22, 0.40, 0.03))
    b2, o2, c2 = apply_conc(60, 24, 16, normal)
    assert (b2, o2, c2) == (60, 24, 16)
    print(f"  [OK] integration: 极端->{b}/{o}/{c} 正常->{b2}/{o2}/{c2} (sum=100)")


def test_dual_source_combine():
    """双源合成: 实时层 + 真实持仓层按权重合成最终指数; 任一层缺失则退回单层。"""
    import fund_holdings_probe as fhp
    rt_board = make_board(0.11, 0.50, 0.80, 0.10)  # 实时层 ~高分
    rt_only = cp.get_fund_concentration(CFG, _board=rt_board)
    rt_score = rt_only["score"]

    # 真实层可用 -> 合成 = w_rt*rt + w_h*hl
    hl_res = {"available": True, "score": 80.0, "hhi": 0.15, "max_weight": 0.35,
              "top3_share": 0.70, "top_industries": [("电子", 30.0)], "fund_count": 35}
    orig = fhp.compute_holdings_concentration
    fhp.compute_holdings_concentration = lambda cfg, force_refresh=False: hl_res
    try:
        comb = cp.get_fund_concentration(CFG, _board=rt_board)
        expect = 0.55 * rt_score + 0.45 * 80.0
        assert abs(comb["score"] - expect) < 0.5, f"合成分应≈{expect}, 实 {comb['score']}"
        assert comb["holdings_available"] is True
        assert comb["holdings_score"] == 80.0
        assert comb["holdings_hhi"] == 0.15
        print(f"  [OK] 双源合成: 实时{rt_score:.0f} + 真实80 -> {comb['score']:.0f} (权重0.55/0.45)")
    finally:
        fhp.compute_holdings_concentration = orig

    # 真实层不可用 -> 退回仅实时层(分数不变)
    fhp.compute_holdings_concentration = lambda cfg, force_refresh=False: None
    try:
        fallback = cp.get_fund_concentration(CFG, _board=rt_board)
        assert abs(fallback["score"] - rt_score) < 0.5, "真实层缺应退回实时层"
        assert fallback["holdings_available"] is False
        print(f"  [OK] 真实层缺 -> 退回实时层({fallback['score']:.0f})")
    finally:
        fhp.compute_holdings_concentration = orig

    # 实时层缺失(board=None)但真实层可用 -> 仅用真实层分数
    fhp.compute_holdings_concentration = lambda cfg, force_refresh=False: hl_res
    try:
        rt_missing = cp.get_fund_concentration(CFG, _board=None)
        assert rt_missing["score"] == 80.0, "实时层缺应仅用真实层"
        assert rt_missing["holdings_available"] is True
        print(f"  [OK] 实时层缺 -> 仅真实层(80)")
    finally:
        fhp.compute_holdings_concentration = orig


def main():
    print("=== concentration_probe 离线测试 ===")
    test_ordering()
    test_hot_cluster_share_reported()
    test_graceful_all_fail()
    test_graceful_partial_fail()
    test_integration_math()
    test_dual_source_combine()
    print("=== 全部通过 ===")


if __name__ == "__main__":
    main()
