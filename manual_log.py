"""
manual_log.py - 手动交易记账系统 (v7.2, 账号体系·本地永久留存·实时估值+曲线+回撤)

核心: 支持「多账号」, 每个账号独立资金曲线, 互不串账.

两类账号来源 (仅做标签区分, 行为完全一致 —— 都永久留存, 本地无清零):
  1) 自己实盘 (默认账号 real / real2 ...): 你手动挂单买卖的真实账户.
  2) 模拟大赛 (sim_<龙虾账户号>): 龙虾炒股大赛盘.
     ⚠️ 大赛的清零是【远程比赛平台】自己干的, 与本地无关.
        本地只负责【忠实记录】: 远程怎么清零是它的事, 咱们本地账本永远留着,
        这样未来回测才有完整依据 (知道某周远程归零前咱们在哪、归零后咱们又怎么走).

设计铁律 (用户明确):
  - 本地【无自动清零机制】. 任何账号都不会被系统自动清空.
  - 只有一种例外: 你亲口让 AI 「删掉某个账号」(delete 命令, 带二次确认),
    且即使如此, 主实盘账号 real 也禁止删除 (最后防线).
  - append-only: 每个账号一份 trades.jsonl + equity.jsonl, 本地永久留存.
  - 账号ID即目录: records/<account_id>/trades.jsonl

用法:
  # 列出所有账号 + 余额快照
  python3 manual_log.py accounts

  # 实盘账号记一笔 (默认 real)
  python3 manual_log.py buy --code 600900 --name 长江电力 --price 28.5 --qty 100 --note "剧本:电力方向"
  python3 manual_log.py deposit --amount 50000 --note "期初本金5万"

  # 指定某个实盘子账号
  python3 manual_log.py buy --account real2 --code 512010 --name 医药ETF --price 0.62 --qty 5000

  # 龙虾大赛账号 (本地永久记录远程的每一笔, 远程清零不影响本地)
  python3 manual_log.py buy --account sim_261984600000041416 --code 601398 --name 工商银行 --price 6.8 --qty 10000
  python3 manual_log.py summary --account sim_261984600000041416

  # 查看摘要 / 导出CSV
  python3 manual_log.py summary
  python3 manual_log.py export

  # 仅当你亲口要求删账号时才用 (二次确认; real 禁止删):
  python3 manual_log.py delete --account real2 --confirm
"""

import os
import json
import argparse
import shutil
from datetime import datetime

RECORD_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "records")

# 仅作「来源标签」: 名字带 sim_ 即视为模拟大赛账号 (来源标记, 不含本金/不清零语义)
SIM_PREFIX = "sim_"

# 主实盘账号 (最后防线: 禁止 delete)
PROTECTED_ACCOUNTS = {"real"}

DEFAULT_ACCOUNT = "real"


# ---------------------------------------------------------------- 账号判定

def is_sim(account_id: str) -> bool:
    """仅用于显示标签: 是否来源=模拟大赛. 不影响任何记账/留存行为."""
    return account_id.startswith(SIM_PREFIX)


def _acc_dir(account_id: str) -> str:
    return os.path.join(RECORD_ROOT, account_id)


def _trade_log(account_id: str) -> str:
    return os.path.join(_acc_dir(account_id), "trades.jsonl")


def _equity_log(account_id: str) -> str:
    return os.path.join(_acc_dir(account_id), "equity.jsonl")


def _ensure(account_id: str):
    os.makedirs(_acc_dir(account_id), exist_ok=True)


def list_accounts() -> list:
    """列出所有已存在账号 (扫描 records/ 子目录, 按名称排序)."""
    if not os.path.isdir(RECORD_ROOT):
        return []
    out = []
    for name in sorted(os.listdir(RECORD_ROOT)):
        d = os.path.join(RECORD_ROOT, name)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "trades.jsonl")):
            out.append(name)
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
    tag = "模拟大赛(远程清零·本地留存)" if is_sim(acc) else "实盘(本地记录)"
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
        tag = "模拟大赛(远程清零·本地留存)" if is_sim(acc) else "实盘(本地记录)"
        print(f"    - [{acc}]  {tag}  现金:{cash:.2f}元  笔数:{n}")


