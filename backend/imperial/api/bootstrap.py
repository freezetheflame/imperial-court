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
from imperial.agent.persona import PersonaService
from imperial.agent.scheduler import AgentScheduler
from imperial.agent.tools import build_tools
from imperial.agent.tracker import TaskTracker
from imperial.bus import Bus
from imperial.court.appointments import AppointmentService
from imperial.court.edicts import EdictService
from imperial.court.impeachments import ImpeachmentService
from imperial.court.memorials import MemorialService
from imperial.institution import Institution, load_institution
from imperial.rule_engine import RuleEngine
from imperial.storage import Storage
from imperial.workflow import WorkflowEngine

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent  # backend/
DEFAULT_INSTITUTION = BACKEND_ROOT / "institutions" / "sanguan-jiuqing.yaml"


def _current_surnames(storage: Storage, exclude_post: str | None = None) -> set[str]:
    """Surnames of all posts currently holding a persona (used for diversity)."""
    import json as _json

    used: set[str] = set()
    rows = storage.query("SELECT id, persona FROM posts WHERE persona IS NOT NULL")
    for r in rows:
        if exclude_post and r["id"] == exclude_post:
            continue
        try:
            persona = _json.loads(r["persona"])
        except (TypeError, _json.JSONDecodeError):
            continue
        if isinstance(persona, dict) and persona.get("name"):
            used.add(PersonaService._surname(persona["name"]))
    return used


def _default_db() -> Path:
    """DB path: $IMPERIAL_DB env override, else backend/imperial.db."""
    env = os.environ.get("IMPERIAL_DB")
    if env:
        return Path(env)
    return BACKEND_ROOT / "imperial.db"


def _llm_available() -> bool:
    """Whether an LLM key is configured (agent network can run)."""
    return bool(
        os.environ.get("IMPERIAL_LLM_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
    )


def _make_llm(model: str | None = None) -> LLMClient:
    """Build a real LLM client from env config (raises if no key)."""
    return LLMClient(model=model, max_tokens=1024, temperature=0.2)


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
    tracker: TaskTracker
    personas: PersonaService
    workflow: WorkflowEngine | None = None
    scheduler: AgentScheduler | None = None

    def make_loop(self, llm: LLMClient | None = None) -> AgentLoop:
        """Build an AgentLoop with the shared tools/engine (llm optional)."""
        return AgentLoop(
            institution=self.institution,
            tools=self.tools,
            llm=llm,  # type: ignore[arg-type]
            engine=self.engine,
        )

    def ensure_personas(self, force: bool = False) -> None:
        """Generate personas for offices that lack one (lazy, idempotent).

        Surnames are accumulated as offices are processed so the court ends
        up with diverse surnames (LLMs otherwise converge on one).
        """
        used: set[str] = set()
        for p in self.institution.posts:
            existing = self.personas.load(p.id)
            if existing is not None and not force:
                used.add(self.personas._surname(existing["name"]))  # noqa: SLF001
                continue
            persona = self.personas.generate(self.institution, p.id, used_surnames=used)
            self.personas.save(p.id, persona)
            used.add(self.personas._surname(persona["name"]))  # noqa: SLF001


def build_context(
    *,
    db_path: Path | str | None = None,
    institution_path: Path | str | None = None,
    seed_posts: bool = True,
    enable_scheduler: bool | None = None,
) -> AppContext:
    storage = Storage(db_path or _default_db())
    institution = load_institution(institution_path or DEFAULT_INSTITUTION)
    engine = RuleEngine(institution)
    bus = Bus(institution, storage, engine)
    personas = PersonaService(storage, llm=_make_llm() if _llm_available() else None)
    appointments = AppointmentService(
        storage,
        persona_regenerator=lambda post_id: personas.generate(
            institution, post_id, used_surnames=_current_surnames(storage, post_id)
        ),
    )
    memorials = MemorialService(storage, bus, institution, engine)
    impeachments = ImpeachmentService(storage, bus, appointments)
    edicts = EdictService(storage, bus)
    tracker = TaskTracker()
    workflow = WorkflowEngine(
        institution=institution, bus=bus, memorials=memorials,
        edicts=edicts, tracker=tracker,
    )
    tools = build_tools(
        bus=bus, storage=storage, memorials=memorials, appointments=appointments,
        tracker=tracker, engine=workflow,
    )

    if seed_posts:
        _seed_posts(storage, institution)

    scheduler: AgentScheduler | None = None
    if enable_scheduler is None:
        enable_scheduler = _llm_available()
    if enable_scheduler:
        loops: dict[str, AgentLoop] = {}

        def loop_factory(post_id: str) -> AgentLoop:
            if post_id not in loops:
                post = institution.post(post_id)
                loops[post_id] = AgentLoop(
                    institution=institution,
                    tools=tools,
                    llm=_make_llm(post.model),
                    engine=engine,
                    max_turns=10,
                )
            return loops[post_id]

        scheduler = AgentScheduler(
            institution=institution, bus=bus, memorials=memorials,
            loop_factory=loop_factory, tracker=tracker, edicts=edicts,
            engine=workflow,
        )

    return AppContext(
        storage=storage, institution=institution, engine=engine, bus=bus,
        appointments=appointments, memorials=memorials, impeachments=impeachments,
        edicts=edicts, tools=tools, tracker=tracker, personas=personas,
        workflow=workflow, scheduler=scheduler,
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
