"""Integration tests against the real DeepSeek API.

Skipped unless IMPERIAL_LLM_API_KEY / DEEPSEEK_API_KEY is set. These are
expensive and non-deterministic — never part of the default suite.
Run explicitly:  IMPERIAL_LLM_API_KEY=... pytest tests/test_llm_integration.py -v
"""
import os

import pytest

from imperial.agent.llm_client import LLMClient, LLMError

pytestmark = pytest.mark.skipif(
    not (os.environ.get("IMPERIAL_LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")),
    reason="no LLM API key configured",
)


def test_real_chat_completion():
    llm = LLMClient(max_tokens=16)
    resp = llm.complete([{"role": "user", "content": "只回复两个字：你好"}])
    assert resp.content is not None
    assert "你好" in resp.content


def test_real_tool_call():
    llm = LLMClient()
    tools = [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取城市天气",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }]
    resp = llm.complete(
        [{"role": "user", "content": "北京天气怎么样？用工具查一下"}],
        tools=tools,
    )
    assert resp.tool_calls, "LLM should have asked for the weather tool"
    assert resp.tool_calls[0].name == "get_weather"


def test_real_bad_key_raises_domain_error():
    llm = LLMClient(api_key="definitely-not-a-real-key")
    with pytest.raises(LLMError, match="LLM call failed"):
        llm.complete([{"role": "user", "content": "hi"}])
