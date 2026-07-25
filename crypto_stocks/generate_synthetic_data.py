"""
generate_synthetic_data.py - 合成加密历史数据 (用于沙箱演示)

沙箱环境无法访问 Binance/OKX API, 用已知价格锚点 + 随机游走生成
接近真实的周频数据. 用户在本地运行 crypto_hist_data.py 即可获得真实数据.

锚点 (真实价格):
  BTC: 2018-04 $6700 -> 2021-11 $69000 -> 2022-11 $16400 -> 2025-07 ~$105000
  ETH: 2018-04 $400  -> 2021-11 $4800  -> 2022-11 $1200  -> 2025-07 ~$2500
  OKB: 2018-04 $1.5  -> 2021-05 $28    -> 2022-11 $12    -> 2025-07 ~$50
"""
import os, sys, csv, math
import numpy as np
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
os.makedirs(DATA, exist_ok=True)

np.random.seed(42)

# 价格锚点 (date, btc, eth, okb) - 大致真实
ANCHORS = [
    ('2018-04-06', 6700, 400, 1.5),
    ('2018-07-01', 7400, 450, 1.3),
    ('2018-12-15', 3200, 85, 0.70),
    ('2019-04-01', 5000, 170, 1.0),
    ('2019-06-26', 13000, 350, 1.4),
    ('2019-09-23', 8300, 180, 1.0),
    ('2020-03-12', 3900, 110, 0.55),
    ('2020-08-17', 12300, 420, 5.2),
    ('2020-12-26', 26500, 680, 5.8),
    ('2021-01-08', 40000, 1100, 6.5),
    ('2021-04-14', 64000, 2400, 18.0),
    ('2021-05-19', 37000, 2500, 12.0),
    ('2021-11-10', 69000, 4800, 28.0),
    ('2022-01-22', 35000, 2400, 22.0),
    ('2022-05-12', 28000, 1700, 13.0),
    ('2022-06-18', 18500, 900, 9.0),
    ('2022-11-21', 16400, 1200, 12.0),
    ('2023-01-14', 21000, 1500, 15.0),
    ('2023-04-14', 30500, 2100, 48.0),
    ('2023-07-13', 31000, 1900, 44.0),
    ('2023-10-23', 35000, 1800, 50.0),
    ('2023-12-07', 44000, 2400, 56.0),
    ('2024-01-10', 46000, 2500, 52.0),
    ('2024-03-14', 73000, 3900, 58.0),
    ('2024-06-22', 65000, 3500, 50.0),
    ('2024-07-22', 57000, 3200, 42.0),
    ('2024-09-15', 58000, 2400, 38.0),
    ('2024-11-20', 94000, 3300, 52.0),
    ('2024-12-05', 100000, 3900, 55.0),
    ('2025-01-20', 104000, 3600, 48.0),
    ('2025-04-14', 85000, 1800, 38.0),
    ('2025-07-18', 108000, 2600, 52.0),
]


def _interpolate_anchors(anchors, start_date, end_date):
    """在锚点之间用指数插值生成每周价格."""
    # 解析锚点
    pts = []
    for row in anchors:
        d = datetime.strptime(row[0], '%Y-%m-%d')
        pts.append((d, {'BTC': row[1], 'ETH': row[2], 'OKB': row[3]}))

    # 生成每周日期 (周五)
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    cur = start
    # 对齐到最近的周五
    while cur.weekday() != 4:
        cur += timedelta(days=1)

    weekly = []
    while cur <= end:
        weekly.append(cur)
        cur += timedelta(weeks=1)

    # 对每个周, 找前后锚点, 指数插值 + 随机噪声
    results = {'date': [], 'BTC': [], 'ETH': [], 'OKB': []}
    for w in weekly:
        # 找前后锚点
        before, after = None, None
        for i, (d, v) in enumerate(pts):
            if d <= w:
                before = (d, v)
            if d >= w and after is None:
                after = (d, v)

        if before is None and after is not None:
            before = (after[0] - timedelta(days=365), {k: v * 0.5 for k, v in after[1].items()})
        if after is None and before is not None:
            after = (before[0] + timedelta(days=365), {k: v * 2 for k, v in before[1].items()})
        if before is None:
            continue

        # 时间比例
        total_span = (after[0] - before[0]).days
        elapsed = (w - before[0]).days
        frac = elapsed / total_span if total_span > 0 else 0.5
        frac = max(0, min(1, frac))

        # 指数插值 (收益率线性)
        results['date'].append(w.strftime('%Y-%m-%d'))
        for coin in ['BTC', 'ETH', 'OKB']:
            p0 = before[1][coin]
            p1 = after[1][coin]
            if p0 > 0 and p1 > 0:
                # log 空间线性插值
                log_p = math.log(p0) * (1 - frac) + math.log(p1) * frac
                base_price = math.exp(log_p)
            else:
                base_price = p0 * (1 - frac) + p1 * frac
            results[coin].append(base_price)

    # 添加随机噪声 (周收益率 ±3-8%)
    for coin in ['BTC', 'ETH', 'OKB']:
        vol = {'BTC': 0.04, 'ETH': 0.06, 'OKB': 0.08}[coin]
        prices = results[coin]
        noisy = [prices[0]]
        for i in range(1, len(prices)):
            ret = (prices[i] / prices[i-1] - 1) + np.random.normal(0, vol)
            noisy.append(max(prices[i-1] * 0.3, prices[i-1] * (1 + ret)))
        results[coin] = noisy

    return results


def generate(output_path=None):
    """生成合成数据并保存."""
    if output_path is None:
        output_path = os.path.join(DATA, 'weekly_adjclose_crypto3.csv')

    # BTC 数据从2018-04起, ETH/OKB 也类似
    start = '2018-04-06'
    end = '2025-07-18'

    data = _interpolate_anchors(ANCHORS, start, end)

    # 过滤掉 ETH/OKB 尚未上市的早期 (ETH 2015 有, OKB 2018-03)
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'BTC', 'ETH', 'OKB'])
        for i in range(len(data['date'])):
            writer.writerow([
                data['date'][i],
                f"{data['BTC'][i]:.2f}",
                f"{data['ETH'][i]:.2f}",
                f"{data['OKB'][i]:.4f}",
            ])

    n = len(data['date'])
    print(f"  合成数据: {n} 周 ({data['date'][0]} ~ {data['date'][-1]})")
    print(f"  BTC: {data['BTC'][0]:.0f} -> {data['BTC'][-1]:.0f}")
    print(f"  ETH: {data['ETH'][0]:.0f} -> {data['ETH'][-1]:.0f}")
    print(f"  OKB: {data['OKB'][0]:.2f} -> {data['OKB'][-1]:.2f}")
    print(f"  已保存: {output_path}")
    return output_path


if __name__ == '__main__':
    generate()
