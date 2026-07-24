""" concentration_probe.py - v6.9 公募基金行业集中度探针 (防御端)
=================================================================
设计目标
--------
与「市场冷热温度计」对称, 但作用于**防御端**: 监测"整个市场/公募资金
对少数行业的抱团集中度", 作为防御端的尾部风险预警。

用户原话: "最近新的公募基金基本全部都全仓半导体AI方向了, 这种集中度
越来越高了, 跟加温度计一样, 本质上还是防御端。"

为什么用"市场拥挤度"而非"基金真实持仓":
  * 基金季报持仓滞后一个季度, 无法实时预警;
  * 市场对某一行业的极致抱团, 会实时反映在行业成交额/资金流/涨幅的
    集中程度上, 这正是尾部风险(踩踏/补跌)的真正来源;
  * 因此本探针用 4 个实时维度合成 0~100 的"行业集中度指数", 作为
    "全市场抱团"的代理指标。含义: 越高 = 资金越挤在少数行业 = 防御越要收。

输出  get_fund_concentration(cfg) -> dict:
    score, label(normal/elevated/crowded/extreme), defensive_tighten(0~1),
    hot_cluster_share_pct, top_hot_sectors, enabled, shadow, apply, detail, _parts

防御端动作(在 auto_trader.run_once 中接成"总风险敞口收紧"):
  * defensive_tighten = 1.0 -> 不干预(正常分散市)
  * < 1.0            -> 防御+进攻按比例缩减, 释放部分转现金(整体降敞口)
  与温度计提(只削进攻、防御底仓不动)正交: 温度=进攻时机, 集中度=市场整体拥挤。

稳健性(与 temperature_probe 一致, 实盘优先, 不死机)
  * 单一维度抓取/计算失败 -> 该维度权重 redistributed 给其他可用维度
  * 全部失败 -> defensive_tighten = 1.0 (等于不干预, 退回原逻辑)
  * 结果缓存 cache_seconds, 避免 loop 模式频繁打接口
  * 仅标准库(urllib/json), 与 market_data.py 风格一致, 无第三方依赖
  * 所有网络调用均 try/except, 异常绝不上抛到下单主流程
=================================================================
"""
import os
import sys
import json
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_CACHE = {"ts": 0.0, "data": None}


def _cfg(cfg):
    return cfg.get("concentration_probe", {}) or {}


def _get_json(url, timeout=10):
    """拉取 JSON, 与 temperature_probe._get_json 同源风格(仅标准库)。"""
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; mx-conc/1.0)",
        "Referer": "https://quote.eastmoney.com/",
    })
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
    return json.loads(raw)


# ---------------------------------------------------------------------------
# 单一数据源: 东方财富 行业板块(成交额/涨跌幅/主力净流入)
# 4 个维度全部由这一次抓取派生, 任一维度缺失仅影响该维度打分
# ---------------------------------------------------------------------------
def fetch_sector_board():
    """行业板块快照 -> list[(name, chg_pct, amount, netflow)]。失败返回 None。

    fs=m:90+t:2 为东方财富行业指数板块; f3=涨跌幅 f6=成交额(元) f62=主力净流入(元)
    """
    url = ("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=300&po=1&np=1"
           "&fltt=2&invt=2&fid=f3&fs=m:90+t:2"
           "&fields=f12,f14,f3,f6,f62")
    try:
        j = _get_json(url)
        rows = (j.get("data") or {}).get("diff") or []
        if not rows:
            return None
        board = []
        for r in rows:
            try:
                chg = float(r.get("f3") or 0.0)
                amt = float(r.get("f6") or 0.0)
                nf = float(r.get("f62") or 0.0)
            except (ValueError, TypeError):
                continue
            board.append((r.get("f14") or "", chg, amt, nf))
        return board if board else None
    except Exception:
        return None


def _is_hot(name, hot_cluster):
    return any(k in (name or "") for k in hot_cluster)


