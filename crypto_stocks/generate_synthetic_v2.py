"""
generate_synthetic_v2.py - Crypto50 合成数据生成 (10年, 沙箱演示)
============================================================

用真实价格锚点 + 赛道 beta 特征生成 50 个代币 10 年周频数据.

逻辑:
  1. BTC 用真实价格锚点 + 噪声 (基准)
  2. 每个代币有 beta (相对 BTC 的弹性), launch_year, 赛道波动率
  3. 未上线的代币价格为 NaN (自动被回测引擎过滤)
  4. 不同赛道有不同的 beta 集中度和波动率

10 年: 2016-01-01 ~ 2025-12-31
"""
import os, sys, csv, math
import numpy as np
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
os.makedirs(DATA, exist_ok=True)

np.random.seed(42)

# BTC 真实价格锚点 (date, btc_price)
BTC_ANCHORS = [
    ('2016-01-08', 430),
    ('2016-07-01', 670),
    ('2016-12-30', 960),
    ('2017-03-10', 1200),
    ('2017-06-11', 2600),
    ('2017-09-01', 4700),
    ('2017-12-16', 19500),
    ('2018-02-01', 8500),
    ('2018-04-06', 6700),
    ('2018-07-01', 7400),
    ('2018-12-15', 3200),
    ('2019-04-01', 5000),
    ('2019-06-26', 13000),
    ('2019-09-23', 8300),
    ('2020-03-12', 3900),
    ('2020-08-17', 12300),
    ('2020-12-26', 26500),
    ('2021-01-08', 40000),
    ('2021-04-14', 64000),
    ('2021-05-19', 37000),
    ('2021-11-10', 69000),
    ('2022-01-22', 35000),
    ('2022-05-12', 28000),
    ('2022-06-18', 18500),
    ('2022-11-21', 16400),
    ('2023-01-14', 21000),
    ('2023-04-14', 30500),
    ('2023-07-13', 31000),
    ('2023-10-23', 35000),
    ('2023-12-07', 44000),
    ('2024-01-10', 46000),
    ('2024-03-14', 73000),
    ('2024-06-22', 65000),
    ('2024-07-22', 57000),
    ('2024-09-15', 58000),
    ('2024-11-20', 94000),
    ('2024-12-05', 100000),
    ('2025-01-20', 104000),
    ('2025-04-14', 85000),
    ('2025-07-18', 108000),
    ('2025-12-31', 130000),
]

# 代币配置: {symbol: (beta, launch_year, base_price_at_launch, theme_vol_mult)}
# beta: 相对 BTC 收益率的弹性 (1.0=跟BTC走, 2.0=BTC涨10%它涨20%)
# theme_vol_mult: 赛道波动率倍数 (DeFi=1.5, L1=1.2, 稳定=1.0)
COIN_CFG = {
    # 防御
    'BTC':  (1.00, 2016, 430, 1.00),
    'ETH':  (1.20, 2016, 10, 1.10),
    'OKB':  (1.30, 2018, 1.0, 1.20),
    # L1 公链
    'SOL':  (1.80, 2020, 0.80, 1.40),
    'ADA':  (1.50, 2017, 0.03, 1.30),
    'AVAX': (1.60, 2020, 3.50, 1.40),
    'DOT':  (1.40, 2020, 3.00, 1.30),
    'NEAR': (1.70, 2020, 1.50, 1.40),
    'APT':  (1.50, 2022, 4.00, 1.40),
    'SUI':  (1.80, 2023, 1.20, 1.50),
    'SEI':  (1.60, 2023, 0.20, 1.50),
    'TON':  (1.40, 2018, 1.50, 1.20),
    'TRX':  (0.90, 2017, 0.002, 1.10),
    # L2
    'ARB':  (1.50, 2021, 1.50, 1.40),
    'OP':   (1.40, 2021, 1.50, 1.35),
    'MATIC':(1.30, 2017, 0.01, 1.30),
    'MANTA':(1.50, 2024, 0.80, 1.50),
    'STRK': (1.40, 2024, 1.20, 1.45),
    'METIS':(1.30, 2021, 2.00, 1.30),
    # DeFi
    'UNI':  (1.40, 2020, 3.00, 1.30),
    'LINK': (1.20, 2017, 0.15, 1.20),
    'AAVE': (1.30, 2020, 50, 1.25),
    'MKR':  (1.10, 2016, 15, 1.15),
    'SNX':  (1.50, 2018, 0.15, 1.35),
    'COMP': (1.40, 2018, 80, 1.30),
    'CRV':  (1.60, 2020, 3.00, 1.40),
    'DYDX': (1.70, 2021, 8.00, 1.50),
    '1INCH':(1.30, 2020, 1.50, 1.25),
    'ENS':  (1.20, 2021, 20, 1.20),
    'LDO':  (1.50, 2020, 2.00, 1.40),
    'JUP':  (1.60, 2024, 0.60, 1.50),
    # AI
    'FET':  (1.80, 2019, 0.008, 1.50),
    'RENDER':(1.70, 2020, 0.05, 1.45),
    'TAO':  (2.00, 2023, 30, 1.60),
    'RNDR': (1.70, 2020, 0.05, 1.45),
    'AKT':  (1.50, 2021, 1.50, 1.40),
    'PHB':  (1.40, 2021, 0.15, 1.30),
    # 模块化
    'TIA':  (1.80, 2023, 2.00, 1.55),
    'DYM':  (1.60, 2024, 2.50, 1.50),
    'PAS':  (1.50, 2024, 0.50, 1.45),
    # DePIN
    'HNT':  (1.50, 2019, 1.50, 1.40),
    'PEAQ': (1.40, 2024, 0.10, 1.50),
    # 存储
    'FIL':  (1.40, 2020, 25, 1.35),
    'AR':   (1.30, 2020, 0.20, 1.25),
    'BLZ':  (1.30, 2018, 0.10, 1.30),
    # GameFi
    'AXS':  (1.80, 2018, 0.10, 1.50),
    'GALA': (1.70, 2020, 0.002, 1.50),
    'IMX':  (1.40, 2021, 0.80, 1.35),
    'ILV':  (1.80, 2021, 50, 1.60),
    'BEAM': (1.50, 2022, 0.01, 1.45),
    # 隐私
    'ZEC':  (1.00, 2016, 400, 1.10),
    'DASH': (0.95, 2014, 5, 1.05),
    'SECRET':(1.30, 2020, 1.00, 1.30),
    # RWA
    'ONDO':  (1.20, 2024, 0.10, 1.20),
    'MANTRA':(1.30, 2024, 0.02, 1.30),
    'POLYX':(1.10, 2022, 0.20, 1.15),
    'RIO':  (1.20, 2021, 0.50, 1.20),
}


