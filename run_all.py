#!/usr/bin/env python
"""
run_all.py - 单次产出三市场权威真值 + 数字回归断言
=============================================================================
解决「真值碎片化」: 加密/A股/美股/跨市场组合各自的头条数字散落在
TRUTH_AUTHORITY.md / docs/TRUTH.md / README / nav_*.json 里, 改一次池子或
修一次数据要人肉同步十几处, 漏一处就出现「三份文档三个数字」。

本脚本:
  1. 依次跑各市场导出脚本, 产出/刷新 docs/data/*.json;
  2. 从产出里抽出**归一化的标量真值** (倍数 / MDD% / CAGR% / Sharpe);
  3. 与 reports/truth_baseline.json 比对, 超出容差即 FAIL 并退出码 1;
  4. 始终写 reports/truth_snapshot_<date>.json 留档。

归一化约定 (基线里存的单位):
  mult   = 倍数, 如 5630.11
  mdd    = 最大回撤百分数, 负数, 如 -70.4  (内部 -0.704 的会 ×100)
  cagr   = 年化百分数, 如 135.2          (内部 1.352 的会 ×100)
  sharpe = 比值, 如 1.60

用法:
  python run_all.py                    # 跑全部 + 回归断言
  python run_all.py --baseline         # 用本次结果刷新基线 (改池/修数据后必做)
  python run_all.py --only crypto,us   # 只跑指定市场
  python run_all.py --no-deep          # 跳过 reconcile(约 45s) 与组合层
  python run_all.py --tol-mult 0.05    # 放宽倍数容差到 5%

退出码: 0=通过  1=数字回归失败  2=子脚本执行失败
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(ROOT, 'docs', 'data')
REPORTS = os.path.join(ROOT, 'reports')
BASELINE = os.path.join(REPORTS, 'truth_baseline.json')

PY = sys.executable


# ---------------------------------------------------------------- 工具
def _run(script, cwd=ROOT, timeout=1800):
    """跑子脚本, 返回 (ok, 输出末行, 错误信息)."""
    try:
        r = subprocess.run([PY, script], cwd=cwd, capture_output=True,
                           text=True, encoding='utf-8', timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, '', f'超时 {timeout}s'
    out = (r.stdout or '') + (r.stderr or '')
    tail = [l for l in out.strip().splitlines() if l.strip()][-1:] or ['']
    if r.returncode != 0:
        return False, tail[0], out.strip().splitlines()[-1] if out.strip() else '未知错误'
    return True, tail[0], ''


def _load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _years(dates):
    """日期字符串列表 -> 年数 (用于从 mult 反算 CAGR)."""
    if not dates or len(dates) < 2:
        return 0.0
    d0 = dt.date.fromisoformat(dates[0][:10])
    d1 = dt.date.fromisoformat(dates[-1][:10])
    return max((d1 - d0).days / 365.25, 1e-9)


def _cagr(mult, yrs):
    return (mult ** (1 / yrs) - 1) * 100 if yrs > 0 and mult > 0 else 0.0


# ---------------------------------------------------------------- 市场定义
def _m_ashare(metrics, meta):
    """A股: docs/data/nav.json. 面板未入库时无法重跑 -> 抛 FileNotFoundError."""
    panel = os.path.join(ROOT, 'markets', 'ashare', 'data', 'ashare_panel_close_em.csv')
    if not os.path.exists(panel):
        raise FileNotFoundError(
            'A股面板缺失: markets/ashare/data/ashare_panel_close_em.csv '
            '(gitignore, 由 markets/ashare/tencent_hfq_rebuild.py 本地生成)')
    ok, tail, err = _run(os.path.join('markets', 'ashare', 'export_nav.py'))
    if not ok:
        raise RuntimeError(f'export_nav.py 失败: {err}')
    d = _load(os.path.join(DOCS, 'nav.json'))
    meta['ashare'] = {'generated_at': d.get('generated_at'), 'source': d.get('source'),
                      'last_date': d.get('last_date')}
    for w in ('10y', 'full'):
        for cfg in ('baseline', 'optimized'):
            node = d.get('windows', {}).get(w, {}).get(cfg)
            if not node or not node.get('mult'):
                continue
            mult = float(node['mult'][-1])
            mdd = min(node['dd']) * 100 if node.get('dd') else 0.0
            yrs = _years(node.get('dates', []))
            metrics[f'ashare.{w}.{cfg}.mult'] = round(mult, 4)
            metrics[f'ashare.{w}.{cfg}.mdd'] = round(mdd, 2)
            metrics[f'ashare.{w}.{cfg}.cagr'] = round(_cagr(mult, yrs), 2)


def _m_us(metrics, meta):
    """美股: docs/data/nav_us.json."""
    ok, tail, err = _run(os.path.join('markets', 'us', 'export_nav_us.py'))
    if not ok:
        raise RuntimeError(f'export_nav_us.py 失败: {err}')
    d = _load(os.path.join(DOCS, 'nav_us.json'))
    meta['us'] = {'generated_at': d.get('generated_at'), 'source': d.get('source'),
                  'last_date': d.get('last_date')}
    for k in ('no_options', 'options_sim'):
        t = d.get('truth', {}).get(k) or {}
        if 'final_mult' not in t:
            continue
        metrics[f'us.{k}.mult'] = round(float(t['final_mult']), 4)
        metrics[f'us.{k}.mdd'] = round(float(t.get('mdd', 0)), 2)
        metrics[f'us.{k}.cagr'] = round(float(t.get('cagr', 0)), 2)


def _m_crypto(metrics, meta):
    """加密: docs/data/nav_crypto.json (发布 NAV, cycle_overlay 口径)."""
    ok, tail, err = _run(os.path.join('markets', 'crypto', 'export_nav_crypto.py'))
    if not ok:
        raise RuntimeError(f'export_nav_crypto.py 失败: {err}')
    d = _load(os.path.join(DOCS, 'nav_crypto.json'))
    meta['crypto'] = {'generated_at': d.get('generated_at'), 'source': d.get('source'),
                      'last_date': d.get('last_date'), 'n_coins': d.get('n_coins')}
    t = (d.get('truth') or {}).get('cycle') or {}
    if 'final_mult' in t:
        metrics['crypto.nav.mult'] = round(float(t['final_mult']), 4)
        metrics['crypto.nav.mdd'] = round(float(t.get('mdd', 0)), 2)
        metrics['crypto.nav.cagr'] = round(float(t.get('cagr', 0)), 2)
        metrics['crypto.nav.sharpe'] = round(float(t.get('sharpe', 0)), 3)


def _m_reconcile(metrics, meta):
    """加密深度口径: reconcile_truth.py 的 10y/12y FULL (约 45s)."""
    rel = os.path.join('markets', 'crypto', 'reconcile_truth.py')
    ok, tail, err = _run(rel, timeout=1800)
    if not ok:
        raise RuntimeError(f'reconcile_truth.py 失败: {err}')
    rep = _load(os.path.join(ROOT, 'markets', 'crypto', 'reports',
                             'reconcile_truth_report.json'))
    tag = {'12y全面板': '12y', '10y窗口': '10y'}
    for win, short in tag.items():
        for cfg, node in (rep.get(win, {}).get('cfgs') or {}).items():
            metrics[f'crypto.{short}.{cfg}.mult'] = round(float(node['multiple']), 3)
            metrics[f'crypto.{short}.{cfg}.mdd'] = round(float(node['mdd']) * 100, 2)
            metrics[f'crypto.{short}.{cfg}.cagr'] = round(float(node['cagr']) * 100, 2)
            metrics[f'crypto.{short}.{cfg}.sharpe'] = round(float(node['sharpe']), 3)


def _m_blend(metrics, meta):
    """跨市场组合层 (共同窗口)."""
    ok, tail, err = _run('portfolio_blend.py')
    if not ok:
        raise RuntimeError(f'portfolio_blend.py 失败: {err}')
    d = _load(os.path.join(DOCS, 'portfolio_blend.json'))
    meta['blend'] = {'common_window': d.get('common_window')}
    for name, node in (d.get('blends') or {}).items():
        key = 'blend.' + name.replace(' ', '_').replace('/', '-').replace('(', '') \
                             .replace(')', '').replace('.', '')
        metrics[key + '.mult'] = round(float(node['multiple']), 4)
        metrics[key + '.mdd'] = round(float(node['mdd']) * 100, 2)
        metrics[key + '.sharpe'] = round(float(node['sharpe']), 3)


STAGES = [
    ('ashare', _m_ashare, True),
    ('us', _m_us, True),
    ('crypto', _m_crypto, True),
    ('reconcile', _m_reconcile, False),   # --no-deep 时跳过
    ('blend', _m_blend, False),
]

#: 阶段 -> 其产出指标的 key 前缀. 用于「阶段被跳过时, 基线里对应指标不参与比对」
#: —— 否则 --no-deep 会让 reconcile 的 40 项全部判 MISSING 而假红。
PREFIX = {
    'ashare': ('ashare.',),
    'us': ('us.',),
    'crypto': ('crypto.nav.',),
    'reconcile': ('crypto.10y.', 'crypto.12y.'),
    'blend': ('blend.',),
}


# ---------------------------------------------------------------- 断言
def _tol_for(key, args):
    if key.endswith('.mult'):
        return args.tol_mult, 'rel'
    if key.endswith('.sharpe'):
        return args.tol_sharpe, 'abs'
    return args.tol_pct, 'abs'      # mdd / cagr (百分点)


def compare(base, cur, args, active_prefixes=None):
    """active_prefixes: 本次实际跑过的阶段前缀; 其余前缀的基线指标直接跳过."""
    rows = []
    for k in sorted(set(base) | set(cur)):
        if active_prefixes and not k.startswith(active_prefixes):
            continue
        b, c = base.get(k), cur.get(k)
        if b is None:
            rows.append((k, None, c, None, 'NEW', '-'))
            continue
        if c is None:
            rows.append((k, b, None, None, 'MISSING', '-'))
            continue
        tol, mode = _tol_for(k, args)
        if mode == 'rel':
            dev = abs(c - b) / abs(b) if b else 0.0
            dev_s = f'{dev*100:.2f}%'
            lim_s = f'{tol*100:.1f}%'
        else:
            dev = abs(c - b)
            dev_s = f'{dev:.3f}'
            lim_s = f'{tol:.3f}'
        rows.append((k, b, c, dev_s, 'OK' if dev <= tol else 'FAIL', lim_s))
    return rows


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description='三市场权威真值产出 + 数字回归断言')
    ap.add_argument('--baseline', action='store_true', help='用本次结果刷新基线')
    ap.add_argument('--only', default='', help='逗号分隔, 只跑 ashare/us/crypto/reconcile/blend')
    ap.add_argument('--no-deep', action='store_true', help='跳过 reconcile 与组合层')
    ap.add_argument('--tol-mult', type=float, default=0.02, help='倍数相对容差 (默认 2%%)')
    ap.add_argument('--tol-pct', type=float, default=0.5, help='MDD/CAGR 绝对容差(百分点)')
    ap.add_argument('--tol-sharpe', type=float, default=0.05, help='Sharpe 绝对容差')
    args = ap.parse_args()

    only = {s.strip() for s in args.only.split(',') if s.strip()}
    metrics, meta, status = {}, {}, {}
    os.makedirs(REPORTS, exist_ok=True)

    print('=' * 78)
    print('run_all.py — 三市场权威真值产出 + 数字回归断言')
    print('=' * 78)

    for name, fn, required in STAGES:
        if only and name not in only:
            continue
        if args.no_deep and not required:
            status[name] = 'SKIPPED(--no-deep)'
            continue
        print(f'\n--- {name} ...')
        try:
            fn(metrics, meta)
            status[name] = 'OK'
            n_before = len(metrics)
            print(f'    OK  (累计 {len(metrics)} 项指标)')
            del n_before
        except FileNotFoundError as e:
            status[name] = 'NO_DATA'
            print(f'    ⚠ 跳过: {e}')
        except Exception as e:                     # noqa: BLE001
            status[name] = f'ERROR: {e}'
            print(f'    ✗ 失败: {e}')

    today = dt.date.today().isoformat()
    snap = {'date': today, 'status': status, 'meta': meta, 'metrics': metrics}
    snap_path = os.path.join(REPORTS, f'truth_snapshot_{today}.json')
    with open(snap_path, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)

    print('\n' + '=' * 78)
    print(f'产出留档: reports/truth_snapshot_{today}.json')
    for k, v in status.items():
        print(f'  {k:<10} {v}')

    if args.baseline:
        with open(BASELINE, 'w', encoding='utf-8') as f:
            json.dump({'updated': today, 'metrics': metrics, 'meta': meta},
                      f, ensure_ascii=False, indent=2)
        print(f'\n基线已刷新: {BASELINE}  ({len(metrics)} 项)')
        return 0

    if not metrics:
        print('\n无可用指标 (数据缺失或全部失败)。')
        return 2
    if any(str(v).startswith('ERROR') for v in status.values()):
        print('\n存在子脚本执行失败。')
        return 2

    if not os.path.exists(BASELINE):
        with open(BASELINE, 'w', encoding='utf-8') as f:
            json.dump({'updated': today, 'metrics': metrics, 'meta': meta},
                      f, ensure_ascii=False, indent=2)
        print(f'\n基线不存在, 已按当前结果创建: {BASELINE}')
        print('下次运行开始生效回归断言。')
        return 0

    base = _load(BASELINE).get('metrics', {})
    ran = tuple(p for st, pfx in PREFIX.items() if status.get(st) == 'OK' for p in pfx)
    rows = compare(base, metrics, args, active_prefixes=ran or None)
    fails = [r for r in rows if r[4] in ('FAIL', 'MISSING')]
    news = [r for r in rows if r[4] == 'NEW']
    skipped = sum(1 for k in base if ran and not k.startswith(ran))
    if skipped:
        print(f'(另有 {skipped} 项基线指标属未跑阶段, 已跳过比对)')

    print('\n' + '=' * 78)
    print(f"{'指标':<44}{'基线':>12}{'当前':>12}{'偏差':>10}{'容差':>8}  结果")
    print('-' * 78)
    for k, b, c, dev, verdict, lim in rows:
        bs = f'{b:,.3f}' if isinstance(b, (int, float)) else '-'
        cs = f'{c:,.3f}' if isinstance(c, (int, float)) else '-'
        print(f'{k:<44}{bs:>12}{cs:>12}{str(dev):>10}{lim:>8}  {verdict}')

    print('-' * 78)
    print(f'共 {len(rows)} 项: 通过 {len(rows)-len(fails)-len(news)} / '
          f'失败 {len(fails)} / 新增 {len(news)}')
    if news:
        print('新增指标(基线中不存在, 请确认是否为预期新增口径):')
        for k, b, c, dev, verdict, lim in news:
            print(f'  + {k} = {c}')

    if fails:
        print('\n❌ 数字回归失败。若为预期变更(改池/修数据), 请:')
        print('   1) 同步更新 TRUTH_AUTHORITY.md / docs/TRUTH.md / README.md;')
        print('   2) 执行 python run_all.py --baseline 刷新基线。')
        return 1
    print('\n✅ 全部数字在容差内。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
