# -*- coding: utf-8 -*-
"""
港股龙头批量抓取 (腾讯行情接口, 无需 key / 不限速)

腾讯接口 web.ifzq.gtimg.cn 单段上限 640 条 → 按 12 年分段滚动拉全历史。
港股必须用 **后复权 hfq**: 长期前复权会把早期价格压成负数(腾讯 2004 qfq 收盘 -54.98)。

用法:
  python fetch_hk_leaders_tencent.py            # 抓全部(增量跳过已抓)
  python fetch_hk_leaders_tencent.py --status
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_equities_tencent import fetch_full  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data")
RAW_DIR = os.path.join(OUT_DIR, "raw_tencent_hk")
os.makedirs(RAW_DIR, exist_ok=True)
PANEL = os.path.join(OUT_DIR, "hk_leaders_weekly_adjclose.csv")

# (代码, 名称)  —— 能叫出名字的港股龙头
TARGETS = [
    ("00001", "长和"), ("00002", "中电控股"), ("00003", "中华煤气"),
    ("00005", "汇丰控股"), ("00006", "电能实业"), ("00016", "新鸿基地产"),
    ("00027", "银河娱乐"), ("00151", "中国旺旺"), ("00267", "中信股份"),
    ("00291", "华润啤酒"), ("00322", "康师傅"), ("00345", "维他奶"),
    ("00386", "中国石化"), ("00388", "港交所"), ("00688", "中国海外发展"),
    ("00690", "联易融"), ("00700", "腾讯控股"), ("00728", "中国电信"),
    ("00762", "中兴通讯"), ("00763", "中兴?中国联通"), ("00857", "中国石油"),
    ("00883", "中国海洋石油"), ("00921", "海信家电"), ("00939", "建设银行"),
    ("00941", "中国移动"), ("00960", "龙湖集团"), ("00981", "中芯国际"),
    ("00992", "联想集团"), ("01024", "快手"), ("01044", "恒安国际"),
    ("01070", "TCL电子"), ("01088", "中国神华"), ("01093", "石药集团"),
    ("01109", "华润置地"), ("01138", "中远海能"), ("01169", "海尔智家"),
    ("01171", "兖矿能源"), ("01177", "中国生物制药"), ("01209", "华润万象生活"),
    ("01211", "比亚迪股份"), ("01288", "农业银行"), ("01299", "友邦保险"),
    ("01347", "华虹半导体"), ("01398", "工商银行"), ("01801", "信达生物"),
    ("01810", "小米集团"), ("01876", "百威亚太"), ("01898", "中煤能源"),
    ("01919", "中远海控"), ("01928", "金沙中国"), ("01929", "周大福"),
    ("02015", "理想汽车"), ("02018", "瑞声科技"), ("02020", "安踏体育"),
    ("02208", "金风科技"), ("02238", "广汽集团"), ("02269", "药明生物"),
    ("02318", "中国平安"), ("02319", "蒙牛乳业"), ("02331", "李宁"),
    ("02333", "长城汽车"), ("02382", "舜宇光学"), ("02380", "中国电力"),
    ("02600", "中国铝业"), ("02601", "中国太保"), ("02628", "中国人寿"),
    ("02899", "紫金矿业"), ("03323", "中国建材"), ("03328", "交通银行"),
    ("03690", "美团"), ("03692", "翰森制药"), ("03898", "时代电气"),
    ("03968", "招商银行"), ("03993", "洛阳钼业"), ("03988", "中国银行"),
    ("06060", "众安在线"), ("06618", "京东健康"), ("06690", "海尔智家H"),
    ("06862", "海底捞"), ("09618", "京东集团"), ("09668", "渤海银行"),
    ("09866", "蔚来"), ("09868", "小鹏汽车"), ("09881", "中芯?汇通达"),
    ("09922", "九毛九"), ("09961", "携程集团"), ("09988", "阿里巴巴"),
    ("09999", "网易"),
]


def load_panel():
    if os.path.exists(PANEL):
        return pd.read_csv(PANEL, index_col=0, parse_dates=True)
    return pd.DataFrame()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    panel = load_panel()
    have = set(panel.columns)
    todo = [(c, n) for c, n in TARGETS if c.lstrip("0") + "_HK" not in have]

    if args.status:
        print(f"面板 {panel.shape[0]} 行 x {panel.shape[1]} 列; 清单 {len(TARGETS)}, 待抓 {len(todo)}")
        return

    ok, fail = {}, []
    for i, (code, name) in enumerate(todo, 1):
        sym = "hk" + code
        tag = code.lstrip("0") + "_HK"
        try:
            s = fetch_full(sym, "hk", name, fq="hfq", start_year=1990)
            if s is None or len(s) < 10:
                raise RuntimeError("数据过少")
            s.name = tag
            ok[tag] = s
            s.to_csv(os.path.join(RAW_DIR, f"{tag}.csv"), header=["close"])
            print(f"{i:3d}/{len(todo)} {tag:10s} {name:10s} {len(s):5d}周 "
                  f"{s.index[0].date()}~{s.index[-1].date()}", flush=True)
        except Exception as e:
            print(f"{i:3d}/{len(todo)} {tag:10s} {name:10s} ERR {str(e)[:60]}", flush=True)
            fail.append(tag)

    if ok:
        new = pd.DataFrame(ok).sort_index()
        panel = pd.concat([panel, new], axis=1, sort=True)
        panel = panel[~panel.index.duplicated(keep="last")].sort_index()
        panel.to_csv(PANEL)
        print(f"\n面板: {panel.shape[0]} 行 x {panel.shape[1]} 列 -> {PANEL}")
    print(f"成功 {len(ok)} / 失败 {len(fail)}")
    if fail:
        print("失败:", ", ".join(fail))


HK_SUFFIX = "_HK"

if __name__ == "__main__":
    main()
