"""
index_buyhold.py — 指数型买入持有(buy & hold)基准回测
==========================================================
与动量择时策略(crypto_options_bt.py)不同: 本脚本不做择时, 而是
把池子里【所有代币】按指数权重配齐、一次性买入、长期持有, 看不同
持有期限的收益分布。

两种权重:
  - equal : 等权(对应"统一购买", 每币买一样多)
  - cap   : 市值加权(对应"按指数排列", 用当前市值快照做固定权重;
            注意=近似, 真实指数会定期再平衡, 但"持有"语义下不调仓)

方法:
  对每个历史周五 t0, 取 t0 当日有价格的代币建篮, 按权重买入并持有
  H 周(3y=156 / 5y=260 / 10y=520), 计算累计倍数 = sum_i w_i * P_i(t)/P_i(t0)。
  若数据在 H 周前结束, 则截到最后一个可用周五(实际持有年限会短于目标)。

数据: data/weekly_adjclose_crypto50.csv (52 币, 2017-08 ~ 2026-08, 周线周五)
      市值快照: mcap_snapshot.json
"""
import pandas as pd
import numpy as np
import json
import sys

PANEL = 'data/weekly_adjclose_crypto50.csv'
HORIZONS = {'3y': 156, '5y': 260, '10y': 520}
WEEKS_PER_YEAR = 52.0


def load():
    px = pd.read_csv(PANEL, index_col=0, parse_dates=True)
    mc = {d['sym']: (d.get('mcap') or 0) for d in json.load(open('mcap_snapshot.json'))}
    return px, mc


def top_n_set(mc, n=10):
    """当前市值快照排名前 n 的代币集合(剔除 mcap<=0)。"""
    items = sorted(((s, m) for s, m in mc.items() if m > 0), key=lambda x: -x[1])
    return set(s for s, _ in items[:n])


def basket_weights(tradable, scheme, mc):
    if scheme == 'equal':
        return {c: 1.0 / len(tradable) for c in tradable}
    # cap weighted (fixed snapshot weights)
    caps = {c: mc.get(c, 0) for c in tradable}
    tot = sum(caps.values())
    if tot <= 0:
        return {c: 1.0 / len(tradable) for c in tradable}
    return {c: caps[c] / tot for c in tradable}


def nav_from(px, mc, t0_idx, scheme, hold_wks, rebal=False, topn=None):
    t0 = px.index[t0_idx]
    tradable = [c for c in px.columns if pd.notna(px[c].iloc[t0_idx]) and px[c].iloc[t0_idx] > 0]
    if topn:
        top = top_n_set(mc, topn)
        tradable = [c for c in tradable if c in top]
    if not tradable:
        return None
    w = basket_weights(tradable, scheme, mc)
    end_idx = min(t0_idx + hold_wks, len(px) - 1)

    if rebal:
        # 周平衡(向量化): 每周组合收益 = 成分币当周回报的等权平均(买入时篮子固定, 每周调回等权)
        # 某币某周缺失(NaN)则不算入该周平均; 整周全缺失(极罕见)则该周收益取 1(跳过)
        sub = px.iloc[t0_idx:end_idx + 1][tradable].astype(float)
        vals = sub.values
        if vals.shape[0] < 2:
            return None
        with np.errstate(divide='ignore', invalid='ignore'):
            ret = vals[1:] / vals[:-1]
        wk_ret = np.nanmean(ret, axis=1)
        wk_ret = np.where(np.isnan(wk_ret), 1.0, wk_ret)
        nav = float(np.prod(wk_ret))
        if not np.isfinite(nav) or nav <= 0:
            return None
        held_years = (px.index[end_idx] - t0).days / 365.25
        return nav, held_years, len(tradable)

    # 不调仓 (buy & hold): 权重随价格漂移
    p0 = px.loc[t0, tradable]
    pend = px.iloc[end_idx][tradable]
    nav = 0.0
    n = 0
    for c in tradable:
        if pd.notna(pend[c]) and pd.notna(p0[c]) and p0[c] > 0:
            nav += w[c] * (pend[c] / p0[c])
            n += 1
    if nav <= 0 or n == 0:
        return None
    held_years = (px.index[end_idx] - t0).days / 365.25
    return nav, held_years, n


