"""
manual_log.py - 手动交易记账系统 (v7.0, 账号体系)

核心: 支持「多账号」, 每个账号独立资金曲线, 互不串账.

两大账号类型:
  1) 自己实盘 (默认账号 real): 手动挂单买卖, 资金曲线永久沉淀, 永不清零.
  2) 模拟大赛 (sim_<龙虾账户号>): 龙虾炒股大赛盘, 每周按比赛规则重置到 100万,
     轨迹可独立追踪, 但清零逻辑与实盘完全隔离.

为什么需要账号体系:
  - 你自己的实战战绩要连续留存 (剧本书写者实力的量化沉淀)
  - 龙虾比赛每周清零, 但也要能读它的账号曲线 (对比实盘 vs 比赛)
  - 未来可能开多实盘子账户 (real / real2 ...) 各自从零起算

设计原则:
  - append-only, 每个账号一份 trades.jsonl + equity.jsonl, 本地永久留存
  - 账号ID即目录: records/<account_id>/trades.jsonl
  - 实盘账号禁止 reset; 仅 sim_* 账号可每周 reset (回到预设本金)
  - 极简: --account <id> 指定账号, 不写则用 real

用法:
  # 列出所有账号 + 余额快照
  python3 manual_log.py accounts

  # 实盘账号记一笔 (默认 real)
  python3 manual_log.py buy --code 600900 --name 长江电力 --price 28.5 --qty 100 --note "剧本:电力方向"
  python3 manual_log.py deposit --amount 50000 --note "期初本金5万"

  # 指定某个实盘子账号
  python3 manual_log.py buy --account real2 --code 512010 --name 医药ETF --price 0.62 --qty 5000

  # 龙虾大赛账号 (每周清零, 100万本金起)
  python3 manual_log.py buy --account sim_261984600000041416 --code 601398 --name 工商银行 --price 6.8 --qty 10000
  python3 manual_log.py summary --account sim_261984600000041416
  python3 manual_log.py reset  --account sim_261984600000041416   # 仅 sim_* 允许

  # 查看摘要 / 导出CSV
  python3 manual_log.py summary
  python3 manual_log.py export
"""

import os
import json
import argparse
from datetime import datetime

RECORD_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "records")

# 模拟大赛预设: 账号ID -> 初始本金(比赛规则)
SIM_ACCOUNTS = {
    "sim_261984600000041416": 1_000_000.0,   # 龙虾炒股大赛第17期账户
}

DEFAULT_ACCOUNT = "real"


# ---------------------------------------------------------------- 账号判定

def is_sim(account_id: str) -> bool:
    return account_id.startswith("sim_") or account_id in SIM_ACCOUNTS


def _acc_dir(account_id: str) -> str:
    return os.path.join(RECORD_ROOT, account_id)


def _trade_log(account_id: str) -> str:
    return os.path.join(_acc_dir(account_id), "trades.jsonl")


def _equity_log(account_id: str) -> str:
    return os.path.join(_acc_dir(account_id), "equity.jsonl")


def _ensure(account_id: str):
    os.makedirs(_acc_dir(account_id), exist_ok=True)


def list_accounts() -> list:
    """列出所有已存在账号 (扫描 records/ 子目录)."""
    if not os.path.isdir(RECORD_ROOT):
        return []
    out = []
    for name in sorted(os.listdir(RECORD_ROOT)):
        d = os.path.join(RECORD_ROOT, name)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "trades.jsonl")):
            out.append(name)
    # 把预设的 sim 账号也列出来(即使还没交易)
    for sim in SIM_ACCOUNTS:
        if sim not in out:
            out.append(sim)
    return out


# ---------------------------------------------------------------- 读写

def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def _cash_balance(account_id):
    trades = _read_jsonl(_trade_log(account_id))
    cash = 0.0
    for t in trades:
        if t["action"] == "deposit":
            cash += t["amount"]
        elif t["action"] == "buy":
            cash -= t["price"] * t["qty"]
        elif t["action"] == "sell":
            cash += t["price"] * t["qty"]
    return cash


