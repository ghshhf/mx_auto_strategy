"""
回归测试: report_html.py (共用报告模板)。

背景
----
6 个 ``blend_*.py`` 原先各自内联 HTML 模板, 且把 Python ``dict`` 的 ``repr``
直接插值进 ``<script>``。资产名一旦含引号就会生成非法 JS、整页白屏。
本测试钉死「模板单一来源 + 注入安全」这两条性质, 防止后续改回内联写法。
"""
import os
import sys
import json
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import report_html as rh  # noqa: E402


class TestJsData(unittest.TestCase):
    def test_output_is_valid_json(self):
        payload = {"BTC": [1.0, 2.5], "标普500": [1.0, 1.2]}
        self.assertEqual(json.loads(rh.jsdata(payload)), payload)

    def test_quote_in_key_does_not_break_js(self):
        # 旧写法 repr(dict) 产出 {'a"b': ...} —— 引号冲突, 非法 JS, 整页白屏。
        # json.dumps 会把内部双引号转义为 \", 因此字符串边界仍然唯一。
        out = rh.jsdata({'a"b': [1, 2]})
        self.assertIn(r'\"', out)          # 内部双引号已转义
        self.assertEqual(json.loads(out), {'a"b': [1, 2]})

    def test_single_quote_key_is_still_valid(self):
        # 单引号在双引号 JSON 字符串内无需转义, 同样安全。
        out = rh.jsdata({"a'b": [1, 2]})
        self.assertEqual(json.loads(out), {"a'b": [1, 2]})

    def test_nan_and_inf_become_null(self):
        # NaN/Infinity 不是合法 JSON/JS 字面量, 必须清洗。
        out = rh.jsdata({"x": [float("nan"), float("inf"), 1.0]})
        self.assertEqual(json.loads(out), {"x": [None, None, 1.0]})
        self.assertNotIn("NaN", out)
        self.assertNotIn("Infinity", out)

    def test_non_ascii_preserved(self):
        # ensure_ascii=False: 中文列名直接可读, 不被转成 \uXXXX 撑大文件。
        self.assertIn("加密", rh.jsdata({"加密": [1]}))


class TestEsc(unittest.TestCase):
    def test_escapes_html(self):
        self.assertEqual(rh.esc("<script>x</script>"), "&lt;script&gt;x&lt;/script&gt;")

    def test_escapes_quotes(self):
        self.assertIn("&quot;", rh.esc('a"b'))
        self.assertIn("&#x27;", rh.esc("a'b"))


class TestPage(unittest.TestCase):
    def _page(self, **kw):
        body = kw.pop("body", "<div class='card'>x</div>")
        return rh.page(title="T", h1="H", sub="S", body=body, **kw)

    def test_no_unescaped_brace_leftovers(self):
        # f-string 漏转义的典型症状: 页面里出现 {{ 或 }}
        html = self._page()
        self.assertNotIn("{{", html)
        self.assertNotIn("}}", html)

    def test_plotly_cdn_omitted_when_unused(self):
        self.assertNotIn("plot.ly", self._page(plotly=False))
        self.assertIn("plot.ly", self._page(plotly=True))

    def test_title_is_escaped(self):
        self.assertIn("&lt;b&gt;", rh.page(title="<b>", h1="h", sub="s", body=""))

    def test_nav_chart_layout_is_balanced(self):
        # Plotly layout 是 JS 对象字面量, 括号必须配平, 否则整页 JS 报错。
        out = rh.nav_chart("c1", rh.line_traces({"BTC": [1, 2]}))
        script = out.split("<script>")[1].split("</script>")[0]
        self.assertEqual(script.count("{"), script.count("}"))
        self.assertEqual(script.count("("), script.count(")"))


class TestLineTraces(unittest.TestCase):
    def test_escapes_series_names(self):
        out = rh.line_traces({"a'b": [1]})
        self.assertNotIn("name:'a'b'", out)  # 旧写法的破损形态
        self.assertIn("name:", out)

    def test_multiple_traces_comma_separated(self):
        out = rh.line_traces({"A": [1], "B": [2]})
        self.assertEqual(out.count("mode:'lines'"), 2)
        self.assertTrue(out.startswith("[") and out.endswith("]"))


if __name__ == "__main__":
    unittest.main()
