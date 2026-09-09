# -*- coding: utf-8 -*-
"""
Twelve Data 美股「龙头宇宙」大批量抓取 (第二批, 2026-09-09)

背景: 第一批 fetch_us_universe_twelvedata.py 已抓 56 个 ETF/宽基。
      本脚本扩容到 **340 个能叫出名字的标的**: 各行业龙头个股 + 中概 ADR + 主题/因子/杠杆 ETF。

🔑 关键约束 (实测):
  - Twelve Data 免费档仅覆盖美股市场 (港股/日股需付费 Grow 计划)
  - 免费额度 800 credits/天, time_series = 1 credit/标的
  - 限流 8 credits/分钟 → 单条串行 + SLEEP 间隔; 遇到 429 自动退避重试
  - 美股历史极深: AMD 可到 1980-03

用法:
  python fetch_us_leaders_twelvedata.py --start 0 --end 50     # 抓第 0~49 个
  python fetch_us_leaders_twelvedata.py --list                 # 只打印清单
  python fetch_us_leaders_twelvedata.py --status               # 查看已抓进度
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data")
RAW_DIR = os.path.join(OUT_DIR, "raw_twelvedata")
os.makedirs(RAW_DIR, exist_ok=True)

PANEL = os.path.join(OUT_DIR, "us_universe_weekly_adjclose.csv")
LEGACY = os.path.join(OUT_DIR, "us_etf_weekly_adjclose.csv")

KEY = json.load(open(os.path.join(HERE, "keys.local.json")))["twelvedata"]["key"]
SLEEP = 7.0

# (symbol, 名称, 分类)  —— 340 个能叫出名字的标的
TARGETS = [
    # ============ 科技巨头 / 软件 / 互联网 (44) ============
    ("AAPL", "苹果", "科技"),
    ("MSFT", "微软", "科技"),
    ("GOOGL", "谷歌", "科技"),
    ("AMZN", "亚马逊", "科技"),
    ("META", "Meta脸书", "科技"),
    ("NVDA", "英伟达", "科技"),
    ("TSLA", "特斯拉", "科技"),
    ("AVGO", "博通", "科技"),
    ("INTC", "英特尔", "科技"),
    ("CRM", "Salesforce", "科技"),
    ("ORCL", "甲骨文", "科技"),
    ("ADBE", "Adobe", "科技"),
    ("NFLX", "奈飞", "科技"),
    ("CSCO", "思科", "科技"),
    ("QCOM", "高通", "科技"),
    ("TXN", "德州仪器", "科技"),
    ("MU", "美光", "科技"),
    ("IBM", "IBM", "科技"),
    ("NOW", "ServiceNow", "科技"),
    ("SHOP", "Shopify", "科技"),
    ("SNOW", "Snowflake", "科技"),
    ("PLTR", "Palantir", "科技"),
    ("DDOG", "Datadog", "科技"),
    ("MDB", "MongoDB", "科技"),
    ("ZS", "Zscaler", "科技"),
    ("CRWD", "CrowdStrike", "科技"),
    ("NET", "Cloudflare", "科技"),
    ("OKTA", "Okta", "科技"),
    ("TWLO", "Twilio", "科技"),
    ("DOCU", "DocuSign", "科技"),
    ("ANSS", "Ansys", "科技"),
    ("CDNS", "Cadence", "科技"),
    ("SNPS", "Synopsys", "科技"),
    ("ANET", "Arista网络", "科技"),
    ("DELL", "戴尔", "科技"),
    ("HPE", "慧与", "科技"),
    ("STX", "希捷", "科技"),
    ("WDC", "西部数据", "科技"),
    ("NTAP", "NetApp", "科技"),
    ("PSTG", "Pure Storage", "科技"),
    ("SMCI", "超微电脑", "科技"),
    ("ARM", "ARM控股", "科技"),
    ("TSM", "台积电ADR", "科技"),
    ("VRT", "Vertiv", "科技"),
    # ============ 半导体设备 / 芯片 (12) ============
    ("AMAT", "应用材料", "半导体"),
    ("LRCX", "泛林集团", "半导体"),
    ("KLAC", "科磊", "半导体"),
    ("ASML", "阿斯麦", "半导体"),
    ("MRVL", "Marvell", "半导体"),
    ("NXPI", "恩智浦", "半导体"),
    ("ON", "安森美", "半导体"),
    ("MCHP", "微芯科技", "半导体"),
    ("ADI", "亚德诺", "半导体"),
    ("SWKS", "思佳讯", "半导体"),
    ("TER", "泰瑞达", "半导体"),
    ("ENTG", "Entegris", "半导体"),
    # ============ 金融 / 银行 / 保险 (21) ============
    ("JPM", "摩根大通", "金融"),
    ("BAC", "美国银行", "金融"),
    ("WFC", "富国银行", "金融"),
    ("GS", "高盛", "金融"),
    ("MS", "摩根士丹利", "金融"),
    ("C", "花旗", "金融"),
    ("V", "Visa", "金融"),
    ("MA", "万事达", "金融"),
    ("AXP", "美国运通", "金融"),
    ("BLK", "贝莱德", "金融"),
    ("SCHW", "嘉信理财", "金融"),
    ("USB", "合众银行", "金融"),
    ("PNC", "PNC金融", "金融"),
    ("TFC", "Truist", "金融"),
    ("BK", "纽约梅隆", "金融"),
    ("MET", "大都会人寿", "金融"),
    ("PRU", "保德信", "金融"),
    ("AIG", "AIG", "金融"),
    ("TRV", "旅行者保险", "金融"),
    ("ALL", "Allstate", "金融"),
    ("CB", "Chubb", "金融"),
    # ============ 交易所 / 评级 / 资管 (7) ============
    ("CME", "芝商所", "交易所"),
    ("ICE", "洲际交易所", "交易所"),
    ("NDAQ", "纳斯达克", "交易所"),
    ("CBOE", "CBOE", "交易所"),
    ("SPGI", "标普全球", "交易所"),
    ("MCO", "穆迪", "交易所"),
    ("FICO", "FICO", "交易所"),
    # ============ 医疗 / 生物 (18) ============
    ("JNJ", "强生", "医疗"),
    ("UNH", "联合健康", "医疗"),
    ("LLY", "礼来", "医疗"),
    ("PFE", "辉瑞", "医疗"),
    ("MRK", "默沙东", "医疗"),
    ("ABBV", "艾伯维", "医疗"),
    ("TMO", "赛默飞", "医疗"),
    ("ABT", "雅培", "医疗"),
    ("DHR", "丹纳赫", "医疗"),
    ("BMY", "百时美施贵宝", "医疗"),
    ("AMGN", "安进", "医疗"),
    ("GILD", "吉利德", "医疗"),
    ("CVS", "CVS健康", "医疗"),
    ("MDT", "美敦力", "医疗"),
    ("ISRG", "直觉外科", "医疗"),
    ("BIIB", "Biogen", "医疗"),
    ("VRTX", "Vertex", "医疗"),
    ("REGN", "再生元", "医疗"),
    # ============ 消费 / 零售 / 餐饮 (22) ============
    ("WMT", "沃尔玛", "消费"),
    ("COST", "好市多", "消费"),
    ("HD", "家得宝", "消费"),
    ("PG", "宝洁", "消费"),
    ("KO", "可口可乐", "消费"),
    ("PEP", "百事", "消费"),
    ("MCD", "麦当劳", "消费"),
    ("NKE", "耐克", "消费"),
    ("SBUX", "星巴克", "消费"),
    ("DIS", "迪士尼", "消费"),
    ("TGT", "塔吉特", "消费"),
    ("LOW", "劳氏", "消费"),
    ("MDLZ", "亿滋", "消费"),
    ("KHC", "卡夫亨氏", "消费"),
    ("GIS", "通用磨坊", "消费"),
    ("KMB", "金佰利", "消费"),
    ("CL", "高露洁", "消费"),
    ("YUM", "百胜餐饮", "消费"),
    ("DRI", "达登餐厅", "消费"),
    ("CCL", "嘉年华邮轮", "消费"),
    ("RCL", "皇家加勒比", "消费"),
    ("MNST", "怪物饮料", "消费"),
    # ============ 工业 / 制造 / 运输 (15) ============
    ("CAT", "卡特彼勒", "工业"),
    ("BA", "波音", "工业"),
    ("HON", "霍尼韦尔", "工业"),
    ("GE", "通用电气", "工业"),
    ("LMT", "洛克希德马丁", "工业"),
    ("RTX", "雷神", "工业"),
    ("DE", "迪尔农机", "工业"),
    ("UPS", "联合包裹", "工业"),
    ("HWM", "Howmet", "工业"),
    ("GD", "通用动力", "工业"),
    ("NOC", "诺格", "工业"),
    ("LHX", "L3Harris", "工业"),
    ("EMR", "艾默生", "工业"),
    ("ETN", "伊顿", "工业"),
    ("FDX", "联邦快递", "工业"),
    # ============ 能源 / 油气 (12) ============
    ("XOM", "埃克森美孚", "能源"),
    ("CVX", "雪佛龙", "能源"),
    ("COP", "康菲石油", "能源"),
    ("SLB", "斯伦贝谢", "能源"),
    ("EOG", "EOG资源", "能源"),
    ("MPC", "Marathon石油", "能源"),
    ("PSX", "Phillips66", "能源"),
    ("VLO", "Valero", "能源"),
    ("OXY", "西方石油", "能源"),
    ("HAL", "哈里伯顿", "能源"),
    ("BKR", "贝克休斯", "能源"),
    ("FANG", "Diamondback", "能源"),
    # ============ 汽车 / 出行 / 住宿 (9) ============
    ("F", "福特", "出行"),
    ("GM", "通用汽车", "出行"),
    ("RIVN", "Rivian", "出行"),
    ("LCID", "Lucid", "出行"),
    ("UBER", "优步", "出行"),
    ("LYFT", "Lyft", "出行"),
    ("ABNB", "Airbnb", "出行"),
    ("EXPE", "Expedia", "出行"),
    ("TRIP", "TripAdvisor", "出行"),
    # ============ 中概 ADR (18) ============
    ("BABA", "阿里巴巴", "中概"),
    ("JD", "京东", "中概"),
    ("PDD", "拼多多", "中概"),
    ("BIDU", "百度", "中概"),
    ("NTES", "网易", "中概"),
    ("NIO", "蔚来", "中概"),
    ("LI", "理想汽车", "中概"),
    ("XPEV", "小鹏汽车", "中概"),
    ("TCOM", "携程", "中概"),
    ("YUMC", "百胜中国", "中概"),
    ("ZTO", "中通快递", "中概"),
    ("HTHT", "华住", "中概"),
    ("TME", "腾讯音乐", "中概"),
    ("BILI", "哔哩哔哩", "中概"),
    ("BEKE", "贝壳", "中概"),
    ("FUTU", "富途控股", "中概"),
    ("TIGR", "老虎证券", "中概"),
    ("IQ", "爱奇艺", "中概"),
    # ============ 矿业 / 金属 / 材料 (14) ============
    ("FCX", "自由港铜金", "矿业"),
    ("NEM", "纽蒙特", "矿业"),
    ("GOLD", "巴里克黄金", "矿业"),
    ("RIO", "力拓", "矿业"),
    ("BHP", "必和必拓", "矿业"),
    ("VALE", "淡水河谷", "矿业"),
    ("AA", "美国铝业", "矿业"),
    ("CLF", "克利夫兰克里夫", "矿业"),
    ("X", "美国钢铁", "矿业"),
    ("NUE", "纽柯钢铁", "矿业"),
    ("STLD", "Steel Dynamics", "矿业"),
    ("MP", "MP Materials稀土", "矿业"),
    ("ALB", "雅保锂业", "矿业"),
    ("SQM", "SQM锂业", "矿业"),
    # ============ 核电 / 电力 / 新能源 (12) ============
    ("SMR", "NuScale核电", "电力"),
    ("OKLO", "Oklo核电", "电力"),
    ("CCJ", "Cameco铀", "电力"),
    ("UEC", "Uranium Energy", "电力"),
    ("ENPH", "Enphase", "电力"),
    ("FSLR", "First Solar", "电力"),
    ("PLUG", "Plug Power氢", "电力"),
    ("BE", "Bloom Energy", "电力"),
    ("VST", "Vistra电力", "电力"),
    ("CEG", "Constellation", "电力"),
    ("TLN", "Talen Energy", "电力"),
    ("NRG", "NRG Energy", "电力"),
    # ============ 公用事业 (5) ============
    ("NEE", "NextEra", "公用"),
    ("DUK", "杜克能源", "公用"),
    ("SO", "南方公司", "公用"),
    ("D", "Dominion", "公用"),
    ("AEP", "美国电力", "公用"),
    # ============ 电信 / 媒体 (10) ============
    ("TMUS", "T-Mobile", "电信"),
    ("VZ", "Verizon", "电信"),
    ("T", "AT&T", "电信"),
    ("CMCSA", "康卡斯特", "电信"),
    ("WBD", "华纳兄弟探索", "电信"),
    ("PARA", "派拉蒙", "电信"),
    ("FOX", "福克斯", "电信"),
    ("NYT", "纽约时报", "电信"),
    ("OMC", "宏盟", "电信"),
    ("IPG", "Interpublic", "电信"),
    # ============ 加密 / 区块链 (9) ============
    ("COIN", "Coinbase", "加密"),
    ("MSTR", "MicroStrategy", "加密"),
    ("MARA", "Marathon挖矿", "加密"),
    ("RIOT", "Riot挖矿", "加密"),
    ("HOOD", "Robinhood", "加密"),
    ("CLSK", "CleanSpark", "加密"),
    ("WULF", "TeraWulf", "加密"),
    ("CORZ", "Core Scientific", "加密"),
    ("IREN", "IREN挖矿", "加密"),
    # ============ 量子 / 前沿科技 (6) ============
    ("IONQ", "IonQ量子", "前沿"),
    ("RGTI", "Rigetti量子", "前沿"),
    ("QBTS", "D-Wave量子", "前沿"),
    ("QUBT", "Quantum Computing", "前沿"),
    ("ARQQ", "Arqit量子安全", "前沿"),
    ("LAES", "SEALSQ", "前沿"),
    # ============ 太空 / 无人机 / eVTOL (6) ============
    ("RKLB", "Rocket Lab", "太空"),
    ("ASTS", "AST SpaceMobile", "太空"),
    ("LUNR", "Intuitive Machines", "太空"),
    ("AVAV", "AeroVironment", "太空"),
    ("JOBY", "Joby Aviation", "太空"),
    ("ACHR", "Archer Aviation", "太空"),
    # ============ AI 基建 / 数据中心 (7) ============
    ("CRWV", "CoreWeave", "AI基建"),
    ("NBIS", "Nebius", "AI基建"),
    ("APLD", "Applied Digital", "AI基建"),
    ("GLXY", "Galaxy Digital", "AI基建"),
    ("MOD", "Modular?Realty", "AI基建"),
    ("EME", "EMCOR", "AI基建"),
    ("WLDN", "Willdan", "AI基建"),
    # ============ 电商 / 互联网其他 (10) ============
    ("BRK-B", "伯克希尔B", "综合"),
    ("RDDT", "Reddit", "互联网"),
    ("SPOT", "Spotify", "互联网"),
    ("SNAP", "Snapchat", "互联网"),
    ("PINS", "Pinterest", "互联网"),
    ("EBAY", "eBay", "互联网"),
    ("ETSY", "Etsy", "互联网"),
    ("W", "Wayfair", "互联网"),
    ("CPNG", "Coupang", "互联网"),
    ("SE", "Sea Limited", "互联网"),
    # ============ 烟草 / 酒类 / 饮料 (8) ============
    ("PM", "菲利普莫里斯", "烟酒"),
    ("MO", "奥驰亚", "烟酒"),
    ("BUD", "百威英博", "烟酒"),
    ("STZ", "星座品牌", "烟酒"),
    ("TAP", "Molson Coors", "烟酒"),
    ("SAM", "波士顿啤酒", "烟酒"),
    ("KDP", "Keurig Dr Pepper", "烟酒"),
    ("CELH", "Celsius控股", "烟酒"),
    # ============ 农业 / 化肥 (6) ============
    ("ADM", "Archer-Daniels", "农业"),
    ("BG", "Bunge", "农业"),
    ("CTVA", "Corteva", "农业"),
    ("MOS", "Mosaic", "农业"),
    ("CF", "CF Industries", "农业"),
    ("NTR", "Nutrien", "农业"),
    # ============ 化工 / 纸业 (6) ============
    ("DOW", "陶氏", "化工"),
    ("DD", "杜邦", "化工"),
    ("LYB", "LyondellBasell", "化工"),
    ("EMN", "Eastman", "化工"),
    ("IP", "国际纸业", "化工"),
    ("PKG", "Packaging Corp", "化工"),
    # ============ 支付 / 金融IT (6) ============
    ("PYPL", "PayPal", "支付"),
    ("XYZ", "Block", "支付"),
    ("FI", "Fiserv", "支付"),
    ("GPN", "Global Payments", "支付"),
    ("JKHY", "Jack Henry", "支付"),
    ("WEX", "WEX Inc", "支付"),
    # ============ 咨询 / IT服务 (5) ============
    ("ACN", "埃森哲", "IT服务"),
    ("CTSH", "Cognizant", "IT服务"),
    ("IT", "Gartner", "IT服务"),
    ("INFY", "Infosys", "IT服务"),
    ("WIT", "Wipro", "IT服务"),
    # ============ 博彩 / 酒店 (6) ============
    ("LVS", "拉斯维加斯金沙", "博彩"),
    ("WYNN", "永利度假", "博彩"),
    ("MGM", "美高梅", "博彩"),
    ("MAR", "万豪", "博彩"),
    ("HLT", "希尔顿", "博彩"),
    ("HGV", "Hilton Grand", "博彩"),
    # ============ 地产 / REIT (8) ============
    ("O", "Realty Income", "REIT"),
    ("SPG", "Simon地产", "REIT"),
    ("PLD", "Prologis物流", "REIT"),
    ("AMT", "American Tower", "REIT"),
    ("CCI", "Crown Castle", "REIT"),
    ("EQIX", "Equinix数据中心", "REIT"),
    ("DLR", "Digital Realty", "REIT"),
    ("WELL", "Welltower", "REIT"),
    # ============ 保险经纪 / 其他金融 (4) ============
    ("MMC", "Marsh McLennan", "保险经纪"),
    ("AON", "怡安", "保险经纪"),
    ("WTW", "Willis Towers", "保险经纪"),
    ("BRO", "Brown & Brown", "保险经纪"),
    # ============ 教育 / 宠物 / 杂项 (4) ============
    ("CHGG", "Chegg", "教育"),
    ("DUOL", "Duolingo", "教育"),
    ("TOST", "Toast", "教育"),
    ("CHWY", "Chewy", "教育"),
    # ============ 主题 / 行业细分 ETF (40) ============
    ("ARKK", "木头姐创新", "主题ETF"),
    ("ARKW", "木头姐互联网", "主题ETF"),
    ("ARKF", "木头姐金融科技", "主题ETF"),
    ("SMH", "半导体ETF", "主题ETF"),
    ("SOXX", "半导体ETF2", "主题ETF"),
    ("IGV", "软件ETF", "主题ETF"),
    ("XBI", "生物科技ETF", "主题ETF"),
    ("IBB", "生物科技ETF2", "主题ETF"),
    ("XRT", "零售ETF", "主题ETF"),
    ("XHB", "住宅建筑ETF", "主题ETF"),
    ("XAR", "航空航天ETF", "主题ETF"),
    ("PPA", "国防ETF", "主题ETF"),
    ("XOP", "油气开采ETF", "主题ETF"),
    ("OIH", "油服ETF", "主题ETF"),
    ("ICLN", "清洁能源ETF", "主题ETF"),
    ("TAN", "太阳能ETF", "主题ETF"),
    ("GDX", "金矿股ETF", "主题ETF"),
    ("GDXJ", "小金矿ETF", "主题ETF"),
    ("SIL", "银矿股ETF", "主题ETF"),
    ("SILJ", "小银矿ETF", "主题ETF"),
    ("PICK", "金属矿业ETF", "主题ETF"),
    ("XME", "金属煤炭ETF", "主题ETF"),
    ("REMX", "稀土ETF", "主题ETF"),
    ("LIT", "锂电ETF", "主题ETF"),
    ("URA", "铀ETF", "主题ETF"),
    ("NLR", "核电ETF", "主题ETF"),
    ("IYR", "地产ETF", "主题ETF"),
    ("REM", "抵押REIT ETF", "主题ETF"),
    ("KBE", "银行ETF", "主题ETF"),
    ("KRE", "区域银行ETF", "主题ETF"),
    ("ITB", "建筑ETF", "主题ETF"),
    ("MOO", "农业ETF", "主题ETF"),
    ("JETS", "航空ETF", "主题ETF"),
    ("BLOK", "区块链ETF", "主题ETF"),
    ("WCLD", "云计算ETF", "主题ETF"),
    ("CIBR", "网络安全ETF", "主题ETF"),
    ("BOTZ", "机器人ETF", "主题ETF"),
    ("AIQ", "AI ETF", "主题ETF"),
    ("ROBO", "机器人ETF2", "主题ETF"),
    ("HACK", "网络安全ETF2", "主题ETF"),
    # ============ 债券细分 (12) ============
    ("AGG", "总债券", "债券细分"),
    ("MUB", "市政债", "债券细分"),
    ("VCIT", "中期公司债", "债券细分"),
    ("VCSH", "短期公司债", "债券细分"),
    ("MBB", "MBS", "债券细分"),
    ("JNK", "垃圾债", "债券细分"),
    ("PFF", "优先股", "债券细分"),
    ("BIL", "1-3月国库券", "债券细分"),
    ("SHV", "短期国债", "债券细分"),
    ("TLH", "10-20年国债", "债券细分"),
    ("GOVT", "全期限国债", "债券细分"),
    ("BWZ", "短债", "债券细分"),
    # ============ 波动率 / 杠杆 (12) ============
    ("UVXY", "VIX短期期货", "波动率"),
    ("VXX", "VIX期货", "波动率"),
    ("VIXM", "VIX中期", "波动率"),
    ("VIXY", "VIX短期", "波动率"),
    ("TQQQ", "纳指3倍多", "杠杆"),
    ("SQQQ", "纳指3倍空", "杠杆"),
    ("UPRO", "标普3倍多", "杠杆"),
    ("SPXU", "标普3倍空", "杠杆"),
    ("SOXL", "半导体3倍多", "杠杆"),
    ("SOXS", "半导体3倍空", "杠杆"),
    ("NVDL", "英伟达2倍多", "杠杆"),
    ("TSLL", "特斯拉2倍多", "杠杆"),
    # ============ 货币 / 因子 (8) ============
    ("UUP", "美元指数", "货币"),
    ("FXY", "日元", "货币"),
    ("FXE", "欧元", "货币"),
    ("FXB", "英镑", "货币"),
    ("FXA", "澳元", "货币"),
    ("MTUM", "动量因子", "因子"),
    ("VLUE", "价值因子", "因子"),
    ("USMV", "低波动因子", "因子"),
    # ============ 全球 ADR 龙头 (62) ============
    # 🔑 关键: Twelve Data 免费档只有美股市场, 但**美股上市的 ADR 属于美股**!
    #    这是绕过限制拿到日本/欧洲/韩国/巴西龙头的唯一免费途径 (含用户点名的丰田 TM)
    # --- 日本 ADR (32) ---
    ("TM", "丰田汽车ADR", "日股ADR"),
    ("HMC", "本田汽车ADR", "日股ADR"),
    ("SONY", "索尼ADR", "日股ADR"),
    ("MUFG", "三菱日联金融", "日股ADR"),
    ("SMFG", "三井住友金融", "日股ADR"),
    ("MFG", "瑞穗金融", "日股ADR"),
    ("NMR", "野村控股", "日股ADR"),
    ("NTDOY", "任天堂ADR", "日股ADR"),
    ("SFTBY", "软银ADR", "日股ADR"),
    ("HTHIY", "日立ADR", "日股ADR"),
    ("CAJ", "佳能ADR", "日股ADR"),
    ("TOELY", "东京电子ADR", "日股ADR"),
    ("FUJHY", "斯巴鲁ADR", "日股ADR"),
    ("MZDAY", "马自达ADR", "日股ADR"),
    ("NSANY", "日产汽车ADR", "日股ADR"),
    ("BRDCY", "普利司通ADR", "日股ADR"),
    ("KMTUY", "小松制作所ADR", "日股ADR"),
    ("FANUY", "发那科ADR", "日股ADR"),
    ("SVNDY", "Seven&iADR", "日股ADR"),
    ("FRCOY", "迅销优衣库ADR", "日股ADR"),
    ("TAK", "武田制药ADR", "日股ADR"),
    ("ESALY", "卫材ADR", "日股ADR"),
    ("ALPMY", "安斯泰来ADR", "日股ADR"),
    ("DSNKY", "第一三共ADR", "日股ADR"),
    ("MSBHF", "三菱商事ADR", "日股ADR"),
    ("MITSY", "三井物产ADR", "日股ADR"),
    ("ITOCY", "伊藤忠商事ADR", "日股ADR"),
    ("NJDCY", "日本电产ADR", "日股ADR"),
    ("KYCCF", "基恩士ADR", "日股ADR"),
    ("SSDOY", "资生堂ADR", "日股ADR"),
    ("PCRHY", "松下ADR", "日股ADR"),
    ("SKM", "SK电信ADR", "日股ADR"),
    # --- 欧洲 ADR (16) ---
    ("NVO", "诺和诺德ADR", "欧股ADR"),
    ("AZN", "阿斯利康ADR", "欧股ADR"),
    ("GSK", "葛兰素史克ADR", "欧股ADR"),
    ("SHEL", "壳牌ADR", "欧股ADR"),
    ("BP", "英国石油ADR", "欧股ADR"),
    ("TTE", "道达尔ADR", "欧股ADR"),
    ("E", "埃尼石油ADR", "欧股ADR"),
    ("SAP", "SAP ADR", "欧股ADR"),
    ("HSBC", "汇丰ADR", "欧股ADR"),
    ("BCS", "巴克莱ADR", "欧股ADR"),
    ("UBS", "瑞银ADR", "欧股ADR"),
    ("DB", "德意志银行ADR", "欧股ADR"),
    ("ING", "荷兰国际ADR", "欧股ADR"),
    ("SAN", "桑坦德ADR", "欧股ADR"),
    ("BBVA", "毕尔巴鄂ADR", "欧股ADR"),
    ("NVS", "诺华ADR", "欧股ADR"),
    # --- 其他新兴/亚洲 ADR + 韩国 (12, 已剔除与上文重复的 TSM/VALE/INFY/WIT) ---
    ("UMC", "联电ADR", "新兴ADR"),
    ("ASX", "日月光ADR", "新兴ADR"),
    ("PBR", "巴西石油ADR", "新兴ADR"),
    ("ITUB", "Itau银行ADR", "新兴ADR"),
    ("BBD", "布拉德斯科ADR", "新兴ADR"),
    ("ABEV", "百威英博ADR", "新兴ADR"),
    ("IBN", "ICICI银行ADR", "新兴ADR"),
    ("HDB", "HDFC银行ADR", "新兴ADR"),
    ("WB", "微博ADR", "新兴ADR"),
    ("EWY", "韩国MSCI ETF", "新兴ADR"),
    ("EWT", "台湾MSCI ETF", "新兴ADR"),
    ("EWW", "墨西哥ETF", "新兴ADR"),
    # ============ 加密概念股 / 挖矿 / 持币公司 / 稳定币 (36) ============
    # 用户 2026-09-09 追加要求: "美股那几个加密相关的公司也都抓一下"
    ("BITF", "Bitfarms挖矿", "加密股"),
    ("HIVE", "HIVE Digital", "加密股"),
    ("HUT", "Hut 8挖矿", "加密股"),
    ("CIFR", "Cipher Mining", "加密股"),
    ("BTDR", "Bitdeer比特小鹿", "加密股"),
    ("CAN", "嘉楠科技", "加密股"),
    ("BTBT", "Bit Digital", "加密股"),
    ("ARBK", "Argo Blockchain", "加密股"),
    ("GREE", "Greenidge挖矿", "加密股"),
    ("SDIG", "Stronghold挖矿", "加密股"),
    ("BKKT", "Bakkt", "加密股"),
    ("BTM", "Bitcoin Depot", "加密股"),
    ("BTCM", "BIT Mining", "加密股"),
    ("BTCS", "BTCS Inc", "加密股"),
    ("LMFA", "LM Funding", "加密股"),
    ("MTPLF", "Metaplanet日本", "加密股"),
    ("CRCL", "Circle稳定币USDC", "加密股"),
    ("BLSH", "Bullish交易所", "加密股"),
    ("GEMI", "Gemini交易所", "加密股"),
    ("SBET", "SharpLink ETH金库", "加密股"),
    ("BMNR", "BitMine ETH金库", "加密股"),
    ("DFDV", "DeFi Development", "加密股"),
    ("UPXI", "Upexi SOL金库", "加密股"),
    ("SMLR", "Semler BTC金库", "加密股"),
    ("KULR", "KULR BTC金库", "加密股"),
    ("ASST", "Strive资产", "加密股"),
    ("EMPD", "Empery Digital", "加密股"),
    ("MFH", "Mercurity Fintech", "加密股"),
    ("STKE", "SOL Strategies", "加密股"),
    ("NAKA", "Nakamoto", "加密股"),
    ("CEPO", "Cantor Equity", "加密股"),
    ("FWDI", "Forward Industries", "加密股"),
    ("XXI", "Twenty One Capital", "加密股"),
    ("BITO", "比特币期货ETF", "加密股"),
    ("BITX", "比特币2倍ETF", "加密股"),
    ("BITW", "Bitwise十大加密", "加密股"),
    ("GDLC", "Grayscale大盘", "加密股"),
]


def fetch(symbol, interval="1week", outputsize=5000, retry=3):
    params = {"symbol": symbol, "interval": interval, "outputsize": outputsize,
              "apikey": KEY, "order": "ASC"}
    url = "https://api.twelvedata.com/time_series?" + urllib.parse.urlencode(params)
    for attempt in range(retry):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                d = json.load(r)
            if "values" not in d:
                raise RuntimeError(str(d)[:120])
            return d
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:120]
            if e.code == 429 and attempt < retry - 1:
                time.sleep(30)
                continue
            raise RuntimeError(f"HTTP {e.code} {body}")
    raise RuntimeError("retry exhausted")


def load_panel():
    """加载已存在的面板(增量合并), 没有则从 legacy 复制"""
    if os.path.exists(PANEL):
        return pd.read_csv(PANEL, index_col=0, parse_dates=True)
    if os.path.exists(LEGACY):
        return pd.read_csv(LEGACY, index_col=0, parse_dates=True)
    return pd.DataFrame()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=len(TARGETS))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--sleep", type=float, default=SLEEP)
    args = ap.parse_args()

    if args.list:
        for i, (s, n, c) in enumerate(TARGETS):
            print(f"{i:3d} {s:8s} {n:14s} {c}")
        print(f"\n总计 {len(TARGETS)} 个标的")
        return

    panel = load_panel()
    have = set(panel.columns)

    if args.status:
        todo = [(s, n, c) for s, n, c in TARGETS if s not in have]
        print(f"面板: {panel.shape[0]} 行 x {panel.shape[1]} 列")
        print(f"清单 {len(TARGETS)} 个, 已抓 {len(TARGETS) - len(todo)}, 待抓 {len(todo)}")
        print("待抓:", ", ".join(s for s, _, _ in todo[:40]))
        return

    batch = [(s, n, c) for s, n, c in TARGETS[args.start:args.end] if s not in have]
    if not batch:
        print(f"[{args.start}:{args.end}] 全部已抓取, 跳过")
        return

    print(f"本批 {len(batch)} 个 (清单 {args.start}~{args.end}, 已跳过已抓的)")
    ok, fail = {}, []
    t0 = time.time()
    for i, (sym, name, cat) in enumerate(batch, 1):
        try:
            d = fetch(sym)
            df = pd.DataFrame(d["values"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            s = pd.Series(df["close"].values,
                          index=pd.to_datetime(df["datetime"]), name=sym)
            s = s[~s.index.duplicated(keep="last")].sort_index()
            ok[sym] = s
            s.to_csv(os.path.join(RAW_DIR, f"{sym}.csv"), header=["close"])
            print(f"{i:3d}/{len(batch)} {sym:8s} {name:12s} {len(s):5d}周 "
                  f"{s.index[0].date()}~{s.index[-1].date()} ({cat})", flush=True)
        except Exception as e:
            print(f"{i:3d}/{len(batch)} {sym:8s} {name:12s} ERR {str(e)[:70]}", flush=True)
            fail.append((sym, str(e)[:40]))

        # 每 20 个增量落盘一次 —— 长批次被中断也不丢已抓数据
        if i % 20 == 0 and ok:
            tmp = pd.concat([panel, pd.DataFrame(ok).sort_index()], axis=1, sort=True)
            tmp = tmp[~tmp.index.duplicated(keep="last")].sort_index()
            tmp.to_csv(PANEL)
            print(f"    [增量保存] {tmp.shape[0]} 行 x {tmp.shape[1]} 列", flush=True)

        time.sleep(args.sleep)

    if ok:
        new = pd.DataFrame(ok).sort_index()
        panel = pd.concat([panel, new], axis=1, sort=True)
        panel = panel[~panel.index.duplicated(keep="last")].sort_index()
        panel.to_csv(PANEL)
        print(f"\n合并后面板: {panel.shape[0]} 行 x {panel.shape[1]} 列 -> {PANEL}")

    print(f"成功 {len(ok)} / 失败 {len(fail)}  耗时 {(time.time() - t0) / 60:.1f} 分钟")
    if fail:
        print("失败:", ", ".join(f"{t}" for t, _ in fail))


if __name__ == "__main__":
    main()
