# -*- coding: utf-8 -*-
"""池变更后统一刷新全部派生统计(防旧快照残留).

背景: 2026-09-06 删 ICP/INJ 后, held_weeks/mcap_snapshot/bt_pool_cycle_participation/
coin_attribution 四个派生 JSON 停在旧 42/41 币面板, 导致后续查询引用过期数据
(曾把回测持有周数误当个人持仓)。此后凡 manage_token.py 增删币, 收尾跑一遍本脚本。

用法:
    python refresh_stats.py          # 全量重算
    python refresh_stats.py --fast  # 跳过两个回测, 只刷新市值
"""
import subprocess, sys, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

STEPS = [
    ("fetch_mcaps.py",              "mcap_snapshot.json + 三CSV市值快照",   True),
    ("held_weeks.py",               "held_weeks.json (回测持有周数)",       False),
    ("coin_attribution.py",         "coin_attribution.json (币贡献归因)",   False),
    ("bt_pool_cycle_participation.py", "bt_pool_cycle_participation.json (周期参与)", False),
]

fast = "--fast" in sys.argv
# json -> 生成它的脚本. --fast 下跳过的文件只查"池外残留", 不查"缺池内币"
# (它们未经本轮重算, 池新增币时本就缺, 属预期, 由全量重算补齐).
FILE_SRC = {
    "mcap_snapshot.json": "fetch_mcaps.py",
    "held_weeks.json": "held_weeks.py",
    "coin_attribution.json": "coin_attribution.py",
    "bt_pool_cycle_participation.json": "bt_pool_cycle_participation.py",
}
# coin_attribution 只统计进攻币 (BTC/ETH 防御币单列 base, 属设计而非缺失),
# 因此对它只校验"池外残留", 不校验"缺池内币".
RESIDUE_ONLY = {"coin_attribution.json"}
RAN = set()
for script, desc, is_cheap in STEPS:
    if fast and not is_cheap:
        print(f"[skip] {script} (--fast)")
        continue
    t0 = time.time()
    print(f"[*] {script} — {desc} ...", flush=True)
    r = subprocess.run([PY, script], cwd=HERE)
    dt = time.time() - t0
    print(f"    {'OK' if r.returncode == 0 else 'FAIL(' + str(r.returncode) + ')'}  {dt:.0f}s\n", flush=True)
    if r.returncode == 0:
        RAN.add(script)

# 终检: 统计文件币集必须 ⊆ 当前池 (池外残留 = 旧版本快照, 报警)
# 2026-09-07 通用化: 不再硬编码具体币名, 任何"已删币仍残留在派生 JSON"都会被拦下.
import json
sys.path.insert(0, HERE)
import crypto_adoption_v2 as ca2
pool = set(ca2.ALL_COINS)


def _collect_syms(f):
    """按各派生 JSON 的 schema 抽取币符号集."""
    d = json.load(open(f, encoding="utf-8"))
    if isinstance(d, dict) and "_meta" in d and "coins" in d:   # held_weeks(新版带 _meta)
        d = d["coins"]
    if isinstance(d, list):            # held_weeks / mcap_snapshot: [{'sym': ...}]
        return {x.get("sym") for x in d if isinstance(x, dict) and x.get("sym")}
    if isinstance(d, dict):
        if "coins" in d and isinstance(d["coins"], list):   # coin_attribution
            return {x.get("coin") or x.get("sym") for x in d["coins"]
                    if isinstance(x, dict) and (x.get("coin") or x.get("sym"))}
        if "detail" in d and isinstance(d["detail"], list):  # bt_pool_cycle_participation
            return {x.get("coin") for x in d["detail"] if isinstance(x, dict) and x.get("coin")}
        if "pool" in d:                # 兜底: 遍历找全部字符串值(符号形态)
            out = set()
            for v in d.values():
                if isinstance(v, list) and v and all(isinstance(i, str) and len(i) <= 8 for i in v):
                    out |= set(v)
            return out
    return set()


stale = []
for f in ["held_weeks.json", "mcap_snapshot.json", "bt_pool_cycle_participation.json", "coin_attribution.json"]:
    p = os.path.join(HERE, f)
    if not os.path.exists(p):
        stale.append((f, "文件不存在"))
        continue
    src = FILE_SRC[f]
    syms = _collect_syms(p)
    check_full = (src in RAN and f not in RESIDUE_ONLY)
    if check_full:                     # 本轮重算过且需全量对齐 -> 残留/缺失都查
        missing = sorted(pool - syms)
        if missing:
            stale.append((f, f"缺池内币 {missing}"))
    else:                              # --fast 跳过 或 进攻币归因 -> 只查池外残留
        pass
    leftovers = sorted(syms - pool)
    if leftovers:
        stale.append((f, f"残留池外币 {leftovers}"))
if stale:
    print("[!] 派生统计与当前池不一致:")
    for f, why in stale:
        print(f"    {f}: {why}")
    sys.exit(1)
print(f"[OK] 全部统计已对齐当前 {len(pool)} 币面板: {sorted(pool)}")
