"""Tool registry — tool definitions + whitelist-gated execution.

Tools are plain callables. The registry knows two things:

1. the OpenAI tool schema for each registered tool (so the LLM can call it),
2. how to execute a tool call for a given post, adjudicating the call
   against the institution's tool whitelist before running it.

Adjudication happens in AgentLoop (via RuleEngine); the registry is just
the name → callable map. Keeping them separate means the registry stays
dumb and testable.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

ToolFn = Callable[..., Any]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: ToolFn
    async_fn: bool = False

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry of available tools, keyed by name."""

    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
    ) -> Callable[[ToolFn], ToolFn]:
        """Decorator: register a tool function."""

        def decorator(fn: ToolFn) -> ToolFn:
            if name in self._tools:
                raise ValueError(f"tool already registered: {name}")
            self._tools[name] = ToolSpec(
                name=name,
                description=description,
                parameters=parameters,
                fn=fn,
                async_fn=inspect.iscoroutinefunction(fn),
            )
            return fn

        return decorator

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self._tools.values()]

    async def execute(self, name: str, arguments: dict[str, Any], **injected: Any) -> Any:
        """Execute a tool. `injected` kwargs are only passed if the tool
        function declares them (e.g. _post_id from AgentLoop)."""
        spec = self._tools[name]
        kwargs = dict(arguments)
        for key, val in injected.items():
            if key in inspect.signature(spec.fn).parameters:
                kwargs[key] = val
        if spec.async_fn:
            return await spec.fn(**kwargs)
        return spec.fn(**kwargs)
