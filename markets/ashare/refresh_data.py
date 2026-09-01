# -*- coding: utf-8 -*-
"""
refresh_data.py
===============
把 A 股历史日线「重新拉取 -> 落本地 data/ashare -> 更新 manifest」。

用法:
  python3 markets/ashare/refresh_data.py            # 刷新 data/ashare/bars 下所有已缓存标的
  python3 markets/ashare/refresh_data.py --flow     # 额外刷新 ETF 资金流累积(需 AkShare 可用)
  python3 markets/ashare/refresh_data.py --push     # 刷新后顺便 git add + commit + push 到 GitHub

说明:
  - 实时源在沙箱常被封, 本脚本应在「能联网的机器」(如你本机) 运行,
    拉完直接 `git add markets/ashare/data/ashare && git commit && git push`,
    即可把数据上传到 GitHub 充当公共缓存(下游在沙箱里直接读, 不必重复拉取)。
  - 指数优先 AkShare 全量, 兜底腾讯分页; ETF 走腾讯后复权日K。
"""
import os
import sys
import json
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analog_core as ac
import data_store

BARS_DIR = data_store.BARS_DIR


def _is_index(code):
    return code.startswith(("sh", "sz")) or (len(code) == 6 and code[0] in "03")


def refresh_bars():
    codes = sorted(f[:-5] for f in os.listdir(BARS_DIR) if f.endswith(".json"))
    print(f"待刷新 {len(codes)} 个标的 ...", flush=True)
    ok = fail = 0
    for code in codes:
        try:
            if _is_index(code):
                bars = ac._pull_akshare_index(code)
                if len(bars) < 200:
                    bars = ac._pull_tencent(code, "1990-01-01")
            else:
                bars = ac._pull_tencent(code)
            if bars:
                data_store.save_bars(code, bars,
                                     "akshare" if _is_index(code) else "tencent")
                ok += 1
            else:
                print(f"  ! {code} 拉取为空(源站可能封了)", file=sys.stderr)
                fail += 1
        except Exception as e:
            print(f"  ! {code} 异常: {e}", file=sys.stderr)
            fail += 1
    print(f"刷新完成: 成功 {ok}, 失败 {fail}")
    return fail == 0


def refresh_flow():
    try:
        import etf_fund_flow as ef
        ef.compute_flow()   # 内部会 save_accum -> data/ashare/flow
        print("资金流累积已刷新")
        return True
    except Exception as e:
        print(f"  ! 资金流刷新失败: {e}", file=sys.stderr)
        return False


def git_push(commit_msg):
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    subprocess.run(["git", "add", "markets/ashare/data/ashare"], cwd=root)
    r = subprocess.run(["git", "commit", "-m", commit_msg], cwd=root,
                       capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    r2 = subprocess.run(["git", "push", "origin", "main"], cwd=root,
                        capture_output=True, text=True)
    print(r2.stdout.strip() or r2.stderr.strip())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--flow", action="store_true", help="额外刷新 ETF 资金流累积")
    ap.add_argument("--push", action="store_true", help="刷新后 git add+commit+push")
    args = ap.parse_args()
    refresh_bars()
    if args.flow:
        refresh_flow()
    if args.push:
        stamp = datetime.date.today().strftime("%Y-%m-%d")
        git_push(f"data(ashare): 刷新日线缓存 {stamp}")
