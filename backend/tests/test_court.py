"""Court services — end-to-end flows with FakeLLM + real bus/storage.

These tests wire the whole system together: edicts → chancery → executor
→ report → memorial → verdict, and the impeachment path. No network.
"""
import asyncio

import pytest

from imperial.agent.loop import AgentLoop
from imperial.agent.tools import build_tools
from imperial.bus import Bus
from imperial.court.appointments import AppointmentService
from imperial.court.edicts import EdictForm, EdictService
from imperial.court.impeachments import ImpeachmentService
from imperial.court.memorials import MemorialError, MemorialService
from imperial.rule_engine import RuleEngine
from tests.fake_llm import FakeLLM


@pytest.fixture
def system(institution, storage):
    """Full system wiring (no LLM — loops driven by FakeLLM in tests)."""
    engine = RuleEngine(institution)
    bus = Bus(institution, storage, engine)
    appointments = AppointmentService(storage)
    memorials = MemorialService(storage, bus, institution, engine)
    impeachments = ImpeachmentService(storage, bus, appointments)
    edicts = EdictService(storage, bus)
    tools = build_tools(bus=bus, storage=storage, memorials=memorials, appointments=appointments)
    return {
        "bus": bus, "engine": engine, "appointments": appointments,
        "memorials": memorials, "impeachments": impeachments,
        "edicts": edicts, "tools": tools, "storage": storage, "institution": institution,
    }


async def _run_loop(system, post_id, prompt, task, fake):
    loop = AgentLoop(
        institution=system["institution"],
        tools=system["tools"],
        llm=fake,  # type: ignore[arg-type]
        engine=system["engine"],
        max_turns=6,
    )
    return await loop.run(post_id, prompt, task)


# ── EdictService ───────────────────────────────────────────
async def test_issue_edict_delivers_to_chancery(system):
    edicts = system["edicts"]
    received = []
    await system["bus"].subscribe("chancery", lambda m: received.append(m) or asyncio.sleep(0))

    form = EdictForm(title="整理季度报告", task_type="report_compile",
                     description="汇总数据", target="finance")
    result = await edicts.issue(form)

    assert result["id"].startswith("edict_")
    assert "奉天承运皇帝" in result["formal_text"]
    await system["bus"].pump_once()
    assert len(received) == 1
    assert received[0].type == "edict"
    assert received[0].payload["form"]["target"] == "finance"


async def test_edict_persisted(system):
    form = EdictForm(title="任务", task_type="research", description="调研")
    result = await system["edicts"].issue(form)
    stored = system["edicts"].get(result["id"])
    assert stored is not None and stored["status"] == "pending"


# ── MemorialService ────────────────────────────────────────
async def test_memorial_submit_and_verdict_flow(system):
    mems = system["memorials"]
    m = await mems.submit(frm="chancery", content="谨奏……", msg_type="memorial")
    assert m["status"] == "submitted"

    decided = await mems.verdict(m["id"], "approved", comment="准")
    assert decided["status"] == "approved"
    assert decided["verdict"] == "approved"


async def test_memorial_rejected_notifies_chancery(system):
    mems = system["memorials"]
    msgs = []
    await system["bus"].subscribe("chancery", lambda m: msgs.append(m) or asyncio.sleep(0))

    m = await mems.submit(frm="chancery", content="奏报")
    await mems.verdict(m["id"], "rejected", comment="重做")
    await system["bus"].pump_once()

    assert any(x.type == "correction" and x.payload["verdict"] == "rejected" for x in msgs)


async def test_memorial_invalid_verdict_rejected(system):
    mems = system["memorials"]
    m = await mems.submit(frm="chancery", content="奏")
    with pytest.raises(MemorialError, match="invalid verdict"):
        await mems.verdict(m["id"], "banish")


