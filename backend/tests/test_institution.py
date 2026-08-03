"""Institution: real YAML loads, model invariants hold."""
import pytest

from imperial.institution import InstitutionError, load_institution


def test_real_institution_loads(institution):
    assert institution.id == "sanguan-jiuqing"
    assert len(institution.posts) == 8  # 3公 + 4部 + 御史助手


def test_posts_have_expected_roles(institution):
    roles = {p.role for p in institution.posts}
    assert {"coordinator", "executor", "inspector", "inspector_assistant", "external"} <= roles
    # exactly one coordinator (chancery) and one inspector (censor)
    assert len(institution.posts_by_role("coordinator")) == 1
    assert len(institution.posts_by_role("inspector")) == 1


def test_reports_to_chain(institution):
    # executors report to chancery; censor reports to emperor (direct)
    for p in institution.posts_by_role("executor"):
        assert p.reports_to == "chancery"
    assert institution.post("censor").reports_to is None  # normalized from 'emperor'
    assert institution.post("chancery").reports_to is None
    assert institution.post("censor_assistant").reports_to == "censor"


def test_can_send_whitelist(institution):
    # emperor → chancery edict: allowed
    assert institution.can_send("emperor", "chancery", "edict")
    # censor → emperor impeachment (privileged direct report): allowed
    assert institution.can_send("censor", "emperor", "impeachment")
    # finance → emperor directly: NOT allowed (must go through chancery)
    assert not institution.can_send("finance", "emperor", "report")
    # chancery → finance task_assignment: allowed
    assert institution.can_send("chancery", "finance", "task_assignment")
    # finance → censor violation_record: NOT allowed (system-generated only)
    assert not institution.can_send("finance", "censor", "violation_record")


def test_can_call_tool_whitelist(institution):
    assert institution.can_call_tool("chancery", "dispatch_task")
    assert institution.can_call_tool("justice", "run_task")
    assert not institution.can_call_tool("justice", "dispatch_task")  # coordinator-only tool
    assert not institution.can_call_tool("finance", "draft_impeachment")  # censor-only tool
    assert institution.can_call_tool("censor", "draft_impeachment")


def test_memorial_state_machine(institution):
    assert institution.memorial_states == (
        "submitted", "read", "approved", "rejected", "held", "returned", "archived",
    )
    assert "approved" in institution.memorial_transitions["read"]
    assert institution.memorial_transitions["approved"] == ("archived",)
    assert institution.memorial_transitions["rejected"] == ("archived",)


def test_unknown_post_raises(institution):
    with pytest.raises(KeyError):
        institution.post("nonexistent")


def test_missing_file_raises(tmp_path):
    with pytest.raises(InstitutionError, match="not found"):
        load_institution(tmp_path / "nope.yaml")


def test_duplicate_post_ids_rejected(tmp_path):
    bad = """
institution:
  id: test
  posts:
    - {id: a, title: A, role: executor, reports_to: emperor, tool_allowance: [run_task]}
    - {id: a, title: A2, role: executor, reports_to: emperor, tool_allowance: [run_task]}
  communication_rules: []
  memorial_state_machine: {states: [submitted, archived], transitions: {}}
"""
    p = tmp_path / "bad.yaml"
    p.write_text(bad, encoding="utf-8")
    with pytest.raises(InstitutionError, match="duplicate post id"):
        load_institution(p)


def test_bad_role_rejected(tmp_path):
    bad = """
institution:
  id: test
  posts:
    - {id: a, title: A, role: wizard, reports_to: emperor, tool_allowance: [run_task]}
  communication_rules: []
  memorial_state_machine: {states: [submitted, archived], transitions: {}}
"""
    p = tmp_path / "bad.yaml"
    p.write_text(bad, encoding="utf-8")
    with pytest.raises(InstitutionError, match="invalid role"):
        load_institution(p)
