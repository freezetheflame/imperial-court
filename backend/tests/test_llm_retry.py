"""LLM retry/backoff + scheduler degradation when retries are exhausted."""
from __future__ import annotations

import pytest

from imperial.agent.llm_client import LLMClient, LLMError, LLMResponse
from imperial.agent.loop import AgentLoop
from imperial.agent.scheduler import AgentScheduler
from imperial.agent.tools import build_tools
from imperial.agent.tracker import TaskTracker
from imperial.bus import Bus
from imperial.court.appointments import AppointmentService
from imperial.court.memorials import MemorialService
from imperial.rule_engine import RuleEngine


# ── client-side retry ──────────────────────────────────────
def _client(monkeypatch, max_retries=2):
    monkeypatch.setattr("imperial.agent.llm_client.time.sleep", lambda *_: None)
    return LLMClient(
        api_key="test-key", max_retries=max_retries, base_delay=0, max_delay=0,
    )


def test_transient_error_retried_until_success(monkeypatch):
    client = _client(monkeypatch)
    calls = {"n": 0}

    def flaky(messages, tools, model):
        calls["n"] += 1
        if calls["n"] < 3:
            raise LLMError("429 rate limited", retryable=True)
        return LLMResponse(content="好了", model="fake")

    monkeypatch.setattr(client, "_complete_chat", flaky)
    resp = client.complete([{"role": "user", "content": "hi"}])
    assert resp.content == "好了"
    assert calls["n"] == 3  # 2 retries + 1 success


def test_permanent_error_raises_immediately(monkeypatch):
    client = _client(monkeypatch)
    calls = {"n": 0}

    def dead(messages, tools, model):
        calls["n"] += 1
        raise LLMError("401 unauthorized", retryable=False)

    monkeypatch.setattr(client, "_complete_chat", dead)
    with pytest.raises(LLMError):
        client.complete([{"role": "user", "content": "hi"}])
    assert calls["n"] == 1  # no wasted retries on auth errors


def test_retryable_error_gives_up_after_max_retries(monkeypatch):
    client = _client(monkeypatch, max_retries=2)
    calls = {"n": 0}

    def always_down(messages, tools, model):
        calls["n"] += 1
        raise LLMError("503 provider overloaded", retryable=True)

    monkeypatch.setattr(client, "_complete_chat", always_down)
    with pytest.raises(LLMError):
        client.complete([{"role": "user", "content": "hi"}])
    assert calls["n"] == 3  # initial + 2 retries


# ── scheduler-side degradation ─────────────────────────────
class DeadLLM:
    """Provider permanently down — every call raises."""

    def complete(self, messages, tools=None, *, model=None):
        raise LLMError("provider down", retryable=False)


@pytest.fixture
def world(institution, storage):
    engine = RuleEngine(institution)
    bus = Bus(institution, storage, engine)
    appointments = AppointmentService(storage)
    memorials = MemorialService(storage, bus, institution, engine)
    tracker = TaskTracker()
    tools = build_tools(
        bus=bus, storage=storage, memorials=memorials, appointments=appointments,
        tracker=tracker,
    )

    def loop_factory(post_id: str) -> AgentLoop:
        return AgentLoop(
            institution=institution, tools=tools, llm=DeadLLM(),  # type: ignore[arg-type]
            engine=engine, max_turns=4,
        )

    scheduler = AgentScheduler(
        institution=institution, bus=bus, memorials=memorials, loop_factory=loop_factory,
        tracker=tracker,
    )
    return {"bus": bus, "scheduler": scheduler, "storage": storage}


async def test_llm_failure_audited_and_no_bogus_memorial(world):
    """LLM down → run fails → audited as llm_failure, no routing side-effects
    (a failure string must never become a memorial)."""
    bus, scheduler, storage = world["bus"], world["scheduler"], world["storage"]
    await scheduler.start()

    await bus.post_message("emperor", "chancery", "edict", payload={"edict_id": "e1"})
    await scheduler.pump_once()
    await scheduler.pump_once()

    failures = storage.get_events(kind="llm_failure", post_id="chancery")
    assert len(failures) == 1
    assert "provider down" in failures[0]["detail"]["error"]
    # no memorial submitted by the crashed run
    assert storage.query("SELECT * FROM memorials") == []
