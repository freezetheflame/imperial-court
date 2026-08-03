"""Agent layer protocol tests — no real API, no network."""
from unittest.mock import MagicMock

import pytest

from imperial.agent.llm_client import LLMClient, LLMResponse
from imperial.agent.loop import AgentLoop
from imperial.agent.tool_registry import ToolRegistry
from imperial.rule_engine import RuleEngine
from tests.fake_llm import FakeLLM


# ── ToolRegistry ───────────────────────────────────────────
def test_register_and_schema():
    reg = ToolRegistry()

    @reg.register("ping", "returns pong", {"type": "object", "properties": {}})
    def ping():
        return "pong"

    assert reg.has("ping")
    schema = reg.schemas()[0]
    assert schema["function"]["name"] == "ping"
    spec = reg.get("ping")
    assert spec is not None and spec.fn() == "pong"


def test_duplicate_register_raises():
    reg = ToolRegistry()

    @reg.register("dup", "a", {"type": "object", "properties": {}})
    def a():
        return 1

    with pytest.raises(ValueError, match="already registered"):
        @reg.register("dup", "b", {"type": "object", "properties": {}})
        def b():
            return 2


# ── LLMClient (chat style, mocked transport) ───────────────
def _mock_chat_client():
    llm = LLMClient(model="m", api_key="k", api_style="chat")
    # stub the inner OpenAI client
    llm._client = MagicMock()
    return llm


def test_chat_parses_tool_calls():
    llm = _mock_chat_client()
    fake_choice = MagicMock()
    tc = MagicMock()
    tc.id = "c1"
    tc.function.name = "run_task"
    tc.function.arguments = '{"target": "x"}'
    fake_choice.message.tool_calls = [tc]
    fake_choice.message.content = None
    fake_choice.finish_reason = "tool_calls"
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_resp.model = "deepseek-chat"
    llm._client.chat.completions.create.return_value = fake_resp

    resp = llm.complete([{"role": "user", "content": "hi"}], tools=[])
    assert resp.content is None
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "run_task"
    assert resp.tool_calls[0].arguments == {"target": "x"}


def test_chat_parses_plain_text():
    llm = _mock_chat_client()
    fake_choice = MagicMock()
    fake_choice.message.tool_calls = None
    fake_choice.message.content = "完成"
    fake_choice.finish_reason = "stop"
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_resp.model = "m"
    llm._client.chat.completions.create.return_value = fake_resp

    resp = llm.complete([{"role": "user", "content": "hi"}])
    assert resp.content == "完成"
    assert resp.tool_calls == []


def test_bad_json_arguments_are_survived():
    llm = _mock_chat_client()
    fake_choice = MagicMock()
    tc = MagicMock()
    tc.id = "c1"
    tc.function.name = "run_task"
    tc.function.arguments = "not json"
    fake_choice.message.tool_calls = [tc]
    fake_choice.message.content = None
    fake_choice.finish_reason = "tool_calls"
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_resp.model = "m"
    llm._client.chat.completions.create.return_value = fake_resp

    resp = llm.complete([{"role": "user", "content": "hi"}])
    assert resp.tool_calls[0].arguments == {"_raw": "not json"}


def test_llm_error_surfaces():
    llm = _mock_chat_client()
    llm._client.chat.completions.create.side_effect = RuntimeError("boom")
    with pytest.raises(Exception, match="LLM call failed"):
        llm.complete([{"role": "user", "content": "hi"}])


# ── AgentLoop ──────────────────────────────────────────────
def _make_loop(institution, fake: FakeLLM, registry: ToolRegistry | None = None):
    reg = registry or ToolRegistry()
    return AgentLoop(
        institution=institution,
        tools=reg,
        llm=fake,  # type: ignore[arg-type] — FakeLLM duck-types LLMClient
        engine=RuleEngine(institution),
        max_turns=5,
    )


def test_loop_runs_tool_then_finishes(institution):
    reg = ToolRegistry()

    @reg.register("run_task", "run it", {"type": "object", "properties": {}})
    def run_task():
        return "done"

    fake = FakeLLM(script=[
        {"tool_calls": [{"name": "run_task", "arguments": {}}]},
        {"content": "任务完成"},
    ])
    loop = _make_loop(institution, fake, reg)
    result = loop.run_sync("finance", "你是个执行者", "去干活")

    assert result.content == "任务完成"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].allowed is True
    assert result.tool_calls[0].result == "done"
    assert not result.had_violations


def test_loop_blocks_disallowed_tool(institution):
    # finance may NOT call dispatch_task (coordinator-only)
    reg = ToolRegistry()

    @reg.register("dispatch_task", "dispatch", {"type": "object", "properties": {}})
    def dispatch_task():
        return "should never run"

    fake = FakeLLM(script=[
        {"tool_calls": [{"name": "dispatch_task", "arguments": {}}]},
        {"content": "明白了"},
    ])
    loop = _make_loop(institution, fake, reg)
    result = loop.run_sync("finance", "你是个执行者", "去分派")

    assert result.had_violations
    record = result.tool_calls[0]
    assert record.allowed is False
    assert "allowance" in record.reason
    # the LLM saw the denial in the conversation
    denial_msg = fake.requests[-1].messages[-1]
    assert "denied" in denial_msg["content"]


def test_loop_unknown_tool_is_error(institution):
    # tool not registered at all → treated as error, not violation
    fake = FakeLLM(script=[
        {"tool_calls": [{"name": "ghost_tool", "arguments": {}}]},
        {"content": "重来"},
    ])
    loop = _make_loop(institution, fake)
    result = loop.run_sync("finance", "执行者", "试试")

    assert result.had_violations  # unknown tool is a non-allowed call
    assert "unknown tool" in result.tool_calls[0].reason


def test_loop_respects_max_turns(institution):
    reg = ToolRegistry()

    @reg.register("run_task", "run", {"type": "object", "properties": {}})
    def run_task():
        return "again"

    # LLM keeps calling tools forever → budget caps it
    fake = FakeLLM(script=[
        {"tool_calls": [{"name": "run_task", "arguments": {}}]},
    ])
    loop = _make_loop(institution, fake, reg)
    result = loop.run_sync("finance", "执行者", "循环")

    assert result.content == "[max_turns reached]"
    assert len(result.tool_calls) == 5


def test_loop_passes_tool_results_back(institution):
    reg = ToolRegistry()

    @reg.register("query_events", "query", {"type": "object", "properties": {}})
    def query_events():
        return {"count": 3}

    fake = FakeLLM(script=[
        {"tool_calls": [{"name": "query_events", "arguments": {}}]},
        {"content": "查到了 3 条"},
    ])
    loop = _make_loop(institution, fake, reg)
    result = loop.run_sync("censor", "监察官", "查记录")

    # the tool result was fed back into the conversation
    tool_msg = fake.requests[1].messages[-1]
    assert tool_msg["role"] == "tool"
    assert "3" in tool_msg["content"]


def test_loop_uses_post_model_override(institution):
    # chancery has model=pro in the institution YAML; loop must pass it through
    reg = ToolRegistry()

    @reg.register("summarize", "sum", {"type": "object", "properties": {}})
    def summarize():
        return "ok"

    fake = FakeLLM(script=[
        {"tool_calls": [{"name": "summarize", "arguments": {}}]},
        {"content": "汇总完毕"},
    ])
    loop = _make_loop(institution, fake, reg)
    loop.run_sync("chancery", "丞相", "汇总")

    # FakeLLM records calls; the 2nd call (after tool) carries model override
    assert fake.calls == 2
