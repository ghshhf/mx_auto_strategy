# -*- coding: utf-8 -*-
"""
Yahoo Finance 全球龙头抓取 (2026-09-09 恢复可用, 之前判定限流不可用)

价值:
  1) 日韩台个股 —— Twelve Data 免费档 404, Yahoo 可取(丰田/三星/海力士/台积电)
  2) adjclose 含分红复权 —— 解决 Twelve Data 免费档只有未复权 close 的问题
  3) 欧/印/澳/巴西 龙头 —— 与美股/港股/A股低相关, 给"最小相关贪心"更多低相关来源

注意: Yahoo 有限流, 串行 + 间隔 1.6s + 失败退避重试
"""
import argparse, json, os, time, urllib.request
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0"}
PROXY = {"http": "http://127.0.0.1:3067", "https": "http://127.0.0.1:3067"}
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "yahoo_global_weekly_adjclose.csv")
RAW = os.path.join(HERE, "data", "raw_yahoo_global")
os.makedirs(RAW, exist_ok=True)

# ===== 全球龙头(日韩台 + 欧 + 印澳巴 + 加英) =====
TARGETS = [
    # ---- 日本(用户点名: 丰田) ----
    ("7203.T", "丰田汽车"), ("6758.T", "索尼"), ("9984.T", "软银集团"), ("6861.T", "基恩士"),
    ("8306.T", "三菱UFJ"), ("6501.T", "日立"), ("6902.T", "电装"), ("7267.T", "本田"),
    ("9432.T", "NTT"), ("6098.T", "Recruit"), ("4568.T", "第一三共"), ("7741.T", "HOYA"),
    ("8035.T", "东京电子"), ("6857.T", "爱德万测试"), ("6920.T", "Lasertec"), ("6146.T", "发那科"),
    ("4502.T", "武田药品"), ("5108.T", "普利司通"), ("6301.T", "小松制作所"), ("9022.T", "JR东海"),
    # ---- 韩国(用户点名: 三星/海力士) ----
    ("005930.KS", "三星电子"), ("000660.KS", "SK海力士"), ("051910.KS", "LG化学"),
    ("005380.KS", "现代汽车"), ("035420.KS", "NAVER"), ("207940.KS", "三星生物"),
    ("006400.KS", "三星SDI"), ("035720.KS", "Kakao"), ("028260.KS", "三星物产"),
    ("105560.KS", "KB金融"), ("055550.KS", "新韩金融"), ("012330.KS", "现代摩比斯"),
    ("034730.KS", "SK"), ("018260.KS", "三星SDS"), ("096770.KS", "SK创新"),
    # ---- 台湾 ----
    ("2330.TW", "台积电"), ("2454.TW", "联发科"), ("2317.TW", "鸿海"), ("2382.TW", "广达"),
    ("3711.TW", "日月光"), ("2308.TW", "台达电"), ("2882.TW", "国泰金"), ("1301.TW", "台塑"),
    ("3008.TW", "大立光"), ("2379.TW", "瑞昱"), ("2408.TW", "南亚科"), ("2303.TW", "联电"),
    # ---- 欧洲 ----
    ("ASML.AS", "ASML"), ("MC.PA", "LVMH"), ("SAP.DE", "SAP"), ("NOVO-B.CO", "诺和诺德"),
    ("NESN.SW", "雀巢"), ("SIE.DE", "西门子"), ("ALV.DE", "安联"), ("SAN.MC", "桑坦德"),
    ("TTE.PA", "道达尔"), ("OR.PA", "欧莱雅"), ("AIR.PA", "空客"), ("SU.PA", "施耐德"),
    ("NOKIA.HE", "诺基亚"), ("VOLV-B.ST", "沃尔沃"), ("AZN.L", "阿斯利康"), ("SHEL.L", "壳牌"),
    ("HSBA.L", "汇丰"), ("ULVR.L", "联合利华"), ("RIO.L", "力拓"), ("GLEN.L", "嘉能可"),
    # ---- 印度/澳洲/巴西/加拿大 ----
    ("RELIANCE.NS", "信实工业"), ("TCS.NS", "塔塔咨询"), ("HDFCBANK.NS", "HDFC银行"),
    ("INFY.NS", "Infosys"), ("BHP.AX", "必和必拓"), ("RIO.AX", "力拓澳"), ("CBA.AX", "澳联邦银行"),
    ("VALE", "淡水河谷"), ("PBR", "巴西石油"), ("SHOP.TO", "Shopify"), ("RY.TO", "加拿大皇家银行"),
    ("TSM", "台积电ADR"), ("TM", "丰田ADR"), ("SONY", "索尼ADR"),
]


def fetch(sym, retries=3):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?range=max&interval=1wk")
    op = urllib.request.build_opener(urllib.request.ProxyHandler(PROXY))
    for a in range(retries):
        try:
            with op.open(urllib.request.Request(url, headers=UA), timeout=35) as r:
                d = json.load(r)
            res = d["chart"]["result"][0]
            ts = res["timestamp"]
            q = res["indicators"]["quote"][0]
            adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
            vals = adj if adj else q["close"]          # 优先用复权价
            idx = pd.to_datetime(ts, unit="s")
            s = pd.Series(vals, index=idx).sort_index()
            s = s[s > 0].dropna()
            s = s[~s.index.duplicated(keep="last")]
            s.name = sym
            return s
        except Exception as e:
            if a == retries - 1:
                raise
            time.sleep(3 * (a + 1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=1.6)
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    panel = pd.read_csv(OUT, index_col=0, parse_dates=True) if os.path.exists(OUT) else pd.DataFrame()
    have = set(panel.columns)
    todo = [(c, n) for c, n in TARGETS if c not in have]
    if args.status:
        print(f"面板 {panel.shape}; 清单 {len(TARGETS)}; 待抓 {len(todo)}")
        return

    print(f"现有 {panel.shape[1]} 列 | 待抓 {len(todo)}", flush=True)
    ok, fail = {}, []
    for i, (sym, name) in enumerate(todo, 1):
        try:
            s = fetch(sym)
            if s is None or len(s) < 100:
                raise RuntimeError("数据过少")
            ok[sym] = s
            s.to_csv(os.path.join(RAW, f"{sym.replace('.','_')}.csv"), header=["close"])
            print(f"{i:3d}/{len(todo)} {sym:<14}{name:<12}{len(s):>5}周 "
                  f"{s.index[0].date()}~{s.index[-1].date()}", flush=True)
        except Exception as e:
            print(f"{i:3d}/{len(todo)} {sym:<14}{name:<12}ERR {str(e)[:45]}", flush=True)
            fail.append(sym)
        time.sleep(args.sleep)
        if len(ok) > 0 and len(ok) % 25 == 0:
            panel = pd.concat([panel, pd.DataFrame(ok).sort_index()], axis=1)
            panel = panel.loc[:, ~panel.columns.duplicated()]
            panel = panel[~panel.index.duplicated(keep="last")].sort_index()
            panel.to_csv(OUT)
            print(f"  --- 阶段存盘: {panel.shape[1]} 列 ---", flush=True)
            ok = {}

    if ok:
        panel = pd.concat([panel, pd.DataFrame(ok).sort_index()], axis=1)
        panel = panel.loc[:, ~panel.columns.duplicated()]
        panel = panel[~panel.index.duplicated(keep="last")].sort_index()
        panel.to_csv(OUT)
    print(f"\n成功 {len(todo)-len(fail)} / 失败 {len(fail)}")
    print(f"Yahoo全球面板: {panel.shape}")
    if fail:
        print("失败:", ", ".join(fail[:40]))


if __name__ == "__main__":
    main()