def cmd_delete(args):
    """仅当用户亲口要求删账号时调用. 二次确认 + 保护主实盘账号."""
    acc = _resolve_account(args)
    if not args.confirm:
        print(f"  ⚠️ 删除账号 [{acc}] 是破坏性操作, 需在命令后加 --confirm 二次确认.")
        print(f"     例如: python3 manual_log.py delete --account {acc} --confirm")
        return
    if acc in PROTECTED_ACCOUNTS:
        print(f"  ⛔ 账号 [{acc}] 是受保护的主实盘账号, 禁止删除 (本地永久留存的最后防线).")
        return
    d = _acc_dir(acc)
    if not os.path.isdir(d):
        print(f"  （账号 [{acc}] 不存在, 无需删除）")
        return
    shutil.rmtree(d)
    print(f"  🗑️ 已删除账号 [{acc}] 全部本地记录. (此操作不可恢复, 仅在你要求时执行)")


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


# ---------------------------------------------------------------- 实时估值 / 曲线 / 回撤

def _is_crypto_account(acc, holdings):
    """判断该账号/持仓是否属加密资产 (账号名含crypto, 或持仓code为加密符号)."""
    if "crypto" in acc.lower():
        return True
    crypto_syms = {"btc", "eth", "sol", "bnb", "xrp", "ada", "doge", "dot", "matic",
                   "avax", "link", "ton", "shib", "ltc", "trx", "uni", "atom", "near",
                   "apt", "arb", "op", "fil", "usdt", "usdc"}
    return any(c.lower() in crypto_syms for c in holdings.keys())


def _current_equity_snapshot(acc):
    """基于最新市价, 计算: 现金 + 各持仓市值 + 浮动盈亏. 返回 dict."""
    cash = _cash_balance(acc)
    holdings = _holdings_value(acc)   # {code: {qty, cost, name}}
    codes = list(holdings.keys())
    # 拉实时价 (非交易时段可能为空, 则用成本回填)
    rt = {}
    if codes:
        try:
            if _is_crypto_account(acc, holdings):
                import crypto_data
                # 加密: 用 crypto_data 全币种行情 (CoinGecko主/Binance/OKX备)
                rt = {k.upper(): {"price": v} for k, v in crypto_data.get_prices(codes).items()}
            else:
                import market_data
                rt = market_data.get_realtime(codes)
        except Exception:
            rt = {}
    market_val = 0.0
    float_pnl = 0.0
    detail = []
    for c, v in holdings.items():
        price = (rt.get(c, {}) or {}).get("price") or (rt.get(c.upper(), {}).get("price")
                   if c.upper() in rt else None) or (v["cost"] / v["qty"] if v["qty"] else 0)
        mv = price * v["qty"]
        pnl = (price - (v["cost"] / v["qty"] if v["qty"] else 0)) * v["qty"]
        market_val += mv
        float_pnl += pnl
        detail.append({"code": c, "name": v["name"], "qty": v["qty"],
                       "cost": round(v["cost"], 2), "price": round(price, 3),
                       "market_value": round(mv, 2), "float_pnl": round(pnl, 2)})
    total = cash + market_val
    return {"cash": cash, "market_val": market_val, "float_pnl": float_pnl,
            "total": total, "detail": detail}


def cmd_mark(args):
    """实时市值估值 (成本口径 -> 市价口径)."""
    acc = _resolve_account(args)
    trades = _read_jsonl(_trade_log(acc))
    if not trades:
        print(f"  （账号 [{acc}] 暂无记录）")
        return
    snap = _current_equity_snapshot(acc)
    tag = "模拟大赛(远程清零·本地留存)" if is_sim(acc) else "实盘(本地记录)"
    print(f"  💹 账号 [{acc}] 实时估值 ({tag})")
    print(f"     当前现金:   {snap['cash']:.2f}元")
    print(f"     持仓市值:   {snap['market_val']:.2f}元")
    print(f"     浮动盈亏:   {snap['float_pnl']:+.2f}元")
    print(f"     ─────────────────────")
    print(f"     总净值:     {snap['total']:.2f}元")
    if snap["detail"]:
        print(f"     持仓明细:")
        for d in snap["detail"]:
            unit = "份" if "crypto" in acc.lower() or d["code"].lower() in ("btc","eth","sol","bnb","xrp","usdt","usdc") else "股"
            print(f"       - {d['name']}({d['code']}): {d['qty']}{unit} @现价{d['price']} = {d['market_value']:.2f}元  浮盈{d['float_pnl']:+.2f}")


