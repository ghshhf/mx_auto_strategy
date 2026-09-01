"""机构研报子模块 CLI 入口。

5 个子命令：
    fetch    --coins BTC,ETH,SOL     联网抓取，把新记录 append 到本地知识库
    analyze  --coins BTC,ETH,SOL     交叉聚合：覆盖数 / 机构 / 分桶目标价上下区间
    latest   --coin BTC [--days 180] 近 N 天研报摘要 + 最新 10 条
    report   --coins BTC,ETH,SOL     完整 Markdown 报告（stdout + 可选 --out <path>）
    add      --institution 渣打 --coin BTC --target-price 150000 --pub-date 2024-07-15
             [--rating bullish] [--horizon-months 18] [--target-date 2025-12-31]
             [--source-url https://...] [--excerpt "..."]
             手工录入一条研报
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# 模块根路径：markets/crypto/research/ 相对文件位置
MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_KB_PATH = MODULE_DIR / "kb" / "coverage.jsonl"

# ── 终端格式化（纯 ASCII，避免 Windows 颜色问题）────────────────
def _h1(text: str) -> str: return f"\n{'=' * 72}\n  {text}\n{'=' * 72}"
def _h2(text: str) -> str: return f"\n  ─ {text} {'─' * max(2, 64 - len(text))}"
def _fmt_price(p) -> str:
    if p is None:
        return "-"
    try:
        p = float(p)
    except Exception:
        return "-"
    if p >= 1000:
        return f"${p:,.0f}"
    if p >= 1:
        return f"${p:,.2f}"
    return f"${p:,.4f}"


def _load_dependencies():
    """一次性加载内部模块 + 种子数据 + 3 源列表。"""
    from .seeds import get_seed_records
    from .sources import get_all_sources
    from .aggregate import analyze_coins, latest, build_report
    return {
        "get_seed_records": get_seed_records,
        "get_all_sources": get_all_sources,
        "analyze_coins": analyze_coins,
        "latest": latest,
        "build_report": build_report,
    }


def _split_coins(arg: str) -> list[str]:
    return [c.strip() for c in (arg or "").split(",") if c.strip()]


# ══════════════════ CLI handlers ════════════════════════════════

def cmd_fetch(args, deps):
    coins = _split_coins(args.coins)
    if not coins:
        print("[fetch] 请用 --coins 指定币列表，如 BTC,ETH,SOL", file=sys.stderr)
        return 2
    sources = deps["get_all_sources"]()
    from .sources.base import fetch_all_sources, append_jsonl_atomic
    scraped = fetch_all_sources(coins, sources)
    kb = os.environ.get("RESEARCH_KB", str(args.kb))
    n = append_jsonl_atomic(kb, scraped)
    print(_h1("机构研报抓取 fetch 结果"))
    print(f"  目标币:         {coins}")
    print(f"  抓取源数:       {len(sources)} (Binance Research, OKX Insights, CoinGecko desc)")
    print(f"  抓取新记录:     {n} 条（去重后写入 kb）")
    print(f"  知识库路径:     {kb}")
    if n > 0:
        insts = sorted({r["institution"] for r in scraped})
        print(f"  命中机构:       {', '.join(insts[:20])}{'…' if len(insts) > 20 else ''}")
    return 0


def cmd_analyze(args, deps):
    coins = _split_coins(args.coins)
    if not coins:
        print("[analyze] 请用 --coins 指定币列表", file=sys.stderr)
        return 2
    seeds = deps["get_seed_records"]()
    kb = os.environ.get("RESEARCH_KB", str(args.kb))
    # 可选：把抓取源也跑一次并入（默认 analyze 只读本地，避免卡顿；--with-scrape 再跑）
    scraped = None
    if args.with_scrape:
        from .sources.base import fetch_all_sources
        scraped = fetch_all_sources(coins, deps["get_all_sources"]())

    current = _parse_current_prices(args.current)
    results = deps["analyze_coins"](coins, seeds, kb, scraped, current_prices=current)

    if args.json:
        print(json.dumps({"coins": results}, ensure_ascii=False, indent=2))
        return 0

    print(_h1(f"机构研报交叉聚合 analyze | {datetime.now().date().isoformat()}"))
    for r in results:
        print(_h2(f"{r['coin']} — 覆盖机构 {r['coverage_count']} 家"))
        if r.get("note"):
            print(f"    Note: {r['note']}")
            continue
        insts = r["institutions"]
        print(f"    机构列表 ({len(insts)}):  {', '.join(insts)}")
        tier = r["tier_distribution"]
        print(f"    Tier 分布:  " + ", ".join(f"{k}={v}" for k, v in sorted(tier.items())))
        print(f"    记录总数:   {r['total_records']}")
        print(f"    {'Horizon 分桶':<14}  {'Count':>5}  {'Min':>10}  {'Max':>10}  "
              f"{'Median':>10}  {'Mean':>10}  {'分歧':>6}  {'上行%':>6}")
        for name, b in r["target_price_ranges"].items():
            c = b.get("count", 0)
            if c == 0:
                print(f"    {name:<14}  {0:>5}  {'-':>10}  {'-':>10}  "
                      f"{'<无数据>':>10}")
                continue
            div = b.get("divergence_ratio", "-")
            up = b.get("upside_vs_current_pct", "-")
            print(f"    {name:<14}  {c:>5}  {_fmt_price(b['min']):>10}  {_fmt_price(b['max']):>10}  "
                  f"{_fmt_price(b['median']):>10}  {_fmt_price(b['mean']):>10}  "
                  f"{str(div):>6}  {f'{up:+.1f}%' if isinstance(up, (int, float)) else '-':>6}")
    print(_h2("完成"))
    return 0


def cmd_latest(args, deps):
    if not args.coin:
        print("[latest] 请用 --coin 指定币", file=sys.stderr)
        return 2
    seeds = deps["get_seed_records"]()
    kb = os.environ.get("RESEARCH_KB", str(args.kb))
    scraped = None
    if args.with_scrape:
        from .sources.base import fetch_all_sources
        scraped = fetch_all_sources([args.coin], deps["get_all_sources"]())

    out = deps["latest"](args.coin, seeds, kb, scraped,
                         window_days=args.days, limit=args.limit)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    window = out.get("window_days", args.days)
    print(_h1(f"最新机构研报 latest | {out.get('coin')} | 近 {window} 天"))
    print(f"  覆盖机构: {out.get('coverage_count')} 家")
    if out.get("note"):
        print(f"  Note:     {out['note']}")
    if out.get("institutions_in_window"):
        print(f"  机构:     {', '.join(out['institutions_in_window'])}")
    if out.get("divergence_ratio_within_1y") is not None:
        print(f"  1y内分歧:  max÷min = {out['divergence_ratio_within_1y']:.2f}x")
    print()
    print(f"  {'Date':<12} {'Institution':<22} {'Coin':<5} {'Target':>10} "
          f"{'Hor(m)':>6} {'Rating':<8} {'Tier':<5}")
    print(f"  {'─' * 12} {'─' * 22} {'─' * 5} {'─' * 10} {'─' * 6} {'─' * 8} {'─' * 5}")
    for r in out.get("records", []):
        print(f"  {r.get('pub_date',''):<12} {str(r.get('institution',''))[:22]:<22} "
              f"{r.get('coin',''):<5} {_fmt_price(r.get('target_price')):>10} "
              f"{str(r.get('horizon_months','-')):>6} {(r.get('rating') or '-'):<8} "
              f"{(r.get('tier') or '-'):<5}")
        if r.get("excerpt"):
            print(f"     └ {r['excerpt'][:100]}")
        if r.get("source_url"):
            print(f"     └ URL: {r['source_url'][:100]}")
    return 0


def cmd_report(args, deps):
    coins = _split_coins(args.coins)
    if not coins:
        print("[report] 请用 --coins 指定币列表", file=sys.stderr)
        return 2
    seeds = deps["get_seed_records"]()
    kb = os.environ.get("RESEARCH_KB", str(args.kb))
    scraped = None
    if args.with_scrape:
        from .sources.base import fetch_all_sources
        scraped = fetch_all_sources(coins, deps["get_all_sources"]())
    current = _parse_current_prices(args.current)
    report = deps["build_report"](coins, seeds, kb, scraped, current_prices=current)
    md = _render_markdown_report(report)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"[report] 已写入: {args.out}")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    # 默认打印 markdown
    print(md)
    return 0


def cmd_add(args, deps):
    from .sources.base import append_jsonl_atomic, compute_record_id
    from .config import normalize_institution, normalize_coin, tier_of, normalize_rating
    from .seeds import get_seed_records  # 确保 seeds 模块路径一致
    institution = normalize_institution(args.institution)
    coin = normalize_coin(args.coin)
    tier = tier_of(institution)
    rating = normalize_rating(args.rating)

    errors = []
    if not institution or tier == "unknown":
        errors.append(f"机构 `{args.institution}` 不在白名单（tier=unknown，默认拒绝）")
    if coin is None:
        errors.append(f"代币 `{args.coin}` 不在 40 币白名单，拒绝")
    try:
        target_price = float(args.target_price)
        if target_price <= 0:
            raise ValueError
    except (TypeError, ValueError):
        errors.append(f"--target-price 必须是正数（got {args.target_price!r}）")
    if not args.pub_date or len(args.pub_date) < 10:
        errors.append("--pub-date 需要 YYYY-MM-DD")
    if errors:
        print("[add] 参数错误：\n  - " + "\n  - ".join(errors), file=sys.stderr)
        return 2

    rec = {
        "id": None,
        "institution": institution,
        "tier": tier,
        "coin": coin,
        "target_price": target_price,
        "target_currency": "USD",
        "target_date": (args.target_date or "").strip() or None,
        "horizon_months": int(args.horizon_months) if args.horizon_months else None,
        "pub_date": args.pub_date[:10],
        "rating": rating,
        "source_type": "manual",
        "source_url": (args.source_url or "").strip() or None,
        "excerpt": (args.excerpt or "").strip()[:200] or f"手工录入（{institution}）",
        "confidence": 0.85,
        "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    rec["id"] = compute_record_id(rec)
    kb = os.environ.get("RESEARCH_KB", str(args.kb))
    n = append_jsonl_atomic(kb, [rec])
    if n == 0:
        print(f"[add] 写入 0 条（id={rec['id']} 已存在，视为重复）")
        print(f"  机构={rec['institution']}  币={rec['coin']}  "
              f"目标价={_fmt_price(rec['target_price'])}  发布日={rec['pub_date']}")
        return 0
    print(f"[add] 成功写入 {n} 条到知识库 {kb}")
    print(f"  id={rec['id']}  机构={rec['institution']}  tier={rec['tier']}  "
          f"币={rec['coin']}  目标价={_fmt_price(rec['target_price'])}  发布日={rec['pub_date']}")
    if rec.get("excerpt"):
        print(f"  摘要: {rec['excerpt']}")
    return 0


# ══ 辅助：--current CLI 参数解析 / MD 报告渲染 ══════════════════

def _parse_current_prices(raw: str | None) -> dict[str, float] | None:
    """--current BTC=67000,ETH=3500,SOL=140 的简单解析。"""
    if not raw:
        return None
    from .config import normalize_coin
    out = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        k, v = chunk.split("=", 1)
        nk = normalize_coin(k)
        if not nk:
            continue
        try:
            out[nk] = float(v.strip())
        except ValueError:
            continue
    return out or None


def _render_markdown_report(rep: dict) -> str:
    lines: list[str] = []
    lines.append(f"# 机构研报交叉分析报告\n")
    lines.append(f"- 生成时间: {rep.get('generated_at')}")
    lines.append(f"- 分析币列表: {', '.join(rep.get('coins', []))}")
    lines.append("")
    lines.append("> 本报告来源：内置种子（渣打/ARK/摩根等大牌）+ 本地知识库 + （可选）实时抓取；")
    lines.append("> 仅用于个人判断参考，不参与任何交易或回测决策。")
    lines.append("")
    for item in rep.get("analyze", []):
        c = item["coin"]
        lines.append(f"## {c} — 覆盖机构 {item.get('coverage_count', 0)} 家")
        if item.get("note"):
            lines.append(f"- **Note**: {item['note']}")
            lines.append("")
            continue
        lines.append(f"- 机构列表（{item['coverage_count']}）: {', '.join(item.get('institutions', []))}")
        lines.append(f"- 记录总数: {item.get('total_records', 0)}")
        lines.append(f"- Tier 分布: " + ", ".join(f"`{k}={v}`" for k, v in sorted(item.get("tier_distribution", {}).items())))
        lines.append("")
        lines.append("| 时间窗口 | 条数 | 最低目标价 | 最高目标价 | 中位数 | 均价 | 分歧 max/min | 上行空间 (vs 当前) |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for name, b in item.get("target_price_ranges", {}).items():
            c = b.get("count", 0)
            if c == 0:
                lines.append(f"| {name} | 0 | — | — | — | — | — | — |")
                continue
            div = b.get("divergence_ratio", "-")
            up = b.get("upside_vs_current_pct", "-")
            up_cell = f"{up:+.1f}%" if isinstance(up, (int, float)) else "-"
            lines.append(f"| {name} | {c} | {_fmt_price(b['min'])} | {_fmt_price(b['max'])} | "
                         f"{_fmt_price(b['median'])} | {_fmt_price(b['mean'])} | {div}x | {up_cell} |")
        lines.append("")

        latest_block = (rep.get("latest") or {}).get(c)
        if latest_block and latest_block.get("records"):
            lines.append(f"### {c} 最新 {len(latest_block['records'])} 条")
            lines.append("")
            lines.append("| 发布日期 | 机构 | 目标价 | Rating | Tier | 摘要 |")
            lines.append("|---|---|---:|---|---|---|")
            for r in latest_block["records"]:
                lines.append(f"| {r.get('pub_date','')} | {r.get('institution','')} | "
                             f"{_fmt_price(r.get('target_price'))} | "
                             f"{r.get('rating') or '-'} | {r.get('tier') or '-'} | "
                             f"{((r.get('excerpt') or '').replace('|','/'))[:120]} |")
            lines.append("")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Report generated by mx_auto_strategy.crypto_stocks.research (v1.0.0)*")
    return "\n".join(lines)


# ══════════════════ argparse setup ══════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="research-cli",
        description="机构研报子模块 CLI：查询主流机构（渣打/ARK/摩根等）对代币的目标价、覆盖数与上下区间。",
    )
    p.add_argument("--kb", default=str(DEFAULT_KB_PATH),
                   help=f"本地知识库 JSONL 路径（默认: {DEFAULT_KB_PATH}）")
    sub = p.add_subparsers(dest="cmd", required=True)

    def _coins_arg(sp, required=True):
        sp.add_argument("--coins", required=required,
                        help="逗号分隔的币列表，如 BTC,ETH,SOL,DOGE")
        sp.add_argument("--with-scrape", action="store_true",
                        help="分析前先联网跑 3 个抓取源并入（默认关）")
        sp.add_argument("--current", default=None,
                        help="当前价映射，如 BTC=67000,ETH=3500,SOL=140")
        sp.add_argument("--json", action="store_true", help="输出 JSON 而非终端表格")
        return sp

    pf = sub.add_parser("fetch", help="联网抓取 3 源 → 写入 kb（去重）")
    pf.add_argument("--coins", required=True, help="BTC,ETH,SOL")
    pf.set_defaults(func=cmd_fetch)

    pa = sub.add_parser("analyze", help="交叉聚合分析（不联网，基于 seeds+kb）")
    _coins_arg(pa)
    pa.set_defaults(func=cmd_analyze)

    pr = sub.add_parser("report", help="生成完整 Markdown 报告")
    _coins_arg(pr)
    pr.add_argument("--out", default=None, help="额外写入 Markdown 文件的路径")
    pr.set_defaults(func=cmd_report)

    pl = sub.add_parser("latest", help="近 N 天单币最新条目表")
    pl.add_argument("--coin", required=True)
    pl.add_argument("--days", type=int, default=180, help="窗口天数（默认 180）")
    pl.add_argument("--limit", type=int, default=10, help="显示条数上限")
    pl.add_argument("--with-scrape", action="store_true")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_latest)

    padd = sub.add_parser("add", help="手工录入一条研报")
    padd.add_argument("--institution", required=True, help="机构名，支持同义/简称")
    padd.add_argument("--coin", required=True)
    padd.add_argument("--target-price", required=True, type=float)
    padd.add_argument("--pub-date", required=True, help="YYYY-MM-DD")
    padd.add_argument("--rating", default=None)
    padd.add_argument("--horizon-months", default=None, type=int)
    padd.add_argument("--target-date", default=None)
    padd.add_argument("--source-url", default=None)
    padd.add_argument("--excerpt", default=None)
    padd.set_defaults(func=cmd_add)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    deps = _load_dependencies()
    return args.func(args, deps)


if __name__ == "__main__":
    sys.exit(main())
