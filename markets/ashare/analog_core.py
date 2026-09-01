# -*- coding: utf-8 -*-
"""
analog_core.py
==============
A 股「类比预测 + 走前回测 + 周期定位」通用引擎（无第三方依赖，纯标准库）。

复用并重构自 index_analog_forecast / sector_analog_forecast 的 fetch_long / build_features，
新增两大能力（用户核心诉求）：

  A. walk_forward_backtest(): 对任意标的长序列做**因果走前回测**，
     每天只用「当时已有的历史」做 KNN 相似日匹配，预测未来 h 日方向，
     与真实方向比对 => 方向命中率 / 跟信号收益 / 按周期分层胜率。
     （类似加密周期回测：验证「这个预测方法到底有没有边缘」。）

  B. regime_at(): 用纯价格动量判定当日处于哪个周期相位
     —— 主升浪 / 赶顶(收割期) / 退潮期 / 主跌浪 / 筑底 / 震荡，
     把"现在在哪"系统化（用户判断当前在退潮期/收割期，让系统给出量化佐证）。

特征(全部因果, 只用当时已有数据):
  周期位置 close/MA250-1 | 动量 ret5/20/60 | 波动 20d已实现波动 | 活跃度 vol/MA20vol

⚠️ 这是"大概方向"的工具, 不是择时系统。A 股比加密更混乱, 边缘随 regime 漂移。
"""
import os
import sys
import math
import time
import json
import bisect
import datetime
import statistics as st
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(BASE))

import sys as _sys
_sys.path.insert(0, BASE)
import data_store  # 本地 + GitHub 双缓存数据层

API = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
TARGET_START = "2005-01-01"


def _get(url, dec="utf-8", timeout=12):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://finance.qq.com/",
    })
    return urllib.request.urlopen(req, timeout=timeout).read().decode(dec, "ignore")


def fetch_daily(code, start, end, count=1000):
    pref = code if code.startswith(("sh", "sz")) else ("sh" if code[0] == "5" else "sz") + code
    url = f"{API}?param={pref},day,{start},{end},{count},"
    try:
        j = json.loads(_get(url))
    except Exception as e:
        print(f"  ! {code} 解析失败: {e}", file=sys.stderr)
        return []
    node = (j.get("data") or {}).get(pref) or {}
    arr = node.get("hfqday") or node.get("day") or []
    out = []
    for r in arr:
        try:
            out.append({"d": r[0], "c": float(r[2]),
                        "v": float(r[5]) if len(r) > 5 else 0.0})
        except (IndexError, ValueError, TypeError):
            continue
    return out


# 旧 _cache 目录保留占位(不再写入); 数据统一进 data/ashare (见 data_store)
CACHE_DIR = os.path.join(BASE, "_cache")


def _pull_tencent(code, target_start=TARGET_START, page=1000):
    """纯腾讯分页实时拉取(不碰缓存), 返回 [{d,c,v}] 升序或 []。"""
    pref = code if code.startswith(("sh", "sz")) else ("sh" if code[0] == "5" else "sz") + code
    today = datetime.date.today()
    end = today.strftime("%Y-%m-%d")
    all_bars = []
    seen = set()
    guard = 0
    while True:
        guard += 1
        if guard > 40:
            break
        bars = fetch_daily(code, target_start, end, page)
        if not bars:
            break
        for b in bars:
            if b["d"] not in seen:
                seen.add(b["d"])
                all_bars.append(b)
        first_d = bars[0]["d"]
        if first_d <= target_start:
            break
        dt = datetime.date.fromisoformat(first_d) - datetime.timedelta(days=1)
        end = dt.strftime("%Y-%m-%d")
        time.sleep(0.12)
    all_bars.sort(key=lambda x: x["d"])
    return all_bars


def _pull_akshare_index(code):
    """AkShare 指数日线全量(主源)。返回 [{d,c,v}] 或 []。"""
    try:
        import akshare as ak
        df = None
        for _ in range(3):
            try:
                df = ak.stock_zh_index_daily(symbol=code)
                if df is not None and len(df) and "date" in df.columns:
                    break
            except Exception:
                time.sleep(0.8)
        if df is not None and len(df) and "date" in df.columns:
            bars = []
            for _, r in df.iterrows():
                try:
                    bars.append({"d": str(r["date"]), "c": float(r["close"]),
                                 "v": float(r.get("volume") or 0)})
                except Exception:
                    continue
            bars.sort(key=lambda x: x["d"])
            return bars
    except Exception as e:
        print(f"  ! AkShare 指数源失败({code}): {e}", file=sys.stderr)
    return []


