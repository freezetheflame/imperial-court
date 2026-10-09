"""动态权限（革职即职权中止）+ 调任/降职 + 并行 fanout / 消息重排。"""
from __future__ import annotations

import json
import time

import pytest

from imperial.agent.llm_client import LLMResponse
from imperial.agent.loop import AgentLoop
from imperial.agent.scheduler import AgentScheduler
from imperial.agent.tools import build_tools
from imperial.agent.tracker import TaskTracker
from imperial.bus import Bus
from imperial.court.appointments import AppointmentError, AppointmentService
from imperial.court.memorials import MemorialService
from imperial.rule_engine import CallToolAction, RuleEngine, SendMessageAction


# ── dynamic permission: vacant post loses all authority ────
def _status_fn(vacant: set[str]):
    return lambda pid: "vacant" if pid in vacant else "active"


def test_vacant_post_denied_tools_and_messages(institution):
    engine = RuleEngine(institution, post_status=_status_fn({"finance"}))
    # tool call denied
    d = engine.judge(CallToolAction("finance", "run_task"))
    assert d.allowed is False
    assert "空缺" in d.reason
    assert d.kind == "policy"
    # outbound message denied
    d = engine.judge(SendMessageAction("finance", "chancery", "result"))
    assert d.allowed is False
    # active colleagues unaffected
    assert engine.judge(CallToolAction("justice", "run_task")).allowed is True
    # emperor / system are exempt
    assert engine.judge(SendMessageAction("emperor", "chancery", "edict")).allowed is True
    assert engine.post_active("finance") is False
    assert engine.post_active("justice") is True


def test_no_status_callback_keeps_static_behavior(institution):
    engine = RuleEngine(institution)
    assert engine.judge(CallToolAction("finance", "run_task")).allowed is True
    assert engine.post_active("finance") is True


def test_unknown_post_treated_as_active(institution):
    """未入库（None）的岗位不误伤——动态权限只拒'确认非 active'的。"""
    engine = RuleEngine(institution, post_status=lambda pid: None)
    assert engine.judge(CallToolAction("finance", "run_task")).allowed is True


# ── scheduler skips vacant posts ───────────────────────────
class RecordingLLM:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools=None, *, model=None):
        self.calls += 1
        return LLMResponse(content="办了", model="fake")


@pytest.fixture
def gov_world(institution, storage):
    def post_status(pid: str):
        row = storage.query_one("SELECT status FROM posts WHERE id = ?", (pid,))
        return row["status"] if row else None

    engine = RuleEngine(institution, post_status=post_status)
    bus = Bus(institution, storage, engine)
    appointments = AppointmentService(storage)
    memorials = MemorialService(storage, bus, institution, engine)
    tracker = TaskTracker()
    tools = build_tools(
        bus=bus, storage=storage, memorials=memorials, appointments=appointments,
        tracker=tracker,
    )
    llm = RecordingLLM()

    def loop_factory(post_id: str) -> AgentLoop:
        return AgentLoop(
            institution=institution, tools=tools, llm=llm,  # type: ignore[arg-type]
            engine=engine, max_turns=4,
        )

    scheduler = AgentScheduler(
        institution=institution, bus=bus, memorials=memorials, loop_factory=loop_factory,
        tracker=tracker,
    )
    return {
        "bus": bus, "scheduler": scheduler, "storage": storage, "llm": llm,
        "appointments": appointments, "institution": institution,
    }


def _seed_post(storage, post_id, *, status="active", agent=None):
    storage.execute(
        """INSERT INTO posts (id, institution_id, title, role, reports_to, status, current_agent)
           VALUES (?, 'sanguan-jiuqing', ?, 'executor', 'chancery', ?, ?)""",
        (post_id, post_id, status, agent),
    )


async def test_vacant_post_agent_never_runs(gov_world):
    storage = gov_world["storage"]
    _seed_post(storage, "finance", status="vacant")
    _seed_post(storage, "justice")
    await gov_world["scheduler"].start()

    await gov_world["bus"].post_message(
        "chancery", "finance", "task_assignment", payload={"edict_id": "e1", "title": "t"},
    )
    await gov_world["bus"].post_message(
        "chancery", "justice", "task_assignment", payload={"edict_id": "e1", "title": "t"},
    )
    await gov_world["scheduler"].pump_once()

    # justice ran, finance did not
    assert gov_world["llm"].calls == 1
    skipped = storage.get_events(kind="agent_skipped", post_id="finance")
    assert len(skipped) == 1


