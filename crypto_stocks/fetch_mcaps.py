"""抓取当前池子(面板57币)的实时市值, 按市值升序输出低市值候选."""
import csv, json, subprocess, sys, os

PANEL = "data/weekly_adjclose_crypto50.csv"
# CoinGecko id 映射 (取自 data_sources.py)
CG = {
    'BTC': 'bitcoin', 'ETH': 'ethereum', 'OKB': 'okb', 'SOL': 'solana',
    'BNB': 'binancecoin', 'ADA': 'cardano', 'AVAX': 'avalanche-2',
    'DOT': 'polkadot', 'LINK': 'chainlink', 'POL': 'polygon-ecosystem-token',
    'TRX': 'tron', 'UNI': 'uniswap', 'NEAR': 'near', 'APT': 'aptos',
    'ARB': 'arbitrum', 'OP': 'optimism', 'SUI': 'sui', 'FET': 'fetch-ai',
    'SKY': 'sky', 'AAVE': 'aave', 'TIA': 'celestia',
    'FIL': 'filecoin',
    'CRV': 'curve-dao-token', 'LDO': 'lido-dao',
    'COMP': 'compound-governance-token', 'DYDX': 'dydx',
    'GALA': 'gala', 'ZEC': 'zcash',
    'DASH': 'dash', 'AR': 'arweave',
    'JUP': 'jupiter', 'JOE': 'joe', 'TAO': 'bittensor', 'ONDO': 'ondo-finance',
    'GRAM': 'the-open-network',
    'CFG': 'centrifuge',
    'XLM': 'stellar', 'LTC': 'litecoin',
    'GMX': 'gmx', 'API3': 'api3',
    'RENDER': 'render-token', 'RON': 'ronin', 'XRP': 'ripple',
}

# 读取面板实际币种
with open(PANEL, encoding='utf-8-sig') as f:
    hdr = next(csv.reader(f))
coins = [c for c in hdr if c and c.lower() != 'date']
print(f"[*] 面板币种 {len(coins)} 个", file=sys.stderr)

ids = [CG[c] for c in coins if c in CG]
missing = [c for c in coins if c not in CG]
print(f"[*] 命中 CG {len(ids)} 个, 缺失 {missing}", file=sys.stderr)

url = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids="
       + ",".join(ids)
       + "&order=market_cap_asc&per_page=250&page=1&sparkline=false")
# 走本地机场代理
env = dict(os.environ)
env['HTTPS_PROXY'] = env['HTTP_PROXY'] = 'socks5h://127.0.0.1:1080'
r = subprocess.run(['curl', '-s', '-m', '40', '-x', 'socks5h://127.0.0.1:1080', url],
                   capture_output=True, text=True, env=env)
try:
    data = json.loads(r.stdout)
except Exception as e:
    print("解析失败:", e, file=sys.stderr)
    print(r.stdout[:500], file=sys.stderr)
    sys.exit(1)

if not isinstance(data, list):
    print("非预期返回:", str(data)[:300], file=sys.stderr)
    sys.exit(1)

rev = {v: k for k, v in CG.items()}
got = {rev.get(d['id']): d for d in data}
rows = []
for c in coins:
    if c in got:
        d = got[c]
        rows.append((c, d.get('market_cap'), d.get('current_price')))
    else:
        rows.append((c, None, None))

# 排序: 有市值的按市值升序(低市值在前); 缺失排最后
def keyf(r):
    return (r[1] is None, r[1] if r[1] is not None else 1e100)
rows.sort(key=keyf)

print(f"\n{'SYM':<7}{'市值(USD)':>16}{'≈亿美金':>12}", file=sys.stderr)
out = []
for c, mc, px in rows:
    if mc is None:
        print(f"{c:<7}{'N/A':>16}", file=sys.stderr)
        out.append({'sym': c, 'mcap': None})
    else:
        yi = mc / 1e8
        print(f"{c:<7}{mc:>16,.0f}{yi:>12.2f}", file=sys.stderr)
        # 赛道
        out.append({'sym': c, 'mcap': mc, 'yi': yi, 'price': px})

with open('mcap_snapshot.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"\n[*] 已写出 mcap_snapshot.json ({len(out)} 条)", file=sys.stderr)