def fetch_long(code, target_start=TARGET_START, page=1000, use_cache=True):
    """日线(腾讯源) — 经 data_store 三级回退: 本地 -> GitHub -> 实时腾讯。"""
    def live(c):
        return _pull_tencent(c, target_start, page)
    return data_store.load_bars(code, live_fn=live, source="tencent")


def fetch_index_long(code, use_cache=True):
    """指数日线 — 优先 AkShare, 兜底腾讯; 经 data_store 三级回退。
    关键修复: 沙箱里 AkShare/腾讯常被封, 此时直接读已提交到 GitHub 的历史,
    不再返回空序列导致下游崩。code 形如 sh000001 / sz399006。"""
    def live(c):
        bars = _pull_akshare_index(c)
        if len(bars) < 200:
            bars = _pull_tencent(c, "1990-01-01")
        return bars
    return data_store.load_bars(code, live_fn=live, source="akshare")


def sma(vals, i, n):
    if i < n - 1:
        return None
    return sum(vals[i - n + 1:i + 1]) / n


def stdev(vals, i, n):
    if i < n - 1:
        return None
    m = sum(vals[i - n + 1:i + 1]) / n
    return math.sqrt(sum((v - m) ** 2 for v in vals[i - n + 1:i + 1]) / n)


def build_features(bars):
    closes = [b["c"] for b in bars]
    vols = [b["v"] for b in bars]
    feats = []
    for i in range(len(bars)):
        c = closes[i]
        ma250 = sma(closes, i, 250) or sma(closes, i, 120) or sma(closes, i, 60)
        ma60 = sma(closes, i, 60)
        ma20v = sma(vols, i, 20)
        if ma250 is None or ma60 is None or ma20v is None or ma20v <= 0:
            feats.append(None)
            continue
        level = c / ma250 - 1.0
        ret5 = (c / closes[i - 5] - 1) if i >= 5 else None
        ret20 = (c / closes[i - 20] - 1) if i >= 20 else None
        ret60 = (c / closes[i - 60] - 1) if i >= 60 else None
        vol20 = stdev([(closes[j] / closes[j - 1] - 1) for j in range(max(1, i - 19), i + 1)],
                      19, 20) if i >= 20 else None
        vol_ratio = vols[i] / ma20v
        if None in (ret5, ret20, ret60, vol20):
            feats.append(None)
            continue
        feats.append([level, ret5, ret20, ret60, vol20, vol_ratio])
    return feats


# ---------------------------------------------------------------------------
# 周期相位判定 (纯价格动量, 只用 idx 之前的数据)
# ---------------------------------------------------------------------------
def regime_at(bars, feats, idx):
    """返回 (label, detail_dict)。基于 idx 日可知的量。"""
    if feats[idx] is None:
        return ("数据不足", {})
    i = idx
    c = bars[i]["c"]
    closes = [b["c"] for b in bars]
    r250 = (c / closes[i - 250] - 1) if i >= 250 else None
    r60 = (c / closes[i - 60] - 1) if i >= 60 else None
    r20 = (c / closes[i - 20] - 1) if i >= 20 else None
    level = feats[i][0]  # close/MA250 - 1
    above_ma = level > 0

    def has(*xs):
        return all(x is not None for x in xs)

    if has(r250, r60, r20):
        # 主升浪: 长中短多, 在年线上方
        if r250 > 0.15 and r60 > 0.10 and above_ma:
            return ("主升浪", {"r250": r250, "r60": r60, "r20": r20, "level": level})
        # 赶顶/收割期: 长期仍强, 但短中期动量减速甚至转负 (r20 < r60)
        if r250 > 0.15 and above_ma and (r20 < r60 or r20 < 0):
            return ("赶顶/收割期", {"r250": r250, "r60": r60, "r20": r20, "level": level})
        # 退潮期: 从高位回落, 中长期仍正但短中期转负, 跌破年线或贴近
        if r250 > 0 and r60 < 0 and r20 < 0:
            return ("退潮期", {"r250": r250, "r60": r60, "r20": r20, "level": level})
        # 主跌浪: 长中短全空
        if r250 < 0 and r60 < 0 and r20 < 0:
            return ("主跌浪", {"r250": r250, "r60": r60, "r20": r20, "level": level})
        # 筑底: 长期弱但中期转强 (恢复中)
        if r250 < 0 and r60 > 0:
            return ("筑底", {"r250": r250, "r60": r60, "r20": r20, "level": level})
        # 震荡: 其余
        return ("震荡", {"r250": r250, "r60": r60, "r20": r20, "level": level})
    return ("数据不足", {})


