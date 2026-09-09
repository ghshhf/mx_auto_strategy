# -*- coding: utf-8 -*-
"""
A股龙头抓取 (腾讯行情, 免费不限速, hfq 后复权)

接口: https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
      ?param=sh600519,week,<start>,<end>,640,hfq
坑: 单段上限 640 条 -> 按 12 年分段滚动; 必须用 hfq(qfq 长期会把早期价格压成负数)

价值: A股 与美股/港股相关性低 -> 给"最小相关贪心"提供真正的低相关来源
"""
import argparse, os, time, json, urllib.request
import pandas as pd

PROXY = "http://127.0.0.1:3067"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "a_leaders_weekly_adjclose.csv")
RAW = os.path.join(HERE, "data", "raw_tencent_a")
os.makedirs(RAW, exist_ok=True)

URL = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
       "?param={sym},week,{start},{end},640,hfq")

# ===== A股龙头清单(高波动行业优先) =====
TARGETS = [
    # 半导体/科技
    ("sh688981", "中芯国际"), ("sz002049", "紫光国微"), ("sh603501", "韦尔股份"),
    ("sz300782", "卓胜微"), ("sh688012", "中微公司"), ("sh688008", "澜起科技"),
    ("sz300661", "圣邦股份"), ("sh603986", "兆易创新"), ("sz002185", "华天科技"),
    ("sh600584", "长电科技"), ("sz002156", "通富微电"), ("sz300223", "北京君正"),
    ("sh688521", "芯原股份"), ("sz300373", "扬杰科技"), ("sh688036", "传音控股"),
    ("sz002415", "海康威视"), ("sz002236", "大华股份"), ("sh600745", "闻泰科技"),
    ("sz002475", "立讯精密"), ("sz002241", "歌尔股份"), ("sh603160", "汇顶科技"),
    # 新能源/锂电/光伏
    ("sz300750", "宁德时代"), ("sz002594", "比亚迪"), ("sz300124", "汇川技术"),
    ("sh688599", "天合光能"), ("sz002459", "晶澳科技"), ("sh601012", "隆基绿能"),
    ("sz300274", "阳光电源"), ("sh688223", "晶科能源"), ("sz002460", "赣锋锂业"),
    ("sh603799", "华友钴业"), ("sz002466", "天齐锂业"), ("sh600438", "通威股份"),
    ("sz300316", "晶盛机电"), ("sh688390", "固德威"), ("sz300827", "上能电气"),
    ("sh605117", "德业股份"), ("sz002812", "恩捷股份"), ("sh688567", "孚能科技"),
    # 医药/生物
    ("sh600276", "恒瑞医药"), ("sz300760", "迈瑞医疗"), ("sh600196", "复星医药"),
    ("sz300347", "泰格医药"), ("sh603259", "药明康德"), ("sz300759", "康龙化成"),
    ("sh688180", "君实生物"), ("sz300142", "沃森生物"), ("sh600521", "华海药业"),
    ("sz002422", "科伦药业"), ("sh688185", "康希诺"), ("sz300601", "康泰生物"),
    ("sh603087", "甘李药业"), ("sz300529", "健帆生物"), ("sh688399", "硕世生物"),
    # 军工
    ("sh600893", "航发动力"), ("sz000768", "中航西飞"), ("sh600760", "中航沈飞"),
    ("sz002179", "中航光电"), ("sh600038", "中直股份"), ("sz300699", "光威复材"),
    ("sh600967", "内蒙一机"), ("sz002013", "中航机电"),
    # 消费/白酒/食品
    ("sh600519", "贵州茅台"), ("sz000858", "五粮液"), ("sh600887", "伊利股份"),
    ("sh603288", "海天味业"), ("sz000651", "格力电器"), ("sz000333", "美的集团"),
    ("sh600690", "海尔智家"), ("sz002714", "牧原股份"), ("sh600298", "安琪酵母"),
    ("sh600809", "山西汾酒"), ("sz000568", "泸州老窖"), ("sh600132", "重庆啤酒"),
    ("sh603833", "欧派家居"), ("sz002572", "索菲亚"),
    # 资源/材料/周期
    ("sh600111", "北方稀土"), ("sh601899", "紫金矿业"), ("sh600362", "江西铜业"),
    ("sh601600", "中国铝业"), ("sz000933", "神火股份"), ("sh600188", "兖州煤业"),
    ("sh601088", "中国神华"), ("sh600028", "中国石化"), ("sh601857", "中国石油"),
    ("sz000983", "山西焦煤"), ("sh600585", "海螺水泥"), ("sz002001", "新和成"),
    ("sh600309", "万华化学"), ("sz000792", "盐湖股份"), ("sh603993", "洛阳钼业"),
    ("sz000630", "铜陵有色"), ("sh601168", "西部矿业"), ("sz002128", "露天煤业"),
    # 金融/券商/金融科技
    ("sz000001", "平安银行"), ("sh600036", "招商银行"), ("sh601318", "中国平安"),
    ("sh600030", "中信证券"), ("sh601166", "兴业银行"), ("sz000776", "广发证券"),
    ("sh600837", "海通证券"), ("sh600000", "浦发银行"), ("sz300059", "东方财富"),
    ("sh600570", "恒生电子"), ("sz002230", "科大讯飞"), ("sh601688", "华泰证券"),
    ("sh601788", "光大证券"), ("sz002736", "国信证券"),
    # 汽车/机械/工业
    ("sh601633", "长城汽车"), ("sh600104", "上汽集团"), ("sh601127", "赛力斯"),
    ("sh600066", "宇通客车"), ("sh600031", "三一重工"), ("sz002008", "大族激光"),
    ("sh601766", "中国中车"), ("sz300450", "先导智能"), ("sh600150", "中国船舶"),
    ("sz002050", "三花智控"), ("sh601100", "恒立液压"), ("sz002472", "双环传动"),
    # 传媒/互联网/其他
    ("sz002027", "分众传媒"), ("sh600637", "东方明珠"), ("sz300413", "芒果超媒"),
    ("sh603000", "人民网"), ("sz002739", "万达电影"), ("sh600845", "宝信软件"),
    ("sz300454", "深信服"), ("sh688111", "金山办公"), ("sz300496", "中科创达"),
    ("sh600588", "用友网络"), ("sz002410", "广联达"), ("sh600570", "恒生电子"),
    # 化工/新材料
    ("sh600346", "恒力石化"), ("sz002648", "卫星化学"), ("sh603260", "合盛硅业"),
    ("sz002064", "华峰化学"), ("sh600426", "华鲁恒升"), ("sz300699", "光威复材"),
    ("sh688065", "凯赛生物"), ("sz002497", "雅化集团"),
    # 公用/电力/环保
    ("sh600900", "长江电力"), ("sh601985", "中国核电"), ("sh003816", "中国广核"),
    ("sz003035", "南网能源"), ("sh600025", "华能水电"),
]


