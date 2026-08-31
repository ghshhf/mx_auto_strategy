# -*- coding: utf-8 -*-
"""manage_token.py — 加密代币池统一管理工具 (加币/删币/刷新/体检)
====================================================================
替代 scripts/ops/ 下的一次性 add_*/del_* 脚本。一次命令完成全部改动:

  数据面板   data/weekly_adjclose_crypto50{,_v3,_10y}.csv  (增/删列, 全历史)
  运营池     crypto_adoption_v2.py  THEME_COINS + COIN_META
  市值映射   fetch_mcaps.py         CG id 映射 (可自动经 CoinGecko 解析)
  CMC 映射   sync_crypto_panel.py   _CMC_ID_MAP (可选 --cmc-id)
  符号映射   data_sources.py        COINGECKO_IDS + CMC_IDS (加删币同步维护)
  筛查标注   _screen_pool_now.py    recent 集合

对齐口径 (与面板既有数据严格一致, 已实证):
  面板周五 F  =  源周K(周一 F+3 开盘那根)的收盘价   [即 -3 口径]
  最后一行持有当前未完结周K的实时收盘快照, 与 sync_crypto_panel 行为一致.

数据源链: Binance -> OKX -> Gate.io (取可用K线最多者; 平台币如 GT 仅 Gate 有).
本机出网经 127.0.0.1:3067 代理 (HTTPS_PROXY 环境变量可覆盖).

用法:
  python manage_token.py list
  python manage_token.py add    RAY --track DEX --launch 2021 --name Raydium
  python manage_token.py remove SKY
  python manage_token.py refresh GT            # 自动选源重拉全历史修列
  python manage_token.py refresh GT --source gate
  python manage_token.py doctor               # 全面板对齐体检
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
PANELS = ['weekly_adjclose_crypto50.csv',
          'weekly_adjclose_crypto50_v3.csv',
          'weekly_adjclose_crypto50_10y.csv']
CA_FILE = os.path.join(HERE, 'crypto_adoption_v2.py')
MCAP_FILE = os.path.join(HERE, 'fetch_mcaps.py')
SYNC_FILE = os.path.join(HERE, 'sync_crypto_panel.py')
SCREEN_FILE = os.path.join(HERE, '_screen_pool_now.py')
DS_FILE = os.path.join(HERE, 'data_sources.py')

PROXY = (os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
         or 'http://127.0.0.1:3067')
TODAY = dt.date.today().isoformat()

# ---------------------------------------------------------------- HTTP --
def http_json(url, timeout=40):
    """GET JSON: urllib(代理) 优先, 失败回退 curl -x 代理 (对 Binance 更稳)."""
    import urllib.request
    try:
        op = urllib.request.build_opener(
            urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY}))
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        return json.loads(op.open(req, timeout=timeout).read().decode('utf-8', 'ignore'))
    except Exception:
        pass
    r = subprocess.run(['curl', '-s', '-m', str(timeout), '-x', PROXY, url],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return None

# ------------------------------------------------------------- 拉数源 --
def fetch_binance(sym):
    """Binance 1w 全量翻页 -> {monday: close}."""
    out, start_ms = {}, None
    for _ in range(8):
        url = f'https://api.binance.com/api/v3/klines?symbol={sym}USDT&interval=1w&limit=1000'
        if start_ms:
            url += f'&startTime={start_ms}'
        arr = http_json(url)
        if not isinstance(arr, list) or not arr:
            break
        for x in arr:
            m = dt.datetime.fromtimestamp(x[0] / 1000, dt.timezone.utc)
            out[m.strftime('%Y-%m-%d')] = float(x[4])
        if len(arr) < 1000:
            break
        start_ms = arr[-1][0] + 1
        time.sleep(0.12)
    return out

def fetch_okx(sym):
    """OKX 1w 翻页 (newest-first) -> {monday: close}."""
    out, after = {}, int(time.time() * 1000)
    for _ in range(8):
        url = (f'https://www.okx.com/api/v5/market/candles?instId={sym}-USDT'
               f'&bar=1W&after={after}&limit=100')
        d = http_json(url)
        data = (d or {}).get('data', [])
        if not data:
            break
        for x in data:
            m = dt.datetime.fromtimestamp(int(x[0]) / 1000, dt.timezone.utc)
            out[m.strftime('%Y-%m-%d')] = float(x[4])
        oldest = min(int(x[0]) for x in data)
        if oldest <= 1420000000000 or len(data) < 100:
            break
        after = oldest - 1
        time.sleep(0.12)
    return out

def fetch_gate(sym):
    """Gate.io 1w 翻页 (秒级时间戳) -> {monday: close}."""
    out, to = {}, int(time.time()) + 86400
    for _ in range(8):
        frm = to - 200 * 7 * 86400
        arr = http_json(f'https://api.gateio.ws/api/v4/spot/candlesticks'
                        f'?currency_pair={sym}_USDT&interval=1w&from={frm}&to={to}&limit=1000')
        if not isinstance(arr, list) or not arr:
            break
        for x in arr:
            m = dt.datetime.fromtimestamp(int(x[0]), dt.timezone.utc)
            out[m.strftime('%Y-%m-%d')] = float(x[2])
        oldest = int(arr[0][0])
        if oldest <= 1400000000 or len(arr) < 2:
            break
        to = oldest
        time.sleep(0.12)
    return out

SOURCES = {'binance': fetch_binance, 'okx': fetch_okx, 'gate': fetch_gate}

def fetch_best(sym, prefer=None):
    """按源链取K线最多者. 返回 (weekly, source_name)."""
    order = [prefer] if prefer else []
    order += [s for s in ['binance', 'okx', 'gate'] if s not in order]
    best, best_name = {}, None
    for name in order:
        w = SOURCES[name](sym)
        print(f"    [{name}] {len(w)} 周", file=sys.stderr)
        if len(w) > len(best):
            best, best_name = w, name
        if len(best) >= 300:      # 足够长, 不再试备源
            break
    return best, best_name

# ------------------------------------------------------------ 面板 IO --
def read_panel(fname):
    """读面板, 返回 (rows, meta). rows[0]=header. meta 记录 BOM/换行以原样回写."""
    path = os.path.join(DATA, fname)
    raw = open(path, 'rb').read()
    meta = {'bom': raw[:3] == b'\xef\xbb\xbf', 'crlf': b'\r\n' in raw[:20000]}
    text = raw.decode('utf-8-sig')
    rows = list(csv.reader(io.StringIO(text)))
    return rows, meta, path

def write_panel(rows, meta, path):
    lineterm = '\r\n' if meta['crlf'] else '\n'
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator=lineterm)
    w.writerows(rows)
    data = buf.getvalue().encode('utf-8')
    if meta['bom']:
        data = b'\xef\xbb\xbf' + data
    with open(path, 'wb') as f:
        f.write(data)

def panel_set_column(fname, sym, weekly_monday):
    """写入/覆盖一列 (-3 口径: 面板周五F = 周一F+3收盘). 返回统计."""
    rows, meta, path = read_panel(fname)
    header, data = rows[0], rows[1:]
    if sym in header:
        ci = header.index(sym)
        header = header[:ci] + header[ci + 1:]
        data = [r[:ci] + r[ci + 1:] if len(r) > ci else r for r in data]
    header = header + [sym]
    nvalid = 0
    first = last = None
    new_data = []
    for r in data:
        r = list(r) + [''] * (len(header) - 1 - len(r)) if len(r) < len(header) - 1 else list(r)
        d = r[0]
        try:
            fri = dt.date.fromisoformat(d)
            monday = (fri + dt.timedelta(days=3)).isoformat()
            v = weekly_monday.get(monday)
        except ValueError:
            v = None
        if v is not None:
            cell = ('%g' % v) if v == v and abs(v) < 1e15 else ''
            if cell == '':
                v = None
        else:
            cell = ''
        if v is not None:
            nvalid += 1
            first = first or d
            last = d
        new_data.append(r + [cell])
    write_panel([header] + new_data, meta, path)
    return {'weeks': nvalid, 'first': first, 'last': last}

def panel_drop_column(fname, sym):
    rows, meta, path = read_panel(fname)
    header, data = rows[0], rows[1:]
    if sym not in header:
        return False
    ci = header.index(sym)
    header = header[:ci] + header[ci + 1:]
    data = [r[:ci] + r[ci + 1:] if len(r) > ci else r for r in data]
    write_panel([header] + data, meta, path)
    return True

# ----------------------------------------------------------- .py 文本编辑 --
def _edit_file(path, fn):
    text = open(path, encoding='utf-8').read()
    new = fn(text)
    if new is None or new == text:
        return False
    open(path, 'w', encoding='utf-8', newline='\n').write(new)
    return True

def _fmt_list(items):
    return '[' + ', '.join("'{}'".format(i) for i in items) + ']'

def pool_add(sym, track):
    """THEME_COINS 赛道追加 (幂等)."""
    def fn(text):
        m = re.search(r'THEME_COINS\s*=\s*\{', text)
        if not m:
            return None
        # 已在任何赛道 -> no-op
        if re.search(r"'%s'" % sym, text[m.start():m.end() + 2000]):
            return text
        pat = re.compile(r'^(\s*)"%s":\s*(\[.*?\])(.*)$' % re.escape(track), re.M)
        mm = pat.search(text)
        if mm:
            items = re.findall(r"'(\w+)'", mm.group(2))
            newline = '%s"%s": %s%s' % (mm.group(1), track,
                                        _fmt_list(items + [sym]), mm.group(3))
            return text[:mm.start()] + newline + text[mm.end():]
        anchor = m.end()
        return (text[:anchor] + '\n    "%s": [' % track + "'%s']," % sym
                + '  # %s added via manage_token.py' % TODAY + text[anchor:])
    return _edit_file(CA_FILE, fn)

def pool_remove(sym):
    """THEME_COINS 所有赛道移除; 空赛道整行删除 (幂等)."""
    def fn(text):
        changed = False
        out = []
        for line in text.split('\n'):
            mm = re.match(r'^(\s*)"[^"]+":\s*\[(.*)\](.*)$', line)
            if mm and re.search(r"'%s'" % sym, mm.group(2)):
                items = [i for i in re.findall(r"'(\w+)'", mm.group(2)) if i != sym]
                changed = True
                name = re.match(r'^\s*"([^"]+)"', line).group(1)
                if not items:
                    # 空赛道: 保留空键 'X': [] 而非删行, 以对齐 PHASE_HISTORY/引擎引用
                    out.append('%s"%s": []%s' % (mm.group(1), name, mm.group(3)))
                else:
                    out.append('%s"%s": %s%s' % (mm.group(1), name,
                                    _fmt_list(items), mm.group(3)))
            else:
                out.append(line)
        return '\n'.join(out) if changed else None
    return _edit_file(CA_FILE, fn)

def meta_add(sym, name, track, launch, role='offense'):
    def fn(text):
        m = re.search(r'COIN_META\s*=\s*\{', text)
        if not m:
            return None
        if re.search(r"^\s*'%s':\s*\{" % sym, text, re.M):
            return text                          # 已存在
        entry = ("    '%s': {'name': '%s', 'role': '%s', 'theme': '%s', "
                 "'launch': %d},  # %s added via manage_token.py"
                 % (sym, name, role, track, int(launch), TODAY))
        return text[:m.end()] + '\n' + entry + text[m.end():]
    return _edit_file(CA_FILE, fn)

def meta_remove(sym):
    def fn(text):
        new = re.sub(r"^\s*'%s':\s*\{.*?\},?\s*(#.*)?$\n?" % sym, '', text,
                     flags=re.M)
        return new if new != text else None
    return _edit_file(CA_FILE, fn)

def cg_resolve_id(sym, name):
    """CoinGecko search 自动解析 id."""
    q = name or sym
    d = http_json(f'https://api.coingecko.com/api/v3/search?query={q}')
    try:
        for c in d.get('coins', [])[:5]:
            if c.get('symbol', '').upper() == sym.upper():
                return c['id']
        if d.get('coins'):
            return d['coins'][0]['id']
    except Exception:
        pass
    return None

def cgmap_add(sym, cg_id):
    def fn(text):
        m = re.search(r'CG\s*=\s*\{', text)
        if not m or not cg_id:
            return None
        if re.search(r"^\s*'%s':\s*'" % sym, text, re.M):
            return text
        return (text[:m.end()] + "\n    '%s': '%s'," % (sym, cg_id)
                + '  # %s' % TODAY + text[m.end():])
    return _edit_file(MCAP_FILE, fn)

def cgmap_remove(sym):
    def fn(text):
        new = re.sub(r"'%s':\s*'[^']*',\s*" % sym, '', text)      # 行内/独立行(前缀)
        new = re.sub(r",\s*'%s':\s*'[^']*'" % sym, '', new)      # 行尾
        return new if new != text else None
    return _edit_file(MCAP_FILE, fn)

def cmcmap_add(sym, cmc_id):
    if not cmc_id:
        return False
    def fn(text):
        m = re.search(r'_CMC_ID_MAP\s*=\s*\{', text)
        if not m:
            return None
        if re.search(r"^\s*'%s':\s*\d+" % sym, text, re.M):
            return text
        return (text[:m.end()] + "\n    '%s': %d," % (sym, int(cmc_id))
                + '  # %s' % TODAY + text[m.end():])
    return _edit_file(SYNC_FILE, fn)

def cmcmap_remove(sym):
    def fn(text):
        new = re.sub(r"'%s':\s*\d+,\s*" % sym, '', text)          # 行内/独立行(前缀)
        new = re.sub(r",\s*'%s':\s*\d+" % sym, '', new)           # 行尾
        return new if new != text else None
    return _edit_file(SYNC_FILE, fn)

# data_sources.py 也维护 COINGECKO_IDS / CMC_IDS 两份映射, 须同步清理
def ds_cgmap_add(sym, cg_id):
    def fn(text):
        m = re.search(r'COINGECKO_IDS\s*=\s*\{', text)
        if not m or not cg_id:
            return None
        if re.search(r"^\s*'%s':\s*'" % sym, text, re.M):
            return text
        return (text[:m.end()] + "\n    '%s': '%s'," % (sym, cg_id)
                + '  # %s' % TODAY + text[m.end():])
    return _edit_file(DS_FILE, fn)

def ds_cgmap_remove(sym):
    def fn(text):
        new = re.sub(r"'%s':\s*'[^']*',\s*" % sym, '', text)      # 行内/独立行(前缀)
        new = re.sub(r",\s*'%s':\s*'[^']*'" % sym, '', new)      # 行尾
        return new if new != text else None
    return _edit_file(DS_FILE, fn)

def ds_cmcmap_add(sym, cmc_id):
    if not cmc_id:
        return False
    def fn(text):
        m = re.search(r'CMC_IDS\s*=\s*\{', text)
        if not m:
            return None
        if re.search(r"^\s*'%s':\s*\d+" % sym, text, re.M):
            return text
        return (text[:m.end()] + "\n    '%s': %d," % (sym, int(cmc_id))
                + '  # %s' % TODAY + text[m.end():])
    return _edit_file(DS_FILE, fn)

def ds_cmcmap_remove(sym):
    def fn(text):
        new = re.sub(r"'%s':\s*\d+,\s*" % sym, '', text)          # 行内/独立行(前缀)
        new = re.sub(r",\s*'%s':\s*\d+" % sym, '', new)           # 行尾
        return new if new != text else None
    return _edit_file(DS_FILE, fn)

def recent_set(sym, add=True):
    """_screen_pool_now.py 的 recent 集合增删 (兼容单/双引号)."""
    def fn(text):
        m = re.search(r'recent\s*=\s*\{(.*?)\}', text, re.S)
        if not m:
            return None
        items = re.findall(r"['\"](\w+)['\"]", m.group(1))
        if add:
            if sym in items:
                return None
            items = items + [sym]
        else:
            if sym not in items:
                return None
            items = [i for i in items if i != sym]
        return (text[:m.start()] + 'recent = {'
                + ', '.join('"{}"'.format(i) for i in items) + '}'
                + text[m.end():])
    return _edit_file(SCREEN_FILE, fn)

# ---------------------------------------------------------------- 命令 --
def cmd_list(args):
    import importlib
    sys.path.insert(0, HERE)
    import crypto_adoption_v2 as ca2
    print('=== 运营池 (crypto_adoption_v2.THEME_COINS) ===')
    for track, coins in ca2.THEME_COINS.items():
        print(f"  {track:<10} {coins}")
    print(f"\n防御: {ca2.DEFENSE_COINS}  进攻去重: {len(ca2.OFFENSE_COINS)} 个")
    print('\n=== 池子 × 面板覆盖 ===')
    print(f"{'币':7}{'角色':6}{'crypto50':10}{'v3':8}{'10y':8}  备注")
    covers = {}
    for fname in PANELS:
        rows, _, _ = read_panel(fname)
        covers[fname] = set(rows[0][1:])
    allc = ca2.DEFENSE_COINS + ca2.OFFENSE_COINS
    for sym in allc:
        m = ca2.COIN_META.get(sym, {})
        c1 = '✓' if sym in covers[PANELS[0]] else '—'
        c2 = '✓' if sym in covers[PANELS[1]] else '—'
        c3 = '✓' if sym in covers[PANELS[2]] else '—'
        note = ''
        if c1 == c2 == c3 == '—':
            note = '⚠ 无任何面板数据'
        print(f"{sym:7}{m.get('role', '?'):6}{c1:10}{c2:8}{c3:8}  {m.get('name', '')} {note}")
    orphan = covers[PANELS[0]] - set(allc)
    if orphan:
        print(f"\n⚠ 面板有列但不在运营池: {sorted(orphan)}")

def cmd_add(args):
    sym = args.sym.upper()
    print(f"[1/5] 拉取 {sym} 周K (Binance→OKX→Gate)...")
    weekly, src = fetch_best(sym, prefer=args.source)
    if len(weekly) < 4:
        raise SystemExit(f"✗ {sym} 各源K线均不足 ({len(weekly)}), 终止")
    ks = sorted(weekly)
    print(f"  源={src}, {len(weekly)} 周, {ks[0]} → {ks[-1]}")
    print(f"[2/5] 写入面板...")
    for fname in PANELS:
        st = panel_set_column(fname, sym, weekly)
        print(f"  {fname}: {st['weeks']} 有效周, {st['first']} → {st['last']}")
    print(f"[3/5] 运营池 {args.track} 赛道 + COIN_META...")
    if not pool_add(sym, args.track):
        print('  (池内已存在, 跳过)')
    if not meta_add(sym, args.name or sym, args.track, args.launch):
        print('  (COIN_META 已存在, 跳过)')
    print(f"[4/5] 市值/CMC 映射...")
    cg = args.cg_id or cg_resolve_id(sym, args.name)
    if cg:
        cgmap_add(sym, cg)
        print(f"  CG id = {cg}")
    else:
        print('  CG id 未能解析, 可稍后手工补 fetch_mcaps.py')
    if args.cmc_id:
        cmcmap_add(sym, args.cmc_id)
        print(f"  CMC id = {args.cmc_id}")
    # data_sources.py 同步维护映射
    if cg:
        ds_cgmap_add(sym, cg)
    if args.cmc_id:
        ds_cmcmap_add(sym, args.cmc_id)
    recent_set(sym, add=True)
    print(f"[5/5] 校验...")
    r = subprocess.run([sys.executable, os.path.join(HERE, 'manage_token.py'),
                        'verify', sym], capture_output=True, text=True,
                       encoding='utf-8')
    print(r.stdout or r.stderr)
    print(f"✓ {sym} 完成。后续建议: 跑 backtest_v2.py 验证; 需要时重生成 nav json.")

def cmd_remove(args):
    sym = args.sym.upper()
    print(f"[1/4] 面板删列 {sym}...")
    for fname in PANELS:
        if panel_drop_column(fname, sym):
            print(f"  {fname}: 已删列")
        else:
            print(f"  {fname}: 无该列")
    print(f"[2/4] 运营池 + COIN_META...")
    print('  池:', '已移除' if pool_remove(sym) else '(不在池内)')
    print('  META:', '已移除' if meta_remove(sym) else '(无条目)')
    print(f"[3/4] 映射清理...")
    print('  CG(fetch_mcaps):', '已移除' if cgmap_remove(sym) else '(无)')
    print('  CMC(sync):', '已移除' if cmcmap_remove(sym) else '(无)')
    print('  DS-CG(data_sources):', '已移除' if ds_cgmap_remove(sym) else '(无)')
    print('  DS-CMC(data_sources):', '已移除' if ds_cmcmap_remove(sym) else '(无)')
    recent_set(sym, add=False)
    print(f"[4/4] 校验...")
    r = subprocess.run([sys.executable, os.path.join(HERE, 'manage_token.py'),
                        'verify', sym], capture_output=True, text=True,
                       encoding='utf-8')
    print(r.stdout or r.stderr)
    print(f"✓ {sym} 已完整移除。")

def cmd_refresh(args):
    sym = args.sym.upper()
    print(f"[1/3] 重拉 {sym} 全历史 (--source={args.source or 'auto'})...")
    weekly, src = fetch_best(sym, prefer=args.source)
    if len(weekly) < 4:
        raise SystemExit(f"✗ {sym} K线不足 ({len(weekly)}), 终止")
    ks = sorted(weekly)
    print(f"  源={src}, {len(weekly)} 周, {ks[0]} → {ks[-1]}")
    print(f"[2/3] 重写面板列 (-3 口径)...")
    for fname in PANELS:
        rows, _, _ = read_panel(fname)
        if sym not in rows[0]:
            print(f"  {fname}: 无该列, 跳过")
            continue
        st = panel_set_column(fname, sym, weekly)
        print(f"  {fname}: {st['weeks']} 有效周, {st['first']} → {st['last']}")
    print(f"[3/3] 校验...")
    r = subprocess.run([sys.executable, os.path.join(HERE, 'manage_token.py'),
                        'verify', sym], capture_output=True, text=True,
                       encoding='utf-8')
    print(r.stdout or r.stderr)
    print(f"✓ {sym} 列已按 {src} 源、-3 口径重写。")

def cmd_verify(args):
    """子进程校验: 模块可导入、池/META 状态、面板列统计 (供 add/remove/refresh 内部调用)."""
    sym = args.sym.upper()
    sys.path.insert(0, HERE)
    import crypto_adoption_v2 as ca2
    in_pool = sym in ca2.OFFENSE_COINS or sym in ca2.DEFENSE_COINS
    in_meta = sym in ca2.COIN_META
    print(f"  模块加载 OK: 防御{len(ca2.DEFENSE_COINS)} + 进攻{len(ca2.OFFENSE_COINS)}"
          f" = {len(ca2.ALL_COINS)} 币")
    print(f"  {sym}: 池={'✓' if in_pool else '✗'}  COIN_META={'✓' if in_meta else '✗'}")
    for fname in PANELS:
        rows, _, _ = read_panel(fname)
        if sym not in rows[0]:
            print(f"  {fname}: 无 {sym} 列")
            continue
        ci = rows[0].index(sym)
        vals = [(r[0], r[ci]) for r in rows[1:] if len(r) > ci and r[ci] not in ('', 'nan')]
        if vals:
            print(f"  {fname}: {len(vals)} 点, {vals[0][0]} → {vals[-1][0]}, 末值={vals[-1][1]}")
        else:
            print(f"  {fname}: 0 点 ⚠")

def cmd_doctor(args):
    """全面板对齐体检: 每列末12行周收益率 vs 源, 判定 -3/+4 口径."""
    sys.path.insert(0, HERE)
    import pandas as pd
    dfs = {f: pd.read_csv(os.path.join(DATA, f), index_col=0, parse_dates=True)
           for f in PANELS}
    all_syms = sorted(set().union(*[set(d.columns) for d in dfs.values()]))
    print(f"体检 {len(all_syms)} 币 × {len(PANELS)} 面板 (每币拉一次源)...\n")
    bad = 0
    for sym in all_syms:
        weekly, src = fetch_best(sym)
        if len(weekly) < 12:
            continue
        for fname in PANELS:
            df = dfs[fname]
            if sym not in df.columns:
                continue
            s = df[sym].dropna()
            if len(s) < 5:
                continue
            tail = s.tail(13)
            dates, vals = list(tail.index), list(tail.values)

            def err(offset):
                mapped = [weekly.get((d + dt.timedelta(days=offset)).strftime('%Y-%m-%d'))
                          for d in dates]
                e = []
                for i in range(1, len(mapped)):
                    a, b, pa, pb = mapped[i - 1], mapped[i], vals[i - 1], vals[i]
                    if a and b and pa and pb:
                        e.append(((b / a - 1) - (pb / pa - 1)) ** 2)
                return (sum(e) / len(e)) if e else None

            e3, e4 = err(3), err(-4)
            if e3 is None or e4 is None:
                continue
            if e4 < 0.3 * e3 and e4 < 0.01:
                print(f"  ⚠ {fname}: {sym} [{src}] 整列+4错位 (err-3={e3:.4f} err+4={e4:.4f})"
                      f"  → python manage_token.py refresh {sym} --source {src}")
                bad += 1
            elif e3 > 0.02 and e4 > 0.02:
                print(f"  ? {fname}: {sym} [{src}] 两口径均不吻合 (源差异或数据异常), 人工复核")
        time.sleep(0.05)
    print(f"\n体检完成: {'发现问题 ' + str(bad) + ' 处' if bad else '未发现口径错位 ✓'}")

def main():
    ap = argparse.ArgumentParser(description='加密代币池统一管理工具')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list', help='池子×面板覆盖矩阵')
    p = sub.add_parser('add', help='加币: 拉数据+写面板+改池子')
    p.add_argument('sym')
    p.add_argument('--track', required=True, help='赛道名, 如 DEX/L1公链')
    p.add_argument('--launch', required=True, type=int, help='上线年')
    p.add_argument('--name', default=None, help='显示名 (默认=符号)')
    p.add_argument('--cg-id', default=None, help='CoinGecko id (默认自动解析)')
    p.add_argument('--cmc-id', default=None, type=int, help='CMC id (可选)')
    p.add_argument('--source', default=None, choices=['binance', 'okx', 'gate'])
    p = sub.add_parser('remove', help='删币: 面板+池子+映射全清')
    p.add_argument('sym')
    p = sub.add_parser('refresh', help='重拉全历史重写列 (修错位/错源)')
    p.add_argument('sym')
    p.add_argument('--source', default=None, choices=['binance', 'okx', 'gate'])
    p = sub.add_parser('verify', help='校验单币状态 (内部用)')
    p.add_argument('sym')
    sub.add_parser('doctor', help='全面板对齐体检')
    args = ap.parse_args()
    {'list': cmd_list, 'add': cmd_add, 'remove': cmd_remove,
     'refresh': cmd_refresh, 'verify': cmd_verify, 'doctor': cmd_doctor}[args.cmd](args)

if __name__ == '__main__':
    main()
