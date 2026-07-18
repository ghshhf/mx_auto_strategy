"""
manual_log.py - 手动实盘记录入口 (v6.8)

用途:
  你手动挂单买卖(自己的实盘账户, 不走API), 用这个脚本把每笔交易记进本地资金曲线.
  比赛盘每周清零, 但咱们自己的实战战绩要连续留存 —— 这是"剧本书写者"实力的量化沉淀.

设计原则:
  - 比赛盘(auto_trader.py 自动写) 和 你自己实盘(本脚本手动写) 分开存, 不混.
  - append-only, 本地永久留存, 不依赖任何模拟盘刷新.
  - 极简: 一行命令记一笔, 资金曲线自动累计.

用法:
  # 记一笔买入
  python3 manual_log.py buy --code 600900 --name 长江电力 --price 28.5 --qty 100 --note "剧本:电力方向,防御端"

  # 记一笔卖出
  python3 manual_log.py sell --code 512010 --name 医药ETF --price 0.62 --qty 5000 --note "医疗反弹止盈"

  # 记一笔资金转入(期初本金/加仓)
  python3 manual_log.py deposit --amount 50000 --note "期初本金5万"

  # 查看资金曲线摘要
  python3 manual_log.py summary

  # 导出CSV(给Excel/画图用)
  python3 manual_log.py export

记录文件:
  records/manual_trades.jsonl  - 每笔手动交易
  records/manual_equity.jsonl  - 每个动作后的资产快照
"""
import os
import json
import argparse
from datetime import datetime

RECORD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "records")
TRADE_LOG = os.path.join(RECORD_DIR, "manual_trades.jsonl")
EQUITY_LOG = os.path.join(RECORD_DIR, "manual_equity.jsonl")


def _ensure():
    os.makedirs(RECORD_DIR, exist_ok=True)


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


def _cash_balance():
    """根据存款+买入支出-卖出收入, 推算当前现金余额."""
    trades = _read_jsonl(TRADE_LOG)
    cash = 0.0
    for t in trades:
        if t["action"] == "deposit":
            cash += t["amount"]
        elif t["action"] == "buy":
            cash -= t["price"] * t["qty"]
        elif t["action"] == "sell":
            cash += t["price"] * t["qty"]
    return cash


def _holdings_value():
    """根据买卖流水, 推算当前持仓(数量×最新手动价需另记, 这里只算成本基准)."""
    trades = _read_jsonl(TRADE_LOG)
    pos = {}  # code -> {qty, cost}
    for t in trades:
        if t["action"] in ("buy", "sell"):
            c = t["code"]
            p = pos.setdefault(c, {"qty": 0, "cost": 0.0, "name": t.get("name", c)})
            if t["action"] == "buy":
                p["qty"] += t["qty"]
                p["cost"] += t["price"] * t["qty"]
            else:
                if p["qty"] > 0:
                    p["cost"] -= t["price"] * t["qty"] * (p["cost"] / (p["qty"] + t["qty"])) if (p["qty"] + t["qty"]) else 0
                p["qty"] -= t["qty"]
    return {k: v for k, v in pos.items() if v["qty"] > 0}


def log_trade(action, code="", name="", price=0.0, qty=0, amount=0.0, note=""):
    _ensure()
    rec = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "code": code, "name": name,
        "price": price, "qty": qty, "amount": amount,
        "note": note,
    }
    with open(TRADE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 写资产快照
    cash = _cash_balance()
    holdings = _holdings_value()
    equity = {"ts": rec["ts"], "cash": round(cash, 2), "positions": holdings, "note": note}
    with open(EQUITY_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(equity, ensure_ascii=False) + "\n")
    return rec, cash, holdings


def cmd_buy(args):
    rec, cash, holdings = log_trade("buy", args.code, args.name, args.price, args.qty, note=args.note)
    print(f"  ✅ 记买入: {args.name}({args.code}) {args.qty}@{args.price} = {args.price*args.qty:.2f}元")
    print(f"  💰 当前现金: {cash:.2f} | 持仓: {len(holdings)}只")


def cmd_sell(args):
    rec, cash, holdings = log_trade("sell", args.code, args.name, args.price, args.qty, note=args.note)
    print(f"  ✅ 记卖出: {args.name}({args.code}) {args.qty}@{args.price} = {args.price*args.qty:.2f}元")
    print(f"  💰 当前现金: {cash:.2f} | 持仓: {len(holdings)}只")


def cmd_deposit(args):
    rec, cash, holdings = log_trade("deposit", amount=args.amount, note=args.note)
    print(f"  ✅ 记资金: {'存入' if args.amount>0 else '取出'} {abs(args.amount):.2f}元")
    print(f"  💰 当前现金: {cash:.2f}")


def cmd_summary(args):
    trades = _read_jsonl(TRADE_LOG)
    if not trades:
        print("  （暂无手动记录）")
        return
    cash = _cash_balance()
    holdings = _holdings_value()
    deposits = sum(t["amount"] for t in trades if t["action"] == "deposit")
    invested = sum(t["price"]*t["qty"] for t in trades if t["action"]=="buy")
    print(f"  📊 手动实盘摘要")
    print(f"     总存入:   {deposits:.2f}元")
    print(f"     总买入额: {invested:.2f}元")
    print(f"     当前现金: {cash:.2f}元")
    print(f"     当前持仓: {len(holdings)}只")
    for c, v in holdings.items():
        print(f"       - {v['name']}({c}): {v['qty']}股, 成本{v['cost']:.2f}元")
    print(f"     交易笔数: {len(trades)}")


def cmd_export(args):
    trades = _read_jsonl(TRADE_LOG)
    out = os.path.join(RECORD_DIR, "manual_trades.csv")
    with open(out, "w", encoding="utf-8") as f:
        f.write("时间,动作,代码,名称,价格,数量,金额,备注\n")
        for t in trades:
            amt = t.get("amount") or (t.get("price",0)*t.get("qty",0))
            f.write(f"{t['ts']},{t['action']},{t['code']},{t['name']},{t['price']},{t['qty']},{amt:.2f},{t['note']}\n")
    print(f"  📄 导出: {out} ({len(trades)}笔)")


def main():
    ap = argparse.ArgumentParser(description="手动实盘记录 (剧本书写者实战沉淀)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("buy"); b.add_argument("--code", required=True); b.add_argument("--name", default="")
    b.add_argument("--price", type=float, required=True); b.add_argument("--qty", type=float, required=True)
    b.add_argument("--note", default=""); b.set_defaults(func=cmd_buy)
    s = sub.add_parser("sell"); s.add_argument("--code", required=True); s.add_argument("--name", default="")
    s.add_argument("--price", type=float, required=True); s.add_argument("--qty", type=float, required=True)
    s.add_argument("--note", default=""); s.set_defaults(func=cmd_sell)
    d = sub.add_parser("deposit"); d.add_argument("--amount", type=float, required=True); d.add_argument("--note", default=""); d.set_defaults(func=cmd_deposit)
    sub.add_parser("summary").set_defaults(func=cmd_summary)
    sub.add_parser("export").set_defaults(func=cmd_export)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
