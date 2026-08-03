"""Memorial service — the memorial state machine and the emperor's verdicts.

States (from the institution): submitted → read → (approved|rejected|held|returned) → archived.

The emperor verdicts:
- approved → archived (job done)
- rejected → archived + chancery is told to re-plan (task returns to chancery)
- held      → stays read (搁置)
- returned  → chancery is told to re-work (发回重办)

Every transition is adjudicated by the rule engine before it happens.
"""
from __future__ import annotations

import uuid
from typing import Any

from imperial.bus import Bus
from imperial.institution import Institution
from imperial.rule_engine import RuleEngine, TransitionMemorialAction
from imperial.storage import Storage

VERDICTS = ("approved", "rejected", "held", "returned")


class MemorialError(RuntimeError):
    pass


class MemorialService:
    def __init__(
        self,
        storage: Storage,
        bus: Bus,
        institution: Institution,
        engine: RuleEngine | None = None,
        on_submit: Any | None = None,  # callable(memorial_dict) fired on new memorial
    ):
        self.storage = storage
        self.bus = bus
        self.institution = institution
        self.engine = engine or RuleEngine(institution)
        self.on_submit = on_submit

    # ── creation ───────────────────────────────────────────
    async def submit(
        self,
        *,
        frm: str,
        content: str,
        edict_id: str | None = None,
        msg_type: str = "memorial",
    ) -> dict[str, Any] | None:
        """A post presents a memorial to the emperor (via the bus)."""
        ok, decision = await self.bus.post_message(
            frm, "emperor", msg_type,
            payload={"content": content, "edict_id": edict_id},
        )
        if not ok:
            reason = decision.reason if decision is not None else "unknown"
            raise MemorialError(f"memorial blocked by rules: {reason}")

        mem_id = f"mem_{uuid.uuid4().hex[:8]}"
        self.storage.execute(
            "INSERT INTO memorials (id, edict_id, from_post, content) VALUES (?, ?, ?, ?)",
            (mem_id, edict_id, frm, content),
        )
        self.storage.insert_event(
            "memorial", frm, {"memorial_id": mem_id, "type": msg_type, "to": "emperor"}
        )
        row = self.get(mem_id)
        if row is not None and self.on_submit is not None:
            self.on_submit(row)
        return row

    # ── verdicts ───────────────────────────────────────────
    async def verdict(self, memorial_id: str, verdict: str, comment: str | None = None) -> dict[str, Any]:
        """The emperor's verdict on a memorial."""
        if verdict not in VERDICTS:
            raise MemorialError(f"invalid verdict: {verdict}")

        mem = self.storage.query_one("SELECT * FROM memorials WHERE id = ?", (memorial_id,))
        if mem is None:
            raise MemorialError(f"memorial not found: {memorial_id}")

        current = mem["status"]
        # The state machine encodes verdict semantics: from `read`, the
        # emperor's verdict moves the memorial to approved/rejected/held/
        # returned. So the verdict value IS the target state.
        if current == "submitted":
            if not self.engine.judge(TransitionMemorialAction("submitted", "read")).allowed:
                raise MemorialError("transition submitted->read not allowed")
            self.storage.execute(
                "UPDATE memorials SET status = 'read' WHERE id = ?", (memorial_id,)
            )
            current = "read"

        target = verdict  # approved | rejected | held | returned
        decision = self.engine.judge(TransitionMemorialAction(current, target))
        if not decision.allowed:
            raise MemorialError(f"transition {current}->{target} not allowed")

        self.storage.execute(
            "UPDATE memorials SET status = ?, verdict = ?, decided_at = datetime('now') WHERE id = ?",
            (target, verdict, memorial_id),
        )
        self.storage.insert_event(
            "memorial_verdict", None,
            {"memorial_id": memorial_id, "verdict": verdict, "comment": comment},
        )

        # rejected / returned → tell the chancery to re-plan (emperor → chancery)
        if verdict in ("rejected", "returned"):
            await self.bus.post_message(
                "emperor", "chancery", "correction",
                payload={
                    "memorial_id": memorial_id,
                    "verdict": verdict,
                    "comment": comment or "",
                    "edict_id": mem["edict_id"],
                },
            )

        return self.get(memorial_id)  # type: ignore[return-value]

    # ── queries ────────────────────────────────────────────
    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return self.storage.query(
                "SELECT * FROM memorials WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        return self.storage.query(
            "SELECT * FROM memorials ORDER BY created_at DESC"
        )

    def get(self, memorial_id: str) -> dict[str, Any] | None:
        return self.storage.query_one("SELECT * FROM memorials WHERE id = ?", (memorial_id,))
