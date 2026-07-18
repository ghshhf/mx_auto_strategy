"""
local_records.py - 本地交易记录与权益曲线留存 (v6.5)

为什么需要:
  模拟盘每周刷新余额/仓位, 但咱们自己要保留连续记录:
    - 每周的选股逻辑 / 实际成交 / 收益曲线
    - 未来迁移到真实资金时, 这些就是宝贵的回测数据
    - 风控未来再说(用户明确: 不玩合约, 只选能长久存在的标的)

记录内容:
  1. trade_log.jsonl  - 每笔成交(日期/标的/方向/价格/数量/模式)
  2. equity_curve.jsonl - 每个交易日收盘后的总资产估算
  3. weekly_summary.json - 每周汇总(收益/排名估算/选股)

写入方式: append-only, 不依赖模拟盘刷新, 本地永久留存.

注意: 模拟盘"每周重置"不影响本地记录连续性 -- 我们记录的是
      "我们的策略在真实行情下的表现", 而非模拟盘账户余额.
"""
import os
import json
import time
from datetime import datetime

RECORD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "records")
TRADE_LOG = os.path.join(RECORD_DIR, "trade_log.jsonl")
EQUITY_LOG = os.path.join(RECORD_DIR, "equity_curve.jsonl")
WEEKLY_LOG = os.path.join(RECORD_DIR, "weekly_summary.json")


def _ensure_dir():
    os.makedirs(RECORD_DIR, exist_ok=True)


def log_trade(mode, code, name, side, price, qty, resp="", note=""):
    """
    记录一笔成交.
    mode: once/grid/rebalance/sell/reset
    side: BUY/SELL
    """
    _ensure_dir()
    rec = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "mode": mode,
        "code": code,
        "name": name,
        "side": side,
        "price": price,
        "qty": qty,
        "amount": round(price * qty, 2),
        "resp": str(resp)[:200],
        "note": note,
    }
    with open(TRADE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def log_equity(date, est_total, positions_value, cash_value, note=""):
    """记录每日权益估算(基于本地成本基准 + 实时价)."""
    _ensure_dir()
    rec = {
        "date": date,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "est_total": round(est_total, 2),
        "positions_value": round(positions_value, 2),
        "cash_value": round(cash_value, 2),
        "note": note,
    }
    with open(EQUITY_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def log_weekly(week_label, start_date, end_date, summary):
    """记录每周汇总. week_label=第17期第1周 等."""
    _ensure_dir()
    data = {}
    if os.path.exists(WEEKLY_LOG):
        try:
            with open(WEEKLY_LOG, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data[week_label] = {
        "start_date": start_date,
        "end_date": end_date,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **summary,
    }
    with open(WEEKLY_LOG, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def load_equity_curve():
    """读取权益曲线, 返回 list[dict]."""
    if not os.path.exists(EQUITY_LOG):
        return []
    out = []
    with open(EQUITY_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def load_trade_log():
    """读取成交记录, 返回 list[dict]."""
    if not os.path.exists(TRADE_LOG):
        return []
    out = []
    with open(TRADE_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def summary_text():
    """生成本地记录摘要(供报告/调试查看)."""
    eq = load_equity_curve()
    trades = load_trade_log()
    if not eq:
        return "本地记录: 暂无权益数据"
    first = eq[0]
    last = eq[-1]
    ret = (last["est_total"] / first["est_total"] - 1) * 100 if first["est_total"] else 0
    lines = [
        f"本地记录摘要 (连续不依赖模拟盘刷新):",
        f"  权益点数: {len(eq)}  | 成交笔数: {len(trades)}",
        f"  首记录: {first['date']} 资产≈{first['est_total']:.0f}",
        f"  末记录: {last['date']} 资产≈{last['est_total']:.0f}",
        f"  累计收益(本地估算): {ret:+.2f}%",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary_text())
