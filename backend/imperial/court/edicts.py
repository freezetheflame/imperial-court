"""Edict service — the emperor's command becomes a formal edict, then
travels to the chancery via the bus (emperor → chancery, type=edict).

The emperor never talks to executors directly. The bus enforces this.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from imperial.bus import Bus
from imperial.storage import Storage


@dataclass
class EdictForm:
    title: str
    task_type: str
    description: str
    target: str | None = None        # 目标岗位，空 = 丞相自定
    constraints: str | None = None
    deadline: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EdictForm":
        title = data.get("title")
        task_type = data.get("task_type")
        description = data.get("description")
        if not title or not task_type or not description:
            raise ValueError("edict requires title, task_type, description")
        return cls(
            title=title,
            task_type=task_type,
            description=description,
            target=data.get("target"),
            constraints=data.get("constraints"),
            deadline=data.get("deadline"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "task_type": self.task_type,
            "description": self.description,
            "target": self.target,
            "constraints": self.constraints,
            "deadline": self.deadline,
        }


def render_formal_edict(form: EdictForm) -> str:
    """Render the structured form into formal edict prose."""
    target = f"着{form.target}办理" if form.target else "着丞相酌定分派"
    deadline = f"，限期{form.deadline}前办妥" if form.deadline else ""
    constraints = f"。约束：{form.constraints}" if form.constraints else ""
    return (
        f"奉天承运皇帝，诏曰：今有要务「{form.title}」，"
        f"属{form.task_type}之事。{target}{deadline}{constraints}。钦此。"
    )


class EdictService:
    def __init__(self, storage: Storage, bus: Bus):
        self.storage = storage
        self.bus = bus

    async def issue(self, form: EdictForm) -> dict[str, Any]:
        """Issue an edict: persist, render formal text, deliver to chancery."""
        edict_id = f"edict_{uuid.uuid4().hex[:8]}"
        formal = render_formal_edict(form)
        self.storage.execute(
            "INSERT INTO edicts (id, title, form_data, formal_text) VALUES (?, ?, ?, ?)",
            (edict_id, form.title, self._json(form.as_dict()), formal),
        )
        self.storage.insert_event("edict", None, {"edict_id": edict_id, "title": form.title})

        ok, decision = await self.bus.post_message(
            "emperor", "chancery", "edict",
            payload={"edict_id": edict_id, "title": form.title, "form": form.as_dict()},
        )
        if not ok:
            reason = decision.reason if decision is not None else "unknown"
            raise RuntimeError(f"edict delivery blocked by rules: {reason}")

        return {
            "id": edict_id,
            "title": form.title,
            "formal_text": formal,
            "status": "pending",
        }

    def list(self) -> list[dict[str, Any]]:
        return self.storage.query(
            "SELECT id, title, status, issued_at FROM edicts ORDER BY issued_at DESC"
        )

    def mark_completed(self, edict_id: str) -> None:
        """Persist completion — survives restarts (progress derives from it)."""
        self.storage.execute(
            "UPDATE edicts SET status = 'completed' WHERE id = ? AND status != 'completed'",
            (edict_id,),
        )

    def get(self, edict_id: str) -> dict[str, Any] | None:
        row = self.storage.query_one(
            "SELECT * FROM edicts WHERE id = ?", (edict_id,)
        )
        if row is None:
            return None
        row["form_data"] = self._unjson(row.get("form_data"))
        return row

    @staticmethod
    def _json(obj: Any) -> str:
        import json

        return json.dumps(obj, ensure_ascii=False)

    @staticmethod
    def _unjson(s: str | None) -> Any:
        import json

        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None