def fetch_segment(sym, start, end):
    url = URL.format(sym=sym, start=start, end=end)
    op = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    with op.open(url, timeout=30) as r:
        d = json.load(r)
    if d.get("code") != 0:
        return []
    v = d.get("data", {}).get(sym, {})
    key = None
    for k in v.keys():
        if "week" in k or "day" in k:
            key = k
            break
    if key is None:
        return []
    return v[key]


def fetch_full(sym, start_year=2005):
    """分段滚动: 每 12 年一段(640 周上限), 直到无新增"""
    rows, cur, end_y = {}, start_year, pd.Timestamp.now().year
    while cur <= end_y:
        seg_end = min(cur + 11, end_y)
        try:
            arr = fetch_segment(sym, f"{cur}-01-01", f"{seg_end}-12-31")
        except Exception:
            arr = []
        new = 0
        for it in arr:
            if not it or len(it) < 3:
                continue
            try:
                dt = pd.Timestamp(it[0]); c = float(it[2])
            except Exception:
                continue
            if dt not in rows and c > 0:
                rows[dt] = c; new += 1
        if new == 0 and cur > start_year:
            break
        cur = seg_end + 1
        time.sleep(0.12)
    if not rows:
        return None
    s = pd.Series(rows).sort_index()
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.3)
    args = ap.parse_args()

    panel = pd.read_csv(OUT, index_col=0, parse_dates=True) if os.path.exists(OUT) else pd.DataFrame()
    have = set(panel.columns)
    seen, uniq = set(), []
    for c, n in TARGETS:
        if c in seen:
            continue
        seen.add(c); uniq.append((c, n))
    todo = [(c, n) for c, n in uniq if c not in have]

    if args.status:
        print(f"面板 {panel.shape}; 清单去重 {len(uniq)}; 待抓 {len(todo)}")
        return

    print(f"现有 A股 {panel.shape[1]} 列 | 待抓 {len(todo)}", flush=True)
    ok, fail = {}, []
    for i, (code, name) in enumerate(todo, 1):
        try:
            s = fetch_full(code, start_year=2005)
            if s is None or len(s) < 100:
                raise RuntimeError("数据过少")
            s.name = code
            ok[code] = s
            s.to_csv(os.path.join(RAW, f"{code}.csv"), header=["close"])
            print(f"{i:3d}/{len(todo)} {code} {name:10s} {len(s):5d}周 "
                  f"{s.index[0].date()}~{s.index[-1].date()}", flush=True)
        except Exception as e:
            print(f"{i:3d}/{len(todo)} {code} {name:10s} ERR {str(e)[:40]}", flush=True)
            fail.append(code)
        time.sleep(args.sleep)
        if len(ok) > 0 and len(ok) % 40 == 0:
            panel = pd.concat([panel, pd.DataFrame(ok).sort_index()], axis=1, sort=True)
            panel = panel.loc[:, ~panel.columns.duplicated()]
            panel = panel[~panel.index.duplicated(keep="last")].sort_index()
            panel.to_csv(OUT)
            print(f"  --- 阶段存盘: A股 {panel.shape[1]} 列 ---", flush=True)
            ok = {}

    if ok:
        panel = pd.concat([panel, pd.DataFrame(ok).sort_index()], axis=1, sort=True)
        panel = panel.loc[:, ~panel.columns.duplicated()]
        panel = panel[~panel.index.duplicated(keep="last")].sort_index()
        panel.to_csv(OUT)
    print(f"\n成功 {len(uniq)-len(fail)} / 失败 {len(fail)}")
    print(f"A股面板: {panel.shape}")
    if fail:
        print("失败:", ", ".join(fail[:40]))


if __name__ == "__main__":
    main()
