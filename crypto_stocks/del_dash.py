"""删除 DASH (Dash, 隐私赛道). 可重入: 已完成的编辑自动跳过.

隐私赛道保留 ZEC 一个代表 (用户"老牌赛道留一个押 beta"原则).

流程:
  1. 删 DASH: crypto_adoption_v2.py / data_sources.py / sync_crypto_panel.py
     / fetch_mcaps.py / README.md / held_weeks.json / mcap_snapshot.json
     / crypto_pool_cg_categories.json / 3 个 CSV 列.
  2. 重新 import 校验: DASH 不在 OFFENSE, OFFENSE n=38 (断言 >=38 踩线通过).
"""
import json
import pandas as pd

FILES = [
    "data/weekly_adjclose_crypto50.csv",
    "data/weekly_adjclose_crypto50_v3.csv",
    "data/weekly_adjclose_crypto50_10y.csv",
]


def _edit_file(path, repls):
    with open(path, "r", encoding="utf-8") as f:
        s = f.read()
    changed = False
    for old, new in repls:
        if old in s:
            s = s.replace(old, new, 1)
            changed = True
        else:
            print(f"    [skip] 已无匹配: {path} :: {old!r}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)
    print(f"[+] 编辑 {path}" + ("" if changed else " (无变更)"))


def main():
    # ---- 1. 源码/映射/文档 ----
    _edit_file("crypto_adoption_v2.py", [
        ("    \"隐私\":    ['ZEC', 'DASH'],",
         "    \"隐私\":    ['ZEC'],  # 2026-08-18 删DASH, 留ZEC押隐私beta"),
        ("    'DASH': {'name': 'Dash', 'role': 'offense', 'theme': '隐私', 'launch': 2014},\n",
         ""),
    ])
    _edit_file("data_sources.py", [
        ("    'DASH': 'dash', 'AR': 'arweave',",
         "    'AR': 'arweave',"),
        ("    'DASH': 131, 'DOT': 6636, 'DYDX': 28324,",
         "    'DOT': 6636, 'DYDX': 28324,"),
    ])
    _edit_file("sync_crypto_panel.py", [
        ("    'DASH': 131,     'DOT': 6636,",
         "    'DOT': 6636,"),
    ])
    _edit_file("fetch_mcaps.py", [
        ("    'DASH': 'dash', 'AR': 'arweave',",
         "    'AR': 'arweave',"),
    ])
    _edit_file("README.md", [
        ("| 隐私 | 3% | 早期 | 1.15x | ZEC, DASH |",
         "| 隐私 | 3% | 早期 | 1.15x | ZEC |"),
    ])

    # ---- 2. JSON: 删 DASH 条目 ----
    for jf in ["held_weeks.json", "mcap_snapshot.json"]:
        with open(jf, "r", encoding="utf-8") as f:
            data = json.load(f)
        n0 = len(data)
        data = [d for d in data if d.get("sym") != "DASH"]
        with open(jf, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[+] JSON {jf}: {n0} -> {len(data)} 条 (删DASH)")

    # cg 分类缓存 (fetch_cg_categories.py 的输出产物, 回测不读, 顺手清理)
    try:
        with open("crypto_pool_cg_categories.json", "r", encoding="utf-8") as f:
            cg = json.load(f)
        if "DASH" in cg:
            del cg["DASH"]
            with open("crypto_pool_cg_categories.json", "w", encoding="utf-8") as f:
                json.dump(cg, f, ensure_ascii=False, indent=2)
            print("[+] crypto_pool_cg_categories.json: 删 DASH")
    except Exception as e:
        print(f"    [skip] cg_categories: {e}")

    # ---- 3. CSV: 删 DASH 列 ----
    for f in FILES:
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        if "DASH" in df.columns:
            df = df.drop(columns=["DASH"])
        df.to_csv(f, index=True)
        print(f"[+] CSV {f}: 删 DASH 列, 剩 {df.shape[1]} 列")

    # ---- 4. 校验 ----
    import sys
    if "crypto_adoption_v2" in sys.modules:
        del sys.modules["crypto_adoption_v2"]
    import crypto_adoption_v2 as ca2
    assert "DASH" not in ca2.OFFENSE_COINS, "DASH 仍在 OFFENSE!"
    assert "DASH" not in ca2.COIN_META, "DASH 仍在 COIN_META!"
    assert len(ca2.OFFENSE_COINS) >= 38, f"断言失败: OFFENSE n={len(ca2.OFFENSE_COINS)}"
    print(f"\n[OK] DEFENSE={ca2.DEFENSE_COINS}  OFFENSE n={len(ca2.OFFENSE_COINS)}  "
          f"ALL={len(ca2.ALL_COINS)}  隐私={ca2.THEME_COINS.get('隐私')}")


if __name__ == "__main__":
    main()
