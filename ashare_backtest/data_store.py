# -*- coding: utf-8 -*-
"""
data_store.py
=============
A 股「本地 + GitHub 双缓存」数据层。

设计目标 (用户建议):
  1. 拉取一次数据源(腾讯/AkShare/东财)后, 缓存到本地 **并随仓库提交到 GitHub**。
  2. 下游读取走三级回退: 本地文件 -> GitHub raw (公开仓库免 token) -> 实时拉取。
     - 本地读取是瞬时的(纯 JSON), 比每次多页分页 HTTP 快得多。
     - GitHub raw 充当「数据 CDN」: 沙箱里东财/ AkShare 历史接口常被封,
       直接读 GitHub 上的已提交历史即可, 不必重复实时拉取。

目录约定 (均在 git 版本管理内, 上传到 GitHub):
  data/ashare/bars/<code>.json          任意标的日线 [{d,c,v}], code 形如 sh000001 / 512480
  data/ashare/flow/etf_flow_accum.json   ETF 每日份额/主力净流入累积
  data/ashare/manifest.json             每个文件的更新日期/行数/来源(可读, 便于巡检)

文件格式 (统一):
  {"updated": "YYYY-MM-DD", "source": "tencent|akshare|eastmoney",
   "bars": [[date, close, vol], ...]}   # date 升序
"""
import os
import sys
import json
import datetime
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.join(BASE, "data", "ashare")
BARS_DIR = os.path.join(DATA_ROOT, "bars")
FLOW_DIR = os.path.join(DATA_ROOT, "flow")
MANIFEST = os.path.join(DATA_ROOT, "manifest.json")

# 公开仓库 raw 基址 (免 token, CDN 加速); 改私有仓库需注入 GH_TOKEN
RAW_BASE = "https://raw.githubusercontent.com/ghshhf/mx_auto_strategy/main/ashare_backtest/data/ashare"

os.makedirs(BARS_DIR, exist_ok=True)
os.makedirs(FLOW_DIR, exist_ok=True)


def _now():
    return datetime.date.today().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 底层 IO
# ---------------------------------------------------------------------------
def _read_local(code):
    p = os.path.join(BARS_DIR, f"{code}.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            blob = json.load(fh)
        bars = blob.get("bars")
        if not bars:
            return None
        return [{"d": b[0], "c": float(b[1]), "v": float(b[2])} for b in bars]
    except Exception:
        return None


def _read_remote(code):
    url = f"{RAW_BASE}/bars/{code}.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mx-ashare"})
        raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")
        blob = json.loads(raw)
        bars = blob.get("bars")
        if not bars:
            return None
        out = [{"d": b[0], "c": float(b[1]), "v": float(b[2])} for b in bars]
        # 顺手存回本地, 下次直接本地
        _save_local(code, out, blob.get("source", "github"))
        return out
    except Exception as e:
        if os.environ.get("VERBOSE"):
            print(f"  ! GitHub raw 取 {code} 失败: {e}", file=sys.stderr)
        return None


def _save_local(code, bars, source="tencent"):
    p = os.path.join(BARS_DIR, f"{code}.json")
    try:
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"updated": _now(), "source": source,
                       "bars": [[b["d"], b["c"], b["v"]] for b in bars]}, fh)
        _touch_manifest(code, len(bars), source)
    except Exception as e:
        print(f"  ! 写本地缓存 {code} 失败: {e}", file=sys.stderr)


def _touch_manifest(code, rows, source):
    try:
        m = {}
        if os.path.exists(MANIFEST):
            with open(MANIFEST, "r", encoding="utf-8") as fh:
                m = json.load(fh)
        m[code] = {"updated": _now(), "rows": rows, "source": source}
        with open(MANIFEST, "w", encoding="utf-8") as fh:
            json.dump(m, fh, ensure_ascii=False, indent=1)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------
def load_bars(code, live_fn=None, source="tencent"):
    """三级回退取日线。优先本地 -> GitHub raw -> 实时(live_fn)。
    live_fn 收到 code, 应返回 [{d,c,v}] 或 []; 命中后自动落本地。"""
    bars = _read_local(code)
    if bars:
        return bars
    bars = _read_remote(code)
    if bars:
        return bars
    if live_fn:
        bars = live_fn(code) or []
        if bars:
            _save_local(code, bars, source)
            return bars
    return []


def save_bars(code, bars, source="tencent"):
    _save_local(code, bars, source)


def load_flow():
    p = os.path.join(FLOW_DIR, "etf_flow_accum.json")
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_flow(accum):
    p = os.path.join(FLOW_DIR, "etf_flow_accum.json")
    try:
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(accum, fh, ensure_ascii=False, indent=1)
        return True
    except Exception as e:
        print(f"  ! 写 flow 缓存失败: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    # 自检: 本地优先, 缺失走 github
    for c in ("sh000001", "512480", "399006"):
        b = load_bars(c)
        print(f"{c}: {len(b)} 条, 区间 {b[0]['d'] if b else '-'}->{b[-1]['d'] if b else '-'}")
