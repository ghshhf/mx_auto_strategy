"""
news_feed.py - 实时新闻资讯参考源 (v1.0, 仅参考·绝不交易)

定位 (用户明确):
  新闻是「剧本的旁证 / 参考值」, 不是「决策源」.
  你的交易主轴是剧本(user_script + weekly_theme 方向), 新闻只做共振确认.
  本工具: 拉公开快讯 -> 与当前剧本方向关键词匹配打标签 -> 落本地存档.
  ⛔ 铁律: 本文件任何代码都不得调用下单/买卖接口.

数据源 (公开免费, 无需 key):
  - 新浪 7x24 快讯 (主源): feed.mix.sina.com.cn/api/roll/get

用法:
  python3 news_feed.py fetch                 # 拉最新快讯, 匹配剧本方向, 存档
  python3 news_feed.py latest --n 10         # 看最近N条 + 共振标记
  python3 news_feed.py latest --resonance    # 只看与剧本共振的
"""
import os
import json
import urllib.request
import argparse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
RECORD_ROOT = os.path.join(HERE, "records")
FEED_LOG = os.path.join(RECORD_ROOT, "news_feed.jsonl")

SINA_URL = ("https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509"
            "&k=&num=30&page=1")

# 行业关键词 -> 共振标签 (用于把新闻文本匹配到剧本方向)
INDUSTRY_KEYWORDS = {
    "电力": ["电力", "电网", "发电", "水电", "火电", "核电", "新能源发电", "特高压", "南网", "国网"],
    "医药": ["医药", "医疗", "药", "疫苗", "创新药", "医疗器械", "生物", "医保", "CXO", "中药"],
    "科技": ["科技", "半导体", "芯片", "AI", "人工智能", "算力", "光刻", "消费电子", "TMT"],
    "银行": ["银行", "信贷", "息差", "农商", "工行", "建行", "招行"],
    "红利": ["红利", "高股息", "分红", "股息率", "低波"],
    "黄金": ["黄金", "贵金属", "白银", "美联储", "降息"],
    "宏观": ["GDP", "CPI", "PPI", "社融", "货币", "财政", "降息", "降准", "美联储", "央行"],
}

# 默认剧本方向 (若读不到 weekly_theme.json 时的兜底)
DEFAULT_DIRECTIONS = ["电力", "医药"]


# ---------------------------------------------------------------- 来源读取

def _fetch_sina():
    req = urllib.request.Request(
        SINA_URL,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
    )
    try:
        raw = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "ignore")
    except Exception as e:
        return [], f"新浪快讯拉取失败: {e}"
    try:
        j = json.loads(raw)
        items = j.get("result", {}).get("data", [])
    except Exception:
        return [], "新浪快讯 JSON 解析失败"
    out = []
    for it in items:
        title = it.get("title", "") or ""
        intro = it.get("intro", "") or it.get("summary", "") or ""
        ctime = it.get("ctime") or it.get("intime") or ""
        out.append({
            "title": title,
            "intro": intro[:200],
            "ts_raw": ctime,
            "url": it.get("url", ""),
        })
    return out, f"OK {len(out)}条"


# ---------------------------------------------------------------- 方向匹配

def _load_directions():
    """读 weekly_theme.json + user_script.md 抽当前剧本方向."""
    dirs = set(DEFAULT_DIRECTIONS)
    try:
        j = json.load(open(os.path.join(HERE, "weekly_theme.json"), encoding="utf-8"))
        ud = j.get("user_direction", "") or ""
        for k in INDUSTRY_KEYWORDS:
            if k in ud:
                dirs.add(k)
        for ml in j.get("main_lines", []) or []:
            ind = ml.get("industry", "")
            if ind in INDUSTRY_KEYWORDS:
                dirs.add(ind)
    except Exception:
        pass
    return dirs


def _match(text, directions):
    """返回 (命中方向列表, 标签). 无命中=无关, 有命中=共振."""
    hits = []
    for d in directions:
        kws = INDUSTRY_KEYWORDS.get(d, [d])
        if any(kw in text for kw in kws):
            hits.append(d)
    return hits


# ---------------------------------------------------------------- 存档 / 读

def _ensure():
    os.makedirs(RECORD_ROOT, exist_ok=True)


def _append(record):
    _ensure()
    with open(FEED_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read():
    if not os.path.exists(FEED_LOG):
        return []
    out = []
    with open(FEED_LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


# ---------------------------------------------------------------- 命令

def cmd_fetch(args):
    items, msg = _fetch_sina()
    if not items:
        print(f"  ⚠️ {msg}")
        return
    directions = _load_directions()
    print(f"  📰 拉取快讯: {msg} | 当前剧本方向: {','.join(directions)}")
    new = 0
    for it in items:
        text = it["title"] + " " + it["intro"]
        hits = _match(text, directions)
        tag = "共振" if hits else "无关"
        rec = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "src": "sina_7x24",
            "title": it["title"],
            "intro": it["intro"],
            "url": it["url"],
            "resonance_with": hits,
            "tag": tag,
        }
        _append(rec)
        new += 1
        mark = "🔥共振" if hits else "  ·  "
        print(f"  {mark} {it['title'][:50]}" + (f"  ←{','.join(hits)}" if hits else ""))
    print(f"  ✅ 新增 {new} 条, 存档: {FEED_LOG}")


def cmd_latest(args):
    recs = _read()
    if not recs:
        print("  （暂无新闻存档, 先跑 fetch）")
        return
    recs = recs[::-1]  # 最新在前
    if args.resonance:
        recs = [r for r in recs if r.get("tag") == "共振"]
    recs = recs[:args.n]
    print(f"  📰 最近新闻 ({len(recs)} 条" + ("，仅共振" if args.resonance else "") + "):")
    for r in recs:
        mark = "🔥" if r.get("tag") == "共振" else "  "
        rh = ",".join(r.get("resonance_with", [])) if r.get("resonance_with") else ""
        print(f"  {mark} [{r.get('ts','')[:16]}] {r.get('title','')[:48]}" + (f"  ←{rh}" if rh else ""))


# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser(description="实时新闻参考源 (仅参考·绝不交易)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch").set_defaults(func=cmd_fetch)
    lv = sub.add_parser("latest")
    lv.add_argument("--n", type=int, default=10)
    lv.add_argument("--resonance", action="store_true", help="只看与剧本共振的")
    lv.set_defaults(func=cmd_latest)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