# ---------------------------------------------------------------------------
# 全局 z 标准化 (一次性) + 邻居查找 (多 horizon 复用)
# ---------------------------------------------------------------------------
def global_z(feats):
    """对特征矩阵做全局标准化(一次性), 返回 (Z, means, sds)。
    注: 仅缩放常量含全样本信息, 特征本身全因果; 对 KNN 排序影响极小, 换来大幅加速。"""
    cols = list(zip(*[f for f in feats if f is not None]))
    means = [st.mean(c) for c in cols]
    sds = [st.pstdev(c) for c in cols]
    Z = [None] * len(feats)
    for i, f in enumerate(feats):
        if f is None:
            continue
        Z[i] = [(f[k] - means[k]) / (sds[k] or 1) for k in range(len(f))]
    return Z, means, sds


def neighbor_idx_at(Z, valid, idx, K=50, train_window=1250, excl=5):
    """返回 idx 的 K 个最相似历史日索引(升序排好), 只用 j<idx 数据。"""
    if Z[idx] is None:
        return None
    lo = max(0, idx - train_window)
    lo_i = bisect.bisect_left(valid, lo)
    hi_i = bisect.bisect_left(valid, idx - excl + 1)
    train = valid[lo_i:hi_i]
    if len(train) < 30:
        return None
    tz = Z[idx]
    z0, z1, z2, z3, z4, z5 = tz
    dist = []
    for j in train:
        zj = Z[j]
        d = ((z0 - zj[0]) ** 2 + (z1 - zj[1]) ** 2 + (z2 - zj[2]) ** 2 +
             (z3 - zj[3]) ** 2 + (z4 - zj[4]) ** 2 + (z5 - zj[5]) ** 2)
        dist.append((d, j))
    dist.sort(key=lambda x: x[0])
    return [j for _, j in dist[:K]], len(train)


