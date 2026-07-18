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
import subprocess
import argparse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
MX_MONI_PY = "/root/.codebuddy/skills/mx-moni/mx_moni.py"
RECORD_ROOT = os.path.join(HERE, "records")

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


def parse_positions(text):
    """从 mx-moni 返回的持仓文本里尽力解析出 posList 关键字段."""
    # mx_moni 可能直接返回 JSON 或 文本表格, 这里做宽松解析
    positions = []
    # 尝试找 JSON 中的 posList
    try:
        # 截取可能的 JSON 段
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            j = json.loads(text[start:end])
            data = j.get("data", j)
            pl = data.get("posList", [])
            for p in pl:
                positions.append({
                    "code": p.get("secCode", ""),
                    "name": p.get("secName", ""),
                    "qty": p.get("count", 0),
                    "price": p.get("price", 0),
                    "value": p.get("value", 0),
                    "profit": p.get("profit", 0),
                })
            return positions
    except Exception:
        pass
    return positions


def parse_balance(text):
    """解析资金/净值文本 -> totalAssets/availBalance."""
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            j = json.loads(text[start:end])
            data = j.get("data", j)
            return {
                "total_assets": data.get("totalAssets", 0) / 1000.0,  # 厘->元
                "avail_balance": data.get("availBalance", 0) / 1000.0,
                "pos_value": data.get("totalPosValue", 0) / 1000.0,
                "nav": data.get("nav", 0),
                "init_money": data.get("initMoney", 0) / 1000.0,
                "acc_name": data.get("accName", ""),
            }
    except Exception:
        pass
    return {}


def sync_once(account, dry=False):
    print(f"  🔄 同步远程账户 [{account}] ...")
    pos_text = _call_mx("我的持仓")
    bal_text = _call_mx("查询资金")
    positions = parse_positions(pos_text)
    balance = parse_balance(bal_text)

    snapshot = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account": account,
        "source": "mx_moni_remote_sync",
        "total_assets": balance.get("total_assets"),
        "avail_balance": balance.get("avail_balance"),
        "pos_value": balance.get("pos_value"),
        "nav": balance.get("nav"),
        "positions": positions,
        "raw_pos_len": len(positions),
    }
    print(f"     持仓数: {len(positions)} | 总资产: {balance.get('total_assets')} | 可用: {balance.get('avail_balance')}")

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