# ── parallel fan-out + requeue ─────────────────────────────
class SlowLLM:
    """Sleeps inside the (threaded) LLM call; records peak concurrency."""

    def __init__(self, counter: dict, delay: float = 0.15):
        self.counter = counter
        self.delay = delay
        self.calls = 0

    def complete(self, messages, tools=None, *, model=None):
        self.calls += 1
        self.counter["cur"] += 1
        self.counter["max"] = max(self.counter["max"], self.counter["cur"])
        time.sleep(self.delay)
        self.counter["cur"] -= 1
        return LLMResponse(content="好了", model="fake")


async def test_executors_run_in_parallel(gov_world):
    _seed_post(gov_world["storage"], "finance")
    _seed_post(gov_world["storage"], "justice")
    counter = {"cur": 0, "max": 0}
    slow = SlowLLM(counter)
    gov_world["llm"] = slow
    # rebuild scheduler loops with the slow LLM
    scheduler = gov_world["scheduler"]
    scheduler.loop_factory = lambda post_id: AgentLoop(  # type: ignore[method-assign]
        institution=gov_world["institution"],
        tools=build_tools(
            bus=gov_world["bus"], storage=gov_world["storage"],
            memorials=gov_world["scheduler"].memorials,
            appointments=gov_world["appointments"],
        ),
        llm=slow,  # type: ignore[arg-type]
        engine=gov_world["bus"].engine,
        max_turns=2,
    )
    await scheduler.start()

    await gov_world["bus"].post_message(
        "chancery", "finance", "task_assignment", payload={"edict_id": "e1", "title": "t1"},
    )
    await gov_world["bus"].post_message(
        "chancery", "justice", "task_assignment", payload={"edict_id": "e1", "title": "t2"},
    )
    await scheduler.pump_once()

    assert slow.calls == 2
    assert counter["max"] == 2  # 两个执行岗真的在并行跑


async def test_busy_post_message_requeued_not_dropped(gov_world):
    _seed_post(gov_world["storage"], "finance")
    counter = {"cur": 0, "max": 0}
    slow = SlowLLM(counter, delay=0.05)
    scheduler = gov_world["scheduler"]
    scheduler.loop_factory = lambda post_id: AgentLoop(  # type: ignore[method-assign]
        institution=gov_world["institution"],
        tools=build_tools(
            bus=gov_world["bus"], storage=gov_world["storage"],
            memorials=gov_world["scheduler"].memorials,
            appointments=gov_world["appointments"],
        ),
        llm=slow,  # type: ignore[arg-type]
        engine=gov_world["bus"].engine,
        max_turns=2,
    )
    await scheduler.start()

    for i in range(2):
        await gov_world["bus"].post_message(
            "chancery", "finance", "task_assignment",
            payload={"edict_id": "e1", "title": f"t{i}"},
        )
    await scheduler.pump_once()  # 第一条开跑，第二条重排
    await scheduler.pump_once()  # 重排的消息被处理

    assert slow.calls == 2  # 一条都没丢


# ── transfer / demote ──────────────────────────────────────
def _seed_for_transfer(storage):
    _seed_post(storage, "chancery", agent="agent_甲")
    storage.execute(
        "UPDATE posts SET persona = ? WHERE id = 'chancery'",
        (json.dumps({"name": "房玄龄"}, ensure_ascii=False),),
    )
    _seed_post(storage, "internal", status="vacant")


def test_transfer_moves_agent_and_persona(storage):
    _seed_for_transfer(storage)
    svc = AppointmentService(storage)
    row = svc.transfer("chancery", "internal", reason="平调")
    assert row["status"] == "active"
    assert row["current_agent"] == "agent_甲"
    assert json.loads(row["persona"])["name"] == "房玄龄"
    src = svc.get_post("chancery")
    assert src["status"] == "vacant" and src["current_agent"] is None
    actions = [r["action"] for r in svc.list_appointments()]
    assert actions.count("transfer") == 2  # 源岗 + 目标岗各记一笔


def test_demote_records_demote_action(storage):
    _seed_for_transfer(storage)
    svc = AppointmentService(storage)
    svc.demote("chancery", "internal", reason="坐事左迁")
    actions = [r["action"] for r in svc.list_appointments()]
    assert "demote" in actions


def test_transfer_from_vacant_post_raises(storage):
    _seed_post(storage, "chancery", status="vacant")
    _seed_post(storage, "internal", status="vacant")
    svc = AppointmentService(storage)
    with pytest.raises(AppointmentError):
        svc.transfer("chancery", "internal", reason="无人可调")
