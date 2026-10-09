"""AgentScheduler tests — message-driven agent network with FakeLLM.

No real API. Verifies routing, single-flight, impeachment handling, and
the memorial side-effects of agent runs.
"""
import asyncio

import pytest

from imperial.agent.loop import AgentLoop
from imperial.agent.scheduler import AgentScheduler
from imperial.agent.tools import build_tools
from imperial.agent.tracker import TaskTracker
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
    tracker = TaskTracker()
    tools = build_tools(
        bus=bus, storage=storage, memorials=memorials, appointments=appointments,
        tracker=tracker,
    )

    fake_llms: dict[str, FakeLLM] = {}

    def loop_factory(post_id: str) -> AgentLoop:
        fake = fake_llms.setdefault(post_id, FakeLLM(script=[{"content": "已阅。"}]))
        return AgentLoop(
            institution=institution, tools=tools, llm=fake,  # type: ignore[arg-type]
            engine=engine, max_turns=4,
        )

    scheduler = AgentScheduler(
        institution=institution, bus=bus, memorials=memorials, loop_factory=loop_factory,
        tracker=tracker,
    )
    return {
        "bus": bus, "scheduler": scheduler, "memorials": memorials, "edicts": edicts,
        "impeachments": impeachments, "appointments": appointments,
        "fake_llms": fake_llms, "storage": storage, "institution": institution,
        "tracker": tracker,
    }


async def test_edict_flow_creates_memorial(world):
    """Emperor edict → chancery decomposes/dispatches → executor reports →
    all subtasks done → aggregate → ONE memorial."""
    await world["scheduler"].start()

    # chancery + executor scripts set BEFORE the pump: pump_once pumps until quiescent,
    # so the whole cascade (dispatch → execute → aggregate → memorial)
    # completes in one call. chancery runs TWICE: edict (decompose/dispatch)
    # then aggregate (summary) — the script covers both invocations.
    world["fake_llms"]["chancery"] = FakeLLM(script=[
        {"tool_calls": [
            {"name": "decompose_task", "arguments": {"edict_id": "e1", "subtasks": [
                {"title": "t1", "target": "finance"},
                {"title": "t2", "target": "justice"},
            ]}},
            {"name": "dispatch_task", "arguments": {"edict_id": "e1", "target": "finance", "title": "t1", "description": "d1"}},
            {"name": "dispatch_task", "arguments": {"edict_id": "e1", "target": "justice", "title": "t2", "description": "d2"}},
        ]},
        {"content": "已分派完毕。"},
        {"content": "两处回报已汇总，臣谨奏陛下。"},
    ])
    world["fake_llms"]["finance"] = FakeLLM(script=[
        {"tool_calls": [{"name": "run_task", "arguments": {"task": "汇总数据"}}]},
        {"tool_calls": [{"name": "report_result", "arguments": {"edict_id": "e1", "summary": "数据已汇总"}}]},
        {"content": "已完成。"},
    ])
    world["fake_llms"]["justice"] = FakeLLM(script=[
        {"tool_calls": [{"name": "run_task", "arguments": {"task": "质检"}}]},
        {"tool_calls": [{"name": "report_result", "arguments": {"edict_id": "e1", "summary": "质检通过"}}]},
        {"content": "已完成。"},
    ])

    await world["edicts"].issue(world_edict_form())
    await world["scheduler"].pump_once()

    # aggregate message fired → chancery summarized → exactly ONE memorial
    memorials = world["memorials"].list()
    assert len(memorials) == 1, f"expected 1 aggregate memorial, got {len(memorials)}"
    assert memorials[0]["from_post"] == "chancery"
    full = world["memorials"].get(memorials[0]["id"])
    assert full is not None and "谨奏" in full["content"]


def _seed_post(storage, post_id):
    storage.execute(
        """INSERT INTO posts (id, institution_id, title, role, reports_to, status)
           VALUES (?, 'sanguan-jiuqing', ?, 'executor', 'chancery', 'active')""",
        (post_id, post_id),
    )


