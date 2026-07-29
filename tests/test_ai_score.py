"""回归测试: ai_score._parse_multipliers 的多格式解析与决策字段捕获。"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import ai_score  # noqa: E402


class TestParseMultipliers(unittest.TestCase):
    def test_plain_json_array(self):
        txt = '[{"code":"600036","multiplier":1.1,"reason":"低PE","risk":"息差","catalyst":"高股息"}]'
        m = ai_score._parse_multipliers(txt, [])
        self.assertEqual(m["600036"]["multiplier"], 1.1)
        self.assertEqual(m["600036"]["reason"], "低PE")
        self.assertEqual(m["600036"]["risk"], "息差")
        self.assertEqual(m["600036"]["catalyst"], "高股息")

    def test_markdown_codeblock(self):
        txt = '```json\n[{"code":"300750","multiplier":0.9,"reason":"估值高"}]\n```'
        m = ai_score._parse_multipliers(txt, [])
        self.assertEqual(m["300750"]["multiplier"], 0.9)
        self.assertEqual(m["300750"]["reason"], "估值高")

    def test_embedded_json(self):
        txt = '好的, 这是结果: [{"code":"000001","multiplier":1.0,"reason":""}] 完毕'
        m = ai_score._parse_multipliers(txt, [])
        self.assertEqual(m["000001"]["multiplier"], 1.0)

    def test_missing_fields_default_empty(self):
        txt = '[{"code":"600036","multiplier":1.2}]'
        m = ai_score._parse_multipliers(txt, [])
        self.assertEqual(m["600036"]["reason"], "")
        self.assertEqual(m["600036"]["risk"], "")
        self.assertEqual(m["600036"]["catalyst"], "")

    def test_invalid_returns_empty(self):
        self.assertEqual(ai_score._parse_multipliers("", []), {})
        self.assertEqual(ai_score._parse_multipliers("no json here", []), {})
        self.assertEqual(ai_score._parse_multipliers('{"not":"array"}', []), {})

    def test_bad_multiplier_skipped(self):
        txt = '[{"code":"600036","multiplier":"NaN"},{"code":"300750","multiplier":1.0}]'
        m = ai_score._parse_multipliers(txt, [])
        self.assertNotIn("600036", m)
        self.assertIn("300750", m)


if __name__ == "__main__":
    unittest.main()
