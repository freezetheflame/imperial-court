"""Storage: schema creation, migration guard, events round-trip."""
import json
import sqlite3

import pytest

from imperial.storage import SCHEMA_VERSION, Storage


def test_creates_schema_and_version(tmp_db):
    s = Storage(tmp_db)
    tables = {r["name"] for r in s.query("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {
        "schema_version", "institutions", "posts", "edicts",
        "memorials", "events", "impeachments", "appointments",
    }
    assert expected <= tables
    row = s.query_one("SELECT version FROM schema_version")
    assert row is not None and row["version"] == SCHEMA_VERSION


def test_persists_across_instances(tmp_db):
    Storage(tmp_db)
    s2 = Storage(tmp_db)  # reopening same file must not error
    row = s2.query_one("SELECT version FROM schema_version")
    assert row is not None and row["version"] == SCHEMA_VERSION


def test_old_schema_migrates_to_v3(tmp_db):
    # simulate an older schema (version 0, no persona column) → migration adds it
    s = Storage(tmp_db)
    s.execute("UPDATE schema_version SET version = 0")
    s.execute("ALTER TABLE posts DROP COLUMN persona")  # back to v2 shape
    s2 = Storage(tmp_db)  # reopen → migrates 0 → SCHEMA_VERSION
    row = s2.query_one("SELECT version FROM schema_version")
    assert row is not None and row["version"] == SCHEMA_VERSION
    cols = {r["name"] for r in s2.query("PRAGMA table_info(posts)")}
    assert "persona" in cols  # v3 migration added the persona column


def test_insert_and_query_events(storage):
    eid = storage.insert_event("violation", "justice", {"tool": "dispatch_task", "reason": "denied"})
    assert eid > 0
    rows = storage.get_events(kind="violation")
    assert len(rows) == 1
    assert rows[0]["post_id"] == "justice"
    assert rows[0]["detail"]["tool"] == "dispatch_task"  # JSON round-trip


def test_get_events_filters(storage):
    storage.insert_event("message_sent", "chancery", {"to": "emperor"})
    storage.insert_event("violation", "justice", {"tool": "x"})
    storage.insert_event("violation", "finance", {"tool": "y"})

    assert len(storage.get_events(kind="violation")) == 2
    assert len(storage.get_events(kind="violation", post_id="justice")) == 1
    assert len(storage.get_events(limit=1)) == 1


def test_query_one_returns_none_when_empty(storage):
    assert storage.query_one("SELECT * FROM events") is None
