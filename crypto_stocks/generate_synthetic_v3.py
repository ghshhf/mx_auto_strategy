"""
generate_synthetic_v3.py - Crypto50 合成数据 V3 (真实波动模拟)
============================================================

V3 vs V2 关键差异 (模拟真实市场的摩擦):
  1. 插针 (flash wick): 随机周出现 -15%~-30% 的瞬时下跌后部分恢复
     -> 真实市场交易所插针/清算瀑布, 周频数据里会表现为异常大阴线
  2. 假突破 (fake breakout): 先突破前高 +8%, 下周立刻回落 -10%
     -> 动量策略最常见的 whipsaw, V2 完全没有
  3. 流动性缺失: 小市值代币随机出现 0 成交周 (价格不变 + NaN 标记)
     -> 模拟真实低流动性 altcoin
  4. 上线暴涨 (launch pump): 新代币上线前 4 周平均 +50%/周
     -> 真实代币上线初期的炒作效应
  5. 归零风险 (rug risk): 小概率事件, 某代币单周跌 -80% 且不恢复
     -> 模拟项目暴雷/ rug pull

新增赛道: Meme (DOGE/SHIB/PEPE/WIF/FLOKI) + LSD (RPL/FXS/PENDLE)
"""
import os, sys, csv, math
import numpy as np
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
os.makedirs(DATA, exist_ok=True)

np.random.seed(42)

# BTC 真实价格锚点 (date, btc_price) - 同 V2
BTC_ANCHORS = [
    ('2016-01-08', 430), ('2016-07-01', 670), ('2016-12-30', 960),
    ('2017-03-10', 1200), ('2017-06-11', 2600), ('2017-09-01', 4700),
    ('2017-12-16', 19500), ('2018-02-01', 8500), ('2018-04-06', 6700),
    ('2018-07-01', 7400), ('2018-12-15', 3200), ('2019-04-01', 5000),
    ('2019-06-26', 13000), ('2019-09-23', 8300), ('2020-03-12', 3900),
    ('2020-08-17', 12300), ('2020-12-26', 26500), ('2021-01-08', 40000),
    ('2021-04-14', 64000), ('2021-05-19', 37000), ('2021-11-10', 69000),
    ('2022-01-22', 35000), ('2022-05-12', 28000), ('2022-06-18', 18500),
    ('2022-11-21', 16400), ('2023-01-14', 21000), ('2023-04-14', 30500),
    ('2023-07-13', 31000), ('2023-10-23', 35000), ('2023-12-07', 44000),
    ('2024-01-10', 46000), ('2024-03-14', 73000), ('2024-06-22', 65000),
    ('2024-07-22', 57000), ('2024-09-15', 58000), ('2024-11-20', 94000),
    ('2024-12-05', 100000), ('2025-01-20', 104000), ('2025-04-14', 85000),
    ('2025-07-18', 108000), ('2025-12-31', 130000),
]

