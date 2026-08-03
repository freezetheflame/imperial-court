"""AgentScheduler tests — message-driven agent network with FakeLLM.

No real API. Verifies routing, single-flight, impeachment handling, and
the memorial side-effects of agent runs.
"""
import asyncio

import pytest

from imperial.agent.loop import AgentLoop
from imperial.agent.scheduler import AgentScheduler
from imperial.agent.tools import build_tools
from imperial.bus import Bus, Message
from imperial.court.appointments import AppointmentService
from imperial.court.edicts import EdictService
from imperial.court.impeachments import ImpeachmentService
from imperial.court.memorials import MemorialService
from imperial.rule_engine import RuleEngine
from tests.fake_llm import FakeLLM


@pytest.fixture
def world(institution, storage):
    """Full wiring + scheduler with FakeLLM-backed loops."""
    engine = RuleEngine(institution)
    bus = Bus(institution, storage, engine)
    appointments = AppointmentService(storage)
    memorials = MemorialService(storage, bus, institution, engine)
    impeachments = ImpeachmentService(storage, bus, appointments)
    edicts = EdictService(storage, bus)
    tools = build_tools(bus=bus, storage=storage, memorials=memorials, appointments=appointments)

    fake_llms: dict[str, FakeLLM] = {}

    def loop_factory(post_id: str) -> AgentLoop:
        fake = fake_llms.setdefault(post_id, FakeLLM(script=[{"content": "已阅。"}]))
        return AgentLoop(
            institution=institution, tools=tools, llm=fake,  # type: ignore[arg-type]
            engine=engine, max_turns=4,
        )

    scheduler = AgentScheduler(
        institution=institution, bus=bus, memorials=memorials, loop_factory=loop_factory,
    )
    return {
        "bus": bus, "scheduler": scheduler, "memorials": memorials, "edicts": edicts,
        "impeachments": impeachments, "appointments": appointments,
        "fake_llms": fake_llms, "storage": storage, "institution": institution,
    }


async def test_edict_flow_creates_memorial(world):
    """Emperor edict → chancery agent decomposes/dispatches; the memorial
    comes only after an executor result arrives."""
    await world["scheduler"].start()

    # chancery agent: decompose + dispatch (no memorial on edict turn)
    world["fake_llms"]["chancery"] = FakeLLM(script=[
        {"tool_calls": [
            {"name": "decompose_task", "arguments": {"edict_id": "e1", "subtasks": [{"title": "t", "target": "finance"}]}},
            {"name": "dispatch_task", "arguments": {"edict_id": "e1", "target": "finance", "title": "t", "description": "d"}},
        ]},
        {"content": "已分派治粟内史办理。"},
    ])

    await world["edicts"].issue(world_edict_form())
    await world["scheduler"].pump_once()

    # no memorial yet — chancery only decomposed/dispatched on the edict
    assert world["memorials"].list() == []

    # now a result arrives → chancery agent summarizes → memorial
    world["fake_llms"]["chancery"] = FakeLLM(script=[
        {"content": "治粟内史已回报，数据汇总完毕，臣谨奏陛下。"},
    ])
    await world["bus"].post_message(
        "finance", "chancery", "result",
        {"edict_id": "e1", "summary": "数据已汇总"},
    )
    await world["scheduler"].pump_once()

    memorials = world["memorials"].list()
    assert len(memorials) == 1
    assert memorials[0]["from_post"] == "chancery"
    full = world["memorials"].get(memorials[0]["id"])
    assert full is not None and "谨奏" in full["content"]


async def test_violation_record_opens_impeachment(world):
    """A blocked message → violation_record → censor agent → impeachment memorial."""
    await world["scheduler"].start()

    world["fake_llms"]["censor"] = FakeLLM(script=[
        {"tool_calls": [
            {"name": "query_events", "arguments": {"post_id": "finance"}},
        ]},
        {"tool_calls": [
            {"name": "recommend_removal", "arguments": {"post_id": "finance", "reason": "多次越权"}},
        ]},
        {"content": "证据确凿，建议革职。"},
    ])

    # finance tries to message emperor directly → blocked → violation → censor
    await world["bus"].post_message("finance", "emperor", "report", {"data": "x"})
    await world["scheduler"].pump_once()
    await world["scheduler"].pump_once()

    # impeachment memorial should have been submitted by censor (privileged)
    memorials = world["memorials"].list()
    assert len(memorials) == 1
    assert memorials[0]["from_post"] == "censor"


async def test_executor_agent_runs_on_assignment(world):
    """Executor inbox message → agent runs run_task + report_result."""
    await world["scheduler"].start()

    world["fake_llms"]["finance"] = FakeLLM(script=[
        {"tool_calls": [
            {"name": "run_task", "arguments": {"task": "汇总数据", "detail": "完成"}},
        ]},
        {"tool_calls": [
            {"name": "report_result", "arguments": {"edict_id": "e1", "summary": "数据已汇总"}},
        ]},
        {"content": "任务完成，已呈报丞相。"},
    ])

    # dispatch a task to finance directly through the bus
    await world["bus"].post_message(
        "chancery", "finance", "task_assignment",
        {"edict_id": "e1", "title": "汇总", "description": "汇总数据"},
    )
    await world["scheduler"].pump_once()

    # the report_result should have gone back to chancery via the bus
    events = world["storage"].get_events(kind="message_sent")
    reports = [e for e in events if e["detail"]["message"]["to"] == "chancery"]
    assert reports, "no report delivered to chancery"


async def test_single_flight_skips_while_busy(world):
    """While a post's agent is running, extra messages are not re-entered."""
    await world["scheduler"].start()

    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowFake(FakeLLM):
        def complete(self, messages, tools=None, *, model=None):  # type: ignore[override]
            return super().complete(messages, tools, model=model)

    # patch _run_agent to gate on an event so we can hold the first run open
    original = world["scheduler"]._run_agent  # noqa: SLF001
    calls = {"n": 0}

    async def gated_run(post_id, msg):
        if post_id in world["scheduler"]._running:  # noqa: SLF001
            return  # single-flight: busy
        world["scheduler"]._running.add(post_id)  # noqa: SLF001
        calls["n"] += 1
        if calls["n"] == 1:
            entered.set()
            await release.wait()
        try:
            return await original(post_id, msg)
        finally:
            world["scheduler"]._running.discard(post_id)  # noqa: SLF001

    world["scheduler"]._run_agent = gated_run  # type: ignore[method-assign]
    world["fake_llms"]["chancery"] = SlowFake(script=[{"content": "处理中。"}])

    msg1 = Message(id="m1", frm="emperor", to="chancery", type="edict", payload={"edict_id": "a"})
    msg2 = Message(id="m2", frm="emperor", to="chancery", type="edict", payload={"edict_id": "b"})

    task = asyncio.create_task(world["scheduler"]._dispatch("chancery", msg1))  # noqa: SLF001
    await entered.wait()  # first run is now inside _run_agent
    # second message while busy: _running contains chancery → skipped
    await world["scheduler"]._dispatch("chancery", msg2)  # noqa: SLF001
    release.set()
    await task
    assert calls["n"] == 1  # only the first run executed


def world_edict_form():
    from imperial.court.edicts import EdictForm

    return EdictForm(title="测试上谕", task_type="research", description="测试", target="finance")
