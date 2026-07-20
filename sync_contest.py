"""
sync_contest.py - 龙虾大赛远程账户 只读同步 (v1.0)

核心理念 (用户明确):
  龙虾大赛的清零是【远程比赛平台】干的, 本地不该替它操心.
  但咱们要在本地【永久保留一份完整记录】, 未来回测才有依据.
  所以本脚本只做一件事: 定时(你手动触发)从远程把账户快照拉回来, 追加进本地账本.

行为:
  - 调 mx-moni 查询持仓/资金 (只读, 不下单)
  - 把远程快照写成 records/sim_<账号>/contest_snapshot.jsonl (追加)
  - 远程清零不影响本地: 每次都是新快照追加, 历史全留
  - 绝不调用任何下单/reset 接口

用法:
  python3 sync_contest.py --account sim_261984600000041416
  python3 sync_contest.py --account sim_261984600000041416 --dry   # 只看不写
"""
import os
import json
import glob
import subprocess
import argparse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
MX_MONI_PY = "/root/.codebuddy/skills/mx-moni/mx_moni.py"
RECORD_ROOT = os.path.join(HERE, "records")
# mx-moni 把每次查询的原始 JSON 落盘到此目录(文件名含查询文本与时间戳)
OUTPUT_DIR = "/root/.openclaw/workspace/mx_data/output"

# 默认龙虾账户
DEFAULT_SIM = "sim_261984600000041416"


def _call_mx(text):
    env = os.environ.copy()
    env["MX_APIKEY"] = env.get("MX_APIKEY", "")
    env["MX_API_URL"] = env.get("MX_API_URL", "https://mkapi2.dfcfs.com/finskillshub")
    try:
        out = subprocess.run(["python3.11", MX_MONI_PY, text],
                             capture_output=True, text=True, timeout=60, env=env)
        return (out.stdout or out.stderr).strip()
    except Exception as e:
        return f"mx_moni调用失败: {e}"


def _latest_json(query):
    """读取 mx-moni 最近一次保存的该查询原始 JSON(避免依赖其表格 stdout)。"""
    try:
        safe = query.replace('/', '_')[:30]
        files = sorted(glob.glob(os.path.join(OUTPUT_DIR, f"mx_moni_{safe}_*.json")), reverse=True)
        if files:
            with open(files[0], encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def extract_positions(j):
    """从 mx-moni 原始 JSON 的 data.posList 提取持仓(数值为原始单位, 元)。"""
    if not j:
        return []
    data = j.get("data", {})
    if not isinstance(data, dict):
        return []
    out = []
    for p in data.get("posList", []):
        out.append({
            "code": p.get("secCode", ""),
            "name": p.get("secName", ""),
            "qty": p.get("count", 0),
            "price": p.get("price", 0),
            "value": p.get("value", 0),
            "profit": p.get("profit", 0),
        })
    return out


def extract_balance(j):
    """从 mx-moni 原始 JSON 的 data 提取资金(原始单位, 元; initMoney=1000000=100万)。"""
    if not j:
        return {}
    data = j.get("data", {})
    if not isinstance(data, dict):
        return {}
    return {
        "total_assets": data.get("totalAssets", 0),
        "avail_balance": data.get("availBalance", 0),
        "pos_value": data.get("totalPosValue", 0),
        "nav": data.get("nav", 0),
        "init_money": data.get("initMoney", 0),
        "acc_name": data.get("accName", ""),
    }


def sync_once(account, dry=False):
    print(f"  🔄 同步远程账户 [{account}] ...")
    _call_mx("我的持仓")   # 触发 mx-moni 写 JSON
    _call_mx("查询资金")
    positions = extract_positions(_latest_json("我的持仓"))
    balance = extract_balance(_latest_json("查询资金"))

    snapshot = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account": account,
        "source": "mx_moni_remote_sync",
        "total_assets": balance.get("total_assets"),
        "avail_balance": balance.get("avail_balance"),
        "pos_value": balance.get("pos_value"),
        "nav": balance.get("nav"),
        "init_money": balance.get("init_money"),
        "positions": positions,
        "raw_pos_len": len(positions),
    }
    ta = balance.get("total_assets")
    ta_str = f"{ta/10000:.2f}万" if ta else "N/A"
    print(f"     持仓数: {len(positions)} | 总资产: {ta_str} | 可用: {balance.get('avail_balance')}")

    if dry:
        print("     [dry] 仅预览, 未写入本地")
        return snapshot

    d = os.path.join(RECORD_ROOT, account)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "contest_snapshot.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    print(f"  ✅ 快照已追加: {path}")
    return snapshot


def main():
    ap = argparse.ArgumentParser(description="龙虾大赛远程账户 只读同步(本地永久留存)")
    ap.add_argument("--account", default=DEFAULT_SIM, help="sim_ 账号ID")
    ap.add_argument("--dry", action="store_true", help="仅预览不写入")
    args = ap.parse_args()
    if not args.account.startswith("sim_"):
        print("  ⚠️ 仅支持 sim_ 开头的大赛账号同步")
        return
    if not os.environ.get("MX_APIKEY"):
        print("  ⚠️ 未检测到 MX_APIKEY 环境变量, 无法调用远程. 先 export MX_APIKEY=...")
        return
    sync_once(args.account, dry=args.dry)


if __name__ == "__main__":
    main()
