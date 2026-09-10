"""
sync_crypto_panel.py - 增量同步加密周K面板到今天 (Binance > OKX > CMC 三级降级)
=============================================================================
复用 crypto_hist_data 的符号映射/取数函数, 仅追加 "现有最后日期之后" 的周K,
不动历史行, 保证网格(Friday)与现有数据严格连续.

数据源优先级:
  1. Binance api.binance.com (周K, 免费, 主源)
  2. OKX     www.okx.com      (周K, 免费, 备源)
  3. CoinMarketCap pro-api.coinmarketcap.com (日线聚合周五, 需 API key, 兜底)

目标文件 (回测实际读取的):
  data/weekly_adjclose_crypto50.csv      (crypto_options_bt.py, 主工作面板)
  data/weekly_adjclose_crypto50_v3.csv   (池管理面板, 与 c50 同币同源)
  data/weekly_adjclose_crypto50_10y.csv  (OOS/10y 真值面板)

用法:
  python sync_crypto_panel.py                     # 单面板逐币取数
  python scripts/ops/sync_all_panels.py           # 单次取数 -> 复用三面板 (推荐)
"""
import os
import sys
import csv
import time
import datetime
import urllib.request
import json

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # 仓库根, 供 net_config
sys.path.insert(0, HERE)
import crypto_hist_data as chd  # noqa: E402

# ---------- 代理 (统一走 net_config 解析) ----------
# 2026-09-01: 原为 "环境变量优先"。沙箱注入的 61350 对 Binance/OKX 全返 502,
# 会让增量同步卡死; 改由 net_config 存活探测 + 回退 3067, 从源头规避。
import net_config  # noqa: E402

_PROXY = net_config.proxy_url()
_op = urllib.request.build_opener(
    urllib.request.ProxyHandler({'http': _PROXY, 'https': _PROXY}))
urllib.request.install_opener(_op)

