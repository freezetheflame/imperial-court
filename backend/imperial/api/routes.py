"""REST routes — expose court services to the frontend.

Thin layer: HTTP in, service calls, JSON out. No business logic here.
Pydantic request models keep the API contract explicit (kimi-friendly).
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from imperial.api.bootstrap import AppContext
from imperial.api.events import EventBroadcaster
from imperial.court.edicts import EdictForm
from imperial.court.impeachments import ImpeachmentError
from imperial.court.memorials import MemorialError
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")


# ── request models (API contract) ──────────────────────────
class EdictIn(BaseModel):
    title: str
    task_type: str
    description: str
    target: str | None = None
    constraints: str | None = None
    deadline: str | None = None


class VerdictIn(BaseModel):
    verdict: str
    comment: str | None = None


class ImpeachmentVerdictIn(BaseModel):
    verdict: str  # approve | reject
    comment: str | None = None


class AppointIn(BaseModel):
    agent: str = Field(default="", description="agent id；空则系统自动生成")


# ── dependency ─────────────────────────────────────────────
_ctx_ref: AppContext | None = None
_bc_ref: EventBroadcaster | None = None


def bind(ctx: AppContext, broadcaster: EventBroadcaster) -> None:
    """Attach context + broadcaster to the router (called from main)."""
    global _ctx_ref, _bc_ref
    _ctx_ref = ctx
    _bc_ref = broadcaster


def _ctx() -> AppContext:
    assert _ctx_ref is not None, "router not bound — call bind() first"
    return _ctx_ref


def _bc() -> EventBroadcaster:
    assert _bc_ref is not None, "router not bound — call bind() first"
    return _bc_ref


# ── edicts ─────────────────────────────────────────────────
@router.post("/edicts", status_code=201)
async def create_edict(body: EdictIn) -> dict[str, Any]:
    try:
        form = EdictForm.from_dict(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    result = await _ctx().edicts.issue(form)
    await _bc().broadcast("edict", result)
    return result


@router.get("/edicts")
def list_edicts() -> list[dict[str, Any]]:
    return _ctx().edicts.list()


@router.get("/edicts/{edict_id}")
def get_edict(edict_id: str) -> dict[str, Any]:
    row = _ctx().edicts.get(edict_id)
    if row is None:
        raise HTTPException(404, "edict not found")
    return row


@router.get("/edicts/{edict_id}/progress")
def get_edict_progress(edict_id: str) -> dict[str, Any]:
    """Task progress for an edict (agent network execution status).

    Storage-backed fallback: if the in-memory tracker lost state (restart)
    but the edict is completed or its memorial exists, report done.
    """
    edict = _ctx().edicts.get(edict_id)
    if edict is None:
        raise HTTPException(404, "edict not found")
    snap = _ctx().tracker.snapshot(edict_id)
    assert snap is not None
    # persist/derive completion from durable state
    if snap["stage"] != "done":
        if edict.get("status") == "completed":
            snap["stage"] = "done"
            snap["percent"] = 100
            snap["total"] = snap["total"] or 1
            snap["done"] = snap["done"] or 1
        else:
            mems = _ctx().memorials.list()
            if any(m.get("edict_id") == edict_id for m in mems):
                snap["stage"] = "done"
                snap["percent"] = 100
                snap["total"] = snap["total"] or 1
                snap["done"] = snap["done"] or 1
    return snap


# ── memorials ──────────────────────────────────────────────
@router.get("/memorials")
def list_memorials(status: str | None = None) -> list[dict[str, Any]]:
    return _ctx().memorials.list(status=status)


@router.get("/memorials/{memorial_id}")
def get_memorial(memorial_id: str) -> dict[str, Any]:
    row = _ctx().memorials.get(memorial_id)
    if row is None:
        raise HTTPException(404, "memorial not found")
    return row


@router.post("/memorials/{memorial_id}/verdict")
async def memorial_verdict(memorial_id: str, body: VerdictIn) -> dict[str, Any]:
    try:
        row = await _ctx().memorials.verdict(memorial_id, body.verdict, comment=body.comment)
    except MemorialError as e:
        raise HTTPException(400, str(e)) from e
    await _bc().broadcast("memorial", row)
    return row


# ── impeachments ───────────────────────────────────────────
@router.get("/impeachments")
def list_impeachments(status: str | None = None) -> list[dict[str, Any]]:
    return _ctx().impeachments.list(status=status)


@router.get("/impeachments/{imp_id}")
def get_impeachment(imp_id: str) -> dict[str, Any]:
    row = _ctx().impeachments.get(imp_id)
    if row is None:
        raise HTTPException(404, "impeachment not found")
    return row


@router.post("/impeachments/{imp_id}/verdict")
async def impeachment_verdict(imp_id: str, body: ImpeachmentVerdictIn) -> dict[str, Any]:
    try:
        row = await _ctx().impeachments.verdict(imp_id, body.verdict, comment=body.comment)
    except ImpeachmentError as e:
        raise HTTPException(400, str(e)) from e
    await _bc().broadcast("impeachment", row)
    return row


# ── posts (官职墙) ─────────────────────────────────────────
def _post_with_persona(row: dict[str, Any]) -> dict[str, Any]:
    """Decode the persona JSON column for the frontend."""
    row = dict(row)
    persona = row.get("persona")
    try:
        row["persona"] = json.loads(persona) if persona else None
    except (json.JSONDecodeError, TypeError):
        row["persona"] = None
    return row


@router.get("/posts")
def list_posts() -> list[dict[str, Any]]:
    rows = _ctx().appointments.list_posts(institution_id=_ctx().institution.id)
    return [_post_with_persona(r) for r in rows]


@router.get("/posts/{post_id}")
def get_post(post_id: str) -> dict[str, Any]:
    row = _ctx().appointments.get_post(post_id)
    if row is None:
        raise HTTPException(404, "post not found")
    return _post_with_persona(row)


@router.post("/posts/{post_id}/appoint")
async def appoint(post_id: str, body: AppointIn) -> dict[str, Any]:
    agent = body.agent or f"agent_{post_id}_{len(_ctx().appointments.list_appointments())}"
    try:
        row = _ctx().appointments.appoint(post_id, agent=agent)
    except Exception as e:  # AppointmentError
        raise HTTPException(400, str(e)) from e
    await _bc().broadcast("post_status", row)
    return _post_with_persona(row)


# ── events ─────────────────────────────────────────────────
@router.get("/events")
def list_events(kind: str | None = None, post_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    return _ctx().storage.get_events(kind=kind, post_id=post_id, limit=limit)


# ── censorate ──────────────────────────────────────────────
@router.get("/censorate/overview")
def censorate_overview() -> dict[str, Any]:
    storage = _ctx().storage
    pending = storage.query_one(
        "SELECT COUNT(*) AS n FROM impeachments WHERE status = 'pending'"
    )
    verdicts = storage.query_one(
        "SELECT COUNT(*) AS n FROM impeachments WHERE status = 'pending' AND recommendation IS NOT NULL"
    )
    violations = storage.query_one("SELECT COUNT(*) AS n FROM events WHERE kind = 'violation'")
    warnings = storage.query_one("SELECT COUNT(*) AS n FROM appointments WHERE action = 'warn'")
    removals = storage.query_one("SELECT COUNT(*) AS n FROM appointments WHERE action = 'remove'")
    return {
        "pending_impeachments": pending["n"] if pending else 0,
        "pending_verdicts": verdicts["n"] if verdicts else 0,
        "recent_violations": violations["n"] if violations else 0,
        "warnings_issued": warnings["n"] if warnings else 0,
        "removals": removals["n"] if removals else 0,
    }


@router.get("/censorate/violations")
def censorate_violations(limit: int = 20) -> list[dict[str, Any]]:
    return _ctx().storage.get_events(kind="violation", limit=limit)
