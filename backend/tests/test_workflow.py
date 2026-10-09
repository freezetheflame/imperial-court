"""Workflow engine + 三省六部 institution — the "swap institution" proof.

These tests verify that the generic WorkflowEngine reproduces the 三公九卿
behavior AND drives the new 三省六部 pipeline (draft → review/veto →
dispatch → execute → aggregate → memorial) purely from YAML data.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from imperial.agent.loop import AgentLoop
from imperial.agent.scheduler import AgentScheduler
from imperial.agent.tools import build_tools
from imperial.agent.tracker import TaskTracker
from imperial.bus import Bus
from imperial.court.appointments import AppointmentService
from imperial.court.edicts import EdictForm, EdictService
from imperial.court.impeachments import ImpeachmentService
from imperial.court.memorials import MemorialService
from imperial.institution import Institution, InstitutionError, load_institution
from imperial.rule_engine import RuleEngine
from imperial.storage import Storage
from imperial.workflow import WorkflowEngine
from tests.fake_llm import FakeLLM

SL_YAML = Path(__file__).resolve().parent.parent / "institutions" / "sansheng-liubu.yaml"


@pytest.fixture
def sl() -> Institution:
    return load_institution(SL_YAML)


def test_sansheng_liubu_workflow_structure(sl):
    """The 三省六部 decree workflow has the five-stage pipeline + veto branch."""
    wf = sl.workflow("decree")
    assert wf.entry_from == "emperor"
    assert wf.entry_to == "zhongshu"
    assert wf.entry_type == "decree_intent"
    assert [s.capability for s in wf.stages] == [
        "draft", "review", "dispatch", "execute", "aggregate",
    ]
    # 门下 review has both an 'ok' and a 'veto' branch (the 封驳环)
    review = wf.stage_by_capability("review")
    assert review.branches["ok"].to == "shangshu"
    assert review.branches["veto"].to == "zhongshu"
    # dispatch fans out to the six ministries
    assert wf.stage_by_capability("dispatch").fanout.to == (
        "libu", "hubu", "lihu", "bingbu", "xingbu", "gongbu",
    )
    # executors report to 尚书省 (not a hardcoded chancery)
    assert wf.stage_by_capability("execute").report_to == "shangshu"


def test_sanguan_and_sansheng_share_engine(sl):
    """Same engine, different data → different pipeline shapes."""
    sg = load_institution(Path(__file__).resolve().parent.parent / "institutions" / "sanguan-jiuqing.yaml")
    sg_wf = sg.workflow("decree")
    sl_wf = sl.workflow("decree")
    # 三公九卿 has NO review stage (丞相 self-reviews); 三省六部 does
    assert sg_wf.stage_by_capability("review") is None
    assert sl_wf.stage_by_capability("review") is not None
    # both aggregate, but into different posts
    assert sg_wf.stage_by_capability("aggregate").post == "chancery"
    assert sl_wf.stage_by_capability("aggregate").post == "shangshu"


# ── engine routing (draft/review/veto) ─────────────────────
@pytest.fixture
def sl_world(tmp_path):
    sl_inst = load_institution(SL_YAML)
    storage = Storage(tmp_path / "sl.db")
    engine = RuleEngine(sl_inst)
    bus = Bus(sl_inst, storage, engine)
    appointments = AppointmentService(storage)
    memorials = MemorialService(storage, bus, sl_inst, engine)
    edicts = EdictService(storage, bus)
    tracker = TaskTracker()
    wfe = WorkflowEngine(
        institution=sl_inst, bus=bus, memorials=memorials, edicts=edicts, tracker=tracker,
    )
    tools = build_tools(
        bus=bus, storage=storage, memorials=memorials, appointments=appointments,
        tracker=tracker, engine=wfe,
    )
    fake_llms: dict[str, FakeLLM] = {}

    def loop_factory(post_id: str) -> AgentLoop:
        fake = fake_llms.setdefault(post_id, FakeLLM(script=[{"content": "已阅。"}]))
        return AgentLoop(
            institution=sl_inst, tools=tools, llm=fake,  # type: ignore[arg-type]
            engine=engine, max_turns=6,
        )

    scheduler = AgentScheduler(
        institution=sl_inst, bus=bus, memorials=memorials, loop_factory=loop_factory,
        tracker=tracker, edicts=edicts, engine=wfe,
    )
    return {
        "bus": bus, "scheduler": scheduler, "memorials": memorials, "edicts": edicts,
        "fake_llms": fake_llms, "storage": storage, "wfe": wfe, "sl": sl_inst,
    }


async def test_draft_review_veto_routing(sl_world):
    """submit_draft → menxia; approve → shangshu; veto → zhongshu."""
    wfe = sl_world["wfe"]
    # draft: zhongshu → menxia
    r = await wfe.submit_draft("e1", "诏书正文", "zhongshu")
    assert r["submitted"] is True
    # approve: menxia → shangshu (edict)
    r = await wfe.approve("e1", "准", "menxia")
    assert r["approved"] is True
    # veto: menxia → zhongshu (veto)
    r = await wfe.veto("e1", "不合规", "menxia")
    assert r["vetoed"] is True


async def test_full_sansheng_flow(sl_world):
    """End-to-end 三省六部: draft → review(approve) → dispatch → execute → aggregate → memorial."""
    await sl_world["scheduler"].start()

    sl_world["fake_llms"]["zhongshu"] = FakeLLM(script=[
        {"tool_calls": [{"name": "submit_draft", "arguments": {"edict_id": "e1", "draft_text": "拟诏：整理财政。"}}]},
        {"content": "已拟稿送审。"},
    ])
    sl_world["fake_llms"]["menxia"] = FakeLLM(script=[
        {"tool_calls": [{"name": "approve", "arguments": {"edict_id": "e1", "reason": "合制"}}]},
        {"content": "审核通过，颁行。"},
    ])
    # 尚书省 runs twice: dispatch (pump 1) then aggregate summary (pump 2)
    sl_world["fake_llms"]["shangshu"] = FakeLLM(script=[
        {"tool_calls": [
            {"name": "dispatch_task", "arguments": {"edict_id": "e1", "target": "libu", "title": "盘点官员", "description": "d1"}},
            {"name": "dispatch_task", "arguments": {"edict_id": "e1", "target": "hubu", "title": "清点钱粮", "description": "d2"}},
        ]},
        {"content": "已分派吏部、户部办理。"},
        {"content": "六部回报已汇总，臣谨奏陛下。"},
    ])
    sl_world["fake_llms"]["libu"] = FakeLLM(script=[
        {"tool_calls": [{"name": "run_task", "arguments": {"task": "盘点官员"}}]},
        {"tool_calls": [{"name": "report_result", "arguments": {"edict_id": "e1", "summary": "官员已盘点"}}]},
        {"content": "吏部办结。"},
    ])
    sl_world["fake_llms"]["hubu"] = FakeLLM(script=[
        {"tool_calls": [{"name": "run_task", "arguments": {"task": "清点钱粮"}}]},
        {"tool_calls": [{"name": "report_result", "arguments": {"edict_id": "e1", "summary": "钱粮已清点"}}]},
        {"content": "户部办结。"},
    ])

    form = EdictForm(title="整理财政", task_type="finance", description="盘点", target="libu")
    await sl_world["edicts"].issue(form)

    # pump_until_quiescent: the whole cascade (draft → review → dispatch →
    # execute → aggregate → memorial) completes in ONE pump call
    await sl_world["scheduler"].pump_once()
    memorials = sl_world["memorials"].list()
    assert len(memorials) == 1
    assert memorials[0]["from_post"] == "shangshu"


async def test_veto_loops_back_to_drafter(sl_world):
    """门下 veto sends the draft back to 中书 for re-drafting."""
    await sl_world["scheduler"].start()

    sl_world["fake_llms"]["zhongshu"] = FakeLLM(script=[
        {"tool_calls": [{"name": "submit_draft", "arguments": {"edict_id": "e1", "draft_text": "第一稿"}}]},
        {"content": "已拟稿。"},
    ])
    sl_world["fake_llms"]["menxia"] = FakeLLM(script=[
        {"tool_calls": [{"name": "veto", "arguments": {"edict_id": "e1", "reason": "措辞不合制"}}]},
        {"content": "封驳打回。"},
    ])

    form = EdictForm(title="试诏", task_type="research", description="测试", target="libu")
    await sl_world["edicts"].issue(form)
    await sl_world["scheduler"].pump_once()

    # the veto message landed in 中书's inbox
    events = sl_world["storage"].get_events(kind="message_sent")
    vetoes = [e for e in events if e["detail"]["message"]["type"] == "veto"]
    assert vetoes, "no veto message delivered"
    assert vetoes[0]["detail"]["message"]["to"] == "zhongshu"


# ── invalid workflow definitions ───────────────────────────
def test_workflow_last_stage_must_be_terminal(tmp_path):
    bad = """
