"""Appointment service — post lifecycle: remove (革职), appoint (任命),
warn (留任警告).

Removals leave the post vacant; the emperor must appoint a new agent.
Warnings are recorded and leave the post untouched.
"""
from __future__ import annotations

from typing import Any

from imperial.storage import Storage


class AppointmentError(RuntimeError):
    pass


class AppointmentService:
    def __init__(self, storage: Storage):
        self.storage = storage

    # ── actions ────────────────────────────────────────────
    def remove(self, post_id: str, *, reason: str, impeachment_id: str | None = None) -> dict[str, Any]:
        """革职 — post becomes vacant, its agent is dismissed."""
        post = self._get_post(post_id)
        self.storage.execute(
            "UPDATE posts SET status = 'vacant', current_agent = NULL WHERE id = ?",
            (post_id,),
        )
        self._record("remove", post_id, reason=reason, impeachment_id=impeachment_id, agent=post.get("current_agent"))
        return self._get_post(post_id)  # type: ignore[return-value]

    def appoint(self, post_id: str, *, agent: str, reason: str = "任命") -> dict[str, Any]:
        """任命 — fill a vacant post (or replace the current agent)."""
        self._get_post(post_id)  # raises if unknown
        self.storage.execute(
            "UPDATE posts SET status = 'active', current_agent = ? WHERE id = ?",
            (agent, post_id),
        )
        self._record("appoint", post_id, reason=reason, agent=agent)
        return self._get_post(post_id)  # type: ignore[return-value]

    def warn(self, post_id: str, *, reason: str, impeachment_id: str | None = None) -> dict[str, Any]:
        """留任警告 — recorded, post untouched."""
        self._get_post(post_id)  # raises if unknown
        self._record("warn", post_id, reason=reason, impeachment_id=impeachment_id)
        return self._get_post(post_id)  # type: ignore[return-value]

    # ── queries ────────────────────────────────────────────
    def list_posts(self, institution_id: str | None = None) -> list[dict[str, Any]]:
        if institution_id:
            return self.storage.query(
                "SELECT * FROM posts WHERE institution_id = ? ORDER BY rowid", (institution_id,)
            )
        return self.storage.query("SELECT * FROM posts ORDER BY rowid")

    def get_post(self, post_id: str) -> dict[str, Any] | None:
        return self._get_post(post_id)

    def list_appointments(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.storage.query(
            "SELECT * FROM appointments ORDER BY id DESC LIMIT ?", (limit,)
        )

    # ── helpers ────────────────────────────────────────────
    def _get_post(self, post_id: str) -> dict[str, Any]:
        row = self.storage.query_one("SELECT * FROM posts WHERE id = ?", (post_id,))
        if row is None:
            raise AppointmentError(f"unknown post: {post_id}")
        return row

    def _record(
        self,
        action: str,
        post_id: str,
        *,
        reason: str,
        agent: str | None = None,
        impeachment_id: str | None = None,
    ) -> None:
        self.storage.execute(
            "INSERT INTO appointments (post_id, action, agent, reason, impeachment_id) VALUES (?, ?, ?, ?, ?)",
            (post_id, action, agent, reason, impeachment_id),
        )
        self.storage.insert_event(
            "appointment", post_id,
            {"action": action, "agent": agent, "reason": reason, "impeachment_id": impeachment_id},
        )