# ---------------------------------------------------------------------------
# 维度派生 + 打分(输入已归一化到 0~1; None 表示维度缺失)
# ---------------------------------------------------------------------------
def _derive_parts(board, hot_cluster):
    """从板块快照派生 4 个原始指标。返回 dict(任一可 None)。"""
    if not board:
        return None
    total_amt = sum(abs(a) for _, _, a, _ in board)
    if total_amt <= 0:
        return None

    # ① 成交额 HHI
    shares = [abs(a) / total_amt for _, _, a, _ in board]
    hhi = sum(s * s for s in shares)

    # ② 科技/AI 簇成交额占比
    hot_amt = sum(abs(a) for n, _, a, _ in board if _is_hot(n, hot_cluster))
    hot_share = hot_amt / total_amt

    # ③ 涨幅集中度: 热点簇贡献了当日多少"正向涨幅"
    total_gain = sum(max(c, 0.0) for _, c, _, _ in board)
    hot_gain = sum(max(c, 0.0) for n, c, _, _ in board if _is_hot(n, hot_cluster))
    ret_share = (hot_gain / total_gain) if total_gain > 0 else None

    # ④ 主力净流入 HHI
    total_nf = sum(abs(nf) for _, _, _, nf in board)
    nf_hhi = (sum((abs(nf) / total_nf) ** 2 for _, _, _, nf in board)
              if total_nf > 0 else None)

    # 热点簇明细(按成交额排序前几)
    hot = sorted([(n, abs(a) / total_amt) for n, _, a, _ in board if _is_hot(n, hot_cluster)],
                 key=lambda x: x[1], reverse=True)

    return {
        "hhi": hhi,
        "hot_share": hot_share,
        "ret_share": ret_share,
        "nf_hhi": nf_hhi,
        "top_hot": hot,
    }


def _score_hhi(hhi):
    # 均衡(100行业等权)=0.01; 拥挤 0.08~0.15。映射 0.02->0, 0.12->1
    return max(0.0, min(1.0, (hhi - 0.02) / (0.12 - 0.02)))


def _score_hot_share(share):
    # 正常 0.15~0.25; 拥挤 >0.35; 极端 >0.45。映射 0.15->0, 0.45->1
    return max(0.0, min(1.0, (share - 0.15) / (0.45 - 0.15)))


def _score_ret_share(ret):
    # 正常 0.3~0.5; 拥挤 >0.7。映射 0.3->0, 0.7->1
    return max(0.0, min(1.0, (ret - 0.3) / (0.7 - 0.3)))


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def get_fund_concentration(cfg, force_refresh=False, _board=None):
    gc = _cfg(cfg)
    enabled = gc.get("enabled", True)
    shadow = gc.get("shadow_mode", True)  # 默认影子: 新风险信号先只观察
    if not enabled:
        return {"score": 0.0, "label": "normal", "defensive_tighten": 1.0,
                "enabled": False, "shadow": shadow, "apply": False,
                "hot_cluster_share_pct": 0.0, "top_hot_sectors": [],
                "detail": "集中度探针未启用, 不干预仓位", "_parts": {}}

    # 命中缓存直接返回(loop 模式避免频繁打接口; 注入 _board 为测试/确定性场景, 跳过缓存)
    now = time.time()
    if (not force_refresh) and _board is None and _CACHE["data"] and (now - _CACHE["ts"] < gc.get("cache_seconds", 300)):
        d = dict(_CACHE["data"])
        d["shadow"] = shadow
        d["apply"] = (enabled and not shadow)
        return d

    hot_cluster = gc.get("hot_cluster", ["半导体", "半导体设备", "AI", "人工智能",
                                         "计算机", "软件", "通信", "电子", "元器件",
                                         "消费电子", "军工", "军工电子"])

    board = _board if _board is not None else fetch_sector_board()
    parts = _derive_parts(board, hot_cluster)

    # 全部失败 -> 安全退回原逻辑(不干预, tighten=1.0)
    if not parts:
        return {"score": 0.0, "label": "unknown", "defensive_tighten": 1.0,
                "enabled": True, "shadow": shadow, "apply": (enabled and not shadow),
                "hot_cluster_share_pct": 0.0, "top_hot_sectors": [],
                "detail": "行业板块数据抓取失败, 退回原仓位逻辑(不干预)", "_parts": {}}

    w = gc.get("weights", {"turnover_hhi": 0.30, "hot_cluster_share": 0.35,
                           "return_dispersion": 0.20, "netflow_hhi": 0.15})

    scored = {}
    scored["turnover_hhi"] = _score_hhi(parts["hhi"])
    scored["hot_cluster_share"] = _score_hot_share(parts["hot_share"])
    if parts["ret_share"] is not None:
        scored["return_dispersion"] = _score_ret_share(parts["ret_share"])
    if parts["nf_hhi"] is not None:
        scored["netflow_hhi"] = _score_hhi(parts["nf_hhi"])

    avail_w = {k: w.get(k, 0.0) for k in scored}
    tot = sum(avail_w.values()) or 1.0
    score = sum(scored[k] * avail_w[k] for k in scored) / tot * 100

    th = gc.get("thresholds", {"elevated": 40, "crowded": 65, "extreme": 82})
    tk = gc.get("tighten", {"elevated": 0.90, "crowded": 0.75, "extreme": 0.60, "floor": 0.50})
    if score >= th["extreme"]:
        label, tighten = "extreme", tk["extreme"]
    elif score >= th["crowded"]:
        label, tighten = "crowded", tk["crowded"]
    elif score >= th["elevated"]:
        # 在 elevated~crowded 之间线性收紧
        r = (score - th["elevated"]) / max(1e-6, th["crowded"] - th["elevated"])
        label, tighten = "elevated", round(tk["elevated"] - (tk["elevated"] - tk["crowded"]) * r, 3)
    else:
        label, tighten = "normal", 1.0
    tighten = max(tk.get("floor", 0.50), tighten)

    top_hot = [n for n, _ in parts["top_hot"][:6]]
    detail = (f"成交额HHI={parts['hhi']:.3f} 科技簇占比={parts['hot_share']*100:.1f}% "
              f"涨幅集中度={ (parts['ret_share'] if parts['ret_share'] is not None else 0):.2f}"
              f" 净流入HHI={ (parts['nf_hhi'] if parts['nf_hhi'] is not None else 0):.3f}"
              f" 热点={','.join(top_hot[:4])}")

    result = {
        "score": round(score, 1),
        "label": label,
        "defensive_tighten": round(tighten, 2),
        "enabled": True,
        "shadow": shadow,
        "apply": (enabled and not shadow),
        "hot_cluster_share_pct": round(parts["hot_share"] * 100, 1),
        "top_hot_sectors": top_hot,
        "detail": detail.strip(),
        "_parts": {k: round(v, 3) for k, v in scored.items()},
    }
    if _board is None:  # 仅真实抓取结果缓存, 注入板不缓存(避免测试串味)
        _CACHE["ts"] = now
        _CACHE["data"] = result
    return result