# ── Impeachment + Appointment ──────────────────────────────
async def test_impeachment_removal_requires_emperor(system):
    imps, apps = system["impeachments"], system["appointments"]
    # seed a post row so appointment can act on it
    system["storage"].execute(
        "INSERT INTO posts (id, institution_id, title, role) VALUES ('justice', 'sanguan-jiuqing', '廷尉', 'executor')"
    )

    imp = await imps.open(target_post="justice", evidence="越权调用工具", type_="tool_violation")
    await imps.submit_recommendation(imp["id"], recommendation="removal", brief="证据确凿")

    # pending until emperor approves
    pending = imps.get(imp["id"])
    assert pending["status"] == "pending"
    assert pending["recommendation"] == "removal"

    await imps.verdict(imp["id"], "approve", comment="革职")
    post = apps.get_post("justice")
    assert post["status"] == "vacant"


async def test_impeachment_reject_keeps_post(system):
    imps, apps = system["impeachments"], system["appointments"]
    system["storage"].execute(
        "INSERT INTO posts (id, institution_id, title, role) VALUES ('finance', 'sanguan-jiuqing', '治粟内史', 'executor')"
    )
    imp = await imps.open(target_post="finance", evidence="轻微违制")
    await imps.submit_recommendation(imp["id"], recommendation="warning")
    await imps.verdict(imp["id"], "reject", comment="证据不足")

    post = apps.get_post("finance")
    assert post["status"] == "active"  # untouched


async def test_appointment_fills_vacancy(system):
    apps = system["appointments"]
    system["storage"].execute(
        "INSERT INTO posts (id, institution_id, title, role) VALUES ('relations', 'sanguan-jiuqing', '典客', 'executor')"
    )
    apps.remove("relations", reason="违制")
    post = apps.get_post("relations")
    assert post["status"] == "vacant"

    apps.appoint("relations", agent="agent_new")
    post = apps.get_post("relations")
    assert post["status"] == "active"
    assert post["current_agent"] == "agent_new"


# ── Full flow: edict → chancery agent → executor agent ─────
async def test_full_task_flow_with_fake_agents(system):
    """The whole journey: emperor issues edict, chancery decomposes+dispatches,
    executor runs and reports, chancery memorializes."""
    received = []
    await system["bus"].subscribe("chancery", lambda m: received.append(m) or asyncio.sleep(0))

    # 1. emperor issues edict
    form = EdictForm(title="整理数据", task_type="report_compile", description="汇总 Q3 数据", target="finance")
    edict = await system["edicts"].issue(form)
    await system["bus"].pump_once()
    assert received and received[0].type == "edict"

    # 2. chancery agent: decompose + dispatch to finance
    fake_chn = FakeLLM(script=[
        {"tool_calls": [
            {"name": "decompose_task", "arguments": {"edict_id": edict["id"], "subtasks": [{"title": "汇总数据", "target": "finance"}]}},
        ]},
        {"tool_calls": [
            {"name": "dispatch_task", "arguments": {"edict_id": edict["id"], "target": "finance", "title": "汇总数据", "description": "收集各部门 Q3 数据"}},
        ]},
        {"content": "已分派治粟内史办理。"},
    ])
    res = await _run_loop(system, "chancery", "你是丞相，负责拆解上谕并分派任务。", f"处理上谕：{edict['formal_text']}", fake_chn)
    assert not res.had_violations
    assert res.content == "已分派治粟内史办理。"

    # 3. executor agent receives assignment, runs, reports back to chancery
    finance_msgs = []
    await system["bus"].subscribe("finance", lambda m: finance_msgs.append(m) or asyncio.sleep(0))
    await system["bus"].pump_once()

    fake_fin = FakeLLM(script=[
        {"tool_calls": [
            {"name": "run_task", "arguments": {"task": "汇总 Q3 数据", "detail": "各部门已提交"}},
        ]},
        {"tool_calls": [
            {"name": "report_result", "arguments": {"edict_id": edict["id"], "summary": "数据汇总完毕"}},
        ]},
        {"content": "任务完成，已呈报丞相。"},
    ])
    res_fin = await _run_loop(system, "finance", "你是治粟内史，执行任务并呈报丞相。", "执行分派的任务", fake_fin)
    assert not res_fin.had_violations

    # 4. the report_result went through the bus to chancery
    await system["bus"].pump_once()
    assert any(m.type == "result" and m.payload["summary"] == "数据汇总完毕" for m in received)