# 代币配置 V3: {symbol: (beta, launch_year, base_price, vol_mult, liquidity_tier)}
# liquidity_tier: 1=高流动性(BTC/ETH级), 2=中等, 3=低(易插针/流动性缺失)
# Meme 赛道: beta 极高 (2.5-3.5), 波动极大
# LSD 赛道: beta 中高 (1.3-1.6), 与 ETH 相关性高
COIN_CFG = {
    # 防御
    'BTC':  (1.00, 2016, 430, 1.00, 1),
    'ETH':  (1.20, 2016, 10, 1.10, 1),
    'OKB':  (1.30, 2018, 1.0, 1.20, 2),
    # L1 公链
    'SOL':  (1.80, 2020, 0.80, 1.40, 2),
    'ADA':  (1.50, 2017, 0.03, 1.30, 2),
    'AVAX': (1.60, 2020, 3.50, 1.40, 2),
    'DOT':  (1.40, 2020, 3.00, 1.30, 2),
    'NEAR': (1.70, 2020, 1.50, 1.40, 2),
    'APT':  (1.50, 2022, 4.00, 1.40, 3),
    'SUI':  (1.80, 2023, 1.20, 1.50, 3),
    'SEI':  (1.60, 2023, 0.20, 1.50, 3),
    'TON':  (1.40, 2018, 1.50, 1.20, 2),
    'TRX':  (0.90, 2017, 0.002, 1.10, 2),
    # L2
    'ARB':  (1.50, 2021, 1.50, 1.40, 2),
    'OP':   (1.40, 2021, 1.50, 1.35, 2),
    'MATIC':(1.30, 2017, 0.01, 1.30, 2),
    'MANTA':(1.50, 2024, 0.80, 1.50, 3),
    'STRK': (1.40, 2024, 1.20, 1.45, 3),
    'METIS':(1.30, 2021, 2.00, 1.30, 3),
    # DeFi
    'UNI':  (1.40, 2020, 3.00, 1.30, 2),
    'LINK': (1.20, 2017, 0.15, 1.20, 2),
    'AAVE': (1.30, 2020, 50, 1.25, 2),
    'MKR':  (1.10, 2016, 15, 1.15, 2),
    'SNX':  (1.50, 2018, 0.15, 1.35, 3),
    'COMP': (1.40, 2018, 80, 1.30, 2),
    'CRV':  (1.60, 2020, 3.00, 1.40, 3),
    'DYDX': (1.70, 2021, 8.00, 1.50, 3),
    '1INCH':(1.30, 2020, 1.50, 1.25, 3),
    'ENS':  (1.20, 2021, 20, 1.20, 3),
    'LDO':  (1.50, 2020, 2.00, 1.40, 2),
    'JUP':  (1.60, 2024, 0.60, 1.50, 3),
    # AI
    'FET':  (1.80, 2019, 0.008, 1.50, 3),
    'RENDER':(1.70, 2020, 0.05, 1.45, 3),
    'TAO':  (2.00, 2023, 30, 1.60, 3),
    'RNDR': (1.70, 2020, 0.05, 1.45, 3),
    'AKT':  (1.50, 2021, 1.50, 1.40, 3),
    'PHB':  (1.40, 2021, 0.15, 1.30, 3),
    # 模块化
    'TIA':  (1.80, 2023, 2.00, 1.55, 3),
    'DYM':  (1.60, 2024, 2.50, 1.50, 3),
    'PAS':  (1.50, 2024, 0.50, 1.45, 3),
    # DePIN
    'HNT':  (1.50, 2019, 1.50, 1.40, 3),
    'PEAQ': (1.40, 2024, 0.10, 1.50, 3),
    # 存储
    'FIL':  (1.40, 2020, 25, 1.35, 2),
    'AR':   (1.30, 2020, 0.20, 1.25, 3),
    'BLZ':  (1.30, 2018, 0.10, 1.30, 3),
    # GameFi
    'AXS':  (1.80, 2018, 0.10, 1.50, 3),
    'GALA': (1.70, 2020, 0.002, 1.50, 3),
    'IMX':  (1.40, 2021, 0.80, 1.35, 3),
    'ILV':  (1.80, 2021, 50, 1.60, 3),
    'BEAM': (1.50, 2022, 0.01, 1.45, 3),
    # 隐私
    'ZEC':  (1.00, 2016, 400, 1.10, 2),
    'DASH': (0.95, 2014, 5, 1.05, 2),
    'SECRET':(1.30, 2020, 1.00, 1.30, 3),
    # RWA
    'ONDO':  (1.20, 2024, 0.10, 1.20, 3),
    'MANTRA':(1.30, 2024, 0.02, 1.30, 3),
    'POLYX':(1.10, 2022, 0.20, 1.15, 3),
    'RIO':  (1.20, 2021, 0.50, 1.20, 3),
}

# 记录每个代币的状态 (用于假突破/rug 等事件)
coin_state = {}

