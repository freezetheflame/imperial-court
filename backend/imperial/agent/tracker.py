"""TaskTracker — multi-task aggregation for an edict.

An edict may fan out into several subtasks across one or more executors.
The tracker counts them: each dispatch_task registers a pending subtask,
each report_result completes one. When the last subtask completes, an
`on_all_complete` callback fires so the chancery can produce ONE aggregate
memorial instead of one per result.

Persistence: when constructed with a Storage instance, subtask state and
the fired-set are written through to SQLite (schema v4) and reloaded on
startup. After a restart mid-flight, progress queries keep working and
inquire_progress (催办) can re-urge pending posts — their late reports
still complete the edict and fire the aggregate exactly once.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class SubtaskState:
    target: str
    title: str
    completed: bool = False
    summary: str | None = None


@dataclass
class EdictProgress:
    edict_id: str
    subtasks: dict[str, SubtaskState] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.subtasks)

    @property
    def done(self) -> int:
        return sum(1 for s in self.subtasks.values() if s.completed)

    @property
    def all_done(self) -> bool:
        return self.total > 0 and self.done == self.total

    def summaries(self) -> list[str]:
        return [s.summary for s in self.subtasks.values() if s.summary]


class TaskTracker:
    """Tracks subtask completion per edict; fires on_all_complete once.

    With `storage` given, state is write-through persisted and reloaded at
    construction (restart recovery).
    """

    def __init__(
        self,
        on_all_complete: Callable[[str], Any] | None = None,
        storage: Any | None = None,
    ):
        self.on_all_complete = on_all_complete
        self._storage = storage
        self._progress: dict[str, EdictProgress] = {}
        self._fired: set[str] = set()
        if storage is not None:
            self._load()

    # ── persistence ────────────────────────────────────────
    def _load(self) -> None:
        """Reload subtask progress + fired-set from SQLite."""
        for r in self._storage.query("SELECT * FROM subtasks"):
            prog = self._progress.setdefault(r["edict_id"], EdictProgress(r["edict_id"]))
            prog.subtasks[r["subtask_key"]] = SubtaskState(
                target=r["target"], title=r["title"],
                completed=bool(r["completed"]), summary=r["summary"],
            )
        for r in self._storage.query(
            "SELECT edict_id FROM edict_aggregation WHERE fired = 1"
        ):
            self._fired.add(r["edict_id"])

    def _persist_subtask(self, edict_id: str, key: str, sub: SubtaskState) -> None:
        if self._storage is None:
            return
        self._storage.execute(
            """INSERT INTO subtasks (edict_id, subtask_key, target, title, completed, summary)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (edict_id, subtask_key)
               DO UPDATE SET completed = excluded.completed, summary = excluded.summary""",
            (edict_id, key, sub.target, sub.title, int(sub.completed), sub.summary),
        )

    def _persist_fired(self, edict_id: str) -> None:
        if self._storage is None:
            return
        self._storage.execute(
            """INSERT INTO edict_aggregation (edict_id, fired) VALUES (?, 1)
               ON CONFLICT (edict_id) DO UPDATE SET fired = 1""",
            (edict_id,),
        )

    # ── lifecycle ──────────────────────────────────────────
    def register_edict(self, edict_id: str) -> None:
        if edict_id not in self._progress:
            self._progress[edict_id] = EdictProgress(edict_id)

    def register_subtask(self, edict_id: str, subtask_key: str, target: str, title: str) -> None:
        """Called by dispatch_task: one pending subtask."""
        self.register_edict(edict_id)
        prog = self._progress[edict_id]
        if subtask_key not in prog.subtasks:
            prog.subtasks[subtask_key] = SubtaskState(target=target, title=title)
            self._persist_subtask(edict_id, subtask_key, prog.subtasks[subtask_key])

    def complete_subtask(self, edict_id: str, subtask_key: str, summary: str) -> bool:
        """Called by report_result. Returns True if this completed the edict."""
        prog = self._progress.get(edict_id)
        if prog is None:
            return False
        sub = prog.subtasks.get(subtask_key)
        if sub is None:
            # a report for an unknown subtask — treat as the sole task
            self.register_subtask(edict_id, subtask_key, "unknown", summary[:40])
            sub = prog.subtasks[subtask_key]
        sub.completed = True
        sub.summary = summary
        self._persist_subtask(edict_id, subtask_key, sub)
        if prog.all_done and edict_id not in self._fired:
            self._fired.add(edict_id)
            self._persist_fired(edict_id)
            return True
        return False

    def fire(self, edict_id: str) -> None:
        """Invoke the on_all_complete callback for a completed edict."""
        if self.on_all_complete is not None:
            self.on_all_complete(edict_id)

    # ── queries ────────────────────────────────────────────
    def progress(self, edict_id: str) -> EdictProgress | None:
        return self._progress.get(edict_id)

    def snapshot(self, edict_id: str) -> dict[str, Any] | None:
        """Structured progress snapshot for the frontend.

        stage:
          pending    — edict registered, no subtasks yet (chancery decomposing)
          executing  — subtasks exist, some pending (agents working)
          done       — all subtasks completed (memorial submitted)
        """
        prog = self._progress.get(edict_id)
        if prog is None:
            return {"edict_id": edict_id, "stage": "pending", "total": 0, "done": 0, "percent": 0, "subtasks": []}
        if prog.all_done:
            stage = "done"
        elif prog.total == 0:
            stage = "pending"
        else:
            stage = "executing"
        subtasks = [
            {
                "key": k,
                "target": s.target,
                "title": s.title,
                "completed": s.completed,
                "summary": s.summary,
            }
            for k, s in prog.subtasks.items()
        ]
        percent = round(prog.done / prog.total * 100) if prog.total else 0
        return {
            "edict_id": edict_id,
            "stage": stage,
            "total": prog.total,
            "done": prog.done,
            "percent": percent,
            "subtasks": subtasks,
        }

    def is_complete(self, edict_id: str) -> bool:
        prog = self._progress.get(edict_id)
        return prog is not None and prog.all_done

    def reset(self) -> None:
        self._progress.clear()
        self._fired.clear()
        if self._storage is not None:
            self._storage.execute("DELETE FROM subtasks")
            self._storage.execute("DELETE FROM edict_aggregation")


async def fire_async(tracker: TaskTracker, edict_id: str) -> None:
    """Fire the tracker's callback, awaiting it if it's a coroutine function."""
    cb = tracker.on_all_complete
    if cb is None:
        return
    result = cb(edict_id)
    if hasattr(result, "__await__"):
        await result
