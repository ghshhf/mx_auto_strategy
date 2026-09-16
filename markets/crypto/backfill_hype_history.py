# -*- coding: utf-8 -*-
"""HYPE 历史回补 — 修复面板 HYPE 只有 45 周(约 0.87y)的缺口

问题:
  面板 HYPE 首格 2025-10-31, 仅 45 周. 对账确认其来源是 **OKX 周K**(43/43 格逐位命中),
  而 OKX 的 HYPE-USDT 现货本身只有 45 周 -> 单靠 OKX 永远补不出更早历史.
  HYPE 实际 TGE = 2024-11-29, 距今约 1.8 年 -> 面板缺约 0.9 年.

解法:
  改用 **Hyperliquid 官方 API**(api.hyperliquid.xyz/info, candleSnapshot) — HYPE 的原生链,
  最权威且免 key. 该源日K 最早 2024-12-05.

日期网格与语义(必须与既有面板一致, 否则拼接会出现 1 周错位):
  面板标签 L 承载的是"以 L+2(周日) 为起点的那一周"的收盘 = 周末时点.
  实测: 面板[L] 与 HL 日线[L+8] 的固定偏移吻合度最高(中位误差 1.6%, 源间价差).
  -> 待补区段取 HL 日线 (L+8) 的 close.
  -> 现有 45 格 **原样保留不动**(它们是 OKX 真值), 只在前段拼接.

用法:
  python backfill_hype_history.py            # 预演(dry-run), 只打印不写盘
  python backfill_hype_history.py --write    # 实际写回三面板(自动备份 .bak)
"""
import os
import sys
import json
import shutil
import urllib.request
from datetime import datetime, timezone, timedelta

import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import net_config  # noqa: E402

DATA = os.path.join(HERE, "data")
PANELS = ["weekly_adjclose_crypto50.csv",
          "weekly_adjclose_crypto50_v3.csv",
          "weekly_adjclose_crypto50_10y.csv"]
COIN = "HYPE"
HL_OFFSET = 8          # 面板标签 L <- HL 日线 (L+8) 收盘
HL_START_MS = 1732000000000     # 2024-11-19, 覆盖 TGE(2024-11-29) 前后
HL_END_MS = 1790000000000

PROXY = net_config.proxy_url()
_op = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
urllib.request.install_opener(_op)


