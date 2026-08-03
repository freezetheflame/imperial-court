"""Impeachment service — violations become impeachments, the censorate
investigates, and the emperor decides.

Flow:
1. bus blocks a violation → violation_record lands in the censor's inbox
2. the censorate (agent) investigates and recommends: warning | removal
3. a new impeachment is persisted and memorialized to the emperor
   (privileged direct report: censor → emperor, type=impeachment)
4. emperor verdict: approve (→ removal / warning executed) | reject (recorded)

Warnings may be executed by the censorate directly; removals always need
the emperor's approval (enforced here, in the service, not the prompt).
"""
from __future__ import annotations

import uuid
from typing import Any

from imperial.bus import Bus
from imperial.storage import Storage

RECOMMENDATIONS = ("warning", "removal")


class ImpeachmentError(RuntimeError):
    pass


class ImpeachmentService:
    def __init__(self, storage: Storage, bus: Bus, appointments: "AppointmentService"):
        self.storage = storage
        self.bus = bus
        self.appointments = appointments

    async def open(
        self,
        *,
        target_post: str,
        violation_event_id: int | None = None,
        evidence: str,
        type_: str = "tool_violation",
    ) -> dict[str, Any]:
        """Open an impeachment case (called by the censorate)."""
        imp_id = f"imp_{uuid.uuid4().hex[:8]}"
        self.storage.execute(
            """INSERT INTO impeachments
               (id, violation_event_id, target_post, type, evidence)
               VALUES (?, ?, ?, ?, ?)""",
            (imp_id, violation_event_id, target_post, type_, evidence),
        )
        self.storage.insert_event(
            "impeachment", target_post,
            {"impeachment_id": imp_id, "type": type_},
        )
        return self.get(imp_id)  # type: ignore[return-value]

    async def submit_recommendation(
        self,
        imp_id: str,
        *,
        recommendation: str,
        brief: str | None = None,
    ) -> dict[str, Any]:
        """The censorate finalizes its recommendation and memorializes to the emperor."""
        if recommendation not in RECOMMENDATIONS:
            raise ImpeachmentError(f"invalid recommendation: {recommendation}")
        imp = self.storage.query_one("SELECT * FROM impeachments WHERE id = ?", (imp_id,))
        if imp is None:
            raise ImpeachmentError(f"impeachment not found: {imp_id}")

        self.storage.execute(
            "UPDATE impeachments SET recommendation = ?, brief = ? WHERE id = ?",
            (recommendation, brief, imp_id),
        )

        # privileged direct report: censor → emperor, type=impeachment
        verdict_needed = "建议革职" if recommendation == "removal" else "建议记档警告"
        ok, decision = await self.bus.post_message(
            "censor", "emperor", "impeachment",
            payload={
                "impeachment_id": imp_id,
                "target_post": imp["target_post"],
                "recommendation": recommendation,
                "brief": brief or "",
                "evidence": imp["evidence"],
                "summary": f"御史台弹劾{imp['target_post']}，{verdict_needed}。",
            },
        )
        if not ok:
            reason = decision.reason if decision is not None else "unknown"
            raise ImpeachmentError(f"impeachment memorial blocked: {reason}")
        return self.get(imp_id)  # type: ignore[return-value]

    async def verdict(self, imp_id: str, verdict: str, comment: str | None = None) -> dict[str, Any]:
        """The emperor decides on the impeachment."""
        if verdict not in ("approve", "reject"):
            raise ImpeachmentError(f"invalid verdict: {verdict}")
        imp = self.storage.query_one("SELECT * FROM impeachments WHERE id = ?", (imp_id,))
        if imp is None:
            raise ImpeachmentError(f"impeachment not found: {imp_id}")
        if imp["status"] != "pending":
            raise ImpeachmentError(f"impeachment already decided: {imp['status']}")

        if verdict == "approve":
            if imp["recommendation"] == "removal":
                # removal always requires the emperor's approval — reached here
                self.appointments.remove(imp["target_post"], reason=comment or "革职", impeachment_id=imp_id)
                status = "verdict_done"
            elif imp["recommendation"] == "warning":
                self.appointments.warn(imp["target_post"], reason=comment or "留任警告", impeachment_id=imp_id)
                status = "verdict_done"
            else:
                raise ImpeachmentError("impeachment has no recommendation yet")
        else:
            status = "rejected"

        self.storage.execute(
            "UPDATE impeachments SET status = ?, verdict = ?, decided_at = datetime('now') WHERE id = ?",
            (status, verdict, imp_id),
        )
        self.storage.insert_event(
            "impeachment_verdict", imp["target_post"],
            {"impeachment_id": imp_id, "verdict": verdict, "comment": comment},
        )
        return self.get(imp_id)  # type: ignore[return-value]

    # ── queries ────────────────────────────────────────────
    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return self.storage.query(
                "SELECT * FROM impeachments WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        return self.storage.query("SELECT * FROM impeachments ORDER BY created_at DESC")

    def get(self, imp_id: str) -> dict[str, Any] | None:
        return self.storage.query_one("SELECT * FROM impeachments WHERE id = ?", (imp_id,))
