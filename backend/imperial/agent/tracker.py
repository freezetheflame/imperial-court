"""TaskTracker — multi-task aggregation for an edict.

An edict may fan out into several subtasks across one or more executors.
The tracker counts them: each dispatch_task registers a pending subtask,
each report_result completes one. When the last subtask completes, an
`on_all_complete` callback fires so the chancery can produce ONE aggregate
memorial instead of one per result.

Pure in-memory state (not persisted): a restart mid-flight loses tracking,
which is acceptable for v1 — the memorials/events tables still hold truth.
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
    """Tracks subtask completion per edict; fires on_all_complete once."""

    def __init__(self, on_all_complete: Callable[[str], Any] | None = None):
        self.on_all_complete = on_all_complete
        self._progress: dict[str, EdictProgress] = {}
        self._fired: set[str] = set()

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
        if prog.all_done and edict_id not in self._fired:
            self._fired.add(edict_id)
            return True
        return False

    def fire(self, edict_id: str) -> None:
        """Invoke the on_all_complete callback for a completed edict."""
        if self.on_all_complete is not None:
            self.on_all_complete(edict_id)

    # ── queries ────────────────────────────────────────────
    def progress(self, edict_id: str) -> EdictProgress | None:
        return self._progress.get(edict_id)

    def is_complete(self, edict_id: str) -> bool:
        prog = self._progress.get(edict_id)
        return prog is not None and prog.all_done

    def reset(self) -> None:
        self._progress.clear()
        self._fired.clear()


async def fire_async(tracker: TaskTracker, edict_id: str) -> None:
    """Fire the tracker's callback, awaiting it if it's a coroutine function."""
    cb = tracker.on_all_complete
    if cb is None:
        return
    result = cb(edict_id)
    if hasattr(result, "__await__"):
        await result