# ---------------------------------------------------------------------------
# 离线自检 / 测试
# ---------------------------------------------------------------------------
def _make_board(hhi_target, hot_share_target, ret_share_target, nf_hhi_target):
    """构造一个近似满足目标指标的假板块(供自检/测试, 不触发网络)。

    把热点簇成交额按 [0.40,0.30,0.20,0.10] 倾斜分到前 4 个热点行业, 其余热点
    行业微量, 非热点均分, 以贴近真实"少数行业主导"的分布; 涨跌幅按 ret_share
    在热点/非热点间分配。净流入与成交额同分布 -> nf_hhi == turnover_hhi。
    """
    board = []
    n = 100
    hot_names = ["电子", "半导体", "AI", "计算机", "通信", "消费电子",
                 "军工", "软件", "元器件", "半导体设备", "人工智能", "军工电子"]
    hot_amt = hot_share_target
    skew = [0.40, 0.30, 0.20, 0.10]
    first4 = sum(skew)
    per_tail = (hot_amt * (1 - first4)) / max(1, len(hot_names) - 4)
    others = (1.0 - hot_amt) / (n - len(hot_names))
    giant_chg = ret_share_target * 10.0
    other_chg = (1.0 - ret_share_target) / (n - 1) * 10.0
    for i in range(n):
        if i < 4:
            amt = hot_amt * skew[i]
        elif i < len(hot_names):
            amt = per_tail
        else:
            amt = others
        if i < len(hot_names):
            name = hot_names[i]
            chg = giant_chg
        else:
            name = f"行业{i}"
            chg = other_chg
        nf = amt  # 净流入与成交额同分布 -> nf_hhi == turnover_hhi
        board.append((name, chg, amt * 1e11, nf * 1e10))
    return board


def _self_test():
    """离线自检: 不触发网络, 演示打分与防御收紧逻辑。"""
    print("=== 行业集中度探针打分逻辑自检(离线) ===")
    cases = [
        ("正常分散市", 0.03, 0.22, 0.40, 0.03),
        ("轻度抱团",   0.08, 0.38, 0.60, 0.06),
        ("高度拥挤",   0.11, 0.50, 0.80, 0.10),
        ("极端抱团(AI/半导体)", 0.14, 0.63, 0.88, 0.13),
    ]
    gc = {"concentration_probe": {"hot_cluster": ["半导体", "AI", "计算机", "电子", "通信"]}}
    for name, h, s, r, nf in cases:
        board = _make_board(h, s, r, nf)
        res = get_fund_concentration({"concentration_probe": {}}, _board=board)
        res2 = get_fund_concentration(gc, _board=board)
        print(f"  {name}: HHI={h} 占比={s*100:.0f}% 涨幅集中度={r} -> "
              f"指数={res['score']:.0f} 标签={res['label']} 防御收紧x{res['defensive_tighten']:.2f}")


if __name__ == "__main__":
    import os as _os
    if _os.environ.get("MOCK"):
        _self_test()
    else:
        try:
            cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                              "strategy_config.json"), encoding="utf-8"))
            print("=== 公募基金行业集中度探针 实时抓取 ===")
            t = get_fund_concentration(cfg, force_refresh=True)
            print(json.dumps(t, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"实时抓取失败({e}), 退回离线自检:")
            _self_test()
