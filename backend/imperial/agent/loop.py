"""Thin agent loop — the only thing every agent has in common.

Loop protocol per turn:
1. call LLM with (system prompt, conversation, tool schemas)
2. if the LLM returns tool calls:
   a. adjudicate each against the institution tool whitelist
   b. execute allowed calls; append results to the conversation
   c. for denied calls, append the denial reason so the LLM can course-correct
3. if the LLM returns text (no tool calls), the turn is done

The loop knows NOTHING about institutions, posts, or politics. All of that
lives in the system prompt and the RuleEngine adjudication. This is the
deep module: small interface (run), heavy behaviour (turn loop, adjudication,
error handling, budget caps) hidden inside.

Threading: one runtime per post (each agent is single-threaded by design —
they talk to each other through the bus, not through shared state).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from imperial.agent.llm_client import LLMClient, LLMResponse
from imperial.agent.tool_registry import ToolRegistry
from imperial.institution import Institution
from imperial.rule_engine import CallToolAction, RuleEngine


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    allowed: bool
    reason: str
    result: Any = None


@dataclass
class AgentRunResult:
    content: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    turns: int = 0

    @property
    def had_violations(self) -> bool:
        return any(not tc.allowed for tc in self.tool_calls)

    def as_dict(self) -> dict:
        return {
            "content": self.content,
            "turns": self.turns,
            "tool_calls": [
                {
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "allowed": tc.allowed,
                    "reason": tc.reason,
                    "result": tc.result,
                }
                for tc in self.tool_calls
            ],
            "had_violations": self.had_violations,
        }


class AgentLoop:
    def __init__(
        self,
        *,
        institution: Institution,
        tools: ToolRegistry,
        llm: LLMClient,
        engine: RuleEngine | None = None,
        max_turns: int = 8,
    ):
        self.institution = institution
        self.tools = tools
        self.llm = llm
        self.engine = engine or RuleEngine(institution)
        self.max_turns = max_turns

    async def run(
        self,
        post_id: str,
        system_prompt: str,
        task: str,
        *,
        extra_messages: list[dict[str, Any]] | None = None,
    ) -> AgentRunResult:
        """Run the loop to completion (LLM stops calling tools)."""
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        if extra_messages:
            messages.extend(extra_messages)
        messages.append({"role": "user", "content": task})

        tool_calls: list[ToolCallRecord] = []
        post = self.institution.post(post_id)
        for _ in range(self.max_turns):
            resp: LLMResponse = self.llm.complete(messages, self.tools.schemas(), model=post.model)
            if not resp.tool_calls:
                return AgentRunResult(content=resp.content or "", tool_calls=tool_calls, turns=len(tool_calls) + 1)

            for tc in resp.tool_calls:
                if not self.tools.has(tc.name):
                    record = ToolCallRecord(tc.name, tc.arguments, False, f"unknown tool: {tc.name}")
                    tool_calls.append(record)
                    messages.append({"role": "assistant", "content": None, "tool_calls": [self._tc_msg(tc)]})
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"error: {record.reason}",
                        }
                    )
                    continue

                decision = self.engine.judge(CallToolAction(post_id, tc.name))
                if not decision.allowed:
                    record = ToolCallRecord(tc.name, tc.arguments, False, decision.reason)
                    tool_calls.append(record)
                    messages.append({"role": "assistant", "content": None, "tool_calls": [self._tc_msg(tc)]})
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"denied: {decision.reason}. You are not permitted to use this tool.",
                        }
                    )
                    continue

                try:
                    result = await self.tools.execute(tc.name, tc.arguments, _post_id=post_id)
                    record = ToolCallRecord(tc.name, tc.arguments, True, "allowed", result)
                except Exception as e:  # noqa: BLE001 — tool errors are data for the LLM
                    record = ToolCallRecord(tc.name, tc.arguments, True, "allowed", {"error": str(e)})
                tool_calls.append(record)
                messages.append({"role": "assistant", "content": None, "tool_calls": [self._tc_msg(tc)]})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(record.result),
                    }
                )

        # budget exhausted with the LLM still calling tools
        return AgentRunResult(
            content="[max_turns reached]",
            tool_calls=tool_calls,
            turns=self.max_turns,
        )

    def run_sync(
        self,
        post_id: str,
        system_prompt: str,
        task: str,
        *,
        extra_messages: list[dict[str, Any]] | None = None,
    ) -> AgentRunResult:
        """Synchronous convenience wrapper (tests, one-shot scripts)."""
        import asyncio

        return asyncio.run(
            self.run(post_id, system_prompt, task, extra_messages=extra_messages)
        )

    @staticmethod
    def _tc_msg(tc: Any) -> dict:
        import json

        return {
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.name,
                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
            },
        }