def full_nav_series(px, mc, scheme, rebal=False, t0_idx=0, topn=None):
    """从 t0_idx 买入、持有至终的 NAV 时间序列(重基=1)。"""
    t0 = px.index[t0_idx]
    tradable = [c for c in px.columns if pd.notna(px[c].iloc[t0_idx]) and px[c].iloc[t0_idx] > 0]
    if topn:
        top = top_n_set(mc, topn)
        tradable = [c for c in tradable if c in top]
    w = basket_weights(tradable, scheme, mc)
    if rebal:
        # 周平衡等权(向量化): 每周组合收益 = 成分币周回报等权平均
        series = [np.nan] * t0_idx
        sub = px.iloc[t0_idx:][tradable].astype(float)
        vals = sub.values
        if vals.shape[0] < 2:
            return pd.Series([np.nan] * len(px), index=px.index, name=f'{scheme}_rebal_nav')
        with np.errstate(divide='ignore', invalid='ignore'):
            ret = vals[1:] / vals[:-1]
        wk_ret = np.nanmean(ret, axis=1)
        wk_ret = np.where(np.isnan(wk_ret), 1.0, wk_ret)
        navs = np.cumprod(wk_ret)
        out = np.concatenate([[1.0], navs])
        full = list(series) + list(out)
        return pd.Series(full[:len(px)], index=px.index, name=f'{scheme}_rebal_nav')
    # 不调仓
    p0 = px.loc[t0, tradable]
    series = []
    for i in range(len(px)):
        pend = px.iloc[i][tradable]
        nav = sum(w[c] * (pend[c] / p0[c]) for c in tradable
                  if pd.notna(pend[c]) and pd.notna(p0[c]) and p0[c] > 0)
        series.append(nav if nav > 0 else np.nan)
    return pd.Series(series, index=px.index, name=f'{scheme}_nav')


def main():
    px, mc = load()
    print(f'面板: {PANEL}  代币列={px.shape[1]}  区间={px.index[0].date()} ~ {px.index[-1].date()} '
          f'({(px.index[-1]-px.index[0]).days/365.25:.1f}年)')
    print('=' * 78)

    schemes = [
        ('equal', '等权(统一购买, 不调仓)', False, None),
        ('equal', '等权周平衡(每周调回等权)', True, None),
        ('cap', '市值加权(按指数, 不调仓)', False, None),
        ('equal', '市值前10·等权(不调仓)', False, 10),
        ('cap', '市值前10·市值加权(不调仓)', False, 10),
    ]
    for scheme, label, rebal, topn in schemes:
        print(f'\n### {label} ###' + (f'  [topn={topn}]' if topn else ''))
        for hlabel, wks in HORIZONS.items():
            rets = []
            for i in range(len(px)):
                r = nav_from(px, mc, i, scheme, wks, rebal=rebal, topn=topn)
                if r is None:
                    continue
                nav, hy, n = r
                rets.append((nav, hy, n))
            if not rets:
                print(f'  {hlabel}: 无样本')
                continue
            mults = np.array([x[0] for x in rets])
            held = np.array([x[1] for x in rets])
            pos = np.mean(mults > 1) * 100
            cap_note = ''
            if held.max() < (wks / WEEKS_PER_YEAR - 0.3):
                cap_note = f'  [数据上限: 实际最长持有 {held.max():.1f}y]'
            print(f'  {hlabel}: 样本={len(rets):>3}  中位倍数={np.median(mults):8.2f}x  '
                  f'中位收益={np.median(mults-1)*100:7.1f}%  正收益={pos:4.0f}%  '
                  f'最佳={mults.max():8.1f}x  最差={mults.min():7.2f}x{cap_note}')

        # 首日期买入持有至终
        r = nav_from(px, mc, 0, scheme, 100000, rebal=rebal, topn=topn)
        if r:
            nav, hy, n = r
            tag = '周平衡' if rebal else '不调仓'
            print(f'  首日期(2017-08-11)买入持有至终({hy:.1f}y): {nav:.1f}x  (含{n}币, {tag})')

    # 输出 NAV 序列供画图
    if '--nav' in sys.argv:
        for scheme, _, rebal in schemes:
            s = full_nav_series(px, mc, scheme, rebal=rebal)
            tag = 'rebal' if rebal else scheme
            s.to_csv(f'index_nav_{tag}.csv', header=True)
        print('\n已输出 index_nav_equal.csv / index_nav_rebal.csv / index_nav_cap.csv')


if __name__ == '__main__':
    main()