async def test_violation_record_first_offence_warns_not_impeaches(world):
    """初犯轻案：决策模型未达革职阈值 → 降格警告，弹劾不上达天听。"""
    _seed_post(world["storage"], "finance")
    await world["scheduler"].start()

    world["fake_llms"]["censor"] = FakeLLM(script=[
        {"tool_calls": [
            {"name": "query_events", "arguments": {"post_id": "finance"}},
        ]},
        {"tool_calls": [
            {"name": "recommend_removal", "arguments": {"post_id": "finance", "reason": "一次越权"}},
        ]},
        {"content": "已查证。"},
    ])

    # finance tries to message emperor directly → blocked → violation → censor
    await world["bus"].post_message("finance", "emperor", "report", {"data": "x"})
    await world["scheduler"].pump_once()
    await world["scheduler"].pump_once()

    # 模型裁定降格：无弹劾奏折，finance 被记警告
    assert world["memorials"].list() == []
    warns = world["storage"].query(
        "SELECT * FROM appointments WHERE post_id = 'finance' AND action = 'warn'"
    )
    assert len(warns) == 1
    # 决策全程留痕（audit summary 可查）
    decisions = world["storage"].get_events(kind="censor_decision", post_id="finance")
    assert len(decisions) == 1
    assert decisions[0]["detail"]["recommendation"] == "warning"


async def test_violation_record_repeat_offender_impeached(world):
    """累犯重案：前科+警告把 P(革职) 推过阈值 → 弹劾奏折直奏皇帝。"""
    await world["scheduler"].start()

    # 给 finance 攒足前科：3 次违制 + 1 次警告（重犯加成）
    _seed_post(world["storage"], "finance")
    for _ in range(3):
        world["storage"].insert_event("message_blocked", "finance", {"tool": "report_result"})
    world["appointments"].warn("finance", reason="此前留任警告")

    world["fake_llms"]["censor"] = FakeLLM(script=[
        {"tool_calls": [
            {"name": "recommend_removal", "arguments": {"post_id": "finance", "reason": "屡犯不改", "confidence": 0.9}},
        ]},
        {"content": "证据确凿，建议革职。"},
    ])

    await world["bus"].post_message("finance", "emperor", "report", {"data": "x"})
    await world["scheduler"].pump_once()
    await world["scheduler"].pump_once()

    memorials = world["memorials"].list()
    assert len(memorials) == 1
    assert memorials[0]["from_post"] == "censor"
    decision = world["storage"].get_events(kind="censor_decision", post_id="finance")[0]["detail"]
    assert decision["recommendation"] == "removal"
    assert decision["probabilities"]["removal"] >= 0.62


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


async def test_busy_post_requeues_then_runs(world):
    """Single-flight: while a post's agent is running, extra messages are
    requeued (not dropped, not re-entered) and processed on a later pump."""
    await world["scheduler"].start()

    entered = asyncio.Event()
    release = asyncio.Event()

    # patch _run_agent to gate on an event so we can hold the first run open
    # (_running is now managed by _dispatch, before _run_agent starts)
    original = world["scheduler"]._run_agent  # noqa: SLF001
    calls = {"n": 0}

    async def gated_run(post_id, msg):
        calls["n"] += 1
        if calls["n"] == 1:
            entered.set()
            await release.wait()
        return await original(post_id, msg)

    world["scheduler"]._run_agent = gated_run  # type: ignore[method-assign]
    world["fake_llms"]["chancery"] = FakeLLM(script=[{"content": "处理中。"}])

    msg1 = Message(id="m1", frm="emperor", to="chancery", type="edict", payload={"edict_id": "a"})
    msg2 = Message(id="m2", frm="emperor", to="chancery", type="edict", payload={"edict_id": "b"})

    task = asyncio.create_task(world["scheduler"]._dispatch("chancery", msg1))  # noqa: SLF001
    await entered.wait()  # first run is now inside _run_agent
    # second message while busy: requeued into chancery's inbox, NOT run yet
    await world["scheduler"]._dispatch("chancery", msg2)  # noqa: SLF001
    release.set()
    await task
    assert calls["n"] == 1  # only the first run executed

    # the requeued message is not lost: a later pump picks it up
    await world["scheduler"].pump_once()
    assert calls["n"] == 2


def world_edict_form():
    from imperial.court.edicts import EdictForm

    return EdictForm(title="测试上谕", task_type="research", description="测试", target="finance")
