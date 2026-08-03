"""LLM client — thin OpenAI-compatible wrapper.

Deep module: callers pass plain messages/tools and get back a normalized
`LLMResponse`; they never touch the OpenAI SDK. Model, base_url, and
api style (chat vs responses) are configurable so the censor's pro model
can slot in later without touching agent code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal

from openai import OpenAI

ApiStyle = Literal["chat", "responses"]


@dataclass
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    model: str | None = None
    reasoning_content: str | None = None  # DeepSeek thinking-mode trace
    raw: dict[str, Any] = field(default_factory=dict)


class LLMError(RuntimeError):
    pass


class LLMClient:
    """Stateless wrapper over an OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        api_style: ApiStyle = "chat",
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ):
        self.model = model or os.environ.get("IMPERIAL_LLM_MODEL", "deepseek-chat")
        base = base_url or os.environ.get("IMPERIAL_LLM_BASE_URL") or "https://api.deepseek.com"
        key = api_key or os.environ.get("IMPERIAL_LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise LLMError("no API key: set IMPERIAL_LLM_API_KEY or DEEPSEEK_API_KEY")
        self.api_style = api_style
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = OpenAI(base_url=base, api_key=key)

    # ── public interface ───────────────────────────────────
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        model: str | None = None,
    ) -> LLMResponse:
        """Run one LLM turn. Returns normalized response with tool calls."""
        use_model = model or self.model
        if self.api_style == "chat":
            return self._complete_chat(messages, tools, use_model)
        return self._complete_responses(messages, tools, use_model)

    # ── chat completions (DeepSeek current) ────────────────
    def _complete_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = dict(
            model=model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001 — surface as domain error
            raise LLMError(f"LLM call failed: {e}") from e

        choice = resp.choices[0]
        msg = choice.message
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json_loads(tc.function.arguments or "{}")
                except ValueError:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(LLMToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            model=resp.model,
            reasoning_content=getattr(msg, "reasoning_content", None),
            raw=resp.model_dump(),
        )

    # ── responses API (future pro model) ───────────────────
    def _complete_responses(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = dict(model=model, input=messages)
        if tools:
            kwargs["tools"] = tools
        try:
            resp = self._client.responses.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"LLM call failed: {e}") from e

        tool_calls: list[LLMToolCall] = []
        text_parts: list[str] = []
        for item in resp.output:
            if item.type == "function_call":
                try:
                    args = json_loads(item.arguments or "{}")
                except ValueError:
                    args = {"_raw": item.arguments}
                tool_calls.append(LLMToolCall(id=item.call_id, name=item.name, arguments=args))
            elif item.type == "message":
                for c in item.content:
                    if c.type == "output_text":
                        text_parts.append(c.text)
        return LLMResponse(
            content="".join(text_parts) or None,
            tool_calls=tool_calls,
            finish_reason=resp.status,
            model=resp.model,
            raw=resp.model_dump(),
        )


def json_loads(s: str) -> Any:
    import json

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        raise ValueError(f"invalid JSON: {s!r}") from None
