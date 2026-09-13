"""台阶审计：把「实测流通量的周度台阶」逐条导出，并对有代表性的币做月度绝对增量拆解。

用途：net issuance 的「实测年化」可能被解锁/释放/供应商回修污染。本脚本把污染源逐条落盘，
      使报告里「哪些台阶是真实供给、哪些是口径变动」的判定可被独立复核。

输出 markets/crypto/out/supply_steps_audit.csv
字段：coin, window, date, weekly_pct_change, circ_before, circ_after
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CDIR = ROOT / "markets" / "crypto" / "data" / "cmc_history"
OUT = ROOT / "markets" / "crypto" / "out" / "supply_steps_audit.csv"

WINDOWS = {"近1年": 365, "近2年": 730, "近3年": 1095}
THRESH = 0.04


def circ_series(sym: str) -> pd.Series:
    d = json.loads((CDIR / f"{sym}.json").read_text(encoding="utf-8"))
    rows = [(pd.to_datetime(int(ts), unit="s"), v[2] / v[0]) for ts, v in d["points"].items()]
    s = pd.DataFrame(rows, columns=["t", "circ"]).set_index("t").sort_index()["circ"]
    return s


def main() -> None:
    recs = []
    for p in sorted(CDIR.glob("*.json")):
        sym = p.stem
        s = circ_series(sym)
        if s.empty:
            continue
        end = s.index[-1]
        for win, days in WINDOWS.items():
            seg = s[s.index >= end - pd.Timedelta(days=days)]
            if len(seg) < 8:
                continue
            w = seg.resample("W").last().dropna()
            ch = w.pct_change().dropna()
            for dt, v in ch[ch.abs() > THRESH].items():
                recs.append(dict(coin=sym, window=win, date=dt.date(),
                                 weekly_pct_change=round(float(v) * 100, 2),
                                 circ_before=float(w.shift(1)[dt]),
                                 circ_after=float(w[dt])))
    df = pd.DataFrame(recs).sort_values(["coin", "date"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"已写出 {OUT.relative_to(ROOT)}  共 {len(df)} 条台阶")
    print(df.groupby("coin").size().sort_values(ascending=False).head(12).to_string())


if __name__ == "__main__":
    main()
