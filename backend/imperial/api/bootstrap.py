"""Application bootstrap — wire the whole system together.

One factory builds: storage → institution → rule engine → bus → court
services → tools → app context. The API layer consumes this context.

Also seeds the posts table from the active institution so appointment
service and the frontend have something to show.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from imperial.agent.llm_client import LLMClient, LLMError
from imperial.agent.loop import AgentLoop
from imperial.agent.tools import build_tools
from imperial.bus import Bus
from imperial.court.appointments import AppointmentService
from imperial.court.edicts import EdictService
from imperial.court.impeachments import ImpeachmentService
from imperial.court.memorials import MemorialService
from imperial.institution import Institution, load_institution
from imperial.rule_engine import RuleEngine
from imperial.storage import Storage

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent  # backend/
DEFAULT_INSTITUTION = BACKEND_ROOT / "institutions" / "sanguan-jiuqing.yaml"


def _default_db() -> Path:
    """DB path: $IMPERIAL_DB env override, else backend/imperial.db."""
    env = os.environ.get("IMPERIAL_DB")
    if env:
        return Path(env)
    return BACKEND_ROOT / "imperial.db"


@dataclass
class AppContext:
    storage: Storage
    institution: Institution
    engine: RuleEngine
    bus: Bus
    appointments: AppointmentService
    memorials: MemorialService
    impeachments: ImpeachmentService
    edicts: EdictService
    tools: Any

    def make_loop(self, llm: LLMClient | None = None) -> AgentLoop:
        """Build an AgentLoop with the shared tools/engine (llm optional)."""
        return AgentLoop(
            institution=self.institution,
            tools=self.tools,
            llm=llm,  # type: ignore[arg-type]
            engine=self.engine,
        )


def build_context(
    *,
    db_path: Path | str | None = None,
    institution_path: Path | str | None = None,
    seed_posts: bool = True,
) -> AppContext:
    storage = Storage(db_path or _default_db())
    institution = load_institution(institution_path or DEFAULT_INSTITUTION)
    engine = RuleEngine(institution)
    bus = Bus(institution, storage, engine)
    appointments = AppointmentService(storage)
    memorials = MemorialService(storage, bus, institution, engine)
    impeachments = ImpeachmentService(storage, bus, appointments)
    edicts = EdictService(storage, bus)
    tools = build_tools(bus=bus, storage=storage, memorials=memorials, appointments=appointments)

    if seed_posts:
        _seed_posts(storage, institution)

    return AppContext(
        storage=storage, institution=institution, engine=engine, bus=bus,
        appointments=appointments, memorials=memorials, impeachments=impeachments,
        edicts=edicts, tools=tools,
    )


def _seed_posts(storage: Storage, institution: Institution) -> None:
    """Insert institution posts into the posts table (idempotent)."""
    existing = {r["id"] for r in storage.query("SELECT id FROM posts")}
    for p in institution.posts:
        if p.id in existing:
            continue
        storage.execute(
            """INSERT INTO posts (id, institution_id, title, role, reports_to, model)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (p.id, institution.id, p.title, p.role, p.reports_to, p.model),
        )
