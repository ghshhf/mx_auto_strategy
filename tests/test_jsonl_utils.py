"""
回归测试: jsonl_utils.py (M21)。

覆盖:
  - read_jsonl: 文件不存在返回 []; 跳过空行/坏行; 正常解析
  - append_jsonl: 自动建目录; 追加不覆盖; 序列化中文 ensure_ascii=False

全部为纯函数测试, 使用 tempfile 不污染项目目录。
"""
import os
import sys
import json
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import jsonl_utils  # noqa: E402


class TestReadJsonl(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(jsonl_utils.read_jsonl("/nonexistent/path/x.jsonl"), [])

    def test_empty_file_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as f:
            f.write("")
            path = f.name
        try:
            self.assertEqual(jsonl_utils.read_jsonl(path), [])
        finally:
            os.remove(path)

    def test_parses_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as f:
            f.write(json.dumps({"a": 1}) + "\n")
            f.write(json.dumps({"b": 2}) + "\n")
            path = f.name
        try:
            self.assertEqual(jsonl_utils.read_jsonl(path), [{"a": 1}, {"b": 2}])
        finally:
            os.remove(path)

    def test_skips_blank_and_bad_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as f:
            f.write(json.dumps({"ok": 1}) + "\n")
            f.write("\n")              # 空行
            f.write("   \n")           # 空白行
            f.write("not json\n")      # 坏行
            f.write(json.dumps({"ok": 2}) + "\n")
            path = f.name
        try:
            out = jsonl_utils.read_jsonl(path)
            self.assertEqual(out, [{"ok": 1}, {"ok": 2}])
        finally:
            os.remove(path)

    def test_preserves_chinese(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as f:
            f.write(json.dumps({"name": "贵州茅台"}, ensure_ascii=False) + "\n")
            path = f.name
        try:
            out = jsonl_utils.read_jsonl(path)
            self.assertEqual(out, [{"name": "贵州茅台"}])
        finally:
            os.remove(path)


class TestAppendJsonl(unittest.TestCase):
    def test_creates_nested_dirs(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "sub1", "sub2", "t.jsonl")
        try:
            jsonl_utils.append_jsonl(path, {"x": 1})
            self.assertTrue(os.path.exists(path))
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_append_does_not_overwrite(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as f:
            f.write(json.dumps({"first": 1}) + "\n")
            path = f.name
        try:
            jsonl_utils.append_jsonl(path, {"second": 2})
            out = jsonl_utils.read_jsonl(path)
            self.assertEqual(out, [{"first": 1}, {"second": 2}])
        finally:
            os.remove(path)

    def test_round_trip_chinese(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "t.jsonl")
        try:
            jsonl_utils.append_jsonl(path, {"name": "长江电力", "code": "600900"})
            out = jsonl_utils.read_jsonl(path)
            self.assertEqual(out, [{"name": "长江电力", "code": "600900"}])
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
