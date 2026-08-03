"""Bus: routing adjudication, delivery, audit trail, violation forwarding."""
import asyncio

import pytest

from imperial.bus import Bus, Message
from imperial.rule_engine import SendMessageAction


async def test_allowed_message_delivered(institution, storage):
    bus = Bus(institution, storage)
    received: list[Message] = []

    async def handler(msg: Message):
        received.append(msg)

    await bus.subscribe("chancery", handler)
    ok, decision = await bus.post_message("emperor", "chancery", "edict", {"title": "t"})
    assert ok
    assert decision is not None and decision.allowed
    await bus.pump_once()
    assert len(received) == 1
    assert received[0].payload["title"] == "t"


async def test_blocked_message_not_delivered_and_violation_forwarded(institution, storage):
    bus = Bus(institution, storage)
    chancery_msgs: list[Message] = []
    censor_msgs: list[Message] = []

    async def ch_handler(msg: Message):
        chancery_msgs.append(msg)

    async def cen_handler(msg: Message):
        censor_msgs.append(msg)

    await bus.subscribe("chancery", ch_handler)
    await bus.subscribe("censor", cen_handler)

    # finance → emperor directly: violates chain, must be blocked
    ok, decision = await bus.post_message("finance", "emperor", "report", {"data": "x"})
    assert not ok
    assert decision is not None and not decision.allowed

    await bus.pump_once()

    # nothing delivered to emperor (no emperor inbox anyway), nothing to chancery
    assert chancery_msgs == []
    # censorate received a violation_record
    assert len(censor_msgs) == 1
    v = censor_msgs[0]
    assert v.type == "violation_record"
    assert v.payload["attempted_from"] == "finance"
    assert v.payload["attempted_to"] == "emperor"
    assert v.payload["attempted_type"] == "report"


async def test_audit_trail_records_sent_and_blocked(institution, storage):
    bus = Bus(institution, storage)
    await bus.post_message("emperor", "chancery", "edict")
    await bus.post_message("finance", "emperor", "report")  # blocked

    events = storage.get_events()
    kinds = [e["kind"] for e in events]
    # edict (sent) + violation_record forward (sent) = 2; blocked = 1
    assert kinds.count("message_sent") == 2
    assert kinds.count("message_blocked") == 1
    blocked = [e for e in events if e["kind"] == "message_blocked"][0]
    assert blocked["detail"]["message"]["from"] == "finance"
    assert blocked["detail"]["decision"]["allowed"] is False

async def test_violation_record_itself_is_audited(institution, storage):
    bus = Bus(institution, storage)
    await bus.subscribe("censor", lambda msg: asyncio.sleep(0))
    await bus.post_message("finance", "emperor", "report")
    # the forwarded violation_record is also a message_sent (system → censor)
    events = storage.get_events()
    sent = [e for e in events if e["kind"] == "message_sent"]
    assert any(e["detail"]["message"]["to"] == "censor" for e in sent)


async def test_audit_tool_call(institution, storage):
    bus = Bus(institution, storage)
    bus.audit_tool_call("justice", "run_task", True, "ok")
    bus.audit_tool_call("justice", "dispatch_task", False, "denied")
    events = storage.get_events()
    assert len(events) == 2
    kinds = {e["kind"] for e in events}
    assert kinds == {"tool_call", "violation"}
    denied = [e for e in events if e["kind"] == "violation"][0]
    assert denied["detail"]["decision"]["allowed"] is False