def hl_daily(coin=COIN):
    body = json.dumps({"type": "candleSnapshot",
                       "req": {"coin": coin, "interval": "1d",
                               "startTime": HL_START_MS, "endTime": HL_END_MS}}).encode()
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = json.loads(r.read().decode())
    out = {}
    for c in rows:
        d = datetime.fromtimestamp(c["t"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        out[d] = float(c["c"])
    return out, rows


def gen_backfill(day, first_label, last_label, offset=HL_OFFSET):
    """生成待补网格: 每周五标签 L -> HL 日线 (L+offset) close"""
    out, L = {}, first_label
    while L <= last_label:
        d = (L + timedelta(days=offset)).strftime("%Y-%m-%d")
        if d in day:
            out[L] = day[d]
        L += timedelta(days=7)
    return out


def load(path):
    px = pd.read_csv(path, index_col=0, encoding="utf-8-sig")
    px.index = pd.to_datetime(px.index, format="mixed")
    return px.sort_index()


def main():
    write = "--write" in sys.argv
    print(f"代理 {PROXY}")
    day, rows = hl_daily()
    ds = sorted(day)
    print(f"Hyperliquid 官方日K: {len(rows)} 根  {ds[0]} ~ {ds[-1]}  "
          f"(TGE 2024-11-29 后首根 {ds[0]})\n")

    anchors = []
    for fn in PANELS:
        p = os.path.join(DATA, fn)
        if not os.path.exists(p):
            print(f"[跳过] {fn} 不存在"); continue
        px = load(p)
        if COIN not in px.columns:
            print(f"[跳过] {fn} 无 {COIN} 列"); continue
        s = px[COIN].dropna()
        print(f"--- {fn} ---")
        print(f"  形状 {px.shape}  索引 {px.index[0].date()} ~ {px.index[-1].date()}")
        print(f"  {COIN}: {len(s)} 格  {s.index[0].date()} ~ {s.index[-1].date()}  "
              f"首价 {s.iloc[0]:.4f}  末价 {s.iloc[-1]:.4f}")

        # 现有 45 格 vs HL 源间对账（只做展示，不改）
        errs = []
        for L, v in list(s.items())[:-2]:
            d = (L + timedelta(days=HL_OFFSET)).strftime("%Y-%m-%d")
            if d in day:
                errs.append(day[d] / v - 1)
        if errs:
            e = np.array(errs)
            print(f"  对账(现有格 vs HL 同日线): 中位偏差 {np.median(e)*100:+.2f}%  "
                  f"区间 {e.min()*100:+.2f}% ~ {e.max()*100:+.2f}%  (源间价差, 非错位)")

        # 待补区段: 从 HL 数据能支撑的最早周五 .. 现有首格的前一周五
        last_label = s.index[0] - timedelta(days=7)
        # 最早的可用标签: 其 (L+offset) 落在 HL 日K 覆盖内
        d0 = datetime.strptime(ds[0], "%Y-%m-%d") - timedelta(days=HL_OFFSET)
        while d0.weekday() != 4:        # 对齐到 >= 该日的周五
            d0 += timedelta(days=1)
        bf = gen_backfill(day, d0, last_label)
        keys = sorted(bf)
        if keys:
            print(f"  待补 {len(bf)} 格: {keys[0].date()} ~ {keys[-1].date()}  "
                  f"(首值 {bf[keys[0]]:.4f} / 末值 {bf[keys[-1]]:.4f})")
            # 衔接检验: 补段末格 与 现有首格
            print(f"  衔接检查: 补段末格 {keys[-1].date()}={bf[keys[-1]]:.4f}  "
                  f"-> 现有首格 {s.index[0].date()}={s.iloc[0]:.4f}  "
                  f"周变动 {(s.iloc[0]/bf[keys[-1]]-1)*100:+.2f}%")
        else:
            print("  无待补")

        anchors.append((fn, p, px, bf))

    if not write:
        print("\n[预演模式] 加 --write 才写盘。")
        return

    print("\n=== 写盘（就地填充 HYPE 列，只对缺失日期新增行）===")
    for fn, p, px, bf in anchors:
        if not bf:
            print(f"  [跳过] {fn} 无待补"); continue
        bak = p + ".bak_hype"
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
            print(f"  备份 -> {os.path.basename(bak)}")
        else:
            print(f"  备份已存在 -> {os.path.basename(bak)}")

        merged = px.copy()
        # 注: 大部分目标日期行已存在(BTC 等老币在那些周有数据), 需就地填充而非新增
        add_idx = pd.DatetimeIndex(sorted(bf.keys()))
        missing = add_idx.difference(merged.index)
        if len(missing):
            merged = pd.concat([merged, pd.DataFrame(index=missing)]).sort_index()
        for L, v in bf.items():
            merged.loc[L, COIN] = v
        merged = merged.sort_index()
        merged.to_csv(p, encoding="utf-8-sig")

        s2 = merged[COIN].dropna()
        n_fill = len(bf) - len(missing)
        print(f"  {fn}: 就地填充 {n_fill} 行 / 新增 {len(missing)} 行 -> "
              f"{COIN} {len(s2)} 格  {s2.index[0].date()} ~ {s2.index[-1].date()}  "
              f"({len(s2)/52:.2f}y)  总形状 {merged.shape}  首价 {s2.iloc[0]:.4f} 末价 {s2.iloc[-1]:.4f}")


if __name__ == "__main__":
    main()
