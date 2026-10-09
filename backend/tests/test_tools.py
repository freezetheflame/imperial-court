"""Tool-level tests — inquire_progress, allowance validation, identity guards."""
from types import SimpleNamespace

import pytest

from imperial.agent.tools import build_tools, validate_tool_allowances
from imperial.agent.tracker import TaskTracker
from imperial.bus import Bus
from imperial.court.appointments import AppointmentService
from imperial.court.memorials import MemorialService
from imperial.rule_engine import RuleEngine


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
    return {"bus": bus, "tools": tools, "tracker": tracker, "institution": institution}


# ── inquire_progress ───────────────────────────────────────
async def test_inquire_progress_urges_only_pending_posts(world):
    tools, tracker = world["tools"], world["tracker"]
    tracker.register_subtask("e1", "finance", "finance", "核算军费")
    tracker.register_subtask("e1", "justice", "justice", "复核律令")
    tracker.complete_subtask("e1", "justice", "已复核")

    result = await tools.execute("inquire_progress", {"edict_id": "e1"}, _post_id="chancery")

    assert result["found"] is True
    assert result["total"] == 2 and result["done"] == 1
    # only the pending post got the 催办 message
    assert len(result["urged"]) == 1
    assert result["urged"][0]["target"] == "finance"
    assert result["urged"][0]["sent"] is True  # chancery→finance inquiry 白名单放行


async def test_inquire_progress_unknown_edict(world):
    result = await world["tools"].execute(
        "inquire_progress", {"edict_id": "nope"}, _post_id="chancery",
    )
    assert result["found"] is False
    assert result["urged"] == []


# ── report_result identity guard ───────────────────────────
async def test_report_result_refuses_without_post_identity(world):
    result = await world["tools"].execute(
        "report_result", {"edict_id": "e1", "summary": "x"},
    )
    assert result["reported"] is False
    assert "身份" in result["reason"]


# ── allowance validation ───────────────────────────────────
def test_shipped_institutions_pass_allowance_validation(world, institution):
    violations = validate_tool_allowances(institution, world["tools"])
    assert violations == []


def test_validate_tool_allowances_catches_unregistered_tool(world):
    fake_institution = SimpleNamespace(
        posts=[
            SimpleNamespace(id="a", title="甲", tool_allowance=["run_task", "fly_to_moon"]),
        ]
    )
    violations = validate_tool_allowances(fake_institution, world["tools"])
    assert len(violations) == 1
    assert "fly_to_moon" in violations[0]
    assert "a" in violations[0]