def generate(output_path=None):
    if output_path is None:
        output_path = os.path.join(DATA, 'weekly_adjclose_crypto50.csv')

    # 1. 生成 BTC 周线
    start_date = datetime(2016, 1, 1)
    end_date = datetime(2025, 12, 31)
    cur = start_date
    while cur.weekday() != 4:
        cur += timedelta(days=1)

    # BTC 指数插值
    pts = []
    for row in BTC_ANCHORS:
        d = datetime.strptime(row[0], '%Y-%m-%d')
        pts.append((d, row[1]))

    weekly_dates = []
    while cur <= end_date:
        weekly_dates.append(cur)
        cur += timedelta(weeks=1)

    # BTC 价格生成
    btc_prices = []
    for w in weekly_dates:
        before, after = None, None
        for d, v in pts:
            if d <= w: before = (d, v)
            if d >= w and after is None: after = (d, v)
        if before is None and after is not None:
            before = (after[0] - timedelta(days=365), after[1] * 0.5)
        if after is None and before is not None:
            after = (before[0] + timedelta(days=365), before[1] * 2.0)
        if before is None: continue
        total_span = (after[0] - before[0]).days
        elapsed = (w - before[0]).days
        frac = max(0, min(1, elapsed / total_span)) if total_span > 0 else 0.5
        log_p = math.log(before[1]) * (1 - frac) + math.log(after[1]) * frac
        base_price = math.exp(log_p)
        btc_prices.append(base_price)

    # 2. 为每个代币生成价格
    all_coins = sorted(COIN_CFG.keys())
    coin_prices = {c: [] for c in all_coins}

    for t in range(len(weekly_dates)):
        year = weekly_dates[t].year
        for c in all_coins:
            beta, launch_year, base_price, vol_mult = COIN_CFG[c]
            if year < launch_year:
                coin_prices[c].append(None)
                continue
            # 上线第一周: 用 base_price
            if year == launch_year and t > 0 and coin_prices[c][t-1] is None:
                coin_prices[c].append(base_price)
                continue
            if t == 0:
                coin_prices[c].append(base_price if year >= launch_year else None)
                continue
            # 正常计算: BTC 周收益率 × beta + 赛道噪声
            btc_ret = (btc_prices[t] / btc_prices[t-1] - 1) if btc_prices[t-1] > 0 else 0
            noise = np.random.normal(0, 0.03 * vol_mult)
            # beta 不对称: 下跌时 beta 更大 (加密市场下跌更猛)
            if btc_ret < 0:
                adj_beta = beta * (1 + 0.2 * min(abs(btc_ret), 0.3) / 0.3)
            else:
                adj_beta = beta
            ret = btc_ret * adj_beta + noise
            prev_p = coin_prices[c][t-1]
            if prev_p is None or prev_p <= 0:
                coin_prices[c].append(base_price)
            else:
                new_p = prev_p * (1 + ret)
                coin_prices[c].append(max(new_p, prev_p * 0.2))  # 最大单周跌 80%

    # 3. 写入 CSV
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date'] + all_coins)
        for t in range(len(weekly_dates)):
            row = [weekly_dates[t].strftime('%Y-%m-%d')]
            for c in all_coins:
                p = coin_prices[c][t]
                if p is None:
                    row.append('')
                elif p < 0.01:
                    row.append(f"{p:.6f}")
                elif p < 1:
                    row.append(f"{p:.4f}")
                else:
                    row.append(f"{p:.2f}")
            writer.writerow(row)

    n = len(weekly_dates)
    print(f"  Crypto50 合成数据: {n} 周 ({weekly_dates[0].strftime('%Y-%m-%d')} ~ {weekly_dates[-1].strftime('%Y-%m-%d')})")
    print(f"  BTC: {btc_prices[0]:.0f} -> {btc_prices[-1]:.0f}")
    n_valid = sum(1 for c in all_coins if coin_prices[c][-1] is not None)
    print(f"  有效代币 (末期): {n_valid}/{len(all_coins)}")
    print(f"  已保存: {output_path}")
    return output_path


if __name__ == '__main__':
    generate()
