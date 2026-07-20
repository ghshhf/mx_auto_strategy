"""
inspect_positions.py - 只读止损/止盈巡检 (v1, 不触发任何交易)

用途: 每天手动触发 3 次(10:00 / 12:00 / 14:00)的"巡检"本质只读 —
      比对券商真实持仓成本与现价, 检查是否触及止损/止盈阈值, 并校验
      .cost_basis.json 成本缓存与现实持仓的一致性(防 auto_trader 幽灵/漏记仓位)。

特点:
  - 只读: 绝不调用买入/卖出, 仅打印结论与建议。
  - 真值来源: mx-moni 落盘的 "我的持仓" JSON (券商口径成本/现价, 权威)。
  - 阈值来源: strategy_config.json 的 risk/sell_rules。

用法:
  python3.11 inspect_positions.py          # 巡检最近一次持仓快照
  python3.11 inspect_positions.py --fresh  # 先拉一次最新持仓再巡检
"""
import os
import sys
import json
import glob
import argparse
import subprocess
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
COST_CACHE_PATH = os.path.join(BASE, ".cost_basis.json")
CONFIG_PATH = os.path.join(BASE, "strategy_config.json")
OUTPUT_DIR = "/root/.openclaw/workspace/mx_data/output"
MX_MONI_PY = "/root/.codebuddy/skills/mx-moni/mx_moni.py"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_cost_cache():
    try:
        with open(COST_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("cost_basis", {})
    except Exception:
        return {}


def latest_position_json():
    files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "mx_moni_我的持仓_*.json")))
    return files[-1] if files else None


def pull_fresh():
    env = os.environ.copy()
    env["MX_APIKEY"] = os.environ.get("MX_APIKEY", "")
    env["MX_API_URL"] = env.get("MX_API_URL", "https://mkapi2.dfcfs.com/finskillshub")
    try:
        subprocess.run(["python3.11", MX_MONI_PY, "我的持仓"],
                       capture_output=True, text=True, timeout=60, env=env)
    except Exception as e:
        print(f"[warn] 拉取最新持仓失败: {e}")
    return latest_position_json()


def parse_positions(path):
    with open(path, "r", encoding="utf-8") as f:
        j = json.load(f)
    out = []
    for p in j["data"]["posList"]:
        dec_c = p.get("costPriceDec", 2)
        dec_p = p.get("priceDec", 2)
        out.append({
            "code": p["secCode"],
            "name": p.get("secName", p["secCode"]),
            "qty": p["count"],
            "cost": p["costPrice"] / (10 ** dec_c),
            "price": p["price"] / (10 ** dec_p),
            "profit": p.get("profit", 0),
            "profit_pct": p.get("profitPct", 0),
            "value": p.get("value", 0),
        })
    return j["data"], out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="先拉一次最新持仓再巡检")
    args = ap.parse_args()
    cfg = load_config()
    risk = cfg.get("risk", {})
    sell = cfg.get("sell_rules", {})

    sl_def = risk.get("stop_loss_pct", -5)          # 防御仓硬止损
    sl_off = risk.get("offensive_stop_loss_pct", -10)  # 进攻仓硬止损
    tiers = sorted([t for t in sell.get("tiers", []) if t.get("gain_pct", 0) > 0],
                   key=lambda t: t["gain_pct"])

    path = pull_fresh() if args.fresh else latest_position_json()
    if not path:
        print("❌ 未找到持仓快照, 请先 --fresh 拉取")
        sys.exit(1)
    meta, positions = parse_positions(path)
    cache = load_cost_cache()

    print(f"\n[{datetime.now():%H:%M:%S}] 巡检 (只读, 不交易)  快照: {os.path.basename(path)}")
    print(f"  总资产={meta['totalAssets']/10000:.2f}万  持仓市值={meta['totalPosValue']/10000:.2f}万  "
          f"可用={meta['availBalance']/10000:.2f}万  总盈亏={meta.get('totalProfit',0):.2f}元\n")

    # ---- 一致性校验: 缓存 vs 券商 ----
    broker_codes = {p["code"] for p in positions}
    cache_codes = set(cache.keys())
    phantom = cache_codes - broker_codes   # 缓存有, 券商无 -> 幽灵仓位
    missing = broker_codes - cache_codes   # 券商有, 缓存无 -> 漏记(会被重复买入)
    if phantom:
        print(f"  ⚠️ 幽灵仓位(缓存有/券商无, auto_trader 会误卖): {sorted(phantom)}")
    if missing:
        print(f"  ⚠️ 漏记仓位(券商有/缓存无, auto_trader 会重复买入): {sorted(missing)}")
    if not phantom and not missing:
        print("  ✅ 成本缓存与券商持仓一致")

    # ---- 逐仓止损/止盈检查 ----
    action_needed = False
    print(f"\n  {'代码':<8}{'名称':<10}{'盈亏%':>9}{'止损线':>9}{'状态':>10}")
    print("  " + "-" * 48)
    for p in positions:
        offensive = cache.get(p["code"], {}).get("_offensive", False)
        sl = sl_off if offensive else sl_def
        g = p["profit_pct"]
        tag = "进攻" if offensive else "防御"
        # 止损判定
        if g <= sl:
            status = f"⛔止损({sl}%)"
            action_needed = True
        else:
            # 止盈档位提示
            hit = [t for t in tiers if g >= t["gain_pct"]]
            if hit:
                top = hit[-1]
                status = f"💰止盈+{top['gain_pct']}%"
                action_needed = True
            else:
                dist = tiers[0]["gain_pct"] - g if tiers else None
                status = f"✅持有(距+{dist:.0f}%)" if dist is not None else "✅持有"
        print(f"  {p['code']:<8}{p['name']:<10}{g:>8.2f}%{sl:>8.0f}%{status:>12}")

    print("\n  ── 巡检结论 ──")
    if action_needed:
        print("  🔔 需要人工关注: 存在触及止损/止盈的仓位, 请按规则处理。")
    else:
        print("  ✅ 全部健康: 无仓位触及止损或首档止盈, 维持现状, 无需操作。")
    if phantom or missing:
        print("  🔧 建议: 先修复 .cost_basis.json 再跑 auto_trader, 避免幽灵/重复交易。")


if __name__ == "__main__":
    main()
