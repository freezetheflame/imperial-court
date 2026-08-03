"""Async message bus with routing adjudication and audit.

Agents never talk directly. Every message goes through the bus, which:

1. adjudicates the message against the institution's communication
   whitelist (rule_engine.judge),
2. delivers it to the recipient's inbox (asyncio.Queue) if allowed,
3. records EVERYTHING (sent + blocked) into the event table — the
   audit trail that powers the censorate and the frontend event stream.

Blocked messages are turned into violation records and forwarded to the
censorate (violation_record message type).

Deep module: agents only know post_message() / subscribe(); routing,
adjudication, and audit all live inside the bus.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from imperial.institution import Institution
from imperial.rule_engine import RuleDecision, RuleEngine, SendMessageAction
from imperial.storage import Storage

Handler = Callable[["Message"], Awaitable[None]]


@dataclass
class Message:
    id: str
    frm: str
    to: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "from": self.frm,
            "to": self.to,
            "type": self.type,
            "payload": self.payload,
        }


class Bus:
    """Process-wide async message bus with adjudication + audit."""

    def __init__(self, institution: Institution, storage: Storage, engine: RuleEngine | None = None):
        self.institution = institution
        self.storage = storage
        self.engine = engine or RuleEngine(institution)
        self._inboxes: dict[str, asyncio.Queue[Message]] = {}
        self._handlers: dict[str, list[Handler]] = {}
        self._lock = asyncio.Lock()

    # ── subscription ───────────────────────────────────────
    async def subscribe(self, post_id: str, handler: Handler) -> None:
        async with self._lock:
            self._handlers.setdefault(post_id, []).append(handler)
            self._inboxes.setdefault(post_id, asyncio.Queue())

    async def _queue_for(self, post_id: str) -> asyncio.Queue[Message]:
        async with self._lock:
            return self._inboxes.setdefault(post_id, asyncio.Queue())

    # ── sending ────────────────────────────────────────────
    async def post_message(
        self,
        frm: str,
        to: str,
        msg_type: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[bool, RuleDecision | None]:
        """Send a message; returns (delivered, decision)."""
        action = SendMessageAction(frm, to, msg_type)
        decision = self.engine.judge(action)
        msg = Message(
            id=f"msg_{uuid.uuid4().hex[:12]}",
            frm=frm,
            to=to,
            type=msg_type,
            payload=payload or {},
        )
        if not decision.allowed:
            # audit + forward violation to censorate
            self._audit("message_blocked", frm, decision=decision, message=msg.as_dict())
            await self._forward_violation(frm, to, msg_type, decision)
            return False, decision

        self._audit("message_sent", frm, decision=decision, message=msg.as_dict())
        queue = await self._queue_for(to)
        await queue.put(msg)
        return True, decision

    async def _forward_violation(self, frm: str, to: str, msg_type: str, decision: RuleDecision) -> None:
        """Notify the censorate of an attempted violation."""
        if not self.institution.has_post("censor"):
            return
        await self._deliver_raw(
            Message(
                id=f"msg_{uuid.uuid4().hex[:12]}",
                frm="system",
                to="censor",
                type="violation_record",
                payload={
                    "attempted_from": frm,
                    "attempted_to": to,
                    "attempted_type": msg_type,
                    "reason": decision.reason,
                },
            )
        )

    async def _deliver_raw(self, msg: Message) -> None:
        self._audit("message_sent", msg.frm, message=msg.as_dict())
        queue = await self._queue_for(msg.to)
        await queue.put(msg)

    # ── receiving ──────────────────────────────────────────
    async def pump_once(self) -> None:
        """Deliver all currently-queued messages to handlers (test-friendly)."""
        for post_id, queue in list(self._inboxes.items()):
            while True:
                try:
                    msg = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                for handler in self._handlers.get(post_id, []):
                    await handler(msg)
                queue.task_done()

    async def pump(self) -> None:
        """Deliver queued messages to handlers. Run as a background task."""
        while True:
            await self.pump_once()
            await asyncio.sleep(0.05)

    # ── audit ──────────────────────────────────────────────
    def _audit(
        self,
        kind: str,
        post_id: str | None,
        decision: RuleDecision | None = None,
        message: dict | None = None,
        **extra: Any,
    ) -> None:
        detail: dict[str, Any] = dict(extra)
        if decision is not None:
            detail["decision"] = decision.as_dict()
        if message is not None:
            detail["message"] = message
        self.storage.insert_event(kind, post_id, detail)

    def audit_tool_call(self, post_id: str, tool: str, allowed: bool, reason: str) -> None:
        kind = "tool_call" if allowed else "violation"
        self.storage.insert_event(
            kind, post_id, {"tool": tool, "decision": {"allowed": allowed, "reason": reason}}
        )