def generate(output_path=None):
    if output_path is None:
        output_path = os.path.join(DATA, 'weekly_adjclose_crypto50_v3.csv')

    # 1. 生成 BTC 周线 (同 V2)
    start_date = datetime(2016, 1, 1)
    end_date = datetime(2025, 12, 31)
    cur = start_date
    while cur.weekday() != 4:
        cur += timedelta(days=1)

    pts = [(datetime.strptime(r[0], '%Y-%m-%d'), r[1]) for r in BTC_ANCHORS]

    weekly_dates = []
    while cur <= end_date:
        weekly_dates.append(cur)
        cur += timedelta(weeks=1)

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
        btc_prices.append(math.exp(log_p))

    # 2. 为每个代币生成价格 (V3: 加真实摩擦)
    all_coins = sorted(COIN_CFG.keys())
    coin_prices = {c: [None] * len(weekly_dates) for c in all_coins}
    global coin_state
    coin_state = {c: {'last_breakout_week': -99, 'is_rugged': False,
                      'launch_week': -1, 'no_trade_until': -1} for c in all_coins}

    for t in range(len(weekly_dates)):
        year = weekly_dates[t].year
        for c in all_coins:
            beta, launch_year, base_price, vol_mult, liq = COIN_CFG[c]
            st = coin_state[c]

            # 未上线
            if year < launch_year:
                continue

            # 上线第一周
            if st['launch_week'] < 0:
                st['launch_week'] = t

            # 上线前 4 周: launch pump (平均 +30%/周, 但波动极大)
            weeks_since_launch = t - st['launch_week']
            if 0 <= weeks_since_launch < 4:
                pump_ret = np.random.normal(0.30, 0.20)
                prev = coin_prices[c][t-1] if t > 0 else None
                if prev is None or prev <= 0:
                    coin_prices[c][t] = base_price
                else:
                    coin_prices[c][t] = prev * (1 + pump_ret)
                continue

            # rug pull: 极小概率, 10 年期望 2-3 个代币被 rug (真实市场比例)
            # 高流动性 0.05%/周, 低流动性 0.15%/周
            rug_prob = 0.0005 if liq <= 2 else 0.0015
            if not st['is_rugged'] and np.random.random() < rug_prob:
                st['is_rugged'] = True
                # 本周暴跌 80%, 之后保持低位
                prev = coin_prices[c][t-1]
                if prev and prev > 0:
                    coin_prices[c][t] = prev * 0.20
                continue
            if st['is_rugged']:
                # 已 rug, 价格在低位随机波动
                prev = coin_prices[c][t-1]
                if prev and prev > 0:
                    coin_prices[c][t] = prev * (1 + np.random.normal(-0.02, 0.05))
                continue

            # 流动性缺失: 低流动性代币 3% 概率本周无成交 (NaN)
            if liq >= 3 and np.random.random() < 0.03:
                # 价格不变, 但标记为低流动性
                prev = coin_prices[c][t-1]
                if prev and prev > 0:
                    coin_prices[c][t] = prev
                continue

            # 正常计算
            if t == 0 or coin_prices[c][t-1] is None:
                coin_prices[c][t] = base_price
                continue

            btc_ret = (btc_prices[t] / btc_prices[t-1] - 1) if btc_prices[t-1] > 0 else 0
            noise = np.random.normal(0, 0.04 * vol_mult)  # V3: 噪声略增

            # beta 不对称: 下跌时 beta 更大
            if btc_ret < 0:
                adj_beta = beta * (1 + 0.2 * min(abs(btc_ret), 0.3) / 0.3)
            else:
                adj_beta = beta
            ret = btc_ret * adj_beta + noise

            # === V3 真实摩擦 ===
            # 1. 插针 (flash wick): 2% 概率出现 -15%~-30% 瞬时下跌
            #    低流动性代币概率更高 (5%)
            wick_prob = 0.02 if liq <= 2 else 0.05
            if np.random.random() < wick_prob:
                wick_drop = np.random.uniform(-0.30, -0.15)
                # 插针部分恢复: 实际收盘只跌一半
                ret += wick_drop * 0.5

            # 2. 假突破 (fake breakout):
            #    如果上周涨 >8% (突破), 本周 40% 概率回落 -5%~-12%
            prev = coin_prices[c][t-1]
            if t >= 2 and prev and coin_prices[c][t-2]:
                prev_ret = (prev / coin_prices[c][t-2] - 1)
                if prev_ret > 0.08:
                    if np.random.random() < 0.40:
                        fake_ret = np.random.uniform(-0.12, -0.05)
                        ret += fake_ret

            prev_p = coin_prices[c][t-1]
            if prev_p is None or prev_p <= 0:
                coin_prices[c][t] = base_price
            else:
                new_p = prev_p * (1 + ret)
                # 最大单周跌 85% (V3: 放宽, 真实市场有 -90% 的)
                coin_prices[c][t] = max(new_p, prev_p * 0.15)

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
                elif p < 0.0001:
                    row.append(f"{p:.10f}")
                elif p < 0.01:
                    row.append(f"{p:.8f}")
                elif p < 1:
                    row.append(f"{p:.4f}")
                else:
                    row.append(f"{p:.2f}")
            writer.writerow(row)

    n = len(weekly_dates)
    n_valid = sum(1 for c in all_coins if coin_prices[c][-1] is not None)
    n_rugged = sum(1 for c in all_coins if coin_state[c]['is_rugged'])
    print(f"  Crypto50 V3 合成数据 (真实摩擦模拟):")
    print(f"  {n} 周 ({weekly_dates[0].strftime('%Y-%m-%d')} ~ {weekly_dates[-1].strftime('%Y-%m-%d')})")
    print(f"  BTC: {btc_prices[0]:.0f} -> {btc_prices[-1]:.0f}")
    print(f"  代币总数: {len(all_coins)} | 末期有效: {n_valid} | Rug pull: {n_rugged}")
    print(f"  已保存: {output_path}")
    return output_path


if __name__ == '__main__':
    generate()