institution:
  id: bad
  posts:
    - {id: a, title: A, role: drafter, reports_to: emperor, tool_allowance: [submit_draft]}
  communication_rules: []
  memorial_state_machine: {states: [submitted, archived], transitions: {}}
  workflows:
    decree:
      entry: {from: emperor, to: a, type: edict}
      stages:
        - {id: draft, post: a, capability: draft, next: {to: a, type: draft}}
"""
    p = tmp_path / "bad.yaml"
    p.write_text(bad, encoding="utf-8")
    with pytest.raises(InstitutionError, match="last stage must be terminal"):
        load_institution(p)


def test_workflow_unknown_post_rejected(tmp_path):
    bad = """
institution:
  id: bad
  posts:
    - {id: a, title: A, role: drafter, reports_to: emperor, tool_allowance: [submit_draft]}
  communication_rules: []
  memorial_state_machine: {states: [submitted, archived], transitions: {}}
  workflows:
    decree:
      entry: {from: emperor, to: a, type: edict}
      stages:
        - {id: draft, post: ghost, capability: draft, next: {to: a, type: draft}, terminal: {type: memorial}}
"""
    p = tmp_path / "bad.yaml"
    p.write_text(bad, encoding="utf-8")
    with pytest.raises(InstitutionError, match="unknown post"):
        load_institution(p)


def test_workflow_dispatch_requires_fanout(tmp_path):
    bad = """
institution:
  id: bad
  posts:
    - {id: a, title: A, role: dispatcher, reports_to: emperor, tool_allowance: [dispatch_task]}
  communication_rules: []
  memorial_state_machine: {states: [submitted, archived], transitions: {}}
  workflows:
    decree:
      entry: {from: emperor, to: a, type: edict}
      stages:
        - {id: dispatch, post: a, capability: dispatch, terminal: {type: memorial}}
"""
    p = tmp_path / "bad.yaml"
    p.write_text(bad, encoding="utf-8")
    with pytest.raises(InstitutionError, match="requires fanout"):
        load_institution(p)
