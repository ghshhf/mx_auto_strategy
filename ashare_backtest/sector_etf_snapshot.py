# -*- coding: utf-8 -*-
"""
sector_etf_snapshot.py
======================
轻量「板块 ↔ 行业ETF 映射 + 动量速览」。

目的: 在动手深挖之前, 先看全貌 —— 把现有 8 大板块映射到代表性行业ETF,
      拉腾讯后复权日K, 算 13/26/52 周动量, 输出一份速览笔记。

数据口径:
  - 行情源: 腾讯 web.ifzq.gtimg.cn 后复权(hfq) 日K (与 ashare_backtest 回测面板一致)
  - 动量: 13周≈65交易日 / 26周≈130 / 52周≈260 (close-to-close)
  - ⚠️ 本速览只含「价格动量」维度; 「资金流」(ETF份额/规模趋势) 为后续步骤, 见笔记末节

依赖: 仅标准库。无代理直连。

输出: records/sector_research/<日期>_行业ETF映射与动量速览.md
用法: python ashare_backtest/sector_etf_snapshot.py
"""
import os
import sys
import json
import time
import datetime
import urllib.request
import urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
OUT_DIR = os.path.join(ROOT, "records", "sector_research")
os.makedirs(OUT_DIR, exist_ok=True)

API = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

# 板块 -> 代表性行业ETF [(code, name, role)]
ETF_MAP = {
    "AI算力链": [
        ("512480", "半导体ETF", "设备/芯片, 确定性+相对低位"),
        ("515880", "通信ETF", "含光模块/算力主线"),
        ("159819", "人工智能ETF", "AI应用层暴露"),
    ],
    "医药": [
        ("512010", "医药ETF", "宽基医药, 观察板块β"),
        ("512170", "医疗ETF", "器械/CXO暴露"),
        ("159992", "创新药ETF", "创新药弹性"),
    ],
    "军工": [
        ("512660", "军工ETF", "航空/船舶/电子综合"),
        ("512670", "国防ETF", "军工龙头集中度更高"),
    ],
    "红利": [
        ("510880", "红利ETF", "上证红利, 银行+制造业"),
        ("512800", "银行ETF", "红利压舱石核心"),
        ("512890", "红利低波ETF", "低波因子, 防御属性"),
    ],
    "新能源": [
        ("515790", "光伏ETF", "光伏产业链"),
        ("159755", "电池ETF", "电池/储能"),
        ("515030", "新能源车ETF", "宁德权重高, 进攻核心"),
    ],
    "防御全谱": [
        ("159611", "电力ETF", "真防御锚(长江电力权重大)"),
        ("515220", "煤炭ETF", "神华等, 防御对冲"),
        ("512690", "白酒ETF", "已失绝对防御, 观察"),
        ("515710", "食品ETF", "消费防御"),
    ],
    "有色/稀土": [
        ("512400", "有色金属ETF", "紫金等资源alpha"),
        ("516780", "稀土ETF", "战略资源弹性"),
        ("518880", "黄金ETF", "低相关对冲"),
    ],
    "券商": [
        ("512000", "券商ETF", "行情Beta/牛熊开关"),
        ("512880", "证券ETF", "高流动性券商敞口"),
    ],
}


def _get(url, dec="utf-8", timeout=12):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://finance.qq.com/",
    })
    return urllib.request.urlopen(req, timeout=timeout).read().decode(dec, "ignore")


def fetch_hfq_day(code, count=270):
    """拉腾讯后复权日K, 返回升序 [{'date','close'}, ...]。优先 hfqday, 退化 day。"""
    prefixed = code
    if not code.startswith(("sh", "sz")):
        # ETF 规则: 5xxxxx(50/51/52/55/56/58...) = 沪(sh); 1xxxxx(15/16/18...) = 深(sz)
        prefixed = ("sh" if code[0] == "5" else "sz") + code
    url = f"{API}?param={prefixed},day,,,{count},hfq"
    try:
        j = json.loads(_get(url, "utf-8"))
    except Exception as e:
        print(f"  ! {code} 解析失败: {e}", file=sys.stderr)
        return []
    node = (j.get("data") or {}).get(prefixed) or {}
    # 优先后复权
    arr = node.get("hfqday") or node.get("day") or []
    out = []
    for r in arr:
        try:
            out.append({"date": r[0], "close": float(r[2])})
        except (IndexError, ValueError, TypeError):
            continue
    return out


def momentum(kl):
    """返回 (last_close, r13, r26, r52) ; 不足历史返回 None。"""
    if len(kl) < 2:
        return None, None, None, None
    last = kl[-1]["close"]
    def ret(back):
        i = len(kl) - 1 - back
        if i < 0:
            return None
        base = kl[i]["close"]
        if base <= 0:
            return None
        return round((last / base - 1) * 100, 1)
    return last, ret(65), ret(130), ret(260)


