# -*- coding: utf-8 -*-
"""周期与耐心量化 —— 把「老牌项目兑现要 4~8 年，但人连 2~3 年都熬不住」做成可检验的数字。

四段:
  A 两轮周期恢复检验    前高 → 创新高 历时 / 底部深度 / 底→今 与 前高→今 的「晚买代价」
  B 全程水下时长        低于历史最高的时间占比 / 最长连续水下 / 跌破 -50% 的时间占比
  C 滚动持有期亏损概率   持有 N 周后仍为负的概率（逐币 + 分组中位）
  D ZEC 路径拆解        底 → 突破前高 → 用户买入价；「等确认再买」只剩多少

只读 data/weekly_adjclose_crypto50_10y.csv，不写盘。
口径提醒: 面板日期标签比其承载价格早 9 天（见 PITFALLS / SKILL 五之二），
年际尺度可忽略；所有值均为后复权价，跨币不可直接比价格绝对值。
"""
import os
import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(_HERE, 'data', 'weekly_adjclose_crypto50_10y.csv')

HORIZONS = [(1, '1周'), (4, '1月'), (13, '3月'), (26, '6月'), (52, '1年'),
            (104, '2年'), (156, '3年'), (208, '4年'), (260, '5年')]
CYCLES = [('2017-01-01', '2018-12-31', 'C1-2017牛'),
          ('2020-06-01', '2022-12-31', 'C2-2021牛')]


def load():
    return pd.read_csv(PANEL, index_col=0, parse_dates=True).sort_index()


def cycle_stat(s, hw0, hw1):
    """在前高窗口 [hw0,hw1] 找最高价 H，之后找第一次 >= H 的日期作为创新高日。

    返回 dict；recovered=False 表示至今未回本（years 为「已等年数」）。
    """
    w = s.loc[hw0:hw1]
    if len(w) < 5:
        return None
    hd, hv = w.idxmax(), float(w.max())
    after = s.loc[hd:].iloc[1:]
    if len(after) < 5:
        return None
    rec = after[after >= hv]
    if len(rec):
        rd = rec.index[0]
        seg = after.loc[:rd]
        recovered = True
    else:
        rd = None
        seg = after
        recovered = False
    low = float(seg.min())
    low_d = seg.idxmin()
    endp = rd if recovered else s.index[-1]
    now = float(s.iloc[-1])
    return dict(h_date=hd.date(), high=hv, low_date=low_d.date(), low=low,
                depth=low / hv - 1.0, recover_date=(rd.date() if recovered else None),
                years=(endp - hd).days / 365.25, recovered=recovered,
                years_to_low=(low_d - hd).days / 365.25,
                mult_from_low=now / low, mult_from_high=now / hv,
                late_ratio=(now / hv) / (now / low))


def cycles(px):
    rows = []
    for c in px.columns:
        s = px[c].dropna()
        for a, b, lab in CYCLES:
            r = cycle_stat(s, a, b)
            if r:
                r['coin'] = c
                r['cyc'] = lab
                rows.append(r)
    return pd.DataFrame(rows)


def underwater(px, min_len=60):
    """全程「低于历史最高价」的时间占比 + 最长连续水下 + 跌破 -50% 时间占比。"""
    out = []
    for c in px.columns:
        s = px[c].dropna()
        if len(s) < min_len:
            continue
        runmax = s.cummax()
        under = (s < runmax * 0.999).values
        deep = (s < runmax * 0.5).values
        best = cur = 0
        for u in under:
            cur = cur + 1 if u else 0
            best = max(best, cur)
        out.append(dict(coin=c, weeks=len(s), years=len(s) * 7 / 365.25,
                        under_frac=float(under.mean()), deep_frac=float(deep.mean()),
                        longest_w=best, longest_y=best * 7 / 365.25))
    return pd.DataFrame(out)


def rolling_loss(s, h):
    """h 周滚动持有 -> (亏钱概率, 收益中位, 样本数)。"""
    r = s.values[h:] / s.values[:-h] - 1.0
    return float((r < 0).mean()), float(np.median(r)), len(r)


def holding_loss(px, min_len=60):
    rows = {}
    for c in px.columns:
        s = px[c].dropna()
        if len(s) < min_len:
            continue
        d = {}
        for h, lab in HORIZONS:
            if len(s) > h + 20:
                d[lab] = rolling_loss(s, h)[0]
        if d:
            rows[c] = d
    tbl = pd.DataFrame(rows).T
    return tbl.reindex(columns=[lab for _, lab in HORIZONS])


def zec_path(px, coin='ZEC', buy='2026-08-25'):
    z = px[coin].dropna()
    info = dict(first_date=z.index[0].date(), first=float(z.iloc[0]),
                last_date=z.index[-1].date(), last=float(z.iloc[-1]),
                high=float(z.max()), high_date=z.idxmax().date(),
                low=float(z.min()), low_date=z.idxmin().date())
    info['full_mult'] = info['last'] / info['first']
    info['low_to_now'] = info['last'] / info['low']
    return z, info


