"""
portfolio_blend.py — 跨市场组合层原型 (mx_auto_strategy)
========================================================
把三个子系统的周度 NAV 回测产出, 对齐到共同周网格, 拼出跨市场组合层,
论证"分散配置"能在不牺牲太多收益的前提下压低整体回撤。

输入 (均经真实性校验):
  - A股 : docs/data/nav.json  windows['full']['optimized']['mult']  (全长 33x, 上海东方财富后复权干净面板)
  - 美股 : us_stocks/data/us_nav_ai.csv  optimized_ai_nav           (22~23x, 真实面板)
  - 加密 : crypto_stocks/backtest_v2.py 真数据重算                   (进攻 100.6x / 防御 40.7x, Binance/OKX 真实周K线)

★ 诚实口径:
  - 加密真实倍数含幸存者偏差(现存主流币清单, 死币未纳入→偏高); 真实数据仅 2017 起。
  - 本原型为方法论证, 非未来业绩承诺。
  - 三序列周收盘日不同(A股周四/美股周一/加密周五), 统一 resample 到 W-FRI 再 inner join。
"""
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_series():
    # ---- A股 ----
    d = json.load(open(os.path.join(ROOT, 'docs/data/nav.json')))
    w = d['windows']['full']['optimized']
    ash = pd.Series(w['mult'], index=pd.to_datetime(w['dates']), name='A股')

    # ---- 美股 ----
    us = pd.read_csv(os.path.join(ROOT, 'us_stocks/data/us_nav_ai.csv'),
                     parse_dates=['date']).set_index('date')['optimized_ai_nav'].rename('美股')

    # ---- 加密 (真实重算, 规避陈旧合成 JSON) ----
    sys.path.insert(0, os.path.join(ROOT, 'crypto_stocks'))
    import backtest_v2 as b2
    px = b2._load_default()
    atk = b2.run_backtest(px, offense_n=3, label='加密_进攻')['nav'].rename('加密_进攻')
    dfn = b2.run_backtest(px, offense_n=3, vol_target=0.60,
                          crash_guard={'thr': -0.15, 'floor': 0.40},
                          label='加密_防御')['nav'].rename('加密_防御')

    raw = pd.concat([ash, us, atk, dfn], axis=1, sort=False)
    # 统一到周五周网格, 再 inner join
    raw = raw.resample('W-FRI').last().ffill()
    df = raw.dropna()
    # 全部归一化到 1.0 起点
    for c in df.columns:
        df[c] = df[c] / df[c].iloc[0]
    return df


def metrics(nav: pd.Series):
    nav = nav / nav.iloc[0]
    rets = nav.pct_change().dropna()
    weeks = len(rets)
    mult = float(nav.iloc[-1])
    cagr = float(nav.iloc[-1] ** (52.0 / weeks) - 1.0) if weeks > 0 else 0.0
    mdd = float((nav / nav.cummax() - 1.0).min())
    sharpe = float(rets.mean() / rets.std() * np.sqrt(52)) if rets.std() > 0 else 0.0
    return {'multiple': mult, 'cagr': cagr, 'mdd': mdd, 'sharpe': sharpe}


def blend_equal(df, cols, w=None):
    rets = df[cols].pct_change().fillna(0.0)
    if w is None:
        w = pd.Series(1.0 / len(cols), index=cols)
    port = (rets * w).sum(axis=1)
    return (1.0 + port).cumprod()


def blend_volparity(df, cols, warmup=52):
    rets = df[cols].pct_change().fillna(0.0)
    vol = rets.rolling(warmup).std().shift(1)           # 用 t-1 及之前, 防前视
    inv = 1.0 / vol
    w = inv.div(inv.sum(axis=1), axis=0)                # 每周再平衡到逆波动权重
    w = w.fillna(1.0 / len(cols))                        # 预热期回退等权
    port = (rets * w).sum(axis=1)
    return (1.0 + port).cumprod()


def main():
    df = load_series()
    print(f"共同周网格: {df.index[0].date()} ~ {df.index[-1].date()}  共 {len(df)} 周")
    print("=" * 78)

    # 单市场 (共同窗口)
    print("【单市场 · 共同窗口 2017-08~2026-07】")
    single = {}
    for c in df.columns:
        m = metrics(df[c])
        single[c] = m
        print(f"  {c:10s}  倍数 {m['multiple']:7.2f}x  CAGR {m['cagr']*100:5.1f}%  "
              f"MDD {m['mdd']*100:6.1f}%  Sharpe {m['sharpe']:.2f}")
    print("-" * 78)

    # 组合层 (加密用防御档 40.7x 作为主腿; 进攻档仅作激进对照)
    crypto_def = '加密_防御'
    schemes = {
        '等权(1/3, 防御加密)':  blend_equal(df, ['A股', '美股', crypto_def]),
        '波动平价(防御加密)':   blend_volparity(df, ['A股', '美股', crypto_def]),
        '稳健倾斜(.4/.4/.2)':  blend_equal(df, ['A股', '美股', crypto_def],
                                          w=pd.Series({'A股': .4, '美股': .4, crypto_def: .2})),
        '等权(1/3, 进攻加密)':  blend_equal(df, ['A股', '美股', '加密_进攻']),
    }
    print("【组合层 · 跨市场分散】")
    blends = {}
    for name, nav in schemes.items():
        m = metrics(nav)
        blends[name] = m
        print(f"  {name:22s} 倍数 {m['multiple']:7.2f}x  CAGR {m['cagr']*100:5.1f}%  "
              f"MDD {m['mdd']*100:6.1f}%  Sharpe {m['sharpe']:.2f}")
    print("=" * 78)

    # 导出 JSON (供 curves 站渲染)
    out = {
        'common_window': [str(df.index[0].date()), str(df.index[-1].date())],
        'n_weeks': len(df),
        'single': {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv)
                       for kk, vv in v.items()} for k, v in single.items()},
        'blends': {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv)
                      for kk, vv in v.items()} for k, v in blends.items()},
        'nav': {
            'dates': [str(d) for d in df.index],
            'series': {c: [round(float(x), 4) for x in df[c].values] for c in df.columns},
            'blend_nav': {name: [round(float(x), 4) for x in nav.values]
                          for name, nav in schemes.items()},
        },
    }
    os.makedirs(os.path.join(ROOT, 'docs/data'), exist_ok=True)
    with open(os.path.join(ROOT, 'docs/data/portfolio_blend.json'), 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("已写出 docs/data/portfolio_blend.json")
    return out


if __name__ == '__main__':
    main()