# ---------- 数据源配置 (key 来自 .env / 环境变量, 不硬编码) ----------
def _load_env_file():
    """读取项目内 .env (已被 .gitignore 屏蔽, 不入库), 仅本地开发用."""
    env = {}
    p = os.path.join(HERE, '.env')
    if os.path.exists(p):
        with open(p, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


_LOCAL_ENV = _load_env_file()
_CMC_KEY = (os.environ.get('CMC_API_KEY')
            or _LOCAL_ENV.get('CMC_API_KEY', ''))

# CMC symbol -> id 映射 (56/57 币; PAS 不在 CMC 上)
# 来源: 2026-08-11 实时查询 pro-api.coinmarketcap.com
# 注意: RENDER id=5690; GRAM(原 TON, 2026-06-15 更名, ticker TON->GRAM, id 不变=11419)
_CMC_ID_MAP = {
    # 2026-08-31
    'AAVE': 7278,   'ADA': 2010,
    'APT': 21794,    'AVAX': 5805,
    'BTC': 1, 'BCH': 1831, 'XLM': 512,
    'DOT': 6636,    'ETH': 1027,
    'GLM': 1455,     'FIL': 2280,    'LINK': 1975,    'LTC': 2,       'POL': 6690,
    'OKB': 3897,
    'RENDER': 5690,    'SOL': 5426,
    'GRAM': 11419,   'TRX': 1958,    'UNI': 7083,     'ZEC': 1437,   'XRP': 52,
    }


def _cmc_get(url):
    """CMC HTTP GET (带 key + 代理)."""
    req = urllib.request.Request(url, headers={
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': _CMC_KEY,
    })
    return json.loads(_op.open(req, timeout=30).read().decode())


def fetch_cmc_weekly(cmc_id, start_date):
    """从 CMC quotes/historical 拉日线, 聚合为 {friday_date: close}.
    CMC 免费版仅支持 daily interval, 我们取每周五的 close 作为周收盘价."""
    if not _CMC_KEY or not cmc_id:
        return {}
    url = (f'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/historical'
           f'?id={cmc_id}&time_start={start_date}&interval=daily')
    try:
        d = _cmc_get(url)
        quotes = d.get('data', {}).get('quotes', [])
        if not quotes:
            return {}
    except Exception as e:
        print(f"    [CMC] id={cmc_id} 失败: {e}", file=sys.stderr)
        return {}

    weekly = {}
    for q in quotes:
        ts_str = q.get('timestamp', '')
        if not ts_str:
            continue
        # CMC timestamp format: "2026-08-08T00:00:00.000Z"
        try:
            dt = datetime.datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            friday = (dt - datetime.timedelta(days=(dt.weekday() - 4) % 7))
            fri_str = friday.strftime('%Y-%m-%d')
        except (ValueError, OSError):
            continue
        close = (q.get('quote', {}).get('USD', {}).get('close')
                 or q.get('quote', {}).get('USD', {}).get('price'))
        if close is not None:
            weekly[fri_str] = close
    return weekly


def fetch_coin_from(start_date, binance_sym, okx_sym, cmc_id=None):
    """三级降级取数: Binance -> OKX -> CMC. 返回 {friday_date: close}."""
    # Level 1: Binance
    rows = chd.fetch_binance_full(binance_sym, start_date)
    if len(rows) >= 2:
        return chd.rows_to_weekly_close(rows)

    # Level 2: OKX
    print(f"    Binance 不足 ({len(rows)}), 试 OKX ...", file=sys.stderr)
    rows = chd.fetch_okx_weekly(okx_sym, start_date)
    if len(rows) >= 2:
        return chd.rows_to_weekly_close(rows)

    # Level 3: CMC
    print(f"    OKX 也不足 ({len(rows)}), 试 CMC ...", file=sys.stderr)
    if cmc_id and _CMC_KEY:
        w = fetch_cmc_weekly(cmc_id, start_date)
        if len(w) >= 1:
            print(f"    CMC 成功: {len(w)} 周", file=sys.stderr)
            return w
        print("    CMC 数据为空", file=sys.stderr)

    return {}


#: 尾部回溯重写窗口(周). 见 TAIL_REFRESH_NOTE.
TAIL_REFRESH_WEEKS = 8

TAIL_REFRESH_NOTE = """
2026-09-10 修复: 历史版本只追加 `d > 面板末日` 的行, 而"当前未完结周"一旦
写入就再也不会被更新. 后果: 若某次同步恰好跑在周初, 该周行会永久冻结在周初
价格上 —— 实测 2026-08-30 那周 RAY 周内 +66%(0.772→1.286), 面板却记成
0.778(-39%); ZEC -33% / UNI -30% 同类. 越靠近当下的行污染越重, 而回测恰恰
最依赖最近的数据.
现改为: 同步时**回溯重写尾部 N 周**(已收盘周用交易所终值覆盖周初快照),
再追加更新的周. 取值优先级 Binance > OKX > CMC, 只在取到非空值时覆盖,
不会把已有数据改成空.
"""

_BIG_CORRECTION = 0.10  # 单格修正幅度超过 10% 时高亮提示 (属正常修复, 但需可见)


def sync_file(fname, prefetched=None, tail_refresh=TAIL_REFRESH_WEEKS, dry_run=False):
    """同步单个面板 CSV: 尾部回溯重写 + 增量追加.

    prefetched: 可选 dict {coin: {date: close}}. 传入时跳过逐币拉取, 直接用
    预取结果——供 sync_all_panels 单次取数后复用到 c50/v3/10y 三张同币池面板,
    消除三份网络取数造成的末行漂移. 列顺序不同的面板(10y)按 header 列名写回,
    与取数顺序无关.

    tail_refresh: 回溯重写的周数 (0 = 退化为旧的纯追加行为).
    dry_run: 只报告将要发生的修改, 不落盘.
    """
    path = os.path.join(DATA, fname)
    if not os.path.exists(path):
        print(f"[跳过] {fname} 不存在")
        return
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        rows = list(reader)
    header = rows[0]
    data = rows[1:]
    coins = header[1:]
    last_date = data[-1][0]

    _ld = datetime.datetime.strptime(last_date, '%Y-%m-%d').date()
    refresh_from = (_ld - datetime.timedelta(weeks=tail_refresh)).isoformat() if tail_refresh \
        else last_date

    cmc_status = "ON" if _CMC_KEY else "OFF"
    src_tag = f"  预取源={len(prefetched) if prefetched else 0}币"
    print(f"\n=== {fname} ===  现有末日={last_date}  币种={len(coins)}  CMC={cmc_status}{src_tag}")
    print(f"  回溯窗口: >= {refresh_from} (尾部 {tail_refresh} 周将被重写)")

    syms = chd.all_coin_symbols()
    new_series = {}
    empty_coins = []
    for coin in coins:
        if prefetched is not None:
            w = {d: p for d, p in prefetched.get(coin, {}).items() if d >= refresh_from}
            new_series[coin] = w
            continue
        cfg = syms.get(coin)
        cmc_id = _CMC_ID_MAP.get(coin)
        if not cfg:
            print(f"  [警告] {coin} 无符号映射, 留空")
            empty_coins.append(coin)
            continue
        w = fetch_coin_from(refresh_from, cfg['binance'], cfg['okx'], cmc_id=cmc_id)
        w = {d: p for d, p in w.items() if d >= refresh_from}
        new_series[coin] = w
        time.sleep(0.05)

    # ---- 回溯重写 + 追加 ----
    idx = {r[0]: i for i, r in enumerate(data)}
    ci = {c: header.index(c) for c in coins}
    corrections = []          # (date, coin, old, new, 幅度)
    updated_cells = 0
    new_dates = set()

    for coin in coins:
        if coin in empty_coins:
            continue
        for d, p in new_series.get(coin, {}).items():
            if p is None or p == '':
                continue
            i = idx.get(d)
            if i is None:                      # 新周 -> 追加
                new_dates.add(d)
                continue
            old = data[i][ci[coin]]            # 已存在 -> 用交易所终值覆盖
            if old == '' or str(old) == str(p):
                if old == '':
                    data[i][ci[coin]] = p
                    updated_cells += 1
                continue
            try:
                dev = abs(float(old) / float(p) - 1)
            except (TypeError, ValueError, ZeroDivisionError):
                dev = 0.0
            data[i][ci[coin]] = p
            updated_cells += 1
            if dev > 0.001:
                corrections.append((d, coin, old, p, dev))

    for d in sorted(new_dates):
        data.append([d] + [''] * (len(header) - 1))
    data.sort(key=lambda r: r[0])
    idx = {r[0]: i for i, r in enumerate(data)}   # 追加后重建索引
    for coin in coins:
        if coin in empty_coins:
            continue
        for d in new_dates:
            p = new_series.get(coin, {}).get(d)
            if p is not None and p != '':
                data[idx[d]][ci[coin]] = p

    corrections.sort(key=lambda x: -x[4])
    if corrections:
        print(f"  回溯修正 {len(corrections)} 格 (幅度>0.1%):")
        for d, coin, old, p, dev in corrections[:12]:
            mark = '  <== 大幅修正' if dev > _BIG_CORRECTION else ''
            print(f"    {d} {coin:<7} {old:>14} -> {p:>14}  ({dev*100:>5.1f}%){mark}")
        if len(corrections) > 12:
            print(f"    ... 另 {len(corrections)-12} 格")
    if not new_dates and updated_cells == 0:
        print("  无需修改 (已是最新)")
        return
    print(f"  新增周: {sorted(new_dates) if new_dates else '无'}   重写格数: {updated_cells}")

    if dry_run:
        print(f"  [dry-run] 未落盘。若执行将写入 -> {path}")
        return

    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)
    print(f"  已写入 -> {path}  共 {len(data)} 周, 末日={data[-1][0]}")

    cov = {c: sum(1 for r in data if r[header.index(c)] != '')
           for c in coins}
    miss = [c for c, n in cov.items() if n < len(data)]
    if miss:
        print(f"  [提示] 仍有空值币种(上市晚/源缺): {miss[:10]}")


if __name__ == '__main__':
    _tail = TAIL_REFRESH_WEEKS
    _dry = False
    _args = [a for a in sys.argv[1:]]
    if '--dry-run' in _args:
        _dry = True
        _args.remove('--dry-run')
    for a in _args:
        if a.startswith('--tail='):
            _tail = int(a.split('=', 1)[1])
    for _f in ('weekly_adjclose_crypto50.csv',
               'weekly_adjclose_crypto50_v3.csv',
               'weekly_adjclose_crypto50_10y.csv'):
        sync_file(_f, tail_refresh=_tail, dry_run=_dry)
    print("\n完成。")
