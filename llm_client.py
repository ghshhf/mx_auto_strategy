"""
llm_client.py - 统一 LLM 调用 (v6.14b, 参考 daily_stock_analysis 的 env 配置 + 优雅降级)

设计依据 (参考 ZhuLinsen/daily_stock_analysis):
  - LLM 配置优先读环境变量 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL / LLM_TIMEOUT_SEC / LLM_MAX_TOKENS / LLM_TEMPERATURE
  - strategy_config.json 的 ai_overlay.llm 作为兜底(适合不愿暴露 env 的场景)
  - 未配置时 call_llm 返回 (None, "LLM 未配置")，调用方据此退回纯规则
    —— 与参考项目 "No LLM configured -> AI analysis unavailable" 的降级语义一致
  - 仅依赖标准库 urllib, 无第三方依赖(不引入 litellm, 保持轻量)

解决的问题:
  原 ai_score.py / script_advisor.py 各自内联一份 _call_llm, 且只从 config.json 读密钥,
  用户每次换模型都要改 config.json。统一后只需 export LLM_BASE_URL/LLM_API_KEY/LLM_MODEL,
  即可接入 DeepSeek / Qwen / 任意 OpenAI 兼容网关, 无需改代码。

用法:
  from llm_client import call_llm, is_configured
  content, err = call_llm(cfg, system_prompt, user_prompt)
  if err:
      # 退回纯规则 / 生成 prompt 文件
"""
import os
import json
import urllib.request


def _resolve_llm_cfg(cfg):
    """合并 env 与 config.json, env 优先。返回扁平 dict。"""
    ai_cfg = (cfg or {}).get("ai_overlay", {}) or {}
    file_llm = ai_cfg.get("llm", {}) or {}

    base_url = os.getenv("LLM_BASE_URL") or file_llm.get("base_url", "")
    api_key = os.getenv("LLM_API_KEY") or file_llm.get("api_key", "")
    model = os.getenv("LLM_MODEL") or file_llm.get("model", "")

    def _to_float(env_name, default):
        v = os.getenv(env_name)
        if v:
            try:
                return float(v)
            except ValueError:
                pass
        return default

    timeout = _to_float("LLM_TIMEOUT_SEC", file_llm.get("timeout_sec", 30))
    max_tokens = int(_to_float("LLM_MAX_TOKENS", file_llm.get("max_tokens", 2000)))
    temperature = _to_float("LLM_TEMPERATURE", file_llm.get("temperature", 0.3))

    return {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "timeout_sec": timeout,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }


def is_configured(cfg=None):
    """LLM 是否已配置(三要素齐全)。"""
    llm = _resolve_llm_cfg(cfg or {})
    return bool(llm["base_url"] and llm["api_key"] and llm["model"])


def call_llm(cfg, system_prompt, user_prompt, *, max_tokens=None, temperature=None):
    """
    调用 OpenAI 兼容 API。返回 (content_str, error_str)。
    任何异常均返回 (None, error_str)，调用方据此安全降级。
    """
    llm = _resolve_llm_cfg(cfg or {})
    base_url = (llm["base_url"] or "").rstrip("/")
    api_key = llm["api_key"] or ""
    model = llm["model"] or ""
    timeout = llm["timeout_sec"]
    mt = max_tokens if max_tokens is not None else llm["max_tokens"]
    temp = temperature if temperature is not None else llm["temperature"]

    if not base_url or not api_key or not model:
        return None, "LLM 未配置 (LLM_BASE_URL/LLM_API_KEY/LLM_MODEL 环境变量 或 config.json ai_overlay.llm 为空)"

    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": mt,
        "temperature": temp,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        body = json.loads(resp.read().decode("utf-8"))
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        return content.strip(), None
    except Exception as e:
        return None, f"LLM API 调用失败: {e}"
