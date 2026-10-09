"""TaskTracker persistence — restart recovery via SQLite (schema v4)."""
import pytest

from imperial.agent.tracker import TaskTracker
from imperial.storage import Storage


@pytest.fixture
def db(tmp_path):
    return tmp_path / "tracker.db"


def test_schema_v4_tables_exist(db):
    storage = Storage(db)
    tables = {r["name"] for r in storage.query(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    assert {"subtasks", "edict_aggregation"} <= tables
    assert storage.query_one("SELECT version FROM schema_version")["version"] == 4


def test_progress_survives_restart(db):
    t1 = TaskTracker(storage=Storage(db))
    t1.register_subtask("e1", "finance", "finance", "核算军费")
    t1.register_subtask("e1", "justice", "justice", "复核律令")
    t1.complete_subtask("e1", "justice", "已复核")

    # simulate restart: fresh tracker over the same DB
    t2 = TaskTracker(storage=Storage(db))
    prog = t2.progress("e1")
    assert prog is not None
    assert prog.total == 2 and prog.done == 1
    assert prog.subtasks["finance"].completed is False
    assert prog.subtasks["justice"].summary == "已复核"


def test_fired_set_survives_restart_exactly_once(db):
    fired: list[str] = []
    t1 = TaskTracker(on_all_complete=fired.append, storage=Storage(db))
    t1.register_subtask("e1", "finance", "finance", "核算军费")
    assert t1.complete_subtask("e1", "finance", "完成") is True

    # restart: the edict must NOT fire again even if a duplicate report arrives
    t2 = TaskTracker(on_all_complete=fired.append, storage=Storage(db))
    assert t2.complete_subtask("e1", "finance", "重复回报") is False
    assert t2.is_complete("e1") is True


def test_late_report_after_restart_completes_edict(db):
    """Restart between dispatch and report: the late report still fires the aggregate."""
    t1 = TaskTracker(storage=Storage(db))
    t1.register_subtask("e1", "finance", "finance", "核算军费")

    fired: list[str] = []
    t2 = TaskTracker(on_all_complete=fired.append, storage=Storage(db))
    assert t2.complete_subtask("e1", "finance", "迟到的回报") is True
    assert t2.progress("e1").all_done


def test_reset_clears_persisted_state(db):
    t1 = TaskTracker(storage=Storage(db))
    t1.register_subtask("e1", "finance", "finance", "核算军费")
    t1.reset()
    t2 = TaskTracker(storage=Storage(db))
    assert t2.progress("e1") is None


def test_inmemory_tracker_unchanged():
    """No storage → pure in-memory, no SQLite involved."""
    t = TaskTracker()
    t.register_subtask("e1", "a", "a", "t")
    assert t.complete_subtask("e1", "a", "s") is True