def cmd_curve(args):
    """导出日期->净值 序列 (基于 equity.jsonl 快照, 用成本口径; 若想市价口径用 mark 频率拉)."""
    acc = _resolve_account(args)
    eqs = _read_jsonl(_equity_log(acc))
    if not eqs:
        print(f"  （账号 [{acc}] 暂无权益快照, 先记几笔交易）")
        return
    out_dir = _acc_dir(acc)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "equity_curve_export.csv")
    with open(out, "w", encoding="utf-8") as f:
        f.write("时间,账号,现金,持仓成本,成本净资产\n")
        for e in eqs:
            pos_val = sum(v.get("cost", 0) for v in e.get("positions", {}).values())
            net = e.get("cash", 0) + pos_val
            f.write(f"{e['ts']},{e['account']},{e.get('cash',0):.2f},{pos_val:.2f},{net:.2f}\n")
    # 控制台也打印首尾收益
    first, last = eqs[0], eqs[-1]
    fp = first.get("cash", 0) + sum(v.get("cost", 0) for v in first.get("positions", {}).values())
    lp = last.get("cash", 0) + sum(v.get("cost", 0) for v in last.get("positions", {}).values())
    ret = (lp / fp - 1) * 100 if fp else 0
    print(f"  📈 曲线导出: {out} ({len(eqs)}个快照)")
    print(f"     首快照净值≈{fp:.2f} -> 末快照净值≈{lp:.2f}  累计{ret:+.2f}%")


def cmd_drawdown(args):
    """回撤闸: 读权益曲线, 算最大回撤/周回撤, 超阈输出降级建议."""
    acc = _resolve_account(args)
    eqs = _read_jsonl(_equity_log(acc))
    if len(eqs) < 2:
        print(f"  （账号 [{acc}] 快照不足, 无法计算回撤）")
        return
    # 用成本净资产序列
    vals = []
    for e in eqs:
        pos_val = sum(v.get("cost", 0) for v in e.get("positions", {}).values())
        vals.append((e["ts"], e.get("cash", 0) + pos_val))
    peak = vals[0][1]; max_dd = 0.0; max_dd_at = ""
    for ts, v in vals:
        if v > peak:
            peak = v
        dd = (v - peak) / peak if peak else 0
        if dd < max_dd:
            max_dd = dd; max_dd_at = ts
    thr = args.threshold / 100 if hasattr(args, "threshold") else 0.05
    print(f"  🔻 账号 [{acc}] 回撤分析")
    print(f"     峰值净值: {peak:.2f} | 最大回撤: {max_dd*100:.2f}% (发生于 {max_dd_at[:10]})")
    if max_dd <= -thr:
        print(f"  ⚠️ 最大回撤已突破阈值 -{thr*100:.0f}% -> 建议: 切换全防御 / 降低进攻暴露 / 提升现金比")
    else:
        print(f"  ✅ 回撤在阈值 -{thr*100:.0f}% 以内, 维持当前市况仓位")


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
    dl = _attach_account(sub.add_parser("delete"))
    dl.add_argument("--confirm", action="store_true", help="二次确认(必须显式加)")
    dl.set_defaults(func=cmd_delete)
    ex = _attach_account(sub.add_parser("export")); ex.set_defaults(func=cmd_export)
    mk = _attach_account(sub.add_parser("mark")); mk.set_defaults(func=cmd_mark)
    cv = _attach_account(sub.add_parser("curve")); cv.set_defaults(func=cmd_curve)
    dd = _attach_account(sub.add_parser("drawdown"))
    dd.add_argument("--threshold", type=float, default=5.0, help="回撤告警阈值(%, 默认5)")
    dd.set_defaults(func=cmd_drawdown)
    return ap


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
