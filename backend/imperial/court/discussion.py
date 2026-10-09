"""Court room service — 朝房集议，the agent playground.

Posts (and the emperor) open discussion threads and speak in them; every
speech is fanned out by the bus to all room participants, so agents can
react to each other. The room is free discussion by design, with two
safety properties that are NOT governance but crash protection:

- a global on/off switch (institution court_room.enabled, overridable by
  the IMPERIAL_COURT_ROOM env var), and
- a per-thread turn budget (court_room.max_turns): when a thread's speech
  count hits the budget it auto-closes — an unbounded LLM chatter loop
  can never burn tokens forever.

Everything is persisted (court_threads / court_messages) and broadcast
over SSE so the frontend can watch the room live. Speeches also flow
through the bus audit trail, so the censorate can use them as evidence.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Awaitable, Callable

from imperial.bus import Bus
from imperial.institution import Institution
from imperial.storage import Storage

ROOM_ID = "court_room"
MSG_TYPE = "discuss"

# async callback used to push SSE events (wired to EventBroadcaster.broadcast)
Broadcaster = Callable[[str, dict[str, Any]], Awaitable[None]]


class CourtRoomError(RuntimeError):
    pass


class CourtRoomService:
    def __init__(
        self,
        storage: Storage,
        bus: Bus,
        institution: Institution,
        broadcaster: Broadcaster | None = None,
    ):
        self.storage = storage
        self.bus = bus
        self.institution = institution
        self._broadcast = broadcaster

    def set_broadcaster(self, broadcaster: Broadcaster) -> None:
        """Wire SSE broadcasting after construction (see api/main.py)."""
        self._broadcast = broadcaster

    # ── config ─────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        """Global switch: YAML court_room.enabled, env override wins."""
        env = os.environ.get("IMPERIAL_COURT_ROOM")
        if env is not None:
            return env.strip().lower() not in ("0", "false", "off", "no")
        return self.institution.court_room.enabled

    @property
    def participants(self) -> tuple[str, ...]:
        return self.institution.court_room.participants

    @property
    def max_turns(self) -> int:
        return self.institution.court_room.max_turns

    # ── threads ────────────────────────────────────────────
    async def open_thread(self, *, topic: str, opened_by: str) -> dict[str, Any]:
        if not self.enabled:
            raise CourtRoomError("朝房已闭（court_room 未启用）")
        if opened_by != "emperor" and opened_by not in self.participants:
            raise CourtRoomError(f"{opened_by} 不在朝房参与者之列")
        tid = f"ct_{uuid.uuid4().hex[:8]}"
        self.storage.execute(
            "INSERT INTO court_threads (id, topic, opened_by) VALUES (?, ?, ?)",
            (tid, topic, opened_by),
        )
        self.storage.insert_event("court_thread_open", opened_by, {"thread_id": tid, "topic": topic})
        thread = self.get_thread(tid)
        await self._emit("court", {"kind": "thread_open", "thread": thread})
        # 开议即广播：议题本身就是开场发言——落库 + fan-out 给全体参与者。
        # 否则议题只是躺在库里，百官无人知晓，讨论永远不会自启动。
        # 这一轮同样计入熔断预算。
        await self.speak(thread_id=tid, frm=opened_by, content=topic)
        return self.get_thread(tid)  # type: ignore[return-value]

    async def close_thread(self, thread_id: str, *, reason: str = "闭议") -> dict[str, Any]:
        thread = self._require_thread(thread_id)
        if thread["status"] == "closed":
            return thread
        self.storage.execute(
            "UPDATE court_threads SET status = 'closed', closed_at = datetime('now') WHERE id = ?",
            (thread_id,),
        )
        self.storage.insert_event("court_thread_close", None, {"thread_id": thread_id, "reason": reason})
        closed = self.get_thread(thread_id)
        await self._emit("court", {"kind": "thread_close", "thread": closed, "reason": reason})
        return closed  # type: ignore[return-value]

    # ── speaking ───────────────────────────────────────────
    async def speak(self, *, thread_id: str, frm: str, content: str) -> dict[str, Any]:
        """Speak in a thread: persist, bump the turn counter (fuse), fan out.

        Returns the persisted message plus fuse state. Raises CourtRoomError
        when the room/thread is closed or the speaker is not a participant.
        """
        if not self.enabled:
            raise CourtRoomError("朝房已闭（court_room 未启用）")
        if frm != "emperor" and frm not in self.participants:
            raise CourtRoomError(f"{frm} 不在朝房参与者之列")
        thread = self._require_thread(thread_id)
        if thread["status"] != "open":
            raise CourtRoomError(f"议题已闭：{thread['topic']}")

        mid = f"cm_{uuid.uuid4().hex[:10]}"
        self.storage.execute(
            "INSERT INTO court_messages (id, thread_id, frm, content) VALUES (?, ?, ?, ?)",
            (mid, thread_id, frm, content),
        )
        self.storage.execute(
            "UPDATE court_threads SET turns = turns + 1 WHERE id = ?",
            (thread_id,),
        )
        turns = thread["turns"] + 1

        # fan out to all participants (except the speaker) via the bus;
        # adjudicated once against the room whitelist
        ok, decision = await self.bus.post_to_room(
            frm, ROOM_ID, MSG_TYPE,
            payload={
                "thread_id": thread_id,
                "topic": thread["topic"],
                "content": content,
                "speaker": frm,
                "turn": turns,
                "turns_left": max(0, self.max_turns - turns),
            },
            recipients=list(self.participants),
        )

        message = {
            "id": mid, "thread_id": thread_id, "frm": frm,
            "content": content, "delivered": ok,
            "blocked_reason": decision.reason if (decision is not None and not ok) else None,
        }
        await self._emit("court", {"kind": "message", "thread_id": thread_id, "message": message})

        # fuse: hitting the budget auto-closes the thread
        closed = False
        if turns >= self.max_turns:
            await self.close_thread(thread_id, reason=f"轮次熔断（{self.max_turns} 轮）")
            closed = True
        message["thread_closed"] = closed
        message["turn"] = turns
        return message

    # ── queries ────────────────────────────────────────────
    def list_threads(self, *, limit: int = 20) -> list[dict[str, Any]]:
        threads = self.storage.query(
            "SELECT * FROM court_threads ORDER BY created_at DESC LIMIT ?", (limit,),
        )
        for t in threads:
            # rowid（插入顺序）而非 created_at：同一秒内的多条发言时间戳相同，
            # 按时间排序会乱序（随机 uuid id 也不保序）
            last = self.storage.query_one(
                "SELECT frm, content, created_at FROM court_messages WHERE thread_id = ? ORDER BY rowid DESC LIMIT 1",
                (t["id"],),
            )
            t["last_message"] = last
        return threads

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        thread = self.storage.query_one(
            "SELECT * FROM court_threads WHERE id = ?", (thread_id,),
        )
        if thread is None:
            return None
        thread["messages"] = self.storage.query(
            "SELECT * FROM court_messages WHERE thread_id = ? ORDER BY rowid ASC",
            (thread_id,),
        )
        return thread

    # ── internals ──────────────────────────────────────────
    def _require_thread(self, thread_id: str) -> dict[str, Any]:
        thread = self.storage.query_one(
            "SELECT * FROM court_threads WHERE id = ?", (thread_id,),
        )
        if thread is None:
            raise CourtRoomError(f"议题不存在：{thread_id}")
        return thread

    async def _emit(self, event: str, data: dict[str, Any]) -> None:
        if self._broadcast is not None:
            await self._broadcast(event, data)
