"""抓取当前池子(面板37币)的实时市值, 按市值升序输出低市值候选.

输出: mcap_snapshot.json (供 held_weeks.py / index_buyhold.py 消费)
排序: 有市值者按市值升序(低市值在前); 缺失市值者排最后。

2026-09-01 修复:
  1. 原脚本硬编码 socks5h://127.0.0.1:1080 —— 该端口实测未监听(HTTP 000), 脚本直接
     跑不通("解析失败: Expecting value: line 1 column 1")。改走 net_config 统一代理。
  2. 补全缺失的 CoinGecko id: GT / INJ / RAY (均已实测校验市值可返回; ONT 已于 2026-09-01 移出面板)。
  3. 移除僵尸映射 API3 / JOE (三面板均无此二币)。
  4. 去掉对外部 curl 的依赖, 改用 urllib (避免 curl 缺失/编码问题)。

注意(重要): 下方的 CoinGecko 映射字典被 manage_token.py 用正则定位并改写
(cgmap_add / cgmap_remove)。两个硬约束:
  1. 本文件**任何位置**(含注释/文档字符串)都不得再出现该字典的声明式样
     (例如 "CG" 后接等号和花括号), 否则 cgmap_add 的 re.search 会先命中
     注释里的那处, 把新映射插进注释中而损坏文件。这也是本注释刻意用描述性
     文字而不写字面样式的原因。
  2. 映射条目必须保持  '符号': 'coingecko-id',  的写法, 否则 cgmap_remove
     的正则无法识别删除目标。
修改本文件后, 建议跑一次 manage_token.py doctor 确认解析未被破坏。
"""
import csv
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
# 允许从 markets/crypto/ 目录下直接运行
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from net_config import proxy_opener  # noqa: E402

PANEL = os.path.join(HERE, "data", "weekly_adjclose_crypto50.csv")

# CoinGecko id 映射 (格式被 manage_token.py 正则依赖, 勿改结构)
CG = {
    'HYPE': 'hyperliquid',  # 2026-09-01
    'ETHFI': 'ether-fi',  # 2026-09-01
    'HBAR': 'hedera-hashgraph',  # 2026-08-31
    'GT': 'gatechain-token',  # 2026-09-01
    'INJ': 'injective-protocol',  # 2026-09-01
    'RAY': 'raydium',  # 2026-09-01
    # 2026-09-01
    'BTC': 'bitcoin', 'ETH': 'ethereum', 'OKB': 'okb', 'SOL': 'solana',
    'BNB': 'binancecoin', 'ADA': 'cardano', 'AVAX': 'avalanche-2',
    'DOT': 'polkadot', 'LINK': 'chainlink', 'POL': 'polygon-ecosystem-token',
    'TRX': 'tron', 'UNI': 'uniswap', 'NEAR': 'near', 'APT': 'aptos',
    'GLM': 'golem',
    'AAVE': 'aave', 'FIL': 'filecoin',
    'BCH': 'bitcoin-cash',
    'DYDX': 'dydx',
    'ZEC': 'zcash',
    'JUP': 'jupiter', 'ONDO': 'ondo-finance',
    'GRAM': 'the-open-network',
    'XLM': 'stellar', 'LTC': 'litecoin', 'ICP': 'internet-computer',
    'RENDER': 'render-token', 'XRP': 'ripple',
    'PENDLE': 'pendle',
}


def fetch_markets(ids, timeout=40):
    """向 CoinGecko 拉市值快照; 失败抛异常由调用方降级。"""
    url = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids="
           + ",".join(ids)
           + "&order=market_cap_asc&per_page=250&page=1&sparkline=false")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = proxy_opener().open(req, timeout=timeout).read().decode("utf-8", "ignore")
    return json.loads(raw)


def main():
    with open(PANEL, encoding="utf-8-sig") as f:
        hdr = next(csv.reader(f))
    coins = [c for c in hdr if c and c.lower() != "date"]
    print(f"[*] 面板币种 {len(coins)} 个", file=sys.stderr)

    ids = [CG[c] for c in coins if c in CG]
    missing = [c for c in coins if c not in CG]
    print(f"[*] 命中 CG {len(ids)} 个, 缺失 {missing}", file=sys.stderr)

    try:
        data = fetch_markets(ids)
    except Exception as e:                      # 网络/解析失败统一降级
        print(f"[!] 拉取失败: {e}", file=sys.stderr)
        print("    提示: 代理由 net_config 统一解析, 可用 MX_PROXY 环境变量显式指定。",
              file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list):
        print("非预期返回:", str(data)[:300], file=sys.stderr)
        sys.exit(1)

    rev = {v: k for k, v in CG.items()}
    got = {rev.get(d["id"]): d for d in data}
    rows = []
    for c in coins:
        d = got.get(c)
        rows.append((c, d.get("market_cap"), d.get("current_price")) if d else (c, None, None))

    # 排序: 有市值的按市值升序(低市值在前); 缺失排最后
    rows.sort(key=lambda r: (r[1] is None, r[1] if r[1] is not None else 1e100))

    print(f"\n{'SYM':<7}{'市值(USD)':>16}{'≈亿美金':>12}", file=sys.stderr)
    out = []
    for c, mc, px in rows:
        if mc is None:
            print(f"{c:<7}{'N/A':>16}", file=sys.stderr)
            out.append({"sym": c, "mcap": None})
        else:
            yi = mc / 1e8
            print(f"{c:<7}{mc:>16,.0f}{yi:>12.2f}", file=sys.stderr)
            out.append({"sym": c, "mcap": mc, "yi": yi, "price": px})

    dst = os.path.join(HERE, "mcap_snapshot.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n[*] 已写出 {os.path.basename(dst)} ({len(out)} 条)", file=sys.stderr)


if __name__ == "__main__":
    main()