def _fmt(v):
    return '—' if v is None else f'{v:,.2f}'


def main():
    px = load()
    df = cycles(px)

    print('=' * 132)
    print('A. 两轮周期恢复检验（前高 → 创新高）')
    print('=' * 132)
    for lab in [c[2] for c in CYCLES]:
        d = df[df.cyc == lab]
        if not len(d):
            continue
        print(f'\n--- {lab} ---')
        t = d.copy()
        t['前高'] = t.high.map(lambda x: f'{x:,.2f}')
        t['底价'] = t.low.map(lambda x: f'{x:,.2f}')
        t['最深亏'] = (t.depth * 100).round(1).astype(str) + '%'
        t['高→底'] = t.years_to_low.round(2).astype(str) + 'y'
        t['前高→新高'] = np.where(t.recovered, t.years.round(2).astype(str) + '年',
                                 '未回本·已' + t.years.round(1).astype(str) + 'y')
        t['底→今'] = t.mult_from_low.round(2).astype(str) + 'x'
        t['前高→今'] = t.mult_from_high.round(2).astype(str) + 'x'
        t['晚买只剩'] = (t.late_ratio * 100).round(1).astype(str) + '%'
        cols = ['coin', 'h_date', '前高', 'low_date', '底价', '最深亏', '高→底',
                'recover_date', '前高→新高', '底→今', '前高→今', '晚买只剩']
        t = t[cols]
        t.columns = ['币', '前高日', '前高价', '底日', '底价', '最深亏', '高→底',
                     '创新高日', '前高→新高', '底→今', '前高→今', '晚买只剩']
        print(t.sort_values('高→底').to_string(index=False))
        rec = d[d.recovered]
        if len(rec):
            print(f'  汇总: 样本 {len(d)} 币, 已创新高 {len(rec)} 币; '
                  f'前高→新高 中位 {rec.years.median():.2f}年 区间 {rec.years.min():.2f}~{rec.years.max():.2f}年')
        print(f'  前高→底部 中位 {d.years_to_low.median():.2f}年; 底部深度中位 {d.depth.median() * 100:.1f}%')

    uw = underwater(px).sort_values('longest_y', ascending=False)
    print()
    print('=' * 132)
    print('B. 全程「低于历史最高价」的时间占比（熬的难度）')
    print('=' * 132)
    u = uw.copy()
    u['水下占比'] = (u.under_frac * 100).round(1).astype(str) + '%'
    u['最长连续水下'] = u.longest_y.round(2).astype(str) + '年'
    u['跌破-50%占比'] = (u.deep_frac * 100).round(1).astype(str) + '%'
    u['总历史'] = u.years.round(2).astype(str) + '年'
    print(u[['coin', '总历史', '水下占比', '最长连续水下', '跌破-50%占比']].to_string(index=False))
    print(f'\n  中位: 水下占比 {uw.under_frac.median() * 100:.1f}% | '
          f'最长连续水下 {uw.longest_y.median():.2f}年 | '
          f'跌破-50%占比 {uw.deep_frac.median() * 100:.1f}%')

    tbl = holding_loss(px)
    old = [c for c in px.columns
           if len(px[c].dropna()) >= 355 and px[c].dropna().index[0] <= pd.Timestamp('2019-12-31')]
    new = [c for c in tbl.index if px[c].dropna().index[0] > pd.Timestamp('2020-12-31')]
    print()
    print('=' * 132)
    print('C. 滚动持有期 → 亏钱概率（面板周频，全部滚动起点）')
    print('=' * 132)
    print((tbl * 100).round(1).to_string())
    grp = pd.DataFrame({
        'BTC': tbl.loc['BTC'],
        'ETH': tbl.loc['ETH'],
        f'老牌组中位({len([c for c in old if c in tbl.index])}币)': tbl.loc[[c for c in old if c in tbl.index]].median(),
        f'2021后上市中位({len(new)}币)': tbl.loc[new].median(),
        '全池中位': tbl.median(),
    })
    print('\n分组中位:')
    print((grp * 100).round(1).to_string())

    z, info = zec_path(px)
    print()
    print('=' * 132)
    print('D. ZEC 路径拆解')
    print('=' * 132)
    print(f"  面板 {info['first_date']} → {info['last_date']}  n={len(z)}")
    print(f"  首值 ${info['first']:,.2f} → 末值 ${info['last']:,.2f}  全程 {info['full_mult']:.2f}x")
    print(f"  最高 ${_fmt(info['high'])} @ {info['high_date']} | 最低 ${_fmt(info['low'])} @ {info['low_date']}")
    print(f"  底 → 末: {info['low_to_now']:.1f}x")


if __name__ == '__main__':
    main()