def _holdings_value(account_id):
    trades = _read_jsonl(_trade_log(account_id))
    pos = {}
    for t in trades:
        if t["action"] in ("buy", "sell"):
            c = t["code"]
            p = pos.setdefault(c, {"qty": 0, "cost": 0.0, "name": t.get("name", c)})
            if t["action"] == "buy":
                p["qty"] += t["qty"]
                p["cost"] += t["price"] * t["qty"]
            else:
                if p["qty"] > 0:
                    avg = p["cost"] / p["qty"] if p["qty"] else 0
                    p["cost"] -= avg * t["qty"]
                p["qty"] -= t["qty"]
    return {k: v for k, v in pos.items() if v["qty"] > 0}


# ---------------------------------------------------------------- 核心写账

def log_trade(account_id, action, code="", name="", price=0.0, qty=0, amount=0.0, note=""):
    _ensure(account_id)
    rec = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account": account_id,
        "action": action,
        "code": code, "name": name,
        "price": price, "qty": qty, "amount": amount,
        "note": note,
    }
    with open(_trade_log(account_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    cash = _cash_balance(account_id)
    holdings = _holdings_value(account_id)
    equity = {"ts": rec["ts"], "account": account_id, "cash": round(cash, 2),
              "positions": holdings, "note": note}
    with open(_equity_log(account_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(equity, ensure_ascii=False) + "\n")
    return rec, cash, holdings


def reset_sim(account_id):
    """仅 sim_* 账号可 reset: 清掉交易流水, 写入一条期初本金 deposit (比赛规则)."""
    if not is_sim(account_id):
        raise PermissionError(f"账号 {account_id} 不是模拟大赛账号, 禁止清零 (实盘战绩永久保留)")
    principal = SIM_ACCOUNTS.get(account_id, 1_000_000.0)
    _ensure(account_id)
    # 截断两个文件
    open(_trade_log(account_id), "w", encoding="utf-8").close()
    open(_equity_log(account_id), "w", encoding="utf-8").close()
    # 写入重置后的期初本金
    rec = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account": account_id,
        "action": "deposit",
        "code": "", "name": "【比赛重置·期初本金】",
        "price": 0, "qty": 0, "amount": principal,
        "note": "每周重置: 回到比赛初始本金",
    }
    with open(_trade_log(account_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    eq = {"ts": rec["ts"], "account": account_id, "cash": principal,
          "positions": {}, "note": rec["note"]}
    with open(_equity_log(account_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(eq, ensure_ascii=False) + "\n")
    return principal


# ---------------------------------------------------------------- 命令实现

def _resolve_account(args):
    return getattr(args, "account", None) or DEFAULT_ACCOUNT


def cmd_buy(args):
    acc = _resolve_account(args)
    rec, cash, holdings = log_trade(acc, "buy", args.code, args.name, args.price, args.qty, note=args.note)
    print(f"  ✅[{acc}] 记买入: {args.name}({args.code}) {args.qty}@{args.price} = {args.price*args.qty:.2f}元")
    print(f"  💰 当前现金: {cash:.2f} | 持仓: {len(holdings)}只")


def cmd_sell(args):
    acc = _resolve_account(args)
    rec, cash, holdings = log_trade(acc, "sell", args.code, args.name, args.price, args.qty, note=args.note)
    print(f"  ✅[{acc}] 记卖出: {args.name}({args.code}) {args.qty}@{args.price} = {args.price*args.qty:.2f}元")
    print(f"  💰 当前现金: {cash:.2f} | 持仓: {len(holdings)}只")


def cmd_deposit(args):
    acc = _resolve_account(args)
    rec, cash, holdings = log_trade(acc, "deposit", amount=args.amount, note=args.note)
    label = "存入" if args.amount > 0 else "取出"
    print(f"  ✅[{acc}] 记资金: {label} {abs(args.amount):.2f}元")
    print(f"  💰 当前现金: {cash:.2f}")


def cmd_summary(args):
    acc = _resolve_account(args)
    trades = _read_jsonl(_trade_log(acc))
    if not trades:
        tag = "模拟大赛" if is_sim(acc) else "实盘"
        print(f"  （账号 [{acc}] ({tag}) 暂无记录）")
        return
    cash = _cash_balance(acc)
    holdings = _holdings_value(acc)
    deposits = sum(t["amount"] for t in trades if t["action"] == "deposit")
    invested = sum(t["price"]*t["qty"] for t in trades if t["action"] == "buy")
    tag = "模拟大赛(每周清零)" if is_sim(acc) else "实盘(永久沉淀)"
    net_asset = cash + sum(v["cost"] for v in holdings.values())  # 成本口径净资产(未含浮动盈亏)
    print(f"  📊 账号 [{acc}] 摘要  ({tag})")
    print(f"     总存入:   {deposits:.2f}元")
    print(f"     总买入额: {invested:.2f}元")
    print(f"     当前现金: {cash:.2f}元")
    print(f"     持仓成本: {sum(v['cost'] for v in holdings.values()):.2f}元")
    print(f"     成本净资产:{net_asset:.2f}元")
    print(f"     当前持仓: {len(holdings)}只")
    for c, v in holdings.items():
        print(f"       - {v['name']}({c}): {v['qty']}股, 成本{v['cost']:.2f}元")
    print(f"     交易笔数: {len(trades)}")


def cmd_accounts(args):
    accs = list_accounts()
    if not accs:
        print("  （暂无账号，记第一笔交易即自动创建 real 账号）")
        return
    print(f"  📒 账号列表 ({len(accs)} 个):")
    for acc in accs:
        trades = _read_jsonl(_trade_log(acc))
        if trades:
            cash = _cash_balance(acc)
            n = len(trades)
        else:
            cash, n = 0.0, 0
        tag = "模拟大赛(每周清零)" if is_sim(acc) else "实盘(永久沉淀)"
        print(f"    - [{acc}]  {tag}  现金:{cash:.2f}元  笔数:{n}")


def cmd_reset(args):
    acc = _resolve_account(args)
    try:
        principal = reset_sim(acc)
        print(f"  🔄[{acc}] 已重置回比赛本金 {principal:.2f}元 (仅模拟大赛账号允许)")
    except PermissionError as e:
        print(f"  ⛔ {e}")


def cmd_export(args):
    acc = _resolve_account(args)
    trades = _read_jsonl(_trade_log(acc))
    out_dir = _acc_dir(acc)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "trades_export.csv")
    with open(out, "w", encoding="utf-8") as f:
        f.write("时间,账号,动作,代码,名称,价格,数量,金额,备注\n")
        for t in trades:
            amt = t.get("amount") or (t.get("price", 0) * t.get("qty", 0))
            f.write(f"{t['ts']},{t['account']},{t['action']},{t['code']},{t['name']},{t['price']},{t['qty']},{amt:.2f},{t['note']}\n")
    print(f"  📄 导出: {out} ({len(trades)}笔)")


# ---------------------------------------------------------------- 入口

def _attach_account(p):
    """给每个子命令挂上 --account (默认 real), 支持 buy --account xxx 这种自然写法."""
    p.add_argument("--account", default=DEFAULT_ACCOUNT,
                   help="账号ID (实盘默认real; 龙虾大赛=sim_261984600000041416)")
    return p


def build_parser():
    ap = argparse.ArgumentParser(description="手动交易记账系统 v7.0 (账号体系)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = _attach_account(sub.add_parser("buy"))
    b.add_argument("--code", required=True); b.add_argument("--name", default="")
    b.add_argument("--price", type=float, required=True); b.add_argument("--qty", type=float, required=True)
    b.add_argument("--note", default=""); b.set_defaults(func=cmd_buy)

    s = _attach_account(sub.add_parser("sell"))
    s.add_argument("--code", required=True); s.add_argument("--name", default="")
    s.add_argument("--price", type=float, required=True); s.add_argument("--qty", type=float, required=True)
    s.add_argument("--note", default=""); s.set_defaults(func=cmd_sell)

    d = _attach_account(sub.add_parser("deposit"))
    d.add_argument("--amount", type=float, required=True); d.add_argument("--note", default="")
    d.set_defaults(func=cmd_deposit)

    sm = _attach_account(sub.add_parser("summary")); sm.set_defaults(func=cmd_summary)
    ac = _attach_account(sub.add_parser("accounts")); ac.set_defaults(func=cmd_accounts)
    rs = _attach_account(sub.add_parser("reset")); rs.set_defaults(func=cmd_reset)
    ex = _attach_account(sub.add_parser("export")); ex.set_defaults(func=cmd_export)
    return ap


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