# ---------------------------------------------------------------------------
# KNN 预测 (在指定 idx, 只用 j<idx 的数据) —— 单 horizon 便捷版
# ---------------------------------------------------------------------------
def knn_predict_at(bars, Z, valid, idx, K=50, horizon=1, train_window=1250, excl=5):
    res = neighbor_idx_at(Z, valid, idx, K, train_window, excl)
    if res is None:
        return None
    knn, n_train = res
    futs = []
    vrs = []
    for j in knn:
        if j + horizon >= len(bars):
            continue
        futs.append(bars[j + horizon]["c"] / bars[j]["c"] - 1)
        vrs.append(Z[j][5])
    if not futs:
        return None
    hit = sum(1 for r in futs if r > 0) / len(futs)
    mean_fut = sum(futs) / len(futs)
    vr_sorted = sorted(vrs)
    med_vr = vr_sorted[len(vr_sorted) // 2]
    hi = [r for r, v in zip(futs, vrs) if v >= med_vr]
    lo = [r for r, v in zip(futs, vrs) if v < med_vr]
    hi_m = sum(hi) / len(hi) if hi else None
    lo_m = sum(lo) / len(lo) if lo else None
    realized = bars[idx + horizon]["c"] / bars[idx]["c"] - 1 if idx + horizon < len(bars) else None
    return {"pred": mean_fut, "hit": hit, "n_train": n_train,
            "hi_m": hi_m, "lo_m": lo_m, "med_vr": med_vr, "realized": realized}


# ---------------------------------------------------------------------------
# 走前回测 (多 horizon, 邻居一次算出多 horizon 复用)
# ---------------------------------------------------------------------------
def walk_forward_backtest(bars, feats, K=50, horizons=(1, 5, 20),
                          train_window=1250, excl=5, step=1, min_idx=260):
    """逐日走前回测。返回 {horizon: stats}。
    stats = {n, hit(方向命中率), avg_real(平均真实收益), sig_ret(跟信号收益),
             base_long(始终看多), by_regime:{label:{n,hit,avg_real}}}"""
    Z, _, _ = global_z(feats)
    valid = [i for i, f in enumerate(feats) if f is not None]
    results = {h: [] for h in horizons}
    max_h = max(horizons)
    total = len(bars) - max_h - 1
    for idx in range(min_idx, total, step):
        if Z[idx] is None:
            continue
        res = neighbor_idx_at(Z, valid, idx, K, train_window, excl)
        if res is None:
            continue
        knn, _ = res
        reg, _ = regime_at(bars, feats, idx)
        # 各 horizon: 真实未来收益 + 基于邻居该 horizon 未来收益的方向信号
        ok = True
        for h in horizons:
            if idx + h >= len(bars):
                ok = False
                break
        if not ok:
            continue
        for h in horizons:
            sig_futs = []
            for j in knn:
                if j + h < len(bars):
                    sig_futs.append(bars[j + h]["c"] / bars[j]["c"] - 1)
            if not sig_futs:
                continue
            mean_sig = sum(sig_futs) / len(sig_futs)
            sgn = 1 if mean_sig > 0 else -1
            real = bars[idx + h]["c"] / bars[idx]["c"] - 1
            results[h].append((sgn, real, reg))

    out = {}
    for h in horizons:
        rows = results[h]
        n = len(rows)
        if n == 0:
            out[h] = None
            continue
        hit = sum(1 for s, r, _ in rows if (s > 0 and r > 0) or (s < 0 and r < 0)) / n
        avg_real = sum(r for _, r, _ in rows) / n
        sig_ret = sum((r if s > 0 else -r) for s, r, _ in rows) / n
        base_long = sum(r for _, r, _ in rows) / n
        by_reg = {}
        for s, r, reg in rows:
            d = by_reg.setdefault(reg, {"n": 0, "hit": 0, "sum_r": 0.0})
            d["n"] += 1
            if (s > 0 and r > 0) or (s < 0 and r < 0):
                d["hit"] += 1
            d["sum_r"] += r
        by_reg_out = {reg: {"n": d["n"], "hit": d["hit"] / d["n"],
                            "avg_real": d["sum_r"] / d["n"]}
                      for reg, d in by_reg.items()}
        out[h] = {"n": n, "hit": hit, "avg_real": avg_real, "sig_ret": sig_ret,
                  "base_long": base_long, "by_regime": by_reg_out}
    return out



def sig(m):
    if m is None:
        return "—"
    if m > 0.0015:
        return "偏多▲"
    if m < -0.0015:
        return "偏空▼"
    return "中性—"


if __name__ == "__main__":
    # 自测: 上证回测 1/5/20 日
    print("拉取上证长序列 ...", file=sys.stderr, flush=True)
    sh = fetch_long("sh000001")
    feats = build_features(sh)
    print(f"条数={len(sh)} 区间={sh[0]['d']}->{sh[-1]['d']}", file=sys.stderr, flush=True)
    bt = walk_forward_backtest(sh, feats, K=50, horizons=(1, 5, 20))
    for h in (1, 5, 20):
        s = bt[h]
        print(f"\n=== 上证 horizon={h}日 ===")
        print(f"样本={s['n']} 方向命中率={s['hit']*100:.1f}% 平均真实收益={s['avg_real']*100:+.2f}% "
              f"跟信号收益={s['sig_ret']*100:+.2f}% 始终看多={s['base_long']*100:+.2f}%")
        print("按周期相位分层(命中率/平均真实):")
        for reg, d in sorted(s["by_regime"].items(), key=lambda kv: -kv[1]["n"]):
            print(f"  {reg:8s} n={d['n']:5d} 命中={d['hit']*100:4.1f}% 真实={d['avg_real']*100:+.2f}%")
    # 当前 regime
    print("\n当前相位:", regime_at(sh, feats, len(sh) - 1))