def pct(v):
    return f"{v:+.1f}%" if isinstance(v, (int, float)) else "—"


def main():
    today = datetime.date.today().strftime("%Y%m%d")
    rows = []          # (sector, code, name, role, last, r13, r26, r52, n)
    print("拉取行业ETF后复权日K并计算动量 ...", file=sys.stderr)
    for sector, etfs in ETF_MAP.items():
        for code, name, role in etfs:
            kl = fetch_hfq_day(code)
            if not kl:
                rows.append((sector, code, name, role, None, None, None, None, 0))
                print(f"  x {name}({code}) 无数据", file=sys.stderr)
                continue
            last, r13, r26, r52 = momentum(kl)
            rows.append((sector, code, name, role, last, r13, r26, r52, len(kl)))
            time.sleep(0.15)

    # ---------- 渲染 Markdown ----------
    lines = []
    lines.append(f"# 行业ETF 映射与动量速览（{today}）\n")
    lines.append("> **性质**：轻量速览，先于深挖看全貌。数据周 ≈ " +
                 (rows[0][8] and rows[0][4] and "今日") + "。\n")
    lines.append("> **行情源**：腾讯后复权(hfq)日K（与 `ashare_backtest` 回测面板同口径）。")
    lines.append("> **动量**：13周≈65交易日 / 26周≈130 / 52周≈260，close-to-close。")
    lines.append("> **资金维度**：本文**仅价格动量**；ETF份额/规模趋势（资金流代理）为下一步，见末节。\n")

    lines.append("---\n")
    lines.append("## 一、板块 ↔ 行业ETF 映射表\n")
    lines.append("| 板块 | 代表行业ETF | 代码 | 角色/暴露 |")
    lines.append("|---|---|---|---|")
    for sector, etfs in ETF_MAP.items():
        for i, (code, name, role) in enumerate(etfs):
            sd = sector if i == 0 else ""
            lines.append(f"| {sd} | {name} | {code} | {role} |")

    lines.append("\n---\n")
    lines.append("## 二、动量速览（13/26/52 周 %）\n")
    lines.append("按板块分组。颜色提示：52周为板块中长期趋势锚。\n")
    lines.append("| 板块 | ETF | 代码 | 最新价 | 13周 | 26周 | 52周 | 样本数 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for sector, code, name, role, last, r13, r26, r52, n in rows:
        last_s = f"{last:.3f}" if isinstance(last, (int, float)) else "—"
        lines.append(f"| {sector} | {name} | {code} | {last_s} | {pct(r13)} | {pct(r26)} | {pct(r52)} | {n} |")

    # 全谱排序：按 52周 动量降序（有数据者）
    lines.append("\n---\n")
    lines.append("## 三、板块强弱全景（按 52 周动量排序）\n")
    lines.append("取每板块「代表ETF」的 52 周动量作为板块中长期强弱代理（多ETF板块取均值）。\n")
    sec52 = {}
    for sector, code, name, role, last, r13, r26, r52, n in rows:
        if isinstance(r52, (int, float)):
            sec52.setdefault(sector, []).append(r52)
    ranked = sorted(sec52.items(), key=lambda kv: sum(kv[1]) / len(kv[1]), reverse=True)
    lines.append("| 排名 | 板块 | 52周动量均值 | 强弱 |")
    lines.append("|---|---|---|---|")
    for i, (sector, vals) in enumerate(ranked, 1):
        avg = sum(vals) / len(vals)
        tag = "强" if avg > 15 else ("中性" if avg > -10 else "弱")
        lines.append(f"| {i} | {sector} | {avg:+.1f}% | {tag} |")

    lines.append("\n---\n")
    lines.append("## 四、下一步：资金维度（待补）\n")
    lines.append("- 价格动量只回答「涨没涨」，不回答「钱往哪去」。")
    lines.append("- 行业ETF层面最干净的资金代理 = **ETF 份额/规模趋势**（份额持续增长 = 资金净流入）。")
    lines.append("  东财 `push2delay` 已验证可拉 ETF 规模/份额快照；日频历史需补一个拉取脚本。")
    lines.append("- 注意：**北向资金自 2024-08 已停更**，不宜再作 A 股资金流主指标。")
    lines.append("- 板块级「主力净流入」(push2) 在本沙箱被断连，优先级放后。\n")
    lines.append("> 触发深挖：用户说「调研 XX 板块(ETF资金)」即可，复用 `sector_research` 7 节模板。")

    out_path = os.path.join(OUT_DIR, f"{today}_行业ETF映射与动量速览.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n已写出: {out_path}", file=sys.stderr)
    # 终端也打印速览表
    print("\n".join(lines))


if __name__ == "__main__":
    main()
