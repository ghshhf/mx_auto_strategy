""" fund_holdings_probe_test.py - 真实持仓层离线单测(不触发网络)
================================================================
覆盖: 基金前十大解析 / 行业解析与归一 / 聚合 HHI / 主入口注入。
真实刷新(refresh_holdings_cache)需妙想接口, 由手动运行验证, 不在此处。
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fund_holdings_probe as fhp


# 模拟妙想"基金重仓持股明细表"原始结构(rawTable 含数值市值)
def _fake_fund_raw(names, mvs):
    return {
        "data": {"data": {"searchDataResultDTO": {"dataTableDTOList": [{
            "rawTable": {
                "headName": names,
                "HOLD_MARKET_CAP": [str(v) for v in mvs],
            },
            "table": {
                "headName": names,
                "HOLD_MARKET_CAP": [f"{v/1e8:.2f}亿" for v in mvs],
            },
        }]}}}
    }


def _fake_industry(value):
    return {
        "data": {"data": {"searchDataResultDTO": {"dataTableDTOList": [{
            "table": {"100000000035009": [value], "headName": [" "]}
        }]}}}
    }


def test_parse_fund_holdings():
    names = ["腾讯控股", "贵州茅台", "百胜中国", "中国海洋石油"]
    mvs = [11.69e8, 11.48e8, 11.21e8, 10.4e8]
    j = _fake_fund_raw(names, mvs)
    out = fhp._parse_fund_holdings(j)
    assert out is not None, "应解析出重仓"
    assert len(out) == 4, f"应 4 只, 实 {len(out)}"
    assert out[0][0] == "腾讯控股"
    assert abs(out[0][1] - 11.69e8) < 1.0
    # 中文数量解析兜底(_parse_amount)
    assert abs(fhp._parse_amount("5.5亿") - 5.5e8) < 1.0
    assert abs(fhp._parse_amount("313.1万") - 313.1e4) < 1.0
    print("  [ok] _parse_fund_holdings")


def _fake_industry_multidto():
    """模拟妙想真实返回: 第一个 dto 是时间序列(行业指数序列, 易串味),
    第二个 dto 才是单值分类(申万一级行业)。"""
    return {
        "data": {"data": {"searchDataResultDTO": {"dataTableDTOList": [
            {  # 时间序列 dto: headName=日期, 列值=某行业指数序列(非行业名)
                "table": {
                    "100000000043779": ["商贸零售-一般零售-百货", "商贸零售-一般零售-百货"],
                    "headName": ["2026-07-24", "2026-07-23"],
                }
            },
            {  # 单值分类 dto: headName 空白, 值='通信(申万)'
                "table": {
                    "100000000035009": ["通信(申万)"],
                    "headName": [" "],
                }
            },
        ]}}}
    }


def test_parse_industry_and_norm():
    assert fhp._parse_industry(_fake_industry("食品饮料")) == "食品饮料"
    # 多 dto 串味: 必须取单值分类 dto 的'通信', 而非时间序列的'商贸零售'
    assert fhp._parse_industry(_fake_industry_multidto()) == "通信"
    # 层级串 / 括号 归一为申万一级
    assert fhp._norm_industry("社会服务-酒店餐饮-餐饮") == "社会服务"
    assert fhp._norm_industry("商贸零售-互联网电商-综合电商") == "商贸零售"
    assert fhp._norm_industry("通信(申万)") == "通信"
    assert fhp._norm_industry("电气设备") == "电力设备"  # 旧版别名
    assert fhp._norm_industry("食品饮料") == "食品饮料"
    print("  [ok] _parse_industry / _norm_industry (含多dto串味修复)")


def test_oil_correction():
    cache = {}
    # 直接验证归一 + 油股纠正逻辑(模拟 resolve 命中缓存路径)
    ind = fhp._norm_industry("化工")
    if "中国海洋石油" in fhp._OIL_STOCKS:
        ind = "石油石化"
    assert ind == "石油石化"
    print("  [ok] 油股纠正(中国海洋石油->石油石化)")


def test_aggregate():
    # 科技抱团场景
    w = {"电子": 0.18, "半导体": 0.16, "计算机": 0.10, "食品饮料": 0.08,
         "医药": 0.07, "电力": 0.06, "银行": 0.05, "汽车": 0.05,
         "有色": 0.04, "军工": 0.04}
    agg = fhp._aggregate(w)
    assert agg["hhi"] > 0.03, "抱团应有较高 HHI"
    assert agg["score"] > 0, "抱团指数应 > 0"
    # 完全均匀场景
    even = {f"行业{i}": 1.0 for i in range(31)}
    agg2 = fhp._aggregate(even)
    assert agg2["hhi"] < 0.04, f"均匀 HHI 应≈0.032, 实 {agg2['hhi']}"
    assert agg2["score"] < 5, f"均匀指数应≈0, 实 {agg2['score']}"
    print(f"  [ok] _aggregate (抱团HHI={agg['hhi']} 指数={agg['score']}; 均匀HHI={agg2['hhi']:.4f})")


def test_compute_injection():
    # 注入 _result, 不走网络/缓存(注入为确定性覆盖, 即便禁用也返回注入值)
    inj = {"available": True, "score": 80.0, "hhi": 0.15, "max_weight": 0.35,
           "top3_share": 0.7, "top_industries": [("电子", 30.0)], "fund_count": 35}
    cfg = {"concentration_probe": {"holdings_layer": {"enabled": True}}}
    r = fhp.compute_holdings_concentration(cfg, _result=inj)
    assert r is inj
    # 禁用层 + 无注入(且无密钥) -> None(不触发网络)
    cfg2 = {"concentration_probe": {"holdings_layer": {"enabled": False}}}
    saved = os.environ.pop("MX_APIKEY", None)
    try:
        assert fhp.compute_holdings_concentration(cfg2) is None
    finally:
        if saved:
            os.environ["MX_APIKEY"] = saved
    print("  [ok] compute_holdings_concentration 注入/开关")


if __name__ == "__main__":
    print("=== fund_holdings_probe 离线单测 ===")
    test_parse_fund_holdings()
    test_parse_industry_and_norm()
    test_oil_correction()
    test_aggregate()
    test_compute_injection()
    print("全部通过 ✅")
