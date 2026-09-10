"""
回归测试: 依赖声明三处不得漂移。

背景
----
CI / publish 工作流用 ``pip install -r requirements.txt`` 装包, 而本地
``pip install -e .`` 读的是 ``pyproject.toml`` 的 ``[project].dependencies``。
两处一旦漂移, 表现是「本地能跑、CI 挂」或反之 —— 且失败点离根因很远, 难查。
可选依赖同理 (``requirements-live.txt`` vs ``[project.optional-dependencies].live``)。

本测试把两对齐为硬约束, 漂移即在 CI 上红灯。
"""
import os
import sys
import tomllib
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _parse_requirements(name):
    """解析 requirements 文件 -> {规范名: 版本约束} (跳过注释/空行)。"""
    path = os.path.join(ROOT, name)
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # 只拆第一个约束符, 形如 "pandas>=1.5"
            for sep in (">=", "<=", "==", "~=", ">", "<"):
                if sep in line:
                    pkg, _, spec = line.partition(sep)
                    out[pkg.strip().lower()] = sep + spec.strip()
                    break
            else:
                out[line.lower()] = ""
    return out


def _parse_pyproject(section):
    """读 pyproject 的 dependencies / optional-dependencies.live。"""
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
        data = tomllib.load(f)
    if section == "live":
        raw = data["project"]["optional-dependencies"]["live"]
    else:
        raw = data["project"]["dependencies"]
    out = {}
    for item in raw:
        for sep in (">=", "<=", "==", "~=", ">", "<"):
            if sep in item:
                pkg, _, spec = item.partition(sep)
                out[pkg.strip().lower()] = sep + spec.strip()
                break
        else:
            out[item.strip().lower()] = ""
    return out


class TestDependencyDecl(unittest.TestCase):
    def test_requirements_matches_pyproject(self):
        req = _parse_requirements("requirements.txt")
        proj = _parse_pyproject("main")
        self.assertEqual(
            req, proj,
            "requirements.txt 与 pyproject [project].dependencies 不一致: "
            f"仅 requirements 有 {sorted(set(req) - set(proj))}; "
            f"仅 pyproject 有 {sorted(set(proj) - set(req))}; "
            f"约束不同 {[k for k in set(req) & set(proj) if req[k] != proj[k]]}",
        )

    def test_live_requirements_matches_pyproject(self):
        req = _parse_requirements("requirements-live.txt")
        proj = _parse_pyproject("live")
        self.assertEqual(req, proj, "requirements-live.txt 与 pyproject optional live 不一致")

    def test_requirements_non_empty(self):
        # 防呆: 若解析逻辑某天失灵返回空 dict, 上面两条会「两个空集合相等」而误绿。
        self.assertGreaterEqual(len(_parse_requirements("requirements.txt")), 3)
        self.assertGreaterEqual(len(_parse_requirements("requirements-live.txt")), 2)


if __name__ == "__main__":
    unittest.main()
