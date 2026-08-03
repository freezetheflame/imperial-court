"""Rule engine: adjudication of messages, tools, transitions; policy hooks."""
from imperial.rule_engine import (
    CallToolAction,
    RuleDecision,
    RuleEngine,
    SendMessageAction,
    TransitionMemorialAction,
)


def test_message_allowed(institution):
    eng = RuleEngine(institution)
    d = eng.judge(SendMessageAction("emperor", "chancery", "edict"))
    assert d.allowed
    assert d.kind == "static"


def test_message_denied_violates_chain(institution):
    eng = RuleEngine(institution)
    # executor trying to report directly to emperor — must go through chancery
    d = eng.judge(SendMessageAction("finance", "emperor", "report"))
    assert not d.allowed
    assert "whitelist" in d.reason


def test_censor_privileged_direct_report(institution):
    eng = RuleEngine(institution)
    d = eng.judge(SendMessageAction("censor", "emperor", "impeachment"))
    assert d.allowed


def test_tool_allowed_and_denied(institution):
    eng = RuleEngine(institution)
    assert eng.judge(CallToolAction("chancery", "dispatch_task")).allowed
    assert not eng.judge(CallToolAction("justice", "dispatch_task")).allowed
    assert eng.judge(CallToolAction("censor", "draft_impeachment")).allowed


def test_memorial_transitions(institution):
    eng = RuleEngine(institution)
    assert eng.judge(TransitionMemorialAction("submitted", "read")).allowed
    assert eng.judge(TransitionMemorialAction("read", "approved")).allowed
    assert eng.judge(TransitionMemorialAction("approved", "archived")).allowed
    assert not eng.judge(TransitionMemorialAction("approved", "read")).allowed  # no going back
    assert not eng.judge(TransitionMemorialAction("submitted", "archived")).allowed


def test_policy_override(institution):
    eng = RuleEngine(institution)
    # normally denied; register a policy that allows it
    assert not eng.judge(SendMessageAction("finance", "emperor", "report")).allowed
    eng.register_policy(
        "message:finance->emperor:report",
        lambda action, inst: RuleDecision(True, "policy override"),
    )
    d = eng.judge(SendMessageAction("finance", "emperor", "report"))
    assert d.allowed
    assert d.kind == "policy"


def test_action_from_dict(institution):
    eng = RuleEngine(institution)
    a = eng.action_from_dict({"kind": "send_message", "from": "emperor", "to": "chancery", "type": "edict"})
    assert isinstance(a, SendMessageAction)
    assert eng.judge(a).allowed


def test_unknown_action_raises(institution):
    eng = RuleEngine(institution)
    try:
        eng.judge(object())  # type: ignore[arg-type]
        assert False, "should have raised"
    except ValueError as e:
        assert "unknown action" in str(e)
