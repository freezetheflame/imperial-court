"""FakeLLM — scripted fake for protocol tests. Never touches the network.

A FakeLLM plays back a script of responses. Each script entry is either:

- {"tool_calls": [{"name": ..., "arguments": {...}}, ...]}: the LLM asks for tools
- {"content": "..."}: the LLM produces its final answer

It records every request so tests can assert what the loop actually sent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from imperial.agent.llm_client import LLMResponse, LLMToolCall


@dataclass
class FakeRequest:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None


@dataclass
class FakeLLM:
    script: list[dict[str, Any]]
    requests: list[FakeRequest] = field(default_factory=list)
    calls: int = 0

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        model: str | None = None,
    ) -> LLMResponse:
        self.requests.append(FakeRequest(messages=list(messages), tools=tools))
        entry = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if "content" in entry:
            return LLMResponse(content=entry["content"], finish_reason="stop", model="fake")
        tcs = [
            LLMToolCall(id=f"call_{i}", name=tc["name"], arguments=tc.get("arguments", {}))
            for i, tc in enumerate(entry.get("tool_calls", []))
        ]
        return LLMResponse(content=None, tool_calls=tcs, finish_reason="tool_calls", model="fake")
