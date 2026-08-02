# -*- coding: utf-8 -*-
"""
QA-02 单元测试: first_listed_index / 三道闸边界 / blend(max_lb=52) 覆盖
纯合成数据, 不依赖面板, 秒级完成。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import backtest_engine as E

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  <- {detail}" if detail and not cond else ""))


def sep(t):
    print("\n" + "-" * 88 + f"\n{t}\n" + "-" * 88)


# ============ 1. first_listed_index ============
sep("1. first_listed_index 语义与缓存")
E._FIRST_LISTED_CACHE.clear()

a = [None, None, 1.0, 2.0]
check("首个非None>0 的索引", E.first_listed_index(a) == 2, E.first_listed_index(a))

b = [None, 0.0, 0.0, 3.0]
check("0 视为无效, 跳到第一个 >0", E.first_listed_index(b) == 3, E.first_listed_index(b))

c = [None, None, None]
check("整列无效返回 None", E.first_listed_index(c) is None, E.first_listed_index(c))

d = [5.0, 6.0]
check("首元素即有效 -> 0", E.first_listed_index(d) == 0, E.first_listed_index(d))

check("空列表返回 None", E.first_listed_index([]) is None)

# 负价(脏数据)不应被当作上市点
e = [-1.0, -2.0, 4.0]
check("负价不算有效上市点", E.first_listed_index(e) == 2, E.first_listed_index(e))

# 缓存命中一致性
f = [None, 7.0, 8.0]
r1 = E.first_listed_index(f)
r2 = E.first_listed_index(f)
check("重复调用结果一致(缓存命中)", r1 == r2 == 1, (r1, r2))

# 缓存不串味: 不同列表即使 id 复用也要正确
before_n = len(E._FIRST_LISTED_CACHE)
g = [None, None, None, None, 9.0]
check("新列表不复用旧缓存值", E.first_listed_index(g) == 4, E.first_listed_index(g))
check("缓存条目递增", len(E._FIRST_LISTED_CACHE) > before_n)

# 缓存是"陈旧"的: 就地改列表不会刷新(设计如此, 面板加载后只读)
h = [None, 1.0]
E.first_listed_index(h)
h[0] = 5.0
check("就地修改后缓存仍返回旧值(已知设计约束, 面板只读故可接受)",
      E.first_listed_index(h) == 1, E.first_listed_index(h))


# ============ 2. 三道闸边界 ============
sep("2. momentum_select 三道闸边界 (合成序列)")
N = 200
DATES = [f"2020-{1 + (k // 4) % 12:02d}-{1 + (k % 4) * 7:02d}" for k in range(N)]
DATES = [f"20{16 + k // 52:02d}-01-{1 + (k % 28):02d}" for k in range(N)]  # 仅取年份用
META = {"AAA": {"industry": "unknown"}, "BBB": {"industry": "unknown"}}


def mk(first_idx, base=10.0, growth=1.01, n=N):
    """first_idx 之前为 None, 之后按 growth 复利上涨"""
    v = [None] * n
    p = base
    for k in range(first_idx, n):
        v[k] = p
        p *= growth
    return v


I = 150
LB = 26

# --- 闸2: 冷却期 ---
# 上市点恰好使 i - first = max_lb + 13 = 39 -> 应通过
ser = {"AAA": mk(I - (LB + E.IPO_SEASON_WEEKS)), "BBB": mk(0, growth=1.005)}
E._FIRST_LISTED_CACHE.clear()
top, full = E.momentum_select(DATES, ser, META, I, LB)
check("冷却期边界 i-first == max_lb+13 -> 放行", "AAA" in [c[0] for c in full],
      [c[0] for c in full])

# 差 1 周 -> 应拦截
ser = {"AAA": mk(I - (LB + E.IPO_SEASON_WEEKS) + 1), "BBB": mk(0, growth=1.005)}
E._FIRST_LISTED_CACHE.clear()
top, full = E.momentum_select(DATES, ser, META, I, LB)
check("冷却期边界 i-first == max_lb+12 -> 拦截", "AAA" not in [c[0] for c in full],
      [c[0] for c in full])

# --- 闸3: 单周跳变 ---
def with_jump(first_idx, jump_at, ratio):
    v = mk(first_idx)
    for k in range(jump_at, len(v)):
        v[k] *= ratio
    return v


# 跳变 +79% (< 80%) 在窗口内 -> 放行
ser = {"AAA": with_jump(0, I - 5, 1.79 / 1.01), "BBB": mk(0, growth=1.005)}
E._FIRST_LISTED_CACHE.clear()
_, full = E.momentum_select(DATES, ser, META, I, LB)
r = ser["AAA"][I - 5] / ser["AAA"][I - 6] - 1
check(f"窗口内单周 +{r:.1%} (<+80%) -> 放行", "AAA" in [c[0] for c in full],
      [c[0] for c in full])

# 跳变 +81% -> 拦截
ser = {"AAA": with_jump(0, I - 5, 1.81 / 1.01), "BBB": mk(0, growth=1.005)}
E._FIRST_LISTED_CACHE.clear()
_, full = E.momentum_select(DATES, ser, META, I, LB)
r = ser["AAA"][I - 5] / ser["AAA"][I - 6] - 1
check(f"窗口内单周 +{r:.1%} (>+80%) -> 拦截", "AAA" not in [c[0] for c in full],
      [c[0] for c in full])

# 跳变在窗口之外(i-max_lb 之前) -> 不应拦截
ser = {"AAA": with_jump(0, I - LB - 5, 2.5), "BBB": mk(0, growth=1.005)}
E._FIRST_LISTED_CACHE.clear()
_, full = E.momentum_select(DATES, ser, META, I, LB)
check("跳变在 26 周打分窗口之外 -> 不拦截", "AAA" in [c[0] for c in full],
      [c[0] for c in full])

# --- 闸1: 价格下限 ---
ser = {"AAA": mk(0), "BBB": mk(0, growth=1.005)}
ser["AAA"] = [(0.4 if v is not None else None) for v in ser["AAA"]]
ser["AAA"][I] = 0.49
E._FIRST_LISTED_CACHE.clear()
_, full = E.momentum_select(DATES, ser, META, I, LB)
check("当前价 0.49 < MIN_VALID_PRICE -> 拦截", "AAA" not in [c[0] for c in full])


# ============ 3. blend 模式 max_lb=52 覆盖 ============
sep("3. blend 模式 (lbs 含 52) 冷却期按 max_lb=52 生效")
# blend 下 max_lb=52, 冷却期门槛 = 52+13 = 65
ser = {"AAA": mk(I - 65), "BBB": mk(0, growth=1.005)}
E._FIRST_LISTED_CACHE.clear()
_, full = E.momentum_select(DATES, ser, META, I, LB, score_mode="blend")
check("blend: i-first == 52+13=65 -> 放行", "AAA" in [c[0] for c in full],
      [c[0] for c in full])

ser = {"AAA": mk(I - 64), "BBB": mk(0, growth=1.005)}
E._FIRST_LISTED_CACHE.clear()
_, full = E.momentum_select(DATES, ser, META, I, LB, score_mode="blend")
check("blend: i-first == 64 (<65) -> 拦截", "AAA" not in [c[0] for c in full],
      [c[0] for c in full])

# 关键回归: plain(lb=26) 门槛 39 < blend 门槛 65, 证明 max_lb 确实取的是 52 而非 lookback
ser = {"AAA": mk(I - 45), "BBB": mk(0, growth=1.005)}
E._FIRST_LISTED_CACHE.clear()
_, f_plain = E.momentum_select(DATES, ser, META, I, LB, score_mode="plain")
E._FIRST_LISTED_CACHE.clear()
_, f_blend = E.momentum_select(DATES, ser, META, I, LB, score_mode="blend")
check("i-first=45: plain 放行 而 blend 拦截 (max_lb 生效)",
      "AAA" in [c[0] for c in f_plain] and "AAA" not in [c[0] for c in f_blend],
      (f"plain={[c[0] for c in f_plain]}", f"blend={[c[0] for c in f_blend]}"))

# blend 下的跳变兜底也应按 52 周窗口
ser = {"AAA": with_jump(0, I - 40, 3.0), "BBB": mk(0, growth=1.005)}
E._FIRST_LISTED_CACHE.clear()
_, full = E.momentum_select(DATES, ser, META, I, LB, score_mode="blend")
check("blend: 40 周前的 +200% 跳变仍被 52 周窗口捕获 -> 拦截",
      "AAA" not in [c[0] for c in full], [c[0] for c in full])


# ============ 4. 不误伤: 长期上市的正常票 ============
sep("4. 回归: 长期上市正常票不受影响")
ser = {"AAA": mk(0, growth=1.02), "BBB": mk(0, growth=1.005)}
E._FIRST_LISTED_CACHE.clear()
top, full = E.momentum_select(DATES, ser, META, I, LB)
check("2 只老票均入选, 高动量者排第一", top == ["AAA", "BBB"], top)

# [QA 自查修正] risk_adj / sortino 要求 _realized_vol > 0, 而等比复利序列的
# 周收益率恒定 -> 标准差 = 0 -> 被 `vol <= 0: continue` 跳过。这是引擎既有行为
# (本次修复未触及), 不是 Bug。改用带确定性噪声的序列来覆盖这两种打分模式。
def mk_noisy(first_idx, base=10.0, growth=1.02, amp=0.03, n=N):
    v = [None] * n
    p = base
    for k in range(first_idx, n):
        wob = 1.0 + amp * (1 if k % 3 == 0 else (-1 if k % 3 == 1 else 0))
        v[k] = p * wob
        p *= growth
    return v


ser_n = {"AAA": mk_noisy(0, growth=1.02), "BBB": mk_noisy(0, growth=1.005, amp=0.02)}
for mode in ("plain", "blend", "risk_adj", "sortino"):
    E._FIRST_LISTED_CACHE.clear()
    t, _ = E.momentum_select(DATES, ser_n, META, I, LB, score_mode=mode)
    check(f"score_mode={mode} 正常返回 2 只", len(t) == 2, t)

# 波动为 0 时 risk_adj/sortino 跳过该票 —— 固化既有行为, 防未来回归
E._FIRST_LISTED_CACHE.clear()
t0, _ = E.momentum_select(DATES, ser, META, I, LB, score_mode="risk_adj")
check("零波动序列在 risk_adj 下被跳过(既有行为, 非本次修复引入)", t0 == [], t0)


# ============ 汇总 ============
print("\n" + "=" * 88)
print(f"QA-02 单元测试: {len(PASS)} PASS / {len(FAIL)} FAIL")
if FAIL:
    for n in FAIL:
        print("   FAILED:", n)
print("=" * 88)
sys.exit(1 if FAIL else 0)
