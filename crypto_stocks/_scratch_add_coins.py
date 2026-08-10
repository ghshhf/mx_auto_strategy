"""把新币 BNB/GMX/API3/GRT 的历史周K抓回并补进 CSV (Binance->OKX 降级, 对齐周五)"""
import os, csv, sys, time
import crypto_hist_data as chd

NEW = ['BNB', 'GMX', 'API3', 'GRT']
FILES = ['data/weekly_adjclose_crypto50.csv', 'data/weekly_adjclose_crypto50_10y.csv']
syms = chd.all_coin_symbols()

def fetch_weekly(coin):
    cfg = syms[coin]
    rows = chd.fetch_binance_full(cfg['binance'], cfg['start'])
    if len(rows) < 2:
        print(f"    Binance 不足({len(rows)}), 试 OKX ...")
        rows = chd.fetch_okx_weekly(cfg['okx'], cfg['start'])
    if len(rows) < 2:
        print(f"    [警告] {coin} 两源均不足, 留空")
        return {}
    w = chd.rows_to_weekly_close(rows)
    print(f"    {coin}: 取到 {len(w)} 周 (首 {min(w)} ~ 末 {max(w)})")
    return w

# 先抓全部新币
data_w = {c: fetch_weekly(c) for c in NEW}

for fname in FILES:
    if not os.path.exists(fname):
        print(f"[跳过] {fname} 不存在"); continue
    with open(fname, encoding='utf-8-sig', newline='') as f:
        r = list(csv.reader(f))
    header, body = r[0], r[1:]
    dates = [row[0] for row in body]
    added = []
    for coin in NEW:
        if coin in header:
            print(f"  {fname}: {coin} 已存在, 跳过"); continue
        w = data_w[coin]
        col = [('' if d not in w else w[d]) for d in dates]
        header.append(coin)
        for i, row in enumerate(body):
            row.append(col[i])
        added.append(coin)
        n = sum(1 for v in col if v != '')
        print(f"  {fname}: 追加 {coin} 列, 非空 {n}/{len(dates)} 周")
    if added:
        with open(fname, 'w', encoding='utf-8-sig', newline='') as f:
            csv.writer(f).writerows([header] + body)
        print(f"  -> 已写回 {fname}  现共 {len(header)-1} 币")
    else:
        print(f"  {fname}: 无新增")
print("\n完成。")
