"""SQLite thin wrapper with schema migration.

Deep module: small interface (execute + named queries), hides connection
management, row factories, and migration. No ORM — plain sqlite3.

Thread-safety: each call opens a short-lived connection (SQLite handles
concurrent readers fine; writers serialize via the file lock). Good enough
for the local single-process deployment.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS institutions (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  definition_yaml TEXT NOT NULL,
  active INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS posts (
  id TEXT PRIMARY KEY,
  institution_id TEXT NOT NULL,
  title TEXT NOT NULL,
  role TEXT NOT NULL,
  reports_to TEXT,
  status TEXT DEFAULT 'active',
  model TEXT,
  current_agent TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS edicts (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  form_data TEXT NOT NULL,
  formal_text TEXT NOT NULL,
  status TEXT DEFAULT 'pending',
  issued_by TEXT DEFAULT 'emperor',
  issued_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS memorials (
  id TEXT PRIMARY KEY,
  edict_id TEXT,
  from_post TEXT NOT NULL,
  to_post TEXT DEFAULT 'emperor',
  content TEXT NOT NULL,
  status TEXT DEFAULT 'submitted',
  verdict TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  decided_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT DEFAULT (datetime('now')),
  kind TEXT NOT NULL,
  post_id TEXT,
  detail TEXT
);

CREATE TABLE IF NOT EXISTS impeachments (
  id TEXT PRIMARY KEY,
  violation_event_id INTEGER,
  target_post TEXT NOT NULL,
  type TEXT NOT NULL,
  evidence TEXT NOT NULL,
  brief TEXT,
  recommendation TEXT,
  status TEXT DEFAULT 'pending',
  verdict TEXT,
  decided_at TEXT
);

CREATE TABLE IF NOT EXISTS appointments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id TEXT NOT NULL,
  action TEXT NOT NULL,
  agent TEXT,
  reason TEXT,
  impeachment_id TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
"""


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class Storage:
    """Thin SQLite wrapper. One instance per database file."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._migrate()

    def _migrate(self) -> None:
        first_run = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _connect(self.path) as conn:
            conn.executescript(SCHEMA)
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            elif row["version"] < SCHEMA_VERSION:
                raise RuntimeError(
                    f"schema too old: {row['version']} < {SCHEMA_VERSION}; migration not implemented yet"
                )
        self._first_run = first_run

    # ── generic ─────────────────────────────────────────────
    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with _connect(self.path) as conn:
            return conn.execute(sql, params)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        with _connect(self.path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ── named queries ───────────────────────────────────────
    def insert_event(self, kind: str, post_id: str | None, detail: dict | None = None) -> int:
        detail_json = json.dumps(detail, ensure_ascii=False) if detail is not None else None
        cur = self.execute(
            "INSERT INTO events (kind, post_id, detail) VALUES (?, ?, ?)",
            (kind, post_id, detail_json),
        )
        lid = cur.lastrowid
        assert lid is not None, "INSERT without lastrowid"
        return int(lid)

    def get_events(self, kind: str | None = None, post_id: str | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if post_id:
            sql += " AND post_id = ?"
            params.append(post_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self.query(sql, params)
        for r in rows:
            if r.get("detail"):
                try:
                    r["detail"] = json.loads(r["detail"])
                except json.JSONDecodeError:
                    pass
        return rows
