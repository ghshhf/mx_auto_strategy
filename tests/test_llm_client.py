"""回归测试: llm_client 的 env 配置解析与优雅降级。"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import llm_client  # noqa: E402


class TestLLMClient(unittest.TestCase):
    def setUp(self):
        # 隔离环境变量, 避免测试机上的真实配置干扰
        self._saved = {}
        for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_TIMEOUT_SEC", "LLM_MAX_TOKENS", "LLM_TEMPERATURE"):
            self._saved[k] = os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def test_not_configured_without_env(self):
        ok = llm_client.is_configured({})
        self.assertFalse(ok)
        content, err = llm_client.call_llm({}, "s", "u")
        self.assertIsNone(content)
        self.assertIn("未配置", err)

    def test_env_overrides_config(self):
        os.environ["LLM_BASE_URL"] = "https://api.example.com/v1"
        os.environ["LLM_API_KEY"] = "sk-test"
        os.environ["LLM_MODEL"] = "test-model"
        os.environ["LLM_TIMEOUT_SEC"] = "15"
        os.environ["LLM_MAX_TOKENS"] = "512"
        os.environ["LLM_TEMPERATURE"] = "0.5"
        cfg = {"ai_overlay": {"llm": {"base_url": "file-url", "api_key": "file-key",
                                      "model": "file-model", "timeout_sec": 30, "max_tokens": 2000}}}
        # 仍应判定为已配置 (env 优先)
        self.assertTrue(llm_client.is_configured(cfg))
        resolved = llm_client._resolve_llm_cfg(cfg)
        self.assertEqual(resolved["base_url"], "https://api.example.com/v1")
        self.assertEqual(resolved["api_key"], "sk-test")
        self.assertEqual(resolved["model"], "test-model")
        self.assertEqual(resolved["timeout_sec"], 15.0)
        self.assertEqual(resolved["max_tokens"], 512)
        self.assertEqual(resolved["temperature"], 0.5)

    def test_config_fallback_when_no_env(self):
        cfg = {"ai_overlay": {"llm": {"base_url": "file-url", "api_key": "file-key",
                                      "model": "file-model", "timeout_sec": 30, "max_tokens": 2000}}}
        self.assertTrue(llm_client.is_configured(cfg))
        resolved = llm_client._resolve_llm_cfg(cfg)
        self.assertEqual(resolved["base_url"], "file-url")


if __name__ == "__main__":
    unittest.main()
